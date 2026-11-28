"""Springfield Water and Sewer Commission's live CSO map (Aquasight) -> data/build/events/ma-springfield-aquasight.json

Source (registry ma-springfield-aquasight)
  The commission's public page https://springfieldalerts.com/Suez/index.php/map-of-cso-locations/ embeds the Aquasight
  (ADS Environmental Services) app at external.aquasight.io (APP_URL below). The app is an Angular shell over a
  DreamFactory API at https://api2.aquasight.io; each request carries the header X-Dreamfactory-API-Key with the key
  the app's own script holds (without it the API answers 400). The app reads three tables, all GET, each with a
  DreamFactory filter and answering {"resource": [...]}:
    ads_us_config   one row per outfall (24 on 2026-11-28): asset (CSO010, CSO015A, CSO036A ...), description,
                    address, latitude, longitude, discharge_to, affected_locations, avg_volume, note, row_create_time.
                    row_create_user (a staff name) is dropped on receipt and never kept.
    cso_status      the map's current status per outfall (noOverflow, overflowed, Overflowing ...) and last_updated.
    cso_status_log  one row per overflow: id, asset, start_timestamp, end_timestamp, checked, remarks. With no date
                    filter it is the whole history in one answer (2,134 rows, 2022-03-19 to 2026-11-26 on 2026-11-28).
  The state portal (ingest.ma_massdep) holds the same overflows a day or more later; this map is the current record.

The key
  Read at each run from the app's scripts: the shell's script addresses are resolved from the shell itself (the hashed
  names are never written here), and the key is the one apiKey next to serverUrl "https://api2.aquasight.io" (KEY_RE,
  bounded). It is held in memory only: never written to a file, a raw save, a log, meta or an error. No key, or two
  different keys, is a failed read (the previous records kept), never a guess. Requests go to external.aquasight.io and
  api2.aquasight.io only, GET only, the three tables above only, community springfield_ma_ads_us only; redirects are
  not followed.

Records (one cso record per log row, in ingest.ma_massdep's shape)
  - source_record_id the row id; permit MA0101613, discharger ma-springfield-wsc; event_type cso (the portal types every
    Springfield outfall, the plant's SPR042 included, as cso).
  - outfall_id the portal's spelling through CROSSWALK (CSO010 -> SPR010, CSO015A -> SPR015A, CSO036A -> SPR036A), each
    checked against the MassDEP CSOs layer and the ECHO registry (meta.crosswalk). An asset not in it keeps the map's
    own id and point (raw._outfall_note says so); no id is guessed.
  - Times: the map's local clock as printed, no zone stated; read as America/New_York to the minute. An hour that
    repeats when daylight time ends is read as its first occurrence, unless that puts the end before the start, when
    the end is read as the second (raw._time_note). A clock time that does not exist (the hour skipped in spring) or a
    garbled date (one row ends in the year 0023) is not read: parse_error, and an unread end leaves ended_at null.
  - status ended with ended_at from end_timestamp; ongoing when the row has no end. reported_at is the row's checked
    time (the map's own check time); published_at null (the map states none).
  - Volume: the map's pop-up prints the outfall's avg_volume for every event. The commission calls it its three-year
    average discharge per event, an estimate for its notice, not a measurement. It is carried (estimate_flag
    "estimated", raw.volume_method) only on events that started on or after the config row's row_create_time (the
    averages now shown date from 2026-01-12); an earlier event gets no volume, since another average applied then.
  - Place: ingest.mail.ma_common.place (the MassDEP CSOs layer as ma_massdep last cached it, the ECHO outfall registry,
    the portal waterbody crosswalk), as the e-mail notices and Somerville's rows are placed; else the map's own point.
  - advice_text: the map's own pop-up wording (the 314 CMR 16.04(10)(g) wording), 48 hours from the end.

One event, not two
  MassDEP's portal holds the same overflows. A log row and the portal's record of the same overflow (same permit and the
  same outfall, suffix included, the portal's start within LINK_MINUTES of the row's and not after the row's end) are
  one event: the row becomes duplicate_of the portal family's shown record (operator_mail.portal_families), one to
  one, closest first. A row with no end is never linked, so an overflow going on is never hidden. build/status.py
  (carry_map_ends) gives a shown portal record with no end the linked row's end. On the saved answers of 2026-11-28
  against the portal file of 2026-11-14, 1,286 rows link within 10 minutes (1,265 at the same minute); wider gaps are
  mostly the next overflow of the outfall (the portal's start at the row's end). The module sorts after ma_massdep and
  reads that run's events file; with no file, every row stands alone (meta.links says so).

Current status (meta.outfalls, never events)
  Per outfall: the status row as given and the map's own derived status (the app's rule: a noOverflow outfall with a
  log row in the last 56 hours shows "Overflow in Last 48 Hours"; one not updated in 12 hours, or missing from the
  status answer, shows "Data Not Received"). meta.data_not_received lists those outfalls so the gap is visible. A label
  is the map's own; none is a finding that the water is safe.

Failures: a failed request, no key, a non-JSON answer, a row of another community, an empty log, one under half the
  records held, or more than a tenth of its rows not built: ok=False, the previous records kept. A row that does not
  build keeps the previous version of its record (meta.kept_previous; health false). A failed status read writes the records with health false
  (partial) and says so in meta.
Run from pipeline/: python -m ingest.ma_springfield_aquasight [--files CONFIG STATUS LOG --out events.json]
Cadence: hourly with the refresh (Massachusetts is live).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events
from common import error_detail, error_text

SOURCE_ID = "ma-springfield-aquasight"
PAGE_URL = "https://springfieldalerts.com/Suez/index.php/map-of-cso-locations/"
APP_HOST = "external.aquasight.io"
API_HOST = "api2.aquasight.io"
APP_URL = (f"https://{APP_HOST}/bc4d3929-4468-4122-921f-e65b6b232476/cso-notification"
           "?selectedClient=ads_us&selectedCommunity=springfield_ma_ads_us")
API_BASE = f"https://{API_HOST}/api/v2/ace_ads/_table/"
COMMUNITY = "springfield_ma_ads_us"
TABLES = ("ads_us_config", "cso_status", "cso_status_log")
PERMIT = "MA0101613"
DISCHARGER_ID = "ma-springfield-wsc"
DISCHARGER = "Springfield Water and Sewer Commission"
AUTHORITY = "Springfield Water and Sewer Commission (CSO map, Aquasight)"
CREDIT = "Springfield Water and Sewer Commission, live CSO map (Aquasight)"
PORTAL_SOURCE = "ma-massdep"
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
SPEC = {"source_id": SOURCE_ID, "outfall_prefix": "SPR", "town": "SPRINGFIELD"}      # ma_common.place's lookups
LINK_MINUTES = 10               # a log row and a portal record of the same outfall this close in start are one overflow
SHRINK = 0.5                    # a log under this share of the records held is a failed read
MAX_UNBUILT = 0.1               # more than this share of rows that do not build is a failed read
STATUS_HOURS = 56               # the app asks cso_status and cso_status_log this far back
STALE_HOURS = 12                # the app shows "Data Not Received" for a noOverflow row not updated in this long
MAX_SCRIPTS = 8
MAX_SCRIPT_BYTES = 15_000_000
TIMEOUT = (20, 90)

# the key, next to the API's address in the app's environment object; bounded on both sides
KEY_RE = re.compile(r'serverUrl\s*:\s*"(https://[A-Za-z0-9.-]{1,100})"\s*,\s*apiKey\s*:\s*"([A-Za-z0-9]{16,128})"')
SCRIPT_NAME = re.compile(r"^[A-Za-z0-9._-]{1,120}\.js$")
STAMP_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$")

# The map's asset -> the portal's outfall id. Checked 2026-11-28 against the MassDEP CSOs layer (DEP_OUTFL_ SPR007 to
# SPR049, 015A and 015B apart, 036A) and the ECHO registry (MA0101613 outfalls 007 to 049; ECHO has 015 and 036 without
# a suffix). The portal's own records use exactly these ids.
CROSSWALK = {f"CSO{n}": f"SPR{n}" for n in (
    "007", "008", "010", "011", "012", "013", "014", "015A", "015B", "016", "017", "018", "019", "024", "025", "034",
    "035", "036A", "037", "042", "045", "046", "048", "049")}

# the map's legend (the app's labels for its status codes)
LABELS = {"noOverflow": "No Overflow in Last 48 Hours", "overflowed": "Overflow in Last 48 Hours",
          "Overflowing": "Overflow Occurring", "notActive": "Data Not Received", "notMonitered": "Not Monitored",
          "rgNotMonitored": "Rain gauge Not Monitored"}
STATUS_NOTE = ("The map's own labels, as the app shows them. A label reports the operator's equipment; it is not a "
               "finding that the water is safe.")

# the map's pop-up wording (the 314 CMR 16.04(10)(g) wording), as printed
ADVICE = ("Avoid contact with these water bodies for 48 hours after the discharge or overflow ceases due to increased "
          "health risks from bacteria and other pollutants. See website for more information on whether specific "
          "resource areas, such as bathing beaches,are affected.")
ADVICE_BASIS = "the operator's CSO map pop-up (the wording of 314 CMR 16.04(10)(g))"
TIME_BASIS = "local clock as printed, no zone stated; read as America/New_York"
VOLUME_METHOD = ("Springfield Water and Sewer Commission's estimate for its notice: the outfall's three-year average "
                 "discharge per event, which its map shows for every event at the outfall; not a measurement of this "
                 "event")
PERSONAL_CONFIG_KEYS = re.compile(r"(?i)(_user|user_|^user$|created_by|modified_by|email|phone)")


class ReadError(Exception):
    """A read that cannot be used (the pipeline's own words only; never a key or an answer's text)."""


# ---------------------------------------------------------------- the key

class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.base, self.srcs = None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "base" and a.get("href") and self.base is None:
            self.base = a["href"]
        elif tag == "script" and a.get("src"):
            self.srcs.append(a["src"])


def script_urls(shell: str, page_url: str = APP_URL) -> list[str]:
    """The app's script addresses from its shell, resolved against its <base href>, on APP_HOST only, main first."""
    p = _Scripts()
    p.feed(shell)
    base = urljoin(page_url, p.base or "")
    out = []
    for src in p.srcs:
        u = urljoin(base, src)
        parts = urlsplit(u)
        name = parts.path.rsplit("/", 1)[-1]
        if parts.scheme == "https" and parts.hostname == APP_HOST and SCRIPT_NAME.match(name) and u not in out:
            out.append(u)
    out.sort(key=lambda u: (not u.rsplit("/", 1)[-1].startswith("main."), u))
    return out[:MAX_SCRIPTS]


def find_key(texts: list[str]) -> str:
    """The one apiKey paired with the API's address in the scripts. Raises ReadError (never quoting a key) when there
    is none or more than one."""
    keys = set()
    for t in texts:
        for m in KEY_RE.finditer(t):
            if urlsplit(m.group(1)).hostname == API_HOST:
                keys.add(m.group(2))
    if not keys:
        raise ReadError(f"no API key for {API_HOST} found in the app's scripts")
    if len(keys) > 1:
        raise ReadError(f"the app's scripts carry {len(keys)} different API keys for {API_HOST}; none is used")
    return keys.pop()


def _get(sess, url: str, headers: dict | None = None) -> requests.Response:
    host = urlsplit(url).hostname
    if host not in (APP_HOST, API_HOST) or not url.startswith("https://"):
        raise ReadError("a request outside the map's two hosts was refused")
    r = sess.get(url, headers={**HEADERS, **(headers or {})}, timeout=TIMEOUT, allow_redirects=False)
    if 300 <= r.status_code < 400:
        raise ReadError(f"HTTP {r.status_code} (a redirect, not followed) at {host}")
    r.raise_for_status()
    return r


def fetch_key(sess) -> str:
    shell = _get(sess, APP_URL).text
    urls = script_urls(shell)
    if not urls:
        raise ReadError("the app's shell lists no scripts")
    texts, size = [], 0
    for u in urls:
        t = _get(sess, u).text
        size += len(t)
        if size > MAX_SCRIPT_BYTES:
            raise ReadError("the app's scripts are larger than expected")
        texts.append(t)
    return find_key(texts)


