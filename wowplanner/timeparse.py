"""Lecture des dates/heures saisies par les joueurs (format français)."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_DATE_RE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?$")
_TIME_RE = re.compile(r"^(\d{1,2})\s*(?:[:hH]\s*(\d{2})?)?$")


def parse_when(date_str: str, time_str: str, tz: ZoneInfo, now: datetime | None = None) -> datetime:
    """Retourne un datetime « aware » dans le fuseau `tz`.

    Dates acceptées : 25/12/2026, 25/12/26, 25/12, 25-12, aujourd'hui, auj, demain.
    Heures acceptées : 21:30, 21h30, 21h, 21.
    """
    now = now.astimezone(tz) if now else datetime.now(tz)

    day = _parse_date(date_str.strip().lower(), now)
    hour = _parse_time(time_str.strip())
    when = datetime.combine(day, hour, tzinfo=tz)

    # Date sans année déjà passée → on suppose l'année suivante.
    m = _DATE_RE.match(date_str.strip())
    if m and m.group(3) is None and when < now:
        try:
            when = when.replace(year=when.year + 1)
        except ValueError:  # 29/02 l'année suivante
            raise ValueError("Cette date est déjà passée.") from None

    if when < now - timedelta(minutes=5):
        raise ValueError("Cette date est déjà passée.")
    return when


def _parse_date(value: str, now: datetime) -> date:
    if value in {"aujourd'hui", "aujourdhui", "auj", "ajd"}:
        return now.date()
    if value == "demain":
        return now.date() + timedelta(days=1)

    m = _DATE_RE.match(value)
    if not m:
        raise ValueError("Date invalide. Formats acceptés : `25/12/2026`, `25/12`, `demain`.")
    d, mth, y = int(m.group(1)), int(m.group(2)), m.group(3)
    year = now.year if y is None else (2000 + int(y) if len(y) == 2 else int(y))
    try:
        return date(year, mth, d)
    except ValueError:
        raise ValueError(f"La date {value} n'existe pas.") from None


def _parse_time(value: str) -> time:
    m = _TIME_RE.match(value)
    if not m:
        raise ValueError("Heure invalide. Formats acceptés : `21:00`, `21h30`, `21h`.")
    h, mins = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mins > 59:
        raise ValueError(f"L'heure {value} n'existe pas.")
    return time(h, mins)
