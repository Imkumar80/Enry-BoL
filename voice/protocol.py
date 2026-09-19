"""
voice/protocol.py — WebSocket protocol for Enry Voice OS.
"""

import base64
import json
from enum import Enum
from pydantic import BaseModel, Field, field_validator
from typing import Optional

PROTOCOL_VERSION = "1.1"


class ClientMessageType(str, Enum):
    AUDIO_CHUNK = "audio_chunk"
    INTERRUPT = "interrupt"
    TURN_END = "turn_end"
    TEXT_INPUT = "text_input"


class ClientAudioChunk(BaseModel):
    type: str = ClientMessageType.AUDIO_CHUNK.value
    sequence: int = Field(ge=0)
    sample_rate: int = 16000
    encoding: str = "pcm_s16le"
    data: str = Field(min_length=1)

    @field_validator("sample_rate")
    @classmethod
    def validate_rate(cls, value):
        if value != 16000:
            raise ValueError("Only 16 kHz audio is supported")
        return value

    @field_validator("encoding")
    @classmethod
    def validate_encoding(cls, value):
        if value != "pcm_s16le":
            raise ValueError("Only pcm_s16le audio is supported")
        return value

    @field_validator("data")
    @classmethod
    def validate_base64_pcm(cls, value):
        try:
            raw = base64.b64decode(value, validate=True)
        except Exception as exc:
            raise ValueError("Invalid base64 audio") from exc
        if not raw or len(raw) % 2:
            raise ValueError("PCM payload must contain an even number of bytes")
        # Prevent accidental multi-megabyte websocket frames.
        if len(raw) > 128_000:
            raise ValueError("Audio chunk is too large")
        return value


class ClientInterrupt(BaseModel):
    type: str = ClientMessageType.INTERRUPT.value


class ClientTurnEnd(BaseModel):
    type: str = ClientMessageType.TURN_END.value


class ClientTextInput(BaseModel):
    type: str = ClientMessageType.TEXT_INPUT.value
    text: str = Field(min_length=1, max_length=4000)


class ServerMessageType(str, Enum):
    VAD = "vad"
    TRANSCRIPT = "transcript"
    AGENT_STATE = "agent_state"
    AGENT_TEXT = "agent_text"
    TTS_START = "tts_start"
    TTS_CHUNK = "tts_chunk"
    TTS_END = "tts_end"
    ACTION = "action"
    ERROR = "error"


class ServerVAD(BaseModel):
    type: str = ServerMessageType.VAD.value
    event: str


class ServerTranscript(BaseModel):
    type: str = ServerMessageType.TRANSCRIPT.value
    final: bool
    text: str


class ServerAgentState(BaseModel):
    type: str = ServerMessageType.AGENT_STATE.value
    state: str


class ServerAgentText(BaseModel):
    type: str = ServerMessageType.AGENT_TEXT.value
    text: str


class ServerTTSStart(BaseModel):
    type: str = ServerMessageType.TTS_START.value
    generation_id: int
    encoding: str = "pcm_s16le"
    sample_rate: int = 24000
    channels: int = 1


class ServerTTSChunk(BaseModel):
    type: str = ServerMessageType.TTS_CHUNK.value
    generation_id: int
    data: str


class ServerTTSEnd(BaseModel):
    type: str = ServerMessageType.TTS_END.value
    generation_id: int


class ServerAction(BaseModel):
    type: str = ServerMessageType.ACTION.value
    intent: str
    success: bool
    message: str
    data: Optional[dict] = None


class ServerError(BaseModel):
    type: str = ServerMessageType.ERROR.value
    code: str
    message: str


def parse_client_message(raw_json: str) -> dict:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON") from exc

    msg_type = data.get("type")
    if msg_type not in {e.value for e in ClientMessageType}:
        raise ValueError(f"Unknown client message type: {msg_type}")

    if msg_type == ClientMessageType.AUDIO_CHUNK.value:
        return ClientAudioChunk.model_validate(data).model_dump()
    if msg_type == ClientMessageType.INTERRUPT.value:
        return ClientInterrupt.model_validate(data).model_dump()
    if msg_type == ClientMessageType.TURN_END.value:
        return ClientTurnEnd.model_validate(data).model_dump()
    if msg_type == ClientMessageType.TEXT_INPUT.value:
        return ClientTextInput.model_validate(data).model_dump()

    raise ValueError(f"Unsupported message type: {msg_type}")
