#!/usr/bin/env python3
"""
GTA IRL OS — Inbox Listener
Слушает все входящие личные сообщения через Telethon.
Если отправитель есть в активных сделках — обновляет стадию
и генерирует следующий вопрос для квалификации.
"""

import os
import sys
import asyncio
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from offer_store import get_offer
from negotiator import (
    get_deal, save_deal, update_stage, add_message,
    draft_first_message, list_deals, STAGE_LABELS
)
from telethon import TelegramClient, events

API_ID    = int(os.getenv("TELEGRAM_API_ID", "30611066"))
API_HASH  = os.getenv("TELEGRAM_API_HASH", "86864ae4d512125ab1fcc930da6a6f5b")
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GROQ_KEY  = os.getenv("GROQ_API_KEY", "")
GROQ_URL  = "https://api.groq.com/openai/v1/chat/completions"

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inbox_session")
STOP_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".inbox_stop")

OWNER_CHAT_ID = None


# ── Найти сделку по sender_id ─────────────────────────────────────────────────

def find_deal_by_sender(sender_id: int):
    """Ищет активную сделку по user_id отправителя."""
    deals = list_deals()
    for deal in deals:
        if deal.get("stage") in ["CLOSED", "LOST", "SCAM"]:
            continue
        contact_id = deal.get("contact", {}).get("user_id")
        if contact_id and int(contact_id) == int(sender_id):
            return deal
        username = deal.get("contact", {}).get("username")
        # Тоже проверяем по username если id не совпал
    return None


# ── AI: следующий вопрос для квалификации ────────────────────────────────────

def generate_qualifying_question(deal: dict, client_reply: str) -> str:
    """Генерирует следующий вопрос для сбора ТЗ/бюджета/дедлайна."""
    messages_history = deal.get("messages", [])
    stage = deal.get("stage", "")

    # Определяем что ещё не собрали
    missing = []
    if not deal.get("budget"):
        missing.append("бюджет")
    if not deal.get("deadline"):
        missing.append("дедлайн")
    if not deal.get("tz"):
        missing.append("техническое задание")

    if not missing:
        # Всё собрано — предлагаем КП
        return generate_offer(deal)

    if not GROQ_KEY:
        return f"Понял! Уточните пожалуйста {missing[0]}?"

    history_text = "\n".join([
        f"{'Я' if m['direction'] == 'outgoing' else 'Клиент'}: {m['text']}"
        for m in messages_history[-6:]
    ])

    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [
                      {"role": "system", "content": f"""Ты ведёшь переговоры по фриланс-заказу от имени Владимира.
Нужно собрать: {', '.join(missing)}.
История диалога:
{history_text}

Ответ клиента: {client_reply}

Напиши ОДИН короткий вопрос (1-2 предложения) чтобы собрать следующий пункт.
Не объясняй зачем спрашиваешь. Просто спроси естественно."""},
                      {"role": "user", "content": client_reply}
                  ],
                  "max_tokens": 100},
            timeout=12)
        if r.status_code == 429:
            return f"Понял! Подскажите {missing[0]}?"
        return r.json()["choices"][0]["message"]["content"]
    except:
        return f"Понял! Подскажите {missing[0]}?"


def generate_offer(deal: dict) -> str:
    """Генерирует КП когда всё собрано."""
    budget = deal.get("budget", "по договорённости")
    deadline = deal.get("deadline", "обсудим")
    tz = deal.get("tz", deal["offer_text"][:200])

    if not GROQ_KEY:
        return f"Готов взяться за задачу.\nСтоимость: {budget}\nСрок: {deadline}\nРаботаю по предоплате 50%. Когда готовы начать?"

    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [
                      {"role": "system", "content": "Напиши короткое КП для фриланс-заказа. 3-4 предложения. Условия: предоплата 50%."},
                      {"role": "user", "content": f"ТЗ: {tz}\nБюджет: {budget}\nСрок: {deadline}"}
                  ],
                  "max_tokens": 200},
            timeout=12)
        if r.status_code == 429:
            return f"Готов взяться. Стоимость: {budget}, срок: {deadline}. Работаю по предоплате 50%."
        return r.json()["choices"][0]["message"]["content"]
    except:
        return f"Готов взяться. Стоимость: {budget}, срок: {deadline}. Работаю по предоплате 50%."


# ── Парсим бюджет/дедлайн из ответа клиента ──────────────────────────────────

