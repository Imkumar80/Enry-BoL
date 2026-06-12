import os
import re
import json
import urllib.request
import urllib.error
from pydantic import BaseModel, Field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# We use the official google-generativeai SDK
import google.generativeai as genai

# Define Structured Output Schema
class ExtractedEntities(BaseModel):
    product: Optional[str] = Field(None, description="Name of the product (e.g. Maggi, Britannia Biscuit, Surf Excel, Amul Milk, Chini)")
    quantity: Optional[float] = Field(None, description="Quantity of the item (e.g. 2, 0.5, 1.5)")
    unit: Optional[str] = Field(None, description="Unit of the quantity (e.g. packet, kg, litre, piece)")
    amount: Optional[float] = Field(None, description="Money amount in rupees (e.g. 500, 150)")
    customer: Optional[str] = Field(None, description="Name of the customer (e.g. Ramesh, Suresh, Pinky)")

class ParsedCommand(BaseModel):
    intent: str = Field(description="Intent name: add_inventory, remove_inventory, update_quantity, create_bill, add_to_bill, record_credit, record_payment, check_stock, check_credit, daily_summary, unknown")
    entities: ExtractedEntities
    original_text: str
    explanation: str = Field(description="Short description of what was understood in English/Hinglish.")

# Initialize Gemini Client if API key is present
api_key = os.getenv("GEMINI_API_KEY")
model_initialized = False

sarvam_api_key = os.getenv("SARVAM_API_KEY")
sarvam_model = os.getenv("SARVAM_MODEL", "sarvam-2b-v0.5")

if api_key:
    try:
        genai.configure(api_key=api_key)
        # We use gemini-1.5-flash as it is highly efficient and supports structured output
        model = genai.GenerativeModel('gemini-1.5-flash')
        model_initialized = True
        print("Gemini client successfully initialized for intent parsing.")
    except Exception as e:
        print(f"Error initializing Gemini: {e}. Falling back to Regex parser.")

def parse_with_gemini(text: str) -> ParsedCommand:
    """Parses text using Gemini structured output."""
    prompt = f"""
    You are the NLU parser for Enry, a Hinglish Voice OS layer for Indian shopkeepers (Kirana stores).
    Your task is to analyze the user's voice transcript and convert it to the requested JSON schema.
    
    Transcript: "{text}"
    
    Follow these rules:
    1. Identify the 'intent' out of:
       - 'create_bill' (e.g., "Ramesh ka bill banao", "bill banao Suresh ka")
       - 'add_to_bill' (e.g., "Ek packet biscuit add karo", "do kilo chini daal do")
       - 'record_credit' (e.g., "Ramesh ko 500 rupaye udhaar likh do", "Ramesh ka 500 udhaar likho")
       - 'record_payment' (e.g., "Suresh ne 200 rupaye diye", "Pinky ne 120 rs pay kiya")
       - 'check_stock' (e.g., "Kitna Surf Excel bacha hai?", "check stock of Maggi")
       - 'check_credit' (e.g., "Ramesh ka kitna udhaar hai?")
       - 'daily_summary' (e.g., "Aaj ka total kya hua?", "daily summary check karo")
       - 'add_inventory' (e.g., "Maggi do packet badhao")
       - 'update_quantity' (e.g., "Chini ka stock 50 kg kar do")
       
    2. Extract entities:
       - 'customer': Customer name (e.g., Ramesh, Suresh, Pinky)
       - 'product': Product name, normalized to standard catalogue name if possible (e.g., "biscuit" -> "Britannia Biscuit", "surf" -> "Surf Excel", "chini" -> "Chini", "doodh" -> "Amul Milk", "maggi" -> "Maggi Noodles")
       - 'quantity': Parse Hinglish and digits (e.g., "ek" -> 1, "do" -> 2, "aadha" -> 0.5, "dhai" -> 2.5)
       - 'unit': Parse unit if mentioned (e.g., "packet", "kg", "litre")
       - 'amount': Parse financial values (e.g., "500", "panch sau" -> 500, "150 rs" -> 150)
       
    3. Generate a friendly 'explanation' in English/Hinglish confirming what will happen (e.g., "Adding 1 packet of Britannia Biscuit to the bill" or "Recording 500 rupees udhaar for Ramesh").
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=ParsedCommand
            )
        )
        return ParsedCommand.model_validate_json(response.text)
    except Exception as e:
        print(f"Gemini API invocation failed: {e}. Falling back to Regex parser.")
        return parse_with_regex(text)

def parse_with_sarvam(text: str) -> ParsedCommand:
    """Parses text using Sarvam AI Chat completions API."""
    url = "https://api.sarvam.ai/v1/chat/completions"
    
    system_prompt = """You are the NLU parser for Enry, a Hinglish Voice OS layer for Indian shopkeepers (Kirana stores).
