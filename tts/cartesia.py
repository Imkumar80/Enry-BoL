"""
tts/cartesia.py — Cartesia Sonic realtime TTS provider.

Uses Cartesia's realtime WebSocket API when available. The server emits raw
PCM16 audio so the browser can play chunks without trying to decode arbitrary
MP3 fragments.
"""

import os
import asyncio
import base64
import json
import logging
from typing import AsyncGenerator

import websockets

from tts.base import TTSProvider

logger = logging.getLogger("tts.cartesia")


class CartesiaTTS(TTSProvider):
    def __init__(self):
        self._api_key = os.getenv("CARTESIA_API_KEY", "")
        self._voice_id = os.getenv(
            "CARTESIA_VOICE_ID",
            "3b554273-4299-48b9-9aaf-eefd438e3941",
        )
        self._model_id = os.getenv("CARTESIA_MODEL_ID", "sonic-3")
        self._sample_rate = int(os.getenv("CARTESIA_SAMPLE_RATE", "24000"))
        self._active: dict[int, asyncio.Event] = {}

    async def stream(self, text: str, generation_id: int) -> AsyncGenerator[str, None]:
        if not self._api_key:
            raise EnvironmentError("CARTESIA_API_KEY not set")
        if not text.strip():
            return

        cancelled = asyncio.Event()
        self._active[generation_id] = cancelled

        # Cartesia's realtime websocket protocol may evolve; keep all wire
        # details in this provider so the rest of the voice pipeline stays
        # provider-agnostic.
        uri = "wss://api.cartesia.ai/tts/websocket"
        headers = {
            "X-API-Key": self._api_key,
            "Cartesia-Version": os.getenv("CARTESIA_VERSION", "2025-04-16"),
        }

        try:
            async with websockets.connect(
                uri,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=1,
                max_size=4 * 1024 * 1024,
            ) as ws:
                await ws.send(json.dumps({
                    "model_id": self._model_id,
                    "transcript": text,
                    "voice": {"mode": "id", "id": self._voice_id},
                    "output_format": {
                        "container": "raw",
                        "encoding": "pcm_s16le",
                        "sample_rate": self._sample_rate,
                    },
                    "context_id": str(generation_id),
                }))

                async for raw in ws:
                    if cancelled.is_set():
                        return

                    if isinstance(raw, bytes):
                        if raw:
                            yield base64.b64encode(raw).decode("ascii")
                        continue

                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    # Realtime responses commonly carry audio as base64 in
                    # a data/audio field. End events are provider-specific.
                    audio = message.get("data") or message.get("audio")
                    if audio:
                        if isinstance(audio, str):
                            yield audio
                        else:
                            yield base64.b64encode(audio).decode("ascii")

                    msg_type = str(message.get("type", "")).lower()
                    if msg_type in {"done", "complete", "flush_done", "error"}:
                        if msg_type == "error":
                            raise RuntimeError(str(message.get("error") or message))
                        return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Cartesia realtime TTS failed")
            raise
        finally:
            self._active.pop(generation_id, None)

    async def cancel(self, generation_id: int):
        event = self._active.get(generation_id)
        if event:
            event.set()


