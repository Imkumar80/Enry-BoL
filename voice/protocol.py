"""
voice/protocol.py — WebSocket Protocol for Enry Voice Pipeline
================================================================
Defines all client→server and server→client message types.
Every message has a `type` field. TTS messages carry a `generation_id`
so stale audio can be discarded after barge-in.
"""

import json
from enum import Enum
from pydantic import BaseModel
from typing import Optional

PROTOCOL_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Client → Server
# ---------------------------------------------------------------------------

class ClientMessageType(str, Enum):
    AUDIO_CHUNK = "audio_chunk"
    INTERRUPT   = "interrupt"
    TURN_END    = "turn_end"
    TEXT_INPUT   = "text_input"   # typed command from dashboard


class ClientAudioChunk(BaseModel):
    type: str = ClientMessageType.AUDIO_CHUNK.value
    sequence: int
    sample_rate: int = 16000
    encoding: str = "pcm_s16le"
    data: str  # base64-encoded PCM

class ClientInterrupt(BaseModel):
    type: str = ClientMessageType.INTERRUPT.value

class ClientTurnEnd(BaseModel):
    type: str = ClientMessageType.TURN_END.value

class ClientTextInput(BaseModel):
    type: str = ClientMessageType.TEXT_INPUT.value
    text: str


# ---------------------------------------------------------------------------
# Server → Client
# ---------------------------------------------------------------------------

class ServerMessageType(str, Enum):
    VAD          = "vad"
    TRANSCRIPT   = "transcript"
    AGENT_STATE  = "agent_state"
    AGENT_TEXT   = "agent_text"       # final text response for dashboard display
    TTS_START    = "tts_start"
    TTS_CHUNK    = "tts_chunk"
    TTS_END      = "tts_end"
    ACTION       = "action"           # structured tool result for UI updates
    ERROR        = "error"


# --- VAD events ---
class ServerVAD(BaseModel):
    type: str = ServerMessageType.VAD.value
    event: str  # "speech_start" | "speech_end"


# --- Transcript ---
class ServerTranscript(BaseModel):
    type: str = ServerMessageType.TRANSCRIPT.value
    final: bool
    text: str


# --- Agent state ---
class ServerAgentState(BaseModel):
    type: str = ServerMessageType.AGENT_STATE.value
    state: str  # "processing" | "speaking" | "idle"


# --- Agent text (full response for dashboard) ---
class ServerAgentText(BaseModel):
    type: str = ServerMessageType.AGENT_TEXT.value
    text: str


# --- TTS streaming ---
class ServerTTSStart(BaseModel):
    type: str = ServerMessageType.TTS_START.value
    generation_id: int


class ServerTTSChunk(BaseModel):
    type: str = ServerMessageType.TTS_CHUNK.value
    generation_id: int
    data: str  # base64 audio


class ServerTTSEnd(BaseModel):
    type: str = ServerMessageType.TTS_END.value
    generation_id: int


# --- Structured action result for frontend UI updates ---
class ServerAction(BaseModel):
    type: str = ServerMessageType.ACTION.value
    intent: str
    success: bool
    message: str
    data: Optional[dict] = None


# --- Errors ---
class ServerError(BaseModel):
    type: str = ServerMessageType.ERROR.value
    code: str
    message: str


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_client_message(raw_json: str) -> dict:
    """Parse raw JSON string from the client into a dict. Returns the dict."""
    data = json.loads(raw_json)
    msg_type = data.get("type")
    if msg_type not in [e.value for e in ClientMessageType]:
        raise ValueError(f"Unknown client message type: {msg_type}")
    return data
