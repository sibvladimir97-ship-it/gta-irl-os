"""
GTA IRL OS — Negotiator
Воронка продаж. Human-in-the-loop на каждом шаге.
Никаких автоотправок без подтверждения.
"""

import json
import uuid
import os
import re
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
    deal.setdefault("followup", None)
    deal.setdefault("followups", [])
    deal.setdefault("events", [])
    deal.setdefault("loss", None)
    return deal


def add_event(deal: dict, event_type: str, title: str, data=None, save=False) -> dict:
    """Append an auditable event to deal timeline."""
    ensure_deal_fields(deal)
    deal["events"].append({
        "type": event_type,
        "title": title,
        "data": data or {},
        "timestamp": datetime.utcnow().isoformat(),
    })
    if save:
        save_deal(deal)
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
        "followup":   None,
        "followups":  [],
        "events":     [],
        "loss":       None,
        "budget":     None,
        "deadline":   None,
        "result":     None,
    }
    ensure_deal_fields(deal)
    add_event(deal, "deal_created", "Сделка создана", {
        "offer_id": deal["offer_id"],
        "stage": deal["stage"],
    })
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
    old_stage = deal.get("stage")
    move_deal(deal, stage, reason="manual_update")
    if old_stage != deal.get("stage"):
        add_event(deal, "stage_changed", f"Стадия: {stage_label(old_stage)} → {stage_label(deal['stage'])}", {
            "from": old_stage,
            "to": deal["stage"],
        })
    save_deal(deal)
    return deal


