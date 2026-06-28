#!/usr/bin/env python3
"""
GTA IRL OS — Main Process
Один процесс. Один getUpdates. Без конфликтов.

Архитектура:
- telebot polling в отдельном thread (единственный getUpdates)
- Telethon в asyncio event loop в отдельном thread (парсинг + отправка)
- Общение между ними через Queue
"""

import os
import sys
import json
import time
import asyncio
import hashlib
import logging
import requests
import threading
from datetime import datetime, timezone, timedelta
from queue import Queue, Empty

import telebot
from telethon import TelegramClient, events

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    ROOT, SESSION_FILE, STOP_FILE, LAST_MSG_IDS_FILE,
    BOT_TOKEN, GROQ_KEY, TELEGRAM_API_ID, TELEGRAM_API_HASH,
    GROQ_URL, GROQ_MODEL, BOT_USERNAME, MONITOR_CHATS,
    OFFER_KEYWORDS, OFFER_EXCLUDE,
    SEND_RATE_LIMIT_SECONDS, HISTORY_SCAN_LIMIT, HISTORY_SCAN_HOURS,
    HISTORY_SCAN_DELAY_SECONDS, SEND_QUEUE_POLL_SECONDS,
)
from offer_store import create_offer, get_offer, update_offer
from negotiator import (
    create_deal, get_deal, save_deal, update_stage, add_message,
    draft_first_message, list_deals, format_deal_card
)

# Глобальные переменные
bot          = telebot.TeleBot(BOT_TOKEN)
owner_id     = None
seen_hashes  = set()
parser_running = False
send_queue   = Queue()   # задачи для Telethon (отправка сообщений)
telethon_loop = None
telethon_client = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger("gta")


# ── Утилиты ───────────────────────────────────────────────────────────────────

def is_offer(text):
    t = text.lower()
    if any(e.lower() in t for e in OFFER_EXCLUDE):
        return False, []
    matches = [k for k in OFFER_KEYWORDS if k.lower() in t]
    return len(matches) >= 1, matches

def offer_hash(text, sender_id):
    return hashlib.md5(f"{sender_id}:{text[:100]}".encode()).hexdigest()

def kb_to_dict(kb):
    """Конвертирует InlineKeyboardMarkup в JSON-сериализуемый dict."""
    if kb is None:
        return None
    if isinstance(kb, dict):
        return kb
    # telebot InlineKeyboardMarkup → dict
    rows = []
    for row in kb.keyboard:
        rows.append([{"text": btn.text, "callback_data": btn.callback_data} for btn in row])
    return {"inline_keyboard": rows}

def send_to_owner(text, keyboard=None):
    if not owner_id:
        return
    payload = {
        "chat_id": owner_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = kb_to_dict(keyboard)
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json=payload, timeout=10)
    except Exception as e:
        log.error(f"send_to_owner: {e}")

def groq(system, user, max_tokens=200):
    if not GROQ_KEY:
        return None
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={"model": GROQ_MODEL,
                  "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}],
                  "max_tokens": max_tokens},
            timeout=15)
        if r.status_code == 429:
            return None
        return r.json()["choices"][0]["message"]["content"]
    except:
        return None

def make_kb(*rows):
    """Создаёт InlineKeyboardMarkup из списков кнопок."""
    kb = telebot.types.InlineKeyboardMarkup()
    for row in rows:
        kb.row(*[telebot.types.InlineKeyboardButton(text, callback_data=cb)
                 for text, cb in row])
    return kb


# ── Telethon: отправка сообщений ──────────────────────────────────────────────

_last_send_time   = 0.0

def load_last_msg_ids():
    if os.path.exists(LAST_MSG_IDS_FILE):
        try:
            return json.load(open(LAST_MSG_IDS_FILE))
        except:
            pass
    return {}

def save_last_msg_id(chat_username, msg_id):
    ids = load_last_msg_ids()
    ids[chat_username] = msg_id
    os.makedirs(os.path.dirname(LAST_MSG_IDS_FILE), exist_ok=True)
    json.dump(ids, open(LAST_MSG_IDS_FILE, "w"))


