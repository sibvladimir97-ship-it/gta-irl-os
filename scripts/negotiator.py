"""
GTA IRL OS — Negotiator
Воронка продаж. Human-in-the-loop на каждом шаге.
Никаких автоотправок без подтверждения.
"""

import json
import uuid
import os
import requests
from typing import Optional
from datetime import datetime

from deal_pipeline import STAGES, STAGE_LABELS, init_pipeline, move_deal, next_action, stage_label

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEALS_DIR  = os.path.join(ROOT, "data", "deals", "active")
CLOSED_DIR = os.path.join(ROOT, "data", "deals", "closed")
os.makedirs(DEALS_DIR, exist_ok=True)
os.makedirs(CLOSED_DIR, exist_ok=True)

GROQ_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def ensure_deal_fields(deal: dict) -> dict:
    """Backfill business fields for old and new deals."""
    init_pipeline(deal)
    deal.setdefault("messages", [])
    deal.setdefault("notes", [])
    deal.setdefault("brief", {})
    deal.setdefault("proposal", None)
    deal.setdefault("payments", [])
    deal.setdefault("payment", {
        "prepayment_status": "pending",
        "prepayment_amount": None,
        "prepayment_received_at": None,
        "final_payment_status": "pending",
        "final_payment_amount": None,
        "final_payment_received_at": None,
    })
    deal.setdefault("execution", {
        "mode": None,
        "status": "not_started",
        "planned_at": None,
        "started_at": None,
        "delivered_at": None,
    })
    return deal

# ── CRUD сделок ───────────────────────────────────────────────────────────────

def create_deal(offer: dict) -> dict:
    deal_id = str(uuid.uuid4())[:8]
    deal = {
        "deal_id":    deal_id,
        "offer_id":   offer["offer_id"],
        "created_at": datetime.utcnow().isoformat(),
        "stage":      "NEW_LEAD",
        "contact": {
            "name":        offer["display"]["sender_name"],
            "username":    offer["raw"].get("sender_username"),
            "user_id":     offer["raw"].get("sender_id"),
            "contact_url": offer["raw"].get("contact_url"),
        },
        "source": {
            "chat":    offer["display"]["chat_name"],
            "msg_url": offer["raw"].get("msg_url"),
        },
        "offer_text": offer["raw_text"],
        "messages":   [],   # история сообщений
        "notes":      [],   # заметки
        "brief":      {},
        "proposal":   None,
        "payments":   [],
        "payment": {
            "prepayment_status": "pending",
            "prepayment_amount": None,
            "prepayment_received_at": None,
            "final_payment_status": "pending",
            "final_payment_amount": None,
            "final_payment_received_at": None,
        },
        "execution": {
            "mode": None,
            "status": "not_started",
            "planned_at": None,
            "started_at": None,
            "delivered_at": None,
        },
        "budget":     None,
        "deadline":   None,
        "result":     None,
    }
    ensure_deal_fields(deal)
    save_deal(deal)
    return deal


def save_deal(deal: dict):
    ensure_deal_fields(deal)
    path = os.path.join(DEALS_DIR, f"{deal['deal_id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(deal, f, ensure_ascii=False, indent=2)


def get_deal(deal_id: str) -> Optional[dict]:
    path = os.path.join(DEALS_DIR, f"{deal_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        deal = json.load(f)
    return ensure_deal_fields(deal)


def update_stage(deal: dict, stage: str) -> dict:
    move_deal(deal, stage, reason="manual_update")
    save_deal(deal)
    return deal


def add_message(deal: dict, direction: str, text: str) -> dict:
    """direction: 'outgoing' | 'incoming'"""
    deal["messages"].append({
        "direction": direction,
        "text":      text,
        "timestamp": datetime.utcnow().isoformat(),
    })
    save_deal(deal)
    return deal


def list_deals(stage: Optional[str] = None) -> list:
    deals = []
    for fname in os.listdir(DEALS_DIR):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(DEALS_DIR, fname), encoding="utf-8") as f:
            deal = ensure_deal_fields(json.load(f))
        if stage is None or deal.get("stage") == stage:
            deals.append(deal)
    return sorted(deals, key=lambda x: x["created_at"], reverse=True)


# ── AI черновик ───────────────────────────────────────────────────────────────

def draft_first_message(deal: dict) -> str:
    """Генерирует черновик первого отклика. Не отправляет."""
    offer_text = deal["offer_text"][:600]
    contact_name = deal["contact"]["name"]

    if not GROQ_KEY:
        return f"Добрый день, {contact_name}! Увидел ваш запрос. Готов помочь. Вакансия ещё актуальна?"

    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [
                      {"role": "system", "content": """Ты пишешь первый отклик на фриланс-заявку от имени Владимира.
Владимир умеет: Python, Telegram-боты, AI-агенты, автоматизация, монтаж видео.
Правила:
- Коротко (2-3 предложения максимум)
- Вежливо, по-русски
- Уточни актуальность заявки
- Не обещай конкретных сроков и цен — это на следующем шаге
- Без лишних слов и эмодзи"""},
                      {"role": "user", "content": f"Заявка:\n{offer_text}\n\nНапиши первый отклик."}
                  ],
                  "max_tokens": 200},
            timeout=15)
        if r.status_code == 429:
            return f"Добрый день! Увидел вашу заявку, готов взяться. Вакансия ещё актуальна?"
        return r.json()["choices"][0]["message"]["content"]
    except:
        return f"Добрый день! Увидел вашу заявку, готов взяться. Вакансия ещё актуальна?"


