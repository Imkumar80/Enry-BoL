import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "bolna.db")

def get_db_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema and seeds it with default data."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        phone TEXT,
        balance REAL DEFAULT 0.0
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        type TEXT CHECK(type IN ('credit', 'payment')) NOT NULL,
        amount REAL NOT NULL,
        description TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers(id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        price REAL NOT NULL,
        stock REAL NOT NULL,
        unit TEXT NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT,
        total_amount REAL NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        quantity REAL NOT NULL,
        price REAL NOT NULL,
        total REAL NOT NULL,
        FOREIGN KEY (invoice_id) REFERENCES invoices(id)
    );
    """)

    # Seed Default Customers
    default_customers = [
        ("Ramesh", "9876543210", 350.00),
        ("Suresh", "9876543211", 0.00),
        ("Pinky", "9876543212", 120.50)
    ]
    for name, phone, balance in default_customers:
        cursor.execute("""
        INSERT OR IGNORE INTO customers (name, phone, balance)
        VALUES (?, ?, ?);
        """, (name, phone, balance))

    # Seed Default Inventory items
    default_inventory = [
        ("Maggi Noodles", 14.00, 100.0, "packet"),
        ("Britannia Biscuit", 30.00, 50.0, "packet"),
        ("Surf Excel", 120.00, 25.0, "kg"),
        ("Amul Milk", 28.00, 40.0, "litre"),
        ("Chini", 44.00, 200.0, "kg")  # Sugar
    ]
    for name, price, stock, unit in default_inventory:
        cursor.execute("""
        INSERT OR IGNORE INTO inventory (name, price, stock, unit)
        VALUES (?, ?, ?, ?);
        """, (name, price, stock, unit))

    conn.commit()
    conn.close()
    print("Database initialized successfully.")

# --- Database Helper Functions ---

def get_all_customers():
    conn = get_db_connection()
    customers = conn.execute("SELECT * FROM customers").fetchall()
    conn.close()
    return [dict(row) for row in customers]

def get_customer_by_name(name):
    conn = get_db_connection()
    customer = conn.execute("SELECT * FROM customers WHERE LOWER(name) = LOWER(?)", (name,)).fetchone()
    conn.close()
    return dict(customer) if customer else None

def get_all_inventory():
    conn = get_db_connection()
    items = conn.execute("SELECT * FROM inventory").fetchall()
    conn.close()
    return [dict(row) for row in items]

def get_inventory_item_by_name(name):
    conn = get_db_connection()
    # Fuzzy match using LIKE
    item = conn.execute("SELECT * FROM inventory WHERE name LIKE ? OR LOWER(name) = LOWER(?)", (f"%{name}%", name)).fetchone()
    conn.close()
    return dict(item) if item else None

def update_stock(product_name, qty_change):
    """Increments or decrements inventory stock."""
    conn = get_db_connection()
    item = get_inventory_item_by_name(product_name)
    if not item:
        conn.close()
        return False
    
    new_stock = item["stock"] + qty_change
    conn.execute("UPDATE inventory SET stock = ? WHERE id = ?", (new_stock, item["id"]))
    conn.commit()
    conn.close()
    return True

def record_khata_transaction(customer_name, action_type, amount, description=""):
    """Records a credit (udhaar) or payment transaction and updates customer balance."""
    conn = get_db_connection()
    customer = get_customer_by_name(customer_name)
    if not customer:
        # Create customer if doesn't exist
        cursor = conn.cursor()
        cursor.execute("INSERT INTO customers (name, phone, balance) VALUES (?, '', 0.0)", (customer_name,))
        customer_id = cursor.lastrowid
        customer_balance = 0.0
    else:
        customer_id = customer["id"]
        customer_balance = customer["balance"]

    if action_type == "credit":
        new_balance = customer_balance + amount
    elif action_type == "payment":
        new_balance = max(0.0, customer_balance - amount)
    else:
        conn.close()
        raise ValueError("Invalid transaction type. Must be 'credit' or 'payment'.")

    conn.execute("UPDATE customers SET balance = ? WHERE id = ?", (new_balance, customer_id))
    conn.execute("""
    INSERT INTO transactions (customer_id, type, amount, description)
    VALUES (?, ?, ?, ?)
    """, (customer_id, action_type, amount, description))

    conn.commit()
    conn.close()
    return new_balance

def create_invoice(customer_name, items_list):
    """
    Creates an invoice and items. Deducts inventory stock.
    items_list format: [{"product_name": str, "quantity": float}]
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Calculate total and verify stocks
    total_amount = 0.0
    valid_items = []

    for item in items_list:
        db_item = get_inventory_item_by_name(item["product_name"])
        if not db_item:
            # Skip or handle missing product
            continue
        
        qty = item["quantity"]
        price = db_item["price"]
        item_total = price * qty
        total_amount += item_total
        
        valid_items.append({
            "name": db_item["name"],
            "qty": qty,
            "price": price,
            "total": item_total,
            "id": db_item["id"],
            "current_stock": db_item["stock"]
        })

    if not valid_items:
        conn.close()
        return None

    # Insert Invoice
    cursor.execute("INSERT INTO invoices (customer_name, total_amount) VALUES (?, ?)", (customer_name, total_amount))
    invoice_id = cursor.lastrowid

    # Insert items and update stock
    for item in valid_items:
        cursor.execute("""
        INSERT INTO invoice_items (invoice_id, product_name, quantity, price, total)
        VALUES (?, ?, ?, ?, ?)
        """, (invoice_id, item["name"], item["qty"], item["price"], item["total"]))
        
        # Deduct stock
        new_stock = max(0.0, item["current_stock"] - item["qty"])
        cursor.execute("UPDATE inventory SET stock = ? WHERE id = ?", (new_stock, item["id"]))

    conn.commit()
    conn.close()
    return invoice_id

def get_all_transactions():
    conn = get_db_connection()
    txs = conn.execute("""
    SELECT t.*, c.name as customer_name 
    FROM transactions t
    JOIN customers c ON t.customer_id = c.id
    ORDER BY t.timestamp DESC
    """).fetchall()
    conn.close()
    return [dict(row) for row in txs]

if __name__ == "__main__":
    init_db()
