# ANTIGRAVITY_SKILLS.md — Voice OS for Kiranas & Indian SMBs

> Behavioral guidelines + domain expertise for building a context-aware Voice OS that lets Indian shopkeepers interact with billing, inventory, and ledger apps entirely through Hinglish voice commands.

**Project Codename:** BOLNA (बोलना — "to speak")
**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

---

## Part I: Foundational Coding Principles (Karpathy-Inspired)

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

**Voice OS specific:** Never assume the user meant "standard English STT" when they say "speech recognition." Always clarify: Hinglish code-mixed? Noisy environment? Streaming vs batch? Which ASR provider?

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

**Voice OS specific:** Don't build a "universal voice platform" when the user needs a kirana billing voice command. Start with one vertical, one language pair, one integration. Expand only when asked.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add voice input" → "User speaks Hinglish command, system returns structured JSON with intent + entities, test with 10 sample utterances"
- "Fix the ASR" → "Write a test with code-switched audio, verify WER < 25% for Hinglish"
- "Integrate inventory" → "Voice command 'Ek packet Maggi add karo' creates inventory entry, verify via API response"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## Part II: Voice OS Architecture Guidelines

### System Architecture (STT → LLM → Action Pipeline)

This project follows a multi-stage cascading pipeline:

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐    ┌────────────────┐    ┌───────────────┐
│  Microphone  │───▶│  ASR / STT   │───▶│  NLU / LLM   │───▶│ Action Router  │───▶│ Target App    │
│  (Audio In)  │    │  (Hinglish)  │    │  (Intent +   │    │ (Inventory,    │    │ (Billing,     │
│              │    │              │    │   Entities)  │    │  Ledger, GST)  │    │  Inventory,   │
└─────────────┘    └──────────────┘    └──────────────┘    └────────────────┘    │  Khata/Ledger)│
                                                                                 └───────────────┘