def send_via_telethon(target, text):
    """Синхронная обёртка с rate limiting."""
    global _last_send_time
    elapsed = time.time() - _last_send_time
    if elapsed < SEND_RATE_LIMIT_SECONDS:
        wait = SEND_RATE_LIMIT_SECONDS - elapsed
        log.info(f"Rate limit: жду {wait:.1f}с перед отправкой")
        time.sleep(wait)

    result_event = threading.Event()
    result_box   = [None]

    def callback(ok, err):
        result_box[0] = (ok, err)
        result_event.set()

    send_queue.put((target, text, callback))
    result_event.wait(timeout=30)
    _last_send_time = time.time()
    return result_box[0] or (False, "timeout")


# ── Парсинг оффера ────────────────────────────────────────────────────────────

def process_offer(text, chat_name, chat_username, msg_id, sender_id,
                  sender_name, sender_username, msg_date, all_mentions):
    found, keywords = is_offer(text)
    if not found:
        return

    h = offer_hash(text, sender_id)
    if h in seen_hashes:
        return
    seen_hashes.add(h)

    best_username = sender_username or (all_mentions[0] if all_mentions else None)
    contact_url = (f"https://t.me/{best_username}" if best_username
                   else f"tg://user?id={sender_id}" if sender_id else None)

    # Rule-based скоринг — без AI, без API-запросов
    from offer_scoring import score_offer, format_score
    rule_score = score_offer(text, keywords)
    score_text = format_score(rule_score)

    # Не показываем офферы с вердиктом "не брать" (скам, низкая релевантность)
    if rule_score["verdict"] == "не брать":
        log.info(f"Пропущен (не брать): {text[:50]}")
        return

    offer = create_offer(
        raw_text=text, chat_name=chat_name, chat_username=chat_username,
        msg_id=msg_id, sender_id=sender_id, sender_name=sender_name,
        sender_username=best_username, msg_date=msg_date,
        keywords=keywords, ai_score=score_text,
    )
    offer["raw"]["contact_url"]   = contact_url
    offer["raw"]["all_mentions"]  = all_mentions
    offer["raw"]["text_username"] = all_mentions[0] if all_mentions else None

    # Строим карточку
    oid = offer["offer_id"]
    safe = lambda s: (s or "").replace("_", "\\_").replace("*", "").replace("[", "")
    name = safe(sender_name)

    if best_username:
        contact_md = f"[{name} @{best_username}](https://t.me/{best_username})"
    elif sender_id:
        contact_md = f"[{name}](tg://user?id={sender_id})"
    else:
        contact_md = name

    msg_url = f"https://t.me/{chat_username}/{msg_id}" if chat_username else None
    source_md = f"[{safe(chat_name)}]({msg_url})" if msg_url else safe(chat_name)
    preview = safe(text[:300]) + ("..." if len(text) > 300 else "")
    kw_str  = ", ".join(keywords[:3])

    card = (f"🎯 *Оффер* `{oid}` | {msg_date}\n"
            f"📍 {source_md}\n"
            f"👤 {contact_md}\n"
            f"🔑 {kw_str}\n\n{preview}")
    if score:
        card += f"\n\n{score}"

    kb = make_kb(
        [("✅ Откликнуться", f"respond:{oid}"), ("🚫 Скам", f"scam:{oid}")],
        [("👁 Скрыть",       f"hide:{oid}"),    ("📤 Делегировать", f"delegate:{oid}")],
    )
    send_to_owner(card, kb)
    log.info(f"Оффер {oid}: {text[:50]}")


# ── Telethon thread ───────────────────────────────────────────────────────────

