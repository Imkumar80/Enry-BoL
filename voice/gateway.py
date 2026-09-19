"""
voice/gateway.py — WebSocket Voice Gateway
============================================
Accepts browser WebSocket connections at /ws/voice.
Orchestrates:
  - PCM audio reception
  - Routing to TurnManager (which owns VAD → ASR → LangGraph → TTS)
  - Session lifecycle
  - Client message parsing
  - Error handling and reconnection support
"""

import asyncio
import base64
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from voice.protocol import (
    ClientMessageType,
    ServerError,
    parse_client_message,
)
from voice.turn_manager import TurnManager

logger = logging.getLogger("voice_gateway")

router = APIRouter()


class VoiceGateway:
    """
    Manages a single WebSocket voice session.
    Routes audio to TurnManager and sends responses back to the browser.
    """

    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        self.session_id = str(uuid.uuid4())
        self.turn_manager = TurnManager(
            send_fn=self._send_message,
            session_id=self.session_id,
        )

    async def _send_message(self, message: dict):
        """Send a JSON message to the browser. Silently ignores if disconnected."""
        try:
            await self.ws.send_json(message)
        except Exception as e:
            logger.warning(f"[{self.session_id[:8]}] Send failed: {e}")

    async def handle_connection(self):
        await self.ws.accept()
        logger.info(f"Voice session started: {self.session_id[:8]}")

        try:
            while True:
                raw = await self.ws.receive_text()
                try:
                    data = parse_client_message(raw)
                except ValueError as e:
                    logger.warning(f"Bad message: {e}")
                    await self._send_message(
                        ServerError(code="INVALID_MESSAGE", message=str(e)).model_dump()
                    )
                    continue

                msg_type = data.get("type")

                if msg_type == ClientMessageType.AUDIO_CHUNK.value:
                    # Decode base64 PCM and feed to turn manager
                    try:
                        pcm_bytes = base64.b64decode(data["data"])
                        await self.turn_manager.on_audio(pcm_bytes)
                    except Exception as e:
                        logger.error(f"Audio processing error: {e}")

                elif msg_type == ClientMessageType.INTERRUPT.value:
                    logger.info(f"[{self.session_id[:8]}] Client interrupt received")
                    await self.turn_manager.on_interrupt()

                elif msg_type == ClientMessageType.TURN_END.value:
                    # Explicit turn end from client (e.g., user pressed a button)
                    if self.turn_manager.state.value == "USER_SPEAKING":
                        await self.turn_manager._on_speech_end()

                elif msg_type == ClientMessageType.TEXT_INPUT.value:
                    text = data.get("text", "").strip()
                    if text:
                        logger.info(f"[{self.session_id[:8]}] Text input: {text}")
                        await self.turn_manager.on_text_input(text)

        except WebSocketDisconnect:
            logger.info(f"Voice session disconnected: {self.session_id[:8]}")
        except Exception as e:
            logger.error(f"Voice gateway error: {e}", exc_info=True)
        finally:
            await self.turn_manager.cleanup()
            logger.info(f"Voice session ended: {self.session_id[:8]}")


@router.websocket("/ws/voice")
async def voice_endpoint(websocket: WebSocket):
    """WebSocket endpoint for the Enry voice pipeline."""
    gateway = VoiceGateway(websocket)
    await gateway.handle_connection()
