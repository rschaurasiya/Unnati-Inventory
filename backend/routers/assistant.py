"""
Kirana AI Copilot API Router
Provides lightweight, non-intrusive AI Assistant chat with live SQLite store snapshot injection,
today's sales intelligence, Groq LLM processing, and a robust deterministic fallback responder.
"""

import os
import re
import logging
from datetime import date
from typing import Dict, Any, List, Optional
import httpx
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import get_db
from backend.config import settings
from backend.models import (
    Bill, BillItem, Customer, Product, ProductForecast,
    ShopkeeperUser, ShopProfile
)
from backend.schemas import AssistantChatRequest, AssistantChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Kirana AI Copilot"])

# Tab mapping helper
TAB_MAP = {
    "dashboard": ("dashboard", "Go to Shop Dashboard →"),
    "billing": ("billing", "Go to Voice Billing POS →"),
    "inventory": ("inventory", "Go to Inventory Catalog →"),
    "customers": ("udhaar", "Go to Udhaar & Customers →"),
    "udhaar": ("udhaar", "Go to Udhaar & Customers →"),
    "sales": ("analytics", "Go to Sales History & Import →"),
    "analytics": ("analytics", "Go to Sales History & Import →"),
    "forecast": ("forecasting", "Go to Demand Forecasting →"),
    "forecasting": ("forecasting", "Go to Demand Forecasting →"),
    "profile": ("profile", "Go to Profile & Settings →")
}


