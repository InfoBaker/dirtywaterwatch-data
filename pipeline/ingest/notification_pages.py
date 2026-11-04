"""Public-notice channel monitor: every monitored row of data/notice-channels.json, fetched once a refresh
-> data/build/events/notification-pages.json (dated overflow notices found on the pages) and
data/build/notice-pages/ (a snapshot per page, the change log, the page-health table health.json).

Why (owner, 2026-11-03)
  Permits and state laws make some web pages the public's reporting channel (New Jersey's CSO permits,
  Part IV.F.8.b.iii: "maintain on a daily basis a CSO Notification System website to inform interested
  citizens of CSO discharges that are occurring or have occurred"), and operators run voluntary ones. Few of
  them show a status. This module watches them all: whether each page answers, whether it changed and when,
  whether it shows a current status, and any dated overflow notice that appears on it.

The register: data/notice-channels.json
  {about, schema_version, schema: {fields, enums, rules}, channels: [row, ...]}: one row per public-notice
  channel per operator or agency in any state (SCHEMA below; validate_register() is the validator, run by
  tests/test_notice_channels.py). Rows are sorted by (state, id) so builders working on different states
  merge cleanly. `basis_kind` says why the channel is public: "law", "permit" or "voluntary".

Fetching
  Each distinct URL of the monitored rows is fetched once a run (rows sharing a URL share the fetch: New
  Jersey's 15 shared-site permits read one page), with the project user agent (a row may ask for the browser
  one with `headers: "browser"`), unless the row's `every_hours` says it is not due. The raw response is
  kept with save_raw (data/raw/notification-pages/<page id>/<stamp>.<ext>) whenever its text changed, and
  an error body once per distinct body. A row may name earlier copies (`seeds`: the research and survey
  copies) that stand as the page's first snapshots, so the first run already compares against them.

Snapshots (data/build/notice-pages/pages/<page id>.json)
  The extracted text of the last good fetch (html: visible text by block; pdf: text rows; json: one line per
  leaf value; rss: one line per item), emails, phone numbers and staff names scrubbed; the content hash (the
  raw bytes) and the text hash (the sorted distinct lines after the rows' `ignore_lines`, so reordered or
  volatile lines such as rainfall readings are not a change); when the current text was first seen
  (`text_since`) and when it last changed; every fetch (time, ok, HTTP status, text hash); the change log
  (lines added and removed, the notices found or skipped). A failed fetch is recorded as such
  (`unreachable_since`) and the last good snapshot is kept.

Notices -> records (event_type from the words; started_at = the notice's date, time_precision "day")
  Only from lines added since the previous snapshot: text that matches the previous snapshot, the shared
  site's wording (the lines of every `shared_site` page and GENERIC) or a row's status line is never a
  notice, and a page's first snapshot is a baseline (its dated notices are listed for review, not
  recorded). A notice is a sentence with a date to the day and an overflow word (overflow, CSO, combined
  sewer, discharge, bypass, SSO, spill; or advisory, "occurring", "has occurred" with a sewer or water word),
  not a meeting, report, permit or construction item, not a negative ("unlikely", "no overflow"); for a row
  with `dated_lines_are_notices` (an event table, Trenton's PDF) any added dated line. Dates more than
  NOTICE_MAX_AGE_DAYS before the fetch, or more than a day after it, are skipped (listed in the change log).
  Status is "unknown" unless the sentence gives an end with its own date ("ended", "ceased" ... and a second
  date: "ended", ended_at that day). The page is the citation (source_url); reported_at stays null (the
  page gives no report time) and raw.first_seen_at is our fetch. Rows with `records: false` (likelihood
  sites, sampling results) never make records.

Page health (data/build/notice-pages/health.json; out/coverage.json states.<ST>.notification_pages)
  Per channel: last fetch, last change, days since the current text was first seen, reachable, whether it
  shows a status, and one public line (`wording`): "Publishes a current status", "<Noun> unreachable since
  <date>", "Links to <link_text> only", "<Noun> unchanged since <date>", "No current status shown since
  <date>", "Not listed on <link_text> since <date>", "No notification page found", "... not read"
  (login, bot check, image only, email only, app only), "Read as a feed", "Not checked yet". <Noun> is the
  row's `noun`, else "Notification page", or "Voluntary page" for a voluntary channel (never "required").
  Per operator and permit (`operators`): the most telling of its channels' lines (ROLLUP_ORDER).

Run from pipeline/:  python -m ingest.notification_pages [--state NJ] [--validate] [--write-schema] [--no-fetch]
Cadence: every refresh (hourly); a row's `every_hours` spaces out a slow page.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from common import (BROWSER_HEADERS, BUILD_DIR, DATA_DIR, HEADERS, ROOT, event, now_iso, read_json, save_raw,
                    scrub_text, write_events, write_json)

SOURCE_ID = "notification-pages"
REGISTER = DATA_DIR / "notice-channels.json"
STORE = BUILD_DIR / "notice-pages"
PAGES_DIR = STORE / "pages"
HEALTH = STORE / "health.json"
RECORDS = STORE / "records.json"
TZ = ZoneInfo("America/New_York")          # every jurisdiction in the register so far keeps Eastern time
NOTICE_MAX_AGE_DAYS = 90
FETCH_LOG_MAX = 500
CHANGE_LOG_MAX = 50
TIMEOUT = 45

# ---------------------------------------------------------------- the register's schema

ENUMS = {
    "channel_kind": ["operator_page", "state_alert_page", "local_health_page", "shared_site", "feed", "social",
                     "lights_signs_page", "news_page", "email_list", "group_results", "swim_guide"],
    "method": ["html", "json", "pdf", "rss"],
    "basis_kind": ["law", "permit", "voluntary"],
    "unmonitored_reason": ["login", "bot_wall", "image_only", "none_found", "email_only", "app_only",
                           "feed_ingested", "other"],
    "publishes": ["status", "likelihood", "notices", "documents", "link_only", "results", "none", "unknown"],
    # docs/plan.md §2.y "What stands in the way": what keeps an unmonitored channel's notices off the open web
    "barrier": ["print_only", "login_required", "no_web_page", "varies_by_town", "not_verified", "image_only",
                "bot_wall", "phone_only", "signs_only"],
}
REQUIRED = {
    "id": "unique channel id: '<state lower>-' then lowercase letters, digits and hyphens; stable (record ids and "
          "snapshots follow the URL, not the id, but merges and reviews follow the id)",
    "state": "two-letter postal code of the jurisdiction (DC included)",
    "operator_id": "data/dischargers.json id of the operator, or null for an agency or group channel",
    "agency": "the agency or group that runs the channel when it is not an operator in data/dischargers.json, else null",
    "name": "public name of the operator or agency",
    "permit": "the NPDES / state permit the channel serves (one of the operator's npdes_permits), or null",
    "channel_kind": "what the channel is (enums.channel_kind)",
    "urls": "the URL(s) read, http(s); [] only for a channel that is not monitored (none found, email only)",
    "method": "how the URLs are read (enums.method); null only when urls is []",
    "legal_basis": "the law or permit clause that makes it a public channel, cited; null only for voluntary",
    "basis_kind": "law, permit or voluntary (enums.basis_kind)",
    "monitored": "true when this module fetches it",
    "unmonitored_reason": "when monitored is false: why (enums.unmonitored_reason); null when monitored",
    "publishes": "what the research saw on it (enums.publishes): a current status, a rainfall likelihood, dated "
                 "notices, documents, only a link elsewhere, sampling results, nothing",
    "note": "research note, internal (not exported); required for none_found and other",
    "checked": "date the row was last checked against the source, YYYY-MM-DD",
    "barrier": "what keeps the channel's notices off the open web (enums.barrier), from unmonitored_reason, the kind "
               "and the note (barrier_for); null for a monitored row or one read through a feed (feed_ingested), and "
               "for a row the register does not settle (then barrier_review says why)",
}
OPTIONAL = {
    "authority": "who is credited on records from this channel (default: name)",
    "noun": "the noun of the health wording (default 'Notification page', 'Voluntary page' for voluntary rows)",
    "link_text": "for link_only / likelihood rows: what the page links to ('the shared rainfall site'); the wording "
                 "is 'Links to <link_text> only'",
    "status_pattern": "regular expression that finds the current status on the page; when it stops matching the "
                      "wording says so",
    "entry": "{start, end}: regular expressions that cut this row's entry out of a page several rows share "
             "(from the first line matching start to the next line matching end)",
    "ignore_lines": "regular expressions of volatile lines (readings, clocks) left out of the text hash",
    "records": "false: never make records from this channel (default true)",
    "dated_lines_are_notices": "true: any added dated line is a notice (an event table)",
    "default_event_type": "event type of a notice whose words name none (common.EVENT_TYPES)",
    "every_hours": "fetch at most this often (default: every refresh)",
    "headers": "'browser' to send a browser user agent (hosts that refuse others)",
    "feed_source_id": "for feed_ingested: the source id of the feed that reads it",
    "signup_url": "where the public signs up for its alerts, when it has a list",
    "seeds": "{url: [{path, fetched_at, http_status}]}: earlier copies (research, surveys) taken as the first "
             "snapshots, oldest first; path relative to the project root",
    "sources": "research or registry ids the row rests on",
    "barrier_review": "internal: why an unmonitored row has no barrier yet (listed in docs/reviews/2026-11-03-barriers.md)",
}
RULES = [
    "channels sorted by (state, id); ids unique",
    "operator_id or agency is given; operator_id exists in data/dischargers.json; a permit given with an "
    "operator_id is one of that operator's npdes_permits",
    "monitored rows have urls and a method; unmonitored rows have an unmonitored_reason",
    "basis_kind law or permit has a legal_basis",
    "barrier is null for monitored and feed_ingested rows, follows login, bot_wall and image_only, and is set (or "
    "barrier_review given) for every other unmonitored row",
    "regular expressions compile; seeds name the row's urls",
]
SCHEMA = {"fields": REQUIRED, "optional_fields": OPTIONAL, "enums": ENUMS, "rules": RULES}
ABOUT = ("Public-notice channels per operator or agency: pages, sites, feeds, lists and accounts through which the "
         "public is told of sewage discharges, by law, permit or voluntarily. Read by "
         "pipeline/ingest/notification_pages.py (schema and validator there; test tests/test_notice_channels.py).")
STATE_CODES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
               "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
               "ND", "OH", "OK", "OR", "PA", "PR", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
               "WY"}
_ID = re.compile(r"^[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _compiles(p) -> bool:
    try:
        re.compile(p)
        return True
    except (re.error, TypeError):
        return False


def validate_register(doc, dischargers: list[dict] | None = None, root: Path | None = None) -> list[str]:
    """Every problem with the register, as sentences (empty: valid). dischargers: data/dischargers.json rows, to
    check operator ids and permits; root: the project root, to check that seed copies exist."""
    from common import EVENT_TYPES
    errs: list[str] = []
    if not isinstance(doc, dict) or not isinstance(doc.get("channels"), list):
        return ["the register is an object with a 'channels' list"]
    if not isinstance(doc.get("schema_version"), int):
        errs.append("schema_version is an integer")
    dis = {r["id"]: r for r in dischargers or [] if isinstance(r, dict) and r.get("id")}
    allowed = set(REQUIRED) | set(OPTIONAL)
    seen: set[str] = set()
    keys = []
    for i, r in enumerate(doc["channels"]):
        where = f"channels[{i}]" + (f" ({r.get('id')})" if isinstance(r, dict) and r.get("id") else "")
        if not isinstance(r, dict):
            errs.append(f"{where}: a row is an object")
            continue
        missing = [k for k in REQUIRED if k not in r]
        if missing:
            errs.append(f"{where}: missing {missing}")
        extra = sorted(set(r) - allowed)
        if extra:
            errs.append(f"{where}: unknown fields {extra}")
        rid, st = r.get("id"), r.get("state")
        if not isinstance(st, str) or st not in STATE_CODES:
            errs.append(f"{where}: state {st!r} is not a postal code")
        if not isinstance(rid, str) or not _ID.match(rid):
            errs.append(f"{where}: id {rid!r} is not a lowercase hyphenated id")
        elif isinstance(st, str) and not rid.startswith(st.lower() + "-"):
            errs.append(f"{where}: id does not start with '{str(st).lower()}-'")
        if rid in seen:
            errs.append(f"{where}: duplicate id")
        seen.add(rid)
        keys.append((str(st), str(rid)))
        op, ag = r.get("operator_id"), r.get("agency")
        if not ((isinstance(op, str) and op) or (isinstance(ag, str) and ag)):
            errs.append(f"{where}: operator_id or agency is needed")
        if op is not None and not isinstance(op, str):
            errs.append(f"{where}: operator_id is a string or null")
        if dis and isinstance(op, str) and op:
            if op not in dis:
                errs.append(f"{where}: operator_id {op!r} is not in data/dischargers.json")
            else:
                permits = dis[op].get("npdes_permits") or ([dis[op]["npdes_permit"]] if dis[op].get("npdes_permit") else [])
                if r.get("permit") and permits and r["permit"] not in permits:
                    errs.append(f"{where}: permit {r['permit']!r} is not one of {op}'s permits {permits}")
        if not isinstance(r.get("name"), str) or not r.get("name"):
            errs.append(f"{where}: name is a non-empty string")
        if r.get("permit") is not None and not isinstance(r.get("permit"), str):
            errs.append(f"{where}: permit is a string or null")
        for k in ("channel_kind", "basis_kind", "publishes"):
            if r.get(k) not in ENUMS[k]:
                errs.append(f"{where}: {k} {r.get(k)!r} is not one of {ENUMS[k]}")
        urls = r.get("urls")
        if not isinstance(urls, list) or not all(isinstance(u, str) and re.match(r"^https?://\S+$", u) for u in urls):
            errs.append(f"{where}: urls is a list of http(s) URLs")
            urls = []
        elif len(set(urls)) != len(urls):
            errs.append(f"{where}: urls repeat")
        m = r.get("method")
        if urls and m not in ENUMS["method"]:
            errs.append(f"{where}: method {m!r} is not one of {ENUMS['method']}")
        if not urls and m is not None and m not in ENUMS["method"]:
            errs.append(f"{where}: method {m!r} is not one of {ENUMS['method']} or null")
        mon, why = r.get("monitored"), r.get("unmonitored_reason")
        if not isinstance(mon, bool):
            errs.append(f"{where}: monitored is true or false")
        elif mon:
            if not urls:
                errs.append(f"{where}: a monitored row needs urls")
            if m not in ENUMS["method"]:
                errs.append(f"{where}: a monitored row needs a method")
            if why is not None:
                errs.append(f"{where}: unmonitored_reason is null when monitored")
        else:
            if why not in ENUMS["unmonitored_reason"]:
                errs.append(f"{where}: unmonitored_reason {why!r} is not one of {ENUMS['unmonitored_reason']}")
            if why in ("none_found", "other") and not (isinstance(r.get("note"), str) and r["note"].strip()):
                errs.append(f"{where}: a {why} row needs a note")
            if why == "feed_ingested" and not r.get("feed_source_id"):
                errs.append(f"{where}: a feed_ingested row names its feed_source_id")
        bar = r.get("barrier")
        if bar is not None and bar not in ENUMS["barrier"]:
            errs.append(f"{where}: barrier {bar!r} is not one of {ENUMS['barrier']} or null")
        if mon is True or why == "feed_ingested":
            if bar is not None:
                errs.append(f"{where}: barrier is null for a monitored or feed_ingested row")
        elif mon is False:
            fixed = {"login": "login_required", "bot_wall": "bot_wall", "image_only": "image_only"}.get(why)
            if fixed and bar != fixed:
                errs.append(f"{where}: unmonitored_reason {why} means barrier {fixed}")
            if bar is None and not (isinstance(r.get("barrier_review"), str) and r["barrier_review"].strip()):
                errs.append(f"{where}: an unmonitored row has a barrier or a barrier_review")
        if bar is not None and r.get("barrier_review"):
            errs.append(f"{where}: barrier_review only on a row with no barrier")
        lb = r.get("legal_basis")
        if r.get("basis_kind") in ("law", "permit") and not (isinstance(lb, str) and lb.strip()):
            errs.append(f"{where}: basis_kind {r.get('basis_kind')} needs a legal_basis")
        if lb is not None and not isinstance(lb, str):
            errs.append(f"{where}: legal_basis is a string or null")
        if r.get("note") is not None and not isinstance(r.get("note"), str):
            errs.append(f"{where}: note is a string or null")
        if not isinstance(r.get("checked"), str) or not _DAY.match(r.get("checked") or ""):
            errs.append(f"{where}: checked is YYYY-MM-DD")
        if "status_pattern" in r and r["status_pattern"] is not None and not _compiles(r["status_pattern"]):
            errs.append(f"{where}: status_pattern does not compile")
        for p in r.get("ignore_lines") or []:
            if not _compiles(p):
                errs.append(f"{where}: ignore_lines {p!r} does not compile")
        if "ignore_lines" in r and not isinstance(r["ignore_lines"], list):
            errs.append(f"{where}: ignore_lines is a list")
        ent = r.get("entry")
        if ent is not None and not (isinstance(ent, dict) and _compiles(ent.get("start")) and ent.get("start")
                                    and _compiles(ent.get("end")) and ent.get("end")):
            errs.append(f"{where}: entry is {{start, end}} with regular expressions")
        for k in ("records", "dated_lines_are_notices"):
            if k in r and not isinstance(r[k], bool):
                errs.append(f"{where}: {k} is true or false")
        if r.get("default_event_type") is not None and r["default_event_type"] not in EVENT_TYPES:
            errs.append(f"{where}: default_event_type {r['default_event_type']!r} is not an event type")
        if r.get("every_hours") is not None and not (isinstance(r["every_hours"], (int, float))
                                                     and not isinstance(r["every_hours"], bool) and r["every_hours"] > 0):
            errs.append(f"{where}: every_hours is a positive number")
        if r.get("headers") is not None and r["headers"] != "browser":
            errs.append(f"{where}: headers is 'browser' or absent")
        for k in ("authority", "noun", "link_text", "signup_url", "feed_source_id"):
            if r.get(k) is not None and not (isinstance(r[k], str) and r[k].strip()):
                errs.append(f"{where}: {k} is a non-empty string or null")
        seeds = r.get("seeds")
        if seeds is not None:
            if not isinstance(seeds, dict):
                errs.append(f"{where}: seeds is {{url: [copies]}}")
            else:
                for u, copies in seeds.items():
                    if u not in urls:
                        errs.append(f"{where}: seed URL {u!r} is not one of the row's urls")
                    if not isinstance(copies, list) or not copies:
                        errs.append(f"{where}: seeds[{u!r}] is a non-empty list")
                        continue
                    ats = []
                    for c in copies:
                        if not (isinstance(c, dict) and isinstance(c.get("path"), str)
                                and isinstance(c.get("fetched_at"), str) and _ISO_Z.match(c["fetched_at"])
                                and isinstance(c.get("http_status"), int)):
                            errs.append(f"{where}: a seed copy is {{path, fetched_at (UTC, Z), http_status}}")
                            continue
                        ats.append(c["fetched_at"])
                        if root is not None and not (Path(root) / c["path"]).exists():
                            # research/*/raw/ is git-ignored: a clone without that folder has no seed copies at all
                            # (the monitor then takes its first snapshot live); a missing file in a present folder is an error
                            raw_dir = Path(root) / Path(c["path"]).parts[0] / Path(c["path"]).parts[1] / "raw"
                            if raw_dir.exists():
                                errs.append(f"{where}: seed copy {c['path']} does not exist")
                    if ats != sorted(ats):
                        errs.append(f"{where}: seeds[{u!r}] are oldest first")
    if keys != sorted(keys):
        errs.append("channels are not sorted by (state, id)")
    return errs


# ---------------------------------------------------------------- barriers (docs/plan.md §2.y)

def barrier_for(r: dict) -> tuple[str | None, str | None]:
    """(barrier, review): what keeps an unmonitored channel's notices off the open web, from its unmonitored_reason,
    its kind and the research note; (None, None) for a monitored row or one read through a feed; (None, why) when the
    register does not settle it (listed for review, never guessed)."""
    if r.get("monitored") or r.get("unmonitored_reason") == "feed_ingested":
        return None, None
    why, kind = r.get("unmonitored_reason"), r.get("channel_kind")
    low = re.sub(r"\s+", " ", str(r.get("note") or "")).strip().lower()
    fixed = {"login": "login_required", "bot_wall": "bot_wall", "image_only": "image_only",
             "email_only": "no_web_page",        # sent by email or text to subscribers; no page to read
             "none_found": "no_web_page"}.get(why)
    if fixed:
        return fixed, None
    if why == "app_only":
        return None, "an app only (Swim Guide): no web page of its own, but no login wall either"
    if kind == "lights_signs_page":
        return "signs_only", None
    if "answers 403" in low:
        return "bot_wall", None
    if "varies by town" in low or "town pages not surveyed" in low:
        return "varies_by_town", None
    if "printed only" in low or "paid notice" in low or re.search(r"\b(?:pamphlets?|leaflets?|letters to|mail notice|"
                                                                   r"in sewer bills)\b", low):
        return "print_only", None
    if "no own page found" in low or "no web channel found" in low:
        return "no_web_page", None
    if low.startswith("no url known (not searched)") or any(p in low for p in (
            "not verified in the research", "listed in the research as not checked", "channel not researched",
            "sign-up route not found", "not named in the research", "not searched individually")):
        return "not_verified", None
    return None, f"the register does not say what keeps it off the web: {low[:120]}"


def apply_barriers(path: Path = REGISTER) -> dict:
    """Write barrier (and barrier_review) on every row of the register, with the current schema block; returns
    {barrier or 'review': rows}."""
    from collections import Counter
    doc = read_json(path, None) or {}
    counts = Counter()
    for r in doc.get("channels") or []:
        bar, review = barrier_for(r)
        r["barrier"] = bar
        if review:
            r["barrier_review"] = review
        else:
            r.pop("barrier_review", None)
        counts[bar or ("review" if review else "none")] += 1
    chans = sorted(doc.get("channels") or [], key=lambda r: (str(r.get("state")), str(r.get("id"))))
    out = {"about": ABOUT, "schema_version": 1, "schema": SCHEMA, "channels": chans}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return dict(counts)


def load_register(path: Path = REGISTER) -> dict:
    return read_json(path, None) or {"about": ABOUT, "schema_version": 1, "schema": SCHEMA, "channels": []}


def write_schema(path: Path = REGISTER) -> dict:
    """The register file with the current schema block, keeping its channels (sorted by state, id)."""
    doc = read_json(path, None) or {}
    chans = sorted(doc.get("channels") or [], key=lambda r: (str(r.get("state")), str(r.get("id"))))
    out = {"about": ABOUT, "schema_version": 1, "schema": SCHEMA, "channels": chans}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return out


# ---------------------------------------------------------------- text extraction

_DROP = re.compile(r"(?is)<(script|style|noscript|svg|head|template|iframe|object)\b[^>]*>.*?</\1\s*>")
_BLOCK = re.compile(r"(?i)<(?:br|/?p|/?div|/?li|/?h[1-6]|/?tr|/?td|/?th|/?section|/?article|/?header|/?footer|/?nav|"
                    r"/?ul|/?ol|/?table|/?main|/?aside|/?button|/?option|/?dt|/?dd|/?blockquote|/?form|/?label|"
                    r"/?figcaption|/?caption|/?summary|/?details|hr)\b[^>]*>")


def _clean(lines) -> list[str]:
    out = []
    for ln in lines:
        s = re.sub(r"\s+", " ", ln).strip()
        if s:
            out.append(scrub_text(s))
    return out


def html_lines(text: str) -> list[str]:
    t = re.sub(r"(?s)<!--.*?-->", " ", text or "")
    t = _DROP.sub(" ", t)
    t = _BLOCK.sub("\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return _clean(t.split("\n"))


def pdf_lines(body: bytes) -> list[str]:
    from ingest import nh_pdftext
    items = nh_pdftext.text_items(body)
    return _clean(" ".join(i["text"] for i in row) for row in nh_pdftext.rows(items))


def json_lines(body: bytes) -> list[str]:
    js = json.loads(body.decode("utf-8", "replace"))
    out: list[str] = []

    def walk(v, path):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{path}.{k}" if path else str(k))
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
        elif v is not None and v != "":
            s = re.sub(r"<[^>]+>", " ", html.unescape(str(v))) if isinstance(v, str) else json.dumps(v)
            out.append(f"{path}: {s}")
    walk(js, "")
    return _clean(out)


def rss_lines(body: bytes) -> list[str]:
    """One line per item or entry: 'date | title | summary' (no XML parser: entity expansion stays off)."""
    t = body.decode("utf-8", "replace")
    out = []
    for m in re.finditer(r"(?is)<(item|entry)\b[^>]*>(.*?)</\1>", t):
        blk = m.group(2)

        def tag(*names):
            for n in names:
                x = re.search(rf"(?is)<{n}\b[^>]*>(.*?)</{n}>", blk)
                if x:
                    v = re.sub(r"(?s)<!\[CDATA\[(.*?)\]\]>", r"\1", x.group(1))
                    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(v)))).strip()
            return ""
        out.append(" | ".join(x for x in (tag("pubDate", "published", "updated", "dc:date"), tag("title"),
                                           tag("description", "summary", "content")) if x))
    return _clean(out)


def extract(method: str, body: bytes) -> tuple[list[str], str | None]:
    """(lines, parse error or None)."""
    try:
        if method == "pdf":
            lines = pdf_lines(body)
            return lines, (None if lines else "no text in the PDF (scanned image?)")
        if method == "json":
            return json_lines(body), None
        if method == "rss":
            return rss_lines(body), None
        return html_lines(body.decode("utf-8", "replace")), None
    except Exception as e:                                    # a page that cannot be read is still reachable
        return [], f"{type(e).__name__}: {e}"


def filtered(lines: list[str], ignore: list[str]) -> list[str]:
    pats = [re.compile(p) for p in ignore or []]
    return [ln for ln in lines if not any(p.search(ln) for p in pats)]


def text_hash(lines: list[str]) -> str:
    """Order-insensitive: the sorted distinct lines (a page that only reorders its rows has not changed)."""
    return hashlib.sha256("\n".join(sorted(set(lines))).encode()).hexdigest()


def entry_lines(lines: list[str], entry: dict | None) -> list[str] | None:
    """The lines of one row's entry on a shared page; None when the entry is not on the page."""
    if not entry:
        return lines
    start, end = re.compile(entry["start"]), re.compile(entry["end"])
    for i, ln in enumerate(lines):
        if start.search(ln):
            out = [ln]
            for x in lines[i + 1:]:
                if end.search(x):
                    break
                out.append(x)
            return out
    return None


