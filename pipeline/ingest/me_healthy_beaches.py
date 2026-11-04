"""Maine Healthy Beaches (Maine DEP): coastal beach advisories and closures.

Source
  Two undocumented GeoJSON files behind the program's embedded ArcGIS web map
  (item 3733e3ddc4a44607996d08e9c498b404), plain GET, no key:
    mapdata_bma.geojson   one point per beach management area (66 + one empty feature) with
                          'Advisory Type' (Elevated Bacteria / Precautionary Rainfall / Closure /
                          No Active Advisory), 'Advisory Status', 'Advisory Start Date',
                          'Public Comment', 'Management Entity', EPA and database beach ids, and the
                          latest enterococcus result per site ('N. Site' ...).
    mapdata_site.geojson  one point per sampling site (85) with the latest result; archived for
                          context, not turned into events.
  maine.gov sits behind CloudFront and answers 403 to non-browser user agents, so every request
  here uses common.BROWSER_HEADERS.

Snapshot to history
  Each poll is a snapshot of what is posted now; the feed has no end times. data/build/me-mhb-state.json
  carries the advisories seen in earlier polls, so one advisory is ONE record across polls
  (started_at = 'Advisory Start Date'). Rules (apply_snapshot):
  - a snapshot that is not a dict with a 'features' list, has no named beach, or has fewer than half
    the previous poll's beaches, and any HTTP or JSON error, is a FAILED FETCH: ok=False with the
    error, previous records kept, state untouched (an advisory stays active across missed polls);
  - disappearance is not lifting: a beach missing from the snapshot (or with an empty 'Advisory
    Type') leaves its advisory active (raw.missing_polls), and build/status.py ages it out 14 days
    after the last confirmation (source_updated_at = last poll that showed it);
  - an advisory is lifted only when its beach is present with 'No Active Advisory' or a different
    advisory, and then only when the beach's status-history page lists it with an end (one row,
    same type, same start) or on the second consecutive such poll. ended_at = the earlier of the
    history end and the first poll that observed the lift; raw.ended_at_precision is 'minute' for
    the history end or 'poll' for the poll time, and raw.lift_observed_between keeps the interval
    (last poll showing it, first poll not showing it).
  - any other failed request in the run (site GeoJSON, a history page) makes the run ok=False
    with the error; the state still advances and the next complete run writes the records.

Backfill (--backfill)
  beach-status-history.html?beach=<name> per beach (server-rendered table, 2024 onward: status,
  start date/time, end date/time, comment; times are Maine local time). Parsed rows are kept in the
  state file, so later polls keep them without refetching. A page that fails to load falls back to
  the copy in research/me/raw/mhb-hist/ when there is one.

Mapping
  Elevated Bacteria -> beach_advisory, Precautionary Rainfall -> rain_advisory, Closure/Closed ->
  beach_closure; anything else that is not 'No Active Advisory' -> unknown with parse_error.
  advice_text is the program's own wording; rainfall advisories carry the portal's "avoid water
  contact for at least 24-48hrs after rainfall ceases" (advice_window_hours 48, the upper bound, and
  the basis notes the clock is rainfall end, which the feed does not give). These are beach
  advisories, never discharge events: no comment in 2024-2026 names sewage as the cause.
  water_slugs: the beach name is matched to an openboatlaunch water (data/waters-ne.csv) by name
  where one Maine water's name appears in the beach name and the town or bbox confirms it
  (water_match 'name'); otherwise, when exactly one bay/sound whose towns include the management
  entity has a bbox containing the beach point, that one (water_match 'inferred'); else none.

Lag and cadence
  Live: the feed changes when a management entity posts or lifts an advisory (results 'typically
  available the following day' after sampling). Season Memorial Day to Labor Day; poll hourly in
  season and daily otherwise (off-season every beach reads 'No Active Advisory').

Run from pipeline/:  python -m ingest.me_healthy_beaches [--backfill]
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse
from zoneinfo import ZoneInfo

import requests

from common import (BROWSER_HEADERS, BUILD_DIR, DATA_DIR, RAW_DIR, ROOT, event, now_iso, read_json,
                    save_raw, stamp, write_events, write_json)

SOURCE_ID = "me-healthy-beaches"
BASE = "https://apps.web.maine.gov/online/healthy_beaches"
BMA_URL = f"{BASE}/mapdata_bma.geojson"
SITE_URL = f"{BASE}/mapdata_site.geojson"
HISTORY_URL = f"{BASE}/public/beach-status-history.html?beach={{}}"
PORTAL_URL = f"{BASE}/public/index.html"
STATE_PATH = BUILD_DIR / "me-mhb-state.json"
RESEARCH_HIST = ROOT / "research" / "me" / "raw" / "mhb-hist"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "Maine Healthy Beaches (Maine DEP)"
HISTORY_START_YEAR = 2024

ADVICE = {
    "beach_advisory": (
        "Advisories are issued as a recommendation to the public to avoid water contact activities in "
        "areas where bacteria results have exceeded the BAV and the risk for water-related illness is "
        "greater. It is recommended that the public avoid all water contact activities at those "
        "locations when an advisory is issued.",
        None, "Maine Healthy Beaches: advisory stays until a follow-up sample is below the Beach Action "
              "Value (enterococci 104 MPN/100 mL)"),
    "rain_advisory": (
        "Moderate to heavy rainfall can increase bacteria levels at the beach. It is recommended to "
        "avoid water contact for at least 24-48hrs after rainfall ceases.",
        48, "Maine Healthy Beaches portal notice: 'at least 24-48hrs after rainfall ceases' (upper bound; "
            "counted from the end of rainfall, which the feed does not give)"),
    "beach_closure": (
        "A beach closure is more severe than an advisory. A closure includes the ability to keep people "
        "out of the water or close the beach to usage.",
        None, "Maine Healthy Beaches: closures are set by the municipality under a local ordinance"),
}


# --------------------------------------------------------------------------- helpers

def classify(advisory_type: str | None) -> str | None:
    """'Elevated Bacteria (Advisory)' -> beach_advisory ...; None for no advisory."""
    t = (advisory_type or "").strip().lower()
    if not t or "no active" in t:
        return None
    if "bacteria" in t:
        return "beach_advisory"
    if "rain" in t:
        return "rain_advisory"
    if "clos" in t:
        return "beach_closure"
    return "unknown"


def parse_when(text: str | None) -> tuple[str | None, str | None]:
    """Feed or page date text -> (ISO with Maine offset, precision). Accepts the RFC 2822 'GMT' form
    the feed uses for dates, 'MM/DD/YYYY hh:mm AM', 'MM/DD/YYYY' and ISO."""
    s = (text or "").strip()
    if not s:
        return None, None
    try:
        if re.search(r"[A-Za-z]{3},? \d{1,2} [A-Za-z]{3} \d{4}", s):
            dt = parsedate_to_datetime(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(TZ).isoformat(), "minute"
    except (TypeError, ValueError):
        pass
    for fmt, prec in (("%m/%d/%Y %I:%M %p", "minute"), ("%m/%d/%Y %H:%M", "minute"), ("%m/%d/%Y", "day"),
                      ("%Y-%m-%d %H:%M:%S", "minute"), ("%Y-%m-%dT%H:%M:%S", "minute"), ("%Y-%m-%d", "day")):
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if prec == "day":
            return dt.date().isoformat(), "day"
        return dt.replace(tzinfo=TZ).isoformat(), prec
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ).isoformat(), "minute"
    except ValueError:
        return None, None


def norm(s: str) -> str:
    s = html.unescape(s or "").lower().replace("&", " and ")
    s = re.sub(r"[’'`]", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def fetch(url: str, tries: int = 3) -> requests.Response:
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=BROWSER_HEADERS, timeout=60)
            r.raise_for_status()
            return r
        except requests.RequestException as e:  # noqa: PERF203
            last = e
            time.sleep(2 * (i + 1))
    raise last  # type: ignore[misc]


# --------------------------------------------------------------------------- water matching

class WaterMatcher:
    """Beach name/town -> openboatlaunch water slug (Maine), only where unambiguous."""

    SALT = {"bay", "sound"}

    def __init__(self):
        self.rows = []
        bbox = {}
        wj = read_json(DATA_DIR / "waters-me.json", {}) or {}
        for w in wj.get("waters", []):
            bbox[w["slug"]] = w.get("bbox")
        with open(DATA_DIR / "waters-ne.csv", newline="") as f:
            for r in csv.DictReader(f):
                if r["state"] != "ME":
                    continue
                towns = [t.strip() for t in (r["towns"] or "").split(";") if t.strip()]
                self.rows.append({"slug": r["slug"], "name": r["name"], "n": norm(r["name"]), "kind": r["kind"],
                                  "towns": {norm(t) for t in towns}, "bbox": bbox.get(r["slug"])})

    @staticmethod
    def _in_bbox(b, lon, lat, pad_deg=0.01) -> bool:
        if not b or lon is None or lat is None:
            return False
        return b[0] - pad_deg <= lon <= b[2] + pad_deg and b[1] - pad_deg <= lat <= b[3] + pad_deg

    def match(self, beach: str, town: str | None, lon: float | None, lat: float | None) -> tuple[list[str], str]:
        nb, nt = f" {norm(beach)} ", norm(town or "")
        # 1. a water's name inside the beach name ('York Harbor Beach' -> York Harbor), confirmed by
        #    town or bbox when several waters share the name.
        hits = [w for w in self.rows if len(w["n"].split()) >= 2 and f" {w['n']} " in nb]
        if hits:   # a same-named water must sit in the beach's town or around its point
            hits = [w for w in hits if nt in w["towns"] or self._in_bbox(w["bbox"], lon, lat, 0.02)]
            if len(hits) == 1:
                return [hits[0]["slug"]], "name"
        # 2. the one salt water whose bbox holds the beach point; when several do, the one whose
        #    towns include the management entity; when none does, the entity's one salt water
        #    within ~2 km of its bbox. Labelled 'inferred' (bbox, not shoreline geometry).
        salt = [w for w in self.rows if w["kind"] in self.SALT]
        cands = [w for w in salt if self._in_bbox(w["bbox"], lon, lat, 0.01)]
        if len(cands) > 1:
            cands = [w for w in cands if nt and nt in w["towns"]]
        elif not cands:
            cands = [w for w in salt if nt and nt in w["towns"] and self._in_bbox(w["bbox"], lon, lat, 0.02)]
        if len(cands) == 1:
            return [cands[0]["slug"]], "inferred"
        return [], "none"


# --------------------------------------------------------------------------- history pages

ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)


def parse_history_html(text: str) -> list[dict]:
    """Rows of the per-beach status history table."""
    out = []
    body = text.split("<tbody>", 1)[-1].split("</tbody>", 1)[0] if "<tbody>" in text else text
    for row in ROW_RE.findall(body):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in CELL_RE.findall(row)]
        if len(cells) < 6:
            continue
        out.append({"status": cells[0], "start_date": cells[1], "start_time": cells[2],
                    "end_date": cells[3], "end_time": cells[4], "comment": re.sub(r"\s+", " ", cells[5])})
    return out


def history_name(url: str | None, fallback: str) -> str:
    if url:
        q = parse_qs(urlparse(url).query).get("beach")
        if q:
            return q[0]
    return fallback


def fetch_history(beach_name: str, raw_dir: Path | None) -> tuple[list[dict] | None, str]:
    url = HISTORY_URL.format(quote_plus(beach_name))
    try:
        r = fetch(url)
        if raw_dir is not None:
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / (re.sub(r"[^A-Za-z0-9]+", "_", beach_name) + ".html")).write_bytes(r.content)
        return parse_history_html(r.text), "live"
    except requests.RequestException:
        p = RESEARCH_HIST / (re.sub(r"[^A-Za-z0-9]+", "_", beach_name) + ".html")
        if p.exists():
            return parse_history_html(p.read_text(errors="replace")), "research copy"
        return None, "failed"


# --------------------------------------------------------------------------- records

def beach_info(feat: dict) -> dict | None:
    p = feat.get("properties") or {}
    name = (p.get("Beach Management Area") or "").strip()
    if not name:
        return None
    lon, lat = (feat.get("geometry") or {}).get("coordinates", [None, None])[:2]
    if lon in (0, 0.0) and lat in (0, 0.0):
        lon = lat = None
    sites = []
    for i in range(1, 30):
        sid = p.get(f"{i}. Site")
        if sid:
            sites.append({"site": sid,
                          "result_mpn_100ml": p.get(f"{i}. Most Recent Enterococcus Bacteria Result (MPN/100mL)"),
                          "elevated": p.get(f"{i}. Elevated Bacteria"),
                          "collected": p.get(f"{i}. Most Recent Date Collected")})
    return {"name": name, "beach_id": (p.get("Database Beach ID") or "").strip() or None,
            "epa_beach_id": (p.get("EPA Beach ID") or "").strip() or None,
            "entity": (p.get("Management Entity") or "").strip() or None,
            "lon": lon, "lat": lat, "history_url": p.get("Beach Advisory Status History"),
            "info_url": p.get("Beach Info Page"), "sites": sites, "props": p}


def make_record(*, key: str, etype: str, status: str, beach: dict, started_at, ended_at, precision,
                comment, matcher: WaterMatcher, raw: dict, source_updated_at=None, parse_error=None,
                end_basis=None) -> dict:
    advice, window, basis = ADVICE.get(etype, (None, None, None))
    slugs, how = matcher.match(beach["name"], beach.get("entity"), beach.get("lon"), beach.get("lat"))
    raw = dict(raw)
    if end_basis:
        raw["ended_at_basis"] = end_basis
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type=etype, status=status,
        discharger_id=None, discharger_name=None,
        outfall_name=None, waterbody_text=beach["name"] if not beach.get("entity") or norm(beach["entity"]) in norm(beach["name"])
        else f"{beach['name']} ({beach['entity']})",
        water_slugs=slugs, water_match=how,
        lat=beach.get("lat"), lon=beach.get("lon"), coord_source="source" if beach.get("lat") else None,
        coord_precision_m=None,
        started_at=started_at, ended_at=ended_at, time_precision=precision,
        source_updated_at=source_updated_at,
        material=None,
        authority=AUTHORITY + (f"; posted by {beach['entity']}" if beach.get("entity") else ""),
        advice_text=(advice + (f" Program comment: \"{comment}\"" if comment else "")) if advice else (comment or None),
        advice_window_hours=window, advice_window_basis=basis,
        source_url=beach.get("history_url") or beach.get("info_url") or PORTAL_URL,
        raw=raw, parse_error=parse_error,
    )


def history_key(beach_id: str, etype: str, started_at: str | None) -> str:
    return f"{beach_id}:{etype}:{(started_at or 'nostart')[:16]}"


def rows_to_history(beach: dict, rows: list[dict], how: str) -> list[dict]:
    """Normalise parsed history rows into stored dicts (not yet event records)."""
    out = []
    for r in rows:
        start, sp = parse_when(f"{r['start_date']} {r['start_time']}".strip())
        if start is None:
            start, sp = parse_when(r["start_date"])
        end, _ = parse_when(f"{r['end_date']} {r['end_time']}".strip())
        if end is None and r.get("end_date"):
            end, _ = parse_when(r["end_date"])
        if start and int(start[:4]) < HISTORY_START_YEAR:
            continue
        out.append({"beach_id": beach["beach_id"] or norm(beach["name"]), "beach": beach["name"],
                    "status_text": r["status"], "event_type": classify(r["status"]) or "unknown",
                    "started_at": start, "precision": sp, "ended_at": end, "comment": r["comment"],
                    "row": r, "via": how})
    return out


# --------------------------------------------------------------------------- snapshot -> state

LIFT_CONFIRMATIONS = 2   # consecutive valid polls showing the beach without this advisory


def _clock() -> datetime:
    """Poll time (UTC); tests replace it."""
    return datetime.now(UTC).replace(microsecond=0)


def _dt(s: str | None) -> datetime | None:
    """ISO text (with offset, 'Z', or a bare date read as Maine midnight) -> aware datetime."""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def validate_snapshot(js, prev_count: int | None) -> tuple[list[dict] | None, str | None]:
    """The beaches of a BMA snapshot, or (None, reason) when it must be treated as a failed fetch:
    not a FeatureCollection-like dict, no named beach, or fewer than half the previous poll's beaches."""
    if not isinstance(js, dict) or not isinstance(js.get("features"), list):
        return None, "malformed snapshot: no 'features' list"
    named = [b for b in (beach_info(f) for f in js["features"] if isinstance(f, dict)) if b]
    if not named:
        return None, "empty snapshot: no named beach features"
    if prev_count and len(named) < prev_count / 2:
        return None, f"incomplete snapshot: {len(named)} beaches against {prev_count} in the previous poll"
    return named, None


