"""
tts/base.py — Abstract TTS Provider
=====================================
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator


class TTSProvider(ABC):
    """Abstract base class for TTS providers."""

    @abstractmethod
    async def stream(self, text: str, generation_id: int) -> AsyncGenerator[str, None]:
        """
        Stream audio for the given text.
        Yields base64-encoded audio chunks.
        Must check cancellation state and stop yielding if cancelled.
        """
        ...

    @abstractmethod
    async def cancel(self, generation_id: int):
        """Cancel an active TTS generation."""
        ...
