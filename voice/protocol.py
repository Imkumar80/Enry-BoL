import json
from enum import Enum
from pydantic import BaseModel
from typing import Optional, Any

# Client -> Server Messages

class ClientMessageType(str, Enum):
    AUDIO = "audio"
    INTERRUPT = "interrupt"
    TURN_END = "turn_end"

class ClientAudioMessage(BaseModel):
    type: str = ClientMessageType.AUDIO.value
    sequence: int
    data: str # Base64 encoded PCM chunks

class ClientInterruptMessage(BaseModel):
    type: str = ClientMessageType.INTERRUPT.value
    turn_id: str

class ClientTurnEndMessage(BaseModel):
    type: str = ClientMessageType.TURN_END.value
    turn_id: str

# Server -> Client Messages

class ServerMessageType(str, Enum):
    VAD = "vad"
    TRANSCRIPT = "transcript"
    TTS = "tts"
    TTS_END = "tts_end"

class ServerVadMessage(BaseModel):
    type: str = ServerMessageType.VAD.value
    state: str # "speech_start", "speech_end"

class ServerTranscriptMessage(BaseModel):
    type: str = ServerMessageType.TRANSCRIPT.value
    text: str
    final: bool

class ServerTtsMessage(BaseModel):
    type: str = ServerMessageType.TTS.value
    generation_id: str
    data: str # Base64 encoded audio chunk

class ServerTtsEndMessage(BaseModel):
    type: str = ServerMessageType.TTS_END.value
    generation_id: str

def parse_client_message(raw_json: str) -> BaseModel:
    data = json.loads(raw_json)
    msg_type = data.get("type")
    if msg_type == ClientMessageType.AUDIO.value:
        return ClientAudioMessage(**data)
    elif msg_type == ClientMessageType.INTERRUPT.value:
        return ClientInterruptMessage(**data)
    elif msg_type == ClientMessageType.TURN_END.value:
        return ClientTurnEndMessage(**data)
    else:
        raise ValueError(f"Unknown message type: {msg_type}")
