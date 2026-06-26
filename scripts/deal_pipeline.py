"""
GTA IRL OS — Deal Pipeline

Единая карта денежной воронки:
заявка → фильтр → отклик → переговоры → ТЗ → КП → предоплата →
исполнение → сдача → доплата → закрытие.

Модуль не знает про Telegram. Он только управляет состоянием сделки.
"""

from datetime import datetime


STAGES = [
    "NEW_LEAD",
    "FILTERED",
    "CARD_SENT",
    "RESPOND_DECIDED",
    "FIRST_MESSAGE_DRAFTED",
    "FIRST_MESSAGE_SENT",
    "WAITING_REPLY",
    "CLIENT_REPLIED",
    "BRIEF_COLLECTING",
    "BRIEF_READY",
    "PROPOSAL_DRAFTED",
    "PROPOSAL_SENT",
    "PREPAYMENT_WAITING",
    "PREPAYMENT_RECEIVED",
    "EXECUTION_PLANNING",
    "IN_PROGRESS",
    "DELIVERED",
    "FINAL_PAYMENT_WAITING",
    "CLOSED_WON",
    "SCAM",
    "HIDDEN",
    "REJECTED",
    "DELEGATED",
    "CLIENT_GHOSTED",
    "CLOSED_LOST",
]


STAGE_LABELS = {
    "NEW_LEAD": "🆕 Новый лид",
    "FILTERED": "🧹 Отфильтровано",
    "CARD_SENT": "📇 Карточка в Telegram",
    "RESPOND_DECIDED": "🎯 Решено откликаться",
    "FIRST_MESSAGE_DRAFTED": "✏️ Черновик отклика готов",
    "FIRST_MESSAGE_SENT": "📨 Первый отклик отправлен",
    "WAITING_REPLY": "⏳ Ждём ответ клиента",
    "CLIENT_REPLIED": "💬 Клиент ответил",
    "BRIEF_COLLECTING": "🔍 Собираем ТЗ / бюджет / дедлайн",
    "BRIEF_READY": "✅ ТЗ собрано",
    "PROPOSAL_DRAFTED": "📋 КП подготовлено",
    "PROPOSAL_SENT": "📤 КП отправлено",
    "PREPAYMENT_WAITING": "💳 Ждём предоплату",
    "PREPAYMENT_RECEIVED": "💰 Предоплата получена",
    "EXECUTION_PLANNING": "🧭 План исполнения",
    "IN_PROGRESS": "⚙️ В работе",
    "DELIVERED": "📦 Сдано клиенту",
    "FINAL_PAYMENT_WAITING": "🧾 Ждём доплату",
    "CLOSED_WON": "🏁 Закрыто успешно",
    "SCAM": "🚫 Скам",
    "HIDDEN": "👁 Скрыто",
    "REJECTED": "❌ Отказались",
    "DELEGATED": "📤 Делегировано",
    "CLIENT_GHOSTED": "👻 Клиент пропал",
    "CLOSED_LOST": "🪦 Закрыто без сделки",
}


NEXT_ACTIONS = {
    "NEW_LEAD": "Проверить заявку: деньги, риск, релевантность.",
    "FILTERED": "Показать карточку заявки в Telegram.",
    "CARD_SENT": "Выбрать действие: откликнуться, скрыть, скам или делегировать.",
    "RESPOND_DECIDED": "Подготовить первый отклик.",
    "FIRST_MESSAGE_DRAFTED": "Проверить черновик и отправить только после подтверждения.",
    "FIRST_MESSAGE_SENT": "Ждать ответ клиента.",
    "WAITING_REPLY": "Отследить входящий ответ или пометить клиента пропавшим.",
    "CLIENT_REPLIED": "Собрать ТЗ, бюджет и дедлайн.",
    "BRIEF_COLLECTING": "Дожать недостающие вводные: объём, срок, деньги, критерий готовности.",
    "BRIEF_READY": "Подготовить коммерческое предложение.",
    "PROPOSAL_DRAFTED": "Проверить КП и отправить клиенту.",
    "PROPOSAL_SENT": "Ждать подтверждение и предоплату.",
    "PREPAYMENT_WAITING": "Контролировать предоплату.",
    "PREPAYMENT_RECEIVED": "Решить исполнение: сам, делегировать или отказаться.",
    "EXECUTION_PLANNING": "Разбить работу на шаги и дедлайны.",
    "IN_PROGRESS": "Делать работу и контролировать дедлайн.",
    "DELIVERED": "Получить подтверждение сдачи и запросить доплату.",
    "FINAL_PAYMENT_WAITING": "Контролировать финальную оплату.",
    "CLOSED_WON": "Записать результат и уроки в память.",
    "SCAM": "Ничего не делать. Оффер исключён.",
    "HIDDEN": "Ничего не делать, пока оффер скрыт.",
    "REJECTED": "Ничего не делать. Решение: не брать.",
    "DELEGATED": "Контролировать делегата и дедлайн.",
    "CLIENT_GHOSTED": "Можно сделать один follow-up или закрыть как lost.",
    "CLOSED_LOST": "Записать причину потери.",
}


