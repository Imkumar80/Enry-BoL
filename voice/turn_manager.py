"""
voice/turn_manager.py — authoritative realtime turn state machine.
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Optional, Callable, Awaitable

from voice.asr import StreamingASR, ASRPartial, ASRFinal, create_asr
from voice.vad import VoiceActivityDetector, VADEvent
from agent.session import set_session_id, reset_session_id
from voice.protocol import (
    ServerVAD, ServerTranscript, ServerAgentState, ServerAgentText,
    ServerTTSStart, ServerTTSChunk, ServerTTSEnd, ServerAction, ServerError,
)

logger = logging.getLogger("turn_manager")


class TurnState(str, Enum):
    IDLE = "IDLE"
    USER_SPEAKING = "USER_SPEAKING"
    END_PENDING = "END_PENDING"
    PROCESSING = "PROCESSING"
    AGENT_SPEAKING = "AGENT_SPEAKING"
    INTERRUPTED = "INTERRUPTED"


class TurnManager:
    def __init__(self, send_fn: Callable[[dict], Awaitable], session_id: str):
        self.send = send_fn
        self.session_id = session_id
        self.state = TurnState.IDLE
        self.turn_id = 0
        self.generation_id = 0

        self.vad = VoiceActivityDetector()
        self.asr: Optional[StreamingASR] = None
        self._processing_task: Optional[asyncio.Task] = None
        self._tts_provider = None
        self._conversation_messages = []
        self._pending_confirmation: Optional[dict] = None
        self._t: dict[str, float] = {}

    def _record(self, key: str):
        self._t[key] = time.perf_counter()

    def _log_turn_telemetry(self):
        t = self._t
        metrics = []
        pairs = [
            ("speech_start", "first_partial", "audio_to_first_asr_partial_ms"),
            ("vad_endpoint", "asr_final", "speech_end_to_final_asr_ms"),
            ("asr_final", "graph_start", "final_asr_to_graph_ms"),
            ("graph_start", "llm_first_token", "graph_to_llm_first_token_ms"),
            ("graph_start", "graph_done", "graph_time_ms"),
            ("tts_request", "tts_first_chunk", "tts_ttfa_ms"),
            ("speech_start", "tts_first_chunk", "total_turn_latency_ms"),
            ("interrupt_start", "tts_cancelled", "tts_cancel_latency_ms"),
        ]
        for a, b, label in pairs:
            if a in t and b in t:
                metrics.append(f"{label}={(t[b]-t[a])*1000:.1f}")
        if metrics:
            logger.info(
                "[Session %s] TURN %s | %s",
                self.session_id[:8], self.turn_id, " | ".join(metrics),
            )

    async def on_audio(self, pcm_data: bytes):
        if not pcm_data:
            return

        events = self.vad.process_audio(pcm_data)

        # A single websocket chunk can contain speech + endpoint silence.
        # Process START first, then deliver the entire chunk to ASR, and only
        # then finalize. This prevents the final chunk from being lost.
        saw_end = False
        for event in events:
            if event == VADEvent.SPEECH_START:
                await self._on_speech_start()
            elif event == VADEvent.SPEECH_END:
                saw_end = True

        if self.asr and self.state in (
            TurnState.USER_SPEAKING, TurnState.END_PENDING
        ):
            await self.asr.push_audio(pcm_data)

        if saw_end:
            await self._on_speech_end()

    async def _on_speech_start(self):
        if self.state in (TurnState.AGENT_SPEAKING, TurnState.PROCESSING):
            await self.on_interrupt()

        if self.state not in (TurnState.IDLE, TurnState.INTERRUPTED):
            return

        self.turn_id += 1
        self._t = {}
        self._record("speech_start")
        self.state = TurnState.USER_SPEAKING

        if self.asr is None:
            self.asr = create_asr()
            await self.asr.start(
                on_partial=self._on_asr_partial,
                on_final=self._on_asr_final,
            )
            else:
                self.asr.begin_turn()
            await self.send(ServerVAD(event="speech_start").model_dump())
            logger.info("Turn %s: speech started", self.turn_id)
        except Exception as exc:
            logger.exception("Failed to start ASR for turn %s", self.turn_id)
            self.asr = None
            self.state = TurnState.IDLE
            await self.send(ServerError(code="ASR_ERROR", message=f"Failed to start ASR: {exc}").model_dump())

    async def _on_speech_end(self):
        if self.state != TurnState.USER_SPEAKING:
            return

        self._record("vad_endpoint")
        self.state = TurnState.END_PENDING
        await self.send(ServerVAD(event="speech_end").model_dump())

        # Short clicks/coughs should not reach the agent.
        if self.vad.last_speech_duration_ms < self.vad.min_speech_ms:
            logger.info("Turn %s: discarded short speech burst (%sms)",
                        self.turn_id, self.vad.last_speech_duration_ms)
            if self.asr:
                await self.asr.cancel()
                self.asr = None
            self.state = TurnState.IDLE
            return

        asr = self.asr
        try:
            result = await asr.end_turn() if hasattr(asr, "end_turn") else (await asr.finish() if asr else None)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Turn %s: ASR finalization failed", self.turn_id)
            result = None

        if not result or not result.text.strip():
            self.state = TurnState.IDLE
            return

        self._record("asr_final")
        await self.send(ServerTranscript(final=True, text=result.text).model_dump())
        self._processing_task = asyncio.create_task(
            self._process_transcript(result.text, self.generation_id)
        )
        try:
            await self._processing_task
        except asyncio.CancelledError:
            logger.info("Turn %s: processing cancelled", self.turn_id)
        finally:
            if self._processing_task and self._processing_task.done():
                self._processing_task = None

    async def _on_asr_partial(self, partial: ASRPartial):
        if "first_partial" not in self._t:
            self._record("first_partial")
        await self.send(ServerTranscript(final=False, text=partial.text).model_dump())

    async def _on_asr_final(self, final: ASRFinal):
        # Deepgram can emit finalized segments before VAD endpointing.
        # They are retained by the ASR implementation; the endpoint remains
        # authoritative for starting agent processing.
        return

    async def on_text_input(self, text: str):
        text = text.strip()
        if not text:
            return
        if self.state in (TurnState.PROCESSING, TurnState.AGENT_SPEAKING):
            await self.on_interrupt()

        self.turn_id += 1
        self._t = {}
        self._record("asr_final")
        await self.send(ServerTranscript(final=True, text=text).model_dump())

        self._processing_task = asyncio.create_task(
            self._process_transcript(text, self.generation_id)
        )
        try:
            await self._processing_task
        except asyncio.CancelledError:
            logger.info("Turn %s: text processing cancelled", self.turn_id)
        finally:
            if self._processing_task and self._processing_task.done():
                self._processing_task = None

    async def force_end_turn(self):
        if self.state == TurnState.USER_SPEAKING:
            await self._on_speech_end()

    async def _process_transcript(self, transcript: str, generation_at_start: int):
        self.state = TurnState.PROCESSING
        await self.send(ServerAgentState(state="processing").model_dump())

        # A stale task must never mutate state or speak.
        if generation_at_start != self.generation_id:
            return

        if self._pending_confirmation:
            outcome = self._parse_confirmation(transcript)
            if outcome == "confirm":
                await self._execute_confirmed_action(generation_at_start)
                return
            if outcome == "cancel":
                self._pending_confirmation = None
                await self._speak_response("Theek hai, cancel kar diya.", generation_at_start)
                return
            # Modification/ambiguous confirmation goes back through the LLM.
            self._pending_confirmation = None

        self._record("graph_start")
        try:
            from agent.graph import process_turn
            token = set_session_id(self.session_id)
            try:
                result = await process_turn(
                    transcript, self._conversation_messages, self._pending_confirmation
                )
            finally:
                reset_session_id(token)
            if generation_at_start != self.generation_id:
                return

            self._record("graph_done")
            response_text = result.get(
                "response_text", "Samajh nahi aaya, dobara boliye."
            )
            action_data = result.get("action_data")
            self._conversation_messages = result.get(
                "messages", self._conversation_messages
            )

            if action_data:
                await self.send(ServerAction(
                    intent=action_data.get("intent", "unknown"),
                    success=action_data.get("success", False),
                    message=action_data.get("message", ""),
                    data=action_data.get("data"),
                ).model_dump())

            self._pending_confirmation = (
                result.get("confirmation_data")
                if result.get("needs_confirmation") else None
            )
            await self._speak_response(response_text, generation_at_start)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Turn %s: processing failed", self.turn_id)
            if generation_at_start == self.generation_id:
                await self.send(ServerError(
                    code="PROCESSING_ERROR", message=str(exc)
                ).model_dump())
                await self._speak_response(
                    "Ek second, request process nahi ho paayi. Phir se try kijiye.",
                    generation_at_start,
                )

    @staticmethod
    def _parse_confirmation(text: str) -> str:
        normalized = " ".join(text.lower().strip().split())
        yes = {"haan", "ha", "haa", "yes", "ok", "okay", "theek", "theek hai",
               "kar do", "karo", "confirm", "ji haan", "hanji"}
        no = {"nahi", "nahin", "no", "cancel", "mat karo", "rehne do", "chhodo"}
        if normalized in yes or normalized in no:
            return "confirm" if normalized in yes else "cancel"
        return "modify"

    async def _execute_confirmed_action(self, generation_at_start: int):
        conf = self._pending_confirmation
        self._pending_confirmation = None
        try:
            from agent.graph import execute_confirmed_action
            token = set_session_id(self.session_id)
            try:
                result = await execute_confirmed_action(conf, self._conversation_messages)
            finally:
                reset_session_id(token)
            if generation_at_start != self.generation_id:
                return
            self._record("graph_done")
            action_data = result.get("action_data")
            if action_data:
                await self.send(ServerAction(
                    intent=action_data.get("intent", "unknown"),
                    success=action_data.get("success", False),
                    message=action_data.get("message", ""),
                    data=action_data.get("data"),
                ).model_dump())
            self._conversation_messages = result.get(
                "messages", self._conversation_messages
            )
            await self._speak_response(
                result.get("response_text", "Ho gaya."), generation_at_start
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Confirmed action failed")
            await self._speak_response("Action fail ho gaya. Please try again.",
                                       generation_at_start)

    async def _speak_response(self, text: str, generation_at_start: int):
        if generation_at_start != self.generation_id:
            return

        self.state = TurnState.AGENT_SPEAKING
        self.generation_id += 1
        gen_id = self.generation_id
        self._record("tts_request")

        await self.send(ServerAgentState(state="speaking").model_dump())
        await self.send(ServerAgentText(text=text).model_dump())
        await self.send(ServerTTSStart(
            generation_id=gen_id,
            encoding="pcm_s16le",
            sample_rate=int(__import__("os").getenv("CARTESIA_SAMPLE_RATE", "24000")),
            channels=1,
        ).model_dump())

        try:
            from tts.cartesia import CartesiaTTS
            self._tts_provider = CartesiaTTS()
            async for chunk_b64 in self._tts_provider.stream(text, gen_id):
                if self.generation_id != gen_id:
                    await self._tts_provider.cancel(gen_id)
                    return
                if "tts_first_chunk" not in self._t:
                    self._record("tts_first_chunk")
                await self.send(ServerTTSChunk(
                    generation_id=gen_id, data=chunk_b64
                ).model_dump())

            if self.generation_id == gen_id:
                await self.send(ServerTTSEnd(generation_id=gen_id).model_dump())
                self.state = TurnState.IDLE
                await self.send(ServerAgentState(state="idle").model_dump())
                self._log_turn_telemetry()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("TTS error")
            if self.generation_id == gen_id:
                await self.send(ServerError(
                    code="TTS_ERROR", message=str(exc)
                ).model_dump())
                self.state = TurnState.IDLE
                await self.send(ServerAgentState(state="idle").model_dump())

    async def on_interrupt(self):
        if self.state not in (
            TurnState.AGENT_SPEAKING, TurnState.PROCESSING
        ):
            return

        self._record("interrupt_start")
        self.generation_id += 1

        if self._tts_provider:
            try:
                await self._tts_provider.cancel(self.generation_id - 1)
            except Exception:
                logger.exception("TTS cancellation failed")
            self._tts_provider = None

        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()

        if self.asr:
            await self.asr.cancel()
            self.asr = None

        self.state = TurnState.INTERRUPTED
        self._record("tts_cancelled")
        await self.send(ServerAgentState(state="idle").model_dump())
        self._log_turn_telemetry()

    async def cleanup(self):
        self.generation_id += 1
        if self._tts_provider:
            try:
                await self._tts_provider.cancel(self.generation_id - 1)
            except Exception:
                pass
        if self.asr:
            await self.asr.cancel()
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
        self.vad.reset()
