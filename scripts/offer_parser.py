#!/usr/bin/env python3
"""
GTA IRL OS — Telegram Offer Parser v2
- Дедупликация по user_id + хэшу текста
- Команда /стоп в боте останавливает парсер
- AI-оценка реализуемости каждого оффера
"""

import os
import asyncio
import hashlib
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
RUNNING = True  # флаг остановки

# Уже отправленные офферы — дедупликация
seen_offers = set()

# ── Каналы ───────────────────────────────────────────────────────────────────

MONITOR_CHATS = [
    "mari_vakansii",
    "freelansim_ru",
]

# ── Ключевые слова — ЗАКАЗЧИКИ ────────────────────────────────────────────────

KEYWORDS = [
    "ищу разработчика", "нужен разработчик", "ищем разработчика",
    "нужен программист", "ищу программиста",
    "автоматизация", "бот телеграм", "нужен бот", "telegram bot",
    "парсер", "python разработчик", "ai агент", "ai agent",
    "чат-бот", "chatbot", "ищу исполнителя", "нужен исполнитель",
    "срочно нужен", "кто может сделать", "кто возьмётся",
    "youtube", "ютуб", "монтаж", "видеомонтаж",
    "оплата сразу", "готов заплатить", "#ищу",
]

# ── Исключения — ФРИЛАНСЕРЫ ───────────────────────────────────────────────────

EXCLUDE = [
    "#помогу", "#предлагаю", "#услуги", "#выполню", "#возьмусь",
    "#портфолио", "#опыт", "#резюме", "#ищуработу", "#ищу_работу",
    "предлагаю свои услуги", "готов выполнить", "мои услуги",
    "принимаю заказы", "открыт к заказам", "обращайтесь ко мне",
]


# ── Фильтр ────────────────────────────────────────────────────────────────────

def is_client_offer(text):
    t = text.lower()
    for excl in EXCLUDE:
        if excl.lower() in t:
            return False, []
    matches = [kw for kw in KEYWORDS if kw.lower() in t]
    return len(matches) >= 1, matches


def offer_hash(text, sender_id=None):
    """Уникальный ключ оффера — по отправителю + первым 100 символам текста."""
    key = f"{sender_id}:{text[:100]}"
    return hashlib.md5(key.encode()).hexdigest()


def is_duplicate(text, sender_id=None):
    h = offer_hash(text, sender_id)
    if h in seen_offers:
        return True
    seen_offers.add(h)
    return False


# ── Отправка ──────────────────────────────────────────────────────────────────

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
        print(f"Ошибка: {e}")


# ── AI оценка ─────────────────────────────────────────────────────────────────

def ai_evaluate(text, chat_name):
    if not GROQ_KEY:
        return None
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [
                      {"role": "system", "content": """Ты оцениваешь фриланс-офферы для Владимира.
Его навыки: Python, Telegram-боты, AI-агенты, автоматизация, Groq/Claude API, монтаж видео.
Важно: с AI-помощью он может сделать почти любую задачу за 1-3 дня.

Ответь строго в формате:
⚡ Реализуемость: [Легко/Средне/Сложно]
💰 Бюджет: [сумма или "уточнить"]
⏱ Срок: [оценка времени]
📌 Вывод: [1 предложение — брать или нет]"""},
                      {"role": "user", "content": f"Оффер из {chat_name}:\n{text[:500]}"}
                  ],
                  "max_tokens": 150},
            timeout=15)
        return r.json()["choices"][0]["message"]["content"]
    except:
        return None


def format_offer(text, chat_name, link, date_str, sender_id=None, is_history=False):
    icon = "📚 *История*" if is_history else "🎯 *Новый оффер*"
    _, keywords = is_client_offer(text)
    preview = text[:350] + ("..." if len(text) > 350 else "")
    kw_str = ", ".join(keywords[:3])
    result = f"{icon} | {date_str}\n📍 {chat_name}\n🔑 {kw_str}\n\n{preview}\n\n🔗 {link}"
    evaluation = ai_evaluate(text, chat_name)
    if evaluation:
        result += f"\n\n{evaluation}"
    return result


