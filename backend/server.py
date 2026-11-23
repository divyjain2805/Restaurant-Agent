import os
import sys
import uuid
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Add current backend directory to path
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

import db
import restaurant_agent
from langgraph.types import Command

app = FastAPI(title="Restaurant Automation API", version="1.0.0")

# Enable CORS for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Persistent compiled graph
compiled_agent = restaurant_agent.compile_graph()

# Models
class OrderRequest(BaseModel):
    user_input: str
    thread_id: Optional[str] = None

class ResumeRequest(BaseModel):
    thread_id: str
    response: Any

class RestockRequest(BaseModel):
    force: bool = False

# Persistent state tracking across user and admin portals
active_sessions: Dict[str, Dict[str, Any]] = {}

def extract_graph_response(config: Dict[str, Any]) -> Dict[str, Any]:
    """Inspects the current state of the LangGraph execution for thread_id."""
    thread_id = config["configurable"]["thread_id"]
    state_snapshot = compiled_agent.get_state(config)
    values = state_snapshot.values or {}
    tasks = state_snapshot.tasks
    active_interrupts = [i for t in tasks for i in t.interrupts] if tasks else []

    logs = values.get("workflow_logs", [])

    if active_interrupts:
        interrupt_data = active_interrupts[0].value
        resp = {
            "status": "INTERRUPTED",
            "thread_id": thread_id,
            "interrupt": interrupt_data,
            "order_id": values.get("order_id"),
            "workflow_logs": logs,
            "values": values
        }
        active_sessions[thread_id] = resp
        return resp

    status = values.get("status", "COMPLETED" if values.get("bill") else "DONE")
    resp = {
        "status": status,
        "thread_id": thread_id,
        "final_message": values.get("final_message", ""),
        "bill": values.get("bill"),
        "order_id": values.get("order_id"),
        "workflow_logs": logs,
        "values": values
    }
    active_sessions[thread_id] = resp
    return resp

@app.on_event("startup")
def startup_db():
    db.init_db()

@app.get("/api/menu")
def get_menu():
    """Retrieve all restaurant menu items with live stock and 24h restock info."""
    menu_items = db.get_all_menu()
    meta = db.get_db()["inventory_meta"].find_one({"_id": "restock_tracker"})
    return {
        "menu": menu_items,
        "last_restocked_at": meta.get("last_restocked_at") if meta else None,
        "restock_interval_hours": meta.get("restock_interval_hours", 24) if meta else 24
    }

@app.post("/api/order")
def start_order(req: OrderRequest):
    """Initiates a new restaurant order through the LangGraph workflow."""
    thread_id = req.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "user_input": req.user_input,
        "relevance_attempts": 0,
        "db_order_attempts": 0,
        "cook_attempts": 0,
        "workflow_logs": []
    }

    try:
        compiled_agent.invoke(initial_state, config=config)
        return extract_graph_response(config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/resume")
def resume_order(req: ResumeRequest):
    """Delivers user reorder or admin chef feedback to resume interrupted workflow."""
    config = {"configurable": {"thread_id": req.thread_id}}
    try:
        compiled_agent.invoke(Command(resume=req.response), config=config)
        return extract_graph_response(config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/order-status/{thread_id}")
def get_order_status(thread_id: str):
    """Allows customer or admin portal to query current status of an order."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        return extract_graph_response(config)
    except Exception:
        if thread_id in active_sessions:
            return active_sessions[thread_id]
        raise HTTPException(status_code=404, detail="Order thread not found.")

@app.get("/api/pending-reviews")
def get_pending_reviews():
    """Returns active orders currently waiting for Admin/Chef review in the kitchen."""
    reviews = []
    for tid, sess in list(active_sessions.items()):
        if sess.get("status") == "INTERRUPTED":
            int_data = sess.get("interrupt", {})
            if int_data.get("type") == "cook_admin_review":
                reviews.append({
                    "thread_id": tid,
                    "order_id": int_data.get("order_id"),
                    "attempt": int_data.get("attempt", 1),
                    "items": int_data.get("items", []),
                    "prompt": int_data.get("prompt"),
                    "timeout_seconds": int_data.get("timeout_seconds", 8),
                    "approval_probability": int_data.get("approval_probability", 0.85)
                })
    return {"reviews": reviews}

class UpdateStockRequest(BaseModel):
    name: str
    stock: int

@app.post("/api/menu/update-stock")
def update_stock(req: UpdateStockRequest):
    """Admin endpoint to manually adjust stock of an item in MongoDB."""
    db.get_db()["menu"].update_one({"name": req.name}, {"$set": {"stock": req.stock}})
    return {"success": True, "name": req.name, "new_stock": req.stock}

@app.post("/api/restock")
def restock_inventory(req: RestockRequest = RestockRequest()):
    """Triggers 24-hour auto-restock check or forced inventory replenishment."""
    was_restocked, msg = db.check_and_auto_restock(force=req.force)
    menu_items = db.get_all_menu()
    return {
        "was_restocked": was_restocked,
        "message": msg,
        "menu": menu_items
    }

@app.get("/api/orders")
def get_orders():
    """Retrieve all historical orders from MongoDB."""
    orders = list(db.get_db()["orders"].find({}, {"_id": 0}).sort("created_at", -1))
    return {"orders": orders}

# Serve frontend static assets
FRONTEND_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def serve_customer_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.get("/admin")
    def serve_admin_dashboard():
        return FileResponse(os.path.join(FRONTEND_DIR, "admin.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