Analyze the user's voice transcript and convert it to a structured JSON object.

You MUST output ONLY valid JSON matching this exact schema:
{
  "intent": "Intent name, one of: add_inventory, remove_inventory, update_quantity, create_bill, add_to_bill, record_credit, record_payment, check_stock, check_credit, daily_summary, unknown",
  "entities": {
    "product": "Product name or null. Normalize to standard names like: 'Britannia Biscuit', 'Surf Excel', 'Chini', 'Amul Milk', 'Maggi Noodles'",
    "quantity": "Quantity number or null (e.g. 1.0, 0.5)",
    "unit": "Unit name or null (e.g. 'packet', 'kg', 'litre')",
    "amount": "Rupee amount or null (e.g. 500.0)",
    "customer": "Customer name or null"
  },
  "original_text": "The exact original transcript",
  "explanation": "A short confirmation message in Hinglish/English confirming the action."
}

Rules:
1. Identify intent: 'create_bill', 'add_to_bill', 'record_credit', 'record_payment', 'check_stock', 'check_credit', 'daily_summary', 'add_inventory', 'update_quantity'.
2. Extract entities and normalize products.
3. Provide a friendly explanation.
4. Output ONLY JSON, with no markdown code blocks (no ```json).
"""

    headers = {
        "Content-Type": "application/json",
        "api-subscription-key": sarvam_api_key
    }
    
    payload = {
        "model": sarvam_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Transcript: \"{text}\""}
        ],
        "temperature": 0.1
    }
    
    try:
        req = urllib.request.Request(
            url, 
            data=json.dumps(payload).encode("utf-8"), 
            headers=headers, 
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content = res_data["choices"][0]["message"]["content"].strip()
            
            # Clean markdown formatting if present
            if content.startswith("```"):
                lines = content.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
                
            return ParsedCommand.model_validate_json(content)
            
    except Exception as e:
        print(f"Sarvam API invocation failed: {e}. Falling back to Regex parser.")
        return parse_with_regex(text)

def parse_with_regex(text: str) -> ParsedCommand:
    """Fallback parser using regex rules for local/offline execution."""
    text_lower = text.lower().strip()
    
    # Defaults
    intent = "unknown"
    product = None
    quantity = None
    unit = None
    amount = None
    customer = None
    explanation = "Sorry, I didn't quite catch that. Could you repeat?"

    # Helper: Extract digits/Hinglish numbers
    num_map = {
        "ek": 1.0, "do": 2.0, "teen": 3.0, "char": 4.0, "paanch": 5.0,
        "che": 6.0, "saat": 7.0, "aath": 8.0, "nau": 9.0, "das": 10.0,
        "aadha": 0.5, "dhai": 2.5, "sade teen": 3.5, "sade char": 4.5,
        "sava": 1.25, "dedh": 1.5
    }
    
    # Try to find a quantity/amount number
    found_number = None
    # Check text numbers
    for k, v in num_map.items():
        if k in text_lower:
            found_number = v
            break
            
    # Check digits
    digit_match = re.search(r'(\d+(?:\.\d+)?)', text_lower)
    if digit_match:
        found_number = float(digit_match.group(1))

    # Helper: Extract customers
    customers = ["ramesh", "suresh", "pinky"]
    for c in customers:
        if c in text_lower:
            customer = c.capitalize()
            break

    # Helper: Extract products
    products = {
        "maggi": ("Maggi Noodles", "packet"),
        "biscuit": ("Britannia Biscuit", "packet"),
        "britannia": ("Britannia Biscuit", "packet"),
        "surf": ("Surf Excel", "kg"),
        "chini": ("Chini", "kg"),
        "sugar": ("Chini", "kg"),
        "doodh": ("Amul Milk", "litre"),
        "milk": ("Amul Milk", "litre"),
        "amul": ("Amul Milk", "litre")
    }
    for pk, (pname, punit) in products.items():
        if pk in text_lower:
            product = pname
            unit = punit
            break

    # 1. Intent: record_credit (Udhaar)
    # E.g. "Ramesh ko 500 rupaye udhaar likh do", "Ramesh ka 150 rs udhaar likho"
    if "udhaar" in text_lower or "credit" in text_lower or "likh do" in text_lower or "likho" in text_lower:
        if customer and found_number:
            intent = "record_credit"
            amount = found_number
            explanation = f"Recording ₹{amount:.2f} credit (udhaar) for {customer}."
        elif customer:
            intent = "check_credit"
            explanation = f"Checking credit balance for {customer}."

    # 2. Intent: record_payment
    # E.g. "Suresh ne 200 rupaye diye", "Pinky ne 120 rs pay kiya", "jama karo"
    elif "diye" in text_lower or "pay" in text_lower or "jama" in text_lower or "paid" in text_lower or "received" in text_lower:
        if customer and found_number:
            intent = "record_payment"
            amount = found_number
            explanation = f"Recording ₹{amount:.2f} payment received from {customer}."

    # 3. Intent: create_bill
    # E.g. "Ramesh ka bill banao", "bill banao"
    elif "bill banao" in text_lower or "create bill" in text_lower or "new bill" in text_lower:
        intent = "create_bill"
        explanation = f"Creating a new bill/cart for {customer if customer else 'a walk-in customer'}."

    # 4. Intent: add_to_bill
    # E.g. "Ek packet biscuit add karo", "do kilo chini add karo", "bill me daal do"
    elif "add" in text_lower or "karo" in text_lower or "daal do" in text_lower:
        if product:
            intent = "add_to_bill"
            quantity = found_number if found_number else 1.0
            explanation = f"Adding {quantity} {unit}(s) of {product} to the current bill."
        else:
            # Fallback if just generic add
            explanation = "I understood you wanted to add something, but couldn't identify the product. Try saying 'biscuit add karo'."

    # 5. Intent: check_stock / check_credit
    elif "stock" in text_lower or "kitna" in text_lower or "bacha hai" in text_lower or "check" in text_lower:
        if product:
            intent = "check_stock"
            explanation = f"Checking current stock level for {product}."
        elif customer:
            intent = "check_credit"
            explanation = f"Checking credit balance for {customer}."

    # 6. Intent: daily_summary
    elif "total" in text_lower or "summary" in text_lower or "aaj ka" in text_lower:
        intent = "daily_summary"
        explanation = "Checking today's total sales and outstanding credit."

    # Form response matching schema
    entities = ExtractedEntities(
        product=product,
        quantity=quantity,
        unit=unit,
        amount=amount,
        customer=customer
    )
    return ParsedCommand(
        intent=intent,
        entities=entities,
        original_text=text,
        explanation=explanation
    )

def parse_command(text: str) -> ParsedCommand:
    """Main entrypoint for NLU parsing."""
    if sarvam_api_key:
        return parse_with_sarvam(text)
    elif model_initialized:
        return parse_with_gemini(text)
    else:
        return parse_with_regex(text)

if __name__ == "__main__":
    # Test cases
    tests = [
        "Ek packet biscuit add karo",
        "Ramesh ka bill banao",
        "Ramesh ko 500 rupaye udhaar likh do",
        "Suresh ne 200 rupaye diye",
        "Kitna Surf Excel bacha hai?",
        "Ramesh ka kitna udhaar hai?",
        "Aaj ka total kya hua?"
    ]
    print("Running NLU Parser tests with Offline Regex engine:")
    for t in tests:
        res = parse_with_regex(t)
        print(f"Text: '{t}' -> Intent: {res.intent} | Entities: {res.entities.model_dump(exclude_none=True)}")
