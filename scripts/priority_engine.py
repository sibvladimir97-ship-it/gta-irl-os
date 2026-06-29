#!/usr/bin/env python3
"""
GTA IRL OS — Priority Engine
Читает все офферы, скорит, формирует рейтинг, отправляет в Telegram.
Без LLM — только Python/regex/словари.
"""

import json
import glob
import re
import os
import requests
from datetime import datetime

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
OWNER_ID  = 335699027

# ── Весовые коэффициенты (настраиваемые) ─────────────────────────────────────

WEIGHTS = {
    "budget_score":      0.30,  # бюджет
    "urgency_score":     0.20,  # срочность
    "simplicity_score":  0.20,  # простота выполнения
    "clarity_score":     0.15,  # чёткость ТЗ
    "close_prob_score":  0.15,  # вероятность закрытия
}

# ── Ниши ─────────────────────────────────────────────────────────────────────

NICHE_PATTERNS = {
    "монтаж":      r"монтаж|видеомонтаж|монтажёр|монтажер|reels|рилс|шортс|shorts|premiere|capcut|davinci|after effects",
    "youtube":     r"youtube|ютуб|ютьюб|ролик|видеоролик|видео ролик",
    "telegram_bot":r"бот|bot|telegram|телеграм|парсер",
    "python":      r"python|питон|скрипт|автоматизация",
    "ai":          r"ai|ии|нейросет|gpt|искусственный интеллект|ai агент|ai agent",
    "smm":         r"smm|таргет|контент|соцсет|instagram|вконтакте|tiktok|тикток",
    "копирайтинг": r"копирайт|текст|сео|seo|статья|описание",
    "дизайн":      r"дизайн|логотип|баннер|фотошоп|illustrator",
    "прочее":      r".*",
}

MONTAGE_KEYWORDS = re.compile(
    r"монтаж|видеомонтаж|монтажёр|монтажер|reels|рилс|шортс|shorts|"
    r"premiere|capcut|davinci|after effects|нарезка|субтитры",
    re.IGNORECASE
)

# ── Извлечение бюджета ────────────────────────────────────────────────────────

BUDGET_RE = re.compile(
    r"(\d[\d\s]*(?:000|к|k|тыс)?\s*(?:руб|₽|rub|р\.)?)",
    re.IGNORECASE
)

def extract_budget(text):
    """Извлекает числовой бюджет из текста."""
    matches = BUDGET_RE.findall(text)
    for m in matches:
        clean = re.sub(r'\s', '', m)
        num = re.sub(r'[^\d]', '', clean)
        if num:
            val = int(num)
            if val < 100:
                val *= 1000  # "10к" → 10000
            if 500 <= val <= 5_000_000:
                return val
    return None

def budget_score(budget):
    if not budget:
        return 3  # неизвестен — средний балл
    if budget >= 50000:  return 10
    if budget >= 20000:  return 8
    if budget >= 10000:  return 6
    if budget >= 5000:   return 4
    return 2

# ── Срочность ─────────────────────────────────────────────────────────────────

URGENT_RE = re.compile(
    r"срочно|сегодня|завтра|asap|быстро|до конца недели|до пятницы|до понедельника|горит",
    re.IGNORECASE
)

def urgency_score(text):
    if URGENT_RE.search(text):
        return 9
    if re.search(r"за \d+ (день|дня|дней)", text, re.IGNORECASE):
        return 7
    return 4

# ── Простота выполнения ───────────────────────────────────────────────────────

SIMPLE_RE  = re.compile(r"монтаж|рилс|reels|шортс|нарезка|субтитры|текст|копирайт|смм|контент", re.IGNORECASE)
COMPLEX_RE = re.compile(r"приложение|app|mobile|ios|android|сайт|website|crm|интеграция|api", re.IGNORECASE)

def simplicity_score(text, niche):
    if niche in ("монтаж", "копирайтинг", "smm"):
        return 9
    if niche in ("telegram_bot", "python"):
        return 7
    if niche == "ai":
        return 6
    if COMPLEX_RE.search(text):
        return 3
    if SIMPLE_RE.search(text):
        return 8
    return 5

