"""What a job's pay is per: hour, day, week, month, or year.

Sites give a salary as two numbers, and a bare "$1,200 - $3,000" or "From
$64" doesn't say whether it's hourly, monthly, or yearly. A job's pay period
(``salary_period``) comes from, in order:

1. The site's own field (Lever's ``interval``, Ashby's ``interval``, a unit
   on Insight Global's ``payRate``, ...): the job board's adapter reads it
   into ``Posting.salary_period``.
2. The posting's text, when it states a period next to the same amount:
   "Pay rate range: $60-64/hour", "$120k - $150k per year".
3. Otherwise it's assumed (``salary_period_estimated``): an amount under
   ``MAX_HOURLY`` is an hourly rate (Insight Global's unlabelled 64, 53, ...),
   and anything else is a yearly salary.

``format_salary`` is the wording the email uses;
frontend/src/lib/jobs.ts ``formatSalary`` mirrors it for the dashboard.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

PERIODS = ("hour", "day", "week", "month", "year")
# Short labels, for the email and the dashboard's table.
PERIOD_SUFFIXES = {"hour": "/hr", "day": "/day", "week": "/wk", "month": "/mo", "year": "/yr"}
# With no stated period, amounts below this (in dollars) are taken as hourly
# rates, and anything else as a yearly salary.
MAX_HOURLY = 300

_PERIOD_WORDS = {
    "hour": {"hour", "hours", "hourly", "hr", "hrs", "h"},
    "day": {"day", "days", "daily"},
    "week": {"week", "weeks", "weekly", "wk", "wks"},
    "month": {"month", "months", "monthly", "mo", "mos", "mth"},
    "year": {"year", "years", "yearly", "yr", "yrs", "annual", "annually", "annum", "pa"},
}
_WORD_TO_PERIOD = {word: period for period, words in _PERIOD_WORDS.items() for word in words}


def normalize_period(value: Any) -> str:
    """A site's pay-period value as one of ``PERIODS``, or "" if it isn't one.

    Reads "Hourly", "per-hour-wage" (Lever), "1 HOUR" / "1 MONTH" (Ashby),
    "YEAR", "annually", "PER_MONTH", ... A count of more than one ("2 WEEK",
    "6 MONTH") isn't a period the dashboard can show, so it's "".
    """
    words = re.findall(r"[a-z]+|\d+", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(value or "")).lower())
    numbers = [int(word) for word in words if word.isdigit()]
    if any(number != 1 for number in numbers):
        return ""
    found = {_WORD_TO_PERIOD[word] for word in words if word in _WORD_TO_PERIOD}
    return found.pop() if len(found) == 1 else ""


# Field names sites use for the pay period, in the order they're tried.
PERIOD_FIELDS = (
    "period", "interval", "unit", "frequency", "payPeriod", "payFrequency", "salaryPeriod",
    "salaryInterval", "rateType", "payType", "rateUnit", "type", "per",
)


def period_from_fields(payload: Any, fields: Iterable[str] = PERIOD_FIELDS) -> str:
    """The pay period from the first of ``fields`` in ``payload`` that names one."""
    if not isinstance(payload, dict):
        return ""
    for field in fields:
        period = normalize_period(payload.get(field))
        if period:
            return period
    return ""


# "$60 - $65/hour", "60-64/hr", "$120k to $150k per year", "$1,200 - $3,000 USD a month"
_AMOUNT = r"\$?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*([kK])?"
_PERIOD_WORD = r"([A-Za-z]+)\b"
_AMOUNT_THEN_PERIOD = re.compile(
    rf"{_AMOUNT}(?:\s*(?:-|–|—|to)\s*{_AMOUNT})?\s*(?:USD|US\$|dollars)?\s*"
    rf"(?:/|\bper\b|\ban?\b|\beach\b)\s*{_PERIOD_WORD}",
    re.IGNORECASE,
)
# "$60 - $65 hourly", "$95,000 annually"
_AMOUNT_THEN_ADVERB = re.compile(
    rf"\$\s*(\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*([kK])?"
    rf"(?:\s*(?:-|–|—|to)\s*{_AMOUNT})?\s*(?:USD\s*)?(hourly|daily|weekly|monthly|yearly|annually)\b",
    re.IGNORECASE,
)
# "hourly rate: $60 - $65", "Annual salary range is $120,000 to $150,000"
_PERIOD_THEN_AMOUNT = re.compile(
    r"\b(hourly|daily|weekly|monthly|yearly|annual)\s+(?:base\s+)?(?:pay|rate|salary|wage|"
    r"compensation)(?:\s+rate)?(?:\s+range)?\s*(?:is|of|:|-|–)?\s*(?:between\s+|from\s+)?"
    rf"{_AMOUNT}(?:\s*(?:-|–|—|to|and)\s*{_AMOUNT})?",
    re.IGNORECASE,
)


def _amounts(groups: tuple[str | None, ...]) -> list[float]:
    """The dollar amounts in a match's (number, "k") group pairs."""
    amounts = []
    for number, thousands in zip(groups[0::2], groups[1::2]):
        if number:
            value = float(number.replace(",", ""))
            amounts.append(value * 1000 if thousands else value)
    return amounts