def draft_offer(deal: dict, budget: str, deadline: str, scope: str) -> str:
    """Генерирует КП. Не отправляет."""
    if not GROQ_KEY:
        return (
            f"Готов взяться за задачу.\n"
            f"Что сделаю: {scope[:300]}\n"
            f"Стоимость: {budget}\n"
            f"Срок выполнения: {deadline}\n"
            f"Работаю по предоплате 50%. Готов начать после подтверждения."
        )

    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [
                      {"role": "system", "content": "Ты пишешь коммерческое предложение для фриланс-заказа. Кратко, конкретно, по-русски. Условия: работа по предоплате 50%."},
                      {"role": "user", "content": f"Заказ: {deal['offer_text'][:400]}\nСтоимость: {budget}\nСрок: {deadline}\nЧто делаю: {scope}\n\nНапиши КП."}
                  ],
                  "max_tokens": 300},
            timeout=15)
        if r.status_code == 429:
            return f"Стоимость работы: {budget}\nСрок выполнения: {deadline}\nРаботаю по предоплате 50%. Готов начать после подтверждения."
        return r.json()["choices"][0]["message"]["content"]
    except:
        return f"Стоимость работы: {budget}\nСрок выполнения: {deadline}\nРаботаю по предоплате 50%."


def proposal_scope(deal: dict) -> str:
    """Return the best available scope for proposal drafting."""
    brief = deal.get("brief") or {}
    if brief.get("scope"):
        return brief["scope"]
    if deal.get("tz"):
        return deal["tz"]

    incoming = [
        m.get("text", "")
        for m in deal.get("messages", [])
        if m.get("direction") == "incoming" and m.get("text")
    ]
    if incoming:
        return incoming[-1][:800]

    return deal.get("offer_text", "")[:800]


def prepare_proposal(deal: dict) -> dict:
    """Generate and save a commercial proposal draft. Does not send it."""
    budget = deal.get("budget") or "уточнить"
    deadline = deal.get("deadline") or "обсудим"
    scope = proposal_scope(deal)
    text = draft_offer(deal, budget, deadline, scope)

    deal["proposal"] = {
        "text": text,
        "budget": budget,
        "deadline": deadline,
        "scope": scope,
        "status": "draft",
        "created_at": datetime.utcnow().isoformat(),
    }
    deal["draft"] = text
    move_deal(deal, "PROPOSAL_DRAFTED", reason="proposal_prepared")
    save_deal(deal)
    return deal


def record_prepayment(deal: dict, amount=None) -> dict:
    """Record that prepayment was received and move deal forward."""
    ensure_deal_fields(deal)
    proposal = deal.get("proposal") or {}
    amount = amount or proposal.get("budget") or deal.get("budget") or "не указано"
    now = datetime.utcnow().isoformat()

    payment = deal["payment"]
    payment["prepayment_status"] = "received"
    payment["prepayment_amount"] = amount
    payment["prepayment_received_at"] = now
    deal["payments"].append({
        "type": "prepayment",
        "amount": amount,
        "received_at": now,
        "note": "marked_from_telegram",
    })
    move_deal(deal, "PREPAYMENT_RECEIVED", reason="prepayment_received")
    save_deal(deal)
    return deal


