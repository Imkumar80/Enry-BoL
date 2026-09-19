"""
app.py — Enry Voice OS API Server
====================================
Single FastAPI application serving:
  - Dashboard HTML/CSS/JS at /static/
  - REST APIs for customers, inventory, transactions, checkout
  - Voice WebSocket at /ws/voice
  - Legacy /api/parse-command and /api/tts for compatibility
"""

from fastapi import FastAPI, HTTPException, Body, Response, UploadFile, File, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import os
import uvicorn
import logging
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

import db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("app")

app = FastAPI(
    title="Enry Voice OS API",
    description="Backend API for the voice-enabled digital Khata ledger, POS, and inventory system.",
    version="2.0.0"
)

# Initialize Database Schema & Seeds
db.init_db()

# Mount Frontend Static Files
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Mount Voice Gateway WebSocket
from voice.gateway import router as voice_router
app.include_router(voice_router)


@app.get("/")
def read_root():
    """Redirects to the frontend index page."""
    return RedirectResponse(url="/static/index.html")


# --- Pydantic Schemas ---

class CommandRequest(BaseModel):
    text: str

class CheckoutItem(BaseModel):
    product_name: str
    quantity: float

class CheckoutRequest(BaseModel):
    customer_name: Optional[str] = None
    items: List[CheckoutItem]

class CustomerRequest(BaseModel):
    name: str
    phone: Optional[str] = ""
    balance: Optional[float] = 0.0

class InventoryRequest(BaseModel):
    name: str
    price: float
    stock: float
    unit: str


# --- REST API Routes (preserved for dashboard) ---

@app.get("/api/customers")
def get_customers(conn=Depends(db.get_db)):
    return db.get_all_customers(conn)

@app.get("/api/inventory")
def get_inventory(conn=Depends(db.get_db)):
    return db.get_all_inventory(conn)

@app.get("/api/transactions")
def get_transactions(conn=Depends(db.get_db)):
    return db.get_all_transactions(conn)

@app.post("/api/customers")
def add_customer(req: CustomerRequest, conn=Depends(db.get_db)):
    try:
        conn.execute(
            "INSERT INTO customers (name, phone, balance) VALUES (?, ?, ?)",
            (req.name, req.phone, req.balance)
        )
        conn.commit()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Customer already exists or invalid data: {e}")
    return {"status": "success", "message": f"Customer {req.name} added successfully."}

@app.post("/api/inventory")
def add_inventory_item(req: InventoryRequest, conn=Depends(db.get_db)):
    try:
        conn.execute(
            "INSERT INTO inventory (name, price, stock, unit) VALUES (?, ?, ?, ?)",
            (req.name, req.price, req.stock, req.unit)
        )
        conn.commit()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Product already exists or invalid data: {e}")
    return {"status": "success", "message": f"Product {req.name} added successfully."}

@app.post("/api/checkout")
def checkout(req: CheckoutRequest, conn=Depends(db.get_db)):
    if not req.items:
        raise HTTPException(status_code=400, detail="Cannot checkout an empty cart.")

    formatted_items = [{"product_name": item.product_name, "quantity": item.quantity} for item in req.items]
    invoice_id = db.create_invoice(req.customer_name or "Walk-in Customer", formatted_items, conn)

    if not invoice_id:
        raise HTTPException(status_code=400, detail="Failed to create invoice. Verify items are in stock.")

    return {"status": "success", "invoice_id": invoice_id, "message": "Checkout completed successfully."}


# --- Legacy /api/parse-command (preserved for dashboard typed commands when WS not connected) ---

