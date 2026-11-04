"""NJ CSO Group shared notification site (njcsonotifications.com): rainfall-based "CSO event
likely / unlikely" per permittee -> data/build/nj-cso-likely.json (a snapshot for the rain-likely
rule to read; not a feed: it writes no events file).

Source
  https://njcsonotifications.com/?handler=Status (registry row nj-njcso-group-interim-outlook):
  undocumented JSON behind the "Combined Sewer Overflow Notification System (interim)" page, which
  re-polls it every 300 s. 15 NJPDES CSO permits (the PVSC district, the Bergen County towns,
  Elizabeth, Perth Amboy). Per permittee: 1-hour (shortWindow) and 4-hour (longWindow) rainfall
  totals with an isExceeded flag, alertLevel / alertLevelLabel ('CSO event unlikely' ...), twelve
  hourly totals and the time of the latest observation; overall lastUpdatedLabel, isStale,
  isHistorical, exceededCount, monitoredCount. Rain is from Iowa Environmental Mesonet gridded
  estimates. The site says: "This site indicates when an overflow is likely, not that one has
  occurred." It names no operator, has no terms and keeps no history; its times are labels with no
  year ('Nov 2, 12:00 PM'), so they are kept as labels and our own fetch time is recorded beside
  them. Nothing here is a reported discharge.

Output
  {source, url, label, disclaimer, ok, error, fetched_at (this run), last_ok_at, source_last_updated_label,
   source_is_stale, source_is_historical, exceeded_count, monitored_count,
   permittees: [{npdes_permit, name, discharger_id, permittee_id, exceeded (either window),
                 alert_level, alert_label, short_window {hours: 1, total_in, label, exceeded},
                 long_window {hours: 4, total_in, label, exceeded}, recent_hourly [{hour_label, total_in}],
                 recent_hourly_total_label, latest_observation_label, fetched_at}]}
  The raw response is saved (data/raw/nj-cso-likely/) when it changed. A failed or malformed fetch
  keeps the previous permittees with ok false, the error and the old last_ok_at, so a reader can
  tell a stale snapshot.

History
  data/build/nj-cso-likely-history.json: {source, updated_at, observations: {permit: [[fetched_at, exceeded,
  short_in, long_in, short_exceeded, long_exceeded, observation_label], ...]}}, one row per successful run (our fetch
  time; the site's own observation label, a time with no year; exceeded null when the site says its
  snapshot is stale or historical), the last 90 days. The site keeps none, so this is what lets
  build/rain_likely.py turn the flag into the rain-likely caution with its 48-hour tail and replay it. When the
  file is missing it is rebuilt from the saved raw responses.

Run from pipeline/:  python -m ingest.nj_cso_likely
"""
from __future__ import annotations

import hashlib
import sys
import time

import requests

from common import BROWSER_HEADERS, BUILD_DIR, HEADERS, ROOT, now_iso, read_json, save_raw, write_json

SOURCE_ID = "nj-cso-likely"
URL = "https://njcsonotifications.com/?handler=Status"
PAGE_URL = "https://njcsonotifications.com/"
OUT = BUILD_DIR / "nj-cso-likely.json"
LABEL = "rain-based likelihood from the permittees' shared site, not a measured or reported overflow"
DISCLAIMER = "This site indicates when an overflow is likely, not that one has occurred."
WINDOW_HOURS = {"shortWindow": 1, "longWindow": 4}
HISTORY = BUILD_DIR / "nj-cso-likely-history.json"
HISTORY_DAYS = 90


def fetch() -> tuple[dict | None, bytes | None, str | None]:
    err = None
    for i, hdr in enumerate([HEADERS, HEADERS, {**BROWSER_HEADERS, "Accept": "application/json"}]):
        try:
            r = requests.get(URL, headers=hdr, timeout=60)
            r.raise_for_status()
            js = r.json()
            if not isinstance(js, dict) or not isinstance(js.get("permittees"), list) or not js["permittees"]:
                raise ValueError(f"no permittees: {str(js)[:200]}")
            return js, r.content, None
        except (requests.RequestException, ValueError) as e:
            err = f"{type(e).__name__}: {e}"
            time.sleep(2 * (i + 1))
    return None, None, err


def num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def window(w, hours: int) -> dict:
    w = w if isinstance(w, dict) else {}
    return {"hours": hours, "total_in": num(w.get("totalInches")), "label": w.get("totalLabel"),
            "exceeded": w.get("isExceeded") if isinstance(w.get("isExceeded"), bool) else None}


def permittee_rows(js: dict, fetched_at: str) -> list[dict]:
    disc = {r["npdes_permit"]: r for r in (read_json(ROOT / "research/nj/dischargers.json", []) or [])
            if r.get("npdes_permit")}
    rows = []
    for p in js.get("permittees") or []:
        if not isinstance(p, dict):
            continue
        permit = (p.get("permitNumber") or "").strip() or None
        sw, lw = window(p.get("shortWindow"), 1), window(p.get("longWindow"), 4)
        flags = [x for x in (sw["exceeded"], lw["exceeded"]) if x is not None]
        rows.append({
            "npdes_permit": permit, "name": p.get("name"), "discharger_id": (disc.get(permit) or {}).get("id"),
            "permittee_id": p.get("permitteeId"),
            "exceeded": any(flags) if flags else None,
            "alert_level": p.get("alertLevel"), "alert_label": p.get("alertLevelLabel"),
            "short_window": sw, "long_window": lw,
            "recent_hourly": [{"hour_label": h.get("hourLabel"), "total_in": num(h.get("totalInches"))}
                              for h in (p.get("recentHourlyTotals") or []) if isinstance(h, dict)],
            "recent_hourly_total_label": p.get("recentHourlyTotalLabel"),
            "latest_observation_label": p.get("latestObservationLabel"),
            "fetched_at": fetched_at,
        })
    rows.sort(key=lambda r: r["npdes_permit"] or "")
    return rows


