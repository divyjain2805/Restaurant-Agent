import os
import sys
import uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import restaurant_agent
from langgraph.types import Command

def test_hitl_timeout():
    test_db = "test_hitl_timeout_db"
    db.init_db(test_db)
    orig_db = db.MONGO_DB_NAME
    db.MONGO_DB_NAME = test_db

    print("\n" + "="*80)
    print("  TEST: 8-Second HITL Timeout & Probabilistic Cooking Outcome")
    print("="*80)

    app = restaurant_agent.compile_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "user_input": "1 Margherita Pizza",
        "relevance_attempts": 0,
        "db_order_attempts": 0,
        "cook_attempts": 0,
        "workflow_logs": []
    }

    # Step 1: Start order
    app.invoke(initial_state, config=config)
    state_snap = app.get_state(config)
    assert any(t.interrupts for t in state_snap.tasks), "Expected HITL interrupt for cook_admin_review"
    print("✅ Cook node reached HITL interrupt with 8s timer prompt.")

    # Step 2: Simulate 8-second timeout expiry by resuming with 'timeout'
    print("⏱️ Simulating 8-second timeout expiry (Admin did not respond)...")
    app.invoke(Command(resume="timeout"), config=config)

    # Check state after timeout auto-resolution
    final_snap = app.get_state(config)
    final_val = final_snap.values
    logs = final_val.get("workflow_logs", [])
    
    timeout_logs = [l for l in logs if "8s Timeout" in l or "probability" in l]
    print(f"👉 Generated log: {timeout_logs[-1] if timeout_logs else 'No timeout log'}")
    assert len(timeout_logs) > 0, "Expected probabilistic auto-resolution log entry"

    cook_status = final_val.get("cook_status")
    print(f"👉 Outcome from probability: cook_status = {cook_status}, overall status = {final_val.get('status')}")
    assert cook_status in ["COOKED", "FAILED"]

    # Cleanup
    db.MONGO_DB_NAME = orig_db
    try:
        db.get_mongo_client().drop_database(test_db)
    except Exception:
        pass

    print("\n" + "="*80)
    print("  🎉 8-SECOND TIMEOUT & PROBABILITY RESOLUTION TEST PASSED!")
    print("="*80 + "\n")

if __name__ == "__main__":
    test_hitl_timeout()