def get_live_store_snapshot(db: Session) -> Dict[str, Any]:
    """
    Queries a lightweight, live operational snapshot from the SQLite database
    including all-time revenue, today's sales figures, and latest recorded sales date.
    All date and numeric queries are safely wrapped to prevent unhandled 500 errors.
    """
    today_str = date.today().isoformat()
    today_revenue = 0.0
    today_bills = 0
    today_units = 0.0
    today_cash = 0.0
    today_upi = 0.0
    today_udhaar = 0.0

    latest_date_str = None
    latest_revenue = 0.0
    latest_bills = 0
    latest_units = 0.0
    latest_cash = 0.0
    latest_upi = 0.0
    latest_udhaar = 0.0

    total_revenue = 0.0
    completed_bills = 0

    try:
        # 1. Total All-Time Revenue & Completed Bills
        rev_row = db.query(
            func.coalesce(func.sum(Bill.total_amount), 0.0),
            func.count(Bill.id)
        ).filter(Bill.status == "COMPLETED").first()
        if rev_row:
            total_revenue = float(rev_row[0] or 0.0)
            completed_bills = int(rev_row[1] or 0)
    except Exception as e:
        logger.warning(f"Error querying all-time revenue: {e}")

    try:
        # 2. Today's Completed Bills & Sales Revenue
        today_rev_row = db.query(
            func.coalesce(func.sum(Bill.total_amount), 0.0),
            func.count(Bill.id)
        ).filter(Bill.status == "COMPLETED", func.date(Bill.created_at) == today_str).first()
        if today_rev_row:
            today_revenue = float(today_rev_row[0] or 0.0)
            today_bills = int(today_rev_row[1] or 0)

        # Today's units sold
        today_units_val = db.query(
            func.coalesce(func.sum(BillItem.quantity), 0.0)
        ).join(Bill, BillItem.bill_id == Bill.id).filter(
            Bill.status == "COMPLETED",
            func.date(Bill.created_at) == today_str
        ).scalar()
        today_units = float(today_units_val or 0.0)

        # Today's payment split
        today_splits = db.query(
            Bill.payment_mode,
            func.sum(Bill.total_amount)
        ).filter(
            Bill.status == "COMPLETED",
            func.date(Bill.created_at) == today_str
        ).group_by(Bill.payment_mode).all()

        for pm, amt in today_splits:
            pm_upper = (pm or "").upper()
            if pm_upper == "CASH":
                today_cash = float(amt or 0.0)
            elif pm_upper == "UPI":
                today_upi = float(amt or 0.0)
            elif pm_upper == "UDHAAR":
                today_udhaar = float(amt or 0.0)
    except Exception as e:
        logger.warning(f"Error querying today's sales: {e}")

    try:
        # 3. Latest Recorded Date Sales in Database
        latest_bill = db.query(
            func.date(Bill.created_at)
        ).filter(Bill.status == "COMPLETED").order_by(Bill.created_at.desc()).first()

        if latest_bill and latest_bill[0]:
            latest_date_str = str(latest_bill[0])

            if latest_date_str != today_str:
                lat_rev_row = db.query(
                    func.coalesce(func.sum(Bill.total_amount), 0.0),
                    func.count(Bill.id)
                ).filter(Bill.status == "COMPLETED", func.date(Bill.created_at) == latest_date_str).first()
                if lat_rev_row:
                    latest_revenue = float(lat_rev_row[0] or 0.0)
                    latest_bills = int(lat_rev_row[1] or 0)

                lat_units_val = db.query(
                    func.coalesce(func.sum(BillItem.quantity), 0.0)
                ).join(Bill, BillItem.bill_id == Bill.id).filter(
                    Bill.status == "COMPLETED",
                    func.date(Bill.created_at) == latest_date_str
                ).scalar()
                latest_units = float(lat_units_val or 0.0)

                lat_splits = db.query(
                    Bill.payment_mode,
                    func.sum(Bill.total_amount)
                ).filter(
                    Bill.status == "COMPLETED",
                    func.date(Bill.created_at) == latest_date_str
                ).group_by(Bill.payment_mode).all()

                for pm, amt in lat_splits:
                    pm_upper = (pm or "").upper()
                    if pm_upper == "CASH":
                        latest_cash = float(amt or 0.0)
                    elif pm_upper == "UPI":
                        latest_upi = float(amt or 0.0)
                    elif pm_upper == "UDHAAR":
                        latest_udhaar = float(amt or 0.0)
            else:
                latest_revenue = today_revenue
                latest_bills = today_bills
                latest_units = today_units
                latest_cash = today_cash
                latest_upi = today_upi
                latest_udhaar = today_udhaar
    except Exception as e:
        logger.warning(f"Error querying latest sales date: {e}")

    # 4. Udhaar Balances & Top Customers
    total_udhaar = 0.0
    top_debtors = []
    try:
        total_udhaar = float(
            db.query(func.coalesce(func.sum(Customer.current_udhaar_balance), 0.0))
            .filter(Customer.is_active == True).scalar() or 0.0
        )
        top_debtors_q = (
            db.query(Customer)
            .filter(Customer.is_active == True, Customer.current_udhaar_balance > 0)
            .order_by(Customer.current_udhaar_balance.desc())
            .limit(3)
            .all()
        )
        top_debtors = [{"name": c.full_name, "balance": round(float(c.current_udhaar_balance), 2)} for c in top_debtors_q]
    except Exception as e:
        logger.warning(f"Error querying udhaar snapshot: {e}")

    # 5. Low Stock / Reorder Items & Most Urgent Products
    low_stock_count = 0
    urgent_products = []
    try:
        low_stock_direct = db.query(Product).filter(
            Product.is_active == True,
            Product.stock_quantity <= Product.min_stock_threshold
        ).all()
        low_stock_count = len(low_stock_direct)

        urgent_items_q = (
            db.query(Product, ProductForecast)
            .join(ProductForecast, Product.id == ProductForecast.product_id)
            .filter(
                Product.is_active == True,
                ProductForecast.risk_level.in_(["LOW_STOCK", "IMMEDIATE_ATTENTION", "POTENTIAL_STOCKOUT"])
            )
            .order_by(ProductForecast.days_inventory_remaining.asc().nullslast())
            .limit(5)
            .all()
        )

        if urgent_items_q:
            for p, pf in urgent_items_q:
                urgent_products.append({
                    "name": p.name,
                    "stock": p.stock_quantity,
                    "unit": p.unit,
                    "days_remaining": round(pf.days_inventory_remaining, 1) if pf.days_inventory_remaining is not None else None,
                    "reorder_qty": round(pf.suggested_reorder_qty, 1) if pf.suggested_reorder_qty else None
                })
        else:
            for p in low_stock_direct[:5]:
                urgent_products.append({
                    "name": p.name,
                    "stock": p.stock_quantity,
                    "unit": p.unit,
                    "days_remaining": None,
                    "reorder_qty": max(0.0, round(p.min_stock_threshold - p.stock_quantity, 1))
                })
    except Exception as e:
        logger.warning(f"Error querying low stock snapshot: {e}")

    # 6. Store Branding & Shopkeeper Profile
    owner_name = "Shopkeeper"
    shop_name = settings.SHOP_NAME
    try:
        owner_user = db.query(ShopkeeperUser).filter(ShopkeeperUser.is_active == True).first()
        if owner_user:
            owner_name = owner_user.full_name or "Shopkeeper"

        profile_row = db.query(ShopProfile).first()
        if profile_row and profile_row.shop_name:
            shop_name = profile_row.shop_name
    except Exception as e:
        logger.warning(f"Error querying shop profile: {e}")

    return {
        "shop_name": shop_name,
        "owner_name": owner_name,
        "total_revenue": total_revenue,
        "completed_bills": completed_bills,
        "today_date": today_str,
        "today_revenue": today_revenue,
        "today_bills": today_bills,
        "today_units": today_units,
        "today_cash": today_cash,
        "today_upi": today_upi,
        "today_udhaar": today_udhaar,
        "latest_date": latest_date_str or today_str,
        "latest_revenue": latest_revenue,
        "latest_bills": latest_bills,
        "latest_units": latest_units,
        "latest_cash": latest_cash,
        "latest_upi": latest_upi,
        "latest_udhaar": latest_udhaar,
        "total_udhaar": total_udhaar,
        "top_debtors": top_debtors,
        "low_stock_count": low_stock_count,
        "urgent_products": urgent_products
    }


