"""
voice/vad.py — Voice Activity Detection using webrtcvad.
"""

import os
from enum import Enum
import webrtcvad


class VADEvent(Enum):
    SPEECH_START = "speech_start"
    SPEECH_CONTINUE = "speech_continue"
    SPEECH_END = "speech_end"


class VoiceActivityDetector:
    """16 kHz mono PCM VAD with configurable endpointing and false-start filtering."""

    def __init__(self):
        self.mode = int(os.getenv("VAD_MODE", "2"))
        self.frame_ms = int(os.getenv("VAD_FRAME_MS", "20"))
        self.end_silence_ms = int(os.getenv("VAD_END_SILENCE_MS", "250"))
        self.min_speech_ms = int(os.getenv("MIN_SPEECH_MS", "120"))
        self.sample_rate = 16000

        if self.frame_ms not in (10, 20, 30):
            raise ValueError("VAD_FRAME_MS must be 10, 20, or 30")
        if not 0 <= self.mode <= 3:
            raise ValueError("VAD_MODE must be 0..3")

        self.frame_bytes = 2 * self.sample_rate * self.frame_ms // 1000
        self._silent_frames_for_endpoint = max(1, self.end_silence_ms // self.frame_ms)
        self._min_speech_frames = max(1, (self.min_speech_ms + self.frame_ms - 1) // self.frame_ms)

        self._vad = webrtcvad.Vad(self.mode)
        self.reset()

    def reset(self):
        self._is_speaking = False
        self._consecutive_silent = 0
        self._speech_frame_count = 0
        self._buffer = b""
        self._last_speech_duration_ms = 0

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    @property
    def last_speech_duration_ms(self) -> int:
        return self._last_speech_duration_ms

    def process_audio(self, pcm_data: bytes) -> list[VADEvent]:
        if not pcm_data:
            return []

        self._buffer += pcm_data
        events = []

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
            elif self._is_speaking:
                self._consecutive_silent += 1
                if self._consecutive_silent >= self._silent_frames_for_endpoint:
                    duration_ms = self._speech_frame_count * self.frame_ms
                    self._last_speech_duration_ms = duration_ms
                    self._is_speaking = False
                    self._consecutive_silent = 0
                    self._speech_frame_count = 0
                    # Emit an endpoint even for a short burst; TurnManager can
                    # discard it without sending the transcript downstream.
                    events.append(VADEvent.SPEECH_END)

        return events
