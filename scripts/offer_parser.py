#!/usr/bin/env python3
"""
GTA IRL OS — Offer Parser v3
- Хранит офферы как JSON (offer_store)
- Отправляет карточки с inline-кнопками
- Raw данные защищены от AI
"""

import os
import asyncio
import hashlib
import requests
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient, events

# Импортируем хранилище
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from offer_store import create_offer, update_offer, validate_contact_url

API_ID    = int(os.getenv("TELEGRAM_API_ID", "30611066"))
API_HASH  = os.getenv("TELEGRAM_API_HASH", "86864ae4d512125ab1fcc930da6a6f5b")
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GROQ_KEY  = os.getenv("GROQ_API_KEY", "")
GROQ_URL  = "https://api.groq.com/openai/v1/chat/completions"

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parser_session")
STOP_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".parser_stop")

OWNER_CHAT_ID = None
RUNNING = True

if os.path.exists(STOP_FILE):
    os.remove(STOP_FILE)

seen_offers = set()

# ── Каналы ───────────────────────────────────────────────────────────────────

MONITOR_CHATS = [
    "mari_vakansii",
    "freelansim_ru",
]

# ── Фильтры ───────────────────────────────────────────────────────────────────

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

EXCLUDE = [
    "#помогу", "#предлагаю", "#услуги", "#выполню", "#возьмусь",
    "#портфолио", "#опыт", "#резюме", "#ищуработу", "#ищу_работу",
    "предлагаю свои услуги", "готов выполнить", "мои услуги",
    "принимаю заказы", "открыт к заказам",
    "страховой взнос", "залог", "гарантийный взнос",  # антискам
]

# Скам-маркеры
SCAM_MARKERS = [
    "страховой взнос", "залог", "гарантийный взнос",
    "внести взнос", "оплатить страховку",
]


def is_client_offer(text):
    t = text.lower()
    for excl in EXCLUDE:
        if excl.lower() in t:
            return False, []
    matches = [kw for kw in KEYWORDS if kw.lower() in t]
    return len(matches) >= 1, matches


def is_scam(text):
    t = text.lower()
    return any(m in t for m in SCAM_MARKERS)


def offer_hash(text, sender_id=None):
    key = f"{sender_id}:{text[:100]}"
    return hashlib.md5(key.encode()).hexdigest()


def is_duplicate(text, sender_id=None):
    h = offer_hash(text, sender_id)
    if h in seen_offers:
        return True
    seen_offers.add(h)
    return False


# ── AI оценка (только display, не трогает raw) ────────────────────────────────

def ai_score(text, chat_name):
    if not GROQ_KEY:
        return None
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [
                      {"role": "system", "content": """Оцени фриланс-оффер для Владимира (Python, боты, AI, монтаж).
Формат ответа — строго 4 строки:
⚡ [Легко/Средне/Сложно]
💰 [бюджет или "уточнить"]
⏱ [срок]
📌 [брать/не брать — 1 причина]"""},
                      {"role": "user", "content": f"{text[:400]}"}
                  ],
                  "max_tokens": 100},
            timeout=12)
        if r.status_code == 429:
            return None
        return r.json()["choices"][0]["message"]["content"]
    except:
        return None


# ── Отправка карточки с inline-кнопками ──────────────────────────────────────

def safe_md(text: str) -> str:
    """Экранирует спецсимволы Markdown v1 в тексте."""
    for ch in ["_", "*", "`", "["]:
        text = text.replace(ch, f"\\{ch}")
    return text


