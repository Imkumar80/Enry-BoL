"""
voice/vad.py — Voice Activity Detection using webrtcvad
========================================================
Processes 16kHz mono PCM audio and emits SPEECH_START / SPEECH_END events.
Endpoint detection uses consecutive silent frames rather than a fixed timer.

Configuration via environment variables:
  VAD_MODE          = 0..3 (aggressiveness, default 2)
  VAD_FRAME_MS      = 10|20|30 (frame duration, default 20)
  VAD_END_SILENCE_MS= silence duration to trigger endpoint (default 500)
"""

import os
from enum import Enum
from typing import Optional
import webrtcvad


class VADEvent(Enum):
    SPEECH_START    = "speech_start"
    SPEECH_CONTINUE = "speech_continue"
    SPEECH_END      = "speech_end"


class VoiceActivityDetector:
    """
    webrtcvad-based VAD.

    Feed it fixed-size PCM frames (10/20/30 ms at 16 kHz, mono, 16-bit LE).
    It returns a VADEvent or None for each frame.
    """

    def __init__(self):
        self.mode: int = int(os.getenv("VAD_MODE", "2"))
        self.frame_ms: int = int(os.getenv("VAD_FRAME_MS", "20"))
        self.end_silence_ms: int = int(os.getenv("VAD_END_SILENCE_MS", "500"))
        self.sample_rate: int = 16000

        # Derived
        self.frame_bytes: int = 2 * self.sample_rate * self.frame_ms // 1000  # 2 bytes/sample
        self._silent_frames_for_endpoint: int = self.end_silence_ms // self.frame_ms

        # State
        self._vad = webrtcvad.Vad(self.mode)
        self._is_speaking: bool = False
        self._consecutive_silent: int = 0
        self._speech_frame_count: int = 0

        # Buffer for accumulating partial frames
        self._buffer: bytes = b""

    def reset(self):
        """Reset state for a new session."""
        self._is_speaking = False
        self._consecutive_silent = 0
        self._speech_frame_count = 0
        self._buffer = b""

    def process_audio(self, pcm_data: bytes) -> list[VADEvent]:
        """
        Process a chunk of PCM audio (any size).
        Internally buffers and splits into fixed-size frames for webrtcvad.
        Returns a list of VADEvents (may be empty).
        """
        self._buffer += pcm_data
        events: list[VADEvent] = []

        while len(self._buffer) >= self.frame_bytes:
            frame = self._buffer[:self.frame_bytes]
            self._buffer = self._buffer[self.frame_bytes:]

            is_speech = self._vad.is_speech(frame, self.sample_rate)

            if is_speech:
                self._consecutive_silent = 0
                if not self._is_speaking:
                    self._is_speaking = True
                    self._speech_frame_count = 1
                    events.append(VADEvent.SPEECH_START)
                else:
                    self._speech_frame_count += 1
                    events.append(VADEvent.SPEECH_CONTINUE)
            else:
                if self._is_speaking:
                    self._consecutive_silent += 1
                    if self._consecutive_silent >= self._silent_frames_for_endpoint:
                        self._is_speaking = False
                        self._speech_frame_count = 0
                        events.append(VADEvent.SPEECH_END)

        return events

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking
