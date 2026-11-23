import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
from datetime import datetime, timedelta

def verify():
    test_db = "test_verify_restock_db"
    print("1. Initializing MongoDB...")
    db.init_db(test_db)

    # 1. Check initial stock
    burger = db.get_db(test_db)["menu"].find_one({"name": "Cheese Burger"})
    print(f"   Initial 'Cheese Burger' stock: {burger['stock']} (default_stock: {burger['default_stock']})")
    assert burger["stock"] == 15

    # 2. Order 5 burgers
    print("2. Reserving order of 5 Cheese Burgers...")
    avail, oid, msg, items, total = db.check_and_reserve_order([{"name": "Cheese Burger", "quantity": 5}], test_db)
    print(f"   Order result: {avail}, Order ID: {oid}, Total: ${total}")
    
    burger_after_order = db.get_db(test_db)["menu"].find_one({"name": "Cheese Burger"})
    print(f"   Stock after order: {burger_after_order['stock']}")
    assert burger_after_order["stock"] == 10

    # 3. Check restock before 24h
    print("3. Checking restock before 24 hours elapsed...")
    restocked, status_msg = db.check_and_auto_restock(test_db, hours_interval=24)
    print(f"   Restocked: {restocked} -> {status_msg}")
    assert restocked is False

    # 4. Simulate 25 hours elapsed
    print("4. Simulating 25 hours elapsed in MongoDB...")
    past_time = (datetime.utcnow() - timedelta(hours=25)).isoformat()
    db.get_db(test_db)["inventory_meta"].update_one(
        {"_id": "restock_tracker"},
        {"$set": {"last_restocked_at": past_time}}
    )

    # 5. Check restock after 25h
    print("5. Triggering auto-restock check after 25 hours...")
    restocked_after, restock_msg = db.check_and_auto_restock(test_db, hours_interval=24)
    print(f"   Restocked: {restocked_after} -> {restock_msg}")
    assert restocked_after is True

    # 6. Verify stock replenished
    burger_replenished = db.get_db(test_db)["menu"].find_one({"name": "Cheese Burger"})
    print(f"   Stock after replenishment: {burger_replenished['stock']} / {burger_replenished['default_stock']}")
    assert burger_replenished["stock"] == 15

    # Cleanup
    db.get_mongo_client().drop_database(test_db)
    print("\n✅ RESULT: 24-Hour Auto-Restock is 100% WORKING and VERIFIED!")

if __name__ == "__main__":
    verify()
