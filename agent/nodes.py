"""
agent/nodes.py — LangGraph Node Functions
===========================================
Defines the agent reasoning node and the tool execution node.
"""

import logging
from langchain_core.messages import ToolMessage
from agent.state import EnryState
from agent.llm import get_llm
from agent.tools import TOOLS_LIST, FINANCIAL_TOOLS

logger = logging.getLogger("agent.nodes")

# Build tool lookup dict
_TOOLS_BY_NAME = {t.name: t for t in TOOLS_LIST}


async def agent_node(state: EnryState) -> dict:
    """
    LLM reasoning node.
    Takes conversation messages, invokes the LLM, and returns the response.
    """
    logger.info("agent_node: reasoning...")
    messages = state.get("messages", [])

    llm = get_llm()
    response = await llm.ainvoke(messages)

    intent = None
    needs_confirmation = False
    confirmation_data = None

    if response.tool_calls:
        tool_call = response.tool_calls[0]
        intent = tool_call["name"]

        # Check if this is a financial tool that needs confirmation
        if intent in FINANCIAL_TOOLS:
            needs_confirmation = True
            confirmation_data = {
                "tool_name": intent,
                "tool_args": tool_call["args"],
                "tool_call_id": tool_call.get("id", ""),
            }

    return {
        "messages": [response],
        "current_intent": intent,
        "needs_confirmation": needs_confirmation,
        "confirmation_data": confirmation_data,
    }


async def tool_node(state: EnryState) -> dict:
    """
    Tool execution node.
    Executes the tool call from the last AI message and returns the result.
    """
    logger.info("tool_node: executing...")
    messages = state.get("messages", [])
    last_msg = messages[-1]

    results = []

    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        for tool_call in last_msg.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call.get("id", tool_name)

            tool_fn = _TOOLS_BY_NAME.get(tool_name)
            if tool_fn is None:
                result_str = f"Unknown tool: {tool_name}"
                logger.warning(result_str)
            else:
                try:
                    logger.info(f"Executing tool: {tool_name}({tool_args})")
                    result_str = tool_fn.invoke(tool_args)
                except Exception as e:
                    result_str = f"Tool execution error: {e}"
                    logger.error(result_str, exc_info=True)

            results.append(ToolMessage(content=str(result_str), tool_call_id=tool_id))

    return {
        "messages": results,
        "action_result": {"tool_results": [r.content for r in results]} if results else None,
    }
