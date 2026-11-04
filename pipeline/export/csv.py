"""CSV downloads of the discharge reports (docs/data-downloads.md).

    write_csvs(events, waters, dischargers, out_dir)

writes, under out_dir (the export passes out/csv):

  water/<water_slug>.csv     one file per tracked water with at least one report (the site links a file
                             only when it exists; header-only files for the waters and operators with no
                             reports would pass the host's file cap: 2026-11-03, 3,319 operators, 822 with
                             reports)
  operator/<id>.csv          one file per discharger in out/dischargers.json with at least one report
  state/<st>.csv             one file per covered state, lowercase two-letter code
  all-reports-<year>.csv     every report, one file per calendar year of started_at (reports with no
                             start date are in the latest year's file)

A water, operator or state file that would pass SPLIT_BYTES (24 MiB; the host takes none over 25 MiB) is
written as <name>-<year>.csv files instead, split the same way, and the split is logged.

Every file is UTF-8 (no byte-order mark) with a header row, RFC 4180 quoting (comma separator, CRLF
line ends, a quote inside a value doubled), one report per row, newest first. Columns are COLUMNS.

The rows come from the public event objects the export writes (build.py: personal fields stripped
under the current rules, staff and private names redacted, no keys starting with "_"), and only from
the fixed top-level fields named here plus two link and municipality values read from their `raw`
(RAW_NOTICE_KEYS, status.TOWN_KEYS). Nothing else of `raw` is copied, so a field the sources add later
cannot reach a download by accident. Text that begins with = + - or @ gets a leading apostrophe so a
spreadsheet does not read it as a formula; numbers are never touched.

This module is named csv.py inside the export package; `import csv` below is the standard library
because the export runs as `python -m export.build` from pipeline/ (pipeline/export is never on the
module path).
"""
from __future__ import annotations

import csv
import math
import re
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from build import status as status_mod

SITE = "https://dirtywaterwatch.org"
COLUMNS = ["event_id", "water", "water_slug", "state", "operator", "operator_id", "outlet_id", "outlet_name",
           "event_type", "category", "status", "started_at", "ended_at", "end_reported", "volume_gal", "volume_text", "lat", "lon",
           "towns", "source_id", "source_name", "record_id", "published_at", "reported_at", "source_updated_at",
           "retrieved_at", "report_url", "notice_url", "site_url", "duplicate_of", "superseded_by"]
