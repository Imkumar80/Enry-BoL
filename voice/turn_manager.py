"""
voice/turn_manager.py — Server-side Turn State Machine
=======================================================
Authoritative turn management:
  IDLE → USER_SPEAKING → END_PENDING → PROCESSING → AGENT_SPEAKING → IDLE
                                                                    ↓
                                                              INTERRUPTED
                                                                    ↓
                                                            USER_SPEAKING

Responsibilities:
  - Speech start/end detection
  - Endpoint detection
  - Turn creation with unique IDs
  - Generation ID management
  - Interruption / barge-in
  - Cancellation of stale TTS/LLM tasks
"""

import asyncio
import logging
import time
import uuid
from enum import Enum
from typing import Optional, Callable, Awaitable

from voice.asr import StreamingASR, ASRPartial, ASRFinal, create_asr
from voice.vad import VoiceActivityDetector, VADEvent
from voice.protocol import (
    ServerVAD, ServerTranscript, ServerAgentState, ServerAgentText,
    ServerTTSStart, ServerTTSChunk, ServerTTSEnd, ServerAction, ServerError,
)

logger = logging.getLogger("turn_manager")


class TurnState(str, Enum):
    IDLE            = "IDLE"
    USER_SPEAKING   = "USER_SPEAKING"
    END_PENDING     = "END_PENDING"
    PROCESSING      = "PROCESSING"
    AGENT_SPEAKING  = "AGENT_SPEAKING"
    INTERRUPTED     = "INTERRUPTED"


