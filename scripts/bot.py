#!/usr/bin/env python3
"""
GTA IRL OS — Telegram Assistant Bot
Groq AI (llama-3.3-70b) + Whisper (голосовые) + файлы OS
В группах: отвечает только на @упоминания и реплаи на свои сообщения
"""

import os
import re
import requests
import telebot
from datetime import date, datetime

# Импортируем воронку
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from offer_store import get_offer, update_offer
from negotiator import create_deal, draft_first_message, update_stage, add_message, format_deal_card, get_deal, save_deal

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL     = "llama-3.3-70b-versatile"
GROQ_URL       = "https://api.groq.com/openai/v1/chat/completions"
WHISPER_URL    = "https://api.groq.com/openai/v1/audio/transcriptions"
BOT_USERNAME   = "gta_irl_assistant_bot"

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURVIVAL = os.path.join(ROOT, "modules", "survival-economy")
TARGET_FILE   = os.path.join(SURVIVAL, "target.md")
BRANCHES_FILE = os.path.join(SURVIVAL, "branches.md")
DAILY_DIR     = os.path.join(SURVIVAL, "daily")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
chat_history = {}


# ── Проверка: нужно ли отвечать ──────────────────────────────────────────────

def should_respond(msg):
    """В личке — всегда. В группе — только @упоминание или реплай на бота."""
    # Личка
    if msg.chat.type == "private":
        return True, msg.text or ""

    # Группа — реплай на сообщение бота
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if msg.reply_to_message.from_user.username == BOT_USERNAME:
            text = msg.text or ""
            return True, text

    # Группа — упоминание @username
    mention = f"@{BOT_USERNAME}"
    text = msg.text or msg.caption or ""
    if mention.lower() in text.lower():
        clean = text.replace(mention, "").strip()
        return True, clean

    return False, ""


def should_respond_voice(msg):
    """Голосовые в группе — только реплай на бота."""
    if msg.chat.type == "private":
        return True
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if msg.reply_to_message.from_user.username == BOT_USERNAME:
            return True
    return False


# ── Файлы системы ─────────────────────────────────────────────────────────────

def read_file(path):
    return open(path).read() if os.path.exists(path) else ""

def read_today():
    path = os.path.join(DAILY_DIR, f"{date.today().isoformat()}.md")
    return read_file(path)

def build_system_context():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""Ты — персональный ассистент GTA IRL OS, операционной системы жизни Владимира.
Текущее время: {now}

Отвечай на русском языке. Будь конкретным и честным.
Если пользователь говорит голосом — отвечай естественно, как в разговоре.

═══ ФИНАНСОВАЯ ЦЕЛЬ ═══
{read_file(TARGET_FILE)}

═══ ДЕНЕЖНЫЕ ВЕТКИ ═══
{read_file(BRANCHES_FILE)}

═══ ДНЕВНОЙ ФОКУС ═══
{read_today() or "Файл за сегодня ещё не создан."}