```

**Component Responsibilities:**

| Component | Purpose | Key Constraint |
|-----------|---------|----------------|
| **Audio Capture** | Hotkey-triggered or always-on mic input | < 100ms activation latency |
| **ASR/STT Engine** | Hinglish code-switched transcription | Must handle noisy shop environments |
| **NLU/LLM Brain** | Intent classification + entity extraction | Must understand kirana domain vocabulary |
| **Action Router** | Map parsed intent to target app API call | Idempotent, with confirmation prompts |
| **Target Integration** | Execute the action in billing/inventory app | Must support offline-first for poor connectivity |

### Critical Design Decisions

1. **Always streaming, not batch.** Users expect real-time feedback. Use WebSocket-based streaming ASR.
2. **Confirmation before destructive actions.** "Ramesh ka ₹500 udhaar delete karo" must always get a spoken confirmation before executing.
3. **Offline-first.** Indian shops have unreliable internet. Queue voice commands locally, sync when online.
4. **Audio preprocessing matters.** Indian retail environments are NOISY (TV, traffic, customers). Apply noise reduction before ASR.

---

## Part III: Hinglish & Indian Language Guidelines

### Code-Switching Patterns to Handle

The system MUST support all three types of code-switching:

| Pattern | Example | Handling |
|---------|---------|----------|
| **Inter-sentential** | "Add 2 packets. Ramesh ka bill banao." | Sentence-level language detection |
| **Intra-sentential** | "Ek packet Britannia biscuit add karo" | Word-level mixed parsing |
| **Intra-word** | "driving-wala", "adjust-karo" | Morphological awareness |

### ASR Provider Selection Matrix

| Provider | Hinglish Quality | Latency | Offline | Cost | Recommendation |
|----------|-----------------|---------|---------|------|----------------|
| **Sarvam AI (Saaras v3)** | ★★★★★ Native code-mix | Low | No | Paid API | **Primary choice for production** |
| **Whisper (fine-tuned)** | ★★★★ With fine-tuning | Medium | Yes | Self-hosted | **Best for offline/privacy** |
| **Bhashini/AI4Bharat** | ★★★ Multilingual focus | Medium | No | Free tier | Good for prototyping |
| **Deepgram** | ★★★ Hindi model | Low | No | Paid API | Fast but weaker on code-mix |
| **Google Cloud STT** | ★★★ Multi-language | Low | No | Paid API | Reliable but not code-mix native |

### Transliteration Rules

When processing Hinglish text output from ASR:
- Normalize Devanagari ↔ Roman script inconsistencies
- Handle common transliteration variants: "karo" / "kro" / "करो" are the same
- Maintain a domain-specific lexicon mapping (e.g., "Parle-G" = "पारले-जी" = "parle g" = "parle ji")
- Use `indic-transliteration` or `ai4bharat-transliteration` for script conversion

### NLU / Intent Parsing Rules

For the kirana domain, define these core intents:

```python
KIRANA_INTENTS = {
    "add_inventory":       "Ek packet Maggi add karo",
    "remove_inventory":    "Do packet Surf Excel hata do",
    "update_quantity":     "Doodh ka stock 50 litre kar do",
    "create_bill":         "Ramesh ka bill banao",
    "add_to_bill":         "Bill mein 2 kg chini add karo",
    "record_credit":       "Ramesh ko 500 rupaye udhaar likh do",
    "record_payment":      "Suresh ne 200 rupaye diye, udhaar se kata do",
    "check_stock":         "Kitna Surf Excel bacha hai?",
    "check_credit":        "Ramesh ka kitna udhaar hai?",
    "generate_gst_invoice":"GST invoice banao Ramesh ka",
    "daily_summary":       "Aaj ka total kya hua?",
}
```

Entity extraction must handle:
- **Product names:** Mixed Hindi/English brand names with fuzzy matching ("Britania" → "Britannia")
- **Quantities:** "ek" = 1, "do" = 2, "aadha" = 0.5, "dhai" = 2.5, "sava" = 1.25
- **Currency:** "rupaye" / "rupee" / "₹" / "paisa" / "rs"
- **Person names:** Indian names with flexible transliteration ("Ramesh" / "रमेश")
- **Units:** "kg" / "kilo" / "litre" / "packet" / "piece" / "दर्जन" (dozen)

---

## Part IV: Indian SMB Domain Knowledge

### Kirana Store Operations Model

```
┌─────────────────────────────────────────────────────────┐
│                    KIRANA STORE                          │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │ Inventory │  │ Billing  │  │  Khata   │  │  GST   │ │
│  │ (Stock)   │  │ (POS)    │  │ (Ledger) │  │ Filing │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───┬────┘ │
│       │              │              │             │      │
│       └──────────────┴──────────────┴─────────────┘      │
│                         │                                │
│                   Voice OS Layer                         │
└─────────────────────────────────────────────────────────┘
```

### Key Domain Concepts

| Concept | Hindi Term | Description |
|---------|------------|-------------|
| Credit/Debt | उधार (Udhaar) | Informal credit system, extremely common |
| Ledger | खाता (Khata) | Customer-wise credit tracking |
| Bill | बिल (Bill) | Point-of-sale invoice |
| Stock | माल (Maal) | Physical inventory |
| Wholesale | थोक (Thok) | Bulk purchase from distributor |
| Retail | खुदरा (Khudra) | Individual sale to customer |
| GST | जीएसटी | Goods & Services Tax compliance |
| HSN Code | एचएसएन कोड | Harmonized System of Nomenclature for products |
| CGST/SGST | सीजीएसटी/एसजीएसटी | Central/State GST components |

### Integration Targets

The Voice OS layer should support plugging into:

1. **Vyapar** — Most popular kirana billing app in India (REST API)
2. **Khatabook** — Digital ledger/udhaar tracking (API)
3. **Tally Prime** — Enterprise accounting (TDL/API)
4. **Custom POS** — Many shops use custom-built billing software
5. **WhatsApp Business** — For sending bills/reminders to customers
6. **UPI / Payment Gateways** — Razorpay, PhonePe, Google Pay for payment tracking

### GST Compliance Rules

When generating invoices via voice:
- Auto-apply correct GST rate based on HSN code
- CGST + SGST for intra-state, IGST for inter-state
- Maintain invoice numbering sequence (mandatory for GST)
- Support for composite dealer (no GST itemization) vs regular dealer
- Generate QR code on invoice (mandatory above threshold)

---

## Part V: Technical Stack Guidelines

### Recommended Tech Stack

```
Backend:
├── Python 3.11+ (FastAPI for API server)
├── WebSocket server for streaming audio
├── Celery + Redis for async task queue
├── SQLite/PostgreSQL for local/cloud data
└── Docker for deployment

ASR/Voice:
├── Sarvam AI Saaras v3 API (primary, Hinglish-native)
├── Whisper (openai-whisper or faster-whisper, fallback/offline)
├── VAD: Silero VAD or WebRTC VAD (voice activity detection)
└── Audio: PyAudio / sounddevice for capture

