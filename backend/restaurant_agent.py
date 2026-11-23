import os
import sys
import json
import uuid
import random
import threading
from typing import TypedDict, List, Dict, Any, Optional, Tuple, Union
from datetime import datetime

# Add local directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import llm_service

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command


# ============================================================================
# STATE DEFINITION
# ============================================================================

class RestaurantOrderState(TypedDict):
    # User Input & Attempt Counters
    user_input: str
    relevance_attempts: int        # Max 1 retry (total 2 chances)
    db_order_attempts: int         # Max 1 retry (total 2 chances)
    cook_attempts: int             # Max 1 retry (total 2 chances)

    # API & LLM Info
    api_available: bool
    active_provider: Optional[str]
    is_relevant: bool
    relevance_reason: str
    structured_order: List[Dict[str, Any]]

    # Database & Inventory
    order_id: Optional[Any]
    db_verified: bool
    db_message: str
    resolved_items: List[Dict[str, Any]]
    total_price: float

    # Cook & HITL
    cook_status: str               # 'NOT_STARTED', 'COOKING', 'COOKED', 'FAILED'
    cook_admin_decision: Optional[str]

    # Serve & Billing
    bill: Optional[Dict[str, Any]]
    final_message: str
    status: str                    # 'IN_PROGRESS', 'COMPLETED', 'FAILED'
    workflow_logs: List[str]


# ============================================================================
# LOGGING & PROBABILISTIC HITL HELPERS
# ============================================================================