# ── Чёткость ТЗ ───────────────────────────────────────────────────────────────

def clarity_score(text):
    score = 5
    if len(text) > 300:  score += 2
    if re.search(r"\d", text):  score += 1  # есть цифры (бюджет/сроки)
    if re.search(r"нужно|требуется|необходимо|хочу", text, re.IGNORECASE):  score += 1
    if re.search(r"\?{2,}|непонятно", text):  score -= 2
    return max(1, min(10, score))

# ── Вероятность закрытия ──────────────────────────────────────────────────────

POSITIVE_RE = re.compile(r"бюджет|оплата|готов заплатить|срочно|сегодня|завтра|ищу|нужен|нужна", re.IGNORECASE)
NEGATIVE_RE = re.compile(r"студент|бесплатно|за опыт|за отзыв|тест", re.IGNORECASE)

def close_prob_score(text):
    score = 5
    score += len(POSITIVE_RE.findall(text)) * 1
    score -= len(NEGATIVE_RE.findall(text)) * 2
    return max(1, min(10, score))

# ── Определение ниши ──────────────────────────────────────────────────────────

def detect_niche(text):
    t = text.lower()
    for niche, pattern in NICHE_PATTERNS.items():
        if re.search(pattern, t):
            return niche
    return "прочее"

def detect_service(text, niche):
    services = {
        "монтаж":       "Видеомонтаж",
        "youtube":      "YouTube-контент",
        "telegram_bot": "Telegram-бот",
        "python":       "Python/автоматизация",
        "ai":           "AI-агент/нейросети",
        "smm":          "SMM/контент",
        "копирайтинг":  "Копирайтинг",
        "дизайн":       "Дизайн",
        "прочее":       "Другое",
    }
    return services.get(niche, "Другое")

def can_delegate(niche):
    return niche in ("монтаж", "дизайн", "копирайтинг", "smm")

def can_do_self(niche):
    return niche in ("монтаж", "telegram_bot", "python", "ai", "youtube")

# ── Основная функция скоринга ─────────────────────────────────────────────────

def score_offer(offer):
    text   = offer.get("raw_text", "") or ""
    d      = offer.get("display", {})
    raw    = offer.get("raw", {})

    niche   = detect_niche(text)
    service = detect_service(text, niche)
    budget  = extract_budget(text)

    bs  = budget_score(budget)
    us  = urgency_score(text)
    ss  = simplicity_score(text, niche)
    cs  = clarity_score(text)
    cps = close_prob_score(text)

    priority = round(
        bs  * WEIGHTS["budget_score"] +
        us  * WEIGHTS["urgency_score"] +
        ss  * WEIGHTS["simplicity_score"] +
        cs  * WEIGHTS["clarity_score"] +
        cps * WEIGHTS["close_prob_score"],
        2
    )

    username = raw.get("sender_username") or ""
    contact  = f"https://t.me/{username}" if username else f"tg://user?id={raw.get('sender_id','')}"

    return {
        "id":           offer["offer_id"],
        "date":         (offer.get("created_at","") or "")[:10],
        "source":       d.get("chat_name",""),
        "contact":      contact,
        "username":     username,
        "niche":        niche,
        "service":      service,
        "budget":       budget or "",
        "budget_raw":   next(iter(BUDGET_RE.findall(text)), ""),
        "urgency":      "срочно" if us >= 8 else "",
        "simplicity":   ss,
        "clarity":      cs,
        "close_prob":   cps,
        "delegate":     "да" if can_delegate(niche) else "нет",
        "self_do":      "да" if can_do_self(niche) else "нет",
        "priority":     priority,
        "status":       offer.get("status","NEW"),
        "is_montage":   bool(MONTAGE_KEYWORDS.search(text)),
        "preview":      (d.get("preview","") or "")[:120],
        "msg_url":      raw.get("msg_url",""),
    }

# ── Создание Excel ────────────────────────────────────────────────────────────

