from typing import TypedDict, List, Optional, Dict, Any

class EnryState(TypedDict):
    """
    The strict conversation state for the LangGraph agent.
    Raw audio is explicitly kept OUT of this state.
    """
    messages: List[Dict[str, Any]]
    
    # Tool Execution State
    current_intent: Optional[str]
    entities: Dict[str, Any]
    action_result: Optional[Dict[str, Any]]

    # Conversation Control State
    turn_id: str
    user_is_speaking: bool
    agent_is_speaking: bool
    interrupted: bool
