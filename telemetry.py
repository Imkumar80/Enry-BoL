"""
telemetry.py — Structured Latency Telemetry
=============================================
Tracks per-turn timing metrics for the voice pipeline.
Used by the TurnManager for structured logging.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telemetry")


@dataclass
class TurnTelemetry:
    turn_id: str
    session_id: str = ""
    generation_id: int = 0

    # Timestamps
    t0_speech_start: Optional[float] = None
    t1_vad_detects: Optional[float] = None
    t2_first_asr_partial: Optional[float] = None
    t3_vad_endpoint: Optional[float] = None
    t4_asr_final: Optional[float] = None
    t5_langgraph_start: Optional[float] = None
    t6_llm_first_token: Optional[float] = None
    t7_response_complete: Optional[float] = None
    t8_cartesia_request: Optional[float] = None
    t9_first_tts_audio: Optional[float] = None
    t10_audio_reaches_browser: Optional[float] = None

    # Interruption
    t_interruption_start: Optional[float] = None
    t_tts_cancellation: Optional[float] = None

    def log_metrics(self):
        metrics = []
        t = self

        if t.t0_speech_start and t.t3_vad_endpoint:
            metrics.append(f"speech_dur={_ms(t.t3_vad_endpoint - t.t0_speech_start)}")

        if t.t3_vad_endpoint and t.t4_asr_final:
            metrics.append(f"endpoint_to_asr={_ms(t.t4_asr_final - t.t3_vad_endpoint)}")

        if t.t5_langgraph_start and t.t7_response_complete:
            metrics.append(f"graph_time={_ms(t.t7_response_complete - t.t5_langgraph_start)}")

        if t.t8_cartesia_request and t.t9_first_tts_audio:
            metrics.append(f"tts_ttfa={_ms(t.t9_first_tts_audio - t.t8_cartesia_request)}")

        if t.t0_speech_start and t.t9_first_tts_audio:
            metrics.append(f"total_latency={_ms(t.t9_first_tts_audio - t.t0_speech_start)}")

        if t.t_interruption_start and t.t_tts_cancellation:
            metrics.append(f"barge_in={_ms(t.t_tts_cancellation - t.t_interruption_start)}")

        if metrics:
            logger.info(f"[Turn {t.turn_id}] " + " | ".join(metrics))


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f}ms"


class TelemetryManager:
    def __init__(self):
        self.turns: dict[str, TurnTelemetry] = {}

    def start_turn(self, turn_id: str, session_id: str = "", generation_id: int = 0):
        self.turns[turn_id] = TurnTelemetry(
            turn_id=turn_id, session_id=session_id, generation_id=generation_id,
            t0_speech_start=time.time()
        )

    def record(self, turn_id: str, event: str):
        if turn_id in self.turns:
            setattr(self.turns[turn_id], event, time.time())

    def finish_turn(self, turn_id: str):
        if turn_id in self.turns:
            self.turns[turn_id].log_metrics()


telemetry = TelemetryManager()
