"""
agent/tools.py — Typed Business Tools for LangGraph
=====================================================
Each tool directly calls existing db.py functions.
No duplicate database logic. No giant string-based ledger tool.

Financial tools (record_credit, record_payment) are marked as
requiring confirmation — the graph handles the confirmation flow.
"""

from langchain_core.tools import tool
from typing import Optional
from datetime import datetime
import db


@tool
def check_stock(product_name: str) -> str:
    """Check the inventory stock for a given product. Use when user asks about stock levels, availability, or 'kitna bacha hai'."""
    conn = db.get_db_connection()
    try:
        item = db.get_inventory_item_by_name(product_name, conn)
        if not item:
            return f"Product '{product_name}' not found in catalog."
        return f"{item['name']} stock is {item['stock']} {item['unit']}(s). Price: ₹{item['price']} per {item['unit']}."
    finally:
        conn.close()


@tool
def check_customer_credit(customer_name: str) -> str:
    """Check the outstanding udhaar (credit) balance for a customer. Use when user asks about someone's balance or 'kitna udhaar hai'."""
    conn = db.get_db_connection()
    try:
        customer = db.get_customer_by_name(customer_name, conn)
        if not customer:
            return f"Customer '{customer_name}' not found in ledger."
        return f"{customer['name']} has an outstanding balance of ₹{customer['balance']:.2f}."
    finally:
        conn.close()


@tool
def record_credit(customer_name: str, amount: float) -> str:
    """Record that a customer took items on udhaar (credit). IMPORTANT: This modifies the ledger. Only call after user confirmation."""
    conn = db.get_db_connection()
    try:
        new_bal = db.record_khata_transaction(customer_name, "credit", amount, "Recorded via Voice OS", conn)
        conn.commit()
        return f"Recorded credit of ₹{amount:.2f} for {customer_name}. New balance: ₹{new_bal:.2f}."
    except Exception as e:
        return f"Failed to record credit: {e}"
    finally:
        conn.close()


@tool
def record_payment(customer_name: str, amount: float) -> str:
    """Record that a customer made a payment towards their udhaar. IMPORTANT: This modifies the ledger. Only call after user confirmation."""
    conn = db.get_db_connection()
    try:
        new_bal = db.record_khata_transaction(customer_name, "payment", amount, "Received payment via Voice OS", conn)
        conn.commit()
        return f"Recorded payment of ₹{amount:.2f} from {customer_name}. Remaining balance: ₹{new_bal:.2f}."
    except Exception as e:
        return f"Failed to record payment: {e}"
    finally:
        conn.close()


@tool
def add_to_bill(product_name: str, quantity: float = 1.0) -> str:
    """Add a product to the active shopping cart/bill for checkout. Use when user says 'add karo', 'bill mein daal do', etc."""
    conn = db.get_db_connection()
    try:
        item = db.get_inventory_item_by_name(product_name, conn)
        if not item:
            return f"Product '{product_name}' not found in catalog."
        total = item['price'] * quantity
        return (f"Added {quantity} {item['unit']}(s) of {item['name']} to cart. "
                f"Price: ₹{item['price']} × {quantity} = ₹{total:.2f}")
    finally:
        conn.close()


@tool
def create_bill(customer_name: str = "Walk-in Customer") -> str:
    """Start a new bill/cart for a customer. Use when user says 'bill banao', 'new bill', etc."""
    return f"Started new bill for customer: {customer_name}."


@tool
def get_daily_summary() -> str:
    """Get today's total sales, credits recorded, and payments received. Use for 'aaj ka total', 'daily summary', etc."""
    conn = db.get_db_connection()
    try:
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

        s = sales["total"] or 0.0
        c = credits["total"] or 0.0
        p = payments["total"] or 0.0
        return f"Today's sales: ₹{s:.2f}. Credits recorded: ₹{c:.2f}. Payments received: ₹{p:.2f}."
    finally:
        conn.close()


@tool
def add_inventory(product_name: str, quantity: float) -> str:
    """Add stock to an existing product in inventory. Use when 'stock aaya', 'add kiya', etc."""
    conn = db.get_db_connection()
    try:
        item = db.get_inventory_item_by_name(product_name, conn)
        if not item:
            return f"Product '{product_name}' not found. Cannot add stock."
        success = db.update_stock(product_name, quantity, conn)
        conn.commit()
        if success:
            return f"Added {quantity} to {item['name']}. New stock: {item['stock'] + quantity} {item['unit']}(s)."
        return f"Failed to update stock for '{product_name}'."
    finally:
        conn.close()


@tool
def update_inventory(product_name: str, quantity: float) -> str:
    """Set the stock level for a product to an exact value. Use when 'stock set karo', 'stock X kar do'."""
    conn = db.get_db_connection()
    try:
        item = db.get_inventory_item_by_name(product_name, conn)
        if not item:
            return f"Product '{product_name}' not found."
        conn.execute("UPDATE inventory SET stock = ? WHERE id = ?", (quantity, item["id"]))
        conn.commit()
        return f"Set {item['name']} stock to {quantity} {item['unit']}(s)."
    finally:
        conn.close()


# Tools that require financial confirmation before execution
FINANCIAL_TOOLS = {"record_credit", "record_payment"}

# All tools list
TOOLS_LIST = [
    check_stock,
    check_customer_credit,
    record_credit,
    record_payment,
    add_to_bill,
    create_bill,
    get_daily_summary,
    add_inventory,
    update_inventory,
]