def same_advisory(a: dict, h: dict) -> bool:
    """A history row is the live advisory `a` when type matches and the start matches to the minute
    (both timed) or to the day (either side known only to the day)."""
    start, hs = _dt(a.get("started_at")), _dt(h.get("started_at"))
    if h.get("event_type") != a.get("event_type") or not start or not hs:
        return False
    if a.get("precision") == "minute" and h.get("precision") == "minute":
        return abs((hs - start).total_seconds()) < 60
    return h["started_at"][:10] == a["started_at"][:10]


def confident_history_end(a: dict, rows: list[dict]) -> str | None:
    """The program's own end time for advisory `a`: only when exactly one history row is the same
    advisory and it gives an end not before its start."""
    m = [h for h in rows if same_advisory(a, h)]
    if len(m) != 1:
        return None
    hs, he = _dt(m[0].get("started_at")), _dt(m[0].get("ended_at"))
    return m[0]["ended_at"] if hs and he and he >= hs else None


def apply_snapshot(state: dict, beaches: dict[str, dict], now: datetime, history_lookup) -> list[str]:
    """Fold one valid snapshot into state['active'] / state['lifted']. Returns the errors of the run.

    - an advisory posted now is confirmed (last_seen = now, missing_polls 0, any pending lift cleared);
      the same beach and type with an earlier-or-equal start than its last confirmation is the same
      advisory with a revised start, not a new one;
    - a beach absent from the snapshot, or present with no 'Advisory Type' value, is no observation:
      its advisory stays active (missing_polls + 1) and ages out in build/status.py from last_seen;
    - a beach present with 'No Active Advisory' or with a different advisory is a lift observation.
      The advisory is lifted when the beach's history page lists it with an end (matched confidently),
      or on the LIFT_CONFIRMATIONS-th consecutive observation. ended_at is the earlier of that history
      end and the poll that first observed the lift; raw records which, and the observed interval.
    """
    errors: list[str] = []
    now_utc = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    now_local = now.astimezone(TZ).isoformat()
    active, lifted = state["active"], state["lifted"]

    present: set[str] = set()
    posted: dict[str, str] = {}          # beach_id -> key of the advisory posted now
    for bid, b in beaches.items():
        p = b["props"]
        t = (p.get("Advisory Type") or "").strip()
        if not t:
            continue
        present.add(bid)
        etype = classify(t)
        if etype is None:
            continue
        start, prec = parse_when(p.get("Advisory Start Date"))
        key = history_key(bid, etype, start)
        if key not in active:
            for k, x in active.items():   # revised start of an advisory already being followed
                if x["beach_id"] == bid and x["event_type"] == etype and k not in posted.values():
                    s_new, seen = _dt(start), _dt(x.get("last_seen"))
                    if s_new and seen and s_new <= seen:
                        x.setdefault("start_revisions", []).append(
                            {"from": x.get("start_text"), "to": p.get("Advisory Start Date"), "at": now_utc})
                        key = k
                        break
        a = active.get(key) or {"beach_id": bid, "event_type": etype, "first_seen": now_utc, "missing_polls": 0}
        a.update({"advisory_type": t, "advisory_status": p.get("Advisory Status"),
                  "start_text": p.get("Advisory Start Date"), "started_at": start, "precision": prec,
                  "comment": (p.get("Public Comment") or "").strip(), "last_seen": now_utc,
                  "last_seen_local": now_local, "missing_polls": 0, "sites": b["sites"]})
        a.pop("pending_lift", None)
        active[key] = a
        posted[bid] = key

    for key in list(active):
        a = active[key]
        bid = a["beach_id"]
        if posted.get(bid) == key:
            continue
        if bid not in present:
            a["missing_polls"] = a.get("missing_polls", 0) + 1
            continue
        observed = f"other advisory posted ({posted[bid]})" if bid in posted else "No Active Advisory"
        pl = a.setdefault("pending_lift", {"first_observed_at": now_local, "first_observed_utc": now_utc,
                                           "observations": 0, "observed": observed})
        pl["observations"] += 1
        b = beaches.get(bid) or state["beaches"].get(bid) or {}
        rows, how = history_lookup(b) if b else (None, "failed")
        if how != "live":
            errors.append(f"history page for {b.get('name', bid)}: {how}")
        for h in rows_to_history(b, rows or [], how) if b else []:
            state["history"][history_key(h["beach_id"], h["event_type"], h["started_at"])] = h
        hist_end = confident_history_end(a, rows_to_history(b, rows or [], how)) if b else None
        if not hist_end and pl["observations"] < LIFT_CONFIRMATIONS:
            continue
        cands = [(pl["first_observed_at"], "poll", "poll")]
        if hist_end:
            cands.append((hist_end, "status history page", "minute"))
        ended, basis, prec = min(cands, key=lambda c: _dt(c[0]))
        a.update({"ended_at": ended, "ended_at_basis": basis, "ended_at_precision": prec,
                  "history_end": hist_end, "lift_observed": observed,
                  "lift_observed_between": [a.get("last_seen_local") or a.get("last_seen"), pl["first_observed_at"]]})
        lifted[key] = active.pop(key)
    return errors