def send_offer_card(offer: dict):
    if not OWNER_CHAT_ID or not BOT_TOKEN:
        return

    d = offer["display"]
    raw = offer["raw"]
    offer_id = offer["offer_id"]

    scam_flag = "🚫 *ВОЗМОЖНЫЙ СКАМ*\n" if is_scam(offer["raw_text"]) else ""

    # Строим блок контакта
    username      = raw.get("sender_username")
    text_username = raw.get("text_username")
    sender_id     = raw.get("sender_id")
    sender_name   = safe_md(d["sender_name"])
    all_mentions  = raw.get("all_mentions", [])

    contact_lines = []

    # Отправитель
    if username:
        clean = username.lstrip("@")
        contact_lines.append(f"[{sender_name} @{clean}](https://t.me/{clean})")
    elif sender_id:
        contact_lines.append(f"[{sender_name}](tg://user?id={sender_id})")
    else:
        contact_lines.append(sender_name)

    # Упомянутые в тексте (кроме уже показанного)
    shown = {username.lstrip("@") if username else ""}
    for mention in all_mentions:
        if mention not in shown and mention.lower() != "username":
            contact_lines.append(f"[@{mention}](https://t.me/{mention})")
            shown.add(mention)

    contact_block = " | ".join(contact_lines)

    # Ссылка на сообщение
    msg_url = raw.get("msg_url")
    source_display = f"[{safe_md(d['chat_name'])}]({msg_url})" if msg_url else safe_md(d['chat_name'])

    preview = safe_md(d["preview"])

    text = (
        f"{scam_flag}"
        f"🎯 *Оффер* `{offer_id}` | {d['date']}\n"
        f"📍 {source_display}\n"
        f"👤 {contact_block}\n"
        f"🔑 {', '.join(d['keywords'][:3])}\n\n"
        f"{preview}"
    )

    if d.get("ai_score"):
        text += f"\n\n{d['ai_score']}"

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Откликнуться", "callback_data": f"respond:{offer_id}"},
            {"text": "🚫 Скам",         "callback_data": f"scam:{offer_id}"},
        ], [
            {"text": "👁 Скрыть",       "callback_data": f"hide:{offer_id}"},
            {"text": "📤 Делегировать", "callback_data": f"delegate:{offer_id}"},
        ]]
    }

    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id":    OWNER_CHAT_ID,
                "text":       text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
                "reply_markup": keyboard,
            },
            timeout=10
        )
    except Exception as e:
        print(f"Ошибка отправки: {e}")


def send_text(text: str):
    if not OWNER_CHAT_ID or not BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": OWNER_CHAT_ID, "text": text,
                  "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=10
        )
    except:
        pass


# ── Сканирование истории ──────────────────────────────────────────────────────

async def get_sender_info(msg, client):
    try:
        sender = await msg.get_sender()
        username  = getattr(sender, "username", None)
        firstName = getattr(sender, "first_name", "") or ""
        sender_id = getattr(sender, "id", None)
    except:
        username, firstName, sender_id = None, "Аноним", None

    # Ищем @username прямо в тексте оффера
    text = msg.text or ""
    mentioned = re.findall(r'@([a-zA-Z0-9_]{4,})', text)
    # Берём первый упомянутый username если у sender нет своего
    text_username = mentioned[0] if mentioned else None

    return {
        "id":           sender_id,
        "username":     username,
        "text_username": text_username,   # username из текста оффера
        "first_name":   firstName,
        "all_mentions": mentioned,
    }


async def process_message(msg, client, chat_name, chat_username, is_history=False):
    global RUNNING
    if os.path.exists(STOP_FILE):
        RUNNING = False
        return

    text = msg.text or ""
    if len(text) < 30:
        return

    found, keywords = is_client_offer(text)
    if not found:
        return

    sender_info = await get_sender_info(msg, client)
    sender_id = sender_info["id"] or msg.sender_id

    if is_duplicate(text, sender_id):
        return

    date_str = msg.date.strftime("%d.%m %H:%M") if hasattr(msg.date, 'strftime') else str(msg.date)
    score = ai_score(text, chat_name)

    # Лучший доступный контакт: sender > упомянут в тексте > tg://user?id=
    best_username = sender_info["username"] or sender_info.get("text_username")
    contact_url = None
    if best_username:
        contact_url = f"https://t.me/{best_username}"
    elif sender_id:
        contact_url = f"tg://user?id={sender_id}"

    offer = create_offer(
        raw_text=text,
        chat_name=chat_name,
        chat_username=chat_username,
        msg_id=msg.id,
        sender_id=sender_id,
        sender_name=sender_info["first_name"] or "Аноним",
        sender_username=best_username,
        msg_date=date_str,
        keywords=keywords,
        ai_score=score,
    )

    # Сохраняем все упоминания и contact_url
    if contact_url:
        offer["raw"]["contact_url"] = contact_url
    offer["raw"]["all_mentions"]  = sender_info.get("all_mentions", [])
    offer["raw"]["text_username"] = sender_info.get("text_username")

    send_offer_card(offer)
    prefix = "📚" if is_history else "🆕"
    print(f"{prefix} [{date_str}] {chat_name}: {text[:60]}...")


async def scan_history(client, entity, chat_name, chat_username, hours=24):
    from datetime import timezone
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    count = 0
    async for msg in client.iter_messages(entity, limit=1000):
        if os.path.exists(STOP_FILE):
            return count
        if not msg.date or msg.date < cutoff:
            break
        await process_message(msg, client, chat_name, chat_username, is_history=True)
        count += 1
        await asyncio.sleep(2)
    return count