def telethon_thread():
    global telethon_loop, telethon_client, parser_running, owner_id

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    telethon_loop = loop

    async def run():
        global telethon_client, parser_running, owner_id

        client = TelegramClient(SESSION_FILE, TELEGRAM_API_ID, TELEGRAM_API_HASH)
        telethon_client = client
        await client.start()

        me = await client.get_me()
        owner_id = me.id
        log.info(f"Telethon: {me.first_name} (ID {me.id})")

        # Обработка очереди отправки
        async def process_send_queue():
            while True:
                try:
                    target, text, cb = send_queue.get_nowait()
                    try:
                        await client.send_message(target, text)
                        cb(True, None)
                        log.info(f"Отправлено: {target}")
                    except Exception as e:
                        cb(False, str(e))
                        log.error(f"Ошибка отправки {target}: {e}")
                except Empty:
                    pass
                await asyncio.sleep(SEND_QUEUE_POLL_SECONDS)

        # Сканирование истории — только новые с последнего запуска
        async def scan_history(entity, chat_name, chat_username):
            last_ids  = load_last_msg_ids()
            min_id    = last_ids.get(chat_username, 0)  # 0 = первый запуск
            cutoff    = datetime.now(timezone.utc) - timedelta(hours=HISTORY_SCAN_HOURS)
            count     = 0
            newest_id = min_id

            # Лимит сообщений за сессию — защита от FloodWait
            async for msg in client.iter_messages(entity, limit=HISTORY_SCAN_LIMIT, min_id=min_id):
                if os.path.exists(STOP_FILE):
                    break
                if not msg.date or msg.date < cutoff:
                    break
                if msg.id > newest_id:
                    newest_id = msg.id
                text = msg.text or ""
                if len(text) < 30:
                    continue
                try:
                    sender = await msg.get_sender()
                    uname  = getattr(sender, "username", None)
                    fname  = getattr(sender, "first_name", "") or ""
                    sid    = getattr(sender, "id", None)
                except:
                    uname, fname, sid = None, "Аноним", None

                import re
                mentions = re.findall(r'@([a-zA-Z0-9_]{4,})', text)
                process_offer(text, chat_name, chat_username, msg.id,
                              sid, fname, uname, msg.date.strftime("%d.%m %H:%M"), mentions)
                count += 1
                await asyncio.sleep(HISTORY_SCAN_DELAY_SECONDS)  # пауза между сообщениями

            # Сохраняем прогресс
            if newest_id > min_id:
                save_last_msg_id(chat_username, newest_id)
                log.info(f"Прогресс сохранён: @{chat_username} до msg_id={newest_id}")

            return count

        # Новые сообщения в каналах
        async def start_parser():
            global parser_running
            if os.path.exists(STOP_FILE):
                os.remove(STOP_FILE)

            monitored = []
            for username in MONITOR_CHATS:
                try:
                    entity = await client.get_entity(username)
                    title  = getattr(entity, "title", username)
                    monitored.append((entity, username, title))
                    log.info(f"Канал: @{username} — {title}")
                except Exception as e:
                    log.warning(f"Пропущен @{username}: {e}")

            if not monitored:
                send_to_owner("⚠️ Нет доступных каналов для мониторинга.")
                return

            names = "\n".join(f"• {t}" for _, _, t in monitored)
            send_to_owner(f"🔍 *Парсер запущен*\n\n{names}\n\nНапиши /стоп для остановки.")
            parser_running = True

            # История
            total = 0
            for entity, uname, title in monitored:
                if os.path.exists(STOP_FILE):
                    break
                n = await scan_history(entity, title, uname)
                total += n
            send_to_owner(f"✅ История просканирована. Офферов: *{total}*\n\nСлушаю новые...")

            # Новые сообщения
            @client.on(events.NewMessage(chats=[e for e, _, _ in monitored]))
            async def on_new(event):
                if os.path.exists(STOP_FILE):
                    return
                text = event.message.text or ""
                if len(text) < 30:
                    return
                try:
                    chat   = await event.get_chat()
                    cu     = getattr(chat, "username", "") or ""
                    cn     = getattr(chat, "title", cu)
                    sender = await event.get_sender()
                    uname  = getattr(sender, "username", None)
                    fname  = getattr(sender, "first_name", "") or ""
                    sid    = getattr(sender, "id", None)
                except:
                    return
                import re
                mentions = re.findall(r'@([a-zA-Z0-9_]{4,})', text)
                process_offer(text, cn, cu, event.message.id, sid, fname, uname,
                              datetime.now().strftime("%H:%M"), mentions)

        # Входящие личные сообщения от клиентов
        @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
        async def on_inbox(event):
            text = event.message.text or ""
            if not text:
                return
            try:
                sender  = await event.get_sender()
                sid     = sender.id
                if sid == me.id:
                    return
                sname   = getattr(sender, "first_name", "") or getattr(sender, "username", "?")
            except:
                return

            # Ищем активную сделку
            for deal in list_deals():
                if deal.get("stage") in ["CLOSED_WON", "CLOSED_LOST", "SCAM"]:
                    continue
                cid = deal.get("contact", {}).get("user_id")
                if cid and int(cid) == int(sid):
                    add_message(deal, "incoming", text)
                    if deal.get("stage") == "FIRST_MESSAGE_SENT":
                        update_stage(deal, "WAITING_REPLY")
                        update_stage(deal, "CLIENT_REPLIED")

                    # Шаблонный следующий вопрос — без AI
                    has_budget  = deal.get("budget")
                    has_deadline = deal.get("deadline")
                    if not has_budget:
                        next_q = "Отлично! Подскажите, какой у вас бюджет на задачу?"
                    elif not has_deadline:
                        next_q = "Понял! В какие сроки нужно выполнить?"
                    else:
                        next_q = "Готов взяться. Работаю по предоплате 50%. Когда готовы начать?"

                    deal["draft"] = next_q
                    save_deal(deal)
                    did = deal["deal_id"]

                    kb = make_kb(
                        [("✅ Отправить", f"send_reply:{did}"),
                         ("❌ Пропустить", f"skip_reply:{did}")],
                    )
                    send_to_owner(
                        f"📨 *Ответ клиента*\nСделка `{did}`\n👤 {sname}\n\n_{text[:300]}_"
                        f"\n\n✏️ *Черновик:*\n{next_q}\n\nОтправить?",
                        kb
                    )
                    break

        asyncio.ensure_future(process_send_queue())
        await start_parser()
        await client.run_until_disconnected()

    loop.run_until_complete(run())


