"""
nlu_parser.py — Gemini-powered NLU for Enry Voice OS
======================================================
Architecture:
  1. Gemini 2.0 Flash is the primary brain — grounded with live DB context
     (every product name, every customer name injected into the system prompt).
  2. Regex engine is the offline fallback — no network needed.
  3. parse_command() is the single entrypoint used by voice_agent.py
"""

import os
import re
import json
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class ExtractedEntities(BaseModel):
    product:  str   = Field(default="",  description="Product name. Empty if not found.")
    quantity: float = Field(default=0.0, description="Quantity. 0.0 if not found.")
    unit:     str   = Field(default="",  description="Unit (packet/kg/litre/…). Empty if not found.")
    amount:   float = Field(default=0.0, description="Rupee amount. 0.0 if not found.")
    customer: str   = Field(default="",  description="Customer name. Empty if not found.")

class ParsedCommand(BaseModel):
    intent:       str              = Field(description=(
        "One of: create_bill | add_to_bill | record_credit | record_payment | "
        "check_stock | check_credit | daily_summary | add_inventory | "
        "remove_inventory | update_quantity | unknown"
    ))
    entities:     ExtractedEntities
    original_text: str
    explanation:  str  = Field(description="Short Hinglish/English confirmation.")
    engine:       str  = Field(default="unknown")

# ---------------------------------------------------------------------------
# Gemini client (initialised once)
# ---------------------------------------------------------------------------

_gemini_client: genai.Client | None = None

def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key or "your_gemini_api_key_here" in api_key:
            raise EnvironmentError("GEMINI_API_KEY not configured in .env")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client

# ---------------------------------------------------------------------------
# DB context helpers — live catalogue injected into every prompt
# ---------------------------------------------------------------------------

def _fetch_db_context() -> tuple[list[str], list[str]]:
    """Returns (product_names, customer_names) from the live DB."""
    try:
        import db
        conn = db.get_db_connection()
        products  = [row["name"] for row in db.get_all_inventory(conn)]
        customers = [row["name"] for row in db.get_all_customers(conn)]
        conn.close()
        return products, customers
    except Exception as e:
        print(f"[NLU] DB context fetch failed: {e}")
        return [], []


def _build_system_prompt(products: list[str], customers: list[str]) -> str:
    product_list  = ", ".join(products)  if products  else "none in DB yet"
    customer_list = ", ".join(customers) if customers else "none in DB yet"

    return f"""You are the NLU brain for Enry, a Hinglish Voice OS for Indian kirana shopkeepers.

== LIVE STORE CATALOGUE ==
Products  : {product_list}
Customers : {customer_list}

== YOUR JOB ==
Parse the shopkeeper's spoken sentence into a JSON object — no markdown, no extra text.

== OUTPUT SCHEMA ==
{{
  "intent": "<see intent list below>",
  "entities": {{
    "product":  "<exact product name from catalogue, closest fuzzy match, or empty string>",
    "quantity": <number, 0.0 if absent>,
    "unit":     "<packet | kg | litre | piece | dozen | etc., or empty string>",
    "amount":   <rupee amount as number, 0.0 if absent>,
    "customer": "<exact customer name from catalogue, closest fuzzy match, or empty string>"
  }},
  "original_text": "<exact transcript>",
  "explanation":   "<one friendly Hinglish sentence confirming the action>"
}}

== VALID INTENTS ==
- create_bill     → "Ramesh ka bill banao", "new bill for Suresh"
- add_to_bill     → "do packet biscuit add karo", "bill mein doodh daal do"
- record_credit   → "Ramesh ko 500 udhaar likh do", "Pinky ka 200 udhaar"
- record_payment  → "Suresh ne 200 diye", "Pinky ne 120 rs pay kiya", "jama karo"
- check_stock     → "Maggi kitna bacha hai?", "surf excel ka stock check karo"
- check_credit    → "Ramesh ka kitna udhaar hai?"
- daily_summary   → "aaj ka total", "daily summary batao"
- add_inventory   → "50 kg chini aaya", "stock mein Maggi add karo"
- update_quantity → "chini ka stock 50 kg kar do"
- unknown         → anything unrelated

== HINGLISH NUMBERS ==
ek=1, do=2, teen=3, char=4, paanch=5, che=6, saat=7, aath=8, nau=9, das=10
aadha=0.5, dedh=1.5, dhai=2.5, sava=1.25, panch sau=500, ek hazaar=1000

== FUZZY MATCHING RULES ==
Always try to match spoken words to the closest catalogue entry:
  "surf wala"   → "Surf Excel"
  "maggi packet"→ "Maggi Noodles"
  "doodh"       → match the milk product in catalogue
  "Ramesh bhai" → "Ramesh"
  "chini"       → match the sugar product

Output ONLY valid JSON. No prose, no code fences."""

