"""Tests for salary.py: what a job's pay is per, and how it reads."""

import json
from pathlib import Path

import pytest

from salary import (
    estimate_period,
    format_salary,
    normalize_period,
    period_from_fields,
    period_from_text,
    salary_period,
    yearly_amounts,
)

# Shared with the dashboard's tests (frontend/src/lib/jobs.test.ts), so the
# email and the dashboard word every salary the same way.
SALARY_FORMATS = Path(__file__).resolve().parents[2] / "frontend/src/test/fixtures/salary_formats.json"


@pytest.mark.parametrize("case", json.loads(SALARY_FORMATS.read_text())["cases"], ids=lambda c: c["text"])
def test_format_salary_matches_the_dashboards_wording(case):
    assert format_salary(case["low"], case["high"], case["period"], case["estimated"]) == case["text"]


@pytest.mark.parametrize(
    "value, period",
    [
        ("Hourly", "hour"),
        ("HOURLY", "hour"),
        ("per-hour-wage", "hour"),  # Lever
        ("1 HOUR", "hour"),  # Ashby
        ("PER_HOUR", "hour"),
        ("hr", "hour"),
        ("daily", "day"),
        ("1 DAY", "day"),
        ("per-week-wage", "week"),
        ("weekly", "week"),
        ("per-month-salary", "month"),
        ("1 MONTH", "month"),
        ("Monthly", "month"),
        ("perMonth", "month"),
        ("per-year-salary", "year"),
        ("1 YEAR", "year"),
        ("Annual", "year"),
        ("annually", "year"),
        ("Yearly", "year"),
        # A count of more than one isn't a period that can be shown.
        ("2 WEEK", ""),
        ("6 MONTH", ""),
        # Not periods.
        ("Salary", ""),
        ("Contract", ""),
        ("NONE", ""),
        ("", ""),
        (None, ""),
        ("hourly or yearly", ""),
    ],
)
def test_normalize_period(value, period):
    assert normalize_period(value) == period


def test_period_from_fields_tries_the_usual_names_in_order():
    assert period_from_fields({"min": 60, "max": 70, "type": "Hourly"}) == "hour"
    assert period_from_fields({"currency": "USD", "rateType": "Annual"}) == "year"
    assert period_from_fields({"interval": "per-month-salary", "type": "Hourly"}) == "month"
    assert period_from_fields({"min": 60, "type": "Contract"}) == ""
    assert period_from_fields({"salaryPeriod": "monthly"}, ("salaryPeriod",)) == "month"
    assert period_from_fields({"type": "Hourly"}, ("salaryPeriod",)) == ""
    assert period_from_fields(None) == ""


@pytest.mark.parametrize(
    "text, low, high, period",
    [
        ("Pay rate range: 60-64/hour", 64, 0, "hour"),
        ("Compensation:\n$55-60/hour\nExact compensation may vary", 55, 0, "hour"),
        ("$60 - $65 per hour on a W2", 60, 65, "hour"),
        ("Rate: $70/hr", 70, 0, "hour"),
        ("Rate: $64.50/hr", 64, 0, "hour"),  # rounding
        ("$120k - $150k/yr", 120400, 0, "year"),
        ("The pay is $75 an hour.", 75, 0, "hour"),
        ("$60 - $65 hourly", 60, 65, "hour"),
        ("Hourly rate: $60 - $65", 60, 65, "hour"),
        ("We pay $1,200 - $3,000 per month.", 1200, 3000, "month"),
        ("Salary: $1,200 to $3,000 USD a month", 1200, 3000, "month"),
        ("$1,200-$3,000/mo", 1200, 3000, "month"),
        ("Monthly salary: $2,500", 2500, 0, "month"),
        ("Base salary of $120k - $150k per year", 120000, 150000, "year"),
        ("The annual salary range is $120,000 to $150,000.", 120000, 150000, "year"),
        ("$95,000 annually", 95000, 0, "year"),
        ("$2,000/week", 2000, 0, "week"),
        ("Day rate: $500 per day", 500, 0, "day"),
    ],
)
def test_period_from_text_reads_what_the_posting_states(text, low, high, period):
    assert period_from_text(text, low, high) == period


@pytest.mark.parametrize(
    "text, low, high",
    [
        # The amount next to the period isn't the job's salary (not even off by one).
        ("Pay rate range: 60-64/hour", 80, 0),
        ("$75-85/hr", 86, 0),
        ("$50 per month gym stipend", 1200, 3000),
        # Numbers next to periods that aren't pay.
        ("You'll work 40 hours per week, 3 days a week in office.", 40, 0),
        ("3 days a week in office", 3, 0),
        ("5+ years of experience", 5, 0),
        # No period at all.
        ("Salary: $1,200 - $3,000", 1200, 3000),
        ("", 60, 0),
        (None, 60, 0),
    ],
)
def test_period_from_text_needs_the_same_amount_and_a_stated_period(text, low, high):
    assert period_from_text(text, low, high) == ""


def test_period_from_text_without_a_salary():
    assert period_from_text("$60/hour", 0, 0) == ""


@pytest.mark.parametrize(
    "low, high, period",
    [
        (64, 0, "hour"),
        (0, 90, "hour"),
        (250, 299, "hour"),
        # Everything else is taken as yearly unless something says otherwise.
        (300, 0, "year"),
        (1200, 3000, "year"),
        (120_000, 150_000, "year"),
        (0, 0, ""),
    ],
)
def test_estimate_period_takes_small_amounts_as_hourly_and_the_rest_as_yearly(low, high, period):
    assert estimate_period(low, high) == period


def test_salary_period_prefers_the_site_then_the_text_then_an_estimate():
    # The site says.
    assert salary_period("Monthly", "$60/hour", 60, 0) == ("month", False)
    # The posting says.
    assert salary_period("", "Pay: $60 - $65 per hour", 60, 65) == ("hour", False)
    # Only the amount tells.
    assert salary_period("", "Great benefits.", 64, 0) == ("hour", True)
    assert salary_period("", None, 140000, 0) == ("year", True)
    # Nothing says: taken as yearly.
    assert salary_period("", "Great benefits.", 1200, 3000) == ("year", True)
    # But a stated period still wins.
    assert salary_period("", "$1,200 - $3,000 per month", 1200, 3000) == ("month", False)
    # No salary, no period (even if the site sends one).
    assert salary_period("Hourly", "$60/hour", 0, 0) == ("", False)


@pytest.mark.parametrize("case", json.loads(SALARY_FORMATS.read_text())["per_year"],
                         ids=lambda c: f"{c['low']}-{c['high']}/{c['period']}")
def test_yearly_amounts_match_the_dashboards(case):
    # With no period, the assumed one: under $300 hourly, else yearly.
    assert yearly_amounts(case["low"], case["high"], case["period"]) == case["yearly"]
