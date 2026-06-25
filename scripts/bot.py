#!/usr/bin/env python3
"""
GTA IRL OS — Telegram Assistant Bot
Groq AI (llama-3.3-70b) + Whisper (голосовые) + файлы OS
"""

import os
import re
import requests
import telebot
from datetime import date, datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL     = "llama-3.3-70b-versatile"
GROQ_URL       = "https://api.groq.com/openai/v1/chat/completions"
WHISPER_URL    = "https://api.groq.com/openai/v1/audio/transcriptions"

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURVIVAL = os.path.join(ROOT, "modules", "survival-economy")
TARGET_FILE   = os.path.join(SURVIVAL, "target.md")
BRANCHES_FILE = os.path.join(SURVIVAL, "branches.md")
DAILY_DIR     = os.path.join(SURVIVAL, "daily")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
chat_history = {}


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

Отвечай на русском языке. Будь конкретным и честным. Если видишь проблему — говори прямо.
Если пользователь говорит голосом — отвечай так же естественно, как в разговоре.

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


# ── Whisper — транскрипция голосовых ─────────────────────────────────────────

def transcribe_voice(file_id):
    """Скачивает голосовое из Telegram и транскрибирует через Groq Whisper."""
    # Получаем путь к файлу
    file_info = bot.get_file(file_id)
    file_url  = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"

    # Скачиваем
    audio_data = requests.get(file_url).content

    # Отправляем в Whisper
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
    r = requests.post(GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": GROQ_MODEL,
              "messages": [{"role": "system", "content": build_system_context()}] + history,
              "max_tokens": 1024},
        timeout=30)
    r.raise_for_status()
    reply = r.json()["choices"][0]["message"]["content"]
    chat_history[user_id].append({"role": "assistant", "content": reply})
    return reply


# ── Хендлеры ─────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "help"])
def cmd_start(msg):
    bot.send_message(msg.chat.id,
        "👋 *GTA IRL OS — Ассистент*\n\n"
        "Подключён к твоей OS. Понимаю текст и голосовые 🎤\n\n"
        "/collapse — полный контекст\n"
        "/status — баланс и дефицит\n"
        "/branches — ветки\n"
        "/today — дневной фокус\n"
        "/reset — сбросить историю\n\n"
        "Или просто пиши / говори голосом.",
        parse_mode="Markdown")

@bot.message_handler(commands=["reset"])
def cmd_reset(msg):
    chat_history.pop(msg.from_user.id, None)
    bot.send_message(msg.chat.id, "✅ История сброшена.")

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


# ── Голосовые сообщения ───────────────────────────────────────────────────────

@bot.message_handler(content_types=["voice"])
def handle_voice(msg):
    thinking = bot.send_message(msg.chat.id, "🎤 Слушаю...")
    try:
        text = transcribe_voice(msg.voice.file_id)
        if not text:
            bot.edit_message_text("❌ Не смог распознать голос.", msg.chat.id, thinking.message_id)
            return
        # Показываем что распознали
        bot.edit_message_text(f"🎤 _{text}_\n\n⏳", msg.chat.id, thinking.message_id, parse_mode="Markdown")
        # Отвечаем через AI
        reply = ask_groq(msg.from_user.id, text)
        bot.edit_message_text(f"🎤 _{text}_\n\n{reply}", msg.chat.id, thinking.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", msg.chat.id, thinking.message_id)


# ── Текстовые сообщения ───────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: True)
def handle_text(msg):
    thinking = bot.send_message(msg.chat.id, "⏳")
    try:
        reply = ask_groq(msg.from_user.id, msg.text.strip())
        bot.edit_message_text(reply, msg.chat.id, thinking.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", msg.chat.id, thinking.message_id)


# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"GTA IRL OS Bot запущен — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("Текст + голосовые через Groq Whisper")
    print("Слушаю...")
    bot.infinity_polling()
