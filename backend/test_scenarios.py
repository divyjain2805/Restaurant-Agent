import os
import sys
import uuid
import unittest
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import restaurant_agent
from langgraph.types import Command

TEST_DB = "test_restaurant_db"

def run_scenario(scenario_name: str, 
                 initial_input: str, 
                 env_override: Dict[str, str] = None, 
                 resume_inputs: List[Any] = None) -> Dict[str, Any]:
    """
    Executes a test scenario through the LangGraph restaurant agent,
    handling any human-in-the-loop interrupts automatically using resume_inputs.
    """
    print("\n" + "="*80)
    print(f"  SCENARIO TEST: {scenario_name}")
    print("="*80)

    # Temporary environment override
    old_env = {}
    if env_override:
        for k, v in env_override.items():
            old_env[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # Re-initialize MongoDB for test isolation
    orig_db_name = db.MONGO_DB_NAME
    db.MONGO_DB_NAME = TEST_DB
    client = db.get_mongo_client()
    try:
        client.drop_database(TEST_DB)
    except Exception:
        pass
    db.init_db(TEST_DB)

    app = restaurant_agent.compile_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "user_input": initial_input,
        "relevance_attempts": 0,
        "db_order_attempts": 0,
        "cook_attempts": 0,
        "workflow_logs": []
    }

    resume_idx = 0
    resume_list = resume_inputs or []

    # Invoke graph initially
    app.invoke(initial_state, config=config)

    # Process interrupts until done
    while True:
        state_snap = app.get_state(config)
        tasks = state_snap.tasks
        active_interrupts = [i for t in tasks for i in t.interrupts] if tasks else []

        if not active_interrupts and not state_snap.next:
            break

        if active_interrupts:
            int_val = active_interrupts[0].value
            if resume_idx < len(resume_list):
                val_to_send = resume_list[resume_idx]
                resume_idx += 1
                int_type = int_val.get("type") if isinstance(int_val, dict) else "interrupt"
                print(f"👉 [TEST SIMULATOR] Responding to Interrupt '{int_type}' with: '{val_to_send}'")
                app.invoke(Command(resume=val_to_send), config=config)
            else:
                print(f"⚠️ Warning: No resume input provided for interrupt: {int_val}")
                break
        else:
            app.invoke(None, config=config)

    final_state = app.get_state(config).values

    # Restore environment and MongoDB name
    if env_override:
        for k, old_val in old_env.items():
            if old_val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_val
    db.MONGO_DB_NAME = orig_db_name

    try:
        client.drop_database(TEST_DB)
    except Exception:
        pass

    print("-" * 80)
    print(f"🏁 RESULT: Status = {final_state.get('status')} | Cook = {final_state.get('cook_status')}")
    if final_state.get("final_message"):
        print(f"📝 Final Message Summary:\n{final_state.get('final_message').strip()[:200]}...")
    print("=" * 80 + "\n")

    return final_state


