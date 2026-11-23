import os
import json
import re
from typing import Tuple, Dict, Any, List, Optional
from dotenv import load_dotenv

# Load env variables from restaurantAgent/.env or workspace .env
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

def get_api_status() -> Dict[str, Any]:
    """Check availability of Gemini and Groq API keys."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")

    has_gemini = bool(gemini_key and gemini_key.strip() and not gemini_key.startswith("your_"))
    has_groq = bool(groq_key and groq_key.strip() and not groq_key.startswith("your_"))

    has_any = has_gemini or has_groq
    preferred = "gemini" if has_gemini else ("groq" if has_groq else None)

    return {
        "has_any": has_any,
        "has_gemini": has_gemini,
        "has_groq": has_groq,
        "preferred": preferred,
        "gemini_key": gemini_key,
        "groq_key": groq_key
    }

def call_gemini(prompt: str, system_prompt: Optional[str] = None) -> str:
    """Call Gemini LLM via langchain_google_genai."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise ValueError("GEMINI_API_KEY not found.")
    
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
        google_api_key=gemini_key,
        temperature=0.1,
        request_timeout=2.0
    )
    messages = []
    if system_prompt:
        messages.append(("system", system_prompt))
    messages.append(("human", prompt))
    response = llm.invoke(messages)
    return response.content

def call_groq(prompt: str, system_prompt: Optional[str] = None) -> str:
    """Call Groq LLM via official groq package."""
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        raise ValueError("GROQ_API_KEY not found.")
    
    from groq import Groq
    client = Groq(api_key=groq_key, timeout=1.0, max_retries=0)
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.1
    )
    return response.choices[0].message.content

def call_llm_with_fallback(prompt: str, system_prompt: Optional[str] = None) -> Tuple[str, str]:
    """
    Attempts to call primary LLM; if it fails or key missing, falls back to the secondary LLM.
    Returns: (response_text, provider_used)
    """
    status = get_api_status()
    if not status["has_any"]:
        raise RuntimeError("No LLM API keys configured.")

    errors = []
    # If Gemini is configured, try it first
    if status["has_gemini"]:
        try:
            return call_gemini(prompt, system_prompt), "gemini"
        except Exception as e:
            errors.append(f"Gemini failed: {e}")

    # Fallback to Groq
    if status["has_groq"]:
        try:
            return call_groq(prompt, system_prompt), "groq"
        except Exception as e:
            errors.append(f"Groq failed: {e}")

    # If both failed or network blocked, raise with detailed error
    raise RuntimeError(f"All LLM providers failed. Details: {'; '.join(errors)}")

# Robust regex/rule-based heuristics used as fallback or sanity check
COMMON_FOOD_KEYWORDS = {
    "burger", "burgers", "pizza", "pizzas", "pasta", "fries", "bread",
    "coke", "coca", "tea", "brownie", "food", "order", "drink", "drinks", "combo",
    "meal", "cheese", "sandwich", "garlic", "beverage", "eat", "hungry", "dish",
    "lobster", "caviar", "salad", "sushi", "soup", "steak", "chicken", "beef",
    "rice", "noodle", "noodles", "dessert", "coffee", "grilled", "curry", "tacos",
    "fruit", "juice", "wings", "plate", "pie", "cake", "shake"
}

ORDER_INTENT_KEYWORDS = {
    "want", "order", "get", "have", "bring", "give", "like", "need", "take", "serve", "buy"
}

def is_food_related_heuristic(text: str) -> bool:
    text_lower = text.lower()
    words = set(re.findall(r"\b\w+\b", text_lower))
    # If any food keyword is present, it's food related
    if any(w in COMMON_FOOD_KEYWORDS for w in words):
        return True
    # If order intent word is paired with common words
    if any(w in ORDER_INTENT_KEYWORDS for w in words) and ("food" in text_lower or "drink" in text_lower or "menu" in text_lower):
        return True
    return False

def parse_items_heuristic(text: str, menu_items: List[Dict]) -> List[Dict]:
    """Fallback item parser in case of network restriction or offline execution."""
    text_lower = text.lower()
    extracted = []
    
    # 1. First check matching against known menu items
    matched_menu_names = set()
    for m in menu_items:
        m_name = m["name"].lower()
        if m_name in text_lower or any(word in text_lower for word in m_name.split() if len(word) > 3):
            pattern = rf"(\d+)\s*(?:x\s*)?{re.escape(m_name)}"
            match = re.search(pattern, text_lower)
            qty = 1
            if match:
                qty = int(match.group(1))
            else:
                word_numbers = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
                for w, num in word_numbers.items():
                    if f"{w} {m_name}" in text_lower or f"{w} {m_name.split()[0]}" in text_lower:
                        qty = num
                        break
            extracted.append({"name": m["name"], "quantity": qty})
            matched_menu_names.add(m_name)
    
    # 2. If no menu items matched but the text is food-related, extract noun phrases or off-menu item names
    if not extracted and is_food_related_heuristic(text):
        # Look for patterns like "<number> <words>" or "order <words>"
        clean = re.sub(r"\b(i\s+want|can\s+i\s+get|please\s+give\s+me|i\s+would\s+like|order|and)\b", ",", text_lower)
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        for p in parts:
            num_match = re.match(r"^(\d+)\s+(.+)$", p)
            if num_match:
                extracted.append({"name": num_match.group(2).title(), "quantity": int(num_match.group(1))})
            elif len(p) > 2 and any(w in COMMON_FOOD_KEYWORDS for w in p.split()):
                extracted.append({"name": p.title(), "quantity": 1})

    return extracted

def analyze_user_order(user_input: str, menu_items: List[Dict]) -> Dict[str, Any]:
    """
    Evaluates order relevance and extracts structured items.
    Returns: {
        "is_relevant": bool,
        "items": List[Dict],  # [{"name": "...", "quantity": int}]
        "provider": str,
        "reason": str
    }
    """
    menu_names = [m["name"] for m in menu_items]
    prompt = f"""You are a helpful restaurant ordering assistant.
Given the customer message: "{user_input}"
Available restaurant menu: {json.dumps(menu_names)}

1. Determine if the customer's message is relevant to placing or inquiring about a restaurant food/drink order.
2. If relevant, extract the ordered items and quantities. Match items to the menu as closely as possible.
3. Respond ONLY with valid JSON in this exact schema:
{{
    "is_relevant": true/false,
    "reason": "short explanation",
    "items": [
        {{"name": "Item Name", "quantity": 1}}
    ]
}}
"""
    try:
        raw_output, provider = call_llm_with_fallback(prompt, "You are a JSON-only restaurant order parser.")
        # Clean json output
        clean_json = re.sub(r"^```json\s*", "", raw_output.strip())
        clean_json = re.sub(r"\s*```$", "", clean_json)
        data = json.loads(clean_json)
        data["provider"] = provider
        return data
    except Exception as e:
        # Graceful fallback heuristic if network/API is unavailable
        is_rel = is_food_related_heuristic(user_input)
        items = parse_items_heuristic(user_input, menu_items) if is_rel else []
        return {
            "is_relevant": is_rel,
            "reason": f"Analyzed (fallback heuristic due to: {str(e)[:60]}...)",
            "items": items,
            "provider": "heuristic_fallback"
        }
