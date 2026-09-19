import asyncio
import base64
import os

import pytest

from voice.protocol import parse_client_message
from voice.vad import VoiceActivityDetector
from tts.cartesia import CartesiaTTS


def test_audio_protocol_validation():
    pcm = base64.b64encode(b"\x00\x00" * 160).decode()
    msg = parse_client_message(
        '{"type":"audio_chunk","sequence":1,"sample_rate":16000,"encoding":"pcm_s16le","data":"'
        + pcm
        + '"}'
    )
    assert msg["sample_rate"] == 16000
    assert msg["encoding"] == "pcm_s16le"


def test_audio_protocol_rejects_wrong_rate():
    pcm = base64.b64encode(b"\x00\x00" * 160).decode()
    with pytest.raises(ValueError):
        parse_client_message(
            '{"type":"audio_chunk","sequence":1,"sample_rate":8000,"encoding":"pcm_s16le","data":"'
            + pcm
            + '"}'
        )


def test_vad_configuration():
    os.environ["VAD_END_SILENCE_MS"] = "450"
    os.environ["MIN_SPEECH_MS"] = "150"
    vad = VoiceActivityDetector()
    assert vad.frame_bytes == 640
    assert vad.min_speech_ms == 150


def test_cartesia_provider_requires_key():
    os.environ.pop("CARTESIA_API_KEY", None)
    with pytest.raises(EnvironmentError):
        asyncio.run(anext(CartesiaTTS().stream("hello", 1)))


if __name__ == "__main__":
    test_audio_protocol_validation()
    test_audio_protocol_rejects_wrong_rate()
    test_vad_configuration()
