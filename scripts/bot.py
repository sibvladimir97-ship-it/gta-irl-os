#!/usr/bin/env python3
"""
GTA IRL OS — Telegram Assistant Bot
Фаза 0: Ассистент подключён к файлам OS
"""

import os
import re
import telebot
from datetime import date, datetime

TOKEN = "8980844354:AAFKX_wtKvLx1kgoWaZ6V9i8S48209GqpcM"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURVIVAL = os.path.join(ROOT, "modules", "survival-economy")
TARGET_FILE = os.path.join(SURVIVAL, "target.md")
BRANCHES_FILE = os.path.join(SURVIVAL, "branches.md")
DAILY_DIR = os.path.join(SURVIVAL, "daily")

bot = telebot.TeleBot(TOKEN)


# ── Парсеры ───────────────────────────────────────────────────────────────────

def parse_table_value(text, *fields):
    """Ищет значение по нескольким вариантам названия поля."""
    for field in fields:
        pattern = rf"\|\s*{re.escape(field)}\s*\|\s*(.+?)\s*\|"
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def parse_number(s):
    if s is None:
        return 0
    s = s.replace(",", "").replace("~", "").replace("THB", "").strip()
    m = re.search(r"[\d]+(?:\.\d+)?", s)
    return float(m.group()) if m else 0


def parse_target():
    if not os.path.exists(TARGET_FILE):
        return None
    text = open(TARGET_FILE).read()

    goal     = parse_number(parse_table_value(text, "Goal amount"))
    balance  = parse_number(parse_table_value(text, "Current balance"))
    deadline = parse_table_value(text, "Deadline")
    mode_m   = re.search(r"\*\*Mode:\*\*\s*(\w+)", text)
    mode     = mode_m.group(1).upper() if mode_m else "NORMAL"
    deficit  = goal - balance if goal else 0

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
            obligations.append({
                "name": name, "amount": parse_number(amount),
                "due": due, "type": dtype,
            })

    return {
        "goal": goal, "balance": balance, "deficit": deficit,
        "deadline": deadline, "days_remaining": days_remaining,
        "mode": mode, "obligations": obligations,
    }


def parse_branches():
    if not os.path.exists(BRANCHES_FILE):
        return []
    text = open(BRANCHES_FILE).read()
    branches = []
    sections = re.split(r"^### ", text, flags=re.MULTILINE)
    for section in sections[1:]:
        lines = section.strip().split("\n")
        branch_id = lines[0].strip()
        body = "\n".join(lines[1:])
        status = parse_table_value(body, "Статус", "Status") or "unknown"
        status = re.sub(r"\*+", "", status).strip()
        branches.append({
            "id":              branch_id,
            "name":            parse_table_value(body, "Название", "Name") or branch_id,
            "status":          status,
            "earliest_income": parse_table_value(body, "Ближайший доход", "Earliest income") or "—",
            "blocking":        parse_table_value(body, "Блокеры", "Blocking factors") or "—",
            "next_action":     parse_table_value(body, "Следующий шаг", "Next action") or "—",
            "frozen_reason":   parse_table_value(body, "Причина заморозки", "Frozen reason") or None,
        })
    return branches


def read_today():
    today = date.today().isoformat()
    path = os.path.join(DAILY_DIR, f"{today}.md")
    if os.path.exists(path):
        return open(path).read()
    return None


# ── Сборка сообщений ──────────────────────────────────────────────────────────

def build_status(t):
    if not t:
        return "❌ Файл target.md не найден"

    mode_icon = "🚨" if t["mode"] == "CRISIS" else "🟡"
    mode_text = "КРИЗИС" if t["mode"] == "CRISIS" else "НОРМАЛЬНЫЙ"

    lines = [
        f"{mode_icon} *РЕЖИМ: {mode_text}*",
        f"",
        f"💰 Баланс:    `{t['balance']:,.0f} THB`",
        f"🎯 Цель:      `{t['goal']:,.0f} THB`",
        f"📉 Дефицит:   `{t['deficit']:,.0f} THB`",
    ]

    if t["days_remaining"] is not None:
        dr = t["days_remaining"]
        icon = "🔴" if dr <= 2 else "🟡" if dr <= 7 else "🟢"
        lines.append(f"⏰ Дедлайн:   {t['deadline']}  {icon} {dr} дн.")
        if dr > 0 and t["deficit"] > 0:
            dpd = t["deficit"] / dr
            lines.append(f"📊 Нужно/день: `{dpd:,.0f} THB`")

    if t["obligations"]:
        lines.append("")
        lines.append("*Неоплачено:*")
        for ob in t["obligations"]:
            icon = "🔴" if "hard" in ob["type"].lower() else "🟡"
            lines.append(f"{icon} {ob['name']}: `{ob['amount']:,.0f} THB`  до {ob['due']}")

    return "\n".join(lines)


