import asyncio

class TTSProvider:
    """
    Abstract Base Class for TTS Providers.
    """
    async def stream(self, text: str):
        raise NotImplementedError

    async def cancel(self):
        raise NotImplementedError

class CartesiaTTS(TTSProvider):
    """
    Streaming implementation of Cartesia Sonic.
    Provides ability to instantly cancel generation during barge-in.
    """
    def __init__(self):
        self._is_cancelled = False

    async def stream(self, text: str):
        self._is_cancelled = False
        print(f"CartesiaTTS: Streaming audio for: '{text}'")
        
        # MOCK IMPLEMENTATION: Yielding dummy chunks
        # In a real implementation, this connects to Cartesia WS API
        # and yields PCM chunks as they arrive.
        for i in range(5):
            if self._is_cancelled:
                print("CartesiaTTS: Generation CANCELLED mid-stream!")
                break
            import base64
            dummy_pcm = b'\x00\x00' * 1600 # Mock 1600 samples of silence
            yield base64.b64encode(dummy_pcm).decode('utf-8')

    async def cancel(self):
        print("CartesiaTTS: Cancel requested!")
        self._is_cancelled = True