LIST_SEP = ";"
# children of out_dir this module owns (and replaces on every run); everything else in out_dir is left alone
MANAGED_DIRS = ("water", "operator", "state")
ALL_REPORTS = "all-reports"                 # all-reports-<year>.csv, one per calendar year of started_at
# keys of an event's `raw` that hold the link to an official notice or memo (a link only; the value must be http or https)
RAW_NOTICE_KEYS = ("notice_url", "memo_pdf", "MoreInfo")
# Event pages (site/src/lib/data.ts eventGetsPage, pageContext): a record that is not a history row gets one when it
# started (else was reported, else published) within PAGE_DAYS days before the snapshot, sets a status now (active.json,
# rain rows aside), stands behind a water's status (a non-grey reason) or is flagged unresolved on a water. Every
# other record's site_url is its row on the state-year archive page (archivePage: ARCHIVE_SPLIT), else its entry in
# the list of all reports (indexChunk: RECENT_DAYS). Keep these and SiteLinks in step with the site (review
# 2026-11-03 P2-2).
PAGE_DAYS = 90
ARCHIVE_SPLIT = 600
RECENT_DAYS = 90
NY = ZoneInfo("America/New_York")
# The static host takes no file over 25 MiB and the site build (site/scripts/count-files.mjs) fails on one;
# scripts/mirror-csv.sh leaves such a file out of site/public/csv. write_csvs reports them as "oversize".
MAX_FILE_BYTES = 25 * 1024 * 1024
# a water, operator or state file over this is split by year (<name>-<year>.csv); the margin keeps it under the limit
SPLIT_BYTES = 24 * 1024 * 1024
STARTED = COLUMNS.index("started_at")
_SAFE = re.compile(r"[A-Za-z0-9._-]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def encode_id(s: str) -> str:
    """The event page's URL segment: every character outside [A-Za-z0-9._-] as ~XX (UTF-8 bytes, upper-case
    hex), the same rule as build.event_file_name() and the site's encodeId(). Also makes file names safe."""
    return "".join(c if _SAFE.fullmatch(c) else "".join(f"~{b:02X}" for b in c.encode()) for c in str(s))


def time_key(e: dict) -> float:
    """Sort key: the start, else the report time, else the publication time (build.time_key)."""
    for k in ("started_at", "reported_at", "published_at"):
        t = status_mod.parse_time(e.get(k))
        if t:
            return t.timestamp()
    return float("-inf")


# ---------------------------------------------------------------- cell values

def _text(v) -> str:
    if v is None:
        return ""
    s = _CONTROL.sub("", str(v))
    return "'" + s if s.startswith(_FORMULA_START) else s


def _number(v, digits: int | None = None) -> str:
    """A finite number as text (integers without a decimal point); anything else is blank."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return ""
    if isinstance(v, float):
        if not math.isfinite(v):
            return ""
        if digits is not None:
            v = round(v, digits)
        if float(v).is_integer():
            return str(int(v))
    return repr(v)


def _url(v) -> str:
    """An http or https address, else blank. Whitespace inside it is percent-encoded."""
    if not isinstance(v, str):
        return ""
    u = _CONTROL.sub("", v).strip()
    try:
        p = urlsplit(u)
    except ValueError:
        return ""
    if p.scheme.lower() not in ("http", "https") or not p.netloc:
        return ""
    return re.sub(r"\s", "%20", u)


def _notice_url(e: dict) -> str:
    raw = e.get("raw")
    if not isinstance(raw, dict):
        return ""
    cands = [raw.get(k) for k in RAW_NOTICE_KEYS]
    urls = raw.get("notice_urls")
    if isinstance(urls, list):
        cands.insert(1, urls[0] if urls else None)
    return next((u for u in map(_url, cands) if u), "")


def _own_towns(e: dict) -> list[str]:
    raw = e.get("raw")
    raw = raw if isinstance(raw, dict) else {}
    return [v for v in (raw.get(k) for k in status_mod.TOWN_KEYS) if isinstance(v, str) and v.strip()]


def _join_towns(candidates) -> str:
    out, seen = [], set()
    for t in candidates:
        if not isinstance(t, str) or not t.strip():
            continue
        t = " ".join(t.split()).replace(LIST_SEP, ",")
        k = status_mod.norm_town(t)
        if k and k not in seen:
            seen.add(k)
            out.append(t)
    return LIST_SEP.join(out)


# ---------------------------------------------------------------- source names (as the site shows them)

_INTERNAL = re.compile(r"(owner|decision|coordinator|sub-?agent|\bagents?\b|fixture|research sample|not subscribed|search result|"
                       r"not checked|not quoted|\b(?:docs|data|research|out|site|pipeline|raw)/|\.md\b|\.json\b|\.py\b|https?:|www\.|"
                       r"\w+\.(?:gov|com|org|us)\b/?)", re.I)
_ASIDE = re.compile(r"\s*\(([^()]*)\)")


def public_text(s) -> str:
    """site/src/lib/data.ts publicText(): asides that carry file paths, web addresses or working notes are dropped."""
    if not s or not isinstance(s, str):
        return ""
    t = re.sub(r"^\s*Owner[^:]{0,40}:\s*", "", s, flags=re.I)
    for _ in range(3):
        t = _ASIDE.sub(lambda m: "" if _INTERNAL.search(m.group(1)) else m.group(0), t)
    t = re.sub(r"\s*(?:\b(?:docs|data|research|out|site|pipeline)/[\w./<>-]*(?:\s+(?:section\s+)?[\d.]+)?[;,]?\s*)+", " ", t, flags=re.I)
    return re.sub(r"\s{2,}", " ", re.sub(r"\s+([.,;:])", r"\1", t)).strip()


def source_labels(events: list[dict], feeds: list[dict] | None = None, registry: list[dict] | None = None) -> dict[str, str]:
    """source_id -> the name the site's pages give the source (sourceLabel): the first registered name of the
    feed with long parenthetical asides removed; for a feed with no registered name, the aside in its records'
    authority field that they name most often. Blank when neither exists (the identifier is never used)."""
    reg = {r.get("id"): r for r in registry or [] if isinstance(r, dict)}
    reg_name = {}
    for f in feeds or []:
        for rid in f.get("registry_ids") or []:
            r = reg.get(rid)
            if r and r.get("name") and r["name"] != f.get("source_id"):
                reg_name[f["source_id"]] = r["name"]
                break
    asides: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        a = e.get("authority")
        if isinstance(a, str) and a.strip() and e.get("source_id"):
            m = re.search(r"\(([^()]+)\)\s*$", a)
            k = public_text(m.group(1) if m else a)
            if k:
                asides[e["source_id"]][k] += 1
    out = {}
    for sid in {e.get("source_id") for e in events if e.get("source_id")} | set(reg_name):
        name = ""
        if sid in reg_name:
            name = _ASIDE.sub(lambda m: "" if len(m.group(1).split()) > 4 else m.group(0), public_text(reg_name[sid])).strip()
        if not name and asides.get(sid):
            name = asides[sid].most_common(1)[0][0]
        out[sid] = name
    return out


# ---------------------------------------------------------------- which events have a page

def _water_rows(waters) -> list[dict]:
    rows = waters.values() if isinstance(waters, dict) else waters
    return [w for w in rows or [] if isinstance(w, dict) and w.get("slug")]


def _ids_of(items) -> list[str]:
    """Event ids from a list of ids or of objects with an event_id (both shapes occur in out/)."""
    out = []
    for x in items or []:
        i = x if isinstance(x, str) else (x.get("event_id") if isinstance(x, dict) else None)
        if i:
            out.append(i)
    return out


def _str(v):
    """The site's str(): a non-empty string, else None."""
    return v if isinstance(v, str) and v else None


def is_history_row(e: dict) -> bool:
    """site isHistoryRow: an annual total or a month- or year-precision record never gets a page."""
    return e.get("event_type") == "annual_total" or e.get("time_precision") in ("month", "year")


def page_context(waters, active_ids=(), as_of=None) -> dict:
    """site pageContext: the snapshot time and the three id sets eventGetsPage reads."""
    rows = _water_rows(waters)
    return {"as_of": status_mod.parse_time(as_of) or datetime.now(UTC), "active": set(active_ids or ()),
            "behind": {r["event_id"] for w in rows for r in w.get("reasons") or []
                       if isinstance(r, dict) and r.get("event_id") and r.get("status") in ("red", "yellow", "unresolved")},
            "unresolved": {i for w in rows for i in _ids_of(w.get("unresolved_events"))}}


def event_gets_page(e: dict, ctx: dict) -> bool:
    """site eventGetsPage: the one rule for which records get /event/<id>/."""
    if is_history_row(e):
        return False
    first = _str(e.get("started_at")) or _str(e.get("reported_at")) or _str(e.get("published_at"))
    t = status_mod.parse_time(first)
    if t is not None and t >= ctx["as_of"] - timedelta(days=PAGE_DAYS):
        return True
    return e["event_id"] in ctx["active"] or e["event_id"] in ctx["behind"] or e["event_id"] in ctx["unresolved"]


def event_page_ids(events: list[dict], waters, active_ids=(), as_of=None) -> set[str]:
    """Event ids that have a page at /event/<id>/ (event_gets_page over page_context): mirrors the site's pagedIds."""
    ctx = page_context(waters, active_ids, as_of)
    return {e["event_id"] for e in events if event_gets_page(e, ctx)}


def _epoch_minutes(s) -> int | None:
    t = status_mod.parse_time(s)
    return None if t is None else math.floor(t.timestamp() / 60 + 0.5)        # JavaScript Math.round


def _ny_day(minutes: int) -> str:
    return datetime.fromtimestamp(minutes * 60, UTC).astimezone(NY).strftime("%Y-%m-%d")


class SiteLinks:
    """Each record's address on the site, by the site's rules (site/src/lib/data.ts eventHref): its page, else its
    row on the state-year archive page (archivePage, eventState, archiveDay), else its entry in the list of all
    reports (indexChunk). Built from the export's own data: the events (with the `state` the export writes), the
    tracked waters, the operator registry, the sources' states and the snapshot time."""

    def __init__(self, events, waters, dischargers, page_ids, as_of=None, source_states=None):
        self.page_ids = set(page_ids or ())
        self.as_of = status_mod.parse_time(as_of) or datetime.now(UTC)
        rows = _water_rows(waters)
        self.water_state = {w["slug"]: (_str(w.get("state")) or w["slug"][-2:]).upper() for w in rows}
        dis = sorted((d for d in dischargers or [] if isinstance(d, dict) and d.get("id")),
                     key=lambda d: (str(d.get("name") or d["id"]).lower(), str(d.get("name") or d["id"])))
        self.dis = {d["id"]: d for d in dis}
        self.permit = {}
        for d in dis:
            for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])]:
                if p and p not in self.permit:
                    self.permit[p] = d["id"]
        self.source_states = source_states or {}
        # loadMeta().states: the waters' states and the states the counted (not duplicate) records count under
        covered = {(_str(w.get("state")) or w["slug"][-2:]).upper() for w in rows}
        covered |= {str(e.get("state") or status_mod.event_state(e) or "").upper() for e in events if not e.get("duplicate_of")}
        self.covered = {c for c in covered if re.fullmatch(r"[A-Z]{2}", c)}
        self.year_counts = Counter()
        for e in events:
            st, day = self.state_of(e), self.day_of(e)
            if st and day and st in self.covered:
                self.year_counts[(st, day[:4])] += 1
        self.recent_from = _ny_day(_epoch_minutes(self.as_of.isoformat()) - RECENT_DAYS * 24 * 60)

    def state_of(self, e: dict) -> str | None:
        """site eventState: the export's state, else its first water's, its operator's, its source's first."""
        st = _str(e.get("state"))
        if st and st != "unknown":
            return st.upper()
        for s in e.get("water_slugs") or []:
            if s in self.water_state:
                return self.water_state[s]
        d = self.dis.get(e.get("discharger_id")) or self.dis.get(self.permit.get(e.get("npdes_permit")))
        if d and _str(d.get("state")):
            return d["state"].upper()
        states = self.source_states.get(e.get("source_id")) or []
        return states[0] if states else None

    @staticmethod
    def minutes_of(e: dict) -> int | None:
        """site indexTimes: the start, else the report time (reported, else published, else source update)."""
        m = _epoch_minutes(_str(e.get("started_at")))
        if m is None:
            m = _epoch_minutes(_str(e.get("reported_at")) or _str(e.get("published_at")) or _str(e.get("source_updated_at")))
        return m

    def day_of(self, e: dict) -> str | None:
        """site archiveDay: the New York day of its start, else of its report time."""
        m = self.minutes_of(e)
        return None if m is None else _ny_day(m)

    def url(self, e: dict) -> str:
        eid = e["event_id"]
        if eid in self.page_ids:
            return f"{SITE}/event/{encode_id(eid)}/"
        st, day = self.state_of(e), self.day_of(e)
        if st and day and st in self.covered:
            y = day[:4]
            path = f"/discharges/{st.lower()}/{y}/" + (f"{day[5:7]}/" if self.year_counts[(st, y)] > ARCHIVE_SPLIT else "")
            return f"{SITE}{path}#{encode_id(eid)}"
        m = self.minutes_of(e)
        chunk = "undated" if m is None else ("recent" if _ny_day(m) >= self.recent_from else _ny_day(m)[:4])
        return f"{SITE}/discharges/all/?id={encode_id(eid)}&y={chunk}"