═══ СИСТЕМА ═══
Цикл: Collect → Classify → Update → Analyze → Prioritize → Collapse → Decide → Execute → Learn
Crisis Mode: дефицит >80% и <3 дней → только 1 активная ветка. Decide всегда принимает человек.
"""


# ── Парсеры ───────────────────────────────────────────────────────────────────

def parse_table_value(text, *fields):
    for field in fields:
        m = re.search(rf"\|\s*{re.escape(field)}\s*\|\s*(.+?)\s*\|", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None

def parse_number(s):
    if not s:
        return 0
    s = s.replace(",", "").replace("~", "").replace("THB", "").strip()
    m = re.search(r"[\d]+(?:\.\d+)?", s)
    return float(m.group()) if m else 0

def parse_target():
    text = read_file(TARGET_FILE)
    if not text:
        return None
    goal    = parse_number(parse_table_value(text, "Goal amount"))
    balance = parse_number(parse_table_value(text, "Current balance"))
    deadline = parse_table_value(text, "Deadline")
    mode_m  = re.search(r"\*\*Mode:\*\*\s*(\w+)", text)
    mode    = mode_m.group(1).upper() if mode_m else "NORMAL"
    deficit = goal - balance if goal else 0
    days_remaining = None
    if deadline:
        clean = re.sub(r"\s*\(.*?\)", "", deadline).strip()
        try:
            days_remaining = (date.fromisoformat(clean) - date.today()).days
        except ValueError:
            pass
    obligations = []
    for row in re.finditer(
        r"\|\s*([^|]+?)\s*\|\s*([\d,~]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(yes|no)\s*\|",
        text, re.IGNORECASE
    ):
        name, amount, due, dtype, layer, paid = [g.strip() for g in row.groups()]
        if paid.lower() == "no":
            obligations.append({"name": name, "amount": parse_number(amount), "due": due, "type": dtype})
    return {"goal": goal, "balance": balance, "deficit": deficit,
            "deadline": deadline, "days_remaining": days_remaining,
            "mode": mode, "obligations": obligations}

def parse_branches():
    text = read_file(BRANCHES_FILE)
    if not text:
        return []
    branches = []
    for section in re.split(r"^### ", text, flags=re.MULTILINE)[1:]:
        lines = section.strip().split("\n")
        body  = "\n".join(lines[1:])
        status = re.sub(r"\*+", "", parse_table_value(body, "Статус", "Status") or "unknown").strip()
        branches.append({
            "id":            lines[0].strip(),
            "name":          parse_table_value(body, "Название", "Name") or lines[0].strip(),
            "status":        status,
            "earliest_income": parse_table_value(body, "Ближайший доход", "Earliest income") or "—",
            "blocking":      parse_table_value(body, "Блокеры", "Blocking factors") or "—",
            "next_action":   parse_table_value(body, "Следующий шаг", "Next action") or "—",
            "frozen_reason": parse_table_value(body, "Причина заморозки", "Frozen reason") or None,
        })
    return branches


# ── Форматирование ────────────────────────────────────────────────────────────

def fmt_status(t):
    if not t:
        return "❌ target.md не найден"
    mode_text = "КРИЗИС 🚨" if t["mode"] == "CRISIS" else "НОРМАЛЬНЫЙ 🟡"
    lines = [f"*Режим: {mode_text}*", "",
             f"💰 Баланс:    `{t['balance']:,.0f} THB`",
             f"🎯 Цель:      `{t['goal']:,.0f} THB`",
             f"📉 Дефицит:   `{t['deficit']:,.0f} THB`"]
    if t["days_remaining"] is not None:
        dr = t["days_remaining"]
        icon = "🔴" if dr <= 2 else "🟡" if dr <= 7 else "🟢"
        lines.append(f"⏰ Дедлайн:   {t['deadline']}  {icon} {dr} дн.")
        if dr > 0 and t["deficit"] > 0:
            lines.append(f"📊 Нужно/день: `{t['deficit']/dr:,.0f} THB`")
    if t["obligations"]:
        lines += ["", "*Неоплачено:*"]
        for ob in t["obligations"]:
            icon = "🔴" if "hard" in ob["type"].lower() else "🟡"
            lines.append(f"{icon} {ob['name']}: `{ob['amount']:,.0f} THB`  до {ob['due']}")
    return "\n".join(lines)

def fmt_branches(branches):
    active = [b for b in branches if b["status"].lower() == "active"]
    frozen = [b for b in branches if b["status"].lower() == "frozen"]
    lines = []
    if active:
        lines.append("*🟢 АКТИВНЫЕ*")
        for b in active:
            lines += ["", f"● *{b['name']}*",
                      f"  Шаг: {b['next_action']}",
                      f"  Доход: {b['earliest_income']}"]
            if b["blocking"] != "—":
                lines.append(f"  ⚠️ {b['blocking']}")
    if frozen:
        lines += ["", "*⚫ ЗАМОРОЖЕНЫ*"]
        for b in frozen:
            lines.append(f"○ {b['name']} — _{b['frozen_reason'] or '—'}_")
    return "\n".join(lines) or "Ветки не найдены"

def fmt_collapse(t, branches):
    today = date.today().isoformat()
    now   = datetime.now().strftime("%H:%M")
    active = [b for b in branches if b["status"].lower() == "active"]
    dr = t.get("days_remaining", 99) if t else 99
    deficit = t.get("deficit", 0) if t else 0
    if t and dr is not None and dr <= 2 and deficit > 0:
        insight = f"💡 *Инсайт:* 48 часов. Нужно `{deficit/max(dr,1):,.0f} THB/день`."
    elif not active:
        insight = "💡 *Инсайт:* Нет активных веток."
    else:
        insight = "💡 *Инсайт:* Система в норме. Выполняй и обновляй вечером."
    return "\n".join([f"*🧠 GTA IRL OS — Контекст*", f"_{today}  {now}_", "",
                      fmt_status(t), "", "─────────────────────", "",
                      fmt_branches(branches), "", "─────────────────────", "", insight])


# ── Whisper ───────────────────────────────────────────────────────────────────

def transcribe_voice(file_id):
    file_info = bot.get_file(file_id)
    file_url  = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
    audio_data = requests.get(file_url).content
    r = requests.post(
        WHISPER_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        files={"file": ("voice.ogg", audio_data, "audio/ogg")},
        data={"model": "whisper-large-v3-turbo", "language": "ru"},
        timeout=30
    )
    r.raise_for_status()
    return r.json().get("text", "").strip()


# ── Groq AI ───────────────────────────────────────────────────────────────────

def ask_groq(user_id, user_message):
    if user_id not in chat_history:
        chat_history[user_id] = []
    chat_history[user_id].append({"role": "user", "content": user_message})
    history = chat_history[user_id][-20:]
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": GROQ_MODEL,
                  "messages": [{"role": "system", "content": build_system_context()}] + history,
                  "max_tokens": 1024},
            timeout=30)
        if r.status_code == 429:
            return "⏳ Слишком много запросов, подожди 10 секунд и повтори."
        r.raise_for_status()
        reply = r.json()["choices"][0]["message"]["content"]
        chat_history[user_id].append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        return f"❌ Ошибка AI: {e}"


# ── Хендлеры ─────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "help"])
def cmd_start(msg):
    bot.send_message(msg.chat.id,
        "👋 *GTA IRL OS — Ассистент*\n\n"
        "В группе: упомяни меня `@gta_irl_assistant_bot` или ответь на моё сообщение.\n"
        "Понимаю текст и голосовые 🎤\n\n"
        "/collapse — полный контекст\n"
        "/status — баланс и дефицит\n"
        "/branches — ветки\n"
        "/today — дневной фокус\n"
        "/reset — сбросить историю",
        parse_mode="Markdown")

@bot.message_handler(commands=["reset"])
def cmd_reset(msg):
    chat_history.pop(msg.from_user.id, None)
    bot.send_message(msg.chat.id, "✅ История сброшена.")

@bot.message_handler(commands=["стоп", "stop"])
def cmd_stop_parser(msg):
    stop_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", ".parser_stop")
    try:
        open(stop_file, 'w').close()
        bot.send_message(msg.chat.id, "⏹ Команда отправлена. Парсер остановится через несколько секунд.")
    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(commands=["status"])
def cmd_status(msg):
    bot.send_message(msg.chat.id, fmt_status(parse_target()), parse_mode="Markdown")

@bot.message_handler(commands=["branches"])
def cmd_branches(msg):
    bot.send_message(msg.chat.id, fmt_branches(parse_branches()), parse_mode="Markdown")

@bot.message_handler(commands=["collapse"])
def cmd_collapse(msg):
    bot.send_message(msg.chat.id, fmt_collapse(parse_target(), parse_branches()), parse_mode="Markdown")

@bot.message_handler(commands=["today"])
def cmd_today(msg):
    content = read_today()
    if not content:
        bot.send_message(msg.chat.id,
            f"Файл за {date.today().isoformat()} не создан.\n"
            "`python3 scripts/daily_cycle.py`", parse_mode="Markdown")
        return
    if len(content) > 4000:
        content = content[:4000] + "\n_...обрезано_"
    bot.send_message(msg.chat.id, f"```\n{content}\n```", parse_mode="Markdown")


@bot.message_handler(content_types=["voice"])
def handle_voice(msg):
    if not should_respond_voice(msg):
        return
    thinking = bot.send_message(msg.chat.id, "🎤 Слушаю...", reply_to_message_id=msg.message_id)
    try:
        text = transcribe_voice(msg.voice.file_id)
        if not text:
            bot.edit_message_text("❌ Не смог распознать.", msg.chat.id, thinking.message_id)
            return
        bot.edit_message_text(f"🎤 _{text}_\n\n⏳", msg.chat.id, thinking.message_id, parse_mode="Markdown")
        reply = ask_groq(msg.from_user.id, text)
        bot.edit_message_text(f"🎤 _{text}_\n\n{reply}", msg.chat.id, thinking.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", msg.chat.id, thinking.message_id)


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(msg):
    respond, clean_text = should_respond(msg)
    if not respond:
        return
    if not clean_text:
        clean_text = "что ты можешь делать?"

    thinking = bot.send_message(msg.chat.id, "⏳", reply_to_message_id=msg.message_id)
    try:
        reply = ask_groq(msg.from_user.id, clean_text)
        bot.edit_message_text(reply, msg.chat.id, thinking.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", msg.chat.id, thinking.message_id)


# ── Inline кнопки воронки ────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    data = call.data
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    try:
        action, offer_id = data.split(":", 1)
    except:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return

    offer = get_offer(offer_id)
    if not offer:
        bot.answer_callback_query(call.id, "❌ Оффер не найден")
        return

    if action == "scam":
        update_offer(offer_id, status="SCAM")
        bot.answer_callback_query(call.id, "🚫 Помечен как скам")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
        bot.send_message(chat_id, f"🚫 Оффер `{offer_id}` помечен как *СКАМ*", parse_mode="Markdown")

    elif action == "hide":
        update_offer(offer_id, status="HIDDEN")
        bot.answer_callback_query(call.id, "👁 Скрыто")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)

    elif action == "delegate":
        update_offer(offer_id, status="DELEGATED")
        bot.answer_callback_query(call.id, "📤 Отмечено для делегирования")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
        bot.send_message(chat_id, f"📤 Оффер `{offer_id}` — *в делегирование*", parse_mode="Markdown")

    elif action == "respond":
        # Создаём сделку и генерируем черновик
        bot.answer_callback_query(call.id, "⏳ Генерирую черновик...")
        deal = create_deal(offer)
        update_offer(offer_id, status="RESPONDED", deal_id=deal["deal_id"])
        update_stage(deal, "FIRST_MESSAGE_DRAFTED")

        draft = draft_first_message(deal)

        # Кнопки подтверждения
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Отправить", "callback_data": f"send_draft:{deal['deal_id']}:{offer_id}"},
                {"text": "✏️ Редактировать", "callback_data": f"edit_draft:{deal['deal_id']}"},
            ], [
                {"text": "❌ Отменить", "callback_data": f"cancel_draft:{deal['deal_id']}"},
            ]]
        }

        # Сохраняем черновик в сделку
        deal["draft"] = draft
        save_deal(deal)

        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
        bot.send_message(
            chat_id,
            f"✏️ *Черновик отклика* (сделка `{deal['deal_id']}`)\n\n_{draft}_\n\nОтправить?",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

    elif action == "send_draft":
        parts = offer_id.split(":", 1)
        deal_id = parts[0]
        real_offer_id = parts[1] if len(parts) > 1 else None

        deal = get_deal(deal_id)
        if not deal:
            bot.answer_callback_query(call.id, "❌ Сделка не найдена")
            return

        draft = deal.get("draft", "")
        contact_url = deal["contact"].get("contact_url", "")
        username = deal["contact"].get("username")

        bot.answer_callback_query(call.id, "📨 Отправляю...")

        # Отправляем через Telethon (через скрипт)
        try:
            import subprocess
            script = f"""
