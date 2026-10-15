"""Evergreen dates for the synthetic demo data.

Every generator under data/fabric-iq writes one fixed snapshot dated BASE, so the
data never changes between runs and `--check` stays meaningful. Left as-is, that
snapshot ages: renewals "maturing in 30 days" mature, then lapse into the past.

This module moves the whole snapshot forward to the current week at read time.
The offset is a whole number of weeks, so every relationship in the data holds:
days-to-maturity, ages, month-over-month series and even weekdays are unchanged;
only the calendar moves. The same module is inlined into the Fabric load
notebook (data/fabric-iq/deploy_fabric.py), so the agent's Fabric IQ tables and
the app agree on the date.

    MRC_EVERGREEN=off       disable (serve the snapshot exactly as generated)
    MRC_AS_OF=YYYY-MM-DD    pin the as-of date (snapped back to a BASE weekday)
"""

from __future__ import annotations

import calendar
import copy
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

BASE = date(2026, 8, 3)

_FULL = list(calendar.month_name)[1:]
_ABBR = [m[:3] for m in _FULL]
_MON = "|".join(_FULL + ["Sept"] + _ABBR)
_LONE = "|".join(m for m in _FULL if m != "May")  # "may" is far more often a verb
_IDX = {**{m: i + 1 for i, m in enumerate(_FULL)}, **{m: i + 1 for i, m in enumerate(_ABBR)}, "Sept": 9}

_RX = re.compile(
    r"(?P<iso>(?<![\w-])(?P<y>(?:19|20)\d\d)-(?P<m>0[1-9]|1[0-2])-(?P<d>[0-3]\d)(?=T\d|(?![\w-])))"
    r"|(?P<ym>(?<![\w-])(?P<ymy>(?:19|20)\d\d)-(?P<ymm>0[1-9]|1[0-2])(?![\w-]))"
    rf"|(?P<dm>\b(?P<dmd>[0-3]?\d)(?P<dms>st|nd|rd|th)? (?P<dmm>{_MON})\b(?P<dmy>,? (?:19|20)\d\d\b)?)"
    rf"|(?P<md>\b(?P<mdm>{_MON})(?P<mdp>\.?) (?P<mdd>[0-3]?\d)(?P<mds>st|nd|rd|th)?\b(?P<mdy>,? (?:19|20)\d\d\b)?)"
    rf"|(?P<my>\b(?P<mym>{_MON}) (?P<myy>(?:19|20)\d\d)\b)"
    rf"|(?P<mo>\b(?P<mon>{_LONE})\b)"
)


def offset_days(today: date | None = None) -> int:
    """Whole weeks between BASE and today (UTC); never negative."""
    if os.getenv("MRC_EVERGREEN", "on").strip().lower() in ("0", "off", "false", "no"):
        return 0
    pinned = os.getenv("MRC_AS_OF", "").strip()
    now = date.fromisoformat(pinned) if pinned else (today or datetime.now(timezone.utc).date())
    return max(0, (now - BASE).days // 7 * 7)


def as_of(days: int | None = None) -> date:
    return BASE + timedelta(days=offset_days() if days is None else days)


def _months(days: int) -> int:
    a = BASE + timedelta(days=days)
    return (a.year * 12 + a.month) - (BASE.year * 12 + BASE.month)


def _add_months(y: int, m: int, n: int) -> tuple[int, int]:
    k = y * 12 + (m - 1) + n
    return k // 12, k % 12 + 1


def _name(orig: str, month: int) -> str:
    if orig in _FULL:
        return _FULL[month - 1]
    if orig == "Sept" and month == 9:
        return "Sept"
    return _ABBR[month - 1]


def _ordinal(n: int) -> str:
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _year_of(month: int, day: int, year_text: str | None) -> int | None:
    """The explicit year, or the one that puts a bare "14 August" nearest BASE."""
    if year_text:
        return int(re.sub(r"\D", "", year_text))
    best = None
    for y in (BASE.year - 1, BASE.year, BASE.year + 1):
        try:
            gap = abs((date(y, month, day) - BASE).days)
        except ValueError:
            continue
        if best is None or gap < best[0]:
            best = (gap, y)
    return best[1] if best else None


def shift_text(text: str, days: int | None = None) -> str:
    """Move every date written in `text` forward by `days` (default: the current offset)."""
    if days is None:
        days = offset_days()
    if not days or not text:
        return text
    months = _months(days)

    def sub(mt: re.Match) -> str:
        g = mt.groupdict()
        try:
            if g["iso"]:
                return (date(int(g["y"]), int(g["m"]), int(g["d"])) + timedelta(days=days)).isoformat()
            if g["ym"]:
                y, m = _add_months(int(g["ymy"]), int(g["ymm"]), months)
                return f"{y:04d}-{m:02d}"
            if g["dm"] or g["md"]:
                key = "dm" if g["dm"] else "md"
                mon_txt, day_txt, suf, yr = g[f"{key}m"], g[f"{key}d"], g[f"{key}s"], g[f"{key}y"]
                month = _IDX[mon_txt]
                year = _year_of(month, int(day_txt), yr)
                if year is None:
                    return mt.group(0)
                d = date(year, month, int(day_txt)) + timedelta(days=days)
                name = _name(mon_txt, d.month)
                sfx = _ordinal(d.day) if suf else ""
                ytxt = f"{yr[:-4]}{d.year}" if yr else ""
                if key == "dm":
                    return f"{d.day}{sfx} {name}{ytxt}"
                return f"{name}{g['mdp']} {d.day}{sfx}{ytxt}"
            if g["my"]:
                y, m = _add_months(int(g["myy"]), _IDX[g["mym"]], months)
                return f"{_name(g['mym'], m)} {y}"
            if g["mo"]:
                _, m = _add_months(BASE.year, _IDX[g["mon"]], months)
                return _FULL[m - 1]
        except ValueError:
            pass
        return mt.group(0)

    return _RX.sub(sub, text)


def shift_obj(obj: Any, days: int | None = None) -> Any:
    """A shifted deep copy of a JSON-like structure."""
    if days is None:
        days = offset_days()
    if isinstance(obj, str):
        return shift_text(obj, days)
    if isinstance(obj, dict):
        return {k: shift_obj(v, days) for k, v in obj.items()}
    if isinstance(obj, list):
        return [shift_obj(v, days) for v in obj]
    return obj


# --------------------------------------------------------------------------- #
# In-place refresh of the bundled data
#
# The engines index the bundles at import (dicts of row references), so the rows
# are rewritten in place rather than replaced: every index keeps pointing at the
# same row objects and sees the new dates. A pristine copy of each tracked
# structure is kept so a refresh always shifts from the original snapshot.
# --------------------------------------------------------------------------- #
_tracked: list[tuple[Any, Any]] = []
_hooks: list[Callable[[], None]] = []
_applied = 0


def track(live: Any) -> None:
    _tracked.append((live, copy.deepcopy(live)))


def on_refresh(fn: Callable[[], None]) -> None:
    _hooks.append(fn)


def _rewrite(live: Any, pristine: Any, days: int) -> None:
    items = pristine.items() if isinstance(pristine, dict) else enumerate(pristine)
    for k, v in items:
        if isinstance(v, str):
            live[k] = shift_text(v, days)
        elif isinstance(v, (dict, list)):
            _rewrite(live[k], v, days)


def ensure_current() -> int:
    """Shift the tracked data to the current week if it has moved; returns the offset."""
    global _applied
    days = offset_days()
    if days != _applied:
        for live, pristine in _tracked:
            _rewrite(live, pristine, days)
        _applied = days
        for fn in _hooks:
            fn()
    return days
