# Enry Voice OS 🎙️

A hands-free, multilingual Voice OS that transforms natural Hinglish speech into structured inventory, billing, and khata ledger actions for Indian SMBs (Small and Medium Businesses).

## 📋 Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Setup & Installation](#setup--installation)
- [Configuration](#configuration)
- [API Documentation](#api-documentation)
- [Project Structure](#project-structure)
- [Voice Command Examples](#voice-command-examples)
- [Contributing](#contributing)
- [License](#license)

---

## 🎯 Overview

Enry Voice OS is designed to simplify retail and SMB operations through voice commands. Shopkeepers and business owners can manage their inventory, create bills, track customer credit (khata), and generate daily summaries—all hands-free in Hinglish.

### Key Benefits:
- **Hands-Free Operation**: No need to stop work to log transactions
- **Hinglish Support**: Natural speech in Hindi and English mixed
- **Real-time Inventory**: Instant stock checks and updates
- **Digital Khata**: Replace paper ledgers with automated credit tracking
- **POS Integration**: Quick billing and checkout operations

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Frontend Layer                         │
│                                                                 │
│  HTML/CSS/JS UI with Audio Recording & Playback Capabilities  │
│  (/static directory)                                            │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (app.py)                     │
│                                                                 │
│  • REST API Endpoints                                           │
│  • Request/Response Validation (Pydantic)                       │
│  • Static File Serving                                          │
│  • Database Connection Management                               │
└────┬─────────────┬──────────────┬──────────────┬────────────────┘
     │             │              │              │
     ▼             ▼              ▼              ▼
  ┌──────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
  │ STT  │   │ NLU/Intent│   │  Action  │   │   TTS    │
  │      │   │ Detection │   │ Execution│   │          │
  │parser│   │(parser.py)│   │ Handlers │   │ Cartesia │
  └──────┘   └──────────┘   └──────────┘   └──────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Database Layer (db.py)                         │
│                                                                 │
│  SQLite3 - Persistent Data Storage                             │
│  • Customers (Name, Phone, Balance)                            │
│  • Inventory (Products, Prices, Stock)                         │
│  • Invoices (Billing Records)                                  │
│  • Transactions (Khata Credit/Payment)                         │
└─────────────────────────────────────────────────────────────────┘
```

### Component Overview

**Frontend (`/static`)**
- HTML/CSS/JavaScript interface
- Audio recording and playback
- Real-time UI updates

**Backend (`app.py`)**
- FastAPI application server
- RESTful API endpoints
- Request validation and error handling

**Voice Processing (`parser.py`)**
- Intent recognition from Hinglish text
- Entity extraction (customer names, products, quantities, amounts)
- Command classification

**Database (`db.py`)**
- SQLite schema management
- CRUD operations for customers, inventory, invoices, transactions
- Connection pooling and transaction management

---

## ✨ Features

### Voice Commands Supported
- **Billing**: "Ek packet biscuit add karo" (Add packet of biscuits)
- **Khata Management**: "Ramesh ko 500 rupees credit de" (Credit ₹500 to customer)
- **Stock Checking**: "Chai ka stock dekh" (Check tea stock)
- **Payment Recording**: "Priya ne 1000 payment kiya" (Record ₹1000 payment from Priya)
- **Daily Summary**: "Aaj ka summary batao" (Give today's summary)
- **Inventory Updates**: "Doodh 20 liter add karo" (Add 20 liters of milk)

### Core Functionalities
✅ Voice-to-text transcription (Hindi/English)  
✅ Intent and entity extraction  
✅ Customer management  
✅ Inventory tracking  
✅ Digital bill generation  
✅ Khata ledger (credit tracking)  
✅ Daily sales summaries  
✅ Text-to-speech responses  

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | HTML, CSS, JavaScript | User Interface |
| **Backend** | FastAPI, Uvicorn | REST API Server |
| **Language Processing** | Python, Pydantic | NLU & Entity Extraction |
| **Database** | SQLite3 | Data Persistence |
| **STT** | Google Speech Recognition | Audio-to-Text |
| **TTS** | Cartesia AI | Text-to-Speech |
| **LLM** | Google Generative AI (Gemini) | NLU Enhancement |
| **Environment** | Python 3.8+ | Runtime |

---

## 🚀 Setup & Installation

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)
- Git
- API Keys:
  - Google Generative AI (Gemini) API key
  - Cartesia AI TTS API key (optional, for premium voice)

### Step 1: Clone the Repository
```bash
git clone https://github.com/Imkumar80/Enry-BoL.git
cd Enry-BoL
```

### Step 2: Create a Virtual Environment
```bash
# On macOS/Linux
python3 -m venv venv
source venv/bin/activate

# On Windows
python -m venv venv
venv\Scripts\activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

**Note**: If `speech_recognition` is missing from requirements.txt, install it manually:
```bash
pip install SpeechRecognition pydub
```

### Step 4: Setup Environment Variables
```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your API keys
nano .env  # or use your preferred editor
```

### Step 5: Run the Application
```bash
python app.py
```

The application will start at `http://127.0.0.1:8000` by default.

---

## ⚙️ Configuration

### Environment Variables (`.env`)

```env
# Google Generative AI (Gemini)
GEMINI_API_KEY=your_gemini_api_key_here

# Cartesia Text-to-Speech
CARTESIA_API_KEY=your_cartesia_key_here
CARTESIA_VOICE_ID=3b554273-4299-48b9-9aaf-eefd438e3941

# Server Configuration
PORT=8000
HOST=127.0.0.1
```

### Getting API Keys

**Google Generative AI (Gemini)**
1. Visit [Google AI Studio](https://aistudio.google.com/)
2. Click "Create API Key"
3. Copy and paste into `.env`

**Cartesia TTS (Optional)**
1. Sign up at [Cartesia.ai](https://www.cartesia.ai/)
2. Get your API key and voice ID from dashboard
3. Add to `.env` for premium voice support

---

## 📡 API Documentation

### Base URL
```
http://localhost:8000
```

### Endpoints

#### 1. **Parse Voice Command**
```
POST /api/parse-command
```
Parses a text command and executes corresponding action.

**Request:**
```json
{
  "text": "Chai ke stock dekh"
}
```

**Response:**
```json
{
  "intent": "check_stock",
  "entities": {
    "product": "chai"
  },
  "explanation": "Understood - checking tea stock",
  "action_taken": "Chai stock is 50 units.",
  "success": true
}
```

---

#### 2. **Speech-to-Text**
```
POST /api/stt
```
Transcribes uploaded audio file.

**Request:** Upload WAV/MP3 file as multipart form data

**Response:**
```json
{
  "text": "Ek packet biscuit add karo",
  "success": true
}
```

---

#### 3. **Text-to-Speech**
```
GET /api/tts?text=Hello
```
Generates audio from text using Cartesia TTS.

**Response:** Audio stream (MP3)

---

#### 4. **Get All Customers**
```
GET /api/customers
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Ramesh",
    "phone": "9876543210",
    "balance": 500.00
  }
]
```

---

#### 5. **Add Customer**
```
POST /api/customers
```

**Request:**
```json
{
  "name": "Priya",
  "phone": "9123456789",
  "balance": 0.0
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Customer Priya added successfully."
}
```

---

#### 6. **Get Inventory**
```
GET /api/inventory
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Chai",
    "price": 20.0,
    "stock": 50,
    "unit": "cups"
  }
]
```

---

#### 7. **Add Inventory Item**
```
POST /api/inventory
```

**Request:**
```json
{
  "name": "Biscuit",
  "price": 15.0,
  "stock": 100,
  "unit": "packets"
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Product Biscuit added successfully."
}
```

---

#### 8. **Checkout/Create Invoice**
```
POST /api/checkout
```

**Request:**
```json
{
  "customer_name": "Ramesh",
  "items": [
    {
      "product_name": "Chai",
      "quantity": 5
    },
    {
      "product_name": "Biscuit",
      "quantity": 2
    }
  ]
}
```

**Response:**
```json
{
  "status": "success",
  "invoice_id": 42,
  "message": "Checkout completed successfully."
}
```

---

#### 9. **Get All Transactions**
```
GET /api/transactions
```

**Response:**
```json
[
  {
    "id": 1,
    "customer_name": "Ramesh",
    "type": "credit",
    "amount": 500.00,
    "description": "Recorded via Voice OS",
    "timestamp": "2026-06-12T15:30:00"
  }
]
```

---

## 📁 Project Structure

```
Enry-BoL/
├── app.py                    # Main FastAPI application
├── parser.py                 # Intent recognition & entity extraction
├── db.py                     # Database schema & operations
├── voice_agent.py            # Voice agent orchestration (optional)
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore rules
├── static/                   # Frontend files
│   ├── index.html           # Main UI page
│   ├── styles.css           # Styling
│   └── script.js            # Client-side logic
├── skills/                   # Skill definitions (extensible)
└── test.wav                  # Sample audio for testing
```

---

## 🎤 Voice Command Examples

### Inventory Management
- "Stock dekh" → Check total stock
- "Chai 20 liters add karo" → Add 20 liters of tea
- "Doodh ka stock kitna hai?" → How much milk in stock?

### Billing
- "Bill banao Ramesh ka" → Create bill for Ramesh
- "Biscuit add karo" → Add biscuits to cart
- "Checkout karo" → Complete transaction

### Khata (Credit) Management
- "Priya ko 1000 rupees credit de" → Credit ₹1000 to Priya
- "Ajay ne 500 payment kiya" → Record ₹500 payment from Ajay
- "Ramesh ka balance dekh" → Check Ramesh's outstanding balance

### Reports
- "Aaj ka summary" → Today's sales summary
- "Kitne customers hai?" → Count of customers
- "Total sales kitne?" → Total revenue

---

## 🔄 Workflow Example

1. **User speaks**: "Ek chai add karo"
2. **STT Layer**: Converts speech to text
3. **Parser Layer**: 
   - Extracts intent: `add_to_bill`
   - Extracts entities: `product="chai", quantity=1`
4. **Intent Handler**: 
   - Looks up product in database
   - Adds to active cart
5. **TTS Layer**: "One tea added to your cart"
6. **Frontend**: Updates UI with cart status

---

## 🧪 Testing

### Using cURL

**Test STT Endpoint:**
```bash
curl -X POST http://localhost:8000/api/stt \
  -F "audio=@test.wav"
```

**Test Command Parsing:**
```bash
curl -X POST http://localhost:8000/api/parse-command \
  -H "Content-Type: application/json" \
  -d '{"text": "Chai ka stock dekh"}'
```

**Get Customers:**
```bash
curl http://localhost:8000/api/customers
```

---

## 🛡️ Error Handling

The API provides descriptive error messages:

```json
{
  "detail": "Product 'xyz' not found in catalog."
}
```

Common HTTP Status Codes:
- `200` - Success
- `400` - Bad request / Invalid input
- `404` - Resource not found
- `500` - Server error
- `503` - External service unavailable (STT/TTS)

---

## 🚀 Deployment

### Local Development
```bash
python app.py
```

### Production (with Gunicorn)
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

### Docker (Optional)
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 🔐 Security Considerations

- Keep API keys in `.env` and never commit to git
- Use HTTPS in production
- Validate all user inputs (already done with Pydantic)
- Implement rate limiting for production
- Add authentication for multi-user scenarios
- Encrypt sensitive data in database

---

## 🤝 Contributing

We welcome contributions! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Commit with descriptive messages (`git commit -m 'Add amazing feature'`)
5. Push to your branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 📞 Support & Contact

For issues, questions, or suggestions:
- Open an [Issue](https://github.com/Imkumar80/Enry-BoL/issues)
- Contact: [GitHub Profile](https://github.com/Imkumar80)

---

## 🎓 Learning Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Google Speech Recognition](https://cloud.google.com/speech-to-text)
- [Cartesia TTS API](https://docs.cartesia.ai/)
- [SQLite Documentation](https://www.sqlite.org/docs.html)

---

**Made with ❤️ for Indian SMBs**

*Transforming retail operations one voice command at a time.*