def add_message(deal: dict, direction: str, text: str) -> dict:
    """direction: 'outgoing' | 'incoming'"""
    now = datetime.utcnow().isoformat()
    deal["messages"].append({
        "direction": direction,
        "text":      text,
        "timestamp": now,
    })
    title = "Исходящее сообщение" if direction == "outgoing" else "Входящее сообщение"
    add_event(deal, "message", title, {
        "direction": direction,
        "text": text[:500],
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


def parse_money_amount(value):
    """Best-effort numeric extraction for dashboard totals."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace(" ", "")
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match else 0


def pipeline_summary(deals=None):
    """Return counts and lightweight cards grouped by deal stage."""
    deals = deals if deals is not None else list_deals()
    summary = {
        "total": len(deals),
        "by_stage": {},
        "active": [],
        "stuck": [],
    }
    for deal in deals:
        ensure_deal_fields(deal)
        stage = deal.get("stage", "UNKNOWN")
        summary["by_stage"][stage] = summary["by_stage"].get(stage, 0) + 1
        if stage not in ["CLOSED_WON", "CLOSED_LOST", "SCAM", "HIDDEN", "REJECTED"]:
            summary["active"].append(deal)
        if stage in ["WAITING_REPLY", "BRIEF_COLLECTING", "PREPAYMENT_WAITING", "FINAL_PAYMENT_WAITING"]:
            summary["stuck"].append(deal)
    return summary


def money_summary(deals=None):
    """Return simple money counters from proposal/payment state."""
    deals = deals if deals is not None else list_deals()
    totals = {
        "proposed": 0,
        "prepayment_received": 0,
        "final_received": 0,
        "won_deals": 0,
        "waiting_prepayment": 0,
        "waiting_final": 0,
    }
    for deal in deals:
        ensure_deal_fields(deal)
        proposal = deal.get("proposal") or {}
        payment = deal.get("payment") or {}
        totals["proposed"] += parse_money_amount(proposal.get("budget") or deal.get("budget"))
        totals["prepayment_received"] += parse_money_amount(payment.get("prepayment_amount"))
        totals["final_received"] += parse_money_amount(payment.get("final_payment_amount"))
        if deal.get("stage") == "CLOSED_WON":
            totals["won_deals"] += 1
        if deal.get("stage") == "PREPAYMENT_WAITING":
            totals["waiting_prepayment"] += 1
        if deal.get("stage") == "FINAL_PAYMENT_WAITING":
            totals["waiting_final"] += 1
    totals["received_total"] = totals["prepayment_received"] + totals["final_received"]
    return totals


LOSS_REASONS = {
    "client_ghosted": "клиент пропал",
    "not_fit": "не подходит по профилю",
    "no_budget": "нет бюджета",
    "too_risky": "слишком рискованно",
    "scam": "скам",
    "delegated": "делегировано",
    "manual": "закрыто вручную",
}


def close_deal(deal: dict, stage: str, reason_code="manual", note=None) -> dict:
    """Close or reject a deal with structured reason for analytics."""
    ensure_deal_fields(deal)
    reason = LOSS_REASONS.get(reason_code, reason_code)
    now = datetime.utcnow().isoformat()
    deal["loss"] = {
        "stage": stage,
        "reason_code": reason_code,
        "reason": reason,
        "note": note,
        "closed_at": now,
    }
    deal["result"] = "won" if stage == "CLOSED_WON" else "lost"
    move_deal(deal, stage, reason=f"closed:{reason_code}", allow_any=True)
    add_event(deal, "deal_closed", f"Сделка закрыта: {stage_label(stage)}", {
        "stage": stage,
        "reason_code": reason_code,
        "reason": reason,
        "note": note,
    })
    save_deal(deal)
    return deal


def loss_summary(deals=None):
    """Return analytics for lost/rejected/scam deals by reason."""
    deals = deals if deals is not None else list_deals()
    summary = {"total_lost": 0, "by_reason": {}, "by_stage": {}}
    for deal in deals:
        ensure_deal_fields(deal)
        if deal.get("stage") not in ["CLOSED_LOST", "REJECTED", "SCAM", "HIDDEN"]:
            continue
        summary["total_lost"] += 1
        loss = deal.get("loss") or {}
        reason = loss.get("reason") or "причина не указана"
        stage = deal.get("stage")
        summary["by_reason"][reason] = summary["by_reason"].get(reason, 0) + 1
        summary["by_stage"][stage] = summary["by_stage"].get(stage, 0) + 1
    return summary


def needs_followup(deal: dict) -> bool:
    """Return true when a deal is waiting on the client or money."""
    ensure_deal_fields(deal)
    return deal.get("stage") in [
        "WAITING_REPLY",
        "BRIEF_COLLECTING",
        "PREPAYMENT_WAITING",
        "FINAL_PAYMENT_WAITING",
        "CLIENT_GHOSTED",
    ]


def list_followup_candidates(deals=None):
    """List active deals that can benefit from a follow-up draft."""
    deals = deals if deals is not None else list_deals()
    return [deal for deal in deals if needs_followup(deal)]


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


def local_followup_text(deal: dict) -> str:
    """Deterministic local follow-up draft by stage."""
    ensure_deal_fields(deal)
    stage = deal.get("stage")
    contact_name = deal.get("contact", {}).get("name") or ""
    hello = f"{contact_name}, добрый день!" if contact_name else "Добрый день!"

    if stage == "WAITING_REPLY":
        return f"{hello} Подскажите, пожалуйста, задача ещё актуальна? Готов обсудить детали и следующий шаг."
    if stage == "BRIEF_COLLECTING":
        return f"{hello} Чтобы точно оценить задачу, уточните, пожалуйста, объём работы, бюджет и желаемый срок."
    if stage == "PREPAYMENT_WAITING":
        return f"{hello} Подскажите, пожалуйста, когда сможете внести предоплату, чтобы я зафиксировал слот и начал работу?"
    if stage == "FINAL_PAYMENT_WAITING":
        return f"{hello} Работа со своей стороны сдана. Подскажите, пожалуйста, когда удобно закрыть финальную оплату?"
    if stage == "CLIENT_GHOSTED":
        return f"{hello} Возвращаюсь по задаче. Если она ещё актуальна — напишите, пожалуйста, и продолжим с текущего места."
    return f"{hello} Подскажите, пожалуйста, какой следующий шаг по задаче?"


def draft_followup(deal: dict) -> str:
    """Generate a follow-up draft. Does not send it."""
    ensure_deal_fields(deal)
    fallback = local_followup_text(deal)

    if not GROQ_KEY:
        return fallback

    messages_history = "\n".join(
        f"{'Я' if m.get('direction') == 'outgoing' else 'Клиент'}: {m.get('text', '')}"
        for m in deal.get("messages", [])[-8:]
    )
    try:
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": """Ты пишешь короткий follow-up клиенту от имени Владимира.
Правила:
- русский язык
- 1-2 предложения
- вежливо и спокойно
- без давления
- не обещай лишнего
- цель: вернуть сделку к следующему шагу"""},
                    {"role": "user", "content": (
                        f"Стадия сделки: {deal.get('stage')}\n"
                        f"Задача: {deal.get('offer_text', '')[:500]}\n"
                        f"История:\n{messages_history}\n\n"
                        "Напиши follow-up."
                    )},
                ],
                "max_tokens": 120,
            },
            timeout=12,
        )
        if r.status_code == 429:
            return fallback
        return r.json()["choices"][0]["message"]["content"]
    except:
        return fallback


def prepare_followup(deal: dict) -> dict:
    """Save a follow-up draft into the deal. Does not send it."""
    ensure_deal_fields(deal)
    text = draft_followup(deal)
    now = datetime.utcnow().isoformat()
    deal["followup"] = {
        "text": text,
        "stage": deal.get("stage"),
        "status": "draft",
        "created_at": now,
    }
    deal["followups"].append(deal["followup"])
    deal["draft"] = text
    add_event(deal, "followup_drafted", "Follow-up подготовлен", {
        "stage": deal.get("stage"),
        "text": text[:500],
    })
    save_deal(deal)
    return deal


def mark_followup_sent(deal: dict, text: str) -> dict:
    """Mark last follow-up as sent and log outgoing message."""
    ensure_deal_fields(deal)
    now = datetime.utcnow().isoformat()
    followup = deal.get("followup") or {
        "text": text,
        "stage": deal.get("stage"),
        "created_at": now,
    }
    followup["status"] = "sent"
    followup["sent_at"] = now
    deal["followup"] = followup
    if not deal.get("followups"):
        deal["followups"] = [followup]
    else:
        deal["followups"][-1] = followup
    deal["messages"].append({
        "direction": "outgoing",
        "text": text,
        "timestamp": now,
        "kind": "followup",
    })
    add_event(deal, "followup_sent", "Follow-up отправлен", {
        "stage": deal.get("stage"),
        "text": text[:500],
    })
    save_deal(deal)
    return deal


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
    add_event(deal, "proposal_drafted", "КП подготовлено", {
        "budget": budget,
        "deadline": deadline,
        "text": text[:500],
    })
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
    add_event(deal, "payment_received", "Предоплата получена", {
        "type": "prepayment",
        "amount": amount,
    })
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
    add_event(deal, "execution_planned", "План исполнения создан", {
        "mode": mode,
    })
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
    add_event(deal, "execution_started", "Работа начата", {
        "mode": execution["mode"],
    })
    save_deal(deal)
    return deal


def mark_delivered(deal: dict) -> dict:
    """Mark delivery to client."""
    ensure_deal_fields(deal)
    execution = deal["execution"]
    execution["status"] = "delivered"
    execution["delivered_at"] = datetime.utcnow().isoformat()
    move_deal(deal, "DELIVERED", reason="delivered")
    add_event(deal, "delivered", "Работа сдана клиенту")
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
    add_event(deal, "payment_received", "Финальная оплата получена", {
        "type": "final_payment",
        "amount": amount,
    })
    add_event(deal, "deal_closed", "Сделка закрыта успешно", {
        "result": "won",
    })
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
    if deal.get("followup"):
        followup = deal["followup"]
        lines.append(f"✉️ Follow-up: {followup.get('status', 'draft')}")
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
    if deal.get("loss"):
        loss = deal["loss"]
        lines.append(f"🪦 Закрытие: {loss.get('reason')}")
    if deal["messages"]:
        last = deal["messages"][-1]
        arrow = "→" if last["direction"] == "outgoing" else "←"
        lines.append(f"\nПоследнее: {arrow} {last['text'][:100]}")

    return "\n".join(lines)


def format_deal_timeline(deal: dict, limit=15) -> str:
    """Format recent deal events for Telegram."""
    ensure_deal_fields(deal)
    events = deal.get("events", [])[-limit:]
    lines = [
        f"🧾 *Timeline сделки {deal['deal_id']}*",
        f"Стадия: {stage_label(deal.get('stage'))}",
        "",
    ]
    if not events:
        lines.append("Событий пока нет.")
        return "\n".join(lines)

    for event in events:
        ts = event.get("timestamp", "")
        short_ts = ts.replace("T", " ")[:16] if ts else "—"
        title = event.get("title") or event.get("type") or "event"
        lines.append(f"• `{short_ts}` — {title}")

    return "\n".join(lines)
