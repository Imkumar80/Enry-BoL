import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from voice.protocol import (
    parse_client_message, 
    ClientMessageType, 
    ServerVadMessage,
    ServerTtsMessage
)
from telemetry import telemetry

router = APIRouter()

class VoiceGateway:
    """
    Handles real-time audio state, WebSocket connections, and routes 
    audio frames to the VAD and Turn Manager.
    """
    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        from voice.turn_manager import TurnManager
        self.turn_manager = TurnManager(self.send_message)

    async def handle_connection(self):
        await self.ws.accept()
        print("Voice Gateway: Client connected")
        try:
            while True:
                data = await self.ws.receive_text()
                try:
                    msg = parse_client_message(data)
                except Exception as e:
                    print(f"Failed to parse message: {e}")
                    continue
                
                if msg.type == ClientMessageType.AUDIO.value:
                    # Optional: push to real VAD here. For now we assume client VAD handles interrupt.
                    pass
                elif msg.type == ClientMessageType.INTERRUPT.value:
                    print(f"Gateway received INTERRUPT for turn {msg.turn_id}")
                    await self.turn_manager.on_user_interrupt()
                elif msg.type == ClientMessageType.TURN_END.value:
                    await self.turn_manager.on_speech_end()
                    
        except WebSocketDisconnect:
            print("Voice Gateway: Client disconnected")
        except Exception as e:
            print(f"Voice Gateway Error: {e}")

    async def send_message(self, message: dict):
        """Utility to send events back to the browser."""
        if self.ws.client_state.name == "CONNECTED":
            await self.ws.send_json(message)

@router.websocket("/ws/voice")
async def voice_endpoint(websocket: WebSocket):
    gateway = VoiceGateway(websocket)
    await gateway.handle_connection()