# ── Bot handlers ──────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "help"])
def cmd_start(msg):
    bot.send_message(msg.chat.id,
        "👋 *GTA IRL OS*\n\n"
        "/collapse — состояние системы\n"
        "/deals — активные сделки\n"
        "/стоп — остановить парсер\n"
        "/старт — запустить парсер\n\n"
        "Или просто напиши что угодно.", parse_mode="Markdown")

@bot.message_handler(commands=["стоп", "stop"])
def cmd_stop(msg):
    open(STOP_FILE, "w").close()
    bot.send_message(msg.chat.id, "⏹ Парсер остановлен.")

@bot.message_handler(commands=["старт", "start_parser"])
def cmd_start_parser(msg):
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    bot.send_message(msg.chat.id, "▶️ Парсер перезапускается...")
    # Перезапуск через новый поток
    t = threading.Thread(target=telethon_thread, daemon=True)
    t.start()

@bot.message_handler(commands=["deals"])
def cmd_deals(msg):
    deals = list_deals()
    active = [d for d in deals if d.get("stage") not in ["CLOSED_WON", "CLOSED_LOST", "SCAM"]]
    if not active:
        bot.send_message(msg.chat.id, "Активных сделок нет.")
        return
    lines = [f"*Активные сделки ({len(active)}):*"]
    for d in active[:10]:
        name = d.get("contact", {}).get("name", "?")
        lines.append(f"• `{d['deal_id']}` — {name} — {d.get('stage','?')}")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown")

@bot.message_handler(commands=["collapse"])
def cmd_collapse(msg):
    deals = list_deals()
    active = [d for d in deals if d.get("stage") not in ["CLOSED_WON", "CLOSED_LOST", "SCAM"]]
    text = (f"*🧠 GTA IRL OS*\n_{datetime.now().strftime('%d.%m %H:%M')}_\n\n"
            f"Парсер: {'🟢 работает' if not os.path.exists(STOP_FILE) else '🔴 остановлен'}\n"
            f"Каналы: {', '.join(MONITOR_CHATS)}\n"
            f"Сделок активных: {len(active)}\n"
            f"Офферов в базе: {len(list(os.listdir(os.path.join(ROOT, 'data', 'offers'))))}")
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=["reset"])
def cmd_reset(msg):
    bot.send_message(msg.chat.id, "✅ История сброшена.")