# ---------------------------------------------------------------- the three tables

def table_url(table: str, flt: str, order: str | None = None) -> str:
    if table not in TABLES:
        raise ReadError("a table outside the map's three was refused")
    q = {"filter": flt}
    if order:
        q["order"] = order
    return API_BASE + table + "?" + urlencode(q, quote_via=quote)


def fetch_table(sess, key: str, table: str, flt: str, order: str | None = None) -> list[dict]:
    r = _get(sess, table_url(table, flt, order),
             headers={"X-Dreamfactory-API-Key": key, "Content-Type": "application/json",
                      "Accept": "application/json"})
    try:
        doc = r.json()
    except ValueError:
        raise ReadError(f"{table}: the answer is not JSON") from None
    rows = doc.get("resource") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
        raise ReadError(f"{table}: the answer has no resource list")
    return rows


def clean_config(rows: list[dict]) -> list[dict]:
    """The config rows without the fields that name a person (row_create_user)."""
    return [{k: v for k, v in r.items() if not PERSONAL_CONFIG_KEYS.search(k)} for r in rows]


def own_community(rows: list[dict], table: str) -> list[dict]:
    other = [r for r in rows if r.get("community_id") != COMMUNITY]
    if other:
        raise ReadError(f"{table}: {len(other)} rows of another community")
    return rows


