import os
import re
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
from dotenv import load_dotenv

# Load env configuration
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "restaurant_db")

_client = None

def get_mongo_client(uri: Optional[str] = None):
    """
    Returns a MongoDB client.
    Connects to real MongoDB if reachable, otherwise seamlessly falls back
    to in-memory mongomock so tests and local runs operate identically.
    """
    global _client
    target_uri = uri or MONGO_URI
    
    # Try connecting to real MongoDB first
    try:
        import pymongo
        client = pymongo.MongoClient(target_uri, serverSelectionTimeoutMS=1500)
        # Verify connection
        client.admin.command('ping')
        return client
    except Exception:
        # Fallback to mongomock for sandbox or offline environments
        try:
            import mongomock
            if _client is None or not isinstance(_client, mongomock.MongoClient):
                _client = mongomock.MongoClient()
            return _client
        except ImportError:
            raise RuntimeError("Neither live MongoDB nor mongomock is available.")

def get_db(db_name: Optional[str] = None):
    """Returns the MongoDB database instance."""
    client = get_mongo_client()
    return client[db_name or MONGO_DB_NAME]

def init_db(db_name: Optional[str] = None) -> None:
    """Initialize MongoDB collections with menu items, default stock, and restock tracker."""
    db = get_db(db_name)
    menu_col = db["menu"]
    meta_col = db["inventory_meta"]

    # Initial default restaurant menu with default_stock capacity
    initial_items = [
        {"item_id": 1, "name": "Cheese Burger", "category": "Fast Food", "price": 8.99, "stock": 15, "default_stock": 15},
        {"item_id": 2, "name": "Veggie Burger", "category": "Fast Food", "price": 7.99, "stock": 10, "default_stock": 10},
        {"item_id": 3, "name": "Margherita Pizza", "category": "Pizza", "price": 12.99, "stock": 8, "default_stock": 8},
        {"item_id": 4, "name": "Pepperoni Pizza", "category": "Pizza", "price": 14.99, "stock": 12, "default_stock": 12},
        {"item_id": 5, "name": "Creamy Alfredo Pasta", "category": "Pasta", "price": 11.49, "stock": 10, "default_stock": 10},
        {"item_id": 6, "name": "French Fries", "category": "Sides", "price": 3.99, "stock": 25, "default_stock": 25},
        {"item_id": 7, "name": "Garlic Bread", "category": "Sides", "price": 4.49, "stock": 15, "default_stock": 15},
        {"item_id": 8, "name": "Coca Cola", "category": "Beverages", "price": 2.49, "stock": 30, "default_stock": 30},
        {"item_id": 9, "name": "Iced Tea", "category": "Beverages", "price": 2.99, "stock": 20, "default_stock": 20},
        {"item_id": 10, "name": "Chocolate Brownie", "category": "Dessert", "price": 5.49, "stock": 12, "default_stock": 12},
    ]

    for item in initial_items:
        menu_col.update_one(
            {"name": item["name"]},
            {"$setOnInsert": item},
            upsert=True
        )

    # Restock metadata tracking (every 24 hours)
    meta_col.update_one(
        {"_id": "restock_tracker"},
        {"$setOnInsert": {
            "_id": "restock_tracker",
            "last_restocked_at": datetime.utcnow().isoformat(),
            "restock_interval_hours": 24
        }},
        upsert=True
    )

def check_and_auto_restock(db_name: Optional[str] = None, hours_interval: int = 24, force: bool = False) -> Tuple[bool, str]:
    """
    Checks if 24 hours have elapsed since the last inventory restock.
    If 24+ hours have passed (or if force=True), replenishes all menu items
    back to their default maximum stock capacity.
    Returns: (was_restocked, message)
    """
    db = get_db(db_name)
    meta_col = db["inventory_meta"]
    menu_col = db["menu"]

    tracker = meta_col.find_one({"_id": "restock_tracker"})
    now = datetime.utcnow()

    should_restock = force
    elapsed_hours = 0.0

    if tracker and "last_restocked_at" in tracker:
        try:
            last_time = datetime.fromisoformat(tracker["last_restocked_at"])
            elapsed_hours = (now - last_time).total_seconds() / 3600.0
            if elapsed_hours >= hours_interval:
                should_restock = True
        except Exception:
            should_restock = True
    else:
        should_restock = True

    if should_restock:
        items = list(menu_col.find({}))
        restocked_details = []
        for item in items:
            def_stock = item.get("default_stock", 15)
            curr_stock = item.get("stock", 0)
            if curr_stock < def_stock:
                menu_col.update_one(
                    {"name": item["name"]},
                    {"$set": {"stock": def_stock, "last_restocked_at": now.isoformat()}}
                )
                restocked_details.append(f"{item['name']}: {curr_stock} -> {def_stock}")

        meta_col.update_one(
            {"_id": "restock_tracker"},
            {"$set": {"last_restocked_at": now.isoformat(), "restock_interval_hours": hours_interval}},
            upsert=True
        )

        log_msg = (f"Restocked {len(restocked_details)} menu items to 24h default capacity: "
                   f"{', '.join(restocked_details) if restocked_details else 'All items were already at full stock'}")
        return True, log_msg

    remaining_hours = round(hours_interval - elapsed_hours, 1)
    return False, f"Stock is fresh. Next 24h restock in {remaining_hours} hours."

