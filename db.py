import sqlite3
import os
from contextlib import closing

DB_PATH = os.path.join(os.path.dirname(__file__), "enry.db")

def get_db_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def get_db():
    """FastAPI dependency to yield a database connection."""
    with closing(get_db_connection()) as conn:
        yield conn

def init_db():
    """Initializes the database schema and seeds it with default data."""
    with closing(get_db_connection()) as conn:
        with conn:
            cursor = conn.cursor()

            # Create tables
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS carts (
                session_id TEXT PRIMARY KEY,
                customer_name TEXT NOT NULL DEFAULT 'Walk-in Customer',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS cart_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                price REAL NOT NULL,
                UNIQUE(session_id, product_id),
                FOREIGN KEY(product_id) REFERENCES inventory(id)
            );
            """)
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

    print("Database initialized successfully.")

# --- Database Helper Functions ---

def get_all_customers(conn=None):
    if conn:
        return [dict(row) for row in conn.execute("SELECT * FROM customers").fetchall()]
    with closing(get_db_connection()) as c:
        return [dict(row) for row in c.execute("SELECT * FROM customers").fetchall()]

def get_customer_by_name(name, conn=None):
    query = "SELECT * FROM customers WHERE LOWER(name) = LOWER(?)"
    if conn:
        customer = conn.execute(query, (name,)).fetchone()
        return dict(customer) if customer else None
    
    with closing(get_db_connection()) as c:
        customer = c.execute(query, (name,)).fetchone()
        return dict(customer) if customer else None

def get_all_inventory(conn=None):
    if conn:
        return [dict(row) for row in conn.execute("SELECT * FROM inventory").fetchall()]
    with closing(get_db_connection()) as c:
        return [dict(row) for row in c.execute("SELECT * FROM inventory").fetchall()]

def get_inventory_item_by_name(name, conn=None):
    query = "SELECT * FROM inventory WHERE name LIKE ? OR LOWER(name) = LOWER(?)"
    params = (f"%{name}%", name)
    if conn:
        item = conn.execute(query, params).fetchone()
        return dict(item) if item else None
    
    with closing(get_db_connection()) as c:
        item = c.execute(query, params).fetchone()
        return dict(item) if item else None

def update_stock(product_name, qty_change, conn=None):
    """Increments or decrements inventory stock."""
    # If connection passed, use it, else manage own connection
    if conn:
        item = get_inventory_item_by_name(product_name, conn)
        if not item:
            return False
        new_stock = item["stock"] + qty_change
        if new_stock < 0:
            return False
        conn.execute("UPDATE inventory SET stock = ? WHERE id = ?", (new_stock, item["id"]))
        return True

    with closing(get_db_connection()) as c:
        item = get_inventory_item_by_name(product_name, c)
        if not item:
            return False
        with c:
            new_stock = item["stock"] + qty_change
            if new_stock < 0:
                return False
            c.execute("UPDATE inventory SET stock = ? WHERE id = ?", (new_stock, item["id"]))
        return True

def record_khata_transaction(customer_name, action_type, amount, description="", conn=None):
    """Records a credit (udhaar) or payment transaction and updates customer balance."""
    def _execute(connection):
        customer = get_customer_by_name(customer_name, connection)
        if not customer:
            # Create customer if doesn't exist
            cursor = connection.cursor()
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
            raise ValueError("Invalid transaction type. Must be 'credit' or 'payment'.")

        connection.execute("UPDATE customers SET balance = ? WHERE id = ?", (new_balance, customer_id))
        connection.execute("""
        INSERT INTO transactions (customer_id, type, amount, description)
        VALUES (?, ?, ?, ?)
        """, (customer_id, action_type, amount, description))
        return new_balance

    if conn:
        return _execute(conn)
    else:
        with closing(get_db_connection()) as c:
            with c:
                return _execute(c)

def create_invoice(customer_name, items_list, conn=None):
    """
    Creates an invoice and items. Deducts inventory stock.
    items_list format: [{"product_name": str, "quantity": float}]
    """
    def _execute(connection):
        cursor = connection.cursor()
        total_amount = 0.0
        valid_items = []

        for item in items_list:
            db_item = get_inventory_item_by_name(item["product_name"], connection)
            if not db_item:
                continue
            
            qty = float(item["quantity"])
            if qty <= 0:
                raise ValueError("Invoice quantity must be greater than zero")
            if qty > db_item["stock"]:
                raise ValueError(
                    f"Insufficient stock for {db_item["name"]}: requested {qty}, available {db_item["stock"]}"
                )
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
            return None

        cursor.execute("INSERT INTO invoices (customer_name, total_amount) VALUES (?, ?)", (customer_name, total_amount))
        invoice_id = cursor.lastrowid

        for item in valid_items:
            cursor.execute("""
            INSERT INTO invoice_items (invoice_id, product_name, quantity, price, total)
            VALUES (?, ?, ?, ?, ?)
            """, (invoice_id, item["name"], item["qty"], item["price"], item["total"]))
            
            new_stock = item["current_stock"] - item["qty"]
            cursor.execute("UPDATE inventory SET stock = ? WHERE id = ?", (new_stock, item["id"]))

        return invoice_id

    if conn:
        return _execute(conn)
    else:
        with closing(get_db_connection()) as c:
            with c:
                return _execute(c)


def create_or_reset_cart(session_id, customer_name="Walk-in Customer", conn=None):
    own = conn is None
    connection = conn or get_db_connection()
    try:
        connection.execute(
            "INSERT INTO carts(session_id, customer_name) VALUES(?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET customer_name=excluded.customer_name, updated_at=CURRENT_TIMESTAMP",
            (session_id, customer_name),
        )
        connection.execute("DELETE FROM cart_items WHERE session_id = ?", (session_id,))
        if own:
            connection.commit()
        return True
    finally:
        if own:
            connection.close()


def add_cart_item(session_id, product_name, quantity, conn=None):
    if quantity <= 0:
        raise ValueError("quantity must be greater than zero")
    own = conn is None
    connection = conn or get_db_connection()
    try:
        item = get_inventory_item_by_name(product_name, connection)
        if not item:
            raise ValueError(f"Product '{product_name}' not found in catalog")
        cart = connection.execute("SELECT session_id FROM carts WHERE session_id = ?", (session_id,)).fetchone()
        if not cart:
            create_or_reset_cart(session_id, "Walk-in Customer", connection)
        connection.execute(
            "INSERT INTO cart_items(session_id, product_id, product_name, quantity, price) VALUES(?,?,?,?,?) "
            "ON CONFLICT(session_id, product_id) DO UPDATE SET quantity=quantity+excluded.quantity, price=excluded.price",
            (session_id, item["id"], item["name"], quantity, item["price"]),
        )
        if own:
            connection.commit()
        return get_cart(session_id, connection)
    finally:
        if own:
            connection.close()


def get_cart(session_id, conn=None):
    own = conn is None
    connection = conn or get_db_connection()
    try:
        cart = connection.execute("SELECT * FROM carts WHERE session_id = ?", (session_id,)).fetchone()
        items = [dict(r) for r in connection.execute(
            "SELECT product_name, quantity, price, quantity*price AS total FROM cart_items WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()]
        total = sum(i["total"] for i in items)
        return {
            "session_id": session_id,
            "customer_name": cart["customer_name"] if cart else "Walk-in Customer",
            "items": items,
            "total": total,
        }
    finally:
        if own:
            connection.close()


def checkout_cart(session_id, conn=None):
    own = conn is None
    connection = conn or get_db_connection()
    try:
        with connection:
            cart = get_cart(session_id, connection)
            if not cart["items"]:
                raise ValueError("Cart is empty")

            # Validate the complete cart before mutating anything.
            for item in cart["items"]:
                db_item = get_inventory_item_by_name(item["product_name"], connection)
                if not db_item:
                    raise ValueError(f"Product '{item['product_name']}' no longer exists")
                if item["quantity"] > db_item["stock"]:
                    raise ValueError(
                        f"Insufficient stock for {db_item['name']}: requested {item['quantity']}, available {db_item['stock']}"
                    )

            invoice_id = create_invoice(cart["customer_name"], cart["items"], connection)
            if invoice_id is None:
                raise ValueError("Unable to create invoice")
            connection.execute("DELETE FROM cart_items WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM carts WHERE session_id = ?", (session_id,))
            return {"invoice_id": invoice_id, "total": cart["total"], "items": cart["items"]}
    finally:
        if own:
            connection.close()


def get_all_transactions(conn=None):
    query = """
    SELECT t.*, c.name as customer_name 
    FROM transactions t
    JOIN customers c ON t.customer_id = c.id
    ORDER BY t.timestamp DESC
    """
    if conn:
        return [dict(row) for row in conn.execute(query).fetchall()]
    with closing(get_db_connection()) as c:
        return [dict(row) for row in c.execute(query).fetchall()]

if __name__ == "__main__":
    init_db()
