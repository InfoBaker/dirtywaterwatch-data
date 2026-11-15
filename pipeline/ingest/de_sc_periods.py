"""Observation periods for the advisories Delaware's map and DES's beach and bloom layers show with no dates
(ingest/de_dnrec_recwater.py, ingest/sc_des_advisories.py). Each read that lists the advisory extends the current
period; a read after an unread gap longer than the confirmation horizon (build/status.py CONFIRM_DAYS) opens a new
period, so a later read that lists the same advisory again never confirms the unread gap (verify3 P1-1).
build/status.py colours each period on its own, keyed on these sources and raw.listed_periods."""
from __future__ import annotations

from datetime import datetime, timedelta

GAP_DAYS = 14          # build/status.py CONFIRM_DAYS


def _t(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def extend(periods: list | None, at: str, first: str, last: str | None) -> list[dict]:
    """The periods after a read at `at` that lists the advisory. `first` is the first read (or the authority's start)
    and `last` the previous read that listed it, for a record saved before periods were kept."""
    periods = [dict(p) for p in periods] if periods else [{"from": first, "to": last or first}]
    cur = periods[-1]
    if _t(at) - _t(cur["to"]) > timedelta(days=GAP_DAYS):
        periods.append({"from": at, "to": at})
    elif _t(at) > _t(cur["to"]):
        cur["to"] = at
    return periods