def superseded_by(e: dict, ids) -> str:
    """The record a superseded one is counted under: the event id its `superseded` note names ("revised by <id>",
    "notice about <id>, which carries the times"), as the site's newestVersion reads it; the note itself when it
    names no record in the file; blank when the record is not superseded."""
    note = e.get("superseded")
    if not isinstance(note, str) or not note:
        return ""
    for tok in note.split():
        tok = tok.rstrip(",.;:)")
        if tok in ids and tok != e.get("event_id"):
            return tok
    return note


# ---------------------------------------------------------------- rows

class _Context:
    def __init__(self, waters, dischargers, source_names, links: SiteLinks, ids=()):
        self.waters = {w["slug"]: w for w in _water_rows(waters)}
        self.dischargers = {d["id"]: d for d in dischargers or [] if isinstance(d, dict) and d.get("id")}
        self.rows_of_permit: dict[str, list[str]] = defaultdict(list)
        for d in self.dischargers.values():
            if d.get("npdes_permit"):
                self.rows_of_permit[d["npdes_permit"]].append(d["id"])
        self.source_names = source_names
        self.links = links
        self.ids = set(ids)

    def operators_of(self, e: dict) -> list[str]:
        """The discharger rows an event belongs to (build.events_by_discharger): the row its discharger_id
        names; with no id, or an id that is no row, the rows holding its npdes_permit as their permit."""
        did = e.get("discharger_id")
        if did in self.dischargers:
            return [did]
        return list(self.rows_of_permit.get(e.get("npdes_permit"), []))


