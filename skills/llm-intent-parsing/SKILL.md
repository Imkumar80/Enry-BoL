---
name: llm-intent-parsing
description: Guidelines for using LLMs (Gemini, GPT, Claude) for structured intent classification and entity extraction from Hinglish voice transcripts. Covers prompt engineering, structured output, few-shot examples, and fallback strategies. Use when implementing the NLU layer of the voice pipeline.
license: MIT
---

# LLM Intent Parsing Skill

How to use LLMs effectively for parsing Hinglish voice commands into structured intents and entities.

## 1. Structured Output is Non-Negotiable

**Never rely on free-text LLM output for action execution.** Always use structured output (JSON schema enforcement).

```python
# Gemini structured output example
from google import genai
from pydantic import BaseModel, Field

class VoiceCommand(BaseModel):
    """Structured output for parsed voice command."""
    intent: str = Field(
        description="One of: add_inventory, remove_inventory, update_quantity, "
                    "create_bill, add_to_bill, record_credit, record_payment, "
                    "check_stock, check_credit, daily_summary, generate_gst_invoice, "
                    "unknown"
    )
    product: str | None = Field(default=None, description="Product name, normalized to English")
    quantity: float | None = Field(default=None, description="Numeric quantity")
    unit: str | None = Field(default=None, description="Unit: packet, kg, litre, piece, dozen")
    customer_name: str | None = Field(default=None, description="Customer name if mentioned")
    amount: float | None = Field(default=None, description="Monetary amount in INR")
    confidence: float = Field(description="Confidence score 0.0 to 1.0")
    needs_clarification: bool = Field(default=False, description="True if command is ambiguous")
    clarification_question: str | None = Field(default=None, description="Question to ask user if ambiguous")

# Use with Gemini
client = genai.Client()
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config=genai.types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=VoiceCommand,
    ),
)
```

## 2. System Prompt Template

```markdown
You are a voice command parser for an Indian kirana (grocery) store management system.

Your job is to parse Hinglish (Hindi-English mixed) voice transcripts into structured commands.

## Rules:
1. The transcript comes from speech recognition and may contain errors. Use context to fix obvious ASR mistakes.
2. Hindi numerals should be converted to numbers: "ek" = 1, "do" = 2, "teen" = 3, etc.
3. Product names should be normalized to their standard English names (e.g., "parle ji" → "Parle-G").
4. Customer names should be kept as-is (proper nouns).
5. Currency is always INR (₹). "rupaye", "rupee", "rs" all mean INR.
6. If the command is ambiguous, set needs_clarification = true and suggest a clarification question.
7. If you cannot determine the intent at all, set intent = "unknown".

## Domain context:
- "udhaar" / "udhar" = credit/loan given to customer
- "khata" = ledger/account
- "bill banao" = create invoice
- "maal" = stock/inventory
- "hata do" / "nikaal do" = remove
- "add karo" / "daal do" = add
- "kitna bacha" = how much remaining (stock check)
- "total" / "hisaab" = sum/calculation
```

## 3. Few-Shot Examples (Include These in Every Prompt)

```json
[
  {
    "transcript": "Ek packet Britannia biscuit add karo",
    "output": {
      "intent": "add_inventory",
      "product": "Britannia Biscuit",
      "quantity": 1,
      "unit": "packet",
      "customer_name": null,
      "amount": null,
      "confidence": 0.95,
      "needs_clarification": false
    }
  },
  {
    "transcript": "Ramesh ko pachaas rupaye udhaar likh do",
    "output": {
      "intent": "record_credit",
      "product": null,
      "quantity": null,
      "unit": null,
      "customer_name": "Ramesh",
      "amount": 50.0,
      "confidence": 0.92,
      "needs_clarification": false
    }
  },
  {
    "transcript": "Do kilo chini aur ek packet surf bill mein daal do",
    "output": {
      "intent": "add_to_bill",
      "product": null,
      "quantity": null,
      "unit": null,
      "customer_name": null,
      "amount": null,
      "confidence": 0.88,
      "needs_clarification": true,
      "clarification_question": "Bill mein do items hain: 2 kg Sugar aur 1 packet Surf Excel. Dono add karoon?"
    }
  },
  {
    "transcript": "Kitna surf bacha hai",
    "output": {
      "intent": "check_stock",
      "product": "Surf Excel",
      "quantity": null,
      "unit": null,
      "customer_name": null,
      "amount": null,
      "confidence": 0.96,
      "needs_clarification": false
    }
  },
  {
    "transcript": "Aaj ka total kya hua",
    "output": {
      "intent": "daily_summary",
      "product": null,
      "quantity": null,
      "unit": null,
      "customer_name": null,
      "amount": null,
      "confidence": 0.97,
      "needs_clarification": false
    }
  }
]
```