class TurnManager:
    """
    Manages conversational turns.
    Connects VAD → ASR → LangGraph → TTS.
    """

    def __init__(self, send_fn: Callable[[dict], Awaitable], session_id: str):
        self.send = send_fn
        self.session_id = session_id

        # State
        self.state = TurnState.IDLE
        self.turn_id: int = 0
        self.generation_id: int = 0

        # Components (created per session)
        self.vad = VoiceActivityDetector()
        self.asr: Optional[StreamingASR] = None

        # Running tasks
        self._processing_task: Optional[asyncio.Task] = None

        # Telemetry timestamps for current turn
        self._t: dict[str, float] = {}

        # Conversation history for LangGraph
        self._conversation_messages: list = []

        # Pending confirmation state
        self._pending_confirmation: Optional[dict] = None

    def _record(self, event: str):
        self._t[event] = time.time()

    def _log_turn_telemetry(self):
        t = self._t
        metrics = []
        if "speech_start" in t and "vad_endpoint" in t:
            metrics.append(f"speech_duration={(t['vad_endpoint']-t['speech_start'])*1000:.0f}ms")
        if "vad_endpoint" in t and "asr_final" in t:
            metrics.append(f"endpoint_to_asr={(t['asr_final']-t['vad_endpoint'])*1000:.0f}ms")
        if "asr_final" in t and "graph_start" in t:
            metrics.append(f"asr_to_graph={(t['graph_start']-t['asr_final'])*1000:.0f}ms")
        if "graph_start" in t and "graph_done" in t:
            metrics.append(f"graph_time={(t['graph_done']-t['graph_start'])*1000:.0f}ms")
        if "tts_request" in t and "tts_first_chunk" in t:
            metrics.append(f"tts_ttfa={(t['tts_first_chunk']-t['tts_request'])*1000:.0f}ms")
        if "speech_start" in t and "tts_first_chunk" in t:
            metrics.append(f"total_latency={(t['tts_first_chunk']-t['speech_start'])*1000:.0f}ms")
        if "interrupt_start" in t and "tts_cancelled" in t:
            metrics.append(f"barge_in={(t['tts_cancelled']-t['interrupt_start'])*1000:.0f}ms")

        if metrics:
            logger.info(f"[Session {self.session_id[:8]}] TURN {self.turn_id} | {' | '.join(metrics)}")

    # ------------------------------------------------------------------
    # Audio ingestion from gateway
    # ------------------------------------------------------------------

    async def on_audio(self, pcm_data: bytes):
        """Process incoming PCM audio. Called by the gateway for every audio chunk."""
        # Run VAD
        events = self.vad.process_audio(pcm_data)

        for event in events:
            if event == VADEvent.SPEECH_START:
                await self._on_speech_start()
            elif event == VADEvent.SPEECH_END:
                await self._on_speech_end()

        # If user is speaking, push audio to ASR
        if self.state in (TurnState.USER_SPEAKING, TurnState.END_PENDING):
            if self.asr:
                await self.asr.push_audio(pcm_data)

    # ------------------------------------------------------------------
    # VAD-driven state transitions
    # ------------------------------------------------------------------

    async def _on_speech_start(self):
        # If agent is speaking, this is a barge-in
        if self.state == TurnState.AGENT_SPEAKING:
            await self.on_interrupt()

        if self.state in (TurnState.IDLE, TurnState.INTERRUPTED):
            self.turn_id += 1
            self._t = {}
            self._record("speech_start")
            self.state = TurnState.USER_SPEAKING

            # Start ASR
            self.asr = create_asr()
            await self.asr.start(
                on_partial=self._on_asr_partial,
                on_final=self._on_asr_final
            )

            await self.send(ServerVAD(event="speech_start").model_dump())
            logger.info(f"Turn {self.turn_id}: Speech started")

    async def _on_speech_end(self):
        if self.state == TurnState.USER_SPEAKING:
            self._record("vad_endpoint")
            self.state = TurnState.END_PENDING
            await self.send(ServerVAD(event="speech_end").model_dump())
            logger.info(f"Turn {self.turn_id}: Endpoint detected")

            # Finalize ASR
            if self.asr:
                result = await self.asr.finish()
                if result and result.text.strip():
                    self._record("asr_final")
                    await self.send(ServerTranscript(final=True, text=result.text).model_dump())
                    await self._process_transcript(result.text)
                else:
                    logger.info(f"Turn {self.turn_id}: Empty transcript, returning to IDLE")
                    self.state = TurnState.IDLE

    # ------------------------------------------------------------------
    # ASR callbacks
    # ------------------------------------------------------------------

    async def _on_asr_partial(self, partial: ASRPartial):
        if "first_partial" not in self._t:
            self._record("first_partial")
        await self.send(ServerTranscript(final=False, text=partial.text).model_dump())

    async def _on_asr_final(self, final: ASRFinal):
        """Called by Deepgram's interim final results. The true final is from finish()."""
        pass  # We use the finish() flow for endpoint-based turns

    # ------------------------------------------------------------------
    # Text input (from dashboard typed commands)
    # ------------------------------------------------------------------

    async def on_text_input(self, text: str):
        """Process a typed text command, bypassing VAD/ASR."""
        self.turn_id += 1
        self._t = {}
        self._record("asr_final")
        await self.send(ServerTranscript(final=True, text=text).model_dump())
        await self._process_transcript(text)

    # ------------------------------------------------------------------
    # Transcript → LangGraph processing
    # ------------------------------------------------------------------

    async def _process_transcript(self, transcript: str):
        self.state = TurnState.PROCESSING
        await self.send(ServerAgentState(state="processing").model_dump())

        # Check if this is a confirmation response
        if self._pending_confirmation:
            affirmative = transcript.lower().strip()
            yes_words = {"haan", "ha", "haa", "yes", "ok", "theek hai", "theek", "kar do",
                         "karo", "sahi hai", "confirm", "yes please", "ji", "ji haan", "hanji"}
            if any(w in affirmative for w in yes_words):
                # Execute the pending action
                await self._execute_confirmed_action()
                return
            else:
                # Cancel the pending action
                self._pending_confirmation = None
                response_text = "Theek hai, cancel kar diya."
                await self._speak_response(response_text)
                return

        self._record("graph_start")

        try:
            # Import here to avoid circular imports at module level
            from agent.graph import process_turn
            result = await process_turn(transcript, self._conversation_messages, self._pending_confirmation)
            self._record("graph_done")

            response_text = result.get("response_text", "Samajh nahi aaya, dobara boliye.")
            action_data = result.get("action_data")
            needs_confirmation = result.get("needs_confirmation", False)
            self._conversation_messages = result.get("messages", self._conversation_messages)

            # Send action data for UI updates (cart, customer selection, etc.)
            if action_data:
                await self.send(ServerAction(
                    intent=action_data.get("intent", "unknown"),
                    success=action_data.get("success", False),
                    message=action_data.get("message", ""),
                    data=action_data.get("data"),
                ).model_dump())

            if needs_confirmation:
                self._pending_confirmation = result.get("confirmation_data")

            # Speak the response
            await self._speak_response(response_text)

        except Exception as e:
            logger.error(f"Turn {self.turn_id}: Processing error: {e}", exc_info=True)
            error_text = "Ek second, request process nahi ho paayi. Phir se try kijiye."
            await self.send(ServerError(code="PROCESSING_ERROR", message=str(e)).model_dump())
            await self._speak_response(error_text)

    async def _execute_confirmed_action(self):
        """Execute a previously confirmed financial action."""
        conf = self._pending_confirmation
        self._pending_confirmation = None

        try:
            from agent.graph import execute_confirmed_action
            result = await execute_confirmed_action(conf, self._conversation_messages)
            self._record("graph_done")

            response_text = result.get("response_text", "Ho gaya.")
            action_data = result.get("action_data")
            self._conversation_messages = result.get("messages", self._conversation_messages)

            if action_data:
                await self.send(ServerAction(
                    intent=action_data.get("intent", "unknown"),
                    success=action_data.get("success", False),
                    message=action_data.get("message", ""),
                    data=action_data.get("data"),
                ).model_dump())

            await self._speak_response(response_text)
        except Exception as e:
            logger.error(f"Confirmed action error: {e}", exc_info=True)
            await self._speak_response("Action fail ho gaya. Please try again.")

    # ------------------------------------------------------------------
    # TTS response
    # ------------------------------------------------------------------

    async def _speak_response(self, text: str):
        self.state = TurnState.AGENT_SPEAKING
        self.generation_id += 1
        gen_id = self.generation_id
        self._record("tts_request")

        await self.send(ServerAgentState(state="speaking").model_dump())
        await self.send(ServerAgentText(text=text).model_dump())
        await self.send(ServerTTSStart(generation_id=gen_id).model_dump())

        first_chunk = True
        try:
            from tts.cartesia import CartesiaTTS
            tts = CartesiaTTS()

            async for chunk_b64 in tts.stream(text, gen_id):
                # Check if this generation has been invalidated (barge-in)
                if self.generation_id != gen_id:
                    logger.info(f"TTS generation {gen_id} invalidated, stopping stream")
                    await tts.cancel(gen_id)
                    break

                if first_chunk:
                    self._record("tts_first_chunk")
                    first_chunk = False

                await self.send(ServerTTSChunk(generation_id=gen_id, data=chunk_b64).model_dump())

        except Exception as e:
            logger.error(f"TTS error: {e}", exc_info=True)
            await self.send(ServerError(code="TTS_ERROR", message=str(e)).model_dump())

        # Only send TTS_END if this generation is still active
        if self.generation_id == gen_id:
            await self.send(ServerTTSEnd(generation_id=gen_id).model_dump())
            self.state = TurnState.IDLE
            await self.send(ServerAgentState(state="idle").model_dump())
            self._log_turn_telemetry()

    # ------------------------------------------------------------------
    # Interruption / barge-in
    # ------------------------------------------------------------------

    async def on_interrupt(self):
        """Handle barge-in: cancel TTS, invalidate generation, transition to user speaking."""
        if self.state not in (TurnState.AGENT_SPEAKING, TurnState.PROCESSING):
            return

        self._record("interrupt_start")
        logger.info(f"Turn {self.turn_id}: BARGE-IN! Cancelling generation {self.generation_id}")

        prev_gen = self.generation_id
        self.generation_id += 1  # Invalidate the current generation
        self.state = TurnState.INTERRUPTED

        # Cancel any running processing task
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
            self._processing_task = None

        # Cancel ASR if running
        if self.asr:
            await self.asr.cancel()
            self.asr = None

        self._record("tts_cancelled")
        await self.send(ServerAgentState(state="idle").model_dump())
        self._log_turn_telemetry()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup(self):
        """Clean up resources when the session ends."""
        if self.asr:
            await self.asr.cancel()
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
        self.vad.reset()
        logger.info(f"Session {self.session_id[:8]} cleaned up")
