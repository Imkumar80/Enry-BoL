from enum import Enum
from typing import Generator

class VADEvent(Enum):
    SPEECH_START = "speech_start"
    SPEECH_CONTINUE = "speech_continue"
    SPEECH_END = "speech_end"

class VoiceActivityDetector:
    """
    Independent VAD module. 
    Processes raw PCM audio and yields VADEvents.
    """
    def __init__(self, sample_rate=16000, frame_duration_ms=30):
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.is_speaking = False
        self.silence_frames = 0
        self.max_silence_frames = 20 # Endpointing: ~600ms of silence
        
        # In a real environment, initialize WebRTC VAD or Silero VAD here:
        # import webrtcvad
        # self.vad = webrtcvad.Vad(3)

    def process_audio(self, pcm_data: bytes) -> Generator[VADEvent, None, None]:
        """
        Process a chunk of audio and yield state changes.
        """
        # MOCK IMPLEMENTATION FOR ARCHITECTURE SCAFFOLDING
        # In reality, this calculates energy or uses webrtcvad.is_speech
        
        # Simple energy threshold (mock)
        is_speech = len(pcm_data) > 0 # Replace with actual VAD check
        
        if is_speech:
            self.silence_frames = 0
            if not self.is_speaking:
                self.is_speaking = True
                yield VADEvent.SPEECH_START
            else:
                yield VADEvent.SPEECH_CONTINUE
        else:
            if self.is_speaking:
                self.silence_frames += 1
                if self.silence_frames > self.max_silence_frames:
                    self.is_speaking = False
                    yield VADEvent.SPEECH_END