def page_id(url: str) -> str:
    u = re.sub(r"^https?://(?:www\.)?", "", url).split("#")[0]
    slug = re.sub(r"[^a-z0-9]+", "-", u.lower()).strip("-")[:60].strip("-")
    return f"{slug}-{hashlib.sha1(url.encode()).hexdigest()[:6]}"


# ---------------------------------------------------------------- snapshots

def _t(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def observe(snap: dict | None, res: dict, lines_full: list[str], ignore: list[str],
            entries: list[dict] | None = None) -> tuple[dict, dict | None]:
    """One fetch into the page snapshot. res: {at, ok, http_status, final_url, content_type, content_hash,
    error, parse_error, last_modified, seed}. Returns (snapshot, change) where change is None (no change),
    {"baseline": True, ...} for the first good snapshot, {"added", "removed", ...} for a change of text, or
    {"unreachable": True} for a failed fetch (the last good snapshot stays)."""
    snap = dict(snap or {})
    at = res["at"]
    snap.setdefault("first_fetch_at", at)
    snap.setdefault("last_change_at", None)
    snap.setdefault("unreachable_since", None)
    log = list(snap.get("fetches") or [])
    snap["last_fetch_at"], snap["last_fetch_ok"] = at, bool(res["ok"])
    snap["last_http_status"], snap["last_error"] = res.get("http_status"), res.get("error")
    if not res["ok"]:
        log.append([at, False, res.get("http_status"), None])
        snap["fetches"] = log[-FETCH_LOG_MAX:]
        snap["unreachable_since"] = snap.get("unreachable_since") or at
        return snap, {"at": at, "unreachable": True, "http_status": res.get("http_status"), "error": res.get("error")}
    lines = filtered(lines_full, ignore)
    th = text_hash(lines)
    log.append([at, True, res.get("http_status"), th])
    snap["fetches"] = log[-FETCH_LOG_MAX:]
    snap["unreachable_since"] = None
    prev = snap.get("last_ok")
    change = None
    if prev is None:
        snap["text_since"] = at
        change = {"at": at, "baseline": True, "to_hash": th, "added": [], "removed": [], "lines": len(lines)}
    elif prev.get("text_hash") != th:
        before = set(prev.get("lines") or [])
        now_set = set(lines)
        added = list(dict.fromkeys(ln for ln in lines if ln not in before))
        removed = list(dict.fromkeys(ln for ln in (prev.get("lines") or []) if ln not in now_set))
        snap["text_since"] = at
        snap["last_change_at"] = at
        change = {"at": at, "from_hash": prev.get("text_hash"), "to_hash": th, "added": added, "removed": removed}
    snap["last_ok"] = {"at": at, "http_status": res.get("http_status"), "final_url": res.get("final_url"),
                       "content_type": res.get("content_type"), "content_hash": res.get("content_hash"),
                       "text_hash": th, "last_modified": res.get("last_modified"), "parse_error": res.get("parse_error"),
                       "seed": bool(res.get("seed")),
                       "raw": res.get("raw") or ((prev or {}).get("raw") if th == (prev or {}).get("text_hash") else None),
                       "lines": lines, "lines_full": lines_full}
    ents = dict(snap.get("entries") or {})
    for e in entries or []:
        found = entry_lines(lines_full, e) is not None
        cur = ents.get(e["start"])
        if cur is None or cur.get("found") != found:
            ents[e["start"]] = {"found": found, "since": at}
    if entries:
        snap["entries"] = ents
    return snap, change


# ---------------------------------------------------------------- notices

_MON = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
        "oct": 10, "nov": 11, "dec": 12}
