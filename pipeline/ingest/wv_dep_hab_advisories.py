"""West Virginia DEP's algal bloom advisory map -> data/build/events/wv-dep-hab-advisories.json.

Source
  The map service behind DEP's Harmful Algal Blooms page (https://dep.wv.gov/WWE/watershed/Algae/Pages/
  Harmful-Algal-Blooms.aspx): https://tagis.dep.wv.gov/arcgis/rest/services/webMercator/algae_advisories/MapServer
  ("Algae advisories in West Virginia"), three layers: 1 'Algal Bloom Location' (points), 2 'Algal Bloom Segments'
  (lines along a stream), 3 'Algal Bloom Area' (polygons on a lake). Fields: OBJECTID, Advisory (text), and
  Date_Observed (DateObserved on layer 3), an esri date. Read 2026-11-14: every layer answered and held no row (DEP's
  page also says no advisory is in effect; its table of reported blooms was last updated in August 2023). The layers
  carry no person, no water name and no edit date.

Records (a map of what is in effect, read as a snapshot)
  - One record per row of any layer (source_record_id '<layer>-<OBJECTID>'), event_type hab_advisory (blooms, never
    sewage), status advisory_active while the map shows it; advice_text is DEP's Advisory text in its words.
  - started_at is the first read of the map that showed it (time_precision poll): DEP gives the day the bloom was
    observed (raw.date_observed, a date on Eastern time), not the day an advisory was issued, so no issue date is
    invented; reported_at, published_at and source_updated_at stay null. A row that leaves the map and comes back is
    a new episode; the earlier one is kept under '<key>~2'. raw._last_seen_in_source is the latest read
    that showed it, so the status build keeps it in effect while the map shows it.
  - A row no longer on a map the module could read is lifted at that read (advisory_lifted, ended_at the read,
    raw.ended_at_precision 'poll'), an upper bound, not DEP's lift time. A layer that answers with an error makes the
    run ok=False: the records are kept and nothing is lifted; so does a layer that answers only part of its rows
    (exceededTransferLimit). The Advisory text is cut before it is saved anywhere (scrub_advisory: common.scrub_text,
    then every street house number, then every sentence naming who reported, sampled or can be called; text that
    cannot be cut to the advice alone is withheld).
  - Placement by the agency's own geometry only: a point's position, a segment's middle vertex, an area's vertex mean,
    rounded to three decimals (coord_source 'agency_layer'); raw.geometry_kind says which. No water name is invented.

Run from pipeline/: python -m ingest.wv_dep_hab_advisories [--file saved.json] [--at 2026-11-14T12:00:00Z]
Cadence: with the refresh (daily is enough; the map changes rarely).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import common
from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "wv-dep-hab-advisories"
SERVICE = "https://tagis.dep.wv.gov/arcgis/rest/services/webMercator/algae_advisories/MapServer"
PAGE = "https://dep.wv.gov/WWE/watershed/Algae/Pages/Harmful-Algal-Blooms.aspx"
LAYERS = {1: "point", 2: "segment", 3: "area"}
STATE_PATH = BUILD_DIR / "wv-dep-hab-advisories-state.json"
AUTHORITY = "West Virginia Department of Environmental Protection (algal bloom advisory map)"
TZ = "America/New_York"
START_BASIS = ("the first read of DEP's map that showed it: DEP gives the day the bloom was observed, not the day an "
               "advisory was issued")
WINDOW_BASIS = "in effect while DEP's map shows it; DEP sets no fixed period"


def place(kind: str, g: dict) -> tuple[float | None, float | None]:
    try:
        if kind == "point":
            x, y = g["x"], g["y"]
        elif kind == "segment":
            pts = [p for path in g.get("paths") or [] for p in path]
            x, y = pts[len(pts) // 2]
        else:
            pts = [p for ring in g.get("rings") or [] for p in ring]
            x, y = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        return round(float(y), 3), round(float(x), 3)
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        return None, None


STREET = (r"(?:Lane|Ln|Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Court|Ct|Way|Boulevard|Blvd|Circle|Cir|Place|Pl|Pike|"
          r"Highway|Hwy|Route|Rte|Trail|Trl|Terrace|Ter|Parkway|Pkwy|Hollow|Holw|Ridge|Loop|Alley|Square|Sq)")
# a house number before a street: '123 Example Lane', '12B N. Example St' (any street, not only a residence's)
HOUSE_NUMBER_RE = re.compile(rf"(?<![\w.,/:-])\d{{1,6}}[A-Za-z]?(?=[ ]{{1,2}}(?:[NSEW]\.?[ ]{{1,2}})?(?:[A-Z0-9][\w'.-]*[ ]{{1,2}}){{1,4}}{STREET}\b)")
# a clause that names who reported, sampled or can be called: the whole sentence is cut
PERSON_CLAUSE_RE = re.compile(
    r"(?i:\b(?:submitted|reported|sampled|collected|photographed|found|called in|sent|provided|observed|noticed)[ ]+by\b)"
    r"|(?i:\b(?:contact(?:ing)?|call(?:ing)?))[ ]+(?!(?i:with)\b)(?:[A-Z]|(?i:us|the)\b|\[|\d)"
    r"|(?i:\b(?:e-?mail|courtesy of|thanks to|resident|residents|homeowner|landowner|property owner|neighbou?r)\b)"
    r"|\b(?:Mr|Mrs|Ms|Miss|Dr)\.?[ ]+[A-Z]|\[(?:name|phone|email) removed\]")
# sentence breaks, not after a title or an initial ('Mrs. Example', 'N. Example Rd')
SENTENCE_RE = re.compile(r"(?<=[.!?;])(?<!\bMr\.)(?<!\bMrs\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bSt\.)(?<!\b[A-Z]\.)[ ]+")
WITHHELD = "(DEP's advisory text is withheld here: it could not be cut to the advisory alone)"


def scrub_advisory(text: str) -> str | None:
    """DEP's Advisory text, cut to the advice before anything is saved: common.scrub_text (e-mails, phones, contact
    names), then every street house number, then every sentence that names who reported, sampled or can be called.
    Text left with a capitalised name pair after 'by' or with nothing but removals is withheld (WITHHELD)."""
    t = " ".join(str(text or "").split())
    if not t:
        return None
    t = HOUSE_NUMBER_RE.sub(common.HOUSE_NUMBER_REMOVED, common.scrub_text(t))
    kept = [x for x in SENTENCE_RE.split(t) if x and not PERSON_CLAUSE_RE.search(x)]
    out = " ".join(kept).strip()
    if not re.search(r"[A-Za-z]{3}", out.replace(common.HOUSE_NUMBER_REMOVED, "")) or \
            re.search(r"\bby[ ]+[A-Z][a-z]+[ ]+[A-Z][a-z]+", out):
        return WITHHELD
    return out


def observed(attrs: dict) -> tuple[str | None, str | None]:
    """(the observation as DEP stores it, an instant in UTC; the day it names). An esri date field is an instant; a
    value at exactly midnight UTC is a date entered with no time (the usual esri convention), so its day is the UTC
    date; any other instant is dated in Eastern time. Both are kept: the instant in raw.date_observed_utc."""
    v = attrs.get("Date_Observed", attrs.get("DateObserved"))
    try:
        t = datetime.fromtimestamp(int(v) / 1000, UTC) if v not in (None, "") else None
    except (TypeError, ValueError, OverflowError):
        return None, None
    if t is None:
        return None, None
    day = t.date() if (t.hour, t.minute, t.second) == (0, 0, 0) else t.astimezone(ZoneInfo(TZ)).date()
    return t.strftime("%Y-%m-%dT%H:%M:%SZ"), day.isoformat()


def rows_of(answers: dict) -> dict[str, dict]:
    """{'<layer>-<OBJECTID>': {kind, advisory, date_observed, lat, lon}}; ValueError for a layer error."""
    out = {}
    for lid, kind in LAYERS.items():
        doc = answers.get(str(lid))
        if not isinstance(doc, dict) or "error" in doc or "features" not in doc:
            raise ValueError(f"layer {lid} did not answer with features: {str(doc)[:200]}")
        if doc.get("exceededTransferLimit"):
            # a page of a longer answer is not the map: no lift is read from it
            raise ValueError(f"layer {lid} answered only part of its rows (exceededTransferLimit)")
        for f in doc["features"]:
            a = f.get("attributes") or {}
            lat, lon = place(kind, f.get("geometry") or {})
            utc, day = observed(a)
            text = " ".join(str(a.get("Advisory") or "").split())
            out[f"{lid}-{a.get('OBJECTID')}"] = {"kind": kind, "advisory": scrub_advisory(text),
                                                 "date_observed": day, "date_observed_utc": utc, "lat": lat, "lon": lon}
    return out


def update(state: dict, current: dict, at: str) -> dict:
    items = state.setdefault("items", {})
    for k, it in items.items():
        if it.get("left_at") is None and k not in current:
            it["left_at"] = at
    for k, row in current.items():
        it = items.get(k)
        if it is not None and it.get("left_at"):
            # back on the map after leaving it: the earlier episode is kept under its own key
            n = 2
            while f"{k}~{n}" in items:
                n += 1
            items[f"{k}~{n}"] = it
            it = None
        if it is None:
            it = items[k] = {"first_seen": at}
        it.update(last_seen=at, **row)
    state["last_poll"] = {"at": at, "listed": sorted(current)}
    return state


def records(state: dict) -> list[dict]:
    out = []
    for k, it in sorted((state.get("items") or {}).items()):
        left = it.get("left_at")
        raw = {"layer_row": k.split("~")[0], "geometry_kind": it.get("kind"), "date_observed": it.get("date_observed"),
               "date_observed_utc": it.get("date_observed_utc"),
               "date_observed_basis": ("Date_Observed: DEP's observation of the bloom, stored as an instant "
                                       "(date_observed_utc); a value at midnight UTC is read as that date, any other "
                                       "instant as its Eastern date"),
               "first_seen_at": it["first_seen"], "_last_seen_in_source": it.get("last_seen"),
               "start_basis": START_BASIS, "time_zone": TZ, "advisory_noun": "Algal bloom advisory"}
        if left:
            raw.update(ended_at_precision="poll", end_basis="the first read of DEP's map that no longer showed it")
        adv = it.get("advisory")
        out.append(event(source_id=SOURCE_ID, source_record_id=k, event_type="hab_advisory",
                         status="advisory_lifted" if left else "advisory_active", waterbody_text=None,
                         water_slugs=[], water_match="none", lat=it.get("lat"), lon=it.get("lon"),
                         coord_source="agency_layer" if it.get("lat") is not None else None,
                         started_at=it["first_seen"], ended_at=left, time_precision="poll", reported_at=None,
                         published_at=None, source_updated_at=None, authority=AUTHORITY,
                         advice_text=f"West Virginia DEP algal bloom map: {adv}" if adv else "West Virginia DEP algal bloom map (no advisory text given)",
                         advice_window_hours=None, advice_window_basis=WINDOW_BASIS, source_url=PAGE, raw=raw))
        out[-1]["fetched_at"] = it.get("last_seen") or out[-1]["fetched_at"]
    return out


def fetch() -> dict:
    answers = {}
    for lid in LAYERS:
        r = requests.get(f"{SERVICE}/{lid}/query", headers=HEADERS, timeout=120,
                         params={"where": "1=1", "outFields": "OBJECTID,Advisory,Date_Observed" if lid != 3 else
                                 "OBJECTID,Advisory,DateObserved", "returnGeometry": "true", "outSR": "4326",
                                 "f": "json"})
        r.raise_for_status()
        answers[str(lid)] = r.json()
    return answers


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = argv[argv.index("--at") + 1] if "--at" in argv else now_iso()
    try:
        answers = json.loads(Path(argv[argv.index("--file") + 1]).read_text()) if "--file" in argv else fetch()
        current = rows_of(answers)
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    state = read_json(STATE_PATH, {}) or {}
    if "--file" not in argv and current and state.get("last_rows") != current:
        save_raw(SOURCE_ID, json.dumps({"fetched_at": at, "rows": current}, indent=1).encode(), "json")
    state["last_rows"] = current
    state = update(state, current, at)
    write_json(STATE_PATH, state)
    recs = records(state)
    meta = {"registry_ids": [SOURCE_ID], "url": SERVICE, "last_poll": state.get("last_poll"),
            "cadence": "with the refresh; the map lists only what is in effect"}
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {sum(1 for r in recs if r['status'] == 'advisory_active')} on the map; {len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
