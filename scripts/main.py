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
    BOT_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH,
    BOT_USERNAME, MONITOR_CHATS,
    OFFER_KEYWORDS, OFFER_EXCLUDE,
    SEND_RATE_LIMIT_SECONDS, HISTORY_SCAN_LIMIT, HISTORY_SCAN_HOURS,
    HISTORY_SCAN_DELAY_SECONDS, SEND_QUEUE_POLL_SECONDS,
)
from ai_service import ask_ai, transcribe_audio
from telegram_risk import (
    classify_telegram_error,
    log_telegram_event,
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
        log_telegram_event("bot_send", status="skipped", channel="owner", meta={"reason": "missing_owner_id"})
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
        response = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                 json=payload, timeout=10)
        log_telegram_event("bot_send", status="ok" if response.ok else "error", channel="owner", meta={
            "status_code": response.status_code,
            "text_chars": len(text or ""),
        })
    except Exception as e:
        log_telegram_event("bot_send", status="error", channel="owner", meta=classify_telegram_error(e))
        log.error(f"send_to_owner: {e}")

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
        log_telegram_event("rate_wait", status="ok", channel="telethon", meta={"wait_seconds": round(wait, 2)})
        time.sleep(wait)

    result_event = threading.Event()
    result_box   = [None]

    def callback(ok, err):
        result_box[0] = (ok, err)
        result_event.set()

    send_queue.put((target, text, callback))
    result_event.wait(timeout=30)
    _last_send_time = time.time()
    if result_box[0] is None:
        log_telegram_event("telethon_send", status="error", channel="client", meta={
            "error_type": "Timeout",
            "target_type": "username" if isinstance(target, str) else "user_id",
            "text_chars": len(text or ""),
        })
        return (False, "timeout")
    return result_box[0]


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
                        log_telegram_event("telethon_send", status="ok", channel="client", meta={
                            "target_type": "username" if isinstance(target, str) else "user_id",
                            "text_chars": len(text or ""),
                        })
                        log.info(f"Отправлено: {target}")
                    except Exception as e:
                        cb(False, str(e))
                        meta = classify_telegram_error(e)
                        meta.update({
                            "target_type": "username" if isinstance(target, str) else "user_id",
                            "text_chars": len(text or ""),
                        })
                        log_telegram_event("telethon_send", status="error", channel="client", meta=meta)
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
                sname = getattr(sender, "first_name", "") or getattr(sender, "username", "?")
            except:
                return

            # Ищем активную сделку по sender_id
            deal = None
            for d in list_deals():
                if d.get("stage") in ["CLOSED_WON", "CLOSED_LOST", "SCAM", "CLIENT_GHOSTED"]:
                    continue
                if str(d.get("contact", {}).get("user_id", "")) == str(sid):
                    deal = d
                    break
            if not deal:
                return

            deal_id = deal["deal_id"]
            stage   = deal.get("stage", "")

            # Логируем и извлекаем данные из текста
            add_message(deal, "incoming", text)
            from negotiator import update_brief_from_text
            changed = update_brief_from_text(deal, text)

            # Обновляем стадию
            if stage in ["FIRST_MESSAGE_SENT", "WAITING_REPLY"]:
                update_stage(deal, "CLIENT_REPLIED")
                update_stage(deal, "QUALIFYING")

            # Что уже собрали
            brief    = deal.get("brief", {})
            budget   = deal.get("budget") or brief.get("budget")
            deadline = deal.get("deadline") or brief.get("deadline")
            scope    = brief.get("scope") or brief.get("description")

            # Следующий шаг воронки
            if not budget:
                next_q     = "Отлично! Подскажите, какой бюджет на задачу?"
                next_stage = "QUALIFYING"
            elif not deadline:
                next_q     = "Понял! В какие сроки нужно выполнить?"
                next_stage = "QUALIFYING"
            elif not scope:
                next_q     = "Хорошо! Опишите подробнее что именно нужно сделать?"
                next_stage = "QUALIFYING"
            else:
                # Всё собрано → КП с предоплатой
                next_q = (
                    f"Отлично, всё понял!\n\n"
                    f"Стоимость: {budget}\n"
                    f"Срок: {deadline}\n\n"
                    f"Работаю по предоплате 50%. "
                    f"Как удобно оплатить? (карта РФ / крипта / Thai Baht)"
                )
                next_stage = "PROPOSAL_SENT"

            deal["draft"]      = next_q
            deal["next_stage"] = next_stage
            save_deal(deal)

            # Что извлекли из сообщения
            changed_txt = ""
            if changed:
                parts = []
                if changed.get("budget"):   parts.append(f"💰 {changed['budget']}")
                if changed.get("deadline"): parts.append(f"⏰ {changed['deadline']}")
                if changed.get("scope"):    parts.append("📋 ТЗ")
                if parts:
                    changed_txt = "\n" + " · ".join(parts)

            stage_lbl = STAGE_LABELS.get(deal.get("stage", ""), "")
            kb = make_kb(
                [("✅ Отправить", f"send_reply:{deal_id}"),
                 ("❌ Пропустить", f"skip_reply:{deal_id}")],
            )
            send_to_owner(
                f"📨 *Ответ клиента*\n"
                f"Сделка `{deal_id}` · {stage_lbl}\n"
                f"👤 {sname}{changed_txt}\n\n"
                f"_{text[:300]}_\n\n"
                f"✏️ *Черновик:*\n{next_q}\n\nОтправить?",
                kb
            )

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
        "/report — дневной Phase 1 отчёт\n"
        "/deals — активные сделки\n"
        "/ai_usage — расход AI за сегодня\n"
        "/telegram_risk — риск Telegram/FloodWait\n"
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
    terminal = ["CLOSED_WON", "CLOSED_LOST", "SCAM", "CLIENT_GHOSTED"]
    active = [d for d in deals if d.get("stage") not in terminal]
    if not active:
        bot.send_message(msg.chat.id, "Активных сделок нет.")
        return

    stage_icons = {
        "NEW_LEAD":             "🆕",
        "RESPOND_DECIDED":      "✅",
        "FIRST_MESSAGE_DRAFTED":"✏️",
        "FIRST_MESSAGE_SENT":   "📨",
        "WAITING_REPLY":        "⏳",
        "CLIENT_REPLIED":       "💬",
        "QUALIFYING":           "🔍",
        "PROPOSAL_SENT":        "📋",
        "PREPAYMENT_WAITING":   "💳",
        "PREPAYMENT_RECEIVED":  "💰",
        "IN_WORK":              "⚙️",
    }

    # Отправляем по одной карточке на каждую сделку
    for d in active[:15]:
        contact = d.get("contact", {})
        name     = contact.get("name", "?")
        username = contact.get("username")
        user_id  = contact.get("user_id")
        stage    = d.get("stage", "?")
        icon     = stage_icons.get(stage, "•")
        did      = d["deal_id"]
        budget   = d.get("budget") or d.get("brief", {}).get("budget") or "—"
        deadline = d.get("deadline") or d.get("brief", {}).get("deadline") or "—"

        # Кликабельная ссылка
        if username:
            contact_link = f"[{name} @{username}](https://t.me/{username})"
        elif user_id:
            contact_link = f"[{name}](tg://user?id={user_id})"
        else:
            contact_link = name

        # Последнее сообщение
        msgs = d.get("messages", [])
        last_msg = ""
        if msgs:
            last = msgs[-1]
            arrow = "→" if last["direction"] == "outgoing" else "←"
            last_msg = f"\n_{arrow} {last['text'][:80]}_"

        text = (
            f"{icon} *{contact_link}*\n"
            f"`{did}` · 💰 {budget} · ⏰ {deadline}\n"
            f"Стадия: {STAGE_LABELS.get(stage, stage)}"
            f"{last_msg}"
        )

        kb = make_kb(
            [("📨 Написать", f"open_chat:{did}"),
             ("✅ Предоплата", f"prepay:{did}"),
             ("👻 Пропал", f"ghost:{did}")],
        )
        bot.send_message(msg.chat.id, text,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                        reply_markup=kb)


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