def plan_execution(deal: dict, mode="self") -> dict:
    """Mark execution planning after prepayment."""
    ensure_deal_fields(deal)
    execution = deal["execution"]
    execution["mode"] = mode
    execution["status"] = "planning"
    execution["planned_at"] = datetime.utcnow().isoformat()
    move_deal(deal, "EXECUTION_PLANNING", reason="execution_planning")
    save_deal(deal)
    return deal


def start_execution(deal: dict, mode=None) -> dict:
    """Mark work as started."""
    ensure_deal_fields(deal)
    execution = deal["execution"]
    if mode:
        execution["mode"] = mode
    execution["mode"] = execution.get("mode") or "self"
    execution["status"] = "in_progress"
    execution["started_at"] = datetime.utcnow().isoformat()
    move_deal(deal, "IN_PROGRESS", reason="execution_started")
    save_deal(deal)
    return deal


def mark_delivered(deal: dict) -> dict:
    """Mark delivery to client."""
    ensure_deal_fields(deal)
    execution = deal["execution"]
    execution["status"] = "delivered"
    execution["delivered_at"] = datetime.utcnow().isoformat()
    move_deal(deal, "DELIVERED", reason="delivered")
    save_deal(deal)
    return deal


def record_final_payment(deal: dict, amount=None) -> dict:
    """Record final payment and close the deal as won."""
    ensure_deal_fields(deal)
    proposal = deal.get("proposal") or {}
    amount = amount or proposal.get("budget") or deal.get("budget") or "не указано"
    now = datetime.utcnow().isoformat()

    payment = deal["payment"]
    payment["final_payment_status"] = "received"
    payment["final_payment_amount"] = amount
    payment["final_payment_received_at"] = now
    deal["payments"].append({
        "type": "final_payment",
        "amount": amount,
        "received_at": now,
        "note": "marked_from_telegram",
    })
    move_deal(deal, "CLOSED_WON", reason="final_payment_received")
    save_deal(deal)
    return deal


# ── Форматирование карточки сделки ────────────────────────────────────────────

def format_deal_card(deal: dict) -> str:
    ensure_deal_fields(deal)
    current_stage_label = stage_label(deal["stage"])
    contact = deal["contact"]
    name = contact.get("name", "?")
    username = contact.get("username")
    contact_display = f"@{username}" if username else f"ID:{contact.get('user_id', '?')}"

    lines = [
        f"📋 *Сделка {deal['deal_id']}*",
        f"Стадия: {current_stage_label}",
        f"Следующий шаг: {deal.get('next_action') or next_action(deal['stage'])}",
        f"Контакт: {contact_display} ({name})",
        f"Источник: {deal['source']['chat']}",
        f"",
        f"_{deal['offer_text'][:200]}..._",
    ]

    if deal.get("budget"):
        lines.append(f"💰 Бюджет: {deal['budget']}")
    if deal.get("deadline"):
        lines.append(f"⏰ Дедлайн: {deal['deadline']}")
    if deal.get("proposal"):
        proposal = deal["proposal"]
        lines.append(f"📋 КП: {proposal.get('status', 'draft')}")
        preview = (proposal.get("text") or "").replace("\n", " ")[:160]
        if preview:
            lines.append(f"_{preview}..._")
    payment = deal.get("payment") or {}
    if payment.get("prepayment_status") == "received":
        lines.append(f"💳 Предоплата: получена ({payment.get('prepayment_amount') or 'сумма не указана'})")
    elif deal["stage"] in ["PROPOSAL_SENT", "PREPAYMENT_WAITING"]:
        lines.append("💳 Предоплата: ожидается")
    if payment.get("final_payment_status") == "received":
        lines.append(f"🧾 Доплата: получена ({payment.get('final_payment_amount') or 'сумма не указана'})")
    elif deal["stage"] == "FINAL_PAYMENT_WAITING":
        lines.append("🧾 Доплата: ожидается")
    execution = deal.get("execution") or {}
    if execution.get("status") and execution.get("status") != "not_started":
        lines.append(f"⚙️ Исполнение: {execution.get('status')}")
    if deal["messages"]:
        last = deal["messages"][-1]
        arrow = "→" if last["direction"] == "outgoing" else "←"
        lines.append(f"\nПоследнее: {arrow} {last['text'][:100]}")

    return "\n".join(lines)
