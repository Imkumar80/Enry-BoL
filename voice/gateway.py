"""
voice/gateway.py — WebSocket Voice Gateway.
"""

import asyncio
import base64
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from voice.protocol import ClientMessageType, ServerError, parse_client_message
from voice.turn_manager import TurnManager

logger = logging.getLogger("voice_gateway")
router = APIRouter()


class VoiceGateway:
    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        self.session_id = str(uuid.uuid4())
        self.turn_manager = TurnManager(self._send_message, self.session_id)
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=150)
        self._audio_worker_task = None
        self._closed = False

    async def _send_message(self, message: dict):
        if self._closed:
            return
        try:
            await self.ws.send_json(message)
        except Exception as exc:
            logger.warning("[%s] Send failed: %s", self.session_id[:8], exc)

    async def _audio_worker(self):
        while not self._closed:
            try:
                pcm = await self._audio_queue.get()
                try:
                    await self.turn_manager.on_audio(pcm)
                except Exception as exc:
                    logger.exception("[%s] Turn manager on_audio failed: %s", self.session_id[:8], exc)
                    await self._send_message(ServerError(
                        code="AUDIO_PROCESS_ERROR", message=f"Audio processing failed: {exc}"
                    ).model_dump())
                finally:
                    self._audio_queue.task_done()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("[%s] Audio worker iteration failed: %s", self.session_id[:8], exc)

    async def handle_connection(self):
        await self.ws.accept()
        self._audio_worker_task = asyncio.create_task(self._audio_worker())
        logger.info("Voice session started: %s", self.session_id[:8])

        try:
            while True:
                raw = await self.ws.receive_text()
                try:
                    data = parse_client_message(raw)
                except ValueError as exc:
                    await self._send_message(ServerError(
                        code="INVALID_MESSAGE", message=str(exc)
                    ).model_dump())
                    continue

                msg_type = data["type"]

                if msg_type == ClientMessageType.AUDIO_CHUNK.value:
                    try:
                        pcm = base64.b64decode(data["data"], validate=True)
                        # Never let the browser block forever behind a slow ASR/TTS path.
                        try:
                            self._audio_queue.put_nowait(pcm)
                        except asyncio.QueueFull:
                            await self._send_message(ServerError(
                                code="AUDIO_BACKPRESSURE",
                                message="Audio queue full; dropping oldest audio frame."
                            ).model_dump())
                            try:
                                self._audio_queue.get_nowait()
                                self._audio_queue.task_done()
                            except asyncio.QueueEmpty:
                                pass
                            self._audio_queue.put_nowait(pcm)
                    except Exception as exc:
                        await self._send_message(ServerError(
                            code="AUDIO_ERROR", message=str(exc)
                        ).model_dump())

                elif msg_type == ClientMessageType.INTERRUPT.value:
                    await self.turn_manager.on_interrupt()

                elif msg_type == ClientMessageType.TURN_END.value:
                    await self.turn_manager.force_end_turn()

                elif msg_type == ClientMessageType.TEXT_INPUT.value:
                    await self.turn_manager.on_text_input(data["text"].strip())

        except WebSocketDisconnect:
            logger.info("Voice session disconnected: %s", self.session_id[:8])
        except Exception:
            logger.exception("Voice gateway error: %s", self.session_id[:8])
        finally:
            self._closed = True
            if self._audio_worker_task:
                self._audio_worker_task.cancel()
                try:
                    await self._audio_worker_task
                except asyncio.CancelledError:
                    pass
            await self.turn_manager.cleanup()
            logger.info("Voice session ended: %s", self.session_id[:8])


@router.websocket("/ws/voice")
async def voice_endpoint(websocket: WebSocket):
    await VoiceGateway(websocket).handle_connection()
