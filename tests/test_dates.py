"""Date filters: local-time ranges for every mode, field names and day keys."""
import datetime as dt
import time
import unittest

from tests.base import TempHomeCase  # noqa: F401
from core import dates


def ts(y, m, d, hh=0, mm=0):
    return time.mktime(dt.datetime(y, m, d, hh, mm).timetuple())


NOW = ts(2026, 11, 9, 15, 30)   # a Monday afternoon


class DateRangeTest(unittest.TestCase):
    def test_today_and_yesterday(self):
        self.assertEqual(dates.range_for("today", now=NOW), (ts(2026, 11, 9), ts(2026, 11, 10)))
        self.assertEqual(dates.range_for("yesterday", now=NOW), (ts(2026, 11, 8), ts(2026, 11, 9)))

    def test_last_7_and_30_days_include_today(self):
        self.assertEqual(dates.range_for("7d", now=NOW), (ts(2026, 11, 3), ts(2026, 11, 10)))
        self.assertEqual(dates.range_for("30d", now=NOW), (ts(2026, 10, 11), ts(2026, 11, 10)))

    def test_this_month_pick_month_pick_year(self):
        self.assertEqual(dates.range_for("month", now=NOW), (ts(2026, 11, 1), ts(2026, 12, 1)))
        self.assertEqual(dates.range_for("ym", "2025-12"), (ts(2025, 12, 1), ts(2026, 1, 1)))
        self.assertEqual(dates.range_for("year", "2024"), (ts(2024, 1, 1), ts(2025, 1, 1)))

    def test_on_and_between(self):
        self.assertEqual(dates.range_for("on", "2026-02-28"), (ts(2026, 2, 28), ts(2026, 3, 1)))
        self.assertEqual(dates.range_for("between", "2026-01-10", "2026-01-12"), (ts(2026, 1, 10), ts(2026, 1, 13)))
        self.assertEqual(dates.range_for("between", "2026-01-12", "2026-01-10"), (ts(2026, 1, 10), ts(2026, 1, 13)))

    def test_leap_day(self):
        self.assertEqual(dates.range_for("on", "2028-02-29"), (ts(2028, 2, 29), ts(2028, 3, 1)))

    def test_filtering_with_a_range(self):
        start, end = dates.range_for("on", "2026-03-15")
        inside, edge_before, edge_after = ts(2026, 3, 15, 23, 59), ts(2026, 3, 14, 23, 59), ts(2026, 3, 16)
        self.assertTrue(start <= inside < end)
        self.assertFalse(start <= edge_before < end)
        self.assertFalse(start <= edge_after < end)

    def test_bad_input(self):
        self.assertIsNone(dates.range_for(""))
        for args in (("nope",), ("on", "2026-13-01"), ("ym", "2026"), ("year", "abc")):
            with self.assertRaises(ValueError):
                dates.range_for(*args)

    def test_fields_and_day_keys(self):
        self.assertEqual(dates.field_column("modified"), "mtime")
        self.assertEqual(dates.field_column("created"), "ctime")
        self.assertEqual(dates.field_column("accessed"), "atime")
        self.assertEqual(dates.field_column(None), "mtime")
        with self.assertRaises(ValueError):
            dates.field_column("mtime; DROP TABLE files")
        self.assertEqual(dates.day_key(ts(2026, 5, 4, 12)), "2026-05-04")


if __name__ == "__main__":
    unittest.main()