def extract_info(text: str, deal: dict):
    """Пытается извлечь бюджет и дедлайн из текста клиента."""
    import re

    # Бюджет
    budget_patterns = [
        r'(\d[\d\s]*(?:руб|рубл|₽|k|к|тыс|000))',
        r'бюджет[:\s]+([^\n,]+)',
        r'готов заплатить[:\s]+([^\n,]+)',
        r'оплата[:\s]+([^\n,]+)',
    ]
    if not deal.get("budget"):
        for pattern in budget_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                deal["budget"] = m.group(1).strip()
                break

    # Дедлайн
    deadline_patterns = [
        r'(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)',
        r'(до\s+\d[^\n,]+)',
        r'(за\s+\d+\s+(?:день|дня|дней|недел|месяц))',
        r'(к\s+\d[^\n,]+)',
        r'срок[:\s]+([^\n,]+)',
    ]
    if not deal.get("deadline"):
        for pattern in deadline_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                deal["deadline"] = m.group(1).strip()
                break

    return deal


# ── Отправка в бот ────────────────────────────────────────────────────────────

def send_to_bot(text: str, keyboard=None):
    if not OWNER_CHAT_ID or not BOT_TOKEN:
        print(f"[БОТ] {text[:80]}")
        return
    payload = {
        "chat_id":    OWNER_CHAT_ID,
        "text":       text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload, timeout=10
        )
    except Exception as e:
        print(f"Ошибка отправки: {e}")


# ── Обработка входящего сообщения от клиента ─────────────────────────────────

async def handle_client_reply(sender_id: int, sender_name: str, text: str):
    """Вызывается когда клиент написал в личку."""
    deal = find_deal_by_sender(sender_id)

    if not deal:
        # Не наш клиент — игнорируем
        return

    deal_id = deal["deal_id"]
    stage = deal.get("stage", "")

    print(f"[{datetime.now().strftime('%H:%M')}] Ответ от {sender_name} по сделке {deal_id}: {text[:60]}")

    # Логируем входящее
    add_message(deal, "incoming", text)

    # Обновляем стадию
    if stage == "FIRST_MESSAGE_SENT":
        update_stage(deal, "QUALIFYING")
        stage = "QUALIFYING"

    # Извлекаем бюджет/дедлайн
    deal = extract_info(text, deal)
    save_deal(deal)

    stage_label = STAGE_LABELS.get(stage, stage)
    contact_name = deal["contact"].get("name", "Клиент")

    # Уведомляем тебя
    send_to_bot(
        f"📨 *Ответ от клиента*\n"
        f"Сделка: `{deal_id}` | {stage_label}\n"
        f"👤 {contact_name}\n\n"
        f"_{text[:300]}_"
        + (f"\n\n💰 Бюджет: {deal['budget']}" if deal.get('budget') else "")
        + (f"\n⏰ Дедлайн: {deal['deadline']}" if deal.get('deadline') else "")
    )

    # Генерируем следующий вопрос
    next_msg = generate_qualifying_question(deal, text)

    # Кнопки подтверждения
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Отправить", "callback_data": f"send_reply:{deal_id}"},
            {"text": "✏️ Изменить", "callback_data": f"edit_reply:{deal_id}"},
        ], [
            {"text": "❌ Пропустить", "callback_data": f"skip_reply:{deal_id}"},
        ]]
    }

    # Сохраняем черновик
    deal["draft"] = next_msg
    save_deal(deal)

    send_to_bot(
        f"✏️ *Черновик ответа* (сделка `{deal_id}`)\n\n"
        f"_{next_msg}_\n\n"
        f"Отправить?",
        keyboard=keyboard
    )


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    global OWNER_CHAT_ID

    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)

    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.start()

    me = await client.get_me()
    OWNER_CHAT_ID = me.id
    print(f"Inbox listener запущен: {me.first_name}")

    send_to_bot("📥 *Inbox listener запущен*\nСлушаю ответы клиентов по активным сделкам.")

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def handle_incoming(event):
        if os.path.exists(STOP_FILE):
            await client.disconnect()
            return

        msg = event.message
        text = msg.text or ""
        if not text:
            return

        try:
            sender = await event.get_sender()
            sender_id   = sender.id
            sender_name = getattr(sender, "first_name", "") or getattr(sender, "username", "?")
        except:
            return

        # Не реагируем на свои сообщения
        if sender_id == me.id:
            return

        await handle_client_reply(sender_id, sender_name, text)

    print("Слушаю входящие личные сообщения...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    print("GTA IRL OS — Inbox Listener")
    asyncio.run(main())
