---
name: voice-pipeline-architecture
description: Architecture guidelines for building the STT → LLM → Action pipeline for context-aware voice OS systems. Covers streaming audio, WebSocket protocols, latency optimization, offline-first patterns, and confirmation flows. Use when designing system architecture, implementing the voice pipeline, or optimizing latency.
license: MIT
---

# Voice Pipeline Architecture Skill

System architecture guidelines for building a production-grade, context-aware Voice OS pipeline.

## 1. Pipeline Design Principles

### The Golden Rule: Streaming, Not Batch

**Never wait for the user to finish speaking before starting processing.**

```
WRONG (Batch):
[Record full audio] ──────────▶ [Send to ASR] ──▶ [Wait] ──▶ [Get text] ──▶ [Process]
                                                   3-5 seconds total

RIGHT (Streaming):
[Audio chunk 1] ──▶ [ASR partial] ──▶ [Pre-warm NLU]
[Audio chunk 2] ──▶ [ASR partial] ──▶ [Update NLU prediction]
[Audio chunk 3] ──▶ [ASR final]  ──▶ [Execute action]
                                      < 1.5 seconds total
```

### Latency Budget

| Stage | Budget | Notes |
|-------|--------|-------|
| Hotkey → Mic active | < 50ms | System-level hook, pre-allocated buffer |
| Audio → ASR streaming | < 200ms | Chunk size: 100-200ms of audio |
| ASR → Final transcript | < 500ms | After end-of-speech detected |
| Transcript → NLU/Intent | < 300ms | LLM structured output, cached prompt |
| Intent → Action executed | < 200ms | Local DB write, no network needed |
| Action → TTS confirmation | < 500ms | Pre-cached common confirmations |
| **Total end-to-end** | **< 1.5s** | User should hear confirmation within 1.5s |

## 2. Component Interfaces

### Abstract ASR Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

@dataclass
class ASRResult:
    text: str
    language: str              # "hi", "en", "hi-en" (code-mixed)
    confidence: float
    is_final: bool
    word_timestamps: list[dict] | None = None

class BaseASR(ABC):
    """Abstract interface for all ASR providers."""
    
    @abstractmethod
    async def transcribe_stream(
        self, 
        audio_chunks: AsyncIterator[bytes],
        language_hint: str = "hi-en",
    ) -> AsyncIterator[ASRResult]:
        """Stream audio chunks, yield partial and final transcripts."""
        ...
    
    @abstractmethod
    async def transcribe_file(
        self, 
        audio_path: str,
        language_hint: str = "hi-en",
    ) -> ASRResult:
        """Transcribe a complete audio file. For offline/batch use."""
        ...
```

### Abstract NLU Interface

```python
@dataclass
class ParsedCommand:
    intent: str                          # e.g., "add_inventory"
    entities: dict[str, Any]             # e.g., {"product": "Maggi", "qty": 1}
    confidence: float
    raw_transcript: str
    requires_confirmation: bool          # True for destructive/financial actions
    confirmation_message: str | None     # "Ramesh ka ₹500 udhaar add karoon?"
    ambiguous: bool                      # True if multiple interpretations exist
    alternatives: list[dict] | None      # Alternative interpretations

class BaseNLU(ABC):
    """Abstract interface for intent classification + entity extraction."""
    
    @abstractmethod
    async def parse(
        self,
        transcript: str,
        context: dict | None = None,     # Active app, recent commands, etc.
    ) -> ParsedCommand:
        ...
```

### Abstract Action Interface

```python
@dataclass
class ActionResult:
    success: bool
    message: str                         # Human-readable result
    message_hindi: str                   # Hindi version for TTS
    data: dict | None = None             # Structured result data
    requires_sync: bool = False          # Needs online sync later

class BaseAction(ABC):
    """Abstract interface for business logic actions."""
    
    @abstractmethod
    async def execute(
        self, 
        command: ParsedCommand,
        dry_run: bool = False,           # For confirmation step
    ) -> ActionResult:
        ...
    
    @abstractmethod
    async def rollback(self, command_id: str) -> ActionResult:
        """Undo a previously executed command."""
        ...
```

## 3. Confirmation Flow (Critical for Financial Actions)

**NEVER execute a financial action without voice confirmation.**

```
User: "Ramesh ko 500 rupaye udhaar likh do"
          │
          ▼
    ┌─────────────┐
    │ NLU Parser   │ → intent: record_credit, amount: 500, customer: Ramesh
    └──────┬──────┘
           │
           ▼
    ┌─────────────────────┐
    │ Confirmation Gate    │ → requires_confirmation = True (financial action)
    └──────┬──────────────┘
           │
           ▼
    ┌─────────────────────────────────────┐
    │ TTS: "Ramesh ka 500 rupaye udhaar   │
    │       add karoon? Haan ya nahi?"     │
    └──────┬──────────────────────────────┘
           │
           ▼
    ┌────────────────┐
    │ Wait for "haan" │ ← Timeout after 10 seconds → Cancel
    │ or "nahi"       │
    └──────┬─────────┘
           │
     ┌─────┴─────┐
     │           │
   "haan"     "nahi"
     │           │
     ▼           ▼
  Execute     Cancel
     │           │
     ▼           ▼
  "Done!"    "Cancel kiya"
