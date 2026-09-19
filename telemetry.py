import time
import logging
from dataclasses import dataclass
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telemetry")

@dataclass
class TurnTelemetry:
    turn_id: str
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
    
    # Interruption tracking
    t_interruption_start: Optional[float] = None
    t_vad_interruption_detects: Optional[float] = None
    t_tts_cancellation: Optional[float] = None

    def log_metrics(self):
        metrics = []
        if self.t0_speech_start and self.t1_vad_detects:
            metrics.append(f"VAD Latency: {(self.t1_vad_detects - self.t0_speech_start)*1000:.1f}ms")
        
        if self.t1_vad_detects and self.t2_first_asr_partial:
            metrics.append(f"ASR First-Token Latency: {(self.t2_first_asr_partial - self.t1_vad_detects)*1000:.1f}ms")
            
        if self.t3_vad_endpoint and self.t4_asr_final:
            metrics.append(f"ASR Final Latency: {(self.t4_asr_final - self.t3_vad_endpoint)*1000:.1f}ms")
            
        if self.t5_langgraph_start and self.t6_llm_first_token:
            metrics.append(f"LLM TTFT: {(self.t6_llm_first_token - self.t5_langgraph_start)*1000:.1f}ms")
            
        if self.t8_cartesia_request and self.t9_first_tts_audio:
            metrics.append(f"TTS TTFA: {(self.t9_first_tts_audio - self.t8_cartesia_request)*1000:.1f}ms")
            
        if self.t0_speech_start and self.t10_audio_reaches_browser:
            metrics.append(f"Total Response Latency: {(self.t10_audio_reaches_browser - self.t0_speech_start)*1000:.1f}ms")
            
        if self.t_interruption_start and self.t_tts_cancellation:
            metrics.append(f"Barge-in Latency: {(self.t_tts_cancellation - self.t_interruption_start)*1000:.1f}ms")
            
        logger.info(f"[Turn {self.turn_id}] " + " | ".join(metrics))

class TelemetryManager:
    def __init__(self):
        self.turns = {}

    def start_turn(self, turn_id: str):
        self.turns[turn_id] = TurnTelemetry(turn_id=turn_id, t0_speech_start=time.time())

    def record(self, turn_id: str, event: str):
        if turn_id in self.turns:
            setattr(self.turns[turn_id], event, time.time())

    def finish_turn(self, turn_id: str):
        if turn_id in self.turns:
            self.turns[turn_id].log_metrics()

telemetry = TelemetryManager()
