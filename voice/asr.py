from dataclasses import dataclass

@dataclass
class ASRPartial:
    text: str

@dataclass
class ASRFinal:
    text: str

class StreamingASR:
    """
    Abstraction for a Streaming ASR service (e.g., local Whisper or Deepgram).
    Provides a push-based interface for audio chunks.
    """
    def __init__(self):
        self.is_running = False
        self.current_transcript = ""

    async def start(self):
        print("StreamingASR: Start stream")
        self.is_running = True
        self.current_transcript = ""

    async def push_audio(self, chunk: bytes):
        """
        Push audio into the ASR engine.
        Should return an ASRPartial or None if nothing transcribed yet.
        """
        if not self.is_running:
            return None
            
        # MOCK IMPLEMENTATION
        # self.current_transcript += " [speech]"
        # return ASRPartial(text=self.current_transcript)
        return None

    async def finish(self):
        """
        Signal end of speech, retrieve the final transcript.
        """
        print("StreamingASR: Finish stream")
        self.is_running = False
        # MOCK RETURN
        return ASRFinal(text=self.current_transcript)

    async def cancel(self):
        """
        Cancel the current transcription (e.g. during barge-in).
        """
        print("StreamingASR: Cancel stream")
        self.is_running = False
        self.current_transcript = ""