@bot.message_handler(commands=["report"])
def cmd_report(msg):
    offers = list(os.listdir(os.path.join(ROOT, "data", "offers")))
    deals  = list_deals()

    by_status = {}
    for f in offers:
        try:
            o = json.load(open(os.path.join(ROOT, "data", "offers", f)))
            s = o.get("status", "NEW")
            by_status[s] = by_status.get(s, 0) + 1
        except:
            pass

    by_stage = {}
    prepaid  = 0
    for d in deals:
        s = d.get("stage", "")
        by_stage[s] = by_stage.get(s, 0) + 1
        if s in ["PREPAYMENT_RECEIVED", "EXECUTION_PLANNING", "CLOSED_WON"]:
            prepaid += 1

    total = len(offers)
    scam  = by_status.get("SCAM", 0)
    resp  = by_status.get("RESPONDED", 0)

    lines = [
        f"📊 *Отчёт GTA IRL OS*",
        f"_{datetime.now().strftime('%d.%m.%Y %H:%M')}_",
        f"",
        f"*Офферы:*",
        f"├ Найдено: `{total}`",
        f"├ Скам/скрыто: `{scam + by_status.get('HIDDEN', 0)}`",
        f"├ Откликнулся: `{resp}`",
        f"└ Делегировано: `{by_status.get('DELEGATED', 0)}`",
        f"",
        f"*Сделки:*",
        f"├ Всего: `{len(deals)}`",
        f"├ Ждём ответа: `{by_stage.get('WAITING_REPLY', 0) + by_stage.get('CLIENT_REPLIED', 0)}`",
        f"├ Квалификация: `{by_stage.get('QUALIFYING', 0)}`",
        f"├ КП отправлено: `{by_stage.get('PROPOSAL_SENT', 0)}`",
        f"├ Ждём предоплату: `{by_stage.get('PREPAYMENT_WAITING', 0)}`",
        f"└ 💰 Предоплата получена: `{prepaid}`",
        f"",
        f"*Конверсия:*",
        f"└ Оффер → отклик: `{round(resp/total*100) if total else 0}%`",
    ]
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown")



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
        text = transcribe_audio(audio, purpose="telegram_voice", meta={
            "chat_type": msg.chat.type,
            "user_id": getattr(msg.from_user, "id", None),
        })
        if not text:
            bot.edit_message_text("❌ Не распознал.", msg.chat.id, thinking.message_id)
            return
        reply = ask_ai(
            "Ты ассистент GTA IRL OS Владимира. Отвечай кратко по-русски.",
            text,
            max_tokens=300,
            purpose="telegram_voice_reply",
            meta={"user_id": getattr(msg.from_user, "id", None)},
        ) or text
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
    reply = ask_ai(
        "Ты ассистент GTA IRL OS Владимира. Отвечай кратко по-русски.",
        text,
        max_tokens=500,
        purpose="telegram_text_reply",
        meta={"user_id": getattr(msg.from_user, "id", None), "chat_type": msg.chat.type},
    )
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
        improved = ask_ai(
            "Напиши короткий первый отклик на фриланс-заявку от имени Владимира. "
            "2-3 предложения. Вежливо, по-русски. Уточни актуальность.",
            f"Заявка:\n{deal['offer_text'][:400]}",
            max_tokens=150,
            purpose="improve_first_draft",
            meta={"deal_id": rest},
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
        draft      = deal.get("draft", "")
        username   = deal["contact"].get("username")
        user_id    = deal["contact"].get("user_id")
        target     = username or user_id
        next_stage = deal.get("next_stage")

        bot.answer_callback_query(call.id, "📨 Отправляю...")
        ok, err = send_via_telethon(target, draft)
        if ok:
            add_message(deal, "outgoing", draft)
            # Переходим на следующую стадию если определена
            if next_stage and next_stage != deal.get("stage"):
                try:
                    update_stage(deal, next_stage)
                except:
                    pass
            # Если КП отправлено — переходим к ожиданию предоплаты
            if deal.get("stage") == "PROPOSAL_SENT":
                try:
                    update_stage(deal, "PREPAYMENT_WAITING")
                except:
                    pass
                kb_prepay = make_kb(
                    [("💳 Предоплата получена", f"prepay:{rest}"),
                     ("👻 Клиент пропал",       f"ghost:{rest}")],
                )
                bot.send_message(chat_id,
                    f"📋 КП отправлено! Сделка `{rest}` → ⏳ ждём предоплату.\n\n"
                    f"Когда придёт — нажми кнопку.",
                    parse_mode="Markdown", reply_markup=kb_prepay)
            else:
                bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
                bot.send_message(chat_id, "✅ Отправлено.", parse_mode="Markdown")
        else:
            bot.send_message(chat_id, f"❌ Ошибка: {err}")

    elif action == "open_chat":
        deal = get_deal(rest)
        if not deal:
            bot.answer_callback_query(call.id, "❌ Сделка не найдена")
            return
        contact  = deal.get("contact", {})
        username = contact.get("username")
        user_id  = contact.get("user_id")
        name     = contact.get("name", "?")
        if username:
            link = f"https://t.me/{username}"
        elif user_id:
            link = f"tg://user?id={user_id}"
        else:
            bot.answer_callback_query(call.id, "❌ Нет контакта")
            return
        bot.answer_callback_query(call.id, "Открываю чат...")
        bot.send_message(chat_id,
            f"💬 Переписка с *{name}*\n{link}\n\n"
            f"Сделка `{rest}` · {STAGE_LABELS.get(deal.get('stage',''), '')}",
            parse_mode="Markdown", disable_web_page_preview=False)

    elif action == "prepay":
        deal = get_deal(rest)
        if not deal:
            bot.answer_callback_query(call.id, "❌")
            return
        bot.answer_callback_query(call.id, "💰 Предоплата!")
        try:
            update_stage(deal, "PREPAYMENT_RECEIVED")
        except:
            pass
        deal["prepayment_received_at"] = datetime.now().isoformat()
        save_deal(deal)
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
        bot.send_message(chat_id,
            f"💰 *Предоплата получена!*\nСделка `{rest}` — в работу!\n\n"
            f"Клиент: {deal['contact'].get('name', '?')}\n"
            f"Бюджет: {deal.get('budget', '—')}\n"
            f"Срок: {deal.get('deadline', '—')}",
            parse_mode="Markdown")

    elif action == "ghost":
        deal = get_deal(rest)
        if not deal:
            bot.answer_callback_query(call.id, "❌")
            return
        bot.answer_callback_query(call.id, "👻 Клиент пропал")
        try:
            update_stage(deal, "CLIENT_GHOSTED")
        except:
            pass
        save_deal(deal)
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
        bot.send_message(chat_id, f"👻 Сделка `{rest}` — клиент пропал.")

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
