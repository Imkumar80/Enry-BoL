from enum import Enum
import asyncio
import uuid
from langchain_core.messages import HumanMessage
from voice.vad import VADEvent
from voice.asr import StreamingASR, ASRFinal
from tts.cartesia import CartesiaTTS
from agent.graph import agent_app
from voice.protocol import ServerTtsMessage, ServerTtsEndMessage
from telemetry import telemetry

class TurnState(Enum):
    IDLE = "IDLE"
    USER_SPEAKING = "USER_SPEAKING"
    END_PENDING = "END_PENDING"
    PROCESSING = "PROCESSING"
    AGENT_SPEAKING = "AGENT_SPEAKING"
    INTERRUPT = "INTERRUPT"

class TurnManager:
    """
    Manages the strict state machine of conversational turns.
    Connects ASR -> LangGraph -> TTS.
    """
    def __init__(self, send_message_callback):
        self.state = TurnState.IDLE
        self.asr = StreamingASR()
        self.tts = CartesiaTTS()
        self.send_message = send_message_callback
        self.current_turn_id = 0
        self.active_generation_id = None
        self.graph_state = {"messages": []}

    async def on_speech_start(self):
        telemetry.start_turn(str(self.current_turn_id))
        telemetry.record(str(self.current_turn_id), "t0_speech_start")
        
        if self.state == TurnState.AGENT_SPEAKING:
            await self.on_user_interrupt()
            
        print("TurnManager: Speech started")
        self.state = TurnState.USER_SPEAKING
        await self.asr.start()

    async def on_speech_end(self):
        if self.state == TurnState.USER_SPEAKING:
            print("TurnManager: Endpoint detected")
            telemetry.record(str(self.current_turn_id), "t3_vad_endpoint")
            self.state = TurnState.END_PENDING
            
            final_result = await self.asr.finish()
            if final_result and isinstance(final_result, ASRFinal):
                telemetry.record(str(self.current_turn_id), "t4_asr_final")
                await self.on_transcript_complete(final_result.text)

    async def on_transcript_complete(self, transcript: str):
        if not transcript.strip():
            self.state = TurnState.IDLE
            return
            
        self.state = TurnState.PROCESSING
        telemetry.record(str(self.current_turn_id), "t5_langgraph_start")
        print(f"TurnManager: Invoking LangGraph with: '{transcript}'")
        
        self.graph_state["messages"].append(HumanMessage(content=transcript))
        self.graph_state["action_result"] = None
        
        # Run LangGraph
        result_state = await agent_app.ainvoke(self.graph_state)
        self.graph_state = result_state # update state
        
        final_msg = result_state["messages"][-1].content
        telemetry.record(str(self.current_turn_id), "t7_response_complete")
        
        await self.speak_response(final_msg)

    async def speak_response(self, text: str):
        self.state = TurnState.AGENT_SPEAKING
        self.active_generation_id = str(uuid.uuid4())
        gen_id = self.active_generation_id
        
        telemetry.record(str(self.current_turn_id), "t8_cartesia_request")
        
        first_chunk = True
        
        async for chunk_b64 in self.tts.stream(text):
            if self.active_generation_id != gen_id:
                break # Cancelled due to barge-in
            
            if first_chunk:
                telemetry.record(str(self.current_turn_id), "t9_first_tts_audio")
                first_chunk = False
                
            await self.send_message(ServerTtsMessage(generation_id=gen_id, data=chunk_b64).dict())
            
        if self.active_generation_id == gen_id:
            await self.send_message(ServerTtsEndMessage(generation_id=gen_id).dict())
            self.state = TurnState.IDLE
            telemetry.finish_turn(str(self.current_turn_id))
            self.current_turn_id += 1

    async def on_user_interrupt(self):
        print(f"TurnManager: BARGE-IN DETECTED on turn {self.current_turn_id}!")
        telemetry.record(str(self.current_turn_id), "t_interruption_start")
        self.state = TurnState.INTERRUPT
        self.active_generation_id = None # invalidate generation
        
        await self.asr.cancel()
        await self.tts.cancel()
        
        telemetry.record(str(self.current_turn_id), "t_tts_cancellation")
        telemetry.finish_turn(str(self.current_turn_id))
        
        self.current_turn_id += 1
        self.state = TurnState.USER_SPEAKING