NLU/LLM:
├── Gemini 2.5 Flash/Pro (primary LLM for intent parsing)
├── Structured output with JSON schema enforcement
├── Few-shot prompting with kirana domain examples
└── Fallback: Local Llama/Mistral for offline mode

TTS (Response):
├── Sarvam AI TTS (Hinglish voice)
├── Google Cloud TTS (Hindi/English)
└── ElevenLabs (premium voice quality)

Frontend:
├── Electron (Desktop) / React Native (Mobile)
├── System tray app with global hotkey
├── Floating overlay widget for active app context
└── PWA fallback for budget Android devices
```

### Code Style & Conventions

- **Language:** Python for backend, TypeScript for frontend
- **Formatting:** Use `ruff` for Python, `prettier` for TypeScript
- **Type hints:** Always use type hints in Python (strict mypy)
- **Docstrings:** Google-style docstrings for all public functions
- **Testing:** pytest with fixtures for audio test data
- **Naming:**
  - Files: `snake_case.py`
  - Classes: `PascalCase`
  - Functions: `snake_case`
  - Constants: `UPPER_SNAKE_CASE`
  - Intents: `lower_snake_case` (e.g., `add_inventory`)
- **Error handling:** Use custom exception hierarchy rooted at `BolnaError`
- **Logging:** Use `structlog` for structured JSON logging
- **Config:** Use `pydantic-settings` for environment/config management

### Project Structure

```
bolna-voice-os/
├── src/
│   ├── audio/              # Audio capture, VAD, preprocessing
│   │   ├── capture.py      # Mic input + hotkey listener
│   │   ├── vad.py          # Voice activity detection
│   │   └── preprocess.py   # Noise reduction, normalization
│   ├── asr/                # Speech-to-text providers
│   │   ├── base.py         # Abstract ASR interface
│   │   ├── sarvam.py       # Sarvam AI Saaras integration
│   │   ├── whisper.py      # Local Whisper fallback
│   │   └── streaming.py    # WebSocket streaming ASR
│   ├── nlu/                # Natural language understanding
│   │   ├── intent.py       # Intent classifier
│   │   ├── entities.py     # Entity extractor (products, amounts, names)
│   │   ├── hinglish.py     # Hinglish normalization & transliteration
│   │   └── prompts/        # LLM prompt templates
│   │       ├── intent_classification.md
│   │       └── entity_extraction.md
│   ├── actions/            # Business logic action handlers
│   │   ├── inventory.py    # Add/remove/check stock
│   │   ├── billing.py      # Create/update bills
│   │   ├── ledger.py       # Udhaar/credit tracking
│   │   ├── gst.py          # GST invoice generation
│   │   └── router.py       # Intent → Action dispatcher
│   ├── integrations/       # External app connectors
│   │   ├── vyapar.py       # Vyapar API client
│   │   ├── khatabook.py    # Khatabook integration
│   │   ├── tally.py        # Tally Prime connector
│   │   └── whatsapp.py     # WhatsApp Business API
│   ├── tts/                # Text-to-speech for confirmations
│   │   ├── base.py         # Abstract TTS interface
│   │   └── sarvam_tts.py   # Sarvam AI voice synthesis
│   ├── context/            # App context awareness
│   │   ├── detector.py     # Active window/app detection
│   │   └── formatter.py    # Context-appropriate response formatting
│   ├── offline/            # Offline-first infrastructure
│   │   ├── queue.py        # Local command queue
│   │   └── sync.py         # Online sync manager
│   └── config.py           # App configuration
├── tests/
│   ├── audio_fixtures/     # Sample Hinglish audio files
│   ├── test_asr.py
│   ├── test_nlu.py
│   ├── test_actions.py
│   └── test_e2e.py         # End-to-end voice command tests
├── data/
│   ├── product_catalog.json    # Common kirana products
│   ├── hindi_numbers.json      # Hindi numeral mappings
│   └── hinglish_lexicon.json   # Domain-specific vocabulary
├── prompts/                    # LLM prompt templates
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## Part VI: Testing & Verification

### Voice-Specific Testing Strategy

1. **ASR Accuracy Tests:**
   - Maintain a test suite of 50+ Hinglish audio samples
   - Target WER < 20% for clean audio, < 30% for noisy environments
   - Test code-switching at all three levels (inter/intra-sentential, intra-word)