def observe(hist: dict | None, rows: list[dict], fetched_at: str, usable: bool = True) -> dict:
    """The history with one observation per permit for this run: [fetched_at, exceeded, short_in, long_in,
    short_exceeded, long_exceeded, the site's observation label];
    exceeded None when the snapshot is not usable (the site says stale or historical). Rows older than
    HISTORY_DAYS before fetched_at are dropped; a repeated fetch time is not added twice."""
    from datetime import datetime, timedelta
    hist = dict(hist or {})
    obs = {k: list(v) for k, v in (hist.get("observations") or {}).items()}
    for r in rows:
        if not r.get("npdes_permit"):
            continue
        seq = obs.setdefault(r["npdes_permit"], [])
        if seq and seq[-1][0] == fetched_at:
            continue
        sw, lw = r.get("short_window") or {}, r.get("long_window") or {}
        seq.append([fetched_at, r.get("exceeded") if usable else None, sw.get("total_in"), lw.get("total_in"),
                    sw.get("exceeded") if usable else None, lw.get("exceeded") if usable else None,
                    r.get("latest_observation_label")])
    cut = (datetime.fromisoformat(fetched_at.replace("Z", "+00:00")) - timedelta(days=HISTORY_DAYS)).isoformat()
    cut = cut.replace("+00:00", "Z")
    obs = {k: sorted(x for x in v if x[0] >= cut) for k, v in obs.items()}
    return {"source": SOURCE_ID, "url": PAGE_URL, "updated_at": fetched_at,
            "note": "per permit: [our fetch time, the site's exceeded flag (null: site stale or historical), "
                    "1-hour inches, 4-hour inches, 1-hour flag, 4-hour flag, the site's observation label]",
            "observations": {k: v for k, v in sorted(obs.items()) if v}}


def history_from_raw(raw_dir=None) -> dict:
    """The history rebuilt from the saved raw responses (data/raw/nj-cso-likely/<UTC stamp>.json)."""
    import json
    from common import RAW_DIR
    raw_dir = raw_dir or RAW_DIR / SOURCE_ID
    hist: dict = {}
    for p in sorted(raw_dir.glob("*.json")) if raw_dir.exists() else []:
        st = p.stem
        if len(st) != 16 or st[8] != "T":
            continue
        at = f"{st[0:4]}-{st[4:6]}-{st[6:8]}T{st[9:11]}:{st[11:13]}:{st[13:15]}Z"
        try:
            js = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(js, dict):
            continue
        hist = observe(hist, permittee_rows(js, at), at, usable=not (js.get("isStale") or js.get("isHistorical")))
    return hist


def main(argv=None) -> int:
    prev = read_json(OUT, {}) or {}
    fetched_at = now_iso()
    js, content, err = fetch()
    base = {"source": "NJ CSO Group 'Combined Sewer Overflow Notification System (interim)'", "url": URL,
            "page_url": PAGE_URL, "registry_ids": ["nj-njcso-group-interim-outlook"], "label": LABEL,
            "disclaimer": DISCLAIMER, "fetched_at": fetched_at}
    if err:
        write_json(OUT, {**prev, **base, "ok": False, "error": err, "last_ok_at": prev.get("last_ok_at"),
                         "permittees": prev.get("permittees", [])})
        print(f"{SOURCE_ID}: fetch failed, previous snapshot kept: {err}", file=sys.stderr)
        return 1
    h = hashlib.sha256(content).hexdigest()
    if prev.get("raw_hash") != h:
        save_raw(SOURCE_ID, content, "json")
    rows = permittee_rows(js, fetched_at)
    out = {**base, "ok": True, "error": None, "last_ok_at": fetched_at, "raw_hash": h,
           "source_last_updated_label": js.get("lastUpdatedLabel"), "source_is_stale": js.get("isStale"),
           "source_is_historical": js.get("isHistorical"), "source_as_of_label": js.get("asOfLabel"),
           "exceeded_count": js.get("exceededCount"), "monitored_count": js.get("monitoredCount"),
           "count": len(rows), "permittees": rows}
    write_json(OUT, out)
    prev_hist = read_json(HISTORY, None)
    if prev_hist is None:
        prev_hist = history_from_raw()
    write_json(HISTORY, observe(prev_hist, rows, fetched_at,
                                usable=not (js.get("isStale") or js.get("isHistorical"))))
    n_ex = sum(1 for r in rows if r["exceeded"])
    print(f"{SOURCE_ID}: {len(rows)} permittees, {n_ex} with a rainfall window exceeded "
          f"(source updated {js.get('lastUpdatedLabel')}, stale {js.get('isStale')}) -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