def event_row(e: dict, ctx: _Context) -> tuple[list[str], list[str]]:
    """(the CSV row for one public event, the ids of the discharger rows it belongs to)."""
    ops = ctx.operators_of(e)
    d = ctx.dischargers[ops[0]] if ops else {}
    slugs = [s for s in e.get("water_slugs") or [] if isinstance(s, str) and s]
    if slugs:
        water = LIST_SEP.join(str((ctx.waters.get(s) or {}).get("name") or s) for s in slugs)
    else:
        water = e.get("waterbody_text") or ""      # not placed on a tracked water: the name as the source wrote it
    state = status_mod.event_state(e)
    operator_id = ops[0] if ops else e.get("discharger_id")
    operator = e.get("discharger_name") or d.get("name")
    towns = _join_towns(_own_towns(e) or d.get("towns") or [])
    eid = e["event_id"]
    row = [
        _text(eid), _text(water), _text(LIST_SEP.join(slugs)), _text(state), _text(operator), _text(operator_id),
        _text(e.get("outfall_id")), _text(e.get("outfall_name")), _text(e.get("event_type")),
        _text(e.get("category") or status_mod.category_of(e.get("event_type"))), _text(e.get("status")),
        _text(e.get("started_at")), _text(e.get("ended_at")), "true" if e.get("ended_at") else "false",
        _number(e.get("volume_gal")), _text(e.get("volume_text")),
        _number(e.get("lat"), 5), _number(e.get("lon"), 5),
        _text(towns), _text(e.get("source_id")), _text(ctx.source_names.get(e.get("source_id"), "")),
        _text(e.get("source_record_id")), _text(e.get("published_at")), _text(e.get("reported_at")),
        _text(e.get("source_updated_at")), _text(e.get("fetched_at")),
        _url(e.get("source_url")), _notice_url(e),
        ctx.links.url(e),
        _text(e.get("duplicate_of")), _text(superseded_by(e, ctx.ids)),
    ]
    return row, ops


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)           # comma, quote only where needed, quote doubled, CRLF line ends (RFC 4180)
        w.writerow(COLUMNS)
        w.writerows(rows)