@app.post("/api/parse-command")
def parse_and_execute_command(req: CommandRequest, conn=Depends(db.get_db)):
    """Parses a Hinglish/English voice transcript and executes corresponding database action."""
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Transcript is empty.")

    import nlu_parser
    parsed = nlu_parser.parse_command(text)
    intent = parsed.intent
    entities = parsed.entities

    action_result = {
        "intent": intent,
        "entities": entities.model_dump(exclude_none=True),
        "explanation": parsed.explanation,
        "action_taken": None,
        "success": False
    }

    try:
        if intent == "record_credit":
            if not entities.customer or not entities.amount:
                action_result["explanation"] = "Missing customer name or credit amount."
            else:
                new_bal = db.record_khata_transaction(
                    customer_name=entities.customer, action_type="credit",
                    amount=entities.amount, description="Recorded via Voice OS", conn=conn
                )
                action_result["action_taken"] = f"Recorded credit. New balance for {entities.customer}: ₹{new_bal:.2f}"
                action_result["success"] = True

        elif intent == "record_payment":
            if not entities.customer or not entities.amount:
                action_result["explanation"] = "Missing customer name or payment amount."
            else:
                new_bal = db.record_khata_transaction(
                    customer_name=entities.customer, action_type="payment",
                    amount=entities.amount, description="Received payment via Voice OS", conn=conn
                )
                action_result["action_taken"] = f"Recorded payment. Remaining balance for {entities.customer}: ₹{new_bal:.2f}"
                action_result["success"] = True

        elif intent == "create_bill":
            action_result["action_taken"] = f"Active cart selected for customer: {entities.customer or 'Walk-in'}"
            action_result["success"] = True

        elif intent == "add_to_bill":
            if not entities.product:
                action_result["explanation"] = "Could not identify product name."
            else:
                db_item = db.get_inventory_item_by_name(entities.product, conn)
                if not db_item:
                    action_result["explanation"] = f"Product '{entities.product}' not found."
                else:
                    qty = entities.quantity or 1.0
                    action_result["product_details"] = {
                        "name": db_item["name"], "price": db_item["price"],
                        "quantity": qty, "unit": db_item["unit"],
                        "total": db_item["price"] * qty
                    }
                    action_result["action_taken"] = f"Added {qty} {db_item['unit']}(s) of {db_item['name']} to cart."
                    action_result["success"] = True

        elif intent == "check_stock":
            if not entities.product:
                action_result["explanation"] = "Product name not specified."
            else:
                db_item = db.get_inventory_item_by_name(entities.product, conn)
                if not db_item:
                    action_result["explanation"] = f"Product '{entities.product}' not found."
                else:
                    action_result["action_taken"] = f"{db_item['name']} stock is {db_item['stock']} {db_item['unit']}(s)."
                    action_result["success"] = True

        elif intent == "check_credit":
            if not entities.customer:
                action_result["explanation"] = "Customer name not specified."
            else:
                customer = db.get_customer_by_name(entities.customer, conn)
                if not customer:
                    action_result["explanation"] = f"Customer '{entities.customer}' not found."
                else:
                    action_result["action_taken"] = f"{customer['name']} has ₹{customer['balance']:.2f} outstanding."
                    action_result["success"] = True

        elif intent == "daily_summary":
            today_date = datetime.now().strftime('%Y-%m-%d')
            sales = conn.execute("SELECT SUM(total_amount) as total FROM invoices WHERE date(timestamp) = ?", (today_date,)).fetchone()
            credits = conn.execute("SELECT SUM(amount) as total FROM transactions WHERE type = 'credit' AND date(timestamp) = ?", (today_date,)).fetchone()
            payments = conn.execute("SELECT SUM(amount) as total FROM transactions WHERE type = 'payment' AND date(timestamp) = ?", (today_date,)).fetchone()
            s_val = sales["total"] or 0.0
            c_val = credits["total"] or 0.0
            p_val = payments["total"] or 0.0
            action_result["action_taken"] = f"Today's sales: ₹{s_val:.2f}. Credits: ₹{c_val:.2f}. Payments: ₹{p_val:.2f}."
            action_result["success"] = True

        elif intent in ["add_inventory", "update_quantity"]:
            if not entities.product or not entities.quantity:
                action_result["explanation"] = "Product name or quantity missing."
            else:
                db_item = db.get_inventory_item_by_name(entities.product, conn)
                if not db_item:
                    action_result["explanation"] = f"Product '{entities.product}' not found."
                else:
                    if intent == "add_inventory":
                        db.update_stock(db_item["name"], entities.quantity, conn)
                        action_result["action_taken"] = f"Added {entities.quantity} to {db_item['name']}."
                    else:
                        conn.execute("UPDATE inventory SET stock = ? WHERE id = ?", (entities.quantity, db_item["id"]))
                        conn.commit()
                        action_result["action_taken"] = f"Set {db_item['name']} stock to {entities.quantity}."
                    action_result["success"] = True
        else:
            action_result["explanation"] = "Could not map to a valid action. Try again."
    except Exception as e:
        action_result["explanation"] = f"System error: {e}"
        action_result["success"] = False

    return action_result


# --- Legacy /api/tts (preserved as Cartesia REST fallback) ---

@app.get("/api/tts")
def tts_proxy(text: str):
    """Generates audio for given text using Cartesia TTS API."""
    from dotenv import load_dotenv
    load_dotenv(override=True)

    api_key = os.getenv("CARTESIA_API_KEY")
    if not api_key or api_key == "your_cartesia_key_here":
        raise HTTPException(status_code=400, detail="Cartesia API key not configured")

    voice_id = os.getenv("CARTESIA_VOICE_ID", "3b554273-4299-48b9-9aaf-eefd438e3941")
    url = "https://api.cartesia.ai/tts/bytes"

    payload = {
        "model_id": "sonic",
        "transcript": text,
        "voice": {"mode": "id", "id": voice_id},
        "output_format": {"container": "mp3", "encoding": "mp3", "sample_rate": 44100}
    }

    import json
    import urllib.request
    import urllib.error

    encoded_data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, data=encoded_data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Cartesia-Version": "2024-06-10",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as response:
            audio_bytes = response.read()
            return Response(content=audio_bytes, media_type="audio/mpeg")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8')
        raise HTTPException(status_code=e.code, detail=f"Cartesia error: {err_body}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run("app:app", host=host, port=port, reload=True)