# ── Сканирование истории ──────────────────────────────────────────────────────

async def scan_history(client, entity, chat_name, chat_username, hours=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    count = 0
    async for msg in client.iter_messages(entity, limit=1000):
        if not msg.date or msg.date < cutoff:
            break
        text = msg.text or ""
        if len(text) < 30:
            continue
        found, _ = is_client_offer(text)
        if not found:
            continue
        sender_id = msg.sender_id
        if is_duplicate(text, sender_id):
            continue
        link = f"https://t.me/{chat_username}/{msg.id}" if chat_username else "нет ссылки"
        date_str = msg.date.strftime("%d.%m %H:%M")
        send_to_bot(format_offer(text, chat_name, link, date_str, sender_id, is_history=True))
        count += 1
        await asyncio.sleep(0.5)
    return count


# ── Команды бота ──────────────────────────────────────────────────────────────

async def check_bot_commands(bot_token, owner_id):
    """Проверяет не написал ли пользователь /стоп в боте."""
    global RUNNING
    offset = 0
    while RUNNING:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{bot_token}/getUpdates",
                params={"offset": offset, "timeout": 5},
                timeout=10
            )
            data = r.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "").lower().strip()
                chat_id = msg.get("chat", {}).get("id")
                if chat_id == owner_id and text in ["/стоп", "/stop", "стоп", "stop"]:
                    RUNNING = False
                    send_to_bot("⏹ *Парсер остановлен.*\nДля запуска снова: `python3 scripts/offer_parser.py`")
                    return
        except:
            pass
        await asyncio.sleep(3)


# ── Основной цикл ─────────────────────────────────────────────────────────────

async def main():
    global OWNER_CHAT_ID, RUNNING

    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.start()

    me = await client.get_me()
    OWNER_CHAT_ID = me.id
    print(f"Авторизован: {me.first_name} (ID: {me.id})")

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
        send_to_bot("⚠️ Ни один чат не подключён.")
        return

    chat_list = "\n".join(f"• {t}" for _, _, t in monitored)
    send_to_bot(
        f"🔍 *Парсер офферов запущен v2*\n\n"
        f"{chat_list}\n\n"
        f"Напиши /стоп чтобы остановить."
    )

    # Запускаем проверку команд параллельно
    asyncio.ensure_future(check_bot_commands(BOT_TOKEN, OWNER_CHAT_ID))

    # Сканируем историю
    total = 0
    for entity, username, title in monitored:
        if not RUNNING:
            break
        print(f"Сканирую: {title}")
        count = await scan_history(client, entity, title, username)
        total += count
        print(f"  Найдено уникальных: {count}")

    if RUNNING:
        msg = f"✅ История просканирована. Уникальных офферов: *{total}*\n\nСлушаю новые..."
        send_to_bot(msg)

    # Слушаем новые сообщения
    entities = [e for e, _, _ in monitored]

    @client.on(events.NewMessage(chats=entities))
    async def handle(event):
        if not RUNNING:
            return
        text = event.message.text or ""
        if len(text) < 30:
            return
        found, _ = is_client_offer(text)
        if not found:
            return
        sender_id = event.message.sender_id
        if is_duplicate(text, sender_id):
            return
        try:
            chat = await event.get_chat()
            title = getattr(chat, "title", None) or getattr(chat, "username", "?")
            uname = getattr(chat, "username", None)
            link = f"https://t.me/{uname}/{event.message.id}" if uname else "нет ссылки"
        except:
            title, link = "Чат", "нет ссылки"
        date_str = datetime.now().strftime("%H:%M")
        send_to_bot(format_offer(text, title, link, date_str, sender_id, is_history=False))

    print("Слушаю новые сообщения. Напиши /стоп в боте для остановки.")

    while RUNNING:
        await asyncio.sleep(1)

    await client.disconnect()
    print("Парсер остановлен.")


if __name__ == "__main__":
    print("GTA IRL OS — Парсер офферов v2")
    asyncio.run(main())
