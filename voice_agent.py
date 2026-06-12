import os
import json
import asyncio
from datetime import datetime
from typing import Annotated
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Cartesia Line imports
from line.llm_agent import LlmAgent, LlmConfig, loopback_tool, end_call
from line.voice_agent_app import VoiceAgentApp

import db
import parser

load_dotenv()

# Ensure litellm can find the OpenRouter API key
# litellm reads OPENROUTER_API_KEY from the environment directly
os.environ["OPENROUTER_API_KEY"] = os.getenv("OPENROUTER_API_KEY", "")

# --- 1. Define Cartesia Line Loopback Tools ---

@loopback_tool
async def execute_ledger_command(ctx, command: Annotated[str, "The complete user spoken sentence to parse and execute ledger, billing, stock, or credit operations"]):
    """Execute ledger actions (record credit, record payment, check stock, check credit, add to bill, create bill, daily summary) by calling the second NLU parser LLM agent."""
    parsed = parser.parse_command(command)
    intent = parsed.intent
    entities = parsed.entities
    explanation = parsed.explanation
    
    conn = db.get_db_connection()
    try:
        if intent == "record_credit":
            if not entities.customer or not entities.amount:
                return f"Error: Customer name or amount is missing. {explanation}"
            new_bal = db.record_khata_transaction(entities.customer, "credit", entities.amount, "Recorded via voice", conn)
            result_data = {
                "intent": "record_credit",
                "success": True,
                "message": f"Recorded credit of ₹{entities.amount:.2f} for {entities.customer}. New balance: ₹{new_bal:.2f}.",
                "customer": entities.customer,
                "amount": entities.amount
            }
            return json.dumps(result_data)
            
        elif intent == "record_payment":
            if not entities.customer or not entities.amount:
                return f"Error: Customer name or amount is missing. {explanation}"
            new_bal = db.record_khata_transaction(entities.customer, "payment", entities.amount, "Received via voice", conn)
            result_data = {
                "intent": "record_payment",
                "success": True,
                "message": f"Recorded payment of ₹{entities.amount:.2f} from {entities.customer}. Remaining balance: ₹{new_bal:.2f}.",
                "customer": entities.customer,
                "amount": entities.amount
            }
            return json.dumps(result_data)
            
        elif intent == "check_stock":
            if not entities.product:
                return f"Error: Product name is missing. {explanation}"
            item = db.get_inventory_item_by_name(entities.product, conn)
            if not item:
                return f"Error: Product '{entities.product}' not found."
            result_data = {
                "intent": "check_stock",
                "success": True,
                "message": f"We have {item['stock']} {item['unit']}(s) of {item['name']} in stock."
            }
            return json.dumps(result_data)
            
        elif intent == "check_credit":
            if not entities.customer:
                return f"Error: Customer name is missing. {explanation}"
            cust = db.get_customer_by_name(entities.customer, conn)
            if not cust:
                return f"Error: Customer '{entities.customer}' not found."
            result_data = {
                "intent": "check_credit",
                "success": True,
                "message": f"{cust['name']} has an outstanding balance of ₹{cust['balance']:.2f}."
            }
            return json.dumps(result_data)
            
        elif intent == "add_to_bill":
            if not entities.product:
                return f"Error: Product name is missing. {explanation}"
            item = db.get_inventory_item_by_name(entities.product, conn)
            if not item:
                return f"Error: Product '{entities.product}' not found in catalog."
            qty = entities.quantity or 1.0
            result_data = {
                "intent": "add_to_bill",
                "success": True,
                "message": f"Added {qty} {item['unit']}(s) of {item['name']} to the cart.",
                "product_details": {
                    "name": item["name"],
                    "price": item["price"],
                    "quantity": qty,
                    "unit": item["unit"],
                    "total": item["price"] * qty
                }
            }
            return json.dumps(result_data)
            
        elif intent == "create_bill":
            cust_name = entities.customer or "Walk-in Customer"
            result_data = {
                "intent": "create_bill",
                "success": True,
                "message": f"Created active cart/bill for {cust_name}.",
                "customer": entities.customer
            }
            return json.dumps(result_data)
            
        elif intent == "daily_summary":
            today_date = datetime.now().strftime('%Y-%m-%d')
            sales = conn.execute("SELECT SUM(total_amount) as total FROM invoices WHERE date(timestamp) = ?", (today_date,)).fetchone()
            credits = conn.execute("SELECT SUM(amount) as total FROM transactions WHERE type = 'credit' AND date(timestamp) = ?", (today_date,)).fetchone()
            payments = conn.execute("SELECT SUM(amount) as total FROM transactions WHERE type = 'payment' AND date(timestamp) = ?", (today_date,)).fetchone()
            
            s_val = sales["total"] or 0.0
            c_val = credits["total"] or 0.0
            p_val = payments["total"] or 0.0
            result_data = {
                "intent": "daily_summary",
                "success": True,
                "message": f"Today's total sales: ₹{s_val:.2f}. Credits recorded: ₹{c_val:.2f}. Payments received: ₹{p_val:.2f}."
            }
            return json.dumps(result_data)
            
        else:
            result_data = {
                "intent": intent,
                "success": False,
                "message": f"I parsed the intent as '{intent}' but could not execute it. Explanation: {explanation}"
            }
            return json.dumps(result_data)
            
    except Exception as e:
        return f"Error executing database operation: {str(e)}"
    finally:
        conn.close()

# --- 2. Initialize the Voice Agent ---

async def get_agent(env, call_request):
    system_prompt = (
        "You are Enry, a helpful, highly expressive and human-like voice assistant for a Kirana shop owner. "
        "You speak in natural Hinglish (code-mixed Hindi and English). "
        "Keep your tone sympathetic yet enthusiastic. Use natural pausing and rhythm. "
        "Keep responses brief, conversational, and direct. "
        "When the user wants to record a credit (udhaar), receive a payment, check stock, add items to a bill/cart, "
        "create a bill, or check the daily summary, you MUST invoke the `execute_ledger_command` tool. "
        "Pass the user's complete spoken instruction exactly as the `command` argument to the tool. "
        "After the tool returns, summarize the result or speak the tool's confirmation message to the user."
        '<emotion value="enthusiastic"/>' # SSML-like emotion guidance for Sonic
    )
    
    return LlmAgent(
        model="openrouter/qwen/qwen3-coder:free",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        tools=[execute_ledger_command, end_call],
        config=LlmConfig(
            system_prompt=system_prompt,
            introduction="Namaste! Mein aapka ledger aur POS assistant hoon. Boliye, aaj kya help karoon?",
        ),
    )

# --- 3. App Runner ---

app = VoiceAgentApp(
    get_agent=get_agent,
)

if __name__ == "__main__":
    app.run(port=8001)