def build_branches(branches):
    active = [b for b in branches if b["status"].lower() == "active"]
    frozen = [b for b in branches if b["status"].lower() == "frozen"]
    lines = []

    if active:
        lines.append("*🟢 АКТИВНЫЕ*")
        for b in active:
            lines.append(f"")
            lines.append(f"● *{b['name']}*")
            lines.append(f"  Шаг: {b['next_action']}")
            lines.append(f"  Доход: {b['earliest_income']}")
            if b["blocking"] and b["blocking"] != "—":
                lines.append(f"  ⚠️ Блокер: {b['blocking']}")

    if frozen:
        lines.append("")
        lines.append("*⚫ ЗАМОРОЖЕНЫ*")
        for b in frozen:
            reason = b["frozen_reason"] or "нет причины"
            lines.append(f"○ {b['name']} — _{reason}_")

    return "\n".join(lines) if lines else "Ветки не найдены"


def build_collapse(t, branches):
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    active = [b for b in branches if b["status"].lower() == "active"]

    lines = [
        f"*🧠 GTA IRL OS — Контекст*",
        f"_{today}  {now}_",
        f"",
        build_status(t),
        f"",
        f"─────────────────────",
        f"",
        build_branches(branches),
        f"",
        f"─────────────────────",
        f"",
    ]

    if t:
        dr = t.get("days_remaining", 99)
        deficit = t.get("deficit", 0)
        if dr is not None and dr <= 2 and deficit > 0:
            dpd = deficit / max(dr, 1)
            lines.append(f"💡 *Инсайт:* 48 часов. Нужно `{dpd:,.0f} THB/день`. Каждый час на счету.")
        elif not active:
            lines.append("💡 *Инсайт:* Нет активных веток. Добавь хотя бы одну.")
        else:
            lines.append("💡 *Инсайт:* Система в норме. Выполняй и обновляй вечером.")

    return "\n".join(lines)


# ── Хендлеры ─────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(msg):
    text = (
        "👋 *GTA IRL OS — Ассистент*\n\n"
        "Я подключён к твоей операционной системе.\n\n"
        "*Команды:*\n"
        "/status — баланс и дефицит\n"
        "/branches — активные и замороженные ветки\n"
        "/collapse — полный контекст системы\n"
        "/today — дневной фокус на сегодня\n"
        "/help — эта справка"
    )
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")


@bot.message_handler(commands=["help"])
def cmd_help(msg):
    cmd_start(msg)


@bot.message_handler(commands=["status"])
def cmd_status(msg):
    t = parse_target()
    bot.send_message(msg.chat.id, build_status(t), parse_mode="Markdown")


@bot.message_handler(commands=["branches"])
def cmd_branches(msg):
    branches = parse_branches()
    bot.send_message(msg.chat.id, build_branches(branches), parse_mode="Markdown")


@bot.message_handler(commands=["collapse"])
def cmd_collapse(msg):
    t = parse_target()
    branches = parse_branches()
    bot.send_message(msg.chat.id, build_collapse(t, branches), parse_mode="Markdown")


@bot.message_handler(commands=["today"])
def cmd_today(msg):
    content = read_today()
    if not content:
        today = date.today().isoformat()
        bot.send_message(
            msg.chat.id,
            f"Файл за {today} ещё не создан.\nЗапусти: `python3 scripts/daily_cycle.py`",
            parse_mode="Markdown"
        )
        return
    if len(content) > 4000:
        content = content[:4000] + "\n\n_...обрезано_"
    bot.send_message(msg.chat.id, f"```\n{content}\n```", parse_mode="Markdown")


@bot.message_handler(func=lambda m: True)
def handle_text(msg):
    text = msg.text.strip().lower()
    if any(w in text for w in ["статус", "деньги", "дефицит", "баланс", "status"]):
        cmd_status(msg)
    elif any(w in text for w in ["ветк", "branch", "dani", "даня", "проект"]):
        cmd_branches(msg)
    elif any(w in text for w in ["коллапс", "контекст", "collapse", "приоритет", "система"]):
        cmd_collapse(msg)
    elif any(w in text for w in ["сегодня", "фокус", "today", "задач"]):
        cmd_today(msg)
    else:
        bot.send_message(
            msg.chat.id,
            "Попробуй: /collapse /status /branches /today"
        )


# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"GTA IRL OS Bot запущен — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("Слушаю сообщения...")
    bot.infinity_polling()
