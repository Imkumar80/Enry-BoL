from langchain_core.tools import tool
from typing import Optional
from datetime import datetime
import db

def _get_conn():
    # Helper to get a short-lived connection since tools are stateless in LangGraph
    # and shouldn't hold onto a connection pool indefinitely.
    import sqlite3
    conn = sqlite3.connect("khata.db")
    conn.row_factory = sqlite3.Row
    return conn

@tool
def record_credit(customer_name: str, amount: float) -> str:
    """Record that a customer took items on udhaar (credit)."""
    conn = _get_conn()
    try:
        new_bal = db.record_khata_transaction(customer_name, "credit", amount, "Recorded via Voice OS", conn)
        return f"Recorded credit. New balance for {customer_name}: ₹{new_bal:.2f}"
    except Exception as e:
        return f"Failed to record credit: {e}"
    finally:
        conn.close()

@tool
def record_payment(customer_name: str, amount: float) -> str:
    """Record that a customer made a payment towards their udhaar (settled balance)."""
    conn = _get_conn()
    try:
        new_bal = db.record_khata_transaction(customer_name, "payment", amount, "Received payment via Voice OS", conn)
        return f"Recorded payment. Remaining balance for {customer_name}: ₹{new_bal:.2f}"
    except Exception as e:
        return f"Failed to record payment: {e}"
    finally:
        conn.close()

@tool
def check_stock(product_name: str) -> str:
    """Check the inventory stock for a given product."""
    conn = _get_conn()
    try:
        item = db.get_inventory_item_by_name(product_name, conn)
        if not item:
            return f"Product '{product_name}' not found in catalog."
        return f"{item['name']} stock is {item['stock']} {item['unit']}(s)."
    finally:
        conn.close()

@tool
def check_credit(customer_name: str) -> str:
    """Check the outstanding udhaar (credit) balance for a customer."""
    conn = _get_conn()
    try:
        customer = db.get_customer_by_name(customer_name, conn)
        if not customer:
            return f"Customer '{customer_name}' not found."
        return f"{customer['name']} has an outstanding balance of ₹{customer['balance']:.2f}."
    finally:
        conn.close()

@tool
def add_to_bill(product_name: str, quantity: float = 1.0) -> str:
    """Add a product to the active shopping cart (bill) for checkout."""
    conn = _get_conn()
    try:
        item = db.get_inventory_item_by_name(product_name, conn)
        if not item:
            return f"Product '{product_name}' not found in catalog."
        
        # We don't save the cart to the DB yet, we just tell the agent it's added.
        # The frontend state manages the cart array based on this intent.
        return f"Added {quantity} {item['unit']}(s) of {item['name']} to active cart. Price is ₹{item['price']} per unit."
    finally:
        conn.close()

@tool
def create_bill(customer_name: str) -> str:
    """Select a customer and start a new bill for them."""
    return f"Started bill for customer: {customer_name}"

@tool
def daily_summary() -> str:
    """Get the total sales, credits, and payments for today."""
    conn = _get_conn()
    try:
        today_date = datetime.now().strftime('%Y-%m-%d')
        sales = conn.execute("SELECT SUM(total_amount) as total FROM invoices WHERE date(timestamp) = ?", (today_date,)).fetchone()
        credits = conn.execute("SELECT SUM(amount) as total FROM transactions WHERE type = 'credit' AND date(timestamp) = ?", (today_date,)).fetchone()
        payments = conn.execute("SELECT SUM(amount) as total FROM transactions WHERE type = 'payment' AND date(timestamp) = ?", (today_date,)).fetchone()
        
        return (f"Today's sales: ₹{sales['total'] or 0.0:.2f}. "
                f"Credits recorded: ₹{credits['total'] or 0.0:.2f}. "
                f"Payments received: ₹{payments['total'] or 0.0:.2f}.")
    finally:
        conn.close()

TOOLS_LIST = [record_credit, record_payment, check_stock, check_credit, add_to_bill, create_bill, daily_summary]
