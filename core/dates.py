"""Date filters in the user's local time zone. Ranges are [start, end) epoch seconds."""
import datetime as _dt
import time

MODES = ("on", "between", "today", "yesterday", "7d", "30d", "month", "ym", "year")
FIELDS = {"modified": "mtime", "created": "ctime", "accessed": "atime"}
DAY_S = 86400


def _local_midnight(d):
    """Why: day boundaries follow the local clock (DST days are 23 or 25 hours long)."""
    return time.mktime(_dt.datetime(d.year, d.month, d.day).timetuple())


def _parse_day(s):
    """Why: URL params carry plain YYYY-MM-DD dates."""
    return _dt.datetime.strptime(s, "%Y-%m-%d").date()


def _month_start(year, month):
    """Why: months are [1st of month, 1st of next month)."""
    return _dt.date(year, month, 1)


def _next_month(d):
    """Why: December rolls over into January of the next year."""
    return _dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def range_for(mode, a=None, b=None, now=None):
    """Why: one function turns every date-filter mode into numeric bounds; None means 'no date filter'."""
    if not mode:
        return None
    today = (_dt.datetime.fromtimestamp(now) if now else _dt.datetime.now()).date()
    one = _dt.timedelta(days=1)
    if mode == "today":
        start, end = today, today + one
    elif mode == "yesterday":
        start, end = today - one, today
    elif mode == "7d":
        start, end = today - 6 * one, today + one
    elif mode == "30d":
        start, end = today - 29 * one, today + one
    elif mode == "month":
        start = _month_start(today.year, today.month)
        end = _next_month(start)
    elif mode == "on":
        start = _parse_day(a)
        end = start + one
    elif mode == "between":
        start, last = _parse_day(a), _parse_day(b or a)
        if last < start:
            start, last = last, start
        end = last + one
    elif mode == "ym":
        y, m = (int(x) for x in a.split("-")[:2])
        start = _month_start(y, m)
        end = _next_month(start)
    elif mode == "year":
        y = int(a)
        start, end = _dt.date(y, 1, 1), _dt.date(y + 1, 1, 1)
    else:
        raise ValueError("Unknown date filter.")
    return _local_midnight(start), _local_midnight(end)


def field_column(name):
    """Why: the URL says modified/created/accessed; the index stores mtime/ctime/atime."""
    if name in (None, "", "modified"):
        return "mtime"
    if name not in FIELDS:
        raise ValueError("Unknown date field.")
    return FIELDS[name]


def day_key(ts):
    """Why: timeline and calendar group files by local calendar day."""
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
