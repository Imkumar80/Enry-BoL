"""
agent/state.py — LangGraph State Schema
=========================================
Defines the conversation state for the Enry agent.
Raw audio, WebSocket objects, VAD state, and TTS playback state
are explicitly excluded.
"""

from typing import TypedDict, Optional, Any
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from typing import Annotated


class EnryState(TypedDict):
    """LangGraph state for the Enry voice agent."""

    # Conversation history (LangChain messages)
    messages: Annotated[list, add_messages]

    # Current turn context
    current_intent: Optional[str]
    entities: dict
    action_result: Optional[dict]
    turn_id: str

    # Financial confirmation
    needs_confirmation: bool
    confirmation_data: Optional[dict]
