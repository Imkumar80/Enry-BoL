"""
agent/session.py — request-local voice session context.
"""
from contextvars import ContextVar
from typing import Optional

_session_id: ContextVar[Optional[str]] = ContextVar("enry_session_id", default=None)

def set_session_id(session_id: str):
    return _session_id.set(session_id)

def reset_session_id(token):
    _session_id.reset(token)

def get_session_id() -> Optional[str]:
    return _session_id.get()
