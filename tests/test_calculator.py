from datetime import date
import unittest

from lifetime.services.calculator import calculate, validate_birth_date


class CalendarTests(unittest.TestCase):
    def test_exact_calendar_days_and_weeks(self):
        result = calculate(date(2000, 1, 31), 80, date(2024, 3, 1))
        self.assertEqual((result["age_years"], result["age_months"], result["age_days"]), (24, 1, 1))
        self.assertEqual(result["lived_days"], (date(2024, 3, 1) - date(2000, 1, 31)).days)
        self.assertEqual(result["lived_weeks"], result["lived_days"] // 7)

    def test_leap_birth_anniversary(self):
        before = calculate(date(2000, 2, 29), 80, date(2023, 2, 27))
        birthday = calculate(date(2000, 2, 29), 80, date(2023, 2, 28))
        leap = calculate(date(2000, 2, 29), 80, date(2024, 2, 28))
        self.assertEqual(before["age_years"], 22)
        self.assertEqual((birthday["age_years"], birthday["age_months"], birthday["age_days"]), (23, 0, 0))
        self.assertEqual(leap["age_years"], 23)
        self.assertEqual(calculate(date(2000, 2, 29), 80, date(2024, 2, 29))["age_years"], 24)

    def test_horizon_clamps_without_negative_lifespan(self):
        result = calculate(date(1920, 10, 3), 75.5, date(2026, 10, 3))
        self.assertTrue(result["beyond_reference"])
        self.assertEqual(result["progress_percent"], 100)
        self.assertEqual(result["scenario_years"], 0)
        self.assertNotIn("death_date", result)

    def test_same_day_and_exact_reference(self):
        newborn = calculate(date(2026, 10, 3), 75, date(2026, 10, 3))
        self.assertEqual(newborn["lived_days"], 0)
        self.assertEqual(newborn["progress_percent"], 0)
        exact = calculate(date(1951, 10, 3), 75, date(2026, 10, 3))
        self.assertFalse(exact["beyond_reference"])
        self.assertEqual(exact["scenario_years"], 0)

    def test_invalid_and_future_dates(self):
        for raw in ("2023-02-29", "2020-1-01", "20200101", "2024-W01-1", "x", "", None):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "^invalid_date$"):
                validate_birth_date(raw, date(2026, 10, 3))
        with self.assertRaisesRegex(ValueError, "^future_date$"):
            validate_birth_date("2026-10-04", date(2026, 10, 3))

    def test_invalid_expectancy(self):
        for value in (0, -1, float("inf"), float("nan"), True, 130):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "^invalid_expectancy$"):
                calculate(date(2000, 1, 1), value, date(2026, 10, 3))