```

### Actions Requiring Confirmation

```python
CONFIRMATION_REQUIRED = {
    "record_credit",          # Adding udhaar
    "record_payment",         # Recording payment
    "delete_bill",            # Deleting a bill
    "delete_credit",          # Removing credit entry
    "update_quantity",        # Large stock changes (>50% of current)
    "generate_gst_invoice",   # GST invoice (has legal implications)
}

CONFIRMATION_NOT_REQUIRED = {
    "check_stock",            # Read-only
    "check_credit",           # Read-only
    "daily_summary",          # Read-only
    "add_to_bill",            # Reversible, in-progress bill
    "add_inventory",          # Usually low-risk
}
```

## 4. Offline-First Architecture

### Command Queue Pattern

```python
class OfflineCommandQueue:
    """Queue voice commands when offline, sync when connected."""
    
    def __init__(self, db_path: str = "offline_queue.db"):
        self.db = sqlite3.connect(db_path)
        self._create_tables()
    
    async def enqueue(self, command: ParsedCommand, result: ActionResult):
        """Store executed command for later cloud sync."""
        self.db.execute(
            "INSERT INTO queue (command_json, result_json, synced, created_at) VALUES (?, ?, 0, ?)",
            (command.to_json(), result.to_json(), datetime.now().isoformat())
        )
    
    async def sync_when_online(self, api_client):
        """Sync queued commands to cloud when internet is available."""
        pending = self.db.execute("SELECT * FROM queue WHERE synced = 0").fetchall()
        for entry in pending:
            try:
                await api_client.sync(entry)
                self.db.execute("UPDATE queue SET synced = 1 WHERE id = ?", (entry["id"],))
            except ConnectionError:
                break  # Stop syncing, will retry later
```

### Connectivity Detection

```python
async def check_connectivity() -> bool:
    """Check if cloud services are reachable."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head("https://api.sarvam.ai/health", timeout=2) as resp:
                return resp.status == 200
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return False

async def select_asr_provider() -> BaseASR:
    """Dynamically select ASR provider based on connectivity."""
    if await check_connectivity():
        return SarvamASR()      # Cloud: better Hinglish quality
    else:
        return WhisperASR()     # Local: works offline
```

## 5. Context Awareness

### Active App Detection

```python
import subprocess

def get_active_window() -> dict:
    """Detect currently focused application (Linux/X11)."""
    try:
        window_id = subprocess.check_output(["xdotool", "getactivewindow"]).strip()
        window_name = subprocess.check_output(["xdotool", "getactivewindow", "getwindowname"]).strip()
        window_class = subprocess.check_output(["xprop", "-id", window_id, "WM_CLASS"]).strip()
        return {
            "window_id": window_id.decode(),
            "window_name": window_name.decode(),
            "window_class": window_class.decode(),
        }
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"window_id": "unknown", "window_name": "unknown", "window_class": "unknown"}

def determine_context(active_window: dict) -> str:
    """Map active window to voice command context."""
    name = active_window["window_name"].lower()
    if "vyapar" in name or "billing" in name:
        return "billing"
    elif "khatabook" in name or "ledger" in name or "khata" in name:
        return "ledger"
    elif "tally" in name:
        return "accounting"
    elif "whatsapp" in name:
        return "messaging"
    else:
        return "general"
```

## 6. WebSocket Streaming Protocol

### Client → Server (Audio Chunks)

```json
{
    "type": "audio_chunk",
    "data": "<base64_encoded_audio>",
    "sample_rate": 16000,
    "encoding": "pcm_s16le",
    "chunk_duration_ms": 100,
    "sequence_number": 42
}
```

### Server → Client (Results)

```json
{
    "type": "transcript",
    "is_final": false,
    "text": "Ek packet",
    "confidence": 0.85,
    "sequence_number": 42
}
```

```json
{
    "type": "command_parsed",
    "intent": "add_inventory",
    "entities": {"product": "Britannia Biscuit", "quantity": 1, "unit": "packet"},
    "requires_confirmation": false,
    "confidence": 0.94
}
```

```json
{
    "type": "action_result",
    "success": true,
    "message": "1 packet Britannia Biscuit inventory mein add hua",
    "tts_audio": "<base64_encoded_tts_audio>"
}
```

## 7. Error Recovery

### Graceful Degradation Chain

```
Primary ASR (Sarvam Cloud) fails?
  → Fallback to local Whisper
  
LLM (Gemini) fails?
  → Fallback to rule-based intent matching (regex patterns)
  
TTS (Sarvam) fails?
  → Fallback to on-screen text display
  
Database write fails?
  → Queue to offline store, retry later
  
All fails?
  → "Kuch gadbad ho gayi, dobara try karo" (Something went wrong, try again)
```

### Never Silently Fail

```python
# WRONG: Silent failure
try:
    result = await asr.transcribe(audio)
except Exception:
    pass  # User hears nothing, thinks app is broken

# RIGHT: Always communicate
try:
    result = await asr.transcribe(audio)
except ASRError as e:
    await tts.speak("Samajh nahi aaya, dobara boliye")  # "Didn't understand, please repeat"
    logger.warning("ASR failed", error=str(e), audio_duration=len(audio))
except ConnectionError:
    await tts.speak("Internet nahi hai, offline mode mein kaam kar raha hoon")
    result = await offline_asr.transcribe(audio)
```