def fetch_all(sess, now: datetime) -> tuple[list[dict], list[dict] | None, list[dict], str | None]:
    """(config, status or None, log, status error). The key lives only inside this call."""
    key = fetch_key(sess)
    c = f"(community_id = {COMMUNITY})"
    config = clean_config(own_community(fetch_table(
        sess, key, "ads_us_config", f"(latest_flag = 1) AND (stat = 1) AND {c}"), "ads_us_config"))
    log = own_community(fetch_table(sess, key, "cso_status_log", c, "start_timestamp desc"), "cso_status_log")
    since = (now.astimezone(TZ) - timedelta(hours=STATUS_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        status = own_community(fetch_table(sess, key, "cso_status", f"{c} AND (last_updated >= {since})"),
                               "cso_status")
        serr = None
    except Exception as e:  # noqa: BLE001 - the status table is meta only
        status, serr = None, error_text(e)
    del key
    return config, status, log, serr


# ---------------------------------------------------------------- times

def local_time(s, later: bool = False) -> tuple[datetime | None, str | None]:
    """'2026-11-26 21:10:00' -> an America/New_York datetime, else (None, why). later: a repeated hour (daylight time's
    end) read as its second occurrence. The why never quotes the text."""
    if s is None or (isinstance(s, str) and not s.strip()):
        return None, "blank"
    m = STAMP_RE.match(str(s).strip())
    if not m:
        return None, "not a date and time"
    y, mo, d, hh, mi, ss = (int(x) if x else 0 for x in m.groups())
    if not 2000 <= y <= 2100:
        return None, "the year is out of range"
    try:
        dt = datetime(y, mo, d, hh, mi, ss, tzinfo=TZ, fold=1 if later else 0)
    except (ValueError, OverflowError):
        return None, "not a valid date"
    if dt.astimezone(UTC).astimezone(TZ).replace(tzinfo=None, fold=0) != dt.replace(tzinfo=None, fold=0):
        return None, "a clock time that does not exist that day (the hour skipped when daylight time begins)"
    return dt, None


def utc(dt: datetime) -> datetime:
    """The instant (two datetimes of one zone compare by their wall clocks, which ignores a repeated hour)."""
    return dt.astimezone(UTC)


def ambiguous(dt: datetime) -> bool:
    return dt.replace(fold=0).utcoffset() != dt.replace(fold=1).utcoffset()


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


# ---------------------------------------------------------------- records

def outfall_of(asset) -> tuple[str | None, int | None, str]:
    """(portal outfall id or None, number, suffix) for the map's asset."""
    a = str(asset or "").strip().upper()
    m = re.match(r"^CSO0*(\d{1,3})([A-Z]?)$", a)
    num, suf = (int(m.group(1)), m.group(2)) if m else (None, "")
    return CROSSWALK.get(a), num, suf


def to_record(row: dict, cfg: dict | None, ctx: dict, fetched_at: str) -> dict:
    from ingest.mail.ma_common import place
    from ingest import ma_massdep as M
    problems = []
    asset = row.get("asset")
    oid, num, suf = outfall_of(asset)
    raw = {"row": {k: row.get(k) for k in ("asset", "start_timestamp", "end_timestamp", "checked", "remarks")},
           "state": "MA", "time_zone": TZ_NAME, "time_basis": TIME_BASIS, "_channel": "web",
           "reported_at_basis": "the map's own check time (the log row's checked field)"}
    if cfg:
        raw.update({"discharge_to": cfg.get("discharge_to"), "affected_locations": cfg.get("affected_locations"),
                    "map_location": cfg.get("address"), "map_description": cfg.get("description")})
    else:
        problems.append("the asset has no row in the map's outfall list")

    start, why = local_time(row.get("start_timestamp"))
    if start is None:
        problems.append(f"start not read ({why})")
    end = None
    if row.get("end_timestamp") not in (None, ""):
        end, why = local_time(row.get("end_timestamp"))
        if end is None:
            problems.append(f"end not read ({why})")
        elif start is not None and utc(end) < utc(start):
            later, _ = local_time(row.get("end_timestamp"), later=True)
            if later is not None and ambiguous(end) and utc(later) >= utc(start):
                end = later
                raw["_time_note"] = ("the end falls in the hour repeated when daylight time ends; read as its second "
                                     "occurrence, since the first is before the start")
            else:
                problems.append("end before the start")
                end = None
        if start is not None and end is not None and ambiguous(start) and "_time_note" not in raw:
            raw["_time_note"] = "the start falls in the hour repeated when daylight time ends; read as its first occurrence"
    if row.get("end_timestamp") in (None, ""):
        status = "ongoing" if start is not None else "unknown"
    elif end is not None:
        status = "ended"
    else:
        status = "ended"
        raw["_end_note"] = "the map gives an end that is not read: ended, end time not confirmed"
    checked, _ = local_time(row.get("checked"))

    # volume: the outfall's current three-year average, only on events since that average was set
    vol = vol_text = None
    avg = (cfg or {}).get("avg_volume")
    since, _ = local_time((cfg or {}).get("row_create_time"))
    if isinstance(avg, (int, float)) and not isinstance(avg, bool) and avg > 0 and since is not None and start is not None:
        if utc(start) >= utc(since):
            vol, vol_text = int(avg), f"{int(avg):,} gallons"
            raw["volume_method"] = VOLUME_METHOD
            raw["volume_basis"] = (f"the map's average for this outfall (note \"{(cfg or {}).get('note')}\", set "
                                   f"{cfg.get('row_create_time')} local time)")
        else:
            raw["_volume_note"] = (f"the map's three-year average for this outfall was set {cfg.get('row_create_time')}, "
                                   "after this event; the average shown then is not on the map, so no volume is carried")

    lay = echo = None
    slugs, wmatch, wnote = [], "none", {}
    water = (cfg or {}).get("discharge_to") or None
    if oid:
        lay, echo, slugs, wmatch, wnote = place(ctx, SPEC, PERMIT, num, suf, water)
        raw["_outfall_key"], raw["_outfall_suffix"] = num, suf
    else:
        slugs, wmatch, wnote = M.resolve_water([("map", water)], SPEC["town"], None,
                                               ctx.get("crosswalk") or {}, ctx.get("waters") or {})
        raw["_outfall_note"] = ("not in the crosswalk to the portal's outfall ids: the map's own id and point are kept"
                                if asset else "the row names no outfall")
    if wnote:
        raw["_water"] = wnote
    lat = lon = coord_source = None
    if lay and lay.get("lat") is not None:
        lat, lon, coord_source = round(lay["lat"], 6), round(lay["lon"], 6), "outfall_layer"
        raw["_coords"] = f"MassDEP CSOs layer DEP_OUTFL_ {lay['dep_id']} (locations are estimates)"
    elif echo and echo.get("lat") is not None:
        lat, lon, coord_source = echo["lat"], echo["lon"], "outfall_layer"
        raw["_coords"] = f"EPA ECHO CSO inventory {echo['npdes_permit']} outfall {echo['outfall']}"
    elif cfg and isinstance(cfg.get("latitude"), (int, float)) and isinstance(cfg.get("longitude"), (int, float)) \
            and 41 < cfg["latitude"] < 43.1 and -73.6 < cfg["longitude"] < -69.8:
        lat, lon, coord_source = round(cfg["latitude"], 6), round(cfg["longitude"], 6), "source"
        raw["_coords"] = "the map's own point for the outfall"

    return event(
        source_id=SOURCE_ID, source_record_id=str(row.get("id")), event_type="cso", status=status,
        discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER, npdes_permit=PERMIT,
        outfall_id=oid or (str(asset).strip() if asset else None),
        outfall_name=(lay or {}).get("address") or (cfg or {}).get("address"),
        waterbody_text=water, water_slugs=slugs, water_match=wmatch,
        lat=lat, lon=lon, coord_source=coord_source,
        started_at=iso(start), ended_at=iso(end), time_precision="minute" if start else None,
        reported_at=iso(checked), published_at=None, source_updated_at=None, fetched_at=fetched_at,
        volume_gal=vol, volume_text=vol_text, estimate_flag="estimated" if vol is not None else "unknown",
        authority=AUTHORITY, advice_text=ADVICE if start else None, advice_window_hours=48 if start else None,
        advice_window_basis=ADVICE_BASIS if start else None,
        source_url=PAGE_URL, raw=raw, parse_error="; ".join(problems) or None,
    )


# ---------------------------------------------------------------- one event, not two

def read_portal(events_dir: Path) -> list[dict] | None:
    """MassDEP's records of Springfield's permit in this run's ma-massdep events file; None when there is no file."""
    doc = read_json(events_dir / f"{PORTAL_SOURCE}.json")
    if not isinstance(doc, dict):
        return None
    return [r for r in doc.get("records") or [] if isinstance(r, dict) and r.get("npdes_permit") == PERMIT
            and not r.get("duplicate_of")]


def link(records: list[dict], portal: list[dict] | None) -> dict:
    """Each row to the portal family of the same overflow: same permit and outfall id (suffix included), the portal's
    start within LINK_MINUTES of the row's start and not after the row's end, one to one, closest start first; the row
    becomes duplicate_of the family's shown record. A row with no end (ongoing, or an end not read) is never linked: it
    stands on its own, so an overflow the map shows as going on is never hidden behind a portal record. build/status.py
    carries a linked row's end to a shown portal record that has none (carry_map_ends)."""
    from ingest import operator_mail as O
    for r in records:
        r["duplicate_of"] = None
        r["raw"].pop("_link_basis", None)
    if not portal:
        return {"portal": (f"no {PORTAL_SOURCE} events file: every row stands alone" if portal is None else
                           f"no record of {PERMIT} in the {PORTAL_SOURCE} events file: every row stands alone"),
                "linked_to_portal": 0, "standing_alone": len(records)}
    by_id = {p["event_id"]: p for p in portal}
    fams = O.portal_families(portal, PERMIT)
    by_outfall: dict[str, list] = {}
    for f in fams:
        oid = str(by_id[f["root"]].get("outfall_id") or "").strip().upper()
        by_outfall.setdefault(oid, []).append(f)
    pairs = []
    for r in records:
        s, e = O.parse_iso(r.get("started_at")), O.parse_iso(r.get("ended_at"))
        if s is None or e is None or r.get("status") != "ended" or not r.get("outfall_id"):
            continue
        for f in by_outfall.get(r["outfall_id"].upper(), []):
            gap = abs((f["start"] - s).total_seconds())
            if gap <= LINK_MINUTES * 60 and f["start"].astimezone(UTC) <= e.astimezone(UTC):
                pairs.append((gap, r["event_id"], f["root"], r, f))
    pairs.sort(key=lambda x: (x[0], x[1], x[2]))
    used_r, used_f, n = set(), set(), 0
    for gap, rid, froot, r, f in pairs:
        if rid in used_r or froot in used_f:
            continue
        used_r.add(rid)
        used_f.add(froot)
        t = f["target"]
        r["duplicate_of"] = t["event_id"]
        r["raw"]["_link_basis"] = (f"the same overflow as the MassDEP portal record {t.get('source_record_id')}: same "
                                   f"permit and outfall, starts {round(gap / 60)} min apart")
        n += 1
    return {"portal": f"{len(portal)} records of {PERMIT}", "linked_to_portal": n, "standing_alone": len(records) - n}


# ---------------------------------------------------------------- current status (meta only)

def outfall_status(config: list[dict], status: list[dict] | None, log: list[dict], now: datetime) -> list[dict]:
    """Per outfall: the status row as given and the map's own derived status (the app's apiStatusCheck)."""
    now_l = now.astimezone(TZ)
    recent_from = now_l - timedelta(hours=STATUS_HOURS)
    stale_from = now_l - timedelta(hours=STALE_HOURS)
    by_asset = {str(s.get("asset")): s for s in status or []}
    out = []
    for c in sorted(config, key=lambda c: str(c.get("asset"))):
        a = str(c.get("asset"))
        s = by_asset.get(a)
        recent = [r for r in log if str(r.get("asset")) == a
                  and (st := local_time(r.get("start_timestamp"))[0]) is not None and utc(st) >= utc(recent_from)]
        upd = local_time((s or {}).get("last_updated"))[0]
        given = (s or {}).get("status")
        if c.get("not_monitored") == 1:
            shown = "notMonitered"
        elif s is None:
            shown = "notActive"
        elif given == "noOverflow" and recent:
            shown = "overflowed"
        elif given == "noOverflow" and (upd is None or utc(upd) <= utc(stale_from)):
            shown = "notActive"
        else:
            shown = given
        out.append({"asset": a, "outfall_id": CROSSWALK.get(a.upper()), "status": given,
                    "last_updated": (s or {}).get("last_updated"), "last_updated_at": iso(upd),
                    "map_status": shown, "map_label": LABELS.get(shown, shown)})
    return out


# ---------------------------------------------------------------- run

def crosswalk_check(ctx: dict) -> dict:
    """Each crosswalk id against the MassDEP CSOs layer (when cached) and the ECHO registry."""
    from ingest import ma_massdep as M
    layer, echo = ctx.get("layer") or {}, ctx.get("echo") or {}
    missing = []
    for a, oid in sorted(CROSSWALK.items()):
        in_layer = M.layer_lookup(layer, oid) is not None if layer else None
        in_echo = M.echo_lookup(echo, PERMIT, oid, None) is not None if echo else None
        if in_layer is False or in_echo is False:
            missing.append({"asset": a, "outfall_id": oid, "in_layer": in_layer, "in_echo": in_echo})
    return {"ids": len(CROSSWALK), "layer_checked": bool(layer), "echo_checked": bool(echo), "not_found": missing}


def run(config: list[dict], status: list[dict] | None, log: list[dict], now: datetime, *,
        events_dir: Path = EVENTS_DIR, out: Path | None = None, ctx: dict | None = None,
        status_error: str | None = None) -> tuple[int, list[dict], dict]:
    out = out or events_dir / f"{SOURCE_ID}.json"
    fetched_at = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    prev = read_json(out, {}) or {}
    held = len(prev.get("records") or [])
    if not log:
        why = "the overflow log answered no rows; the previous records are kept"
    elif held and len(log) < held * SHRINK:
        why = f"the overflow log answered {len(log)} rows against {held} records held; the previous records are kept"
    else:
        why = None
    if why:
        write_events(SOURCE_ID, [], ok=False, error=why, path=out)
        print(f"{SOURCE_ID}: FAILED {why}", file=sys.stderr)
        return 1, [], {}
    if ctx is None:
        from ingest import operator_mail as O
        ctx = O.ma_context({"springfield": SPEC})
    cfg = {str(c.get("asset")).strip().upper(): c for c in config}
    before = {str(r.get("source_record_id")): r for r in prev.get("records") or [] if isinstance(r, dict)}
    recs, unread, kept = [], [], 0
    for row in log:
        try:
            recs.append(to_record(row, cfg.get(str(row.get("asset") or "").strip().upper()), ctx, fetched_at))
        except Exception as e:  # noqa: BLE001 - one row never stops the others
            unread.append(f"log row {row.get('id')}: not built ({type(e).__name__})")
            old = before.get(str(row.get("id")))
            if old is not None:             # the previous version of the record stays
                old["raw"] = {**(old.get("raw") or {}), "_kept_previous_since": fetched_at}
                recs.append(old)
                kept += 1
    if len(unread) > len(log) * MAX_UNBUILT:
        why = (f"{len(unread)} of {len(log)} overflow-log rows did not build; the previous records are kept")
        write_events(SOURCE_ID, [], ok=False, error=why, meta={"unread": unread[:50]}, path=out)
        print(f"{SOURCE_ID}: FAILED {why}", file=sys.stderr)
        return 1, [], {}
    links = link(recs, read_portal(events_dir))
    recs.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    outfalls = outfall_status(config, status, log, now)
    meta = {"registry_ids": [SOURCE_ID], "url": PAGE_URL, "app": APP_URL, "api_host": API_HOST, "credit": CREDIT,
            "key": "read from the app's script at each run and held in memory only",
            "rows_read": len(log), "outfalls_listed": len(config), "links": links,
            "crosswalk": crosswalk_check(ctx), "outfalls": outfalls, "status_note": STATUS_NOTE,
            "data_not_received": [o["outfall_id"] or o["asset"] for o in outfalls if o["map_status"] == "notActive"],
            "with_volume": sum(r["volume_gal"] is not None for r in recs),
            "parse_errors": sum(bool(r["parse_error"]) for r in recs),
            "time_note": "the map's times have no zone; read as America/New_York",
            "volume_note": VOLUME_METHOD, "covers_permits": [PERMIT], "statewide": False}
    if status is None:
        meta["status_error"] = status_error or "the status table was not read"
    if unread:
        meta["unread"] = unread
        meta["kept_previous"] = kept
    if status is None or unread:
        write_events(SOURCE_ID, recs, ok=False, partial=True, meta=meta, path=out,
                     error="; ".join(([meta["status_error"]] if status is None else []) + unread))
        print(f"{SOURCE_ID}: PARTIAL {len(recs)} records", file=sys.stderr)
        return 1, recs, meta
    write_events(SOURCE_ID, recs, meta=meta, path=out)
    print(f"{SOURCE_ID}: {len(recs)} records; {links['linked_to_portal']} linked to the portal, "
          f"{links['standing_alone']} standing alone; data not received: {meta['data_not_received'] or 'none'} -> {out}")
    return 0, recs, meta


def _rows(path: str) -> list[dict]:
    doc = json.loads(Path(path).read_text())
    return doc.get("resource") if isinstance(doc, dict) else doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--files", nargs=3, metavar=("CONFIG", "STATUS", "LOG"), help="saved answers (no request)")
    ap.add_argument("--out", help="events file to write (needed with --files)")
    ap.add_argument("--now", help="the time the saved answers were read (ISO), for the status labels")
    a = ap.parse_args(argv)
    if a.files and not a.out:
        ap.error("--files needs --out")
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(UTC)
    if a.files:
        config, status, log = clean_config(_rows(a.files[0])), _rows(a.files[1]), _rows(a.files[2])
        code, _, _ = run(config, status, log, now, out=Path(a.out))
        return code
    with requests.Session() as sess:
        return live(sess, now)


def live(sess, now: datetime, events_dir: Path = EVENTS_DIR, ctx: dict | None = None) -> int:
    """One live read: the key, the three tables, the raw saves (never the key or the bundle), the events file."""
    out = events_dir / f"{SOURCE_ID}.json"
    try:
        config, status, log, serr = fetch_all(sess, now)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=error_text(e), path=out)
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    for name, rows in (("config", config), ("status", status), ("log", log)):
        if rows is not None:        # the answers as read, the config without row_create_user; never the key
            save_raw(SOURCE_ID, json.dumps({"resource": rows}, ensure_ascii=False), f"{name}.json")
    code, _, _ = run(config, status, log, now, events_dir=events_dir, out=out, ctx=ctx, status_error=serr)
    return code


if __name__ == "__main__":
    sys.exit(main())
