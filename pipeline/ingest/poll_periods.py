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


def revise_place(r: dict, at: str, *, name, lat, lon, county=None) -> bool:
    """The layer corrected the advisory's name or point under the same id (verification P2-4): the current values
    replace the saved ones (points already rounded to 0.001 degree), the earlier ones are kept in
    raw.place_revisions with the read that changed them. True when anything changed."""
    new = {"waterbody_text": name, "lat": lat, "lon": lon}
    old = {k: r.get(k) for k in new}
    changed = {k: v for k, v in new.items() if v is not None and v != old[k]}
    if county is not None and county != r["raw"].get("county"):
        changed["county"] = county
    if not changed:
        return False
    r["raw"].setdefault("place_revisions", []).append(
        {"read_at": at, "was": {k: (r["raw"].get(k) if k == "county" else old[k]) for k in changed}})
    for k, v in changed.items():
        if k == "county":
            r["raw"]["county"] = v
        else:
            r[k] = v
    return True
