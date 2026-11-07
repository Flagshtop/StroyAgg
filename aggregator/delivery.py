"""Разбор текстов о доставке: «завтра», «28 октября», «2–4 дня», «пт, 31 окт» и т.п."""
import re
from datetime import date, timedelta
from typing import Optional

_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}
_DATE_RE = re.compile(
    r"(\d{1,2})\s*(?:[-–—]\s*(\d{1,2})\s*)?(янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек)[а-я]*\.?",
    re.I,
)
_NUM_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b")
_DAYS_RE = re.compile(
    r"(?:от\s+)?(\d{1,3})\s*(?:[-–—]|до)?\s*(\d{1,3})?\s*(?:раб\w*\.?\s*)?(?:дн\w*|день|сут\w*)", re.I
)
_HOURS_RE = re.compile(r"(\d{1,2})\s*(?:[-–—]\s*\d{1,2}\s*)?(?:ч\b|час)", re.I)
_WEEKS_RE = re.compile(r"(\d{1,2})\s*(?:[-–—]\s*\d{1,2}\s*)?недел", re.I)


def _resolve_date(day: int, month: int, today: date, year: Optional[int] = None) -> Optional[date]:
    try:
        d = date(year or today.year, month, day)
    except ValueError:
        return None
    if year is None and d < today - timedelta(days=7):
        d = date(d.year + 1, month, day)  # «5 января», сказанное в декабре
    return d


def parse_delivery(text: str, today: Optional[date] = None) -> tuple[Optional[int], Optional[date]]:
    """Возвращает (дней до получения, дата получения). Берётся самый быстрый вариант из текста."""
    if not text:
        return None, None
    today = today or date.today()
    t = text.lower().replace("\xa0", " ").replace(" ", " ").replace("ё", "е")
    candidates: list[int] = []

    for m in _DATE_RE.finditer(t):
        d = _resolve_date(int(m.group(1)), _MONTHS[m.group(3)[:3].replace("май", "мая")], today)
        if d:
            candidates.append((d - today).days)
    for m in _NUM_DATE_RE.finditer(t):
        y = m.group(3)
        year = (2000 + int(y) if len(y) == 2 else int(y)) if y else None
        d = _resolve_date(int(m.group(1)), int(m.group(2)), today, year)
        if d:
            candidates.append((d - today).days)

    if "сегодня" in t or "в течение часа" in t or _HOURS_RE.search(t):
        candidates.append(0)
    if "послезавтра" in t:
        candidates.append(2)
    elif "завтра" in t:
        candidates.append(1)

    for m in _DAYS_RE.finditer(t):
        candidates.append(int(m.group(1)))
    for m in _WEEKS_RE.finditer(t):
        candidates.append(int(m.group(1)) * 7)

    candidates = [c for c in candidates if 0 <= c <= 365]
    if not candidates:
        return None, None
    days = min(candidates)
    return days, today + timedelta(days=days)


def parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    t = text.replace("\xa0", " ").replace(" ", " ").replace(" ", " ")
    m = re.search(r"(\d[\d ]*(?:[.,]\d{1,2})?)", t)
    if not m:
        return None
    try:
        return float(m.group(1).replace(" ", "").replace(",", "."))
    except ValueError:
        return None
