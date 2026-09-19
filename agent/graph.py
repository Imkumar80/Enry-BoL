import asyncio
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage
from agent.state import EnryState
from agent.llm import LocalLLM
from agent.tools import TOOLS_LIST

llm = LocalLLM()

async def agent_node(state: EnryState):
    print("LangGraph: agent_node reasoning...")
    messages = state.get("messages", [])
    
    # Check if there is an action_result that we need to pass back to the LLM
    if state.get("action_result"):
        res = state["action_result"]
        messages.append(HumanMessage(content=f"System Tool Result: {res}"))
        
    response = await llm.generate(messages)
    
    intent = None
    if response.tool_calls:
        intent = response.tool_calls[0]['name']
        
    return {"messages": messages + [response], "current_intent": intent, "action_result": None}

async def action_node(state: EnryState):
    print("LangGraph: action_node executing...")
    messages = state.get("messages", [])
    last_msg = messages[-1]
    
    action_result = {}
    if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
        tool_call = last_msg.tool_calls[0]
        tool_name = tool_call['name']
        tool_args = tool_call['args']
        
        # Execute tool
        for t in TOOLS_LIST:
            if t.name == tool_name:
                print(f"Executing Tool: {tool_name} with {tool_args}")
                try:
                    res = t.invoke(tool_args)
                    action_result = {"success": True, "data": res}
                except Exception as e:
                    action_result = {"success": False, "error": str(e)}
                break

    return {"action_result": action_result}

async def response_node(state: EnryState):
    print("LangGraph: response_node finalizing...")
    return {"agent_is_speaking": True}

def should_execute_tool(state: EnryState):
    messages = state.get("messages", [])
    if not messages: return "response"
    last_msg = messages[-1]
    if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
        return "action"
    return "response"

workflow = StateGraph(EnryState)
workflow.add_node("agent", agent_node)
workflow.add_node("action", action_node)
workflow.add_node("response", response_node)

workflow.set_entry_point("agent")

# If agent wants to call a tool, go to action. Otherwise, respond.
workflow.add_conditional_edges("agent", should_execute_tool, {"action": "action", "response": "response"})

# After action, always loop back to agent to interpret result and speak.
workflow.add_edge("action", "agent")
workflow.add_edge("response", END)

agent_app = workflow.compile()