import asyncio
from telethon import TelegramClient
import os
async def send():
    client = TelegramClient('scripts/parser_session',
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'))
    await client.start()
    target = '{username}' if '{username}' != 'None' else int({deal['contact'].get('user_id', 0)})
    await client.send_message(target, '''{draft}''')
    await client.disconnect()
asyncio.run(send())
"""
            result = subprocess.run(
                ["python3", "-c", script],
                capture_output=True, text=True, timeout=20,
                env={**os.environ, "TELEGRAM_API_ID": os.getenv("TELEGRAM_API_ID", ""),
                     "TELEGRAM_API_HASH": os.getenv("TELEGRAM_API_HASH", "")}
            )
            if result.returncode == 0:
                update_stage(deal, "FIRST_MESSAGE_SENT")
                add_message(deal, "outgoing", draft)
                bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
                bot.send_message(chat_id,
                    f"✅ *Отклик отправлен!*\nСделка `{deal_id}` → стадия: 📨 Отправлено\n\nЖдём ответа...",
                    parse_mode="Markdown")
            else:
                bot.send_message(chat_id, f"❌ Ошибка отправки: {result.stderr[:200]}")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка: {e}")

    elif action == "send_reply":
        deal_id = offer_id  # здесь offer_id = deal_id
        deal = get_deal(deal_id)
        if not deal:
            bot.answer_callback_query(call.id, "❌ Сделка не найдена")
            return

        draft = deal.get("draft", "")
        username = deal["contact"].get("username")
        user_id  = deal["contact"].get("user_id")

        bot.answer_callback_query(call.id, "📨 Отправляю...")

        try:
            import subprocess
            target = f"'{username}'" if username else str(user_id or 0)
            script = f"""
import asyncio, os
from telethon import TelegramClient
async def send():
    c = TelegramClient('scripts/parser_session',
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'))
    await c.start()
    await c.send_message({target}, '''{draft}''')
    await c.disconnect()
asyncio.run(send())
"""
            result = subprocess.run(
                ["python3", "-c", script],
                capture_output=True, text=True, timeout=20,
                env={**os.environ,
                     "TELEGRAM_API_ID":   os.getenv("TELEGRAM_API_ID", ""),
                     "TELEGRAM_API_HASH": os.getenv("TELEGRAM_API_HASH", "")}
            )
            if result.returncode == 0:
                add_message(deal, "outgoing", draft)
                bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
                bot.send_message(chat_id,
                    f"✅ *Отправлено!*\nСделка `{deal_id}`",
                    parse_mode="Markdown")
            else:
                bot.send_message(chat_id, f"❌ {result.stderr[:200]}")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка: {e}")

    elif action == "skip_reply":
        bot.answer_callback_query(call.id, "⏭ Пропущено")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)


# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"GTA IRL OS Bot запущен — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Username: @{BOT_USERNAME}")
    print("Группа: отвечает только на @упоминания и реплаи")
    print("Слушаю...")
    bot.infinity_polling()
