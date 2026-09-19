"""
voice/asr.py — Streaming ASR Abstraction & Implementations
============================================================
Provides:
  - StreamingASR          (abstract base)
  - DeepgramStreamingASR  (cloud, primary)
  - LocalWhisperASR       (local, fallback)

Select via ASR_PROVIDER env var: "deepgram" | "local"
"""

import os
import asyncio
import base64
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("asr")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ASRPartial:
    text: str

@dataclass
class ASRFinal:
    text: str


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class StreamingASR(ABC):
    """
    Push-based streaming ASR.
    Callers push audio chunks and receive partial/final transcripts via callback.
    """

    @abstractmethod
    async def start(self, on_partial: Optional[Callable[[ASRPartial], Awaitable]] = None,
                    on_final: Optional[Callable[[ASRFinal], Awaitable]] = None):
        ...

    @abstractmethod
    async def push_audio(self, pcm_data: bytes):
        ...

    @abstractmethod
    async def finish(self) -> Optional[ASRFinal]:
        ...

    @abstractmethod
    async def cancel(self):
        ...


# ---------------------------------------------------------------------------
# Deepgram Streaming ASR
# ---------------------------------------------------------------------------

class DeepgramStreamingASR(StreamingASR):
    """
    Uses Deepgram's live streaming WebSocket API for real-time transcription.
    Supports Kannada (kn), Hindi (hi), English (en) via multi-language or
    the nova-2 model with language detection.
    """

    def __init__(self):
        self._api_key = os.getenv("DEEPGRAM_API_KEY", "")
        self._connection = None
        self._on_partial: Optional[Callable] = None
        self._on_final: Optional[Callable] = None
        self._is_running = False
        self._accumulated_text = ""
        self._client = None
        self._final_received = asyncio.Event()

    async def start(self, on_partial=None, on_final=None):
        if not self._api_key:
            raise EnvironmentError("DEEPGRAM_API_KEY not set")

        self._on_partial = on_partial
        self._on_final = on_final
        self._is_running = True
        self._accumulated_text = ""
        self._final_received = asyncio.Event()

        try:
            from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions

            self._client = DeepgramClient(self._api_key)
            self._connection = self._client.listen.asyncwebsocket.v("1")

            # Wire up event handlers
            async def on_message(conn, result, **kwargs):
                try:
                    alt = result.channel.alternatives[0]
                    transcript = alt.transcript
                    if not transcript:
                        return

                    is_final = result.is_final

                    if is_final:
                        self._accumulated_text += (" " + transcript if self._accumulated_text else transcript)
                        if self._on_final:
                            await self._on_final(ASRFinal(text=self._accumulated_text.strip()))
                    else:
                        partial_text = (self._accumulated_text + " " + transcript).strip()
                        if self._on_partial:
                            await self._on_partial(ASRPartial(text=partial_text))
                except Exception as e:
                    logger.error(f"Deepgram message handler error: {e}")

            async def on_error(conn, error, **kwargs):
                logger.error(f"Deepgram error: {error}")

            self._connection.on(LiveTranscriptionEvents.Transcript, on_message)
            self._connection.on(LiveTranscriptionEvents.Error, on_error)

            options = LiveOptions(
                model="nova-3",
                language="hi",           # Hindi primary, handles code-mixed
                encoding="linear16",
                sample_rate=16000,
                channels=1,
                interim_results=True,
                utterance_end_ms="1000",
                vad_events=False,
                smart_format=True,
            )

            if not await self._connection.start(options):
                raise RuntimeError("Failed to start Deepgram connection")

            logger.info("Deepgram ASR started")
        except Exception as e:
            logger.error(f"Deepgram ASR start failed: {e}")
            self._is_running = False
            raise

    async def push_audio(self, pcm_data: bytes):
        if not self._is_running or not self._connection:
            return
        try:
            await self._connection.send(pcm_data)
        except Exception as e:
            logger.error(f"Deepgram send error: {e}")

    async def finish(self) -> Optional[ASRFinal]:
        if not self._is_running or not self._connection:
            return ASRFinal(text=self._accumulated_text.strip()) if self._accumulated_text else None
        self._is_running = False
        try:
            await self._connection.finish()
            logger.info("Deepgram ASR finished")
        except Exception as e:
            logger.error(f"Deepgram finish error: {e}")
        self._connection = None
        return ASRFinal(text=self._accumulated_text.strip()) if self._accumulated_text else None

    async def cancel(self):
        self._is_running = False
        if self._connection:
            try:
                await self._connection.finish()
            except Exception:
                pass
            self._connection = None
        self._accumulated_text = ""
        logger.info("Deepgram ASR cancelled")


# ---------------------------------------------------------------------------
# Local Whisper ASR (fallback)
# ---------------------------------------------------------------------------

class LocalWhisperASR(StreamingASR):
    """
    Offline ASR using faster-whisper.
    Accumulates audio until finish() is called, then transcribes.
    Partial transcripts are not available (batch mode).
    """

    def __init__(self):
        self._model = None
        self._audio_buffer = bytearray()
        self._is_running = False
        self._on_partial = None
        self._on_final = None

    def _ensure_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                model_size = os.getenv("WHISPER_MODEL_SIZE", "base")
                self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
                logger.info(f"Loaded faster-whisper model: {model_size}")
            except ImportError:
                logger.error("faster-whisper not installed. Install with: pip install faster-whisper")
                raise

    async def start(self, on_partial=None, on_final=None):
        self._ensure_model()
        self._audio_buffer = bytearray()
        self._is_running = True
        self._on_partial = on_partial
        self._on_final = on_final
        logger.info("Local Whisper ASR started")

    async def push_audio(self, pcm_data: bytes):
        if self._is_running:
            self._audio_buffer.extend(pcm_data)

    async def finish(self) -> Optional[ASRFinal]:
        if not self._is_running:
            return None
        self._is_running = False

        if len(self._audio_buffer) < 3200:  # Less than 0.1s of audio
            return None

        try:
            import numpy as np
            # Convert PCM s16le to float32
            audio_int16 = np.frombuffer(bytes(self._audio_buffer), dtype=np.int16)
            audio_float = audio_int16.astype(np.float32) / 32768.0

            segments, info = self._model.transcribe(
                audio_float,
                beam_size=3,
                language="hi",
                vad_filter=True,
            )
            text = " ".join(seg.text for seg in segments).strip()
            logger.info(f"Local Whisper result: '{text}'")

            if text and self._on_final:
                result = ASRFinal(text=text)
                await self._on_final(result)
                return result
            return ASRFinal(text=text) if text else None
        except Exception as e:
            logger.error(f"Local Whisper transcription error: {e}")
            return None

    async def cancel(self):
        self._is_running = False
        self._audio_buffer = bytearray()
        logger.info("Local Whisper ASR cancelled")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_asr() -> StreamingASR:
    """Create an ASR instance based on ASR_PROVIDER env var."""
    provider = os.getenv("ASR_PROVIDER", "deepgram").lower()
    if provider == "deepgram":
        return DeepgramStreamingASR()
    elif provider == "local":
        return LocalWhisperASR()
    else:
        logger.warning(f"Unknown ASR_PROVIDER '{provider}', falling back to deepgram")
        return DeepgramStreamingASR()