def deterministic_fallback_reply(
    message: str,
    snapshot: Dict[str, Any],
    input_source: str = "text"
) -> AssistantChatResponse:
    """
    Intelligent, rule-based fallback responder if Groq LLM API is missing,
    offline, or rate-limited. Never crashes during demos!
    """
    msg_lower = message.lower().strip()

    # Format helpers
    shop_name = snapshot["shop_name"]
    rev = f"₹{snapshot['total_revenue']:,.2f}"
    bills = snapshot["completed_bills"]
    udhaar = f"₹{snapshot['total_udhaar']:,.2f}"

    today_rev = snapshot.get("today_revenue", 0.0)
    today_bills = snapshot.get("today_bills", 0)
    today_units = snapshot.get("today_units", 0.0)
    today_units_fmt = int(today_units) if today_units.is_integer() else today_units

    debtors_list = snapshot.get("top_debtors", [])
    if debtors_list:
        debtors_str = ", ".join([f"{d['name']} (₹{d['balance']:,.2f})" for d in debtors_list])
    else:
        debtors_str = "No pending Udhaar accounts"

    urgent_list = snapshot.get("urgent_products", [])
    if urgent_list:
        urgent_str = ", ".join([f"{u['name']} ({u['stock']} {u['unit']} left)" for u in urgent_list[:3]])
    else:
        urgent_str = "All items currently have healthy stock levels"

    # 1. Sales History / Import / CSV / Excel / Audit (Specific records/import keywords)
    if any(k in msg_lower for k in ["import", "csv", "excel", "history", "audit", "purana"]):
        reply = (
            f"Sales History tab mein aap date-wise bills audit kar sakte hain aur historical CSV/Excel data import kar sakte hain "
            f"with automatic duplicate detection and sales aggregation."
        )
        return AssistantChatResponse(
            reply=reply,
            action_tab="analytics",
            action_label="Go to Sales History & Import →",
            source="fallback",
            input_source=input_source
        )

    # 2. Voice Billing / POS / Bill / Aawaz / Microphone
    if any(k in msg_lower for k in ["pos", "billing", "voice bill", "aawaz", "mic", "checkout", "how to use pos"]):
        reply = (
            f"Voice Billing POS use karne ke liye mic button dabayein aur boliye jaise '2 kilo chini aur ek bread'. "
            f"Items turant cart mein add honge, aur aap Cash, UPI ya Udhaar se checkout kar sakte hain."
        )
        return AssistantChatResponse(
            reply=reply,
            action_tab="billing",
            action_label="Go to Voice Billing POS →",
            source="fallback",
            input_source=input_source
        )

    # 3. Low Stock / Reorder / Maal / Khatam / Shortage
    if any(k in msg_lower for k in ["low stock", "reorder", "khatam", "maal", "kam", "shortage"]):
        reply = (
            f"Inventory review shows {len(urgent_list)} items needing attention, including {urgent_str}. "
            f"Aap Demand Forecasting tab mein jakar 1-click reorder se stock turant replenish kar sakte hain."
        )
        return AssistantChatResponse(
            reply=reply,
            action_tab="forecasting",
            action_label="Go to Demand Forecasting →",
            source="fallback",
            input_source=input_source
        )

    # 4. Udhaar / Khata / Customer / Credit / Baaki
    if any(k in msg_lower for k in ["udhaar", "khata", "credit", "baaki", "balance", "settle"]):
        reply = (
            f"Total outstanding Udhaar balance {udhaar} hai across all registered customers. "
            f"Top balances: {debtors_str}. Settle karne ke liye Udhaar & Customers tab visit karein."
        )
        return AssistantChatResponse(
            reply=reply,
            action_tab="udhaar",
            action_label="Go to Udhaar & Customers →",
            source="fallback",
            input_source=input_source
        )

    # 5. Profile / Settings / Shop Name / Password / Logo
    if any(k in msg_lower for k in ["profile", "setting", "dukaan", "logo", "password", "owner", "naam"]):
        reply = (
            f"Aap Profile & Settings tab se store branding '{shop_name}', shop logo, owner credentials, "
            f"aur audio feedback switch customize kar sakte hain."
        )
        return AssistantChatResponse(
            reply=reply,
            action_tab="profile",
            action_label="Go to Profile & Settings →",
            source="fallback",
            input_source=input_source
        )

    # 6. Today's Sales / Revenue / Summary / Earning / Collection / Aaj / Bikri / Kamai
    if any(k in msg_lower for k in ["today", "aaj", "sale", "sales", "revenue", "earning", "collection", "bikri", "kamai", "summary"]):
        if today_bills > 0:
            reply = (
                f"Today's sales total ₹{today_rev:,.2f} across {today_bills} completed bills ({today_units_fmt} units sold). "
                f"Overall store revenue is {rev} across {bills} total bills."
            )
        else:
            lat_date = snapshot.get("latest_date", "recent dates")
            lat_rev = snapshot.get("latest_revenue", 0.0)
            lat_bills = snapshot.get("latest_bills", 0)
            lat_units = snapshot.get("latest_units", 0.0)
            lat_units_fmt = int(lat_units) if lat_units.is_integer() else lat_units
            reply = (
                f"Today's sales have no new bills yet, but latest recorded sales on {lat_date} totaled ₹{lat_rev:,.2f} across {lat_bills} bills ({lat_units_fmt} units sold). "
                f"Overall store revenue is {rev}."
            )

        return AssistantChatResponse(
            reply=reply,
            action_tab="dashboard",
            action_label="Go to Shop Dashboard →",
            source="fallback",
            input_source=input_source
        )

    # 7. Greetings (Namaste, Hello, Hi, Hey)
    if any(k in msg_lower for k in ["namaste", "hello", "hi", "hey", "kem cho", "ram ram"]):
        reply = (
            f"Namaste! Main aapka Kirana AI Copilot hoon for {shop_name}. "
            f"Aap mujhse live sales numbers, low stock alerts, Udhaar balances, ya kisi bhi app feature ke baare mein pooch sakte hain."
        )
        return AssistantChatResponse(
            reply=reply,
            action_tab="dashboard",
            action_label="Go to Shop Dashboard →",
            source="fallback",
            input_source=input_source
        )

    # General default response
    reply = (
        f"{shop_name} is currently running smoothly with {bills} completed bills ({rev}) and {udhaar} in active Udhaar. "
        f"Aap mujhse stock, billing, ya customer khata ke baare mein kuch bhi pooch sakte hain!"
    )
    return AssistantChatResponse(
        reply=reply,
        action_tab="dashboard",
        action_label="Go to Shop Dashboard →",
        source="fallback",
        input_source=input_source
    )