# ---------------------------------------------------------------------------
# JSON parsing helper
# ---------------------------------------------------------------------------

def _parse_json_response(content: str) -> dict:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        content = match.group(0)
    return json.loads(content)


def _assemble(data: dict, text: str, engine: str) -> ParsedCommand:
    data["original_text"] = text
    data["engine"] = engine
    if "entities" not in data:
        data["entities"] = {}
    return ParsedCommand.model_validate(data)

# ---------------------------------------------------------------------------
# Engine 1 — Gemini 2.0 Flash (main brain)
# ---------------------------------------------------------------------------

def _parse_with_gemini(text: str, system_prompt: str) -> ParsedCommand:
    client = _get_gemini_client()

    response = client.models.generate_content(
        model="gemini-2.0-flash-lite",
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.1,
            response_mime_type="application/json",
        ),
        contents=f'Transcript: "{text}"',
    )

    data = _parse_json_response(response.text)
    return _assemble(data, text, "gemini-2.0-flash")

# ---------------------------------------------------------------------------
# Engine 2 — Regex (offline fallback, zero network)
# ---------------------------------------------------------------------------

_HINGLISH_NUMS = {
    "panch sau": 500.0, "ek hazaar": 1000.0,   # multi-word first
    "ek": 1.0, "do": 2.0, "teen": 3.0, "char": 4.0, "paanch": 5.0,
    "che": 6.0, "saat": 7.0, "aath": 8.0, "nau": 9.0, "das": 10.0,
    "aadha": 0.5, "dedh": 1.5, "dhai": 2.5, "sava": 1.25,
}

# Common Hindi aliases that may not appear in DB names
_PRODUCT_ALIASES: dict[str, list[str]] = {
    "Amul Milk":        ["doodh", "dudh", "milk", "amul"],
    "Chini":            ["chini", "sugar"],
    "Surf Excel":       ["surf"],
    "Maggi Noodles":    ["maggi"],
    "Britannia Biscuit":["biscuit", "britannia"],
}

def _parse_with_regex(text: str, system_prompt: str) -> ParsedCommand:
    """Offline keyword + DB-context fallback. Never touches the network."""
    tl = text.lower().strip()
    product = ""; customer = ""; quantity = 0.0; unit = ""; amount = 0.0

    # --- Number extraction ---
    found_number: float | None = None
    for phrase, val in sorted(_HINGLISH_NUMS.items(), key=lambda x: -len(x[0])):
        if phrase in tl:
            found_number = val
            break
    m = re.search(r'(\d+(?:\.\d+)?)', tl)
    if m:
        found_number = float(m.group(1))

    # --- Entity extraction: parse DB list from system_prompt ---
    prod_match = re.search(r'Products\s*:\s*(.+)', system_prompt)
    cust_match = re.search(r'Customers\s*:\s*(.+)', system_prompt)
    db_products  = [p.strip() for p in prod_match.group(1).split(",")] if prod_match else []
    db_customers = [c.strip() for c in cust_match.group(1).split(",")] if cust_match else []

    for p in sorted(db_products, key=len, reverse=True):
        keywords = p.lower().split()
        aliases = _PRODUCT_ALIASES.get(p, [])
        if (p.lower() in tl
                or any(kw in tl and len(kw) > 3 for kw in keywords)
                or any(a in tl for a in aliases)):
            product = p; break

    for c in sorted(db_customers, key=len, reverse=True):
        if c.lower() in tl:
            customer = c; break

    # Guess customer from Hinglish grammar
    if not customer:
        gm = re.search(r'(\w+)\s+(?:ka|ko|ne|bhai)\b', tl)
        if gm:
            cand = gm.group(1)
            if cand not in {"aaj", "kitna", "kya", "bill", "udhaar", "stock"}:
                customer = cand.capitalize()

    # Guess product from position before verb
    if not product:
        vm = re.search(r'(\w+)\s+(?:add|karo|daal|lao|de do)', tl)
        if vm:
            cand = vm.group(1)
            if cand not in {"packet", "kilo", "litre", "ek", "do", "teen", "me", "mein", "jama"}:
                product = cand.capitalize()

    # --- Unit extraction ---
    for u in ["packet", "kg", "kilo", "litre", "piece", "peti", "dozen"]:
        if u in tl:
            unit = u; break

    # --- Intent classification (specific → general, verbless last) ---
    intent = "unknown"
    if any(w in tl for w in ["udhaar", "credit", "likh do", "likho"]):
        intent = "check_credit" if not found_number else "record_credit"
        amount = found_number or 0.0
    elif any(w in tl for w in ["diye", "pay", "jama", "paid", "received", "mila"]):
        intent = "record_payment"; amount = found_number or 0.0
    elif any(w in tl for w in ["bill banao", "create bill", "new bill", "naya bill"]):
        intent = "create_bill"
    elif any(w in tl for w in ["stock", "kitna", "bacha hai", "check"]):
        intent = "check_stock" if product else ("check_credit" if customer else "unknown")
    elif any(w in tl for w in ["total", "summary", "aaj ka", "daily"]):
        intent = "daily_summary"
    elif any(w in tl for w in ["aaya", "stock mein", "add kiya", "mila hai"]):
        intent = "add_inventory"; quantity = found_number or 0.0
    elif any(w in tl for w in ["add", "karo", "daal do", "daal", "bill mein", "bill me"]):
        intent = "add_to_bill" if product else "unknown"
        quantity = found_number or 1.0
    elif product:   # verbless: "surf wala do packet"
        intent = "add_to_bill"
        quantity = found_number or 1.0

    expl_map = {
        "add_to_bill":    f"Adding {quantity} {unit} of {product} to the bill.",
        "record_credit":  f"Recording ₹{amount:.0f} udhaar for {customer}.",
        "record_payment": f"Recording ₹{amount:.0f} payment from {customer}.",
        "create_bill":    f"Creating new bill for {customer or 'walk-in customer'}.",
        "check_stock":    f"Checking stock for {product}.",
        "check_credit":   f"Checking udhaar balance for {customer}.",
        "daily_summary":  "Fetching today's sales summary.",
        "add_inventory":  f"Adding {quantity} {unit} of {product} to inventory.",
        "unknown":        "Samajh nahi aaya. Zara phir se bolein?",
    }

    return ParsedCommand(
        intent=intent,
        entities=ExtractedEntities(product=product, quantity=quantity,
                                   unit=unit, amount=amount, customer=customer),
        original_text=text,
        explanation=expl_map.get(intent, "Samajh nahi aaya. Zara phir se bolein?"),
        engine="regex",
    )

