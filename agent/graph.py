"""
agent/graph.py — LangGraph Agent Orchestration
================================================
Graph structure:
  START → agent → [tool required?]
                    ├── no  → END
                    └── yes → [needs confirmation?]
                                ├── yes → END (with confirmation_data)
                                └── no  → tool → agent → END

Two public entry points called by the TurnManager:
  - process_turn()              — process a new user transcript
  - execute_confirmed_action()  — execute a previously confirmed financial action
"""

import logging
import os
from typing import Optional

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

from agent.state import EnryState
from agent.nodes import agent_node, tool_node
from agent.tools import TOOLS_LIST, FINANCIAL_TOOLS

logger = logging.getLogger("agent.graph")

# Build tool lookup
_TOOLS_BY_NAME = {t.name: t for t in TOOLS_LIST}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _build_system_prompt() -> str:
    """Build the system prompt with live DB context."""
    try:
        import db
        conn = db.get_db_connection()
        products = [row["name"] for row in db.get_all_inventory(conn)]
        customers = [row["name"] for row in db.get_all_customers(conn)]
        conn.close()
    except Exception:
        products, customers = [], []

    product_list = ", ".join(products) if products else "none yet"
    customer_list = ", ".join(customers) if customers else "none yet"

    return f"""You are Enry, a helpful voice assistant for an Indian kirana shop.
You can speak in Kannada, Hinglish, Hindi, or English.
CRITICAL TTS RULE: You MUST output all your responses EXCLUSIVELY using the English alphabet (Roman script / Transliteration). DO NOT use Kannada script, Devanagari, or any native characters, as the TTS engine cannot read them and will glitch out. For example, write "Maggi stock eshtu ide" instead of "ಮಾಗಿ ಸ್ಟಾಕ್ ಎಷ್ಟು ಇದೆ".

Keep responses brief and conversational.

STORE CATALOGUE:
Products: {product_list}
Customers: {customer_list}

YOUR CAPABILITIES (use the corresponding tools):
- check_stock: Check product stock levels
- check_customer_credit: Check customer udhaar/credit balance
- record_credit: Record udhaar (credit) for a customer
- record_payment: Record payment received from a customer
- add_to_bill: Add items to the active cart/bill
- create_bill: Start/reset a new bill for a customer
- checkout_bill: Checkout the current bill; always ask for confirmation first
- get_daily_summary: Get today's sales summary
- add_inventory: Add stock to inventory
- update_inventory: Set exact stock level

HINGLISH NUMBER MAPPING:
ek=1, do=2, teen=3, char=4, paanch=5, das=10, panch sau=500, hazaar=1000

FUZZY MATCHING:
Match spoken words to closest catalogue entry:
  "maggi" → Maggi Noodles, "biscuit" → Britannia Biscuit,
  "surf/surf wala" → Surf Excel, "doodh/milk" → Amul Milk, "chini" → Chini

IMPORTANT RULES:
1. Always use the appropriate tool for business operations. Do NOT just reply with text.
2. For financial actions (record_credit, record_payment), ask for user confirmation first before calling the tool.
3. Keep responses under 2 sentences.
4. If you cannot understand the request, say so in Hinglish."""


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _should_use_tool(state: EnryState) -> str:
    """Route: if the last message has tool_calls, go to tool node or confirmation."""
    messages = state.get("messages", [])
    if not messages:
        return "end"

    last_msg = messages[-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        # Check if it needs confirmation (financial tool)
        if state.get("needs_confirmation"):
            return "end"  # Don't execute — return to turn manager for confirmation
        return "tool"
    return "end"


def _build_graph() -> StateGraph:
    workflow = StateGraph(EnryState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tool", tool_node)

    workflow.set_entry_point("agent")

    workflow.add_conditional_edges("agent", _should_use_tool, {
        "tool": "tool",
        "end": END,
    })

    # After tool execution, go back to agent for the final response
    workflow.add_edge("tool", "agent")

    return workflow.compile()


# Compile once
_graph = _build_graph()


# ---------------------------------------------------------------------------
# Public API for TurnManager
# ---------------------------------------------------------------------------

async def process_turn(transcript: str, conversation_messages: list,
                       pending_confirmation: Optional[dict] = None) -> dict:
    """
    Process a user transcript through the LangGraph agent.

    Returns:
        {
            "response_text": str,
            "action_data": dict | None,   # for UI updates
            "needs_confirmation": bool,
            "confirmation_data": dict | None,
            "messages": list,             # updated conversation history
        }
    """
    # Build the initial state
    system_msg = SystemMessage(content=_build_system_prompt())
    user_msg = HumanMessage(content=transcript)

    # Start with system + history + new user message
    messages = [system_msg] + conversation_messages + [user_msg]

    initial_state: EnryState = {
        "messages": messages,
        "current_intent": None,
        "entities": {},
        "action_result": None,
        "turn_id": "",
        "needs_confirmation": False,
        "confirmation_data": None,
    }

    # Run the graph
    result_state = await _graph.ainvoke(initial_state)

    # Extract the response
    final_messages = result_state.get("messages", [])
    needs_confirmation = result_state.get("needs_confirmation", False)
    confirmation_data = result_state.get("confirmation_data")

    # Find the last AI message for the response text
    response_text = "Samajh nahi aaya, dobara boliye."
    for msg in reversed(final_messages):
        if isinstance(msg, AIMessage) and msg.content:
            response_text = msg.content
            break

    # Build action data for frontend
    action_data = None
    intent = result_state.get("current_intent")
    if intent and not needs_confirmation:
        action_result = result_state.get("action_result")
        if action_result:
            action_data = {
                "intent": intent,
                "success": True,
                "message": response_text,
                "data": action_result,
            }

    # If confirmation needed, craft the confirmation question
    if needs_confirmation and confirmation_data:
        tool_name = confirmation_data.get("tool_name", "")
        tool_args = confirmation_data.get("tool_args", {})
        if tool_name == "record_credit":
            response_text = f"{tool_args.get('customer_name', 'Customer')} ke account mein ₹{tool_args.get('amount', 0):.0f} udhaar add kar doon? Haan ya nahi?"
        elif tool_name == "record_payment":
            response_text = f"{tool_args.get('customer_name', 'Customer')} se ₹{tool_args.get('amount', 0):.0f} payment record kar doon? Haan ya nahi?"
        elif tool_name == "checkout_bill":
            response_text = "Current bill checkout kar doon? Haan ya nahi?"

    # Keep only user and AI messages for conversation history (skip system)
    updated_history = [m for m in final_messages if not isinstance(m, SystemMessage)]

    return {
        "response_text": response_text,
        "action_data": action_data,
        "needs_confirmation": needs_confirmation,
        "confirmation_data": confirmation_data,
        "messages": updated_history,
    }


async def execute_confirmed_action(confirmation_data: dict, conversation_messages: list) -> dict:
    """
    Execute a previously confirmed financial action.

    Called after the user says 'haan'/'yes' to a confirmation prompt.
    """
    tool_name = confirmation_data.get("tool_name", "")
    tool_args = confirmation_data.get("tool_args", {})

    tool_fn = _TOOLS_BY_NAME.get(tool_name)
    if not tool_fn:
        return {
            "response_text": f"Tool '{tool_name}' not found.",
            "action_data": None,
            "messages": conversation_messages,
        }

    try:
        result_str = tool_fn.invoke(tool_args)
        logger.info(f"Confirmed action executed: {tool_name}({tool_args}) → {result_str}")

        # Build action data for frontend
        action_data = {
            "intent": tool_name,
            "success": True,
            "message": result_str,
            "data": {"customer": tool_args.get("customer_name"), "amount": tool_args.get("amount")},
        }

        return {
            "response_text": result_str,
            "action_data": action_data,
            "messages": conversation_messages + [
                AIMessage(content=result_str),
            ],
        }
    except Exception as e:
        logger.error(f"Confirmed action failed: {e}", exc_info=True)
        return {
            "response_text": f"Action fail ho gaya: {e}",
            "action_data": None,
            "messages": conversation_messages,
        }