# --------------------------------------------------------------------------- records

def build_records(state: dict, beaches: dict[str, dict], matcher: WaterMatcher) -> list[dict]:
    """History rows, then live advisories; a history row confidently matching a live advisory is
    folded into it (raw.history_row) instead of being a second record."""
    records: dict[str, dict] = {}
    live = list(state["lifted"].items()) + list(state["active"].items())
    matched_hist: dict[str, str] = {}
    for key, a in live:
        m = [hk for hk, h in state["history"].items() if h["beach_id"] == a["beach_id"] and same_advisory(a, h)]
        if len(m) == 1:
            matched_hist[m[0]] = key
    for key, h in sorted(state["history"].items()):
        if key in matched_hist:
            continue
        b = beaches.get(h["beach_id"]) or state["beaches"].get(h["beach_id"]) or {"name": h["beach"]}
        perr = None
        if h["event_type"] == "unknown":
            perr = f"unrecognised advisory status {h['status_text']!r}"
        if not h["started_at"]:
            perr = (perr + "; " if perr else "") + "no start date"
        if h["ended_at"]:
            status = "advisory_lifted"
        else:
            status = "unknown"
            perr = (perr + "; " if perr else "") + "history row has no end and the live feed does not show it"
        records[key] = make_record(
            key=key, etype=h["event_type"], status=status, beach=b, started_at=h["started_at"],
            ended_at=h["ended_at"], precision=h["precision"], comment=h["comment"], matcher=matcher,
            raw={"from": "beach-status-history.html", "via": h.get("via"), **h["row"],
                 "epa_beach_id": b.get("epa_beach_id"), "management_entity": b.get("entity")},
            parse_error=perr)
    hist_by_live = {v: k for k, v in matched_hist.items()}
    for bucket, status in (("lifted", "advisory_lifted"), ("active", "advisory_active")):
        for key, a in state[bucket].items():
            b = beaches.get(a["beach_id"]) or state["beaches"].get(a["beach_id"]) or {"name": a["beach_id"]}
            perr = None
            if a["event_type"] == "unknown":
                perr = f"unrecognised Advisory Type {a.get('advisory_type')!r}"
            if not a["started_at"]:
                perr = (perr + "; " if perr else "") + f"unparsed Advisory Start Date {a.get('start_text')!r}"
            raw = {"from": "mapdata_bma.geojson", "advisory_type": a.get("advisory_type"),
                   "advisory_status": a.get("advisory_status"), "advisory_start_date": a.get("start_text"),
                   "public_comment": a["comment"], "first_seen": a["first_seen"], "last_seen": a["last_seen"],
                   "missing_polls": a.get("missing_polls", 0), "sites": a.get("sites"),
                   "epa_beach_id": b.get("epa_beach_id"), "management_entity": b.get("entity")}
            for k in ("pending_lift", "start_revisions", "ended_at_precision", "lift_observed",
                      "lift_observed_between", "history_end"):
                if a.get(k) is not None:
                    raw[k] = a[k]
            ended, basis = a.get("ended_at"), a.get("ended_at_basis")
            hk = hist_by_live.get(key)
            if hk:
                h = state["history"][hk]
                raw["history_row"] = hk
                if (status == "advisory_lifted" and h.get("ended_at") and _dt(h["ended_at"]) and ended
                        and _dt(h["started_at"]) <= _dt(h["ended_at"]) < _dt(ended)):
                    ended, basis = h["ended_at"], "status history page"
                    raw["ended_at_precision"] = "minute"
                elif status == "advisory_active" and h.get("ended_at"):
                    raw["history_end"] = h["ended_at"]   # page shows an end the feed does not yet
            records[key] = make_record(
                key=key, etype=a["event_type"], status=status, beach=b, started_at=a["started_at"],
                ended_at=ended if status == "advisory_lifted" else None, precision=a["precision"],
                comment=a["comment"], matcher=matcher, end_basis=basis if status == "advisory_lifted" else None,
                raw=raw, source_updated_at=a["last_seen"], parse_error=perr)
    return sorted(records.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backfill", action="store_true", help="scrape every beach's status-history page (2024 onward)")
    args = ap.parse_args(argv)

    now = _clock()
    poll_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    state = read_json(STATE_PATH, {}) or {}
    for k in ("active", "lifted", "history", "beaches"):
        state.setdefault(k, {})

    # ---- the snapshot; anything short of a complete one is a failed fetch that changes nothing
    snap_error = None
    try:
        r = fetch(BMA_URL)
        save_raw(SOURCE_ID, r.content, "bma.geojson")
        named, snap_error = validate_snapshot(r.json(), state.get("last_feature_count"))
    except (requests.RequestException, ValueError) as e:
        named, snap_error = None, f"{type(e).__name__}: {e}"
    if snap_error:
        state["failed_polls"] = state.get("failed_polls", 0) + 1
        state["last_failure"] = {"at": poll_at, "error": snap_error}
        write_json(STATE_PATH, state)
        write_events(SOURCE_ID, [], ok=False, error=snap_error,
                     meta={"active_now": len(state["active"]), "last_poll_at": state.get("last_poll_at")})
        print(f"{SOURCE_ID}: snapshot rejected, records kept: {snap_error}", file=sys.stderr)
        return 1

    errors: list[str] = []
    try:
        rs = fetch(SITE_URL)
        save_raw(SOURCE_ID, rs.content, "site.geojson")
    except requests.RequestException as e:
        errors.append(f"site geojson: {type(e).__name__}: {e}")

    matcher = WaterMatcher()
    beaches = {}
    for b in named:
        bid = b["beach_id"] or norm(b["name"])
        beaches[bid] = b
        state["beaches"][bid] = {k: v for k, v in b.items() if k != "props"}

    # ---- backfill from the per-beach history pages
    if args.backfill:
        raw_dir = RAW_DIR / SOURCE_ID / f"history-{stamp()}"
        fetched = {"live": 0, "research copy": 0, "failed": 0}
        for bid, b in beaches.items():
            rows, how = fetch_history(history_name(b["history_url"], b["name"]), raw_dir)
            fetched[how] += 1
            if how != "live":
                errors.append(f"history page for {b['name']}: {how}")
            for h in rows_to_history(b, rows or [], how):
                state["history"][history_key(h["beach_id"], h["event_type"], h["started_at"])] = h
            time.sleep(0.3)
        state["history_fetched_at"] = poll_at
        state["history_fetch"] = fetched
        print(f"backfill: {fetched}, {len(state['history'])} history rows stored")

    def lookup(b: dict):
        return fetch_history(history_name(b.get("history_url"), b["name"]), None)

    errors += apply_snapshot(state, beaches, now, lookup)
    records = build_records(state, beaches, matcher)

    state["last_poll_at"] = poll_at
    state["last_feature_count"] = len(beaches)
    state["last_poll_active"] = len(state["active"])
    state["failed_polls"] = 0
    write_json(STATE_PATH, state)

    meta = {"beaches_in_feed": len(beaches), "active_now": len(state["active"]),
            "pending_lifts": sum(1 for a in state["active"].values() if a.get("pending_lift")),
            "history_rows": len(state["history"]), "history_fetched_at": state.get("history_fetched_at"),
            "poll_cadence": "hourly Memorial Day-Labor Day, daily otherwise"}
    if errors:
        # a partial run never refreshes the feed's clock: previous records stay, ok=False with the error
        # (the state file has the new snapshot, so the next complete run writes it out)
        path = write_events(SOURCE_ID, records, ok=False, error="; ".join(errors), meta=meta)
        print(f"{SOURCE_ID}: partial run, records kept: {'; '.join(errors)} -> {path}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, records, meta=meta)
    print(f"{SOURCE_ID}: {len(records)} records ({len(state['active'])} active now) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