def run_all_tests():
    print("\n" + "#"*80)
    print("       RESTAURANT WORK AUTOMATION - COMPREHENSIVE TEST SUITE")
    print("#"*80)

    # -------------------------------------------------------------
    # 1. Missing API Keys -> Exit with Sorry
    # -------------------------------------------------------------
    state1 = run_scenario(
        scenario_name="1. Missing API Keys Check (Exit with sorry/regret)",
        initial_input="I want 1 Cheese Burger",
        env_override={"GEMINI_API_KEY": None, "GROQ_API_KEY": None}
    )
    assert state1.get("status") == "FAILED"
    assert "sorry" in state1.get("final_message", "").lower()

    # -------------------------------------------------------------
    # 2. Irrelevant input -> 2nd chance also irrelevant -> Exit
    # -------------------------------------------------------------
    state2 = run_scenario(
        scenario_name="2. Irrelevant Input (Fails both chances -> Exit)",
        initial_input="Tell me the distance to Mars",
        resume_inputs=["Who won the 1994 World Cup?"]
    )
    assert state2.get("status") == "FAILED"
    assert state2.get("relevance_attempts") == 2

    # -------------------------------------------------------------
    # 3. Irrelevant input -> 2nd chance valid food order -> Success
    # -------------------------------------------------------------
    state3 = run_scenario(
        scenario_name="3. Irrelevant Input -> Corrected on 2nd Chance -> Cook & Serve",
        initial_input="What is the weather in Tokyo?",
        resume_inputs=["1 Cheese Burger", "approved"]
    )
    assert state3.get("status") == "COMPLETED"
    assert state3.get("is_relevant") is True
    assert state3.get("bill") is not None

    # -------------------------------------------------------------
    # 4. Item not in DB -> 2nd chance also not in DB -> Exit
    # -------------------------------------------------------------
    state4 = run_scenario(
        scenario_name="4. Item Not in DB (Fails both chances -> Exit)",
        initial_input="2 Grilled Lobster and Caviar",
        resume_inputs=["1 Dragon Fruit Salad"]
    )
    assert state4.get("status") == "FAILED"
    assert state4.get("db_order_attempts") == 2

    # -------------------------------------------------------------
    # 5. Happy Path (Item in DB -> Cook Approved First Try -> Serve & Bill)
    # -------------------------------------------------------------
    state5 = run_scenario(
        scenario_name="5. Happy Path (Burger & Coke -> Cook Approved -> Bill & Greeting)",
        initial_input="2 Cheese Burger and 1 Coca Cola",
        resume_inputs=["approved"]
    )
    assert state5.get("status") == "COMPLETED"
    assert state5.get("cook_status") == "COOKED"
    assert state5.get("bill")["grand_total"] > 0

    # -------------------------------------------------------------
    # 6. Cook Fails 1st Attempt -> Remakes (Chance 2) -> Approved -> Serve
    # -------------------------------------------------------------
    state6 = run_scenario(
        scenario_name="6. Cook Fails Attempt 1 -> Order in DB -> Remakes (Chance 2) -> Approved -> Serve",
        initial_input="1 Creamy Alfredo Pasta",
        resume_inputs=["failed", "approved"]
    )
    assert state6.get("status") == "COMPLETED"
    assert state6.get("cook_attempts") == 2
    assert state6.get("cook_status") == "COOKED"

    # -------------------------------------------------------------
    # 7. Cook Fails 1st Attempt & Remake also fails -> Cancel & Exit
    # -------------------------------------------------------------
    state7 = run_scenario(
        scenario_name="7. Cook Fails Both Attempts -> Cancel & Exit with Regret",
        initial_input="1 Pepperoni Pizza",
        resume_inputs=["failed", "failed"]
    )
    assert state7.get("status") == "FAILED"
    assert state7.get("cook_attempts") == 2
    assert state7.get("cook_status") == "FAILED"
    assert "cancelled" in state7.get("final_message", "").lower()

    # -------------------------------------------------------------
    # 8. 24-Hour Inventory Auto-Restock Verification
    # -------------------------------------------------------------
    print("\n" + "="*80)
    print("  SCENARIO TEST: 8. 24-Hour Inventory Auto-Restock Verification")
    print("="*80)
    test_db_name = "test_restock_db"
    db.init_db(test_db_name)
    
    # 1. Place an order to deplete stock
    _, _, _, items_res, _ = db.check_and_reserve_order([{"name": "Cheese Burger", "quantity": 5}], test_db_name)
    burger_doc = db.get_db(test_db_name)["menu"].find_one({"name": "Cheese Burger"})
    print(f"👉 Stock after order of 5 Cheese Burgers: {burger_doc['stock']} (default is {burger_doc['default_stock']})")
    assert burger_doc["stock"] == 10

    # 2. Check restock before 24 hours (should not restock)
    restocked, msg = db.check_and_auto_restock(test_db_name, hours_interval=24)
    print(f"👉 Restock check before 24 hours elapsed: restocked={restocked} ({msg})")
    assert restocked is False

    # 3. Simulate passage of 25 hours by updating last_restocked_at
    from datetime import datetime, timedelta
    past_time = (datetime.utcnow() - timedelta(hours=25)).isoformat()
    db.get_db(test_db_name)["inventory_meta"].update_one(
        {"_id": "restock_tracker"},
        {"$set": {"last_restocked_at": past_time}}
    )
    print(f"👉 Simulated 25 hours elapsed (timestamp set to: {past_time})")

    # 4. Trigger auto-restock check
    restocked_after, msg_after = db.check_and_auto_restock(test_db_name, hours_interval=24)
    print(f"👉 Restock check after 25 hours: restocked={restocked_after} ({msg_after})")
    assert restocked_after is True

    # 5. Verify stock is restored to 15
    burger_restocked = db.get_db(test_db_name)["menu"].find_one({"name": "Cheese Burger"})
    print(f"👉 Stock after 24-hour replenishment: {burger_restocked['stock']} / {burger_restocked['default_stock']}")
    assert burger_restocked["stock"] == burger_restocked["default_stock"]

    # Cleanup
    db.get_mongo_client().drop_database(test_db_name)

    print("\n" + "="*80)
    print("  🎉 ALL 8 RESTAURANT WORK AUTOMATION & RESTOCK SCENARIOS PASSED!")
    print("="*80 + "\n")

if __name__ == "__main__":
    run_all_tests()
