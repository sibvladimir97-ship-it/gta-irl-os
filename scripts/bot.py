#!/usr/bin/env python3
"""
GTA IRL OS — Telegram Assistant Bot
Фаза 0: Ассистент с Claude AI + подключение к файлам OS
"""

import os
import re
import anthropic
import telebot
from datetime import date, datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURVIVAL = os.path.join(ROOT, "modules", "survival-economy")
TARGET_FILE   = os.path.join(SURVIVAL, "target.md")
BRANCHES_FILE = os.path.join(SURVIVAL, "branches.md")
DAILY_DIR     = os.path.join(SURVIVAL, "daily")

bot    = telebot.TeleBot(TELEGRAM_TOKEN)
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# История диалога на пользователя (в памяти, сбрасывается при перезапуске)
chat_history = {}


# ── Чтение файлов системы ─────────────────────────────────────────────────────

def read_file(path):
    if os.path.exists(path):
        return open(path).read()
    return ""

def read_today():
    path = os.path.join(DAILY_DIR, f"{date.today().isoformat()}.md")
    return read_file(path)

def build_system_context():
    """Собирает весь контекст GTA IRL OS для Claude."""
    target   = read_file(TARGET_FILE)
    branches = read_file(BRANCHES_FILE)
    today    = read_today()
    now      = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""Ты — персональный ассистент GTA IRL OS, операционной системы жизни Владимира.

Текущее время: {now}

Ты знаешь всё о системе и помогаешь Владимиру принимать решения, фокусироваться и двигаться вперёд.
Отвечай на русском языке. Будь конкретным, кратким и честным.
Если видишь проблему — говори прямо. Не льсти и не уклоняйся.

═══════════════════════════════
ТЕКУЩАЯ ФИНАНСОВАЯ ЦЕЛЬ (target.md):
═══════════════════════════════
{target}

═══════════════════════════════
ДЕНЕЖНЫЕ ВЕТКИ (branches.md):
═══════════════════════════════
{branches}

═══════════════════════════════
ДНЕВНОЙ ФОКУС СЕГОДНЯ:
═══════════════════════════════
{today if today else "Дневной файл ещё не создан. Запустить: python3 scripts/daily_cycle.py"}

═══════════════════════════════
КАК РАБОТАЕТ GTA IRL OS:
═══════════════════════════════
Цикл: Collect → Classify → Update → Analyze → Prioritize → Collapse → Decide → Execute → Learn
Принципы:
- Crisis Mode: дефицит > 80% и < 3 дней → только 1 активная ветка
- Decide всегда принимает человек
- Каждый модуль = одна ответственность
- Система помогает видеть ясно, не решает вместо тебя
"""


# ── Парсеры для команд ────────────────────────────────────────────────────────

def parse_table_value(text, *fields):
    for field in fields:
        pattern = rf"\|\s*{re.escape(field)}\s*\|\s*(.+?)\s*\|"
        m = re.search(pattern, text, re.IGNORECASE)
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
            dl = date.fromisoformat(clean)
            days_remaining = (dl - date.today()).days
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
        bid  = lines[0].strip()
        body = "\n".join(lines[1:])
        status = re.sub(r"\*+", "", parse_table_value(body, "Статус", "Status") or "unknown").strip()
        branches.append({
            "id":            bid,
            "name":          parse_table_value(body, "Название", "Name") or bid,
            "status":        status,
            "earliest_income": parse_table_value(body, "Ближайший доход", "Earliest income") or "—",
            "blocking":      parse_table_value(body, "Блокеры", "Blocking factors") or "—",
            "next_action":   parse_table_value(body, "Следующий шаг", "Next action") or "—",
            "frozen_reason": parse_table_value(body, "Причина заморозки", "Frozen reason") or None,
        })
    return branches


# ── Форматирование команд ─────────────────────────────────────────────────────

def fmt_status(t):
    if not t:
        return "❌ target.md не найден"
    mode_text = "КРИЗИС 🚨" if t["mode"] == "CRISIS" else "НОРМАЛЬНЫЙ 🟡"
    lines = [
        f"*Режим: {mode_text}*", "",
        f"💰 Баланс:    `{t['balance']:,.0f} THB`",
        f"🎯 Цель:      `{t['goal']:,.0f} THB`",
        f"📉 Дефицит:   `{t['deficit']:,.0f} THB`",
    ]
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
        insight = f"💡 *Инсайт:* 48 часов. Нужно `{deficit/max(dr,1):,.0f} THB/день`. Каждый час на счету."
    elif not active:
        insight = "💡 *Инсайт:* Нет активных веток. Добавь хотя бы одну."
    else:
        insight = "💡 *Инсайт:* Система в норме. Выполняй и обновляй вечером."

    return "\n".join([
        f"*🧠 GTA IRL OS — Контекст*",
        f"_{today}  {now}_", "",
        fmt_status(t), "",
        "─────────────────────", "",
        fmt_branches(branches), "",
        "─────────────────────", "",
        insight,
    ])


# ── Claude AI ─────────────────────────────────────────────────────────────────

def ask_claude(user_id, user_message):
    """Отправляет сообщение Claude с контекстом системы и историей диалога."""
    if user_id not in chat_history:
        chat_history[user_id] = []

    chat_history[user_id].append({"role": "user", "content": user_message})

    # Ограничиваем историю последними 20 сообщениями
    history = chat_history[user_id][-20:]

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=build_system_context(),
        messages=history,
    )

    reply = response.content[0].text
    chat_history[user_id].append({"role": "assistant", "content": reply})

    return reply


# ── Хендлеры ─────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(msg):
    bot.send_message(msg.chat.id,
        "👋 *GTA IRL OS — Ассистент*\n\n"
        "Я подключён к твоей операционной системе и знаю Claude AI.\n\n"
        "*Команды:*\n"
        "/collapse — полный контекст системы\n"
        "/status — баланс и дефицит\n"
        "/branches — активные ветки\n"
        "/today — дневной фокус\n"
        "/reset — сбросить историю диалога\n\n"
        "Или просто напиши что угодно — отвечу с пониманием контекста системы.",
        parse_mode="Markdown")

@bot.message_handler(commands=["help"])
def cmd_help(msg):
    cmd_start(msg)

@bot.message_handler(commands=["reset"])
def cmd_reset(msg):
    chat_history.pop(msg.from_user.id, None)
    bot.send_message(msg.chat.id, "✅ История диалога сброшена.")

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
            f"Файл за {date.today().isoformat()} ещё не создан.\n"
            "Запусти: `python3 scripts/daily_cycle.py`", parse_mode="Markdown")
        return
    if len(content) > 4000:
        content = content[:4000] + "\n\n_...обрезано_"
    bot.send_message(msg.chat.id, f"```\n{content}\n```", parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def handle_text(msg):
    uid  = msg.from_user.id
    text = msg.text.strip()

    # Показываем что думаем
    thinking = bot.send_message(msg.chat.id, "⏳")

    try:
        reply = ask_claude(uid, text)
        bot.edit_message_text(reply, msg.chat.id, thinking.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", msg.chat.id, thinking.message_id)


# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"GTA IRL OS Bot + Claude запущен — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("Слушаю сообщения...")
    bot.infinity_polling()