async def call_groq_llm(
    message: str,
    history: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    api_key: str,
    input_source: str = "text"
) -> Optional[AssistantChatResponse]:
    """
    Calls Groq OpenAI-compatible chat completions API using fast, accurate models.
    """
    debtors_text = ", ".join([f"{d['name']} (₹{d['balance']:,.2f})" for d in snapshot.get("top_debtors", [])]) or "None"
    urgent_text = ", ".join([
        f"{u['name']} (Stock: {u['stock']} {u['unit']}, Reorder: {u.get('reorder_qty', 'Needed')})"
        for u in snapshot.get("urgent_products", [])
    ]) or "All items have healthy stock"

    system_prompt = f"""You are "Kirana AI Copilot", an intelligent and friendly assistant for an Indian retail grocery/kirana store.

LIVE STORE DATABASE SNAPSHOT:
- Store Name: {snapshot['shop_name']}
- Shop Owner: {snapshot['owner_name']}
- Today's Sales ({snapshot['today_date']}): ₹{snapshot['today_revenue']:,.2f} across {snapshot['today_bills']} bills ({snapshot['today_units']} units sold). Cash: ₹{snapshot['today_cash']:,.2f}, UPI: ₹{snapshot['today_upi']:,.2f}, Udhaar: ₹{snapshot['today_udhaar']:,.2f}.
- Latest Recorded Date ({snapshot.get('latest_date', 'N/A')}): ₹{snapshot.get('latest_revenue', 0.0):,.2f} across {snapshot.get('latest_bills', 0)} bills ({snapshot.get('latest_units', 0.0)} units sold).
- Total All-Time Store Revenue: ₹{snapshot['total_revenue']:,.2f} across {snapshot['completed_bills']} completed bills.
- Total Outstanding Udhaar: ₹{snapshot['total_udhaar']:,.2f}
- Top Udhaar Debtors: {debtors_text}
- Urgent Restock Items: {urgent_text}

INSTRUCTIONS:
1. Answer in maximum 2 to 3 short, clear sentences. Keep your response direct, helpful, and conversational.
2. If asked about "today's sales", "aaj ki sale", "today's revenue", "today's earning", or "today's summary":
   - If today has sales (> ₹0), state today's exact figures: "Today's sales total ₹[Amount] across [N] completed bills ([X] units sold). Overall store revenue is ₹[Total Revenue]."
   - If today's sales are ₹0 in demo mode, explain that today has 0 new bills and immediately share the latest recorded sales from {snapshot.get('latest_date', 'recent dates')}.
3. Respond in the EXACT same language or dialect the user uses:
   - If user asks in English -> reply in simple English.
   - If user asks in Hindi (Devanagari) -> reply in natural Hindi.
   - If user asks in Hinglish (e.g., 'aaj ki sale kitni hai', 'aaj ka summary batao', 'stock batao') -> reply in friendly, professional Hinglish.
4. Use the exact numbers from the LIVE STORE DATABASE SNAPSHOT above.
5. If relevant, suggest a navigation action by appending this EXACT line at the very end of your response:
   ACTION_TAB: <tab_name>
   Where <tab_name> is one of: dashboard, billing, inventory, customers, sales, forecast, profile.
   Do not add any other formatting to this tag.
"""

    messages = [{"role": "system", "content": system_prompt}]
    for turn in history[-4:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    models_to_try = [
        getattr(settings, "GROQ_MODEL", "qwen/qwen3.8-27b"),
        "qwen/qwen3.8-27b",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant"
    ]
    seen = set()
    models = []
    for m in models_to_try:
        if m and m not in seen:
            seen.add(m)
            models.append(m)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=8.0) as client:
        for model_name in models:
            try:
                payload = {
                    "model": model_name,
                    "messages": messages,
                    "temperature": 0.4,
                    "max_tokens": 200
                }
                res = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                if res.status_code == 200:
                    data = res.json()
                    raw_reply = data["choices"][0]["message"]["content"].strip()

                    action_tab = None
                    action_label = None

                    match = re.search(r"ACTION_TAB:\s*([a-zA-Z0-9_]+)", raw_reply, re.IGNORECASE)
                    if match:
                        tab_key = match.group(1).lower().strip()
                        raw_reply = re.sub(r"ACTION_TAB:\s*[a-zA-Z0-9_]+", "", raw_reply).strip()
                        if tab_key in TAB_MAP:
                            action_tab, action_label = TAB_MAP[tab_key]

                    return AssistantChatResponse(
                        reply=raw_reply,
                        action_tab=action_tab,
                        action_label=action_label,
                        source="groq",
                        input_source=input_source
                    )
                else:
                    logger.warning(f"Groq model {model_name} returned status {res.status_code}: {res.text[:150]}")
            except Exception as e:
                logger.warning(f"Groq call failed for {model_name}: {str(e)}")
                continue

    return None