_MONTH = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_DATE_RES = [
    ("mdy_name", re.compile(rf"\b{_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)),
    ("ymd", re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")),
    ("mdy_num", re.compile(r"(?<![\d/.-])(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})(?![\d/-])")),
    ("dmy_name", re.compile(rf"\b(\d{{1,2}})\s+{_MONTH}\.?,?\s+(\d{{4}})\b", re.I)),
    ("md_name", re.compile(rf"\b{_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!,?\s*\d)", re.I)),
]


def find_dates(s: str, ref: date) -> list[tuple[int, date]]:
    """(position, date) of every date to the day in s, in order. A month and day without a year take the year
    that puts them closest before ref (or up to a day after it)."""
    out: dict[int, date] = {}
    taken: list[tuple[int, int]] = []
    for kind, rx in _DATE_RES:
        for m in rx.finditer(s):
            if any(a <= m.start() < b or a < m.end() <= b for a, b in taken):
                continue
            g = m.groups()
            try:
                if kind == "mdy_name":
                    d = date(int(g[2]), _MON[g[0][:3].lower()], int(g[1]))
                elif kind == "ymd":
                    d = date(int(g[0]), int(g[1]), int(g[2]))
                elif kind == "mdy_num":
                    y = int(g[2]) + (2000 if len(g[2]) == 2 else 0)
                    d = date(y, int(g[0]), int(g[1]))
                elif kind == "dmy_name":
                    d = date(int(g[2]), _MON[g[1][:3].lower()], int(g[0]))
                else:
                    mo, dy = _MON[g[0][:3].lower()], int(g[1])
                    d = date(ref.year, mo, dy)
                    if d > ref + timedelta(days=1):
                        d = date(ref.year - 1, mo, dy)
            except (ValueError, KeyError):
                continue
            if not 1990 <= d.year <= ref.year + 1:
                continue
            out[m.start()] = d
            taken.append((m.start(), m.end()))
    return sorted(out.items())


STRONG = re.compile(r"\b(?:overflow(?:s|ed|ing)?|CSOs?|combined sewer|discharg(?:e|es|ed|ing)|bypass(?:es|ed|ing)?|"
                    r"SSOs?|spill(?:s|ed)?|sewage release)\b", re.I)
WEAK = re.compile(r"\badvisor(?:y|ies)\b|\boccurring\b|\bha(?:s|ve) occurred\b", re.I)
CONTEXT = re.compile(r"sewer|sewage|\bCSO|outfall|overflow|discharg|bypass|river|\bbay\b|creek|brook|harbou?r|beach|"
                     r"\bwater|swim|bathing", re.I)
NOT_EVENT = re.compile(r"\b(?:hearings?|meetings?|workshops?|webinars?|comment period|public comment|agendas?|minutes|"
                       r"presentations?|progress reports?|annual reports?|semi-?annual|quarterly|construction|"
                       r"long term control plan|LTCP|permits?|contracts?|bids?|RFPs?|RFQs?|grants?|budgets?|awards?|"
                       r"newsletters?|boil[- ]water|drinking water|traffic|road closures?|parking|snow|heat advisory|"
                       r"wind advisory|winter|travel advisory|tax|billing|press release)\b", re.I)
NEGATIVE = re.compile(r"\bunlikely\b|\bno (?:CSO|overflow|discharge|bypass|spill)(?:e?s)?\b|"
                      r"\bnot (?:occurring|discharging|active|overflowing)\b|\b(?:gate|outfall)\b[^.]*\bis closed\b", re.I)
END = re.compile(r"\b(?:ended|has ended|ceased|stopped|is over|concluded|no longer|lifted|resolved|until)\b", re.I)
GENERIC = [re.compile(p, re.I) for p in (
    r"CSO event (?:likely|unlikely)", r"overflow is likely", r"indicates when an overflow", r"confirmation of any discharge",
    r"predicts if a CSO is likely", r"an overflow likely", r"Precipitation totals and overflow thresholds")]
_DATE_LINE_WORDS = re.compile(r"(?i)\b(?:posted|on|updated|date|issued|published|at|am|pm|a\.m\.|p\.m\.)\b|[\d:,|.\s-]")


def _sentences(line: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])", line) if s.strip()]


def _date_line(line: str, ref: date) -> date | None:
    """The date of a line that is only a date ('Posted on November 2, 2026'), else None."""
    ds = find_dates(line, ref)
    if len(ds) != 1:
        return None
    rest = line
    for kind, rx in _DATE_RES:
        rest = rx.sub(" ", rest)
    return ds[0][1] if not _DATE_LINE_WORDS.sub("", rest).strip() else None


def event_type_of(s: str, default: str | None) -> tuple[str, str]:
    """(event type, the words it rests on)."""
    if re.search(r"\bbypass", s, re.I):
        if re.search(r"\b(?:plant|treatment|WWTP|WPCF|WRRF|facility)\b", s, re.I):
            return "plant_bypass", "bypass at a treatment plant"
        return "bypass", "bypass"
    if re.search(r"\bSSOs?\b|sanitary sewer", s, re.I):
        return "sso", "sanitary sewer overflow"
    if re.search(r"\bCSOs?\b|combined sewer", s, re.I):
        return "cso", "CSO / combined sewer"
    if re.search(r"\bblend", s, re.I):
        return "blended", "blending"
    if re.search(r"beach|swim|bathing", s, re.I):
        if re.search(r"\bclos(?:ed|ure|ing)\b", s, re.I):
            return "beach_closure", "beach closure"
        if re.search(r"advisor", s, re.I):
            return "beach_advisory", "beach advisory"
    return (default or "unknown"), ("the channel's default type" if default else "no type words")


def find_notices(added: list[str], lines_full: list[str], cfg: dict, generic: set[str], at: str) -> tuple[list[dict], list[dict]]:
    """(notices, skipped) among the added lines of a page. cfg: the page's rows merged (status patterns,
    dated_lines_are_notices, default_event_type)."""
    ref = _t(at).astimezone(TZ).date()
    status_res = [re.compile(p) for p in cfg.get("status_patterns") or []]
    notices, skipped = [], []
    index = {ln: i for i, ln in enumerate(lines_full)}
    for ln in added:
        for s in _sentences(ln):
            if s in generic or ln in generic or any(g.search(s) for g in GENERIC):
                continue
            if any(p.search(s) for p in status_res):
                continue
            dates = find_dates(s, ref)
            via = "sentence"
            words = bool(STRONG.search(s) or (WEAK.search(s) and CONTEXT.search(s)))
            if not dates and words and s == ln and ln in index:          # 'Title' then 'Posted on <date>'
                i = index[ln]
                for j in (i + 1, i - 1):
                    if 0 <= j < len(lines_full):
                        d = _date_line(lines_full[j], ref)
                        if d:
                            dates, via = [(0, d)], "adjacent date line"
                            break
            if not dates:
                continue
            if not (words or cfg.get("dated_lines_are_notices")):
                continue
            if NOT_EVENT.search(s) and not cfg.get("dated_lines_are_notices"):
                skipped.append({"text": s, "why": "a meeting, report, permit or other non-event item"})
                continue
            if NEGATIVE.search(s):
                skipped.append({"text": s, "why": "says no overflow is occurring"})
                continue
            start = dates[0][1]
            if start > ref + timedelta(days=1):
                skipped.append({"text": s, "why": f"dated {start} (after the fetch)"})
                continue
            if (ref - start).days > NOTICE_MAX_AGE_DAYS:
                skipped.append({"text": s, "why": f"dated {start}, more than {NOTICE_MAX_AGE_DAYS} days before the fetch"})
                continue
            end = None
            if END.search(s) and len(dates) >= 2 and dates[1][1] >= start:
                end = dates[1][1]
            et, et_basis = event_type_of(s, cfg.get("default_event_type"))
            out_m = re.search(r"\boutfalls?\s+(?:no\.?\s*|#\s*)?([0-9]{3}[A-Z]?)\b", s, re.I)
            notices.append({"text": s, "line": ln, "start": start, "end": end, "event_type": et,
                            "type_basis": et_basis, "date_from": via, "outfall": out_m.group(1).upper() if out_m else None,
                            "dates": [d.isoformat() for _, d in dates]})
    return notices, skipped


def day_iso(d: date | None) -> str | None:
    return datetime(d.year, d.month, d.day, tzinfo=TZ).isoformat() if d else None


def notice_record(n: dict, page: dict, at: str) -> dict:
    """An event record from one notice on a page (page: {url, page_id, rows})."""
    rows = page["rows"]
    ops = sorted({r["operator_id"] for r in rows if r.get("operator_id")})
    one = rows[0] if len(ops) <= 1 else None
    norm = re.sub(r"\s+", " ", n["text"]).strip().lower()
    key = f"{page['page_id']}:{n['start'].isoformat()}:{hashlib.sha1(norm.encode()).hexdigest()[:10]}"
    raw = {"notice_text": n["text"], "page_line": n["line"] if n["line"] != n["text"] else None,
           "dates_in_text": n["dates"], "date_from": n["date_from"], "type_basis": n["type_basis"],
           "first_seen_at": at, "last_seen_at": at, "removed_from_page_at": None,
           "channel_ids": [r["id"] for r in rows], "discharger_ids": ops,
           "status_basis": ("ended: the notice gives an end and its date" if n["end"] else
                            "unknown: the notice gives no end with a date"),
           "time_basis": "day: the date written in the notice; the page gives no report time (first_seen_at is our fetch)"}
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type=n["event_type"],
        status="ended" if n["end"] else "unknown",
        discharger_id=ops[0] if len(ops) == 1 else None,
        discharger_name=(one or {}).get("name") if one else (rows[0].get("authority") or rows[0].get("name")),
        npdes_permit=(one or {}).get("permit") if one else None,
        outfall_id=n["outfall"], started_at=day_iso(n["start"]), ended_at=day_iso(n["end"]), time_precision="day",
        reported_at=None, published_at=None, source_updated_at=None, fetched_at=at,
        authority=rows[0].get("authority") or rows[0].get("name"), source_url=page["url"], raw=raw)


# ---------------------------------------------------------------- health

ROLLUP_ORDER = ["status", "status_unreachable", "no_status", "entry_missing", "unreachable", "unchanged", "link_only",
                "not_checked", "feed", "not_read", "none_found"]
REASON_TEXT = {"login": "behind a login; not read", "bot_wall": "behind a bot check; not read",
               "image_only": "an image only; not read", "app_only": "shown only in a script app; not read",
               "other": "not read"}


def day_text(s: str | None) -> str:
    t = _t(s)
    if t is None:
        return ""
    d = t.astimezone(TZ)
    return f"{d:%b} {d.day}, {d.year}"


def noun_of(row: dict) -> str:
    return row.get("noun") or ("Voluntary page" if row.get("basis_kind") == "voluntary" else "Notification page")


def shown_text(lines: list[str], pattern: str) -> str | None:
    """The line(s) carrying the last match of the status pattern (a status may run over two lines of the page)."""
    starts, pos = [], 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1
    ms = list(re.finditer(pattern, " ".join(lines)))
    if not ms:
        return None
    m = ms[-1]
    return " ".join(ln for ln, st in zip(lines, starts) if st < m.end() and st + len(ln) > m.start())[:300] or None


def channel_health(row: dict, snaps: dict[str, dict], now: datetime) -> dict:
    """The health of one register row from its pages' snapshots (snaps: {url: snapshot})."""
    noun = noun_of(row)
    h = {k: row.get(k) for k in ("id", "state", "operator_id", "agency", "name", "permit", "channel_kind", "basis_kind",
                                 "legal_basis", "method", "monitored", "unmonitored_reason", "publishes", "link_text",
                                 "feed_source_id", "signup_url")}
    urls = row.get("urls") or []
    h.update({"url": urls[0] if urls else None, "urls": urls, "last_fetch": None, "last_ok": None, "reachable": None,
              "unreachable_since": None, "last_change": None, "unchanged_since": None, "days_since_change": None,
              "watching_since": None, "publishes_status": None, "shown_text": None, "entry_listed": None})
    if not row.get("monitored"):
        why = row.get("unmonitored_reason")
        if why == "none_found":
            kind, text = "none_found", ("No page found" if row.get("basis_kind") == "voluntary" else "No notification page found")
        elif why == "feed_ingested":
            kind, text = "feed", "Read as a feed"
        elif why == "email_only":
            kind, text = "not_read", "Email list; not read"
        else:
            kind, text = "not_read", f"{noun} {REASON_TEXT.get(why, 'not read')}"
        h.update({"wording": text, "wording_kind": kind, "wording_date": None})
        return h
    ss = [snaps.get(u) for u in urls]
    if not ss or any(s is None or not s.get("last_fetch_at") for s in ss):
        h.update({"wording": "Not checked yet", "wording_kind": "not_checked", "wording_date": None})
        return h
    h["last_fetch"] = min(s["last_fetch_at"] for s in ss)
    oks = [s["last_ok"]["at"] for s in ss if s.get("last_ok")]
    h["last_ok"] = min(oks) if len(oks) == len(ss) else None
    h["watching_since"] = min(s.get("first_fetch_at") for s in ss)
    down = [s for s in ss if not s.get("last_fetch_ok")]
    h["reachable"] = not down
    h["unreachable_since"] = min(s["unreachable_since"] for s in down) if down else None
    changes = [s.get("last_change_at") for s in ss if s.get("last_change_at")]
    h["last_change"] = max(changes) if changes else None
    since = [s.get("text_since") for s in ss if s.get("text_since")]
    h["unchanged_since"] = max(since) if since else None
    if h["unchanged_since"]:
        h["days_since_change"] = max(0, (now - _t(h["unchanged_since"])).days)
    # what the page shows now (the last good copy), the row's entry of a shared page
    lines = []
    for s in ss:
        lf = (s.get("last_ok") or {}).get("lines_full") or []
        ent = entry_lines(lf, row.get("entry"))
        if row.get("entry"):
            h["entry_listed"] = ent is not None
        lines += ent or []
    pat = row.get("status_pattern")
    if pat:
        h["shown_text"] = shown_text(lines, pat)
    pub = row.get("publishes")
    if pub == "status":
        h["publishes_status"] = bool(h["shown_text"]) if pat else bool(h["reachable"])
    else:
        h["publishes_status"] = False
    if down:
        kind = "status_unreachable" if pub == "status" else "unreachable"
        h.update({"wording": f"{noun} unreachable since {day_text(h['unreachable_since'])}", "wording_kind": kind,
                  "wording_date": h["unreachable_since"]})
    elif row.get("entry") and not h["entry_listed"]:
        since_e = max(((s.get("entries") or {}).get(row["entry"]["start"]) or {}).get("since") or "" for s in ss) or None
        h.update({"wording": f"Not listed on {row.get('link_text') or 'the shared site'} since {day_text(since_e)}",
                  "wording_kind": "entry_missing", "wording_date": since_e})
    elif h["publishes_status"]:
        h.update({"wording": "Publishes a current status", "wording_kind": "status", "wording_date": h["last_ok"]})
    elif pub == "status":
        h.update({"wording": f"No current status shown since {day_text(h['unchanged_since'])}", "wording_kind": "no_status",
                  "wording_date": h["unchanged_since"]})
    elif pub in ("link_only", "likelihood"):
        h.update({"wording": f"Links to {row.get('link_text') or 'another site'} only", "wording_kind": "link_only",
                  "wording_date": None})
    else:
        h.update({"wording": f"{noun} unchanged since {day_text(h['unchanged_since'])}", "wording_kind": "unchanged",
                  "wording_date": h["unchanged_since"]})
    return h


def rollup(rows: list[dict]) -> list[dict]:
    """Per operator (or agency) and permit: the most telling line of its channels (ROLLUP_ORDER)."""
    groups: dict[tuple, list[dict]] = {}
    for h in rows:
        groups.setdefault((h.get("operator_id") or "", h.get("agency") or "", h.get("permit") or ""), []).append(h)
    out = []
    for (op, ag, permit), hs in groups.items():
        best = min(hs, key=lambda h: ROLLUP_ORDER.index(h["wording_kind"]) if h["wording_kind"] in ROLLUP_ORDER else 99)
        out.append({"operator_id": op or None, "agency": ag or None, "name": hs[0].get("name"), "permit": permit or None,
                    "basis_kind": sorted({h["basis_kind"] for h in hs})[0] if len({h["basis_kind"] for h in hs}) == 1 else "mixed",
                    "wording": best["wording"], "wording_kind": best["wording_kind"], "wording_date": best.get("wording_date"),
                    "from_channel": best["id"], "publishes_status": any(h.get("publishes_status") for h in hs),
                    "channels": [h["id"] for h in hs]})
    out.sort(key=lambda r: (r["operator_id"] or "~", r["agency"] or "", r["permit"] or ""))
    return out


PUBLIC_FIELDS = ["id", "operator_id", "agency", "name", "permit", "channel_kind", "basis_kind", "legal_basis", "url",
                 "method", "monitored", "unmonitored_reason", "feed_source_id", "signup_url", "publishes",
                 "last_fetch", "last_change", "unchanged_since", "days_since_change", "reachable", "unreachable_since",
                 "publishes_status", "shown_text", "entry_listed", "wording", "wording_kind", "wording_date"]


def build_health(channels: list[dict], snaps: dict[str, dict], now: datetime) -> dict:
    states: dict[str, dict] = {}
    for st in sorted({r["state"] for r in channels}):
        hs = [channel_health(r, snaps, now) for r in channels if r["state"] == st]
        ops = rollup(hs)
        counts = {"channels": len(hs), "monitored": sum(1 for h in hs if h["monitored"]),
                  "reachable": sum(1 for h in hs if h["reachable"]),
                  "unreachable": sum(1 for h in hs if h["reachable"] is False),
                  "publishing_status": sum(1 for h in hs if h["publishes_status"]),
                  "changed_7d": sum(1 for h in hs if h["last_change"] and (now - _t(h["last_change"])).days < 7),
                  "operators": len(ops), "operators_with_status": sum(1 for o in ops if o["publishes_status"]),
                  "operators_none_found": sum(1 for o in ops if o["wording_kind"] == "none_found"),
                  "by_basis": {k: sum(1 for h in hs if h["basis_kind"] == k) for k in ENUMS["basis_kind"]}}
        states[st] = {"counts": counts, "operators": ops,
                      "channels": [{k: h.get(k) for k in PUBLIC_FIELDS} for h in hs]}
    return {"built": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "source_id": SOURCE_ID,
            "definitions": {
                "reachable": "the last fetch answered with HTTP 2xx (after redirects)",
                "unchanged_since": "when the page's current text was first seen (by this monitor or the research copies "
                                   "it started from); reordering and volatile readings are not changes",
                "publishes_status": "the page shows a current status now (found by the channel's status pattern)",
                "wording": "one public line per channel; operators carry the most telling line of their channels",
                "basis_kind": "law, permit or voluntary: why the channel is public"},
            "states": states}


# ---------------------------------------------------------------- the run

def pages_of(channels: list[dict]) -> dict[str, dict]:
    """{url: {url, page_id, method, rows, ignore, browser, every_hours, seeds, entries, cfg}} for the monitored rows."""
    pages: dict[str, dict] = {}
    for r in channels:
        if not r.get("monitored"):
            continue
        for u in r.get("urls") or []:
            p = pages.setdefault(u, {"url": u, "page_id": page_id(u), "method": r["method"], "rows": [], "ignore": [],
                                     "browser": False, "every_hours": None, "seeds": None, "entries": [],
                                     "cfg": {"status_patterns": [], "dated_lines_are_notices": False,
                                             "default_event_type": None, "records": False, "shared": False}})
            p["rows"].append(r)
            p["ignore"] += [x for x in r.get("ignore_lines") or [] if x not in p["ignore"]]
            p["browser"] |= r.get("headers") == "browser"
            if r.get("every_hours"):
                p["every_hours"] = min(p["every_hours"] or r["every_hours"], r["every_hours"])
            if (r.get("seeds") or {}).get(u) and p["seeds"] is None:
                p["seeds"] = r["seeds"][u]
            if r.get("entry") and r["entry"] not in p["entries"]:
                p["entries"].append(r["entry"])
            c = p["cfg"]
            if r.get("status_pattern") and r["status_pattern"] not in c["status_patterns"]:
                c["status_patterns"].append(r["status_pattern"])
            c["dated_lines_are_notices"] |= bool(r.get("dated_lines_are_notices"))
            c["default_event_type"] = c["default_event_type"] or r.get("default_event_type")
            c["records"] |= r.get("records", True) is not False
            c["shared"] |= r.get("channel_kind") == "shared_site"
    return pages


def due(snap: dict | None, every_hours, now: datetime) -> bool:
    if not every_hours or not snap or not snap.get("last_fetch_at") or (snap.get("last_ok") or {}).get("seed"):
        return True
    return now - _t(snap["last_fetch_at"]) >= timedelta(hours=float(every_hours) - 0.25)


def fetch(url: str, browser: bool = False) -> dict:
    import requests
    at = now_iso()
    hdr = dict(BROWSER_HEADERS if browser else HEADERS)
    try:
        r = requests.get(url, headers=hdr, timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:
        return {"at": at, "ok": False, "http_status": None, "error": f"{type(e).__name__}: {e}"[:300], "body": b""}
    ok = 200 <= r.status_code < 300 and bool(r.content)
    return {"at": at, "ok": ok, "http_status": r.status_code, "final_url": r.url,
            "content_type": r.headers.get("Content-Type"), "last_modified": r.headers.get("Last-Modified"),
            "error": None if ok else f"HTTP {r.status_code}" + ("" if r.content else " (empty body)"),
            "body": r.content}


EXT = {"html": "html", "json": "json", "pdf": "pdf", "rss": "xml"}


def seed_snapshot(page: dict, root: Path = ROOT) -> tuple[dict | None, list[dict]]:
    """The page's snapshot built from its seed copies (oldest first), and the changes between them."""
    snap, changes = None, []
    for c in page.get("seeds") or []:
        p = root / c["path"]
        if not p.exists():
            continue
        body = p.read_bytes()
        ok = 200 <= int(c.get("http_status") or 0) < 300
        lines, perr = extract(page["method"], body) if ok else ([], None)
        res = {"at": c["fetched_at"], "ok": ok, "http_status": c.get("http_status"), "final_url": None,
               "content_type": None, "content_hash": hashlib.sha256(body).hexdigest(),
               "error": None if ok else f"HTTP {c.get('http_status')}", "parse_error": perr, "seed": True,
               "raw": c["path"]}
        snap, ch = observe(snap, res, lines, page["ignore"], page["entries"])
        if ch:
            ch["seed"] = c["path"]
            changes.append(ch)
    if snap is not None:
        snap["seeded_from"] = [c["path"] for c in page.get("seeds") or []]
    return snap, changes


def run(channels: list[dict], now: datetime | None = None, fetcher=fetch, store: Path = STORE, save=True,
        root: Path = ROOT, fetch_pages: bool = True, raw_saver=None) -> dict:
    """One monitor run over the register rows: fetch, snapshot, diff, notices -> records, health. Returns
    {records, health, snaps, stats, results}. fetcher(url, browser) -> fetch result and raw_saver(source, body,
    ext) -> path (default save_raw) are replaceable for tests."""
    raw_saver = raw_saver or save_raw
    now = now or datetime.now(UTC)
    pages_dir = store / "pages"
    pages = pages_of(channels)
    snaps: dict[str, dict] = {}
    seeded_changes: dict[str, list] = {}
    for u, p in pages.items():
        s = read_json(pages_dir / f"{p['page_id']}.json", None)
        if s is None and p["seeds"]:
            s, seeded_changes[u] = seed_snapshot(p, root)
        snaps[u] = s
    todo = [u for u, p in pages.items() if fetch_pages and due(snaps.get(u), p["every_hours"], now)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = dict(zip(todo, ex.map(lambda u: fetcher(u, pages[u]["browser"]), todo)))
    store_records = read_json(store / "records.json", {}) or {}
    generic = set()
    for u, p in pages.items():                                 # the shared sites' own wording is never a notice
        if p["cfg"]["shared"] and snaps.get(u) and snaps[u].get("last_ok"):
            generic |= set(snaps[u]["last_ok"].get("lines_full") or [])
    stats = {"pages": len(pages), "fetched": len(results), "reachable": 0, "changed": 0, "records_new": 0}
    for u, res in results.items():
        p = pages[u]
        body = res.pop("body", b"") or b""
        res["content_hash"] = hashlib.sha256(body).hexdigest() if body else None
        lines, perr = extract(p["method"], body) if res["ok"] else ([], None)
        res["parse_error"] = perr
        prev = snaps.get(u)
        th = text_hash(filtered(lines, p["ignore"])) if res["ok"] else None
        if save and body:
            key = th if res["ok"] else "err:" + res["content_hash"]
            if (prev or {}).get("raw_key") != key:
                path = Path(raw_saver(f"{SOURCE_ID}/{p['page_id']}", body, EXT.get(p["method"], "bin")))
                res["raw"] = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
                prev = dict(prev or {})
                prev["raw_key"] = key
        snap, ch = observe(prev, res, lines, p["ignore"], p["entries"])
        snap.update({"page_id": p["page_id"], "url": u, "method": p["method"], "channel_ids": [r["id"] for r in p["rows"]]})
        stats["reachable"] += bool(res["ok"])
        new_ids, skipped = [], []
        if ch and ch.get("added") and p["cfg"]["records"]:
            gen = generic if not p["cfg"]["shared"] else generic | set(lines)
            notes, skipped = find_notices(ch["added"], lines, p["cfg"], gen, res["at"])
            for n in notes:
                rec = notice_record(n, p, res["at"])
                if rec["event_id"] not in store_records:
                    store_records[rec["event_id"]] = rec
                    new_ids.append(rec["event_id"])
        if ch:
            if ch.get("added") or ch.get("removed"):
                stats["changed"] += 1
            ch.update({"notices": new_ids, "skipped": skipped})
            log = list(snap.get("changes") or [])
            for sc in seeded_changes.get(u, []):
                log.append(sc)
            log.append({**ch, "added": ch.get("added", [])[:200], "removed": ch.get("removed", [])[:200]})
            snap["changes"] = log[-CHANGE_LOG_MAX:]
        elif seeded_changes.get(u):
            snap["changes"] = (list(snap.get("changes") or []) + seeded_changes[u])[-CHANGE_LOG_MAX:]
        stats["records_new"] += len(new_ids)
        snaps[u] = snap
        if save:
            write_json(pages_dir / f"{p['page_id']}.json", snap)
    # notices still on the page / gone from it
    for rec in store_records.values():
        url = rec.get("source_url")
        s = snaps.get(url)
        if not s or not s.get("last_ok") or url not in results or not results[url]["ok"]:
            continue
        here = any(rec["raw"]["notice_text"] in ln for ln in s["last_ok"].get("lines_full") or [])
        if here:
            rec["raw"]["last_seen_at"], rec["raw"]["removed_from_page_at"] = s["last_ok"]["at"], None
        elif not rec["raw"].get("removed_from_page_at"):
            rec["raw"]["removed_from_page_at"] = s["last_ok"]["at"]
    health = build_health(channels, snaps, now)
    if save:
        write_json(store / "records.json", store_records)
        write_json(store / "health.json", health)
    return {"records": list(store_records.values()), "health": health, "snaps": snaps, "stats": stats,
            "results": {u: {k: v for k, v in r.items() if k != "body"} for u, r in results.items()}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", action="append", help="only these states (repeatable)")
    ap.add_argument("--validate", action="store_true", help="validate the register and stop")
    ap.add_argument("--write-schema", action="store_true", help="write the schema block into the register and stop")
    ap.add_argument("--barriers", action="store_true", help="write each row's barrier into the register and stop")
    ap.add_argument("--no-fetch", action="store_true", help="rebuild health from the snapshots without fetching")
    a = ap.parse_args(argv)
    if a.write_schema:
        doc = write_schema()
        print(f"{REGISTER}: schema written, {len(doc['channels'])} channels kept")
        return 0
    if a.barriers:
        print(f"{REGISTER}: barriers written: {apply_barriers()}")
        return 0
    try:
        doc = load_register()
    except (OSError, ValueError) as e:                     # another builder mid-write: try again next refresh
        print(f"{SOURCE_ID}: the register could not be read ({e}); nothing fetched", file=sys.stderr)
        return 1
    errs = validate_register(doc, read_json(DATA_DIR / "dischargers.json", []), ROOT)
    if errs:
        print(f"{SOURCE_ID}: the register has {len(errs)} problem(s):\n  " + "\n  ".join(errs[:40]), file=sys.stderr)
        if a.validate:
            return 1
    if a.validate:
        print(f"{REGISTER}: valid, {len(doc['channels'])} channels")
        return 0
    bad = {r.get("id") for r in doc["channels"] if isinstance(r, dict) and validate_register(
        {"schema_version": 1, "channels": [r]})}
    channels = [r for r in doc["channels"] if r.get("id") not in bad and (not a.state or r.get("state") in a.state)]
    out = run(channels, fetch_pages=not a.no_fetch)
    if a.no_fetch:
        print(f"{SOURCE_ID}: health rebuilt from the snapshots, nothing fetched -> {HEALTH}")
        return 0
    recs = sorted(out["records"], key=lambda r: r.get("started_at") or "", reverse=True)
    h = out["health"]["states"]
    meta = {"statewide": False, "covers_permits": [], "states": sorted(h),
            "pages": out["stats"]["pages"], "fetched": out["stats"]["fetched"], "reachable": out["stats"]["reachable"],
            "changed": out["stats"]["changed"], "records_new": out["stats"]["records_new"],
            "health_counts": {st: v["counts"] for st, v in h.items()},
            "register_rows": len(channels), "register_rows_skipped_invalid": sorted(x for x in bad if x),
            "time_precision": "day", "label": "dated notices found on public notification pages"}
    down = [u for u, r in out["results"].items() if not r["ok"]]
    err = (f"{len(down)} of {len(out['results'])} pages unreachable" if down else None)
    all_down = bool(out["results"]) and len(down) == len(out["results"])
    write_events(SOURCE_ID, recs, ok=not all_down, error=err, meta=meta)
    s = out["stats"]
    status_n = sum(v["counts"]["publishing_status"] for v in h.values())
    print(f"{SOURCE_ID}: {s['fetched']} of {s['pages']} pages fetched, {s['reachable']} reachable, {s['changed']} "
          f"changed, {s['records_new']} new records ({len(recs)} kept); {status_n} channels show a status -> {HEALTH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
