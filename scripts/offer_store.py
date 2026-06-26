"""
GTA IRL OS — Offer Store
Хранит каждый оффер как JSON с разделением raw data и display data.
Raw поля (username, urls) никогда не изменяются AI.
"""

import json
import uuid
import os
from typing import Optional
from datetime import datetime

OFFERS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "offers")
os.makedirs(OFFERS_DIR, exist_ok=True)


def create_offer(
    raw_text: str,
    chat_name: str,
    chat_username: str,
    msg_id: int,
    sender_id: int,
    sender_name: str,
    sender_username: Optional[str],
    msg_date: str,
    keywords: list,
    ai_score: Optional[str] = None,
    score: Optional[dict] = None,
) -> dict:
    """Создаёт оффер. Raw поля защищены от изменений AI."""

    offer_id = str(uuid.uuid4())[:8]

    # RAW DATA — никогда не передаются в AI, не изменяются
    raw = {
        "sender_id":       sender_id,
        "sender_username": sender_username,          # может быть None
        "chat_username":   chat_username,
        "msg_id":          msg_id,
        "msg_url":         f"https://t.me/{chat_username}/{msg_id}" if chat_username else None,
        "contact_url":     f"https://t.me/{sender_username}" if sender_username else f"tg://user?id={sender_id}",
    }

    offer = {
        "offer_id":    offer_id,
        "created_at":  datetime.utcnow().isoformat(),
        "status":      "NEW",          # NEW | RESPONDED | HIDDEN | SCAM
        "raw":         raw,
        "raw_text":    raw_text,       # оригинальный текст оффера, не изменяется
        "display": {
            "chat_name":    chat_name,
            "sender_name":  sender_name,
            "date":         msg_date,
            "keywords":     keywords,
            "ai_score":     ai_score,   # оценка AI — только display, не влияет на raw
            "score":        score,
            "preview":      raw_text[:350] + ("..." if len(raw_text) > 350 else ""),
        },
        "deal_id": None,  # заполняется когда создаётся сделка
    }

    # Сохраняем
    path = os.path.join(OFFERS_DIR, f"{offer_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(offer, f, ensure_ascii=False, indent=2)

    return offer


def get_offer(offer_id: str) -> Optional[dict]:
    path = os.path.join(OFFERS_DIR, f"{offer_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def update_offer(offer_id: str, **kwargs) -> Optional[dict]:
    offer = get_offer(offer_id)
    if not offer:
        return None
    offer.update(kwargs)
    offer["updated_at"] = datetime.utcnow().isoformat()
    path = os.path.join(OFFERS_DIR, f"{offer_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(offer, f, ensure_ascii=False, indent=2)
    return offer


def list_offers(status: Optional[str] = None) -> list:
    offers = []
    for fname in os.listdir(OFFERS_DIR):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(OFFERS_DIR, fname), encoding="utf-8") as f:
            offer = json.load(f)
        if status is None or offer.get("status") == status:
            offers.append(offer)
    return sorted(offers, key=lambda x: x["created_at"], reverse=True)


def validate_contact_url(offer: dict) -> tuple[bool, str]:
    """Проверяет кликабельность ссылки на контакт."""
    raw = offer.get("raw", {})
    contact_url = raw.get("contact_url", "")
    sender_username = raw.get("sender_username")

    if sender_username:
        # Проверяем что username не содержит Markdown который ломает ссылки
        clean = sender_username.strip().lstrip("@")
        if "_" in clean:
            # Нижние подчёркивания в username — экранируем в Markdown
            return True, f"https://t.me/{clean}"
        return True, f"https://t.me/{clean}"
    elif raw.get("sender_id"):
        return True, f"tg://user?id={raw['sender_id']}"
    else:
        return False, ""
