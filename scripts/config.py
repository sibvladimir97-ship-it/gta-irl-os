"""
GTA IRL OS — runtime configuration.

This module centralizes environment variables and operational limits.
It intentionally does not print secrets and does not read or write .env.
"""

import os


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SESSION_FILE = os.path.join(ROOT, "scripts", "parser_session")
STOP_FILE = os.path.join(ROOT, "scripts", ".parser_stop")
LAST_MSG_IDS_FILE = os.path.join(ROOT, "data", "last_msg_ids.json")

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GROQ_KEY = os.getenv("GROQ_API_KEY", "")
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
BOT_USERNAME = os.getenv("BOT_USERNAME", "gta_irl_assistant_bot")

MONITOR_CHATS = [
    chat.strip()
    for chat in os.getenv("MONITOR_CHATS", "mari_vakansii,freelansim_ru").split(",")
    if chat.strip()
]

OFFER_KEYWORDS = [
    "ищу разработчика", "нужен разработчик", "нужен программист",
    "автоматизация", "бот телеграм", "нужен бот", "telegram bot",
    "парсер", "python", "ai агент", "ai agent", "чат-бот",
    "ищу исполнителя", "нужен исполнитель", "срочно нужен",
    "youtube", "ютуб", "монтаж", "#ищу", "готов заплатить",
]

OFFER_EXCLUDE = [
    "#помогу", "#предлагаю", "#услуги", "#выполню", "#портфолио",
    "#резюме", "#ищуработу", "предлагаю свои услуги", "мои услуги",
    "принимаю заказы", "страховой взнос", "залог",
]

# Telegram safety defaults.
SEND_RATE_LIMIT_SECONDS = int(os.getenv("SEND_RATE_LIMIT_SECONDS", "15"))
HISTORY_SCAN_LIMIT = int(os.getenv("HISTORY_SCAN_LIMIT", "100"))
HISTORY_SCAN_HOURS = int(os.getenv("HISTORY_SCAN_HOURS", "24"))
HISTORY_SCAN_DELAY_SECONDS = float(os.getenv("HISTORY_SCAN_DELAY_SECONDS", "1.0"))
SEND_QUEUE_POLL_SECONDS = float(os.getenv("SEND_QUEUE_POLL_SECONDS", "0.5"))


def missing_required_env():
    """Return missing env names required for the integrated Telegram runtime."""
    required = {
        "TELEGRAM_TOKEN": BOT_TOKEN,
        "TELEGRAM_API_ID": TELEGRAM_API_ID,
        "TELEGRAM_API_HASH": TELEGRAM_API_HASH,
    }
    return [name for name, value in required.items() if not value]
