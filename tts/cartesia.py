"""
tts/cartesia.py — Cartesia Sonic TTS Implementation
=====================================================
Uses the Cartesia REST streaming API to generate audio.
Streams audio chunks as they arrive for low latency.
Supports immediate cancellation via generation_id tracking.

Configuration:
  CARTESIA_API_KEY  — required
  CARTESIA_VOICE_ID — optional (defaults to built-in Indian voice)
"""

import os
import json
import base64
import asyncio
import logging
from typing import AsyncGenerator, Set

import httpx
from tts.base import TTSProvider

logger = logging.getLogger("tts.cartesia")


class CartesiaTTS(TTSProvider):
    """
    Cartesia Sonic TTS with streaming and cancellation.
    Uses the REST /tts/bytes endpoint for simplicity and reliability.
    Audio is returned as MP3 and chunked for streaming.
    """

    # Class-level set of cancelled generation IDs
    _cancelled_generations: Set[int] = set()

    def __init__(self):
        self._api_key = os.getenv("CARTESIA_API_KEY", "")
        self._voice_id = os.getenv("CARTESIA_VOICE_ID", "3b554273-4299-48b9-9aaf-eefd438e3941")
        self._url = "https://api.cartesia.ai/tts/bytes"

    async def stream(self, text: str, generation_id: int) -> AsyncGenerator[str, None]:
        """
        Stream TTS audio for the given text.
        Yields base64-encoded MP3 audio chunks.
        """
        if not self._api_key or self._api_key == "your_cartesia_key_here":
            logger.error("Cartesia API key not configured")
            return

        if not text.strip():
            return

        # Clear this generation from cancelled set (fresh start)
        self._cancelled_generations.discard(generation_id)

        payload = {
            "model_id": "sonic",
            "transcript": text,
            "voice": {
                "mode": "id",
                "id": self._voice_id,
            },
            "output_format": {
                "container": "mp3",
                "encoding": "mp3",
                "sample_rate": 44100,
            },
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Cartesia-Version": "2024-06-10",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", self._url, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        logger.error(f"Cartesia error {response.status_code}: {error_body.decode()}")
                        return

                    # Stream chunks as they arrive
                    chunk_size = 4096  # ~4KB chunks for smooth streaming
                    async for chunk in response.aiter_bytes(chunk_size):
                        # Check if this generation was cancelled
                        if generation_id in self._cancelled_generations:
                            logger.info(f"TTS generation {generation_id} cancelled mid-stream")
                            self._cancelled_generations.discard(generation_id)
                            return

                        if chunk:
                            yield base64.b64encode(chunk).decode("utf-8")

        except httpx.TimeoutException:
            logger.error("Cartesia TTS timeout")
        except Exception as e:
            logger.error(f"Cartesia TTS error: {e}", exc_info=True)

    async def cancel(self, generation_id: int):
        """Cancel an active TTS generation. The stream will stop yielding chunks."""
        logger.info(f"Cartesia TTS: Cancel generation {generation_id}")
        self._cancelled_generations.add(generation_id)