## 4. Multi-Item Command Handling

Kirana owners often bundle multiple items in one utterance:

```
"Ramesh ka bill banao — do kilo chini, ek packet Surf, aur teen Parle-G"
```

This is a **compound command**. Parse it into:
```json
{
  "intent": "create_bill_with_items",
  "customer_name": "Ramesh",
  "items": [
    {"product": "Sugar", "quantity": 2, "unit": "kg"},
    {"product": "Surf Excel", "quantity": 1, "unit": "packet"},
    {"product": "Parle-G", "quantity": 3, "unit": "piece"}
  ],
  "confidence": 0.90
}
```

**Design choice:** Either:
- Parse as single compound command (faster, more natural)
- Split into sequential atomic commands (more reliable, easier to confirm)

Recommend: **Compound for read-only, sequential for writes.** A bill preview can show all items at once, but each credit entry should be confirmed individually.

## 5. Fallback: Rule-Based Intent Matching

When LLM is unavailable (offline, quota exceeded), use regex-based fallback:

```python
import re

INTENT_PATTERNS = {
    "add_inventory": [
        r"(?:add|daal|rakh)\s+(?:karo|do|de)",
        r"(?:aaya|aaye|aa\s+gaya)\s+(?:hai|hain)",
        r"stock\s+(?:mein|me)\s+(?:add|daal)",
    ],
    "check_stock": [
        r"kitna?\s+(?:bacha|baki|hai|hain|stock)",
        r"stock\s+(?:check|dekh|batao)",
        r"kya\s+(?:bacha|baki)\s+hai",
    ],
    "record_credit": [
        r"udhaar\s+(?:likh|likho|daal|add)",
        r"(?:credit|udhar)\s+(?:de|do|karo)",
        r"khata\s+(?:mein|me)\s+(?:likh|daal)",
    ],
    "record_payment": [
        r"(?:paisa|paise|rupaye|rupee)\s+(?:diye|mile|aaye)",
        r"(?:payment|bhugtan)\s+(?:hua|kiya|aaya)",
        r"udhaar\s+(?:se|mein)\s+(?:kat|kata|minus)",
    ],
    "daily_summary": [
        r"aaj\s+ka\s+(?:total|hisaab|summary)",
        r"din\s+(?:bhar|ka)\s+(?:total|hisaab)",
    ],
}

def match_intent_regex(transcript: str) -> str:
    """Fallback intent matching using regex patterns."""
    transcript = transcript.lower().strip()
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, transcript):
                return intent
    return "unknown"
```

## 6. LLM Provider Selection

| Provider | Speed | Hinglish Quality | Cost | Offline | Recommendation |
|----------|-------|-----------------|------|---------|----------------|
| **Gemini 2.5 Flash** | ★★★★★ | ★★★★ | Low | No | **Primary: Fast + cheap + good structured output** |
| **Gemini 2.5 Pro** | ★★★ | ★★★★★ | Medium | No | Complex disambiguation cases |
| **GPT-4o Mini** | ★★★★ | ★★★★ | Low | No | Alternative to Gemini Flash |
| **Claude Haiku** | ★★★★ | ★★★ | Low | No | Good but weaker on Hindi |
| **Local Llama 3.2** | ★★★ | ★★★ | Free | Yes | **Offline fallback** |
| **Regex fallback** | ★★★★★ | ★★ | Free | Yes | Last resort, always available |

## 7. Prompt Optimization Rules

1. **Keep system prompt under 1000 tokens.** Longer prompts increase latency without proportional accuracy gains.
2. **Include 5 few-shot examples** — one for each major intent category.
3. **Temperature = 0.** Intent parsing is deterministic, not creative.
4. **Cache the system prompt.** Use Gemini's context caching for the static portion.
5. **Stream the response.** Don't wait for full generation if you only need the intent field first.
6. **Measure token usage.** Track input/output tokens per command for cost monitoring.