def _same_amount(found: float, wanted: float) -> bool:
    """Equal but for rounding ($64.50 and $64, $120k and $120,500)."""
    return wanted > 0 and abs(found - wanted) <= max(0.5, wanted * 0.005)


def period_from_text(text: str | None, low: float, high: float) -> str:
    """The pay period the posting states next to the same amount as the
    salary (``low`` or ``high``), or "" if it doesn't state one."""
    text = str(text or "")
    if not text or not (low or high):
        return ""
    for pattern, amount_groups, period_group in (
        (_AMOUNT_THEN_PERIOD, (1, 2, 3, 4), 5),
        (_AMOUNT_THEN_ADVERB, (1, 2, 3, 4), 5),
        (_PERIOD_THEN_AMOUNT, (2, 3, 4, 5), 1),
    ):
        for match in pattern.finditer(text):
            period = normalize_period(match.group(period_group))
            if not period:
                continue
            amounts = _amounts(tuple(match.group(index) for index in amount_groups))
            if any(_same_amount(amount, wanted) for amount in amounts for wanted in (low, high)):
                return period
    return ""


def estimate_period(low: float, high: float) -> str:
    """The pay period assumed when nothing states one: "hour" for an amount
    under ``MAX_HOURLY``, else "year" ("" when there's no salary)."""
    amount = max(low or 0, high or 0)
    if amount <= 0:
        return ""
    return "hour" if amount < MAX_HOURLY else "year"


# How many of each period make a year, to compare pay across periods: 40
# hours a week, 5 days a week, 52 weeks a year.
PER_YEAR = {"hour": 2080, "day": 260, "week": 52, "month": 12, "year": 1}


def yearly_amounts(low: Any, high: Any, period: Any = "") -> list[float]:
    """The listed amounts (0 or missing means not listed) as yearly pay, for
    sorting and filtering: $50/hr is $104,000 a year, $3,000/mo $36,000. A job
    with no period gets the assumed one (``estimate_period``), as it's shown."""
    amounts = [
        float(value) for value in (low, high)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
    ]
    if not amounts:
        return []
    if period not in PER_YEAR:
        period = estimate_period(max(amounts), 0)
    return [amount * PER_YEAR[period] for amount in amounts]


def salary_period(
    site_period: str, description: str | None, low: float, high: float
) -> tuple[str, bool]:
    """``(period, estimated)`` for a job's salary: the site's field, else the
    posting's text, else assumed from the amount (``estimate_period``).
    ``("", False)`` when there's no salary."""
    if not (low or high):
        return "", False
    period = normalize_period(site_period) or period_from_text(description, low, high)
    if period:
        return period, False
    return estimate_period(low, high), True


def _money(value: float) -> str:
    """"$64", "$64.50", "$120,000"."""
    if value != int(value) and value < 1000:
        return f"${value:,.2f}"
    return f"${value:,.0f}"


def format_salary(low: Any, high: Any, period: Any = "", estimated: bool = False) -> str:
    """"$60 - $65/hr", "From $140,000/yr", "$1,200 - $3,000/mo", or
    "From $64/hr (est.)" / "$1,200 - $3,000/yr (est.)" when the period is
    assumed. A job saved before periods were kept (no ``period``) gets the
    assumed one."""
    low, high = float(low or 0), float(high or 0)
    if not low and not high:
        return "Not listed"
    if not low:
        amount = f"Up to {_money(high)}"
    elif not high or high == low:
        amount = f"From {_money(low)}" if not high else _money(low)
    else:
        amount = f"{_money(low)} - {_money(high)}"
    if str(period or "") not in PERIOD_SUFFIXES:
        period, estimated = estimate_period(low, high), True
    return f"{amount}{PERIOD_SUFFIXES[period]}{' (est.)' if estimated else ''}"
