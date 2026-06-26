"""
GTA IRL OS — Offer Scoring

Локальная оценка заявок без платных API:
- антискам;
- примерный бюджет;
- сложность;
- релевантность навыкам Владимира;
- рекомендация: брать / уточнить / не брать.
"""

import re


SKILL_KEYWORDS = {
    "telegram": ["telegram", "телеграм", "бот", "чат-бот", "бота", "боты"],
    "python": ["python", "питон", "парсер", "скрипт", "автоматизация", "api"],
    "ai": ["ai", "ии", "нейросеть", "gpt", "llm", "агент", "ассистент"],
    "video": ["монтаж", "видео", "youtube", "ютуб", "shorts", "reels"],
}


SCAM_MARKERS = [
    "страховой взнос",
    "гарантийный взнос",
    "залог",
    "внести взнос",
    "оплатить страховку",
    "оплатить доступ",
    "регистрационный взнос",
    "предоплата от исполнителя",
    "карта для выплаты",
    "паспортные данные",
    "без опыта от 100000",
    "переписать текст",
    "набор текста",
    "скан",
]


LOW_VALUE_MARKERS = [
    "модератор",
    "оператор",
    "менеджер по продажам",
    "диагност",
    "копирайтер",
    "рерайт",
    "анкета",
    "заполните форму",
]


URGENT_MARKERS = ["срочно", "сегодня", "до завтра", "горит", "asap"]


def _lower(text):
    return (text or "").lower()


def matched_skills(text):
    t = _lower(text)
    skills = []
    for skill, words in SKILL_KEYWORDS.items():
        if any(word in t for word in words):
            skills.append(skill)
    return skills


def risk_markers(text):
    t = _lower(text)
    return [marker for marker in SCAM_MARKERS if marker in t]


def extract_budget(text):
    """Return human-readable budget found in offer text."""
    patterns = [
        r"(?:бюджет|оплата|стоимость|фикс)\s*[:—-]?\s*(от\s*)?([\d\s]{2,9})\s*(₽|руб|р|thb|usd|\$)",
        r"(от\s*)?([\d\s]{2,9})\s*(₽|руб|р|thb|usd|\$)\s*(?:/|за|в|руб)",
        r"([\d\s]{2,9})\s*(₽|руб|р|thb|usd|\$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            groups = [g for g in match.groups() if g]
            return " ".join(g.strip() for g in groups)
    return "уточнить"


def money_score(budget):
    if budget == "уточнить":
        return 1
    digits = re.sub(r"\D", "", budget)
    if not digits:
        return 1
    amount = int(digits)
    if amount >= 50000:
        return 3
    if amount >= 15000:
        return 2
    return 1


def complexity(text):
    t = _lower(text)
    if any(word in t for word in ["интеграция", "crm", "api", "личный кабинет", "платеж", "парсер"]):
        return "средне"
    if any(word in t for word in ["архитектура", "платформа", "saas", "production", "мобильное приложение"]):
        return "сложно"
    return "легко"


def recommendation(text, skills, risks, budget):
    t = _lower(text)
    if risks:
        return "не брать", f"риск: {risks[0]}"
    if any(marker in t for marker in LOW_VALUE_MARKERS) and not {"telegram", "python", "ai"} & set(skills):
        return "не брать", "низкая релевантность навыкам GTA IRL OS"
    if {"telegram", "python", "ai"} & set(skills):
        if budget == "уточнить":
            return "уточнить", "релевантно, но нужно узнать бюджет"
        return "брать", "релевантно навыкам и есть деньги"
    return "уточнить", "нужно понять, есть ли техническая задача"


def score_offer(text, keywords=None):
    keywords = keywords or []
    skills = matched_skills(text)
    risks = risk_markers(text)
    budget = extract_budget(text)
    verdict, reason = recommendation(text, skills, risks, budget)
    urgency = any(marker in _lower(text) for marker in URGENT_MARKERS)

    score = {
        "verdict": verdict,
        "reason": reason,
        "risk": "high" if risks else "normal",
        "risk_markers": risks,
        "budget": budget,
        "money_score": money_score(budget),
        "complexity": complexity(text),
        "skills": skills,
        "keywords": keywords,
        "urgent": urgency,
    }
    return score


def format_score(score):
    verdict_icon = {
        "брать": "✅",
        "уточнить": "🟡",
        "не брать": "⛔",
    }.get(score.get("verdict"), "🟡")
    risk_icon = "🚫" if score.get("risk") == "high" else "🟢"
    skills = ", ".join(score.get("skills") or ["нет явного совпадения"])
    urgency = "да" if score.get("urgent") else "нет"
    return "\n".join([
        f"{verdict_icon} Вердикт: {score.get('verdict')} — {score.get('reason')}",
        f"{risk_icon} Риск: {score.get('risk')}",
        f"💰 Деньги: {score.get('budget')} / score {score.get('money_score')}",
        f"⚙️ Сложность: {score.get('complexity')}",
        f"🧩 Навыки: {skills}",
        f"⏱ Срочно: {urgency}",
    ])
