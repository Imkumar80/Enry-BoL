from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import os
import uvicorn
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

import db
import parser

app = FastAPI(
    title="Enry Voice OS API",
    description="Backend API for the voice-enabled digital Khata ledger, POS, and inventory system.",
    version="1.0.0"
)

# Initialize Database Schema & Seeds
db.init_db()

# Mount Frontend Static Files
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_root():
    """Redirects to the frontend index page."""
    return RedirectResponse(url="/static/index.html")

# --- Pydantic Schemas for Requests ---
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

from fastapi import Depends

# --- API Routes ---

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

# --- Intent Handlers for Voice Command Router ---

def handle_record_credit(entities, action_result, conn):
    if not entities.customer or not entities.amount:
        action_result["explanation"] = "Missing customer name or credit amount. Try again."
    else:
        new_bal = db.record_khata_transaction(
            customer_name=entities.customer,
            action_type="credit",
            amount=entities.amount,
            description="Recorded via Voice OS",
            conn=conn
        )
        action_result["action_taken"] = f"Recorded credit. New balance for {entities.customer}: ₹{new_bal:.2f}"
        action_result["success"] = True

def handle_record_payment(entities, action_result, conn):
    if not entities.customer or not entities.amount:
        action_result["explanation"] = "Missing customer name or payment amount. Try again."
    else:
        new_bal = db.record_khata_transaction(
            customer_name=entities.customer,
            action_type="payment",
            amount=entities.amount,
            description="Received payment via Voice OS",
            conn=conn
        )
        action_result["action_taken"] = f"Recorded payment. Remaining balance for {entities.customer}: ₹{new_bal:.2f}"
        action_result["success"] = True

def handle_create_bill(entities, action_result, conn):
    action_result["action_taken"] = f"Active cart selected for customer: {entities.customer or 'Walk-in'}"
    action_result["success"] = True

def handle_add_to_bill(entities, action_result, conn):
    if not entities.product:
        action_result["explanation"] = "Could not identify product name in command."
    else:
        db_item = db.get_inventory_item_by_name(entities.product, conn)
        if not db_item:
            action_result["explanation"] = f"Product '{entities.product}' not found in catalog."
        else:
            qty = entities.quantity or 1.0
            action_result["product_details"] = {
                "name": db_item["name"],
                "price": db_item["price"],
                "quantity": qty,
                "unit": db_item["unit"],
                "total": db_item["price"] * qty
            }
            action_result["action_taken"] = f"Added {qty} {db_item['unit']}(s) of {db_item['name']} to active cart."
            action_result["success"] = True

def handle_check_stock(entities, action_result, conn):
    if not entities.product:
        action_result["explanation"] = "Product name not specified for stock check."
    else:
        db_item = db.get_inventory_item_by_name(entities.product, conn)
        if not db_item:
            action_result["explanation"] = f"Product '{entities.product}' not found."
        else:
            action_result["action_taken"] = f"{db_item['name']} stock is {db_item['stock']} {db_item['unit']}(s)."
            action_result["success"] = True

def handle_check_credit(entities, action_result, conn):
    if not entities.customer:
        action_result["explanation"] = "Customer name not specified."
    else:
        customer = db.get_customer_by_name(entities.customer, conn)
        if not customer:
            action_result["explanation"] = f"Customer '{entities.customer}' not found."
        else:
            action_result["action_taken"] = f"{customer['name']} has an outstanding balance of ₹{customer['balance']:.2f}."
            action_result["success"] = True

def handle_inventory_update(intent, entities, action_result, conn):
    if not entities.product or not entities.quantity:
        action_result["explanation"] = "Product name or quantity details missing."
    else:
        qty_change = entities.quantity if intent == "add_inventory" else None
        db_item = db.get_inventory_item_by_name(entities.product, conn)
        
        if not db_item:
            action_result["explanation"] = f"Product '{entities.product}' not found."
        else:
            if intent == "add_inventory":
                db.update_stock(db_item["name"], qty_change, conn)
                action_result["action_taken"] = f"Added {qty_change} to {db_item['name']}. New stock: {db_item['stock'] + qty_change}"
            else:
                conn.execute("UPDATE inventory SET stock = ? WHERE id = ?", (entities.quantity, db_item["id"]))
                conn.commit()
                action_result["action_taken"] = f"Set {db_item['name']} stock directly to {entities.quantity}."
            action_result["success"] = True

def handle_daily_summary(entities, action_result, conn):
    today_date = datetime.now().strftime('%Y-%m-%d')
    sales = conn.execute(
        "SELECT SUM(total_amount) as total FROM invoices WHERE date(timestamp) = ?",
        (today_date,)
    ).fetchone()
    
    credits = conn.execute(
        "SELECT SUM(amount) as total FROM transactions WHERE type = 'credit' AND date(timestamp) = ?",
        (today_date,)
    ).fetchone()
    
    payments = conn.execute(
        "SELECT SUM(amount) as total FROM transactions WHERE type = 'payment' AND date(timestamp) = ?",
        (today_date,)
    ).fetchone()
    
    sales_val = sales["total"] or 0.0
    credit_val = credits["total"] or 0.0
    payment_val = payments["total"] or 0.0
    
    action_result["action_taken"] = f"Today's total sales: ₹{sales_val:.2f}. Credits recorded: ₹{credit_val:.2f}. Payments received: ₹{payment_val:.2f}."
    action_result["success"] = True

# --- Main Voice Route ---

@app.post("/api/parse-command")
def parse_and_execute_command(req: CommandRequest, conn=Depends(db.get_db)):
    """Parses a Hinglish/English voice transcript and executes corresponding database action."""
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Transcript is empty.")

    # 1. Parse intent & entities
    parsed = parser.parse_command(text)
    intent = parsed.intent
    entities = parsed.entities
    
    action_result = {
        "intent": intent,
        "entities": entities.model_dump(exclude_none=True),
        "explanation": parsed.explanation,
        "action_taken": None,
        "success": False
    }

    # 2. Strategy Router Logic
    intent_handlers = {
        "record_credit": handle_record_credit,
        "record_payment": handle_record_payment,
        "create_bill": handle_create_bill,
        "add_to_bill": handle_add_to_bill,
        "check_stock": handle_check_stock,
        "check_credit": handle_check_credit,
        "daily_summary": handle_daily_summary,
    }

    try:
        if intent in intent_handlers:
            intent_handlers[intent](entities, action_result, conn)
        elif intent in ["add_inventory", "update_quantity"]:
            handle_inventory_update(intent, entities, action_result, conn)
        else:
            action_result["explanation"] = "I understood the words but couldn't map it to a valid action. Try saying 'Ek packet biscuit add karo' or 'Ramesh ka bill banao'."
    except Exception as e:
        action_result["explanation"] = f"System error executing action: {e}"
        action_result["success"] = False

    return action_result

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run("app:app", host=host, port=port, reload=True)