def year_of(row: list[str]) -> str | None:
    """The calendar year of a row's started_at as written (its first four digits), None when it has none."""
    m = re.match(r"\s*(\d{4})-", row[STARTED])
    return m.group(1) if m else None


def by_year(rows: list[list[str]], idx, latest: str) -> dict[str, list[int]]:
    """{year: row positions}, newest year first; rows with no start date go in the latest year's file (the
    latest year among these rows, else `latest`). Positions keep the newest-first order of `rows`."""
    dated: dict[str, list[int]] = defaultdict(list)
    undated = []
    for i in sorted(set(idx)):
        y = year_of(rows[i])
        (dated[y] if y else undated).append(i)
    last = max(dated, default=latest)
    dated[last] = sorted(dated[last] + undated)
    return {y: dated[y] for y in sorted(dated, reverse=True)}


def write_csvs(events: list[dict], waters, dischargers: list[dict], out_dir, *, source_names: dict | None = None,
               page_ids: set | None = None, states=None, as_of=None, active_ids=(), source_states: dict | None = None) -> dict:
    """Write the CSV files under out_dir (see the module docstring) and return the counts {"files", "water",
    "operator", "state", "events", "all_reports", "split", "oversize"}: files is the number of files written; water,
    operator and state the number of waters, operators and states (a split one still counts once); all_reports the
    year files, newest year first; split the water, operator or state files written by year; oversize the relative
    paths of files still above MAX_FILE_BYTES.

    events       the public event objects the export writes (full records, not the slim list)
    waters       the tracked waters: rows with slug, name and optionally events (ids, as the water page
                 lists them: includes reports placed on a stretch upstream) and unresolved_events
    dischargers  out/dischargers.json's rows (id, name, npdes_permit, towns); an event is in the file of the
                 row its discharger_id names, else of the rows holding its npdes_permit
    source_names source_id -> name; default: source_labels(events)
    page_ids     event ids that have a page, for site_url; default: event_page_ids(events, waters, active_ids, as_of)
    states       the covered states; default: the waters' states and every state an event resolves to
    as_of        the snapshot time (out/meta.json status_now), for the page rule and the archive links
    active_ids   the ids in out/active.json (rain rows aside), for the page rule
    source_states source_id -> its states as the site's sources list them (the last fallback of a record's state)

    Files are written to <out_dir>.tmp first and moved in only when all are written, so a failure
    leaves the previous set in place.
    """
    out_dir = Path(out_dir)
    seen, uniq = set(), []
    for e in events:
        if e.get("event_id") and e["event_id"] not in seen:
            seen.add(e["event_id"])
            uniq.append(e)
    uniq.sort(key=lambda e: (-time_key(e), e["event_id"]))          # newest first, ties by id
    wrows = _water_rows(waters)
    pages = page_ids if page_ids is not None else event_page_ids(uniq, wrows, active_ids, as_of)
    ctx = _Context(waters, dischargers,
                   source_names if source_names is not None else source_labels(uniq),
                   SiteLinks(uniq, wrows, dischargers, pages, as_of, source_states), seen)

    rows, by_id, by_state, by_operator = [], {}, defaultdict(list), defaultdict(list)
    for i, e in enumerate(uniq):
        row, ops = event_row(e, ctx)
        rows.append(row)
        by_id[e["event_id"]] = i
        if row[3]:
            by_state[row[3]].append(i)
        for op in ops:
            by_operator[op].append(i)

    tmp = out_dir.with_name(out_dir.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    counts = {"files": 0, "water": 0, "operator": 0, "state": 0, "events": len(rows), "all_reports": [], "split": [],
              "oversize": []}
    # the year undated reports go to when nothing else says: the newest start year in the data, else this year
    latest = max((y for y in map(year_of, rows) if y), default=None) or \
        str((status_mod.parse_time(as_of) or datetime.now(UTC)).year)

    def emit(rel: str, idx) -> None:
        _write(tmp / rel, [rows[i] for i in sorted(set(idx))])     # positions follow the newest-first order
        counts["files"] += 1
        if (tmp / rel).stat().st_size > MAX_FILE_BYTES:
            counts["oversize"].append(rel)

    def put(stem: str, idx, kind: str) -> None:
        """stem.csv, or stem-<year>.csv per year when the file would pass SPLIT_BYTES."""
        counts[kind] += 1
        path = tmp / f"{stem}.csv"
        _write(path, [rows[i] for i in sorted(set(idx))])
        size = path.stat().st_size
        years = by_year(rows, idx, latest) if size > SPLIT_BYTES else {}
        if len(years) > 1:
            path.unlink()
            counts["split"].append(f"{stem}.csv")
            print(f"export: csv {stem}.csv would be {size / 1048576:.1f} MiB (over 24 MiB); "
                  f"written as {stem}-<year>.csv for {', '.join(years)}")
            for y, ids in years.items():
                emit(f"{stem}-{y}.csv", ids)
        else:
            counts["files"] += 1
            if size > MAX_FILE_BYTES:
                counts["oversize"].append(f"{stem}.csv")

    try:
        for y, ids in by_year(rows, range(len(rows)), latest).items():
            emit(f"{ALL_REPORTS}-{y}.csv", ids)
            counts["all_reports"].append(f"{ALL_REPORTS}-{y}.csv")
        placed = defaultdict(list)
        for i, e in enumerate(uniq):
            for s in e.get("water_slugs") or []:
                placed[s].append(i)
        for w in wrows:
            listed = [by_id[x] for x in _ids_of(w.get("events")) if x in by_id]
            if listed or placed.get(w["slug"]):
                put(f"water/{encode_id(w['slug'])}", listed + placed.get(w["slug"], []), "water")
        for did in ctx.dischargers:
            if by_operator.get(did):
                put(f"operator/{encode_id(did)}", by_operator.get(did, []), "operator")
        covered = {str(s).upper() for s in (states if states is not None else
                                            {w.get("state") for w in wrows if w.get("state")} | set(by_state))}
        for st in sorted(s for s in covered if re.fullmatch(r"[A-Z]{2}", s)):
            put(f"state/{st.lower()}", by_state.get(st, []), "state")
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in MANAGED_DIRS:                                      # swap in: only what this module owns
            if (out_dir / name).is_dir():
                shutil.rmtree(out_dir / name)
        for old in out_dir.glob(f"{ALL_REPORTS}*.csv"):                # last run's year files (and an old all-reports.csv)
            old.unlink()
        for name in MANAGED_DIRS:
            if (tmp / name).exists():
                (tmp / name).rename(out_dir / name)
            else:
                (out_dir / name).mkdir(exist_ok=True)                  # a kind with no files still has its directory
        for new in tmp.glob(f"{ALL_REPORTS}-*.csv"):
            new.rename(out_dir / new.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return counts
