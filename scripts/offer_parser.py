#!/usr/bin/env python3
"""
GTA IRL OS — Telegram Offer Parser
Сканирует историю за 24ч + слушает новые сообщения
"""

import os
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient, events

API_ID    = int(os.getenv("TELEGRAM_API_ID", "30611066"))
API_HASH  = os.getenv("TELEGRAM_API_HASH", "86864ae4d512125ab1fcc930da6a6f5b")
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GROQ_KEY  = os.getenv("GROQ_API_KEY", "")
GROQ_URL  = "https://api.groq.com/openai/v1/chat/completions"

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parser_session")

OWNER_CHAT_ID = None

# ── Каналы для мониторинга ────────────────────────────────────────────────────

MONITOR_CHATS = [
    "mari_vakansii",
    "freelansim_ru",
    # добавляй сюда каналы которые мониторишь вручную
]

# ── Ключевые слова ────────────────────────────────────────────────────────────

KEYWORDS = [
    "ищу разработчика", "нужен разработчик", "ищем разработчика",
    "нужен программист", "ищу программиста",
    "автоматизация", "бот телеграм", "нужен бот", "telegram bot",
    "парсер", "python разработчик", "ai агент", "ai agent",
    "чат-бот", "chatbot", "фриланс", "freelance",
    "ищу исполнителя", "нужен исполнитель",
    "срочно нужен", "кто может сделать", "кто возьмётся",
    "youtube", "ютуб", "монтаж", "видеомонтаж",
    "оплата сразу", "бюджет", "готов заплатить",
]


# ── Утилиты ───────────────────────────────────────────────────────────────────

def is_offer(text):
    text_lower = text.lower()
    matches = [kw for kw in KEYWORDS if kw.lower() in text_lower]
    return len(matches) >= 1, matches


def send_to_bot(text):
    global OWNER_CHAT_ID
    if not OWNER_CHAT_ID or not BOT_TOKEN:
        print("[БОТ]", text[:80])
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_CHAT_ID, "text": text,
                  "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=10
        )
    except Exception as e:
        print(f"Ошибка отправки: {e}")


def ai_evaluate(text, chat_name):
    if not GROQ_KEY:
        return None
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [
                      {"role": "system", "content": "Ты оцениваешь фриланс-офферы. Владимир умеет: Python, Telegram-боты, AI-агенты, автоматизация, монтаж видео. Оцени оффер в 1-2 предложения: стоит ли браться, примерный бюджет."},
                      {"role": "user", "content": f"Оффер из {chat_name}:\n{text[:400]}"}
                  ],
                  "max_tokens": 120},
            timeout=15)
        return r.json()["choices"][0]["message"]["content"]
    except:
        return None


def format_offer(text, chat_name, link, date_str, is_history=False):
    icon = "📚 *История*" if is_history else "🎯 *Новый оффер*"
    found, keywords = is_offer(text)
    preview = text[:300] + ("..." if len(text) > 300 else "")
    kw_str = ", ".join(keywords[:3])
    result = f"{icon} | {date_str}\n📍 {chat_name}\n🔑 {kw_str}\n\n{preview}\n\n🔗 {link}"
    evaluation = ai_evaluate(text, chat_name)
    if evaluation:
        result += f"\n\n🧠 *Оценка:* {evaluation}"
    return result


# ── Сканирование истории ──────────────────────────────────────────────────────

async def scan_history(client, entity, chat_name, chat_username, hours=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    count = 0
    async for msg in client.iter_messages(entity, limit=500):
        if not msg.date or msg.date < cutoff:
            break
        text = msg.text or ""
        if len(text) < 30:
            continue
        found, _ = is_offer(text)
        if not found:
            continue
        link = f"https://t.me/{chat_username}/{msg.id}" if chat_username else "нет ссылки"
        date_str = msg.date.strftime("%d.%m %H:%M")
        send_to_bot(format_offer(text, chat_name, link, date_str, is_history=True))
        count += 1
        await asyncio.sleep(0.8)
    return count


# ── Основной цикл ─────────────────────────────────────────────────────────────

async def main():
    global OWNER_CHAT_ID

    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.start()

    me = await client.get_me()
    OWNER_CHAT_ID = me.id
    print(f"Авторизован: {me.first_name}")

    # Подключаемся к чатам
    monitored = []
    for username in MONITOR_CHATS:
        try:
            entity = await client.get_entity(username)
            title = getattr(entity, "title", username)
            monitored.append((entity, username, title))
            print(f"OK: @{username} — {title}")
        except Exception as e:
            print(f"FAIL: @{username} — {e}")

    if not monitored:
        send_to_bot("⚠️ Ни один чат не подключён. Проверь список MONITOR\\_CHATS.")
        return

    # Сканируем историю
    chat_list = "\n".join(f"• {t}" for _, _, t in monitored)
    send_to_bot(f"🔍 *Сканирую историю за 24ч*\n\n{chat_list}")

    total = 0
    for entity, username, title in monitored:
        print(f"Сканирую историю: {title}")
        count = await scan_history(client, entity, title, username)
        print(f"  Найдено: {count}")
        total += count

    if total == 0:
        send_to_bot("📭 За 24ч офферов по ключевым словам не найдено.\n\nСлушаю новые сообщения в реальном времени...")
    else:
        send_to_bot(f"✅ Сканирование завершено. Найдено: *{total} офферов*\n\nТеперь слушаю новые...")

    # Слушаем новые
    entities = [e for e, _, _ in monitored]
    chat_map = {getattr(e, "id", None): (u, t) for e, u, t in monitored}

    @client.on(events.NewMessage(chats=entities))
    async def handle(event):
        text = event.message.text or ""
        if len(text) < 30:
            return
        found, _ = is_offer(text)
        if not found:
            return
        try:
            chat = await event.get_chat()
            title = getattr(chat, "title", None) or getattr(chat, "username", "?")
            uname = getattr(chat, "username", None)
            link = f"https://t.me/{uname}/{event.message.id}" if uname else "нет ссылки"
        except:
            title, link = "Чат", "нет ссылки"
        date_str = datetime.now().strftime("%H:%M")
        send_to_bot(format_offer(text, title, link, date_str, is_history=False))

    print("Слушаю новые сообщения...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    print("GTA IRL OS — Парсер офферов")
    asyncio.run(main())
