import os
import asyncio
from dotenv import load_dotenv
load_dotenv()
from cartesia import AsyncCartesia

async def generate():
    client = AsyncCartesia(api_key=os.environ.get("CARTESIA_API_KEY"))
    phrases = {
        "test1": "Maggi stock eshtu ide?",
        "test2": "Ramesh ge eradu noora aivathu rupayi udhaar haaki.",
        "test3": "Bill start maadi, eradu Maggi mattu ondu Amul Milk add maadi.",
        "test4": "Checkout maadbahuda?",
        "barge_in1": "Today's sales summary",
        "barge_in2": "Wait, stop.",
    }
    os.makedirs("test_audio", exist_ok=True)
    voice_id = "3b554273-4299-48b9-9aaf-eefd438e3941"

    for name, text in phrases.items():
        print(f"Generating {name}...")
        audio_stream = await client.tts.sse(
            model_id="sonic-latest",
            transcript=text,
            voice={"mode": "id", "id": voice_id},
            output_format={"container": "raw", "encoding": "pcm_s16le", "sample_rate": 16000}
        )
        
        with open(f"test_audio/{name}.raw", "wb") as f:
            async for chunk in audio_stream:
                if hasattr(chunk, 'audio'):
                    f.write(chunk.audio)
        print(f"Saved test_audio/{name}.raw")

if __name__ == "__main__":
    asyncio.run(generate())
