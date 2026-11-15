"""Listing periods for advisories polled from a map layer with no dates (Kansas's KDHE HAB layer, Missouri's DNR HAB
map). Each read that lists the advisory extends the current period; a read after a gap longer than the confirmation
horizon (build/status.py CONFIRM_DAYS) starts a new period, so a later listing never confirms the unread gap
(verification pass 2026-11-15 P1-1). build/status.py colours each period on its own, keyed on raw.listed_periods."""
from __future__ import annotations

from datetime import datetime, timedelta

GAP_DAYS = 14          # build/status.py CONFIRM_DAYS


def _t(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def seen(r: dict, at: str) -> None:
    """Record a read at `at` that lists the advisory on record r (its raw._last_seen_in_source is the previous read)."""
    raw = r["raw"]
    periods = raw.get("listed_periods")
    if not periods:      # an earlier save: one period from the start to the last listing read
        periods = [{"from": r["started_at"], "to": raw.get("_last_seen_in_source") or r["started_at"]}]
    last = periods[-1]
    if _t(at) - _t(last["to"]) > timedelta(days=GAP_DAYS):
        periods.append({"from": at, "to": at})
    elif _t(at) > _t(last["to"]):
        last["to"] = at
    raw["listed_periods"] = periods
    raw["_last_seen_in_source"] = at