def make_excel(scored):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Все офферы"

    hfill = PatternFill('solid', start_color='1A1A2E', end_color='1A1A2E')
    hfont = Font(bold=True, color='FFFFFF', name='Arial', size=10)
    nf    = Font(name='Arial', size=9)
    lf    = Font(color='1A73E8', underline='single', name='Arial', size=9)
    ca    = Alignment(horizontal='center', vertical='center')
    la    = Alignment(horizontal='left', vertical='center', wrap_text=True)
    thin  = Side(border_style='thin', color='E0E0E0')
    brd   = Border(left=thin, right=thin, top=thin, bottom=thin)

    cols = [
        ("Priority", 8), ("ID", 10), ("Дата", 10), ("Источник", 22),
        ("Контакт", 20), ("Ниша", 14), ("Услуга", 20), ("Бюджет", 10),
        ("Срочность", 9), ("Простота", 8), ("Ясность ТЗ", 9),
        ("Вероятность", 9), ("Делегировать", 10), ("Сам", 6),
        ("Статус", 12), ("Превью", 50),
    ]

    for c, (h, w) in enumerate(cols, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = hfont; cell.fill = hfill
        cell.alignment = ca; cell.border = brd
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.row_dimensions[1].height = 24

    # Цвета по приоритету
    def row_color(priority, is_montage):
        if is_montage:
            return 'E8F5E9'  # светло-зелёный — монтаж
        if priority >= 7:    return 'FFF9C4'  # жёлтый — высокий приоритет
        if priority >= 5:    return None
        return 'FAFAFA'

    for i, s in enumerate(scored, 2):
        rc = row_color(s["priority"], s["is_montage"])
        rf = PatternFill('solid', start_color=rc, end_color=rc) if rc else None

        def wr(col, val, font=None, align=None, hl=None):
            cl = ws.cell(row=i, column=col, value=val)
            cl.font = font or nf; cl.alignment = align or la; cl.border = brd
            if rf: cl.fill = rf
            if hl: cl.hyperlink = hl
            return cl

        wr(1,  s["priority"], align=ca)
        wr(2,  s["id"])
        wr(3,  s["date"], align=ca)
        wr(4,  s["source"])
        cl = wr(5, s["username"] or s["contact"], font=lf if s["contact"] else nf)
        if s["contact"]: cl.hyperlink = s["contact"]
        wr(6,  s["niche"], align=ca)
        wr(7,  s["service"])
        wr(8,  s["budget"] or "?", align=ca)
        wr(9,  s["urgency"] or "—", align=ca)
        wr(10, s["simplicity"], align=ca)
        wr(11, s["clarity"], align=ca)
        wr(12, s["close_prob"], align=ca)
        wr(13, s["delegate"], align=ca)
        wr(14, s["self_do"], align=ca)
        wr(15, s["status"], align=ca)
        wr(16, s["preview"])
        ws.row_dimensions[i].height = 18

    ws.auto_filter.ref = f'A1:P{len(scored)+1}'
    ws.freeze_panes = 'A2'

    # Лист: ТОП монтаж
    ws2 = wb.create_sheet("🎬 Монтаж (1 очередь)")
    montage = [s for s in scored if s["is_montage"]]
    _write_top_sheet(ws2, montage, "Монтаж — первая очередь", hfill, hfont, nf, lf, brd, ca, la)

    # Лист: ТОП по Priority
    ws3 = wb.create_sheet("🏆 ТОП Priority")
    top = sorted(scored, key=lambda x: x["priority"], reverse=True)[:50]
    _write_top_sheet(ws3, top, "ТОП-50 по приоритету", hfill, hfont, nf, lf, brd, ca, la)

    # Лист: ТОП по бюджету
    ws4 = wb.create_sheet("💰 ТОП Бюджет")
    by_budget = sorted([s for s in scored if s["budget"]], key=lambda x: x["budget"], reverse=True)[:30]
    _write_top_sheet(ws4, by_budget, "ТОП-30 по бюджету", hfill, hfont, nf, lf, brd, ca, la)

    out = os.path.join(ROOT, "gta_priority.xlsx")
    wb.save(out)
    return out, len(montage)

def _write_top_sheet(ws, data, title, hfill, hfont, nf, lf, brd, ca, la):
    from openpyxl.styles import Font, PatternFill
    ws['A1'] = title
    ws['A1'].font = Font(bold=True, size=12, name='Arial')
    cols = ["Priority", "Ниша", "Услуга", "Бюджет", "Контакт", "Превью"]
    widths = [8, 14, 20, 10, 22, 55]
    from openpyxl.utils import get_column_letter
    for c, (h, w) in enumerate(zip(cols, widths), 1):
        cell = ws.cell(row=2, column=c, value=h)
        cell.font = hfont; cell.fill = hfill; cell.alignment = ca; cell.border = brd
        ws.column_dimensions[get_column_letter(c)].width = w
    for i, s in enumerate(data, 3):
        ws.cell(row=i, column=1, value=s["priority"]).font = Font(bold=True, name='Arial', size=9)
        ws.cell(row=i, column=2, value=s["niche"]).font = nf
        ws.cell(row=i, column=3, value=s["service"]).font = nf
        ws.cell(row=i, column=4, value=s["budget"] or "?").font = nf
        cl = ws.cell(row=i, column=5, value=s["username"] or "—")
        cl.font = lf if s["contact"] else nf
        if s["contact"]: cl.hyperlink = s["contact"]
        ws.cell(row=i, column=6, value=s["preview"]).font = nf
        ws.row_dimensions[i].height = 16

# ── Telegram отчёт ────────────────────────────────────────────────────────────

def send_report(scored, montage_count, out_path):
    if not BOT_TOKEN:
        return

    total  = len(scored)
    with_budget = [s for s in scored if s["budget"]]
    avg_budget = int(sum(s["budget"] for s in with_budget) / len(with_budget)) if with_budget else 0

    top20 = sorted(scored, key=lambda x: x["priority"], reverse=True)[:20]

    lines = [
        "📊 *Priority Engine — Результат*",
        f"",
        f"Обработано заявок: *{total}*",
        f"По монтажу (1 очередь): *{montage_count}*",
        f"Средний бюджет: *{avg_budget:,} ₽*".replace(",", " "),
        f"",
        f"*ТОП-20 перспективных:*",
    ]

    for i, s in enumerate(top20, 1):
        budget_str = f"{s['budget']:,}₽".replace(",", " ") if s["budget"] else "?"
        contact = f"@{s['username']}" if s["username"] else "нет username"
        lines.append(
            f"{i}. [{s['niche']}] {s['service']} · {budget_str} · {contact} · score:{s['priority']}"
        )

    lines.append(f"\n📁 Таблица сохранена: gta\\_priority.xlsx")

    text = "\n".join(lines)

    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": OWNER_ID, "text": text, "parse_mode": "Markdown",
              "disable_web_page_preview": True},
        timeout=15
    )

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("GTA IRL OS — Priority Engine")
    print("Читаю офферы...")

    files = glob.glob(os.path.join(ROOT, "data", "offers", "*.json"))
    offers = []
    for f in files:
        try:
            offers.append(json.load(open(f)))
        except:
            pass

    print(f"Загружено: {len(offers)}")

    print("Скорю...")
    scored = [score_offer(o) for o in offers]
    scored.sort(key=lambda x: x["priority"], reverse=True)

    montage = [s for s in scored if s["is_montage"]]
    with_budget = [s for s in scored if s["budget"]]
    avg_budget = int(sum(s["budget"] for s in with_budget) / len(with_budget)) if with_budget else 0

    print(f"\nРезультат:")
    print(f"  Всего: {len(scored)}")
    print(f"  Монтаж: {len(montage)}")
    print(f"  Со знакомым бюджетом: {len(with_budget)}")
    print(f"  Средний бюджет: {avg_budget:,} ₽")

    print("\nТОП-10:")
    for i, s in enumerate(scored[:10], 1):
        print(f"  {i}. [{s['niche']}] {s['service']} | {s['budget'] or '?'}₽ | score:{s['priority']} | @{s['username'] or '?'}")

    print("\nСоздаю Excel...")
    out, montage_count = make_excel(scored)
    print(f"Сохранено: {out}")

    print("Отправляю отчёт в Telegram...")
    send_report(scored, montage_count, out)
    print("Готово!")

if __name__ == "__main__":
    main()