# ── Команды через polling ─────────────────────────────────────────────────────

async def poll_commands():
    global RUNNING
    offset = 0
    while RUNNING:
        if os.path.exists(STOP_FILE):
            RUNNING = False
            send_text("⏹ *Парсер остановлен.*")
            return
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 3},
                timeout=8
            )
            for update in r.json().get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = (msg.get("text", "") or "").lower().strip()
                if text in ["/стоп", "/stop", "стоп", "stop"]:
                    RUNNING = False
                    open(STOP_FILE, 'w').close()
                    send_text("⏹ *Парсер остановлен.*")
                    return
        except:
            pass
        await asyncio.sleep(2)


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    global OWNER_CHAT_ID, RUNNING

    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.start()

    me = await client.get_me()
    OWNER_CHAT_ID = me.id
    print(f"Авторизован: {me.first_name}")

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
        send_text("⚠️ Нет доступных каналов.")
        return

    chat_list = "\n".join(f"• {t}" for _, _, t in monitored)
    send_text(f"🔍 *Парсер офферов v3*\n\n{chat_list}\n\nКнопки: Откликнуться / Скам / Скрыть / Делегировать\nНапиши /стоп для остановки.")

    asyncio.ensure_future(poll_commands())

    total = 0
    for entity, username, title in monitored:
        if not RUNNING:
            break
        print(f"Сканирую историю: {title}")
        count = await scan_history(client, entity, title, username)
        total += count

    if RUNNING:
        send_text(f"✅ История просканирована. Офферов: *{total}*\n\nСлушаю новые...")

    entities = [e for e, _, _ in monitored]
    names = {getattr(e, "id", None): (u, t) for e, u, t in monitored}

    @client.on(events.NewMessage(chats=entities))
    async def handle(event):
        if not RUNNING:
            return
        try:
            chat = await event.get_chat()
            chat_username = getattr(chat, "username", None) or ""
            chat_name = getattr(chat, "title", chat_username)
        except:
            chat_username, chat_name = "", "Чат"
        await process_message(event.message, client, chat_name, chat_username, is_history=False)

    # Слушаем входящие личные сообщения (inbox listener встроен)
    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def handle_inbox(event):
        if not RUNNING:
            return
        msg = event.message
        text = msg.text or ""
        if not text:
            return
        try:
            sender = await event.get_sender()
            sender_id   = sender.id
            if sender_id == me.id:
                return
            sender_name = getattr(sender, "first_name", "") or getattr(sender, "username", "?")
        except:
            return
        # Ищем активную сделку
        from negotiator import list_deals, get_deal, save_deal, update_stage, add_message, STAGE_LABELS
        deals = list_deals()
        matched = None
        for deal in deals:
            if deal.get("stage") in ["CLOSED", "LOST", "SCAM"]:
                continue
            if deal.get("contact", {}).get("user_id") and int(deal["contact"]["user_id"]) == int(sender_id):
                matched = deal
                break
        if not matched:
            return
        deal_id = matched["deal_id"]
        add_message(matched, "incoming", text)
        if matched.get("stage") == "FIRST_MESSAGE_SENT":
            update_stage(matched, "QUALIFYING")
        # Уведомляем
        send_text(
            f"📨 *Ответ клиента*\nСделка `{deal_id}`\n👤 {sender_name}\n\n_{text[:300]}_"
        )
        # Генерируем следующий вопрос
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from inbox_listener import generate_qualifying_question
        next_q = generate_qualifying_question(matched, text)
        matched["draft"] = next_q
        save_deal(matched)
        keyboard = {"inline_keyboard": [[
            {"text": "✅ Отправить", "callback_data": f"send_reply:{deal_id}"},
            {"text": "❌ Пропустить", "callback_data": f"skip_reply:{deal_id}"},
        ]]}
        if OWNER_CHAT_ID and BOT_TOKEN:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": OWNER_CHAT_ID,
                      "text": f"✏️ *Черновик ответа*\n\n_{next_q}_\n\nОтправить?",
                      "parse_mode": "Markdown",
                      "reply_markup": keyboard},
                timeout=10
            )

    print("Слушаю новые сообщения и входящие от клиентов...")
    while RUNNING:
        await asyncio.sleep(1)

    await client.disconnect()
    print("Парсер остановлен.")


if __name__ == "__main__":
    print("GTA IRL OS — Парсер офферов v3")
    asyncio.run(main())
