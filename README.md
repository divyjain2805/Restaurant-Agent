# 🍽️ Restaurant Work Automation Agent (LangChain + LangGraph + MongoDB)

An intelligent restaurant workflow automation system built with **LangChain**, **LangGraph**, and **MongoDB**, featuring dual-API fallback (**Gemini** & **Groq**), structured order validation, inventory tracking, **Human-in-the-Loop (HITL)** Chef/Admin cooking verification, and automated billing with customer greeting.

---

## 🏗️ Architecture & Workflow

The system is modeled as a cyclic state graph in **LangGraph**:

```
[START]
   │
   ▼
[1. api_check] ──────────── (No API Keys) ─────────────► [EXIT with Sorry / Regret]
   │ (API Key Valid)
   ▼
[2. relevance_and_parse] ── (Irrelevant > 1 chance) ──► [EXIT with Goodbye]
   │ (Relevant Order)
   ▼
[3. database_check] ─────── (Not in DB > 1 chance) ────► [EXIT with Apology]
   │ (Order In MongoDB & Stock Reserved)
   ▼
[4. cook (HITL)] ────────── (Cook Failed > 1 chance) ──► [EXIT with Cancellation]
   │ (Admin/Chef Approved)
   ▼
[5. serve] ────────────────────────────────────────────► [Food Served + Bill + Greeting] ──► [END]
```

### Flow Breakdown:
1. **API Key Verification (`api_check`)**:
   - Checks presence of `GEMINI_API_KEY` or `GROQ_API_KEY`.
   - Dual-API fallback: If Gemini fails, automatically falls back to Groq (and vice versa).
   - If **neither** key is found: takes an immediate exit with a polite regret message.

2. **Relevance & Structured Extraction (`relevance_and_parse`)**:
   - Analyzes user input to verify if it represents a food/restaurant order.
   - If not relevant: grants **one chance** to re-enter a valid order. If the second attempt is still not relevant, takes an exit.
   - If relevant: extracts items and quantities in structured format (`[{"name": "...", "quantity": ...}]`).

3. **MongoDB Inventory & Menu Validation (`database_check`)**:
   - Checks menu presence and available stock in MongoDB (`menu` collection).
   - If found: atomically decrements stock via `$inc`, inserts order document into `orders` collection (`PENDING`), and advances to kitchen.
   - If not found or out of stock: gives **one chance** to reorder from the available menu. If second attempt also fails, takes an exit with an apology.

4. **Kitchen Cook & Human-in-the-Loop (`cook`)**:
   - Updates order status to `COOKING` in MongoDB.
   - **Human Interrupt (HITL) with 8-Second Countdown Timer**:
     - Chef/Admin is prompted to verify if the dish cooked successfully (`approved` or `failed`).
     - **Automatic Probabilistic Resolution**: If the Admin does not respond within **8 seconds**, the system automatically resolves the decision based on cooking probability (**85% approval / 15% failure**) to keep the workflow moving smoothly without blocking.
   - If successful: moves to Serve.
   - If cooking fails: has **one chance** to remake:
     - Checks if order/ingredients are verified in MongoDB.
     - If verified: updates MongoDB document to `COOKING_RETRY` and retries cooking with Admin review (8s timer).
     - If not in database or second cooking attempt fails: cancels order in MongoDB and takes exit with apology.

5. **Serve & Billing (`serve`)**:
   - Updates order document status to `SERVED`.
   - Generates itemized bill with subtotal, tax (5%), and grand total.
   - Delivers food with a warm greeting and completes the workflow.

---

## 🍃 MongoDB Collections Schema

### 1. `menu` Collection
```json
{
  "_id": "ObjectId",
  "item_id": 1,
  "name": "Cheese Burger",
  "category": "Fast Food",
  "price": 8.99,
  "stock": 15
}
```

### 2. `orders` Collection
```json
{
  "_id": "ORD-0001",
  "order_id": "ORD-0001",
  "items": [
    {
      "menu_id": 1,
      "name": "Cheese Burger",
      "price": 8.99,
      "quantity": 2,
      "item_total": 17.98
    }
  ],
  "total_amount": 17.98,
  "status": "SERVED",
  "created_at": "2026-11-23T14:23:24.000000",
  "updated_at": "2026-11-23T14:23:31.000000"
}
```

---

## 🌟 5-Star Michelin Fine Dining Experience

The application is themed as **L'Étoile Royale • Maison de Haute Gastronomie**:

- **☀️ Day & 🌙 Night Ambience Switcher**:
  - **Night Mode (Michelin Noir & Champagne Gold)**: Deep caviar noir backgrounds, champagne gold typography, subtle glowing borders.
  - **Day Mode (L'Étoile Ivory & Antique Bronze)**: Refined Italian alabaster marble, antique bronze trims, and espresso text.
- **Dedicated Portals**:
  - **Dining Room Portal (`/`)**: Natural language table concierge, artisanal menu card, dynamic culinary progress tracker, and leather-embossed gold bill.
  - **Executive Kitchen Console (`/admin`)**: Active cooking tickets with 8-second timer and automated probability fallback, real-time MongoDB pantry controls, and intelligent order history.
- **Smart Orders Filter**:
  - Shows orders placed **today (present date)**.
  - If no orders have been placed today, automatically displays the **most recent 15 orders** from MongoDB!

- **`db.py`**: MongoDB database layer using **PyMongo** (with auto-fallback to mongomock if offline/sandboxed).
- **`restaurant_agent.py`**: Core LangGraph workflow definition, nodes, routing functions, and interactive CLI runner.
- **`llm_service.py`**: Dual-provider LLM caller (Gemini & Groq) with automatic fallback and order extraction.
- **`test_scenarios.py`**: Automated test suite simulating all 7 branch scenarios with MongoDB.
- **`.env`**: API keys & MongoDB connection string configuration (`MONGO_URI`, `MONGO_DB_NAME`).

---

## 🚀 How to Run

### 1. Configure Environment Variables
In `restaurantAgent/.env`:
```env
# MongoDB Configuration
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=restaurant_db

# LLM Keys
GROQ_API_KEY=your_groq_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

### 2. Run Interactive Terminal Mode
```bash
python restaurantAgent/restaurant_agent.py
```

### 3. Run Automated Comprehensive Test Suite
```bash
python restaurantAgent/test_scenarios.py
```
