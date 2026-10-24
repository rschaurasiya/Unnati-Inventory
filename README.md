# Apna Kirana: Shopkeeper Voice POS, AI Copilot & Inventory Assistant

[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116+-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite / SQLAlchemy](https://img.shields.io/badge/Database-SQLAlchemy%202.0-red.svg)](https://www.sqlalchemy.org/)
[![Voice TTS](https://img.shields.io/badge/Voice%20TTS-ElevenLabs%20%7C%20Edge--TTS-orange.svg)]()
[![AI Copilot](https://img.shields.io/badge/AI%20Copilot-Groq%20%7C%20Offline%20Engine-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

An intelligent, speech-driven Point-of-Sale (POS), inventory management, customer credit (Udhaar) ledger, AI Copilot, and predictive demand forecasting system tailored specifically for Indian grocery (**Kirana**) stores.

The system bridges spoken bilingual grocery orders (Hindi/Hinglish), real-time catalog mapping, atomic inventory tracking, digital Udhaar ledgers with 4-digit 2FA OTP authorization, 80mm thermal receipt printing, historical CSV sales data ingestion, predictive demand forecasting, and an AI shop assistant with Indian voice synthesis.

---

## 📌 Problem Statement

Traditional neighborhood Kirana stores in India face unique operational challenges:
1. **Rapid Spoken Transactions**: Customers order groceries rapidly in colloquial Hindi or Hinglish (e.g., *"2 kilo cheeni aur 3 packet maggi dena"*), requiring shopkeepers to look up prices, calculate totals, and record ledger entries manually.
2. **Stockouts & Inaccurate Stock**: High-turnover staples (milk, atta, sugar, rice) run out unexpectedly because sales are not recorded in real time.
3. **Informal Credit (Udhaar) Disputes**: Udhaar is essential for neighborhood commerce, but paper ledgers (*Khata*) lead to unauthorized purchases, billing disputes, and unverified debts.
4. **Peak Rush Multi-Customer Handling**: Handling multiple in-store customers simultaneously leads to lost bills or delayed checkout.
5. **Lack of Analytics & Digital Readiness**: Small retailers cannot leverage modern demand forecasting because raw transaction data is fragmented or non-existent.

---

## 🚀 Key Features

### 1. Spoken Hindi/Hinglish Voice & Text Billing
- **Real-Time Natural Language Parsing**: Converts spoken or typed Hinglish phrases into structured draft billing items.
- **Phonetic & Colloquial Catalog Matching**: Maps spoken aliases (e.g., *"cheeni"*, *"chini"*, *"gehun ka aata"*, *"sona masoori"*, *"sarson tel"*) to canonical products in the catalog.
- **Unit & Quantity Extraction**: Automatically extracts quantities and units (kg, packet, litre, piece, dozen) with fallback defaults.
- **Live Draft POS Interface**: Shopkeepers can add, edit, override prices, or drop items before finalization.

### 2. Multi-Bill Hold & Resume State Machine
- **Concurrent Bill Handling**: Manage up to 5 concurrent active bills with tabbed switching.
- **Instant Hold / Resume**: Seamlessly switch between customers without losing drafted cart items.
- **Visual Status Badges**: Shows item counts and live subtotal totals directly in the bill tabs.

### 3. Product Catalog & ACID Inventory Tracking
- **Comprehensive Indian Grocery Catalog**: Pre-seeded with common Indian grocery staples across Grains, Spices, Dairy, Snacks, and Household items.
- **Atomic Stock Deduction**: Guaranteed ACID stock deduction upon bill finalization. Prevents negative stock and overselling.
- **Real-Time Low-Stock Alerts**: Detects items dipping below customizable thresholds (`min_stock_threshold`).
- **Inventory Restocking**: Supports direct restock adjustments with reason notes and audit timestamps.

### 4. Multi-Mode Billing Engine (CASH, UPI, UDHAAR)
- **Immediate Finalization for CASH and UPI**: Stock is deducted immediately, completed bills are recorded, and daily sales summaries are updated synchronously.
- **Idempotency Guarantee**: Accepts an `idempotency_key` per bill. Replaying duplicate network requests safely returns the existing bill without double-charging credit or double-deducting inventory.

### 5. Digital Udhaar (Credit) Ledger & Family Accounts
- **Primary Account Holders (*Mukhiya*)**: Maintains verified customer profiles with structured addresses, credit limits, and outstanding debt balances.
- **Family Member Sub-Accounts**: Links dependents (spouse, son, daughter, etc.) to a primary account with individual spending limits.
- **Credit Limit Boundary Enforcement**: Automatically rejects transactions exceeding primary credit limits or individual member allowances.
- **Immutable Transaction Ledger**: Records every debit purchase and credit repayment with before/after balance snapshots.
- **Soft Deactivation**: Prevents deletion of customer or member accounts that possess transaction history to preserve audit integrity.

### 6. Udhaar Transaction 2FA Flow (Clean OTP Verification)
- **4-Digit Transaction OTP**: Cryptographically generated server-side (`0000`–`9999`) for authorizing specific Udhaar purchases.
- **Strict Cryptographic Binding**: The OTP session is securely bound to the customer ID, bill ID, 3-minute expiry TTL, and maximum 3 attempts.
- **Development / Mock Mode**: When external telecom gateways are not configured, a clean development badge displays `Demo OTP: [ XXXX ]` for testing.
- **Clean Finalization UX**: Once verified, the bill finalizes directly into `✓ Udhaar Bill Finalized Successfully` with bill details and optional thermal printing.

### 7. Digital Receipts & 80mm Thermal Printing
- **Monospace Thermal Slip Formatter**: Produces industry-standard 80mm monospace slips with store branding header, masked customer phone, itemized lines, subtotal, and outstanding Udhaar balance.
- **Browser Thermal Print Integration**: Supports direct one-click thermal printing formatted via native `@media print` CSS rules.
- **Store Profile Sync**: Store name, address, phone number, and GSTIN automatically populate on all thermal receipts.

### 8. Bulletproof 3-Layer Voice & Audio Engine
- **Layer 1 (Local Disk & Memory Cache)**: Instant playback of repeated phrases via SHA-256 hashed `.tts_cache/<hash>.mp3` audio files.
- **Layer 2 (ElevenLabs Flash v2.5 / Edge-TTS)**: High-quality natural voice synthesis with Indian accents (ElevenLabs Flash or free Microsoft Edge-TTS `en-IN-PrabhatNeural` / `hi-IN-SwaraNeural`).
- **Layer 3 (Browser Offline SpeechSynthesis)**: Client-side browser speech synthesis backup ensuring audio works completely offline without network access.

### 9. Kirana AI Copilot (Shopkeeper Intelligent Assistant)
- **Real-Time Store Context Injection**: Live operational snapshot of all-time sales, today's revenue, active bills, and stock levels injected directly into the LLM context.
- **Groq LLM Acceleration**: Powered by Groq fast inference (`qwen/qwen3.8-27b`).
- **Deterministic Offline Fallback Engine**: If no Groq API key is configured or the network is offline, a built-in rule-based AI engine answers sales, inventory, and navigation questions accurately.
- **Voice & Quick Actions**: Built-in microphone voice transcription and actionable navigational shortcuts (e.g., "Go to Inventory →", "Go to Billing POS →").

### 10. Predictive Demand Forecasting & Reorder Intelligence
- **Data Sufficiency Gate**: Built-in verification engine determining whether historical data is `SUFFICIENT_DATA` ($\ge 7$ usable days) or `INSUFFICIENT_DATA` ($< 7$ days).
- **Demand Curves**: Generates 7-day and 30-day forecast curves using moving averages and trend projections.
- **Reorder Recommendations**: Computes suggested reorder quantities based on current stock, minimum thresholds, lead times, and daily run rates.
- **Stockout Risk Indicators**: Identifies items at high risk of stockout with chronological urgency ranking (Immediate Attention, Low Stock, Reorder Soon).

### 11. Historical Sales CSV / Excel Bulk Import Pipeline
- **Flexible Column Mapping**: Automatically detects and maps column headers across various POS export formats (Product Name, Quantity, Sale Date, Unit Price, Revenue).
- **Phonetic & Alias Resolution**: Automatically resolves imported product names to catalog IDs using known grocery aliases.
- **Zero-Inventory-Mutation Guarantee**: Ingesting historical sales data strictly updates historical aggregates and forecasting tables without altering current physical warehouse inventory.

### 12. Store Profile & Brand Customization
- **Shopkeeper Settings**: Edit Store Name, Owner Name, Contact Phone, Full Address, and GSTIN Number.
- **Interactive Image Cropper**: Upload and crop square store logos and shopkeeper avatars directly in the browser with live preview cards.

### 13. Single-Page Application (SPA) Routing & Responsive UI
- **URL Synchronization**: Direct URL navigation for all major tabs:
  - `/dashboard` — Store overview, daily metrics, and quick actions.
  - `/billing` — Spoken POS voice order capture and draft checkout.
  - `/inventory` — Real-time catalog stock levels, low-stock alerts, and restocking.
  - `/customers` — Udhaar credit ledgers, customer accounts, and family members.
  - `/sales` — Sales history analytics and CSV/Excel bulk import.
  - `/forecast` — Predictive demand curves and reorder recommendations.
  - `/profile` — Shopkeeper profile, store branding, and account settings.
- **Full History API**: Browser back/forward buttons work seamlessly.
- **Responsive Navigation**: Mobile navigation drawer with backdrop, desktop sidebar, and fluid touch controls.

---

## 🛠️ Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend Runtime** | Python 3.11+ / 3.13 |
| **API Framework** | FastAPI (ASGI), Pydantic v2, Pydantic-Settings |
| **Database & ORM** | SQLAlchemy 2.0, SQLite (default) / PostgreSQL compatible |
| **Frontend** | HTML5, Vanilla JavaScript (ES6+ Modules), Vanilla CSS3 (Custom Glassmorphism Design System) |
| **AI Copilot** | Groq Cloud API (Qwen 2.5 / Llama 3) + Deterministic Offline Rule-Based Engine |
| **Voice / TTS Engine**| ElevenLabs Flash v2.5, Microsoft Edge-TTS, Browser SpeechSynthesis |
| **File Processing** | Pandas, OpenPyXL, RapidFuzz |
| **Security & Auth** | Passlib / Bcrypt, PyJWT |
| **Server** | Uvicorn (ASGI) |
| **Testing** | Pytest, Starlette / HTTPX TestClient |

---

## 🏛️ System Architecture

```text
                  Spoken Hindi/Hinglish Voice or Text
                                   ↓
                   NLP Voice Billing Parser & Matcher
                                   ↓
                  Interactive Draft POS (Multi-Bill)
                                   ↓
                       Billing Router (ACID Transaction)
             ┌─────────────────────┼─────────────────────┐
             ↓                     ↓                     ↓
           CASH                   UPI                  UDHAAR
             ↓                     ↓                     ↓
     Instant Deduction     Instant Deduction     Select Customer / Member
             │                     │                     ↓
             │                     │             4-Digit 2FA OTP
             │                     │                     ↓
             │                     │             Cryptographic Check
             │                     │                     ↓
             └─────────────────────┼─────────────────────┘
                                   ↓
                   Atomic Bill Finalization & Ledger Commit
                                   ↓
                 Completed Bills (Single Source of Truth)
                                   ↓
               Daily Product-Level Sales Summary Aggregation
                                   ↓
                Data Sufficiency Gate (>= 7 Usable Days)
                                   ↓
               Predictive Demand Forecasting & Reorder Alarms
                                   ↓
               Kirana AI Copilot Context & Analytics Dashboard
```

---

## 💻 Installation & Local Setup

### 1. Prerequisites
- **Python 3.11+** (Python 3.13 tested and verified)
- **Git**

### 2. Clone the Repository
```bash
git clone https://github.com/rschaurasiya/final_project.git
cd final_project
```

### 3. Create and Activate Virtual Environment
```bash
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Environment Configuration
Copy the configuration template to create your local `.env` file:
```bash
# Windows (PowerShell)
Copy-Item .env.example .env

# Linux / macOS
cp .env.example .env
```

*(By default, the application runs 100% locally with SQLite, Edge-TTS/Browser TTS, and the built-in offline AI Copilot without needing any external paid API keys!)*

#### Optional External API Keys (for Cloud Enhancements):
Open `.env` in an editor to add optional keys:
- `ELEVENLABS_API_KEY`: For premium ElevenLabs cloud voice synthesis.
- `GROQ_API_KEY`: For Groq cloud LLM chat responses.

---

## 🏃 Running the Application

Start the local FastAPI development server:
```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Once started, open your browser and access:
- **Main Web Application**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Voice Billing POS**: [http://127.0.0.1:8000/billing](http://127.0.0.1:8000/billing)
- **Inventory Management**: [http://127.0.0.1:8000/inventory](http://127.0.0.1:8000/inventory)
- **Customer Udhaar Ledger**: [http://127.0.0.1:8000/customers](http://127.0.0.1:8000/customers)
- **Sales Analytics & CSV Import**: [http://127.0.0.1:8000/sales](http://127.0.0.1:8000/sales)
- **Demand Forecasting**: [http://127.0.0.1:8000/forecast](http://127.0.0.1:8000/forecast)
- **Shop Profile & Settings**: [http://127.0.0.1:8000/profile](http://127.0.0.1:8000/profile)
- **Interactive OpenAPI / Swagger Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc API Documentation**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## 🧪 Running Automated Tests

Run the test suite using pytest:
```bash
# Run tests
python -m pytest tests/ -q

# Run specific module tests
python -m pytest tests/test_kirana_ai_copilot.py -v
python -m pytest tests/test_voice_three_layer_fallback.py -v
python -m pytest tests/test_demand_forecasting_enhancements.py -v
python -m pytest tests/test_udhaar_otp_verification.py -v
python -m pytest tests/test_historical_import.py -v
```

---

## 📂 Project Structure

```text
final_project/
├── backend/
│   ├── main.py                  # FastAPI application entrypoint & lifespan
│   ├── config.py                # Pydantic Settings & environment loader
│   ├── database.py              # SQLAlchemy database engine & session maker
│   ├── init_db.py               # Database table creation & catalog seeding
│   ├── models.py                # Database models (Products, Bills, Customers, Udhaar)
│   ├── schemas.py               # Pydantic validation schemas
│   ├── security.py              # Password hashing & JWT utilities
│   ├── seed_data.py             # Default Kirana grocery catalog & demo customers
│   ├── nlp/                     # Bilingual NLP parser, phonetic dictionary & matcher
│   ├── routers/                 # API endpoints (billing, inventory, customers, voice, copilot, etc.)
│   └── services/                # Forecasting, sales aggregation, ElevenLabs TTS service
├── frontend/
│   ├── index.html               # Main SPA single-page application interface
│   ├── css/
│   │   └── style.css            # Glassmorphism styling, responsive layout, dark theme
│   └── js/                      # Frontend ES6 modules
│       ├── app.js               # Router, navigation, and application coordinator
│       ├── billing.js           # Voice/Text POS billing & multi-bill state machine
│       ├── copilot.js           # Kirana AI Copilot floating drawer & voice assistant
│       ├── customers.js         # Customer management & Udhaar credit ledger
│       ├── dashboard.js         # Daily KPI metrics & store snapshot
│       ├── forecasting.js       # Demand curves & stockout reorder recommendations
│       ├── inventory.js         # Stock tracking, search, and restocking modals
│       ├── profile.js           # Shopkeeper profile, logo/avatar cropping & branding
│       ├── sales.js             # Sales history analytics & CSV import workflow
│       └── shared/              # API clients, state management & UI helpers
├── data/
│   ├── test_import_files/       # Sample CSV and Excel files for testing import
│   └── uploads/                 # Storage for user-uploaded store logos and avatars
├── tests/                       # Automated pytest suite
├── .env.example                 # Configuration environment template
├── .gitignore                   # Files and patterns ignored from Git
├── requirements.txt             # Complete Python runtime dependencies
└── README.md                    # Project documentation & run guide
```

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
