"""
voice/asr.py — streaming ASR abstraction.
"""

import os
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("asr")


@dataclass
class ASRPartial:
    text: str


@dataclass
class ASRFinal:
    text: str


class StreamingASR(ABC):
    @abstractmethod
    async def start(self, on_partial: Optional[Callable[[ASRPartial], Awaitable]] = None,
                    on_final: Optional[Callable[[ASRFinal], Awaitable]] = None): ...
    @abstractmethod
    async def push_audio(self, pcm_data: bytes): ...
    @abstractmethod
    async def finish(self) -> Optional[ASRFinal]: ...
    @abstractmethod
    async def cancel(self): ...


class DeepgramStreamingASR(StreamingASR):
    """Deepgram realtime ASR. Language/model are fully environment-configurable."""

    def __init__(self):
        self._api_key = os.getenv("DEEPGRAM_API_KEY", "")
        self._connection = None
        self._on_partial = None
        self._on_final = None
        self._is_running = False
        self._accumulated_text = ""
        self._final_received = asyncio.Event()
        self._last_final: Optional[ASRFinal] = None
        self._turn_started = False

    async def start(self, on_partial=None, on_final=None):
        if not self._api_key:
            raise EnvironmentError("DEEPGRAM_API_KEY not set")

        from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions

        self._on_partial = on_partial
        self._on_final = on_final
        self._is_running = True
        self._accumulated_text = ""
        self._last_final = None
        self._final_received = asyncio.Event()

        self._client = DeepgramClient(self._api_key)
        self._connection = self._client.listen.asyncwebsocket.v("1")

        async def on_message(conn, result, **kwargs):
            try:
                alt = result.channel.alternatives[0]
                transcript = (alt.transcript or "").strip()
                logger.info("Deepgram is_final=%s transcript='%s'", result.is_final, transcript)
                if not transcript:
                    return

                if result.is_final:
                    # Deepgram's final transcript is a segment/delta. Append it
                    # once; don't treat every interim result as a new segment.
                    self._accumulated_text = (
                        f"{self._accumulated_text} {transcript}".strip()
                    )
                    self._last_final = ASRFinal(self._accumulated_text)
                    self._final_received.set()
                    if self._on_final:
                        await self._on_final(self._last_final)
                elif self._on_partial:
                    partial = f"{self._accumulated_text} {transcript}".strip()
                    await self._on_partial(ASRPartial(partial))
            except Exception:
                logger.exception("Deepgram transcript callback failed")

        async def on_error(conn, error, **kwargs):
            logger.error("Deepgram error: %s", error)

        self._connection.on(LiveTranscriptionEvents.Transcript, on_message)
        self._connection.on(LiveTranscriptionEvents.Error, on_error)

        model = "nova-3"
        language = "kn"
        options = LiveOptions(
            model=model,
            language=language,
            encoding="linear16",
            sample_rate=16000,
            channels=1,
            interim_results=True,
        )

        if not await self._connection.start(options):
            self._connection = None
            self._is_running = False
            raise RuntimeError("Failed to start Deepgram connection")

        logger.info("Deepgram started: model=%s language=%s", model, language)

    def begin_turn(self):
        self._accumulated_text = ""
        self._last_final = None
        self._final_received = asyncio.Event()
        self._turn_started = True

    async def end_turn(self) -> Optional[ASRFinal]:
        if not self._is_running:
            return self._last_final
        try:
            await asyncio.wait_for(self._final_received.wait(), timeout=0.35)
        except asyncio.TimeoutError:
            pass
        result = self._last_final
        self._turn_started = False
        return result

    async def push_audio(self, pcm_data: bytes):
        if self._is_running and self._connection:
            await self._connection.send(pcm_data)

    async def finish(self) -> Optional[ASRFinal]:
        if not self._connection:
            return self._last_final
        connection = self._connection
        self._connection = None
        self._is_running = False
        try:
            await connection.finish()
        except Exception:
            logger.exception("Deepgram finish failed")
        return self._last_final

    async def cancel(self):
        self._is_running = False
        connection, self._connection = self._connection, None
        if connection:
            try:
                await connection.finish()
            except Exception:
                pass
        self._accumulated_text = ""
        self._last_final = None


class LocalWhisperASR(StreamingASR):
    """Batch fallback; intentionally not marketed as streaming."""

    def __init__(self):
        self._model = None
        self._audio_buffer = bytearray()
        self._is_running = False
        self._on_final = None

    def _ensure_model(self):
        from faster_whisper import WhisperModel
        size = os.getenv("WHISPER_MODEL_SIZE", "base")
        device = os.getenv("WHISPER_DEVICE", "cpu")
        compute = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        self._model = self._model or WhisperModel(size, device=device, compute_type=compute)

    async def start(self, on_partial=None, on_final=None):
        self._ensure_model()
        self._audio_buffer = bytearray()
        self._is_running = True
        self._on_final = on_final

    async def push_audio(self, pcm_data: bytes):
        if self._is_running:
            self._audio_buffer.extend(pcm_data)

    async def finish(self) -> Optional[ASRFinal]:
        if not self._is_running:
            return None
        self._is_running = False
        if len(self._audio_buffer) < 3200:
            return None
        import numpy as np
        audio = np.frombuffer(bytes(self._audio_buffer), dtype=np.int16).astype(np.float32) / 32768.0
        try:
            segments, _ = self._model.transcribe(
                audio, beam_size=3,
                language=os.getenv("WHISPER_LANGUAGE", "hi"),
                vad_filter=True,
            )
            text = " ".join(seg.text for seg in segments).strip()
            result = ASRFinal(text) if text else None
            if result and self._on_final:
                await self._on_final(result)
            return result
        except Exception:
            logger.exception("Local Whisper transcription failed")
            return None

    async def cancel(self):
        self._is_running = False
        self._audio_buffer.clear()


def create_asr() -> StreamingASR:
    provider = os.getenv("ASR_PROVIDER", "deepgram").lower()
    if provider == "local":
        return LocalWhisperASR()
    return DeepgramStreamingASR()