@router.post(
    "/api/assistant/chat",
    response_model=AssistantChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Kirana AI Copilot Chat Endpoint",
    description="Interacts with Kirana AI Copilot. Queries live SQLite database snapshot (including today's sales and all-time revenue) and returns concise natural answers with action chips."
)
@router.post(
    "/api/v1/assistant/chat",
    response_model=AssistantChatResponse,
    include_in_schema=False
)
async def api_assistant_chat(payload: AssistantChatRequest, db: Session = Depends(get_db)):
    """
    POST /api/assistant/chat
    Answers shopkeeper questions using live store context and Groq LLM, with fallback guarantee.
    """
    input_source = getattr(payload, "input_source", "text") or "text"

    # 1. Fetch live SQLite snapshot (safely guarded)
    snapshot = get_live_store_snapshot(db)

    # 2. Check for GROQ_API_KEY
    groq_api_key = (
        getattr(settings, "GROQ_API_KEY", "") or
        os.getenv("GROQ_API_KEY", "")
    ).strip()

    if groq_api_key:
        try:
            llm_response = await call_groq_llm(
                message=payload.message,
                history=payload.history or [],
                snapshot=snapshot,
                api_key=groq_api_key,
                input_source=input_source
            )
            if llm_response:
                return llm_response
        except Exception as e:
            logger.error(f"Error invoking Groq LLM, falling back to deterministic responder: {e}")

    # 3. Fallback to smart deterministic responder
    return deterministic_fallback_reply(payload.message, snapshot, input_source)