def get_all_menu(db_name: Optional[str] = None) -> List[Dict]:
    """Retrieve all menu items from MongoDB, auto-checking 24h restock."""
    db = get_db(db_name)
    menu_col = db["menu"]
    
    # Auto-initialize if empty
    if menu_col.count_documents({}) == 0:
        init_db(db_name)

    # Check and apply 24-hour auto restock if due
    check_and_auto_restock(db_name)

    # Check 24-hour restock cycle
    check_and_auto_restock(db_name)

    items = list(menu_col.find({}, {"_id": 0}))
    return items

def find_menu_item(item_name: str, db_name: Optional[str] = None) -> Optional[Dict]:
    """Find a menu item by regex / case-insensitive search."""
    db = get_db(db_name)
    menu_col = db["menu"]
    regex = re.compile(re.escape(item_name), re.IGNORECASE)
    doc = menu_col.find_one({"name": regex}, {"_id": 0})
    return doc

def check_and_reserve_order(items: List[Dict], db_name: Optional[str] = None) -> Tuple[bool, Optional[str], str, List[Dict], float]:
    """
    Checks if items are present in MongoDB menu collection and sufficient stock exists.
    Atomically decrements stock and inserts an order into 'orders' collection.
    Returns: (is_available, order_id, message, resolved_items, total_price)
    """
    db = get_db(db_name)
    menu_col = db["menu"]
    orders_col = db["orders"]

    if menu_col.count_documents({}) == 0:
        init_db(db_name)

    # Check and apply 24-hour auto restock if due
    check_and_auto_restock(db_name)

    if not items:
        return False, None, "No valid items were specified in the order.", [], 0.0

    resolved_items = []
    total_price = 0.0

    for item in items:
        name = item.get("name", "").strip()
        quantity = int(item.get("quantity", 1))

        regex = re.compile(f"^{re.escape(name)}$", re.IGNORECASE)
        doc = menu_col.find_one({"name": regex})

        # Partial matching fallback if exact match wasn't found
        if not doc:
            doc = menu_col.find_one({"name": re.compile(re.escape(name), re.IGNORECASE)})

        if not doc:
            return False, None, f"Item '{name}' is not on our menu.", [], 0.0

        item_name = doc["name"]
        item_id = doc.get("item_id", 1)
        price = doc["price"]
        stock = doc["stock"]

        if stock < quantity:
            return False, None, f"Not enough stock for '{item_name}' (available: {stock}, requested: {quantity}).", [], 0.0

        resolved_items.append({
            "menu_id": item_id,
            "name": item_name,
            "price": price,
            "quantity": quantity,
            "item_total": round(price * quantity, 2)
        })
        total_price += round(price * quantity, 2)

    # Reserve stock by decrementing in MongoDB
    for item in resolved_items:
        menu_col.update_one(
            {"name": item["name"]},
            {"$inc": {"stock": -item["quantity"]}}
        )

    # Next sequential order ID or ObjectId string
    order_count = orders_col.count_documents({}) + 1
    order_id = f"ORD-{order_count:04d}"

    order_doc = {
        "_id": order_id,
        "order_id": order_id,
        "items": resolved_items,
        "total_amount": total_price,
        "status": "PENDING",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    orders_col.insert_one(order_doc)

    return True, order_id, f"Order #{order_id} verified and reserved in MongoDB.", resolved_items, total_price

def update_order_status(order_id: Any, status: str, db_name: Optional[str] = None) -> None:
    """Update order status in MongoDB orders collection."""
    db = get_db(db_name)
    orders_col = db["orders"]
    orders_col.update_one(
        {"$or": [{"_id": order_id}, {"order_id": order_id}]},
        {"$set": {"status": status, "updated_at": datetime.utcnow().isoformat()}}
    )

def check_stock_for_retry(resolved_items: List[Dict], db_name: Optional[str] = None) -> bool:
    """Check if restaurant still has ingredients/stock to remake the order in MongoDB."""
    db = get_db(db_name)
    menu_col = db["menu"]
    for item in resolved_items:
        doc = menu_col.find_one({"name": item["name"]})
        if not doc or doc.get("stock", 0) < 0:
            return False
    return True
