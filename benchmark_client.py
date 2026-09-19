import asyncio
import json
import base64
import time
import sys
import websockets

async def run_benchmark(audio_file):
    print(f"=== Benchmarking with {audio_file} ===")
    
    with open(audio_file, "rb") as f:
        pcm_data = f.read()

    # Pad with 1 second of silence so VAD triggers end-of-speech
    pcm_data += b'\x00' * 32000

    # 16kHz, 1 channel, 2 bytes per sample -> 32000 bytes/sec -> 640 bytes/20ms
    chunk_size = 640

    t_start = time.time()
    t_first_partial = None
    t_final = None
    t_tts_start = None
    t_first_tts_chunk = None

    async with websockets.connect("ws://localhost:8000/ws/benchmark") as ws:
        # Task to send audio
        async def sender():
            nonlocal pcm_data
            offset = 0
            while offset < len(pcm_data):
                chunk = pcm_data[offset:offset+chunk_size]
                if len(chunk) < chunk_size:
                    chunk += b'\x00' * (chunk_size - len(chunk))
                await ws.send(json.dumps({
                    "type": "audio_chunk",
                    "sequence": offset // chunk_size,
                    "sample_rate": 16000,
                    "encoding": "pcm_s16le",
                    "data": base64.b64encode(chunk).decode('utf-8')
                }))
                offset += chunk_size
                await asyncio.sleep(0.01)  # slightly faster than real-time
            
            print("Finished sending audio")
            # Wait for 45 seconds to allow ASR and LLM to finish
            await asyncio.sleep(45)
            print("Timeout waiting for response")

        # Task to receive
        async def receiver():
            nonlocal t_first_partial, t_final, t_tts_start, t_first_tts_chunk
            while True:
                try:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    msg_type = data.get("type")
                    if msg_type == "vad":
                        print(f"VAD Event: {data.get('event')}")
                    elif msg_type == "transcript":
                        if not data.get("final") and not t_first_partial:
                            t_first_partial = time.time()
                        elif data.get("final"):
                            t_final = time.time()
                            print(f"Final transcript: {data.get('text')}")
                    elif msg_type == "tts_start":
                        t_tts_start = time.time()
                    elif msg_type == "tts_chunk":
                        if not t_first_tts_chunk:
                            t_first_tts_chunk = time.time()
                            # We stop receiving after the first TTS chunk for simple benchmarking
                            return
                    else:
                        print(f"Received: {msg_type} - {data}")
                except websockets.exceptions.ConnectionClosed:
                    break

        sender_task = asyncio.create_task(sender())
        await receiver()
        sender_task.cancel()

    if t_first_partial:
        print(f"Audio Start -> First ASR Partial: {(t_first_partial - t_start)*1000:.0f}ms")
    if t_final:
        print(f"Audio Start -> ASR Final: {(t_final - t_start)*1000:.0f}ms")
    if t_tts_start and t_final:
        print(f"ASR Final -> TTFT (tts_start): {(t_tts_start - t_final)*1000:.0f}ms")
    if t_first_tts_chunk and t_tts_start:
        print(f"TTFT -> First TTS Audio: {(t_first_tts_chunk - t_tts_start)*1000:.0f}ms")
    if t_first_tts_chunk:
        print(f"Total Latency (Audio Start -> TTS Audio): {(t_first_tts_chunk - t_start)*1000:.0f}ms")
    print("\n")

async def main():
    if len(sys.argv) > 1:
        await run_benchmark(sys.argv[1])
    else:
        for file in os.listdir("test_audio"):
            if file.endswith(".raw"):
                await run_benchmark(f"test_audio/{file}")

if __name__ == "__main__":
    asyncio.run(main())
