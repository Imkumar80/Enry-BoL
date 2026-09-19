"""
tts/cartesia.py — Cartesia Sonic realtime TTS provider.

Uses the official Cartesia Python SDK's async WebSocket context API.
Audio is emitted as raw PCM16 base64 chunks for browser playback.
"""

import os
import base64
import asyncio
import logging
from typing import AsyncGenerator

from tts.base import TTSProvider

logger = logging.getLogger("tts.cartesia")


class CartesiaTTS(TTSProvider):
    def __init__(self):
        self._api_key = os.getenv("CARTESIA_API_KEY", "")
        self._voice_id = os.getenv(
            "CARTESIA_VOICE_ID",
            "6ccbfb76-1fc6-48b9-9aaf-eefd438e3941",
        )
        self._model_id = os.getenv("CARTESIA_MODEL_ID", "sonic-latest")
        self._sample_rate = int(os.getenv("CARTESIA_SAMPLE_RATE", "44100"))
        self._language = os.getenv("CARTESIA_LANGUAGE", "en")
        self._cancelled: set[int] = set()

    async def stream(self, text: str, generation_id: int) -> AsyncGenerator[str, None]:
        if not self._api_key:
            raise EnvironmentError("CARTESIA_API_KEY not set")
        if not text.strip():
            return

        from cartesia import AsyncCartesia

        self._cancelled.discard(generation_id)
        client = AsyncCartesia(api_key=self._api_key)

        try:
            audio_stream = await client.tts.sse(
                model_id=self._model_id,
                transcript=text,
                voice={"mode": "id", "id": self._voice_id},
                output_format={
                    "container": "raw",
                    "encoding": "pcm_s16le",
                    "sample_rate": self._sample_rate,
                },
                language=self._language,
            )

            async for chunk in audio_stream:
                if generation_id in self._cancelled:
                    return
                if hasattr(chunk, 'audio') and chunk.audio:
                    yield base64.b64encode(chunk.audio).decode("utf-8")
                elif getattr(chunk, 'type', None) == "error":
                    raise RuntimeError(
                        getattr(chunk, 'message', None) or getattr(chunk, 'title', None) or "Cartesia TTS error"
                    )
        except asyncio.CancelledError:
            raise
        finally:
            self._cancelled.discard(generation_id)
            await client.close()

    async def cancel(self, generation_id: int):
        # The TurnManager cancels the owning processing task as well, which
        # closes the async websocket context. This flag also prevents already
        # queued chunks from being emitted.
        self._cancelled.add(generation_id)