@bot.message_handler(content_types=["voice"])
def handle_voice(msg):
    if msg.chat.type != "private" and not (
        msg.reply_to_message and
        getattr(msg.reply_to_message.from_user, "username", "") == BOT_USERNAME
    ):
        return
    thinking = bot.send_message(msg.chat.id, "🎤 Слушаю...", reply_to_message_id=msg.message_id)
    try:
        fi  = bot.get_file(msg.voice.file_id)
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fi.file_path}"
        audio = requests.get(url).content
        r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            files={"file": ("voice.ogg", audio, "audio/ogg")},
            data={"model": "whisper-large-v3-turbo", "language": "ru"}, timeout=30)
        r.raise_for_status()
        text = r.json().get("text", "").strip()
        if not text:
            bot.edit_message_text("❌ Не распознал.", msg.chat.id, thinking.message_id)
            return
        reply = groq("Ты ассистент GTA IRL OS Владимира. Отвечай кратко по-русски.", text, max_tokens=300) or text
        bot.edit_message_text(f"🎤 _{text}_\n\n{reply}", msg.chat.id, thinking.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ {e}", msg.chat.id, thinking.message_id)

@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(msg):
    text = msg.text or ""
    # Группа — только @упоминания и реплаи
    if msg.chat.type != "private":
        mention = f"@{BOT_USERNAME}"
        is_reply = (msg.reply_to_message and
                    getattr(msg.reply_to_message.from_user, "username", "") == BOT_USERNAME)
        if mention.lower() not in text.lower() and not is_reply:
            return
        text = text.replace(f"@{BOT_USERNAME}", "").strip()

    thinking = bot.send_message(msg.chat.id, "⏳", reply_to_message_id=msg.message_id)
    reply = groq("Ты ассистент GTA IRL OS Владимира. Отвечай кратко по-русски.", text, max_tokens=500)
    if reply:
        bot.edit_message_text(reply, msg.chat.id, thinking.message_id)
    else:
        bot.edit_message_text("⏳ AI недоступен, попробуй позже.", msg.chat.id, thinking.message_id)


# ── Callback кнопки ───────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    data    = call.data
    chat_id = call.message.chat.id
    msg_id  = call.message.message_id
    log.info(f"CALLBACK: {data}")

    try:
        action, rest = data.split(":", 1)
    except:
        bot.answer_callback_query(call.id, "❌")
        return

    # ── Оффер ──
    if action in ("scam", "hide", "delegate", "respond"):
        offer = get_offer(rest)
        if not offer:
            bot.answer_callback_query(call.id, "❌ Оффер не найден")
            return

        if action == "scam":
            update_offer(rest, status="SCAM")
            bot.answer_callback_query(call.id, "🚫 Скам")
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)

        elif action == "hide":
            update_offer(rest, status="HIDDEN")
            bot.answer_callback_query(call.id, "👁 Скрыто")
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)

        elif action == "delegate":
            update_offer(rest, status="DELEGATED")
            bot.answer_callback_query(call.id, "📤 Делегировано")
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)

        elif action == "respond":
            bot.answer_callback_query(call.id, "✅ Черновик готов")
            deal = create_deal(offer)
            update_offer(rest, status="RESPONDED", deal_id=deal["deal_id"])
            update_stage(deal, "RESPOND_DECIDED")
            update_stage(deal, "FIRST_MESSAGE_DRAFTED")

            # Шаблонный черновик — без AI, мгновенно
            contact_name = offer["display"].get("sender_name", "")
            draft = f"Добрый день{', ' + contact_name if contact_name else ''}! Увидел вашу заявку — всё ещё актуально?"
            deal["draft"] = draft
            save_deal(deal)

            did = deal["deal_id"]
            kb  = make_kb(
                [("✅ Отправить", f"send_draft:{did}"),
                 ("✏️ AI-улучшить", f"ai_draft:{did}"),
                 ("❌ Отменить",  f"cancel_draft:{did}")],
            )
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
            bot.send_message(chat_id,
                f"✏️ *Черновик*\nСделка `{did}`\n\n{draft}\n\nОтправить или улучшить через AI?",
                parse_mode="Markdown", reply_markup=kb)

    # ── AI-улучшение черновика по запросу ──
    elif action == "ai_draft":
        deal = get_deal(rest)
        if not deal:
            bot.answer_callback_query(call.id, "❌ Сделка не найдена")
            return
        bot.answer_callback_query(call.id, "⏳ Улучшаю через AI...")
        improved = groq(
            "Напиши короткий первый отклик на фриланс-заявку от имени Владимира. "
            "2-3 предложения. Вежливо, по-русски. Уточни актуальность.",
            f"Заявка:\n{deal['offer_text'][:400]}", max_tokens=150
        ) or deal.get("draft", "")
        deal["draft"] = improved
        save_deal(deal)
        did = rest
        kb = make_kb(
            [("✅ Отправить", f"send_draft:{did}"),
             ("❌ Отменить",  f"cancel_draft:{did}")],
        )
        bot.edit_message_text(
            f"✏️ *AI-черновик*\nСделка `{did}`\n\n{improved}\n\nОтправить?",
            chat_id, msg_id, parse_mode="Markdown", reply_markup=kb
        )

    # ── Отправка черновика ──
    elif action == "send_draft":
        deal = get_deal(rest)
        if not deal:
            bot.answer_callback_query(call.id, "❌ Сделка не найдена")
            return
        draft    = deal.get("draft", "")
        username = deal["contact"].get("username")
        user_id  = deal["contact"].get("user_id")
        target   = username or user_id

        if not target:
            bot.answer_callback_query(call.id, "❌ Нет контакта")
            bot.send_message(chat_id, "❌ Нет username или user_id для отправки.")
            return

        bot.answer_callback_query(call.id, "📨 Отправляю...")
        ok, err = send_via_telethon(target, draft)
        if ok:
            update_stage(deal, "FIRST_MESSAGE_SENT")
            update_stage(deal, "WAITING_REPLY")
            add_message(deal, "outgoing", draft)
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
            bot.send_message(chat_id, f"✅ Отправлено! Сделка `{rest}` → ⏳ ждём ответ.",
                             parse_mode="Markdown")
        else:
            bot.send_message(chat_id, f"❌ Ошибка: {err}")

    elif action == "cancel_draft":
        bot.answer_callback_query(call.id, "❌ Отменено")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)

    # ── Ответ клиенту в диалоге ──
    elif action == "send_reply":
        deal = get_deal(rest)
        if not deal:
            bot.answer_callback_query(call.id, "❌ Сделка не найдена")
            return
        draft    = deal.get("draft", "")
        username = deal["contact"].get("username")
        user_id  = deal["contact"].get("user_id")
        target   = username or user_id

        bot.answer_callback_query(call.id, "📨 Отправляю...")
        ok, err = send_via_telethon(target, draft)
        if ok:
            add_message(deal, "outgoing", draft)
            bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
            bot.send_message(chat_id, "✅ Ответ отправлен.", parse_mode="Markdown")
        else:
            bot.send_message(chat_id, f"❌ Ошибка: {err}")

    elif action == "skip_reply":
        bot.answer_callback_query(call.id, "⏭ Пропущено")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)


# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("GTA IRL OS запускается...")

    # Telethon в отдельном thread
    t = threading.Thread(target=telethon_thread, daemon=True)
    t.start()

    # Ждём пока Telethon авторизуется и получим owner_id
    for _ in range(30):
        if owner_id:
            break
        time.sleep(1)

    log.info(f"Owner ID: {owner_id}")
    log.info("Bot polling started")

    # Telebot polling — единственный getUpdates
    bot.infinity_polling(allowed_updates=["message", "callback_query"], timeout=30, long_polling_timeout=30)