# ---------------------------------------------------------------------------
# Engine chain
# ---------------------------------------------------------------------------

_ENGINE_PRIORITY = [
    ("gemini",  _parse_with_gemini),
    ("regex",   _parse_with_regex),   # always available offline
]

def parse_command(text: str) -> ParsedCommand:
    """
    Main NLU entrypoint.

    1. Fetches live DB context (all products + customers).
    2. Builds a grounded system prompt.
    3. Tries Gemini first, falls back to offline regex.
    """
    products, customers = _fetch_db_context()
    system_prompt = _build_system_prompt(products, customers)

    for engine_name, engine_fn in _ENGINE_PRIORITY:
        try:
            result = engine_fn(text, system_prompt)
            print(f"[NLU] ✓ {engine_name}: {result.intent} | {result.entities.model_dump(exclude_defaults=True)}")
            return result
        except EnvironmentError as e:
            print(f"[NLU] {engine_name} skipped: {e}")
        except Exception as e:
            print(f"[NLU] {engine_name} failed: {e}")

    print("[NLU] All engines failed.")
    return ParsedCommand(
        intent="unknown", entities=ExtractedEntities(),
        original_text=text, explanation="Samajh nahi aaya. Zara phir se bolein?",
        engine="none",
    )

# ---------------------------------------------------------------------------
# CLI test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        "Ek packet biscuit add karo",
        "Ramesh ka bill banao",
        "Ramesh ko panch sau rupaye udhaar likh do",
        "Suresh ne 200 rupaye diye",
        "Kitna Surf Excel bacha hai?",
        "Ramesh ka kitna udhaar hai?",
        "Aaj ka total kya hua?",
        "50 kg chini aaya",
        "Do litre doodh bill mein daal do",
        "surf wala do packet",
        "Pinky bhai ka 150 jama karo",
        "xyzzy blorp flibble",
    ]

    print("=" * 60)
    print("NLU Parser — Gemini 2.0 Flash test run")
    print("=" * 60)
    for t in tests:
        result = parse_command(t)
        print(f"\nInput  : {t}")
        print(f"Engine : {result.engine}")
        print(f"Intent : {result.intent}")
        ent = result.entities.model_dump(exclude_defaults=True)
        print(f"Entities: {ent}")
        print(f"Explain: {result.explanation}")