def log_task(task_name: str, status_icon: str, message: str, logs: List[str]) -> List[str]:
    """Helper to format and display live task progress and persist to logs."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    banner = f"[{timestamp}] {status_icon} [TASK: {task_name}] {message}"
    print(banner)
    logs.append(banner)
    return logs

def resolve_cook_decision(decision_input: Any, default_approval_rate: float = 0.85) -> Tuple[bool, str]:
    """
    Evaluates admin decision.
    If timeout (8s expired), empty, or auto, automatically determines approval/failure
    based on probability (default: 85% success, 15% failure).
    Returns: (is_success, log_reason)
    """
    if decision_input is None:
        dec = "timeout"
    elif isinstance(decision_input, dict):
        dec = str(decision_input.get("decision", "timeout")).strip().lower()
    else:
        dec = str(decision_input).strip().lower()

    if dec in ["timeout", "auto", "probabilistic", "none", "", "timer_expired"]:
        roll = random.random()
        is_app = roll < default_approval_rate
        pct = int(default_approval_rate * 100)
        outcome_str = "APPROVED" if is_app else "FAILED"
        return is_app, f"⏱️ 8s Timeout expired. Auto-resolved via probability ({pct}% approval chance -> {outcome_str})"
    
    is_app = dec in ["approved", "yes", "success", "true", "y", "ok"]
    return is_app, f"Manual decision by Admin: '{dec.upper()}'"

def timed_admin_input(prompt: str, timeout: float = 8.0) -> str:
    """Prompt admin for input with an 8-second countdown. If no input, defaults to 'timeout'."""
    print(f"{prompt} (Timer: {timeout:.0f}s - press Enter to submit, or wait for auto-probability)")
    user_input = [None]

    def get_input():
        try:
            user_input[0] = input("[approved / failed]> ").strip()
        except Exception:
            pass

    t = threading.Thread(target=get_input, daemon=True)
    t.start()
    t.join(timeout)

    if user_input[0] is not None and user_input[0] != "":
        return user_input[0]
    
    print(f"\n⏱️  8-second timer expired! Auto-resolving via cooking probability...")
    return "timeout"


# ============================================================================
# GRAPH NODES
# ============================================================================

def api_check_node(state: RestaurantOrderState) -> Dict[str, Any]:
    """
    Work 1: Check if API key (Gemini or Groq) is present.
    If not, take exit with sorry/regret message.
    """
    logs = list(state.get("workflow_logs", []))
    status_info = llm_service.get_api_status()

    if not status_info["has_any"]:
        msg = ("We are deeply sorry, but our restaurant automation system is currently unavailable "
               "because no AI API keys (Gemini / Groq) are configured. Please contact the manager.")
        logs = log_task("API Check", "❌", "No Gemini or Groq API keys found. Exiting with apology.", logs)
        return {
            "api_available": False,
            "active_provider": None,
            "final_message": msg,
            "status": "FAILED",
            "workflow_logs": logs
        }

    provider = status_info["preferred"]
    logs = log_task("API Check", "✅", f"API keys detected. Active LLM provider: {provider.upper()}.", logs)
    return {
        "api_available": True,
        "active_provider": provider,
        "workflow_logs": logs
    }


def relevance_and_parse_node(state: RestaurantOrderState) -> Dict[str, Any]:
    """
    Work 2 & 3:
    - If input is not relevant to food order, give 1 chance to reorder. If again not relevant, exit.
    - If relevant, extract structured order.
    """
    logs = list(state.get("workflow_logs", []))
    user_input = state.get("user_input", "")
    relevance_attempts = state.get("relevance_attempts", 0)

    # Fetch menu items from DB for context
    menu_items = db.get_all_menu()
    analysis = llm_service.analyze_user_order(user_input, menu_items)
    is_relevant = analysis.get("is_relevant", False)
    items = analysis.get("items", [])
    reason = analysis.get("reason", "")

    if not is_relevant:
        if relevance_attempts == 0:
            logs = log_task("Input Relevance", "⚠️", 
                            f"Input '{user_input}' is not relevant to a food order. Offering 1 chance to reorder.", logs)
            
            # Pause graph and ask human/user for 2nd chance input
            new_input = interrupt({
                "type": "reorder_irrelevant",
                "message": ("Sorry, your request does not seem to be a food order. "
                            "You have ONE chance to enter a valid food or drink order. What would you like to have?"),
                "attempt": 1
            })

            # Check new input
            logs = log_task("Input Relevance Retry", "🔄", f"Received second chance input: '{new_input}'", logs)
            analysis_retry = llm_service.analyze_user_order(str(new_input), menu_items)
            
            if not analysis_retry.get("is_relevant", False):
                msg = ("We are sorry, but your second input was also not recognized as a food order. "
                       "Exiting order session. Have a great day!")
                logs = log_task("Input Relevance Retry", "❌", "Second input still not relevant. Terminating.", logs)
                return {
                    "user_input": str(new_input),
                    "relevance_attempts": 2,
                    "is_relevant": False,
                    "relevance_reason": "Second input not food related.",
                    "structured_order": [],
                    "final_message": msg,
                    "status": "FAILED",
                    "workflow_logs": logs
                }
            else:
                logs = log_task("Input Relevance Retry", "✅", 
                                f"Second input is valid food order: {analysis_retry.get('items')}", logs)
                return {
                    "user_input": str(new_input),
                    "relevance_attempts": 1,
                    "is_relevant": True,
                    "relevance_reason": analysis_retry.get("reason", "Valid order on retry."),
                    "structured_order": analysis_retry.get("items", []),
                    "workflow_logs": logs
                }
        else:
            msg = ("We are sorry, but we could not understand your order after two attempts. "
                   "Taking exit now. Please visit again!")
            logs = log_task("Input Relevance", "❌", "Non-relevant input after retry. Terminating.", logs)
            return {
                "relevance_attempts": relevance_attempts + 1,
                "is_relevant": False,
                "structured_order": [],
                "final_message": msg,
                "status": "FAILED",
                "workflow_logs": logs
            }

    logs = log_task("Input Relevance", "✅", 
                    f"Relevant food order parsed: {items} ({reason})", logs)
    return {
        "is_relevant": True,
        "relevance_reason": reason,
        "structured_order": items,
        "workflow_logs": logs
    }


def database_check_node(state: RestaurantOrderState) -> Dict[str, Any]:
    """
    Work 3: Check database for order.
    Checks 24-hour auto-restock cycle, checks stock in MongoDB,
    if present reserves stock and moves to kitchen.
    If not, gives 1 chance to re-order from available menu.
    """
    logs = list(state.get("workflow_logs", []))
    structured_order = state.get("structured_order", [])
    db_order_attempts = state.get("db_order_attempts", 0)

    # Check 24-hour auto restock status
    was_restocked, restock_msg = db.check_and_auto_restock()
    if was_restocked:
        logs = log_task("Inventory 24h Auto-Restock", "🔄", restock_msg, logs)

    is_avail, order_id, db_msg, resolved_items, total_price = db.check_and_reserve_order(structured_order)

    if not is_avail:
        if db_order_attempts == 0:
            logs = log_task("Database Inventory Check", "⚠️", 
                            f"{db_msg} Offering 1 chance to re-order from available menu.", logs)
            
            all_menu = db.get_all_menu()
            menu_summary = ", ".join([f"{m['name']} (${m['price']:.2f})" for m in all_menu if m['stock'] > 0])
            
            # Pause graph and ask human/user for second chance order
            new_order_input = interrupt({
                "type": "reorder_db_not_found",
                "message": f"Sorry, {db_msg}\nYou have ONE chance to reorder from our available menu:\n{menu_summary}\nPlease enter your choice:",
                "available_menu": menu_summary,
                "attempt": 1
            })

            logs = log_task("Database Reorder Retry", "🔄", f"Received reorder choice: '{new_order_input}'", logs)
            
            # Re-parse items
            analysis_retry = llm_service.analyze_user_order(str(new_order_input), all_menu)
            retry_items = analysis_retry.get("items", [])
            
            is_avail_retry, order_id_retry, db_msg_retry, resolved_retry, total_retry = db.check_and_reserve_order(retry_items)
            
            if not is_avail_retry:
                msg = (f"We apologize, but your reordered item is also not available: {db_msg_retry} "
                       "Taking exit with apologies.")
                logs = log_task("Database Reorder Retry", "❌", "Item still unavailable in DB on retry. Terminating.", logs)
                return {
                    "db_order_attempts": 2,
                    "db_verified": False,
                    "db_message": db_msg_retry,
                    "resolved_items": [],
                    "total_price": 0.0,
                    "final_message": msg,
                    "status": "FAILED",
                    "workflow_logs": logs
                }
            else:
                logs = log_task("Database Reorder Retry", "✅", 
                                f"Order #{order_id_retry} verified and reserved in database! Total: ${total_retry:.2f}", logs)
                return {
                    "order_id": order_id_retry,
                    "db_order_attempts": 1,
                    "db_verified": True,
                    "db_message": db_msg_retry,
                    "resolved_items": resolved_retry,
                    "total_price": total_retry,
                    "workflow_logs": logs
                }
        else:
            msg = ("We are sorry, but the requested items are not present in our database. "
                   "Taking exit with regret. Have a good day!")
            logs = log_task("Database Inventory Check", "❌", "Item not in database after retry. Terminating.", logs)
            return {
                "db_order_attempts": db_order_attempts + 1,
                "db_verified": False,
                "db_message": db_msg,
                "final_message": msg,
                "status": "FAILED",
                "workflow_logs": logs
            }

    logs = log_task("Database Inventory Check", "✅", 
                    f"Order #{order_id} verified in DB: {resolved_items} (Total: ${total_price:.2f}). Moving to kitchen.", logs)
    return {
        "order_id": order_id,
        "db_verified": True,
        "db_message": db_msg,
        "resolved_items": resolved_items,
        "total_price": total_price,
        "workflow_logs": logs
    }


def cook_node(state: RestaurantOrderState) -> Dict[str, Any]:
    """
    Cook takes that task to make the order:
    - If cook successful to make -> go next (Serve).
    - If not -> has 1 chance to make it again.
      - If order is not present in database -> take exit with sorry.
      - If order is present in database -> update it and make again.
    - Uses Human Interrupt (Admin / Chef role verification: approved or failed).
    """
    logs = list(state.get("workflow_logs", []))
    order_id = state["order_id"]
    resolved_items = state["resolved_items"]
    cook_attempts = state.get("cook_attempts", 0)

    # Update DB to COOKING
    db.update_order_status(order_id, "COOKING")
    logs = log_task("Kitchen Cook", "👨‍🍳", 
                    f"Chef is preparing Order #{order_id} ({resolved_items}). Awaiting Admin/Chef verification...", logs)

    # Human-in-the-Loop Interrupt: Admin role verifies cooking outcome with 8s timer
    admin_review = interrupt({
        "type": "cook_admin_review",
        "order_id": order_id,
        "attempt": cook_attempts + 1,
        "items": resolved_items,
        "timeout_seconds": 8,
        "approval_probability": 0.85,
        "prompt": "Admin/Chef role: Is the dish cooked successfully? (approved / failed):"
    })

    # Interpret admin response or apply probability if timed out (8s)
    is_success, decision_reason = resolve_cook_decision(admin_review, default_approval_rate=0.85)
    logs = log_task("Admin HITL Verification", "📋", decision_reason, logs)

    if is_success:
        db.update_order_status(order_id, "COOKED")
        logs = log_task("Kitchen Cook", "✅", 
                        f"Order #{order_id} is successfully prepared! Passing to Server.", logs)
        return {
            "cook_status": "COOKED",
            "cook_admin_decision": "approved",
            "cook_attempts": cook_attempts + 1,
            "workflow_logs": logs
        }

    # Cook failed on Attempt 1: check if retry allowed
    cook_attempts += 1
    logs = log_task("Kitchen Cook", "⚠️", 
                    f"Cooking Attempt #{cook_attempts} was NOT successful ({decision_reason}). Checking retry policy...", logs)

    if cook_attempts == 1:
        # Check if order is still present in database to remake
        has_stock = db.check_stock_for_retry(resolved_items)
        if not has_stock:
            db.update_order_status(order_id, "CANCELLED")
            msg = ("We are extremely sorry! The cook encountered an error preparing your order, "
                   "and the required items/ingredients are no longer present in our database to remake it. "
                   "Taking exit with sincere apologies.")
            logs = log_task("Kitchen Cook Retry", "❌", "Order items not available in DB for remake. Cancelling.", logs)
            return {
                "cook_status": "FAILED",
                "cook_attempts": cook_attempts,
                "final_message": msg,
                "status": "FAILED",
                "workflow_logs": logs
            }

        # Order is present in database -> update it and make again!
        db.update_order_status(order_id, "COOKING_RETRY")
        logs = log_task("Kitchen Cook Retry", "🔄", 
                        f"Order #{order_id} confirmed in database. Kitchen is remaking order (Chance 2). Awaiting Admin verification (8s timer)...", logs)

        # 2nd Chance Cook Interrupt
        admin_retry_review = interrupt({
            "type": "cook_admin_review",
            "order_id": order_id,
            "attempt": 2,
            "items": resolved_items,
            "timeout_seconds": 8,
            "approval_probability": 0.85,
            "prompt": "Admin/Chef role (Chance 2): Is the remade dish cooked successfully? (approved / failed):"
        })

        retry_success, retry_decision_reason = resolve_cook_decision(admin_retry_review, default_approval_rate=0.85)
        logs = log_task("Admin HITL Retry Verification", "📋", retry_decision_reason, logs)

        if retry_success:
            db.update_order_status(order_id, "COOKED")
            logs = log_task("Kitchen Cook Retry", "✅", 
                            f"Order #{order_id} remade successfully on Chance 2! Passing to Server.", logs)
            return {
                "cook_status": "COOKED",
                "cook_admin_decision": "approved_on_retry",
                "cook_attempts": 2,
                "workflow_logs": logs
            }
        else:
            db.update_order_status(order_id, "CANCELLED")
            msg = ("We deeply regret to inform you that our kitchen was unable to prepare your order "
                   "even after remaking it. Your order has been cancelled and no charges will apply. "
                   "Please accept our apologies. Goodbye!")
            logs = log_task("Kitchen Cook Retry", "❌", f"Cook failed second attempt ({retry_decision_reason}). Cancelling order.", logs)
            return {
                "cook_status": "FAILED",
                "cook_attempts": 2,
                "final_message": msg,
                "status": "FAILED",
                "workflow_logs": logs
            }
    else:
        # Exceeded chances
        db.update_order_status(order_id, "CANCELLED")
        msg = "Cooking attempts exhausted. Taking exit with apologies."
        logs = log_task("Kitchen Cook", "❌", "Cooking attempts exhausted. Terminating.", logs)
        return {
            "cook_status": "FAILED",
            "cook_attempts": cook_attempts,
            "final_message": msg,
            "status": "FAILED",
            "workflow_logs": logs
        }


def serve_node(state: RestaurantOrderState) -> Dict[str, Any]:
    """
    Serve takes the food from cook and gives to user with food and bill of food,
    along with a polite greeting as well as clean exit.
    """
    logs = list(state.get("workflow_logs", []))
    order_id = state["order_id"]
    resolved_items = state["resolved_items"]
    subtotal = state["total_price"]

    # Calculate tax (5%) and grand total
    tax_rate = 0.05
    tax_amount = round(subtotal * tax_rate, 2)
    grand_total = round(subtotal + tax_amount, 2)

    bill = {
        "order_id": order_id,
        "items": resolved_items,
        "subtotal": subtotal,
        "tax_rate": "5%",
        "tax_amount": tax_amount,
        "grand_total": grand_total,
        "payment_status": "PAID"
    }

    # Update DB status to SERVED
    db.update_order_status(order_id, "SERVED")

    # Format itemized bill table
    bill_lines = ["\n🧾 ------------------- RESTAURANT BILL -------------------",
                  f"Order Number : #{order_id}",
                  f"Date & Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                  "----------------------------------------------------------",
                  f"{'Item':<28} {'Qty':<6} {'Price':<10} {'Total':<10}",
                  "----------------------------------------------------------"]
    for it in resolved_items:
        bill_lines.append(f"{it['name']:<28} {it['quantity']:<6} ${it['price']:<9.2f} ${it['item_total']:<9.2f}")
    bill_lines.append("----------------------------------------------------------")
    bill_lines.append(f"{'Subtotal:':<46} ${subtotal:.2f}")
    bill_lines.append(f"{'Tax (5%):':<46} ${tax_amount:.2f}")
    bill_lines.append(f"{'Grand Total:':<46} ${grand_total:.2f}")
    bill_lines.append("----------------------------------------------------------")

    bill_text = "\n".join(bill_lines)

    greeting_msg = (
        f"\n🍽️  SERVER: Here is your freshly prepared hot meal! Please enjoy your food.\n"
        f"{bill_text}\n\n"
        f"🌟 Thank you for dining with us! We hope you have a delightful dining experience "
        f"and we look forward to serving you again soon. Have a wonderful day! 👋\n"
    )

    logs = log_task("Serve & Billing", "🍽️", 
                    f"Food delivered for Order #{order_id}. Bill presented (${grand_total:.2f}) with warm greeting.", logs)

    return {
        "bill": bill,
        "final_message": greeting_msg,
        "status": "COMPLETED",
        "workflow_logs": logs
    }


# ============================================================================
# CONDITIONAL ROUTING FUNCTIONS
# ============================================================================

def route_after_api_check(state: RestaurantOrderState) -> str:
    if not state.get("api_available", False):
        return END
    return "relevance_and_parse"

def route_after_relevance(state: RestaurantOrderState) -> str:
    if not state.get("is_relevant", False):
        return END
    return "database_check"

def route_after_database_check(state: RestaurantOrderState) -> str:
    if not state.get("db_verified", False):
        return END
    return "cook"

def route_after_cook(state: RestaurantOrderState) -> str:
    if state.get("cook_status") != "COOKED":
        return END
    return "serve"


# ============================================================================
# WORKFLOW GRAPH BUILDER
# ============================================================================

def build_restaurant_graph() -> StateGraph:
    """Builds and compiles the complete LangGraph workflow."""
    builder = StateGraph(RestaurantOrderState)

    # Add Nodes
    builder.add_node("api_check", api_check_node)
    builder.add_node("relevance_and_parse", relevance_and_parse_node)
    builder.add_node("database_check", database_check_node)
    builder.add_node("cook", cook_node)
    builder.add_node("serve", serve_node)

    # Add Edges & Conditional Routing
    builder.add_edge(START, "api_check")
    builder.add_conditional_edges("api_check", route_after_api_check, {
        "relevance_and_parse": "relevance_and_parse",
        END: END
    })
    builder.add_conditional_edges("relevance_and_parse", route_after_relevance, {
        "database_check": "database_check",
        END: END
    })
    builder.add_conditional_edges("database_check", route_after_database_check, {
        "cook": "cook",
        END: END
    })
    builder.add_conditional_edges("cook", route_after_cook, {
        "serve": "serve",
        END: END
    })
    builder.add_edge("serve", END)

    return builder

def compile_graph(checkpointer: Optional[Any] = None):
    """Compiles the graph with MemorySaver checkpointer for human interrupts."""
    if checkpointer is None:
        checkpointer = MemorySaver()
    builder = build_restaurant_graph()
    return builder.compile(checkpointer=checkpointer)


# ============================================================================
# INTERACTIVE CONSOLE RUNNER
# ============================================================================

def run_interactive():
    """Runs the restaurant automation agent interactively in terminal."""
    db.init_db()
    app = compile_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("\n" + "="*70)
    print("      🍽️  RESTAURANT WORK AUTOMATION AGENT (LANGGRAPH)  🍽️")
    print("="*70)

    user_input = input("\nCustomer: What would you like to order today?\n> ")

    initial_state = {
        "user_input": user_input,
        "relevance_attempts": 0,
        "db_order_attempts": 0,
        "cook_attempts": 0,
        "workflow_logs": []
    }

    # Initial invoke
    print("\n--- Starting Restaurant Agent Workflow ---")
    app.invoke(initial_state, config=config)

    # Loop to handle any Human-in-the-Loop interrupts
    while True:
        state_snapshot = app.get_state(config)
        tasks = state_snapshot.tasks
        active_interrupts = [i for t in tasks for i in t.interrupts] if tasks else []

        if not active_interrupts and not state_snapshot.next:
            # Graph finished
            final_state = state_snapshot.values
            if final_state.get("final_message"):
                print("\n" + final_state["final_message"])
            print(f"\n[Workflow Result: {final_state.get('status', 'DONE')}]")
            break

        # Check for interrupt
        if active_interrupts:
            interrupt_data = active_interrupts[0].value
            int_type = interrupt_data.get("type") if isinstance(interrupt_data, dict) else None

            if int_type in ["reorder_irrelevant", "reorder_db_not_found"]:
                prompt_msg = interrupt_data.get("message", "Please enter new input:")
                print(f"\n[SYSTEM ALERT]: {prompt_msg}")
                resumed_input = input("> ")
                app.invoke(Command(resume=resumed_input), config=config)
            
            elif int_type == "cook_admin_review":
                prompt_msg = interrupt_data.get("prompt", "Admin/Chef confirmation (approved/failed):")
                print(f"\n[ADMIN/CHEF INTERRUPT]: {prompt_msg}")
                admin_choice = timed_admin_input(prompt_msg, timeout=8.0)
                app.invoke(Command(resume=admin_choice), config=config)
            
            else:
                generic_resp = input(f"\nInput required: {interrupt_data}\n> ")
                app.invoke(Command(resume=generic_resp), config=config)
        else:
            # If not finished and no interrupt, step forward
            app.invoke(None, config=config)

if __name__ == "__main__":
    run_interactive()
