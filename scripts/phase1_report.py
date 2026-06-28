"""
GTA IRL OS — Phase 1 daily report.

Aggregates local operational data required by Phase 1:
jobs found, filtered, replies, negotiations, prepayments,
AI usage, and Telegram errors.
"""

from datetime import date, datetime

from ai_service import ai_usage_summary
from negotiator import list_all_deals
from offer_store import list_offers
from telegram_risk import telegram_risk_summary


TERMINAL_FILTERED_STATUSES = {"SCAM", "HIDDEN", "DELEGATED"}
NEGOTIATION_STAGES = {
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
}


def _report_day(day=None):
    if day is None:
        return date.today().isoformat()
    if isinstance(day, date):
        return day.isoformat()
    return str(day)


def _is_same_day(value, day):
    if not value:
        return False
    try:
        return datetime.fromisoformat(str(value)).date().isoformat() == day
    except ValueError:
        return str(value).startswith(day)


def _deal_has_event_today(deal, event_type, day):
    for event in deal.get("events", []):
        if event.get("type") == event_type and _is_same_day(event.get("timestamp"), day):
            return True
    return False


def _count_incoming_replies_today(deals, day):
    count = 0
    for deal in deals:
        for message in deal.get("messages", []):
            if message.get("direction") == "incoming" and _is_same_day(message.get("timestamp"), day):
                count += 1
    return count


def _count_prepayments_today(deals, day):
    count = 0
    amount_known = 0
    for deal in deals:
        payment = deal.get("payment") or {}
        if _is_same_day(payment.get("prepayment_received_at"), day):
            count += 1
            if payment.get("prepayment_amount"):
                amount_known += 1
            continue
        for payment_event in deal.get("payments", []):
            if payment_event.get("type") == "prepayment" and _is_same_day(payment_event.get("received_at"), day):
                count += 1
                if payment_event.get("amount"):
                    amount_known += 1
                break
    return {"count": count, "amount_known": amount_known}


def phase1_report(day=None):
    """Return raw Phase 1 report counters."""
    day = _report_day(day)
    offers = list_offers()
    deals = list_all_deals()
    offers_today = [offer for offer in offers if _is_same_day(offer.get("created_at"), day)]
    deals_today = [deal for deal in deals if _is_same_day(deal.get("created_at"), day)]

    filtered_today = [
        offer for offer in offers_today
        if offer.get("status") in TERMINAL_FILTERED_STATUSES
    ]
    responded_today = [
        offer for offer in offers_today
        if offer.get("status") == "RESPONDED" or offer.get("deal_id")
    ]
    negotiations = [
        deal for deal in deals
        if deal.get("stage") in NEGOTIATION_STAGES
        and (
            _is_same_day(deal.get("created_at"), day)
            or _is_same_day(deal.get("updated_at"), day)
            or _deal_has_event_today(deal, "message", day)
            or _deal_has_event_today(deal, "stage_changed", day)
        )
    ]
    prepayments = _count_prepayments_today(deals, day)
    ai = ai_usage_summary(day)
    telegram = telegram_risk_summary(day)

    return {
        "day": day,
        "jobs_found": len(offers_today),
        "filtered_saved": len(filtered_today),
        "responded": len(responded_today),
        "deals_created": len(deals_today),
        "client_replies": _count_incoming_replies_today(deals, day),
        "negotiations": len(negotiations),
        "prepayments": prepayments,
        "ai": ai,
        "telegram": telegram,
    }


def format_phase1_report(day=None):
    """Format Phase 1 report for Telegram."""
    report = phase1_report(day)
    ai = report["ai"]
    telegram = report["telegram"]
    risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(telegram["risk_level"], "⚪")

    lines = [
        f"📊 *Phase 1 report — {report['day']}*",
        "",
        "*Pipeline:*",
        f"• Jobs found: `{report['jobs_found']}`",
        f"• Filtered saved: `{report['filtered_saved']}`",
        f"• Replies sent / deals started: `{report['responded']}`",
        f"• Deals created: `{report['deals_created']}`",
        f"• Client replies: `{report['client_replies']}`",
        f"• Active negotiations touched: `{report['negotiations']}`",
        f"• Prepayments: `{report['prepayments']['count']}`",
        "",
        "*AI usage:*",
        f"• Attempts: `{ai['total']}`",
        f"• OK: `{ai['by_status'].get('ok', 0)}`",
        f"• No key/fallback: `{ai['by_status'].get('no_key', 0)}`",
        f"• Rate/error: `{ai['by_status'].get('rate_limited', 0) + ai['by_status'].get('error', 0)}`",
        "",
        "*Telegram risk:*",
        f"• Risk: {risk_icon} `{telegram['risk_level']}`",
        f"• Sends: `{telegram['sends']}`",
        f"• Errors: `{telegram['errors']}`",
        f"• FloodWait: `{telegram['flood_waits']}`",
    ]

    if telegram.get("warnings"):
        lines.append("\n*Warnings:*")
        for warning in telegram["warnings"]:
            lines.append(f"• {warning}")

    lines.append("\nNote: `Filtered saved` counts stored offers marked SCAM/HIDDEN/DELEGATED; parser-level discarded posts are not persisted yet.")
    return "\n".join(lines)
