"""
agent/tools.py — typed business tools.
"""
from datetime import datetime
from langchain_core.tools import tool
import db
from agent.session import get_session_id

def _positive(value, name):
    value = float(value)
    if value <= 0 or value != value or value == float("inf"):
        raise ValueError(f"{name} must be greater than zero")
    return value

@tool
def check_stock(product_name: str) -> str:
    """Check stock and price for a product."""
    with db.get_db_connection() as conn:
        item = db.get_inventory_item_by_name(product_name, conn)
        if not item:
            return f"Product '{product_name}' not found in catalog."
        return f"{item['name']} stock is {item['stock']} {item['unit']}(s). Price: ₹{item['price']} per {item['unit']}."

@tool
def check_customer_credit(customer_name: str) -> str:
    """Check outstanding customer udhaar."""
    with db.get_db_connection() as conn:
        customer = db.get_customer_by_name(customer_name, conn)
        if not customer:
            return f"Customer '{customer_name}' not found in ledger."
        return f"{customer['name']} has an outstanding balance of ₹{customer['balance']:.2f}."

@tool
def record_credit(customer_name: str, amount: float) -> str:
    """Record udhaar. Only execute after explicit confirmation."""
    amount = _positive(amount, "amount")
    with db.get_db_connection() as conn:
        new_bal = db.record_khata_transaction(customer_name, "credit", amount, "Recorded via Voice OS", conn)
        conn.commit()
        return f"Recorded credit of ₹{amount:.2f} for {customer_name}. New balance: ₹{new_bal:.2f}."

@tool
def record_payment(customer_name: str, amount: float) -> str:
    """Record customer payment. Only execute after explicit confirmation."""
    amount = _positive(amount, "amount")
    with db.get_db_connection() as conn:
        new_bal = db.record_khata_transaction(customer_name, "payment", amount, "Received payment via Voice OS", conn)
        conn.commit()
        return f"Recorded payment of ₹{amount:.2f} from {customer_name}. Remaining balance: ₹{new_bal:.2f}."

@tool
def create_bill(customer_name: str = "Walk-in Customer") -> str:
    """Create/reset the current session cart."""
    session_id = get_session_id()
    if not session_id:
        raise RuntimeError("No voice session context")
    db.create_or_reset_cart(session_id, customer_name or "Walk-in Customer")
    return f"Started new bill for customer: {customer_name or 'Walk-in Customer'}."

@tool
def add_to_bill(product_name: str, quantity: float = 1.0) -> str:
    """Add a product to the current session cart."""
    quantity = _positive(quantity, "quantity")
    session_id = get_session_id()
    if not session_id:
        raise RuntimeError("No voice session context")
    cart = db.add_cart_item(session_id, product_name, quantity)
    if not cart["items"]:
        return "Cart is empty."
    return (
        f"Added to cart. Current total is ₹{cart['total']:.2f}. "
        f"{len(cart['items'])} item line(s)."
    )

@tool
def checkout_bill() -> str:
    """Checkout the current session cart and create an invoice."""
    session_id = get_session_id()
    if not session_id:
        raise RuntimeError("No voice session context")
    result = db.checkout_cart(session_id)
    return f"Checkout complete. Invoice #{result['invoice_id']} created for ₹{result['total']:.2f}."

@tool
def get_daily_summary() -> str:
    """Get today's sales, credits and payments."""
    with db.get_db_connection() as conn:
        day = datetime.now().strftime("%Y-%m-%d")
        sales = conn.execute("SELECT COALESCE(SUM(total_amount),0) total FROM invoices WHERE date(timestamp)=?", (day,)).fetchone()["total"]
        credits = conn.execute("SELECT COALESCE(SUM(amount),0) total FROM transactions WHERE type='credit' AND date(timestamp)=?", (day,)).fetchone()["total"]
        payments = conn.execute("SELECT COALESCE(SUM(amount),0) total FROM transactions WHERE type='payment' AND date(timestamp)=?", (day,)).fetchone()["total"]
        return f"Today's sales: ₹{sales:.2f}. Credits recorded: ₹{credits:.2f}. Payments received: ₹{payments:.2f}."

@tool
def add_inventory(product_name: str, quantity: float) -> str:
    """Add stock to an existing product."""
    quantity = _positive(quantity, "quantity")
    with db.get_db_connection() as conn:
        item = db.get_inventory_item_by_name(product_name, conn)
        if not item:
            return f"Product '{product_name}' not found."
        if not db.update_stock(product_name, quantity, conn):
            raise RuntimeError("Inventory update failed")
        conn.commit()
        return f"Added {quantity} to {item['name']}. New stock: {item['stock'] + quantity} {item['unit']}(s)."

@tool
def update_inventory(product_name: str, quantity: float) -> str:
    """Set an exact non-negative inventory stock level."""
    quantity = float(quantity)
    if quantity < 0 or quantity != quantity or quantity == float("inf"):
        raise ValueError("quantity must be non-negative")
    with db.get_db_connection() as conn:
        item = db.get_inventory_item_by_name(product_name, conn)
        if not item:
            return f"Product '{product_name}' not found."
        conn.execute("UPDATE inventory SET stock=? WHERE id=?", (quantity, item["id"]))
        conn.commit()
        return f"Set {item['name']} stock to {quantity} {item['unit']}(s)."

FINANCIAL_TOOLS = {"record_credit", "record_payment"}
MUTATING_TOOLS = FINANCIAL_TOOLS | {"create_bill", "add_to_bill", "checkout_bill", "add_inventory", "update_inventory"}

TOOLS_LIST = [
    check_stock, check_customer_credit, record_credit, record_payment,
    create_bill, add_to_bill, checkout_bill, get_daily_summary,
    add_inventory, update_inventory,
]
