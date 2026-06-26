#!/usr/bin/env python3
"""
GTA IRL OS — Telegram Offer Parser
Мониторит чаты по ключевым словам и присылает офферы в бот

Запуск:
    python3 scripts/offer_parser.py

При первом запуске попросит номер телефона и код из Telegram.
После авторизации сессия сохраняется — повторный вход не нужен.
"""

import os
import re
import asyncio
import requests
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat

# ── Config ────────────────────────────────────────────────────────────────────

API_ID   = int(os.getenv("TELEGRAM_API_ID", "30611066"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "86864ae4d512125ab1fcc930da6a6f5b")
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Твой Telegram ID — куда слать офферы (узнаем автоматически при старте)
OWNER_CHAT_ID = None

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parser_session")

# ── Ключевые слова для поиска офферов ────────────────────────────────────────

OFFER_KEYWORDS = [
    # Разработка и автоматизация
    "ищу разработчика", "нужен разработчик", "ищем разработчика",
    "нужен программист", "ищу программиста",
    "автоматизация", "бот телеграм", "telegram bot", "нужен бот",
    "парсер", "скрипт", "python разработчик",
    "ai агент", "ai agent", "чат-бот", "chatbot",
    # Фриланс
    "фриланс", "freelance", "удаленно", "remote",
    "ищу исполнителя", "нужен исполнитель",
    "оплата", "бюджет", "заказ", "задача",
    # YouTube / контент
    "youtube", "ютуб", "монтаж", "видеомонтаж",
    "контент", "reels", "shorts",
    # Конкретные форматы
    "срочно нужен", "кто может", "помогите найти",
]

# Чаты для мониторинга (добавляй username без @)
MONITOR_CHATS = [
    # Хабр Фриланс — реальные заказы на Python, боты, парсинг
    "freelansim_ru",
    # Фриланс заказы общие
    "freelance_ru_chat",
    "ru_python",
    # AI и автоматизация
    "ai_python_ru",
    "chatgpt_ru",
    "openai_ru",
    # Telegram боты и разработка
    "tgdev",
    "botcreators",
    # Удалённая работа
    "remote_ru",
    "digital_nomad_russia",
    # YouTube / контент / монтаж
    "youtube_ru_chat",
    "videoeditors_ru",
    # Общий фриланс чат
    "freelance_chat_ru",
    "it_freelance_ru",
]

# ── Отправка в бот ────────────────────────────────────────────────────────────

def send_to_bot(text):
    """Отправляет сообщение через бота в личку."""
    global OWNER_CHAT_ID
    if not OWNER_CHAT_ID or not BOT_TOKEN:
        print(f"[ОФФЕР] {text[:100]}")
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": OWNER_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10
        )
    except Exception as e:
        print(f"Ошибка отправки: {e}")


def analyze_offer(text, chat_name, msg_link):
    """Быстрая оценка оффера через Groq."""
    if not GROQ_API_KEY:
        return None

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": """Ты анализируешь офферы о работе для фрилансера.
Владимир умеет: Python, Telegram боты, AI агенты, автоматизация, монтаж видео.
Оцени оффер кратко: реально ли взяться, примерный бюджет, срочность.
Ответь в 2-3 предложения максимум."""},
                    {"role": "user", "content": f"Оффер из {chat_name}:\n{text[:500]}"}
                ],
                "max_tokens": 150,
            },
            timeout=15
        )
        return r.json()["choices"][0]["message"]["content"]
    except:
        return None


def is_offer(text):
    """Проверяет содержит ли сообщение оффер."""
    text_lower = text.lower()
    matches = [kw for kw in OFFER_KEYWORDS if kw.lower() in text_lower]
    return len(matches) >= 1, matches


# ── Основной клиент ───────────────────────────────────────────────────────────

async def main():
    global OWNER_CHAT_ID

    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.start()

    # Получаем свой ID
    me = await client.get_me()
    OWNER_CHAT_ID = me.id
    print(f"✅ Авторизован как: {me.first_name} (@{me.username})")
    print(f"   Твой ID: {OWNER_CHAT_ID}")

    # Подключаемся к чатам
    monitored = []
    for chat_username in MONITOR_CHATS:
        try:
            entity = await client.get_entity(chat_username)
            monitored.append(entity)
            print(f"✅ Мониторю: @{chat_username}")
        except Exception as e:
            print(f"⚠️  Не могу подключиться к @{chat_username}: {e}")

    if not monitored:
        print("⚠️  Ни один чат не подключён. Добавь себя в чаты или обнови список.")

    send_to_bot(
        f"🤖 *Парсер офферов запущен*\n\n"
        f"Мониторю {len(monitored)} чатов\n"
        f"Ключевых слов: {len(OFFER_KEYWORDS)}\n\n"
        f"Буду присылать офферы сюда."
    )

    print(f"\n🔍 Слушаю сообщения... (Ctrl+C для остановки)\n")

    @client.on(events.NewMessage(chats=monitored if monitored else None))
    async def handle_message(event):
        msg = event.message
        text = msg.text or ""

        if len(text) < 30:
            return

        found, keywords = is_offer(text)
        if not found:
            return

        # Получаем название чата
        try:
            chat = await event.get_chat()
            chat_name = getattr(chat, 'title', None) or getattr(chat, 'username', 'Неизвестный чат')
        except:
            chat_name = "Неизвестный чат"

        # Ссылка на сообщение
        try:
            chat_username = getattr(await event.get_chat(), 'username', None)
            msg_link = f"https://t.me/{chat_username}/{msg.id}" if chat_username else "нет ссылки"
        except:
            msg_link = "нет ссылки"

        now = datetime.now().strftime("%H:%M")
        preview = text[:300] + ("..." if len(text) > 300 else "")

        # Анализ через AI
        ai_take = analyze_offer(text, chat_name, msg_link)

        # Формируем сообщение
        output = (
            f"🎯 *Новый оффер* | {now}\n"
            f"📍 {chat_name}\n"
            f"🔑 Ключевые слова: {', '.join(keywords[:3])}\n\n"
            f"{preview}\n\n"
            f"🔗 {msg_link}"
        )

        if ai_take:
            output += f"\n\n🧠 *Оценка:* {ai_take}"

        send_to_bot(output)
        print(f"[{now}] Оффер из {chat_name}: {text[:60]}...")

    await client.run_until_disconnected()


if __name__ == "__main__":
    print("GTA IRL OS — Парсер офферов")
    print("=" * 40)
    asyncio.run(main())
