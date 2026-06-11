---
name: hinglish-voice-ai
description: Guidelines for building Hinglish (Hindi-English code-switching) voice AI systems. Covers ASR provider selection, transliteration, code-switching patterns, noise handling, and Indian accent optimization. Use when working on any speech-to-text, voice command, or NLU component.
license: MIT
---

# Hinglish Voice AI Skill

Domain-specific skill for building production-grade Hinglish voice recognition and natural language understanding.

## 1. ASR Selection Rules

**Always prefer code-switching-native ASR models over monolingual pipelines.**

Decision tree:
```
Need Hinglish ASR?
├── Production + Cloud OK → Sarvam AI Saaras v3 (best Hinglish quality)
├── Production + Privacy Required → Fine-tuned Whisper (self-hosted)
├── Prototyping + Free → Bhashini API / AI4Bharat models
├── Low Latency Required → Deepgram Hindi model (trade off code-mix quality)
└── Offline Required → faster-whisper with Hinglish fine-tuned weights
```

**Never:**
- Use English-only Whisper for Hinglish input (30-50% WER increase)
- Use sequential Language-ID → Monolingual ASR pipeline (fails on intra-sentential switching)
- Apply standard English text normalization to Hindi/Devanagari output

## 2. Audio Preprocessing

Indian retail environments are extremely noisy. Always apply:

```python
# REQUIRED preprocessing before ASR
def preprocess_audio(audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    """Prepare raw audio for ASR in noisy Indian retail environment."""
    # 1. Resample to 16kHz (ASR standard)
    if sample_rate != 16000:
        audio = resample(audio, sample_rate, 16000)
    
    # 2. Voice Activity Detection — strip silence and background
    vad_segments = silero_vad(audio)
    audio = concatenate_segments(vad_segments)
    
    # 3. Noise reduction (critical for shop environments)
    audio = noisereduce.reduce_noise(y=audio, sr=16000)
    
    # 4. Normalize volume
    audio = normalize_rms(audio, target_db=-20)
    
    return audio
```

## 3. Code-Switching Handling

### Three types to support:

**Inter-sentential** (language switch at sentence boundary):
```
Input:  "Add this to inventory. Ramesh ka bill banao."
Output: [{"lang": "en", "text": "Add this to inventory."},
         {"lang": "hi", "text": "Ramesh ka bill banao."}]
```

**Intra-sentential** (switch within a sentence — MOST COMMON):
```
Input:  "Ek packet Britannia biscuit add karo"
Output: {"text": "Ek packet Britannia biscuit add karo",
         "tokens": [("ek","hi"), ("packet","en"), ("britannia","en"),
                    ("biscuit","en"), ("add","en"), ("karo","hi")]}
```

**Intra-word** (Hindi morphology applied to English root):
```
Input:  "driving-wala", "adjust-karo", "bill-waala"
Handle: Strip Hindi suffixes (-wala, -karo, -waala), extract English root
```

## 4. Hindi Numeral Parsing

Always support both Hindi and English numerals:

```python
HINDI_NUMERALS = {
    "ek": 1, "do": 2, "teen": 3, "chaar": 4, "paanch": 5,
    "chhah": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "barah": 12, "terah": 13, "chaudah": 14,
    "pandrah": 15, "solah": 16, "satrah": 17, "atharah": 18,
    "unnis": 19, "bees": 20, "pacchees": 25, "tees": 30,
    "chalees": 40, "pachaas": 50, "saath": 60, "sattar": 70,
    "assi": 80, "nabbe": 90, "sau": 100, "hazaar": 1000,
    "lakh": 100000, "crore": 10000000,
    # Fractional
    "aadha": 0.5, "pauna": 0.75, "sava": 1.25,
    "dhai": 2.5, "saadhe": "prefix_half",  # e.g., "saadhe teen" = 3.5
    # Dozen
    "darjan": 12,
}
```

## 5. Product Name Fuzzy Matching

Indian shopkeepers pronounce brand names with local variations:

```python
PRODUCT_ALIASES = {
    "Britannia": ["britania", "britaniya", "britanya", "ब्रिटानिया"],
    "Parle-G": ["parle g", "parle ji", "parlae", "पारले-जी", "parlay"],
    "Surf Excel": ["surf", "surf exel", "सर्फ़", "sarph excel"],
    "Maggi": ["maggi", "magi", "मैगी", "meggi"],
    "Amul": ["amul", "amool", "अमूल"],
    "Haldiram": ["haldiram", "haldirams", "हल्दीराम"],
}
```

**Always use fuzzy string matching** (Levenshtein distance or phonetic matching like Soundex) to resolve product references. Never require exact string matches for voice-derived product names.

## 6. Evaluation Metrics

Don't use standard WER for Hinglish. Use:

| Metric | Purpose | Target |
|--------|---------|--------|
| **toWER** (transliteration-optimized WER) | Accounts for spelling/script variations | < 20% |
| **Intent Accuracy** | Correct intent classification | > 95% |
| **Entity F1** | Product + quantity + amount extraction | > 90% |
| **Latency P95** | End-to-end processing time | < 1.5s |
| **Noise Robustness** | WER in 40dB SNR (shop noise) | < 30% |
