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
        "budget":     None,
        "deadline":   None,
        "result":     None,
    }
    init_pipeline(deal)
    save_deal(deal)
    return deal


def save_deal(deal: dict):
    init_pipeline(deal)
    path = os.path.join(DEALS_DIR, f"{deal['deal_id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(deal, f, ensure_ascii=False, indent=2)


def get_deal(deal_id: str) -> Optional[dict]:
    path = os.path.join(DEALS_DIR, f"{deal_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        deal = json.load(f)
    return init_pipeline(deal)


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
            deal = json.load(f)
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


# ── Форматирование карточки сделки ────────────────────────────────────────────

def format_deal_card(deal: dict) -> str:
    init_pipeline(deal)
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
    if deal["messages"]:
        last = deal["messages"][-1]
        arrow = "→" if last["direction"] == "outgoing" else "←"
        lines.append(f"\nПоследнее: {arrow} {last['text'][:100]}")

    return "\n".join(lines)
