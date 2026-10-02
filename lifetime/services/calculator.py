"""Calendar arithmetic independent of Flask, persistence, and time zones."""

from calendar import monthrange
from datetime import date
import math
import re


def validate_birth_date(raw: str, today: date) -> date:
    if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ValueError("invalid_date")
    try:
        birth = date.fromisoformat(raw)
    except ValueError as error:
        raise ValueError("invalid_date") from error
    if birth > today:
        raise ValueError("future_date")
    return birth


def _add_months(start: date, months: int) -> date:
    number = start.year * 12 + start.month - 1 + months
    year, month = divmod(number, 12)
    month += 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))


def calculate(birth_date: date, expectancy: float, today: date) -> dict:
    """Use Feb 28 anniversaries in non-leap years for a Feb 29 birth.

    The fractional age uses the actual length of the current birthday year.
    scenario_years describes the reference horizon, never remaining lifespan.
    """
    if birth_date > today:
        raise ValueError("future_date")
    if isinstance(expectancy, bool) or not math.isfinite(expectancy) or not 0 < expectancy < 130:
        raise ValueError("invalid_expectancy")
    months = (today.year - birth_date.year) * 12 + today.month - birth_date.month
    if _add_months(birth_date, months) > today:
        months -= 1
    years, remaining_months = divmod(months, 12)
    days = (today - _add_months(birth_date, months)).days
    birthday = _add_months(birth_date, years * 12)
    next_birthday = _add_months(birth_date, (years + 1) * 12)
    fractional_age = years + (today - birthday).days / (next_birthday - birthday).days
    lived_days = (today - birth_date).days
    return {
        "age_years": years,
        "age_months": remaining_months,
        "age_days": days,
        "lived_days": lived_days,
        "lived_weeks": lived_days // 7,
        "expectancy": expectancy,
        "progress_percent": min(100.0, fractional_age / expectancy * 100),
        "beyond_reference": fractional_age > expectancy,
        "scenario_years": max(0.0, expectancy - fractional_age),
    }
