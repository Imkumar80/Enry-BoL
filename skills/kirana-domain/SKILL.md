---
name: kirana-domain
description: Domain knowledge for Indian kirana store operations, billing, inventory management, udhaar/credit systems, and GST compliance. Use when implementing business logic, designing data models, or building integrations for Indian retail/SMB applications.
license: MIT
---

# Kirana Domain Knowledge Skill

Deep domain expertise for building software that serves Indian kirana stores, SMBs, and micro-entrepreneurs.

## 1. Understanding the Kirana Ecosystem

**A kirana store is NOT a Western convenience store.** Key differences:

- **Credit (Udhaar) is the default**, not the exception. 60%+ transactions are on credit.
- **No barcode scanners** in most shops. Products identified by name/brand.
- **Handwritten ledgers (Khata)** are still the primary bookkeeping method.
- **Relationships > Transactions.** A shopkeeper knows every regular customer by name.
- **Mixed inventory** — same shop sells groceries, toiletries, stationery, phone recharges.
- **Distributor-driven supply chain** — orders placed via phone call to distributor, not online.

## 2. Data Model

### Core Entities

```python
# Products
class Product:
    id: str
    name: str                    # Primary name (English)
    name_hindi: str              # Hindi name (Devanagari)
    aliases: list[str]           # All known pronunciations/spellings
    category: str                # grocery, toiletry, snack, beverage, etc.
    hsn_code: str                # GST HSN code
    gst_rate: float              # 0%, 5%, 12%, 18%, 28%
    unit: str                    # packet, kg, litre, piece, dozen
    mrp: float                   # Maximum Retail Price (printed on product)
    selling_price: float         # Actual selling price (may differ from MRP)
    wholesale_price: float       # Price from distributor
    stock_quantity: float        # Current stock
    reorder_level: float         # Alert when stock falls below this
    expiry_tracking: bool        # Whether to track expiry dates

# Customers (Grahak)
class Customer:
    id: str
    name: str                    # As known to shopkeeper
    phone: str                   # For UPI/WhatsApp
    address: str                 # Optional, for delivery
    credit_limit: float          # Max udhaar allowed
    current_balance: float       # Current udhaar amount
    relationship: str            # regular, occasional, new

# Transactions
class Transaction:
    id: str
    customer_id: str
    items: list[BillItem]
    total_amount: float
    paid_amount: float           # Could be partial
    credit_amount: float         # Udhaar portion
    payment_mode: str            # cash, upi, credit, mixed
    gst_invoice_number: str      # If GST invoice generated
    timestamp: datetime
    voice_command_id: str        # Link back to the voice command that created this

# Credit/Udhaar Ledger
class CreditEntry:
    id: str
    customer_id: str
    amount: float
    type: str                    # "credit_given" or "payment_received"
    description: str             # What was bought / payment note
    balance_after: float         # Running balance
    timestamp: datetime
    voice_command_id: str
```

### Important Business Rules

1. **MRP is law.** You CANNOT sell above MRP (Maximum Retail Price) in India. Selling below MRP is fine.
2. **Udhaar has no interest.** Kirana credit is informal, interest-free, trust-based.
3. **Partial payments are normal.** A customer might pay ₹300 against ₹500 udhaar.
4. **Returns are verbal.** "Yeh Maggi expired hai, badal do" — exchange, no formal return process.
5. **Daily settlement.** Cash drawer should match total cash sales at end of day.
6. **Distributor credit cycle.** Shop owner also takes credit from distributor (usually 7-30 day terms).

## 3. GST Compliance

### Tax Structure

```python
GST_RATES = {
    "essential_food": 0.0,       # Rice, wheat, milk, eggs, fresh vegetables
    "packaged_food": 5.0,        # Packaged rice, sugar, tea, spices
    "processed_food": 12.0,      # Ghee, butter, fruit juice, namkeen
    "toiletries": 18.0,          # Soap, shampoo, toothpaste
    "luxury_fmcg": 28.0,         # Aerated drinks, tobacco
}

# Threshold for GST registration
GST_REGISTRATION_THRESHOLD = 4000000  # ₹40 lakh annual turnover
COMPOSITION_SCHEME_LIMIT = 15000000    # ₹1.5 crore for flat rate scheme
```

### Invoice Requirements

For a valid GST invoice, ALWAYS include:
- Seller GSTIN
- Buyer GSTIN (if B2B, >₹2.5 lakh)
- Invoice number (sequential, no gaps)
- Date of issue
- Description of goods with HSN code
- Quantity and unit
- Taxable value
- Tax rate and amount (CGST + SGST or IGST)
- Total amount
- QR code (if annual turnover > ₹500 crore)

### Composite Dealer Simplification

Most kiranas are **Composite Dealers** (turnover < ₹1.5 crore):
- Flat tax rate (1% for traders)
- Cannot collect tax from customers
- Cannot issue tax invoices (only "Bill of Supply")
- Cannot claim input tax credit
- Simpler quarterly filing

**When building voice commands for GST, always ask:** "Is this shop a regular dealer or composite dealer?" The billing flow differs significantly.

## 4. Common Voice Command Patterns

### Inventory Commands
```
"Ek carton Parle-G aaya hai" → add_inventory(product="Parle-G", qty=1, unit="carton")
"Doodh ka 20 litre stock update karo" → update_stock(product="Milk", qty=20, unit="litre")
"Kitna Surf bacha hai?" → check_stock(product="Surf Excel")
"Kaunsa maal khatam hone wala hai?" → low_stock_alert()
"Aaj ka stock report do" → daily_stock_report()
```

### Billing Commands
```
"Ramesh ka bill banao" → create_bill(customer="Ramesh")
"Bill mein 2 kg chini add karo" → add_to_bill(product="Sugar", qty=2, unit="kg")
"Total kitna hua?" → calculate_bill_total()
"Bill print karo" → print_bill()
"UPI se payment hua" → mark_payment(mode="upi")
```

### Udhaar/Credit Commands
```
"Ramesh ko 500 rupaye udhaar likh do" → add_credit(customer="Ramesh", amount=500)
"Suresh ne 200 diye" → record_payment(customer="Suresh", amount=200)
"Ramesh ka kitna udhaar hai?" → check_credit(customer="Ramesh")
"Sabka udhaar list karo" → list_all_credits()
"Ramesh ko WhatsApp pe reminder bhejo" → send_reminder(customer="Ramesh", via="whatsapp")
```

## 5. UX Principles for Kirana Owners

1. **Speak, don't type.** Every feature must be accessible via voice.
2. **Hindi-first UI.** Default language is Hindi with English mixed in (Hinglish).
3. **Big buttons, simple screens.** Many users are 40+ with reading glasses.
4. **Auditory confirmation.** Always speak back what was done: "Ramesh ka ₹500 udhaar add hua. Total ₹1200 ho gaya."
5. **No jargon.** Say "udhaar" not "credit," say "bill" not "invoice," say "maal" not "inventory."
6. **WhatsApp integration is expected.** This is the primary communication channel.
7. **Works on ₹8,000 Android phones.** Optimize for low-end hardware.
8. **Data backup anxiety is real.** Prominently show "data saved" / "backup complete" messages.