TERMINAL_STAGES = {
    "SCAM",
    "HIDDEN",
    "REJECTED",
    "CLOSED_WON",
    "CLOSED_LOST",
}


ALLOWED_TRANSITIONS = {
    "NEW_LEAD": {"FILTERED", "CARD_SENT", "RESPOND_DECIDED", "SCAM", "HIDDEN", "REJECTED"},
    "FILTERED": {"CARD_SENT", "SCAM", "HIDDEN", "REJECTED"},
    "CARD_SENT": {"RESPOND_DECIDED", "SCAM", "HIDDEN", "DELEGATED", "REJECTED"},
    "RESPOND_DECIDED": {"FIRST_MESSAGE_DRAFTED", "REJECTED"},
    "FIRST_MESSAGE_DRAFTED": {"FIRST_MESSAGE_SENT", "REJECTED"},
    "FIRST_MESSAGE_SENT": {"WAITING_REPLY", "CLIENT_REPLIED", "CLIENT_GHOSTED"},
    "WAITING_REPLY": {"CLIENT_REPLIED", "CLIENT_GHOSTED", "CLOSED_LOST"},
    "CLIENT_REPLIED": {"BRIEF_COLLECTING", "BRIEF_READY", "REJECTED"},
    "BRIEF_COLLECTING": {"BRIEF_READY", "CLIENT_GHOSTED", "REJECTED"},
    "BRIEF_READY": {"PROPOSAL_DRAFTED", "REJECTED", "DELEGATED"},
    "PROPOSAL_DRAFTED": {"PROPOSAL_SENT", "REJECTED"},
    "PROPOSAL_SENT": {"PREPAYMENT_WAITING", "PREPAYMENT_RECEIVED", "CLIENT_GHOSTED", "CLOSED_LOST"},
    "PREPAYMENT_WAITING": {"PREPAYMENT_RECEIVED", "CLIENT_GHOSTED", "CLOSED_LOST"},
    "PREPAYMENT_RECEIVED": {"EXECUTION_PLANNING", "DELEGATED", "REJECTED"},
    "EXECUTION_PLANNING": {"IN_PROGRESS", "DELEGATED", "REJECTED"},
    "IN_PROGRESS": {"DELIVERED", "DELEGATED"},
    "DELIVERED": {"FINAL_PAYMENT_WAITING", "CLOSED_WON"},
    "FINAL_PAYMENT_WAITING": {"CLOSED_WON", "CLOSED_LOST"},
    "DELEGATED": {"IN_PROGRESS", "DELIVERED", "CLOSED_WON", "CLOSED_LOST"},
    "CLIENT_GHOSTED": {"WAITING_REPLY", "CLOSED_LOST"},
}


LEGACY_STAGE_ALIASES = {
    "QUALIFYING": "BRIEF_COLLECTING",
    "OFFER_SENT": "PROPOSAL_SENT",
    "WAITING_PREPAYMENT": "PREPAYMENT_WAITING",
    "IN_WORK": "IN_PROGRESS",
    "CLOSED": "CLOSED_WON",
    "LOST": "CLOSED_LOST",
}


def normalize_stage(stage):
    """Return current canonical stage name."""
    return LEGACY_STAGE_ALIASES.get(stage, stage)


def stage_label(stage):
    stage = normalize_stage(stage)
    return STAGE_LABELS.get(stage, stage)


def next_action(stage):
    stage = normalize_stage(stage)
    return NEXT_ACTIONS.get(stage, "Определить следующий шаг вручную.")


def is_terminal_stage(stage):
    stage = normalize_stage(stage)
    return stage in TERMINAL_STAGES


def can_transition(current_stage, next_stage):
    current_stage = normalize_stage(current_stage)
    next_stage = normalize_stage(next_stage)

    if current_stage == next_stage:
        return True
    if current_stage in TERMINAL_STAGES:
        return False
    return next_stage in ALLOWED_TRANSITIONS.get(current_stage, set())


def init_pipeline(deal):
    """Ensure deal has canonical stage and transition history."""
    stage = normalize_stage(deal.get("stage", "NEW_LEAD"))
    deal["stage"] = stage
    deal.setdefault("stage_history", [])
    if not deal["stage_history"]:
        now = deal.get("created_at") or datetime.utcnow().isoformat()
        deal["stage_history"].append({
            "from": None,
            "to": stage,
            "at": now,
            "reason": "created",
        })
    deal["next_action"] = next_action(stage)
    return deal


def move_deal(deal, next_stage, reason=None, allow_any=False):
    """Move deal to a new stage and append auditable transition history."""
    init_pipeline(deal)

    current = normalize_stage(deal.get("stage", "NEW_LEAD"))
    target = normalize_stage(next_stage)

    if target not in STAGES:
        raise ValueError(f"Unknown deal stage: {next_stage}")

    if not allow_any and not can_transition(current, target):
        raise ValueError(f"Illegal deal transition: {current} -> {target}")

    if current != target:
        deal["stage_history"].append({
            "from": current,
            "to": target,
            "at": datetime.utcnow().isoformat(),
            "reason": reason or "",
        })

    deal["stage"] = target
    deal["updated_at"] = datetime.utcnow().isoformat()
    deal["next_action"] = next_action(target)
    return deal