2. **Intent Classification Tests:**
   - 100+ test utterances covering all intents
   - Include ambiguous utterances with expected clarification behavior
   - Test Hindi-only, English-only, and mixed inputs

3. **Entity Extraction Tests:**
   - Product name fuzzy matching accuracy > 95%
   - Quantity parsing (Hindi numerals + English + mixed) accuracy > 99%
   - Currency amount parsing accuracy > 99%

4. **End-to-End Pipeline Tests:**
   ```python
   # Example E2E test
   def test_add_inventory_hinglish():
       """Verify full pipeline: audio → ASR → NLU → action → confirmation."""
       audio = load_test_audio("add_maggi_packet.wav")
       result = pipeline.process(audio)
       assert result.intent == "add_inventory"
       assert result.entities["product"] == "Maggi"
       assert result.entities["quantity"] == 1
       assert result.entities["unit"] == "packet"
       assert result.action_status == "success"
   ```

5. **Latency Benchmarks:**
   - Audio capture → ASR complete: < 500ms
   - ASR → NLU/Intent: < 300ms
   - NLU → Action execution: < 200ms
   - Total end-to-end: < 1.5 seconds

---

## Part VII: Security & Privacy

### Non-Negotiable Rules

1. **Audio data NEVER leaves the device without explicit user consent.**
2. **All financial data (udhaar, bills) is encrypted at rest.**
3. **API keys for ASR/LLM providers are NEVER hardcoded.** Use environment variables or vault.
4. **Voice biometrics for shop owner authentication** (optional but recommended).
5. **Audit log for all voice-triggered financial transactions.**
6. **PII handling:** Customer names and financial data follow India's DPDP Act 2023 guidelines.

---

## Part VIII: Common Mistakes to Avoid

| Mistake | Why It's Wrong | What To Do Instead |
|---------|---------------|-------------------|
| Using English-only Whisper for Hinglish | WER will be 40%+ on code-switched speech | Use Sarvam AI or fine-tuned Whisper with Hinglish data |
| Treating "karo" and "kar do" as different intents | Both mean "do it" — Hindi morphological variants | Normalize verb forms before intent classification |
| Hardcoding product names | Kiranas stock 500-2000 unique products | Use fuzzy matching + product catalog with aliases |
| Ignoring network failures | Indian shops have patchy connectivity | Build offline-first with sync queue |
| Building desktop-only | Most kirana owners use Android phones | Mobile-first (PWA or React Native) with desktop as bonus |
| Skipping confirmation for financial actions | Voice misrecognition could create wrong bills | ALWAYS confirm: "Ramesh ka ₹500 udhaar add karoon?" |
| Using standard text normalization for Hindi | Strips diacritics, breaks Devanagari | Use Indic-aware normalization (indic-nlp-library) |
| Over-engineering the LLM pipeline | Complex chain-of-thought for simple "add item" | Simple structured output with few-shot prompts |

---

## Part IX: Hackathon-Specific Guidelines

### MVP Scope (Build This First)

```
Phase 1 (Day 1): Voice → Text → Structured Intent
├── Hotkey-triggered mic capture
├── Sarvam AI STT for Hinglish transcription
├── Gemini Flash for intent + entity extraction
└── JSON output with intent, entities, confidence

Phase 2 (Day 1-2): Intent → Action
├── In-memory inventory store (SQLite)
├── Billing/invoice generation
├── Udhaar/credit tracking (khata)
└── Spoken confirmation via TTS

Phase 3 (Day 2): Polish & Demo
├── Simple web UI showing voice command history
├── Real-time inventory dashboard
├── 5 demo scenarios with pre-recorded audio fallback
└── "Wow factor": Live demo with actual Hinglish voice commands
```

### Demo Script (5 Commands That Tell the Story)

1. **"Ek packet Britannia biscuit add karo"** → Inventory updated
2. **"Ramesh ka bill banao — do kilo chini aur ek packet Surf"** → Bill generated
3. **"Ramesh ko 150 rupaye udhaar likh do"** → Credit recorded
4. **"Kitna Surf bacha hai?"** → Stock check response
5. **"Aaj ka total kya hua?"** → Daily summary spoken back

---

**These guidelines are working if:** Hinglish voice commands are parsed correctly >90% of the time, financial actions always require confirmation, the system works in noisy environments, and a non-technical kirana owner can use it without training.
