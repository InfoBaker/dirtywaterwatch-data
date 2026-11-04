#!/usr/bin/env python3
"""Write docs/source-tally.md: a running tally of every information source, state by state, and which we get.

    python3 scripts/gen_source_tally.py [--root DIR] [--out FILE] [--now ISO] [--obl-dir DIR]

Owner (2026-11-03): "a running tally of all information sources and which ones we get and don't get for each
state so we can keep track of opportunities to consider." Run at the end of every refresh (`make tally`, called
from scripts/refresh.sh). Reads only; the one file it writes is docs/source-tally.md. Nothing is fetched.

Inputs (all under --root, default the project):
  docs/source-checklist.json      every source considered (status used/candidate/watch/rejected/unreachable)
  data/sources/*.yaml             the source registry (enabled, role, states, cadence, registry_ids)
  out/sources.json                feed health (last_ok_at, stale, count)
  out/coverage.json               per-state grade and sentence, per-feed precision, cadence, 12-month records
  data/notice-channels.json       the public-notice channel register (else data/notice-channels.draft.json; if
                                  neither exists the section says so)
  docs/owner-signups.md, docs/subscriptions.md, docs/decisions.md   where an owner item is linked from
  out/waters.json, data/waters-*.json, data/outfalls-*.json (the outfall registry), out/events.json,
  data/build/status.json          the water-record block (are the water bodies identified?)

Per state (fixed order, New England then the mid-Atlantic): the coverage grade and sentence; "Collected now"
(each feed that runs); "Monitored channels" (register rows monitored true); "Not collected" (checklist rows with
status candidate, watch, rejected or unreachable that no feed collects, registry rows with no feed and no
checklist row, register rows monitored false) with a short reason and what would unlock each; "Opportunities"
(the not-collected rows worth chasing, ranked: dated public channels, then feeds with history, then context
sources); and "Water records" (origin, geometry, outfalls with no record, unplaced reports, duplicate names).

A source is never described as safe or clean here; this is a map of what we read and what we do not.
No personal name or contact reaches the file: emails, phone numbers and the names in data/build/name-blocklist.json
are scrubbed from every text taken from the inputs, and owner items are linked by line, never quoted.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# the order the sections take: New England (alphabetical), then the mid-Atlantic (alphabetical), then any other live
# state alphabetically. Which states are in the tally is data/rules.json `live_states` (the site's one list; this
# order alone when the file has none)
STATE_ORDER = ["CT", "MA", "ME", "NH", "RI", "VT", "NJ", "NY", "PA", "DC", "MD", "VA"]
STATES = list(STATE_ORDER)
STATE_NAMES = {"CT": "Connecticut", "MA": "Massachusetts", "ME": "Maine", "NH": "New Hampshire",
               "RI": "Rhode Island", "VT": "Vermont", "NJ": "New Jersey", "NY": "New York", "PA": "Pennsylvania",
               "DC": "District of Columbia", "MD": "Maryland", "VA": "Virginia"}
OTHER_NAMES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
               "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
               "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "MI": "Michigan",
               "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
               "NM": "New Mexico", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
               "OR": "Oregon", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
               "UT": "Utah", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
               "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands", "AS": "American Samoa",
               "MP": "Northern Mariana Islands"}


def set_live_states(root: Path) -> list[str]:
    """STATES (and STATE_NAMES for a state new to the tally) from <root>/data/rules.json `live_states`; the fixed order
    when the file has no list."""
    try:
        live = json.loads((root / "data" / "rules.json").read_text()).get("live_states")
    except (OSError, ValueError, AttributeError):
        live = None
    codes = [str(x).upper() for x in live if isinstance(x, str)] if isinstance(live, list) and live else list(STATE_ORDER)
    STATES[:] = [s for s in STATE_ORDER if s in codes] + sorted(set(codes) - set(STATE_ORDER))
    for s in STATES:
        STATE_NAMES.setdefault(s, OTHER_NAMES.get(s, s))
    return STATES
NOT_COLLECTED_STATUSES = ("candidate", "watch", "rejected", "unreachable")
STATUS_RANK = {"candidate": 0, "unreachable": 1, "registered": 2, "watch": 3, "rejected": 4}

# what would unlock a source (the label shown), in the order a person would reach for them
UNLOCKS = ["owner sign-up", "engineering work", "owner contact", "licence decision", "records request",
           "bot wall", "image-only", "no URL", "reference only", "none: rejected"]
UNLOCK_RANK = {u: i for i, u in enumerate(UNLOCKS)}
TIERS = {1: "dated public channels", 2: "feeds with history", 3: "context sources"}
OPPORTUNITY_EXCLUDED_UNLOCKS = {"reference only", "none: rejected"}
RESEARCH_ONLY_ROLES = {"science", "law", "prior_art"}
SEWAGE_TYPES = {"cso", "sso", "bypass", "blended", "plant_bypass", "unknown", "annual_total"}

# decisions that block a source: (what the source row looks like, the line of docs/decisions.md that holds the
# decision, the unlock it stands for). The line is found at run time, so numbering can change.
DECISION_LINKS = [
    (re.compile(r"nhdes-healthy-swimming-mapper|nh-des-swimming", re.I),
     re.compile(r"NHDES Healthy Swimming Mapper licence"), "licence decision", None),
    (re.compile(r"me-dep-cso-activity", re.I), re.compile(r"Freedom of Access request"), "records request", None),
    (re.compile(r"ct-deep-(cso-dashboard|performance-dashboard)", re.I), re.compile(r"do not probe the vendor endpoint"),
     "owner contact",
     # the dashboard itself is collected; what the decision holds back is the 2022-2024 history, so it is shown as a row
     {"state": "CT", "name": "CT DEEP dashboard: complete 2022-2024 history (200-row paging; vendor endpoint not to be probed)",
      "role": "events", "reason": "the dashboard returns 200 rows a view, so earlier history is partial; DEEP export or annual spreadsheets needed"}),
    (re.compile(r"va-richmond-emnet", re.I), re.compile(r"Richmond's live map"), "owner contact", None),
]

RX_LICENCE = re.compile(r"distribution is discouraged|licen[cs]e (decision|restrict|prohibit|bars|forbids)|terms (of use )?"
                        r"(prohibit|restrict|forbid)|may not be (redistributed|republished)|written permission|"
                        r"redistribution (is )?(not|prohibited)|no (re-?use|redistribution)", re.I)
RX_RECORDS = re.compile(r"records? request|public records|freedom of (access|information)|\bfoaa\b|\bfoia\b|\brtkl\b|"
                        r"right[- ]to[- ]know law|data request|ask (the )?(swsc|agency|dep\b|department|city|town|"
                        r"district|operator|utility|mwra) for (the |a |an )?(data|records?|spreadsheets?|files?|copy|export)", re.I)
RX_BOT = re.compile(r"\b403\b|cloudflare|captcha|\bbot\b|bot[- ]?(wall|check|block|detect)|blocks? (scripted|server|"
                    r"automated|non-browser)|akamai|incapsula|imperva|forbidden|access denied|\bwaf\b|js[- ]challenge", re.I)
RX_IMAGE = re.compile(r"image[- ]only|scanned|no text layer|image (map|file)|screenshot|flyer|jpe?g\b|png\b|"
                      r"map[- ]only|picture of", re.I)
RX_SIGNUP = re.compile(r"sign[- ]?up|subscribe|subscription|everbridge|nixle|constant ?contact|govdelivery|mailchimp|"
                       r"notify ?me|email (list|alerts?|notifications?)|text alerts?|alert list|member (portal|profile)|"
                       r"opt[- ]in|newsletter", re.I)
RX_CONTACT = re.compile(r"\bemail (the|a|him|her)|\bcall (the|a)|\bphone\b|contact (the|a|them)|ask (the )?(operator|"
                        r"supervisor|staff|agency|city|town)|\bletter\b|in person|by request|on request", re.I)

EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RX = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")
CONTACT_NAME_RX = re.compile(r"\bContact: [A-Z][a-z]+ [A-Z][a-z]+(?:, [A-Za-z ]+)?")
URL_RX = re.compile(r"https?://[^\s|)>\"'\]]+")


# ------------------------------------------------------------------ reading

def registry_outfalls(inp: "Inputs") -> list[dict]:
    """The official outfall registry under the tally's root (every data/outfalls-*.json through the pipeline's one
    loader); a file it cannot read is noted, never fatal."""
    sys.path.insert(0, str(ROOT / "pipeline"))
    import common
    rows = common.load_outfall_registry(inp.root / "data")
    inp.notes.extend(f"{x}" for x in common.OUTFALL_REGISTRY_SKIPPED)
    return [o for o in rows if not common.is_provisional(o) or o.get("outfall_kind") == "cso"]


class Inputs:
    """Every input, read once; a missing or unreadable one is noted, never fatal (the tally is best-effort)."""

    def __init__(self, root: Path, obl_dir: Path | None = None):
        self.root = root
        self.notes: list[str] = []
        self.missing: list[str] = []
        self.obl_dir = obl_dir

    def path(self, rel: str) -> Path:
        return self.root / rel

    def json(self, rel: str, default=None, required: bool = True):
        p = self.path(rel)
        for attempt in range(3):          # a refresh may be rewriting it: try again before giving up
            try:
                return json.loads(p.read_text())
            except FileNotFoundError:
                if required:
                    self.missing.append(rel)
                return default
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                if attempt == 2:
                    self.notes.append(f"{rel}: unreadable ({type(e).__name__}); left out")
                    return default
                time.sleep(0.6 * (attempt + 1))
        return default

    def text(self, rel: str) -> str:
        try:
            return self.path(rel).read_text()
        except (FileNotFoundError, OSError, UnicodeDecodeError):
            self.missing.append(rel)
            return ""


def parse_flat_yaml(text: str) -> dict:
    """The registry's yaml is flat: `key: value` lines with JSON-compatible quoted strings and lists, and `#` notes.
    Used only when PyYAML is not importable."""
    out: dict = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if v in ("", "null", "~"):
            out[k] = None
        elif v in ("true", "True"):
            out[k] = True
        elif v in ("false", "False"):
            out[k] = False
        elif v[0] in "\"[{":
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError:
                out[k] = v.strip("\"'")
        elif re.fullmatch(r"-?\d+(\.\d+)?", v):
            out[k] = float(v) if "." in v else int(v)
        else:
            out[k] = v.strip("'")
    return out


def load_registry(inp: Inputs) -> dict[str, dict]:
    """{id: row} from data/sources/*.yaml."""
    try:
        import yaml  # type: ignore
    except Exception:
        yaml = None
    rows: dict[str, dict] = {}
    d = inp.path("data/sources")
    if not d.is_dir():
        inp.missing.append("data/sources/*.yaml")
        return rows
    for p in sorted(d.glob("*.yaml")):
        try:
            text = p.read_text()
            row = yaml.safe_load(text) if yaml else parse_flat_yaml(text)
        except Exception as e:
            inp.notes.append(f"{p.name}: unreadable ({type(e).__name__})")
            continue
        if isinstance(row, dict):
            rows[str(row.get("id") or p.stem)] = row
    return rows


# ------------------------------------------------------------------ scrubbing

class Scrubber:
    """Emails, phone numbers and the names in data/build/name-blocklist.json never reach the file."""

    def __init__(self, root: Path):
        names: list[str] = []
        try:
            d = json.loads((root / "data" / "build" / "name-blocklist.json").read_text())
            names = [n for n in (d.get("names") if isinstance(d, dict) else d) or [] if isinstance(n, str) and len(n) > 3]
        except Exception:
            pass
        self.rx = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
                             + r")(?![\w])", re.I) if names else None
        self.person_shaped = None
        pipe = root / "pipeline"
        if (pipe / "build" / "redact.py").exists():
            try:
                if str(pipe) not in sys.path:
                    sys.path.insert(0, str(pipe))
                from build import redact  # type: ignore
                data = root / "data"
                self.person_shaped = lambda t: bool(redact.person_shaped(t, data))
            except Exception:
                self.person_shaped = None

    def __call__(self, s) -> str:
        s = "" if s is None else str(s)
        s = EMAIL_RX.sub("[email removed]", s)
        s = PHONE_RX.sub("[phone removed]", s)
        s = CONTACT_NAME_RX.sub("Contact: [name removed]", s)
        if self.rx:
            s = self.rx.sub("[name removed]", s)
        return s

    def water_text(self, s) -> str:
        """A report's water-name text: also drops a value that is only a person's name (a reporter's, as some
        agencies fill that field)."""
        s = self(s)
        if self.person_shaped and s and "[" not in s and self.person_shaped(s):
            return "[name removed]"
        return s


def clip(s, n: int = 110) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip().replace("\u2014", "-").replace("\u2013", "-")
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return (cut or s[:n]).rstrip(".,;:- ") + "..."


SENT_END = re.compile(r"(?<=[a-z0-9)])\.\s+(?=[A-Z])")


def first_sentence(s, n: int = 110) -> str:
    """The first sentence, clipped; a lone capital before a period (E. coli) is not a sentence end."""
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    m = SENT_END.search(s)
    if m and m.start() >= 8:
        s = s[:m.start()]
    return clip(s, n).rstrip(".;:, ")


def n(x) -> str:
    return f"{int(x):,}"


def pct(a, b) -> str:
    return f"{100.0 * a / b:.1f}%" if b else "-"


def cadence_text(h) -> str:
    if h is None:
        return "-"
    h = float(h)
    if h < 1:
        return f"every {round(h * 60)} min"
    if h == 1:
        return "hourly"
    if h < 24:
        return f"every {h:g} h"
    d = h / 24
    if d == 1:
        return "daily"
    if d < 7:
        return f"every {d:g} days"
    if d == 7:
        return "weekly"
    if 27 <= d <= 32:
        return "monthly"
    if d >= 330:
        return "yearly"
    return f"every {d:g} days"


def fetch_text(ts) -> str:
    return re.sub(r"^(\d{4}-\d\d-\d\d)T(\d\d:\d\d).*$", r"\1 \2Z", ts) if isinstance(ts, str) and ts else "-"


# ------------------------------------------------------------------ doc links (owner items, decisions)

def url_key(u: str) -> str | None:
    m = re.match(r"https?://([^/\s?#]+)(/[^\s?#]*)?", str(u or "").strip().lower())
    if not m:
        return None
    host = m.group(1).removeprefix("www.")
    path = (m.group(2) or "").rstrip("/")
    return f"{host}{path}" if path else None          # a bare host is too loose to match on


WHO_STOP = set("""water sewer sewage authority commission department district county city town public works wastewater
treatment combined overflow overflows notice notices alerts alert system everbridge nixle list lists email form
massachusetts connecticut vermont hampshire maine york jersey pennsylvania maryland virginia rhode island regional
utility greater management health river notification notifications discharge discharges emergency service services
constant contact sign this that with from about state who what address where research status""".split())


class DocIndex:
    """URLs per line of docs/owner-signups.md and docs/subscriptions.md (line numbers kept), and the lines of
    docs/decisions.md the decision patterns find."""

    def __init__(self, inp: Inputs):
        self.signup: dict[str, tuple[str, int, str | None]] = {}
        self.decisions_lines = inp.text("docs/decisions.md").splitlines()
        self.who_rows: list[tuple[int, str]] = []
        for i, line in enumerate(inp.text("docs/owner-signups.md").splitlines(), 1):
            if line.lstrip().startswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                who = cells[1] if len(cells) > 1 and re.fullmatch(r"\d+", cells[0] or "x") else (cells[0] if cells else "")
                wt = [t for t in re.findall(r"[a-z]{4,}", who.lower()) if t not in WHO_STOP]
                if wt:
                    self.who_rows.append((i, wt[0]))
        for doc in ("docs/owner-signups.md", "docs/subscriptions.md"):          # owner-signups wins a clash
            for i, line in enumerate(inp.text(doc).splitlines(), 1):
                status = None
                if line.lstrip().startswith("|"):
                    cells = [c.strip() for c in line.strip().strip("|").split("|")]
                    if cells and re.fullmatch(r"[a-z_]+(?:[ :;,()a-z_-]{0,30})?", cells[-1] or "x"):
                        status = cells[-1]
                for u in URL_RX.findall(line):
                    k = url_key(u.rstrip(".,;:"))
                    if k and (k not in self.signup or (doc.endswith("owner-signups.md") and not self.signup[k][0].endswith("owner-signups.md"))):
                        self.signup[k] = (doc, i, status)

    def who_link(self, *names) -> tuple[str, int] | None:
        """The owner-signups.md table row whose "who" cell opens with the entity the source's name or operator
        names (the first distinctive word of the cell appears in the source's own words; a tie is no link)."""
        toks = {t for x in names for t in re.findall(r"[a-z]{4,}", str(x or "").lower())} - WHO_STOP
        hits = [ln for ln, first in self.who_rows if first in toks]
        return ("docs/owner-signups.md", hits[0]) if len(hits) == 1 else None

    def signup_link(self, *urls) -> tuple[str, int, str | None] | None:
        for u in urls:
            k = url_key(u)
            if k and k in self.signup:
                return self.signup[k]
        return None

    def decision_line(self, rx: re.Pattern) -> int | None:
        for i, line in enumerate(self.decisions_lines, 1):
            if rx.search(line):
                return i
        return None


def doc_link(doc: str, line: int) -> str:
    base = doc.split("/")[-1]
    return f"[{base} L{line}]({base}#L{line})"


# ------------------------------------------------------------------ what a not-collected source needs

def classify(row: dict, docs: DocIndex) -> tuple[str, str | None]:
    """(unlock label, link markdown or None) for one not-collected row."""
    status, role = row.get("status"), row.get("role")
    text = " ".join(str(row.get(k) or "") for k in ("reason_full", "name"))
    ident = str(row.get("id") or "")           # a decision names a source by its id, not by what a news story calls it
    access = set(row.get("access") or [])
    machine = bool(access & {"api", "arcgis", "csv", "json", "rss"})
    for rx_row, rx_line, label, _gate in DECISION_LINKS:
        if rx_row.search(ident):
            ln = docs.decision_line(rx_line)
            if ln:
                return label, doc_link("docs/decisions.md", ln)
    sign = docs.signup_link(row.get("url"), row.get("homepage"))
    if sign and status != "rejected" and role not in RESEARCH_ONLY_ROLES \
            and (sign[0].endswith("owner-signups.md") or not machine):
        doc, ln, st = sign
        return "owner sign-up", doc_link(doc, ln) + (f" ({clip(st, 24)})" if st else "")
    if row.get("origin") == "register":      # the register's own reason (login, bot wall, none found ...) names the unlock
        hint = str(row.get("unlock") or "").lower()
        for u in UNLOCKS:
            if hint == u:
                return u, None
    if status == "rejected":                  # looked at and set aside: only a decision, above, can reopen it
        return "none: rejected", None
    if not str(row.get("url") or "").strip():
        return "no URL", None
    if role in RESEARCH_ONLY_ROLES:
        return "reference only", None
    if RX_LICENCE.search(text):
        return "licence decision", None
    if RX_RECORDS.search(text):
        return "records request", None
    if RX_BOT.search(text):
        return "bot wall", None
    if RX_IMAGE.search(text) or access == {"map_only"}:
        return "image-only", None
    if not machine:           # a feed we can poll needs engineering, whatever else is said about it
        if (access & {"email", "app", "social"} or RX_SIGNUP.search(text)) and role in ("events", "advisories", "news", "social"):
            link = docs.who_link(row.get("operator"))
            return "owner sign-up", (doc_link(*link) if link else None)
        if access & {"phone"} or RX_CONTACT.search(text):
            link = docs.who_link(row.get("operator"))
            return "owner contact", (doc_link(*link) if link else None)
    return "engineering work", None


def tier_of(row: dict, unlock: str) -> int:
    """1 dated public channels, 2 feeds with history, 3 context sources."""
    role, status = row.get("role"), row.get("status")
    access = set(row.get("access") or [])
    if row.get("origin") == "register" or role in ("events", "advisories"):
        return 1
    if role in ("news", "social") and status == "candidate":
        return 1
    if role in ("monitoring", "outfalls", "permits") and (row.get("history") or row.get("machine_readable")
                                                          or access & {"api", "arcgis", "csv", "rss"}):
        return 2
    return 3


def is_opportunity(row: dict, unlock: str) -> bool:
    return unlock not in OPPORTUNITY_EXCLUDED_UNLOCKS        # nothing to do for reference-only and rejected rows


# ------------------------------------------------------------------ state assignment

def states_in(text) -> list[str]:
    found = []
    for t in re.findall(r"\b[A-Z]{2}\b", str(text or "")):
        if t in STATE_NAMES and t not in found:
            found.append(t)
    return found


def checklist_states(r: dict, reg: dict) -> list[str]:
    found = states_in(r.get("state")) or states_in(r.get("jurisdiction"))
    if found:
        return found
    slugs = [s.rsplit("-", 1)[-1].upper() for s in r.get("water_slugs") or [] if isinstance(s, str)]
    found = [s for s in dict.fromkeys(slugs) if s in STATE_NAMES]
    if found:
        return found
    y = reg.get(r.get("id") or "") or {}
    found = [s for s in (y.get("states") or []) if s in STATE_NAMES]
    if found:
        return found
    m = re.match(r"([a-z]{2})-", str(r.get("id") or ""))
    return [m.group(1).upper()] if m and m.group(1).upper() in STATE_NAMES else []


UNMONITORED_TEXT = {"login": "behind a login", "bot_wall": "behind a bot check", "image_only": "an image only",
                    "none_found": "no page found", "email_only": "an email list only", "app_only": "shown only in an app",
                    "feed_ingested": "read as a feed", "other": "not read"}
# what the register's unmonitored_reason says it would take (labels of UNLOCKS); "other" is read from the note
UNMONITORED_UNLOCK = {"login": "owner sign-up", "bot_wall": "bot wall", "image_only": "image-only", "none_found": "no URL",
                      "email_only": "owner sign-up", "app_only": "owner sign-up"}


def monitor_health(inp: Inputs) -> dict[str, dict]:
    """{channel id: the monitor's health row} from data/build/notice-pages/health.json (notification_pages.py), if it
    has run."""
    doc = inp.json("data/build/notice-pages/health.json", None, required=False)
    out: dict[str, dict] = {}
    for st in ((doc or {}).get("states") or {}).values() if isinstance(doc, dict) else []:
        for h in (st or {}).get("channels") or []:
            if isinstance(h, dict) and h.get("id"):
                out[h["id"]] = h
    return out


def register_rows(inp: Inputs) -> tuple[list[dict], str | None]:
    """The notice-channel register (data/notice-channels.json: {channels: [...]}; schema in
    pipeline/ingest/notification_pages.py), normalised: [{id, states, operator, channel, url, monitored, reason, unlock,
    last_state, feed}]. Other shapes (a bare list, rows keyed by state, a monitor dict) are read too."""
    src = None
    data = None
    for rel in ("data/notice-channels.json", "data/notice-channels.draft.json"):
        if inp.path(rel).exists():
            data = inp.json(rel, None, required=False)
            src = rel
            break
    if data is None:
        return [], None
    raw: list[tuple[str | None, dict]] = []
    if isinstance(data, list):
        raw = [(None, r) for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        for key in ("channels", "rows", "register", "items"):
            if isinstance(data.get(key), list):
                raw = [(None, r) for r in data[key] if isinstance(r, dict)]
                break
        else:
            for k, v in data.items():
                if isinstance(v, list) and k.upper() in STATE_NAMES:
                    raw += [(k.upper(), r) for r in v if isinstance(r, dict)]
                elif isinstance(v, dict) and k.upper() in STATE_NAMES:
                    for kk in ("channels", "rows"):
                        if isinstance(v.get(kk), list):
                            raw += [(k.upper(), r) for r in v[kk] if isinstance(r, dict)]
    health = monitor_health(inp)
    out = []

    def pick(r, *keys):
        for k in keys:
            v = r.get(k)
            if v not in (None, "", [], {}):
                return v
        return None

    for forced, r in raw:
        sts = []
        v = pick(r, "states", "state", "jurisdictions", "jurisdiction")
        for tok in ([v] if isinstance(v, str) else list(v or [])):
            sts += states_in(str(tok).upper() if len(str(tok)) <= 2 else tok)
        if forced:
            sts = [forced]
        mon = r.get("monitored")
        mdict = r.get("monitor") if isinstance(r.get("monitor"), dict) else {}
        if mon is None and mdict:
            mon = mdict.get("enabled", mdict.get("monitored"))
        if isinstance(mon, str):
            mon = mon.strip().lower() in ("true", "yes", "y", "1", "monitored")
        rid = pick(r, "id", "key")
        why = r.get("unmonitored_reason")
        urls = r.get("urls") if isinstance(r.get("urls"), list) else []
        url = pick(r, "url", "link") or (urls[0] if urls else None) or r.get("signup_url")
        last = pick(r, "last_state", "monitor_state", "last_status", "monitor_status", "last_result") \
            or pick(mdict, "last_state", "state", "status", "last_status", "result")
        if isinstance(last, dict):
            last = pick(last, "state", "status", "result", "summary")
        h = health.get(rid) or {}
        if last is None and h.get("wording"):
            last = h["wording"] + (f" (fetched {str(h['last_fetch'])[:10]})" if h.get("last_fetch") else "")
        reason = pick(r, "reason", "why", "not_monitored_reason")
        if reason is None and why:
            # the research note explains "no page found" and "other"; the other reasons say it themselves
            reason = first_sentence(r.get("note"), 100) if why in ("none_found", "other") and r.get("note") else UNMONITORED_TEXT.get(why)
        if reason is None:
            reason = first_sentence(pick(r, "note", "notes"), 100) or None
        kind = pick(r, "channel_kind", "kind", "type")
        label = pick(r, "channel", "label", "title", "authority") or (str(kind).replace("_", " ") if kind else None)
        host = re.sub(r"^https?://(www\.)?", "", str(url or "")).split("/")[0] if url else ""
        out.append({"states": list(dict.fromkeys(sts)), "operator": pick(r, "operator", "name", "agency", "who", "owner"),
                    "channel": label, "host": host, "url": url, "monitored": bool(mon), "reason": reason, "id": rid,
                    "unlock": pick(r, "unlock", "needs") or UNMONITORED_UNLOCK.get(why),
                    "feed": r.get("feed_source_id") if why == "feed_ingested" else None, "ingested": why == "feed_ingested",
                    "publishes": pick(r, "publishes"), "role": pick(r, "role"),
                    "last_state": last if last is None else str(last)})
    return out, src


# ------------------------------------------------------------------ the water-records block

ABBREV = {"r": "river", "riv": "river", "bk": "brook", "brk": "brook", "hbr": "harbor", "harbour": "harbor",
          "pd": "pond", "lk": "lake", "chan": "channel", "ck": "creek", "cr": "creek", "st": "saint", "mt": "mount"}
EXTRA_WATER_FILES = ("waters-extra.json", "waters-dc.json", "waters-nhd.json")
ORIGINS = [("obl", "openboatlaunch extract"), ("nhd", "NHD build"), ("osm", "OpenStreetMap fallback"),
           ("hand", "hand record"), ("editorial", "editorial")]
APPROX_KEYS = ("approximate", "geometry_approximate", "geometry_approx", "approx_geometry", "approx")
APPROX_NOTE = re.compile(r"geometry is approximate|approximate geometry|approximate position|approximate (line|course)", re.I)


def norm_name(s) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower().replace("'", ""))
    return " ".join(ABBREV.get(t, t) for t in s.split())


def norm_town(t) -> str:
    t = re.sub(r"\s+", " ", str(t or "").strip().lower())
    t = re.sub(r"^(town|city|village|borough) of ", "", t)
    return re.sub(r"\s+(town|city)$", "", t)


def load_waters(inp: Inputs) -> dict[str, dict]:
    """Every water record as the build loads them (build/status.load_waters): waters-ne.json, the other
    data/waters-*.json, then waters-extra, waters-dc, waters-nhd; the first record of a slug stays. Each copy gets
    `_origin` and `_file`."""
    d = inp.path("data")
    paths = [d / "waters-ne.json"] + sorted(p for p in d.glob("waters-*.json")
                                            if p.name != "waters-ne.json" and p.name not in EXTRA_WATER_FILES)
    paths += [d / name for name in EXTRA_WATER_FILES]
    waters: dict[str, dict] = {}
    seen_any = False
    for p in paths:
        if not p.exists():
            continue
        doc = inp.json(f"data/{p.name}", None, required=False)
        if not doc:
            continue
        seen_any = True
        rows = doc.get("waters", []) if isinstance(doc, dict) else doc
        for w in rows:
            if not isinstance(w, dict) or not w.get("slug"):
                continue
            if w.get("editorial") or w.get("origin") == "editorial":
                origin = "editorial"
            elif w.get("hand"):
                origin = "hand"
            elif p.name in EXTRA_WATER_FILES:
                origin = "osm" if (str(w.get("source") or "").lower() == "osm" or p.name == "waters-extra.json") else "nhd"
            else:
                origin = "obl"
            waters.setdefault(w["slug"], {**w, "_origin": origin, "_file": p.name})
    if not seen_any:
        inp.missing.append("data/waters-*.json")
    return waters


def geometry_state(w: dict, obl_dir: Path | None, cache: dict) -> str:
    """'yes', 'no' or 'unchecked' (an openboatlaunch record whose geometry file cannot be looked up)."""
    if w.get("geometry"):
        return "yes"
    if w["_origin"] != "obl" and w.get("_file") in EXTRA_WATER_FILES:
        return "no"
    if obl_dir is None or not obl_dir.is_dir():
        return "unchecked"
    p = obl_dir / f"{w['slug']}.json"
    if w["slug"] in cache:
        return cache[w["slug"]]
    try:
        g = "yes" if json.loads(p.read_text()).get("geometry") else "no"
    except FileNotFoundError:
        g = "no"
    except Exception:
        g = "unchecked"
    cache[w["slug"]] = g
    return g


def is_approximate(w: dict) -> bool:
    if any(w.get(k) for k in APPROX_KEYS):
        return True
    return bool(APPROX_NOTE.search(str(w.get("note") or "")))


def live_event(e: dict) -> bool:
    return not (e.get("fixture") or e.get("superseded") or e.get("duplicate_of"))


def water_blocks(inp: Inputs, scrub: Scrubber) -> dict[str, dict]:
    waters = load_waters(inp)
    site = inp.json("out/waters.json", None)
    on_site = {w.get("slug") for w in (site or {}).get("waters", []) if isinstance(w, dict)} if site else None
    obl_dir = inp.obl_dir
    gcache: dict = {}
    slug_alias = {a: s for s, w in waters.items() for a in (w.get("slug_aliases") or []) if isinstance(a, str) and a not in waters}

    blocks = {st: {"records": 0, "on_site": 0, "origins": Counter(), "approx": 0, "no_geom": 0, "geom_unchecked": 0,
                   "outfalls": 0, "outfalls_no_record": 0, "permits": Counter(), "permit_names": {},
                   "plant_outfalls": 0, "plant_no_record": 0,
                   "reports": 0, "unplaced": 0, "unplaced_names": Counter(), "unplaced_raw": {}, "no_water": 0,
                   "dup_names": 0, "dup_records": 0, "dup_resolved": 0, "dup_unresolved": [], "dup_reports": 0,
                   "unplaced_listed": 0, "no_state": 0, "obl_checked": bool(obl_dir and obl_dir.is_dir()),
                   "site_known": on_site is not None} for st in STATES}
    by_state_names: dict[tuple, list[str]] = defaultdict(list)
    for slug, w in waters.items():
        st = str(w.get("state") or "").upper()
        if st not in blocks:
            continue
        b = blocks[st]
        b["records"] += 1
        b["origins"][w["_origin"]] += 1
        if on_site is not None and slug in on_site:
            b["on_site"] += 1
        if is_approximate(w):
            b["approx"] += 1
        g = geometry_state(w, obl_dir, gcache)
        if g == "no":
            b["no_geom"] += 1
        elif g == "unchecked":
            b["geom_unchecked"] += 1
        nm = norm_name(w.get("name") or "")
        if nm:
            by_state_names[(st, nm)].append(slug)

    # duplicate names, one per state and normalised name: resolvable by town when every record lists a town and no
    # two records share one (the build then picks the water whose towns hold the report's town)
    dup_slugs: dict[str, set] = defaultdict(set)
    for (st, nm), slugs in sorted(by_state_names.items()):
        if len(slugs) < 2:
            continue
        b = blocks[st]
        b["dup_names"] += 1
        b["dup_records"] += len(slugs)
        town_sets = [{norm_town(t) for t in waters[s].get("towns") or [] if norm_town(t)} for s in slugs]
        ok = all(town_sets) and all(not (town_sets[i] & town_sets[j]) for i in range(len(slugs)) for j in range(i + 1, len(slugs)))
        if ok:
            b["dup_resolved"] += 1
        else:
            b["dup_unresolved"].append(waters[slugs[0]].get("name") or nm)
        dup_slugs[st].update(slugs)

    # outfalls in the registry with no water record: every registry file (data/outfalls-*.json, national, once per
    # permit and outfall: pipeline/common.py load_outfall_registry); combined sewer outfalls (official, and the
    # provisional ones the reports place) are counted, treatment plant outfalls on their own line, the other
    # provisional places from the reports not at all; a state outside the tally is left out
    for o in registry_outfalls(inp):
        st = str(o.get("state") or "").upper() or (str(o.get("npdes_permit") or "")[:2])
        if st not in blocks:
            continue
        b = blocks[st]
        s = o.get("water_slug")
        s = slug_alias.get(s, s)
        if o.get("outfall_kind") == "other":          # EPA flags it CSO but it is no sewage outfall
            continue
        if o.get("outfall_kind") == "plant":          # treatment plant outfalls: their own line
            b["plant_outfalls"] += 1
            b["plant_no_record"] += int(not s or s not in waters)
            continue
        b["outfalls"] += 1                           # combined sewer outfalls (official and provisional)
        if not s or s not in waters:
            b["outfalls_no_record"] += 1
            pm = str(o.get("npdes_permit") or "?")
            b["permits"][pm] += 1
            b["permit_names"].setdefault(pm, o.get("permittee"))

    # reports: placed, unplaced, no receiving water (out/events.json, data/build/status.json)
    ev_doc = inp.json("out/events.json", None)
    status = inp.json("data/build/status.json", None)
    unplaced_listed = set((status or {}).get("unplaced_events") or [])
    nr_listed = set((status or {}).get("no_receiving_water_events") or [])
    for e in (ev_doc or {}).get("events", []) if isinstance(ev_doc, dict) else []:
        st = str(e.get("state") or "").upper()
        if not live_event(e):
            continue
        if st not in blocks:
            continue
        b = blocks[st]
        b["reports"] += 1
        eid = e.get("event_id")
        slugs = e.get("water_slugs") or []
        if e.get("no_receiving_water") or eid in nr_listed:
            b["no_water"] += 1
        elif eid in unplaced_listed or (status is None and not slugs):
            b["unplaced"] += 1
            raw = scrub.water_text(e.get("waterbody_text")).strip()
            key = norm_name(raw) or "(no water named)"
            b["unplaced_names"][key] += 1
            b["unplaced_raw"].setdefault(key, raw or "(no water named)")
        if slugs and st in dup_slugs and any(s in dup_slugs[st] for s in slugs):
            b["dup_reports"] += 1
    blocks["_meta"] = {"waters": len(waters), "events": ev_doc is not None, "status": status is not None,
                       "unplaced_listed": len(unplaced_listed),
                       "on_site_total": len(on_site) if on_site is not None else None}
    return blocks


# ------------------------------------------------------------------ building the tally

def feed_states_map(feeds: list[dict], coverage: dict, reg: dict) -> dict[str, list[str]]:
    """source_id -> states: the coverage file's per-state feed lists, the rain caution's sources, the states of the
    feed's registry rows, then the id's own prefix."""
    out: dict[str, list[str]] = defaultdict(list)
    cstates = (coverage or {}).get("states") or {}
    for st, c in cstates.items():
        for f in c.get("feeds") or []:
            out[f["source_id"]].append(st)
        rc = c.get("rain_caution") or {}
        if rc.get("covered"):
            for sid in rc.get("sources") or []:
                if st not in out[sid]:
                    out[sid].append(st)
    for f in feeds:
        sid = f["source_id"]
        if out.get(sid):
            continue
        sts = []
        for rid in [sid] + list(f.get("registry_ids") or []):
            sts += [s for s in ((reg.get(rid) or {}).get("states") or []) if s in STATE_NAMES]
        if not sts:
            m = re.match(r"(?:nyc|[a-z]{2})(?=-)", sid)
            if m:
                code = "NY" if m.group(0) == "nyc" else m.group(0).upper()
                if code in STATE_NAMES:
                    sts = [code]
        out[sid] = list(dict.fromkeys(sts))
    return out


def collected_ids(feeds: list[dict], reg: dict) -> set[str]:
    ids: set[str] = set()
    for f in feeds:
        ids.add(f["source_id"])
        ids.update(f.get("registry_ids") or [])
        ids.update((reg.get(f["source_id"]) or {}).get("registry_ids") or [])
    return ids


def feed_line_fields(f: dict, cov_feed: dict | None, reg: dict) -> dict:
    rids = [r for r in [f["source_id"]] + list(f.get("registry_ids") or []) if r in reg]
    rows = [reg[r] for r in rids]
    name = (rows[0].get("name") if rows else None) or (cov_feed or {}).get("name") or f"{f['source_id']} (no registry row)"
    types: list[str] = []
    for r in rows:
        for t in r.get("event_types") or []:
            if t not in types:
                types.append(t)
    role = next((r.get("role") for r in rows if r.get("role")), None)
    gives = f"{role}: {', '.join(types[:5])}" if role and types else (role or ("sewage reports" if cov_feed else "-"))
    cad = (cov_feed or {}).get("cadence_hours") or f.get("expected_cadence_hours")
    rec = (cov_feed or {}).get("records_12m")
    return {"name": name, "gives": gives, "precision": (cov_feed or {}).get("precision_text") or "-",
            "cadence": cadence_text(cad), "records": n(rec) if rec is not None else f"n/a ({n(f.get('count') or 0)} kept)",
            "last_ok": fetch_text(f.get("last_ok_at")),
            "stale": ("failing" if f.get("ok") is False else ("stale" if f.get("stale") else "no"))}


def build_not_collected(inp: Inputs, reg: dict, feeds: list[dict], register: list[dict], docs: DocIndex,
                        scrub: Scrubber) -> tuple[dict[str, list[dict]], dict]:
    checklist = inp.json("docs/source-checklist.json", []) or []
    have = collected_ids(feeds, reg)
    per_state: dict[str, list[dict]] = {st: [] for st in STATES}
    stats = {"unassigned": Counter(), "rows_considered": len(checklist), "already_collected": 0, "registry_only": 0}
    in_checklist = set()
    for r in checklist:
        in_checklist.add(r.get("id"))
        in_checklist.add(r.get("original_id"))
        if r.get("status") not in NOT_COLLECTED_STATUSES:
            continue
        if r.get("id") in have or r.get("original_id") in have:
            stats["already_collected"] += 1
            continue
        y = reg.get(r.get("id") or "") or {}
        sts = checklist_states(r, reg)
        if not [s for s in sts if s in per_state]:
            stats["unassigned"][r.get("area") or "?"] += 1
            continue
        row = {"id": r.get("id"), "name": scrub(r.get("name")), "status": r["status"], "role": r.get("role"),
               "access": r.get("access") or [], "url": r.get("url"), "homepage": y.get("homepage"),
               "reason": scrub(first_sentence(r.get("status_reason") or r.get("notes") or "")),
               "reason_full": scrub(" ".join(str(r.get(k) or "") for k in ("status_reason", "notes"))),
               "operator": scrub(r.get("operator")),
               "access_detail": scrub(r.get("access_detail")), "history": r.get("history"),
               "machine_readable": r.get("machine_readable"), "origin": "checklist"}
        for st in sts:
            if st in per_state:
                per_state[st].append(row)
    # registry rows with no feed and no checklist row (hand-added)
    for rid, y in reg.items():
        if rid in have or rid in in_checklist or y.get("enabled") is False:
            continue
        sts = [s for s in (y.get("states") or []) if s in per_state] or checklist_states({"id": rid}, reg)
        sts = [s for s in sts if s in per_state]
        if not sts:
            continue
        stats["registry_only"] += 1
        row = {"id": rid, "name": scrub(y.get("name")), "status": "registered", "role": y.get("role"),
               "access": y.get("access") or [], "url": y.get("url"), "homepage": y.get("homepage"),
               "reason": "in the source registry, no ingester yet", "reason_full": "", "operator": scrub(y.get("attribution")),
               "access_detail": scrub(y.get("access_detail")),
               "history": None, "machine_readable": y.get("machine_readable"), "origin": "registry"}
        for st in sts:
            per_state[st].append(row)
    # register rows not monitored
    for r in register:
        if r["monitored"] or r.get("ingested"):        # a feed already reads an ingested channel: it is collected
            continue
        sts = [s for s in r["states"] if s in per_state]
        if not sts:
            stats["unassigned"]["register"] += 1
            continue
        op, ch = scrub(r.get("operator")), scrub(r.get("channel"))
        nm = " / ".join(x for x in [op, ch if ch != op else None] if x) or scrub(r.get("id")) or "channel"
        row = {"id": r.get("id"), "name": nm, "status": "not monitored", "role": r.get("role") or "events", "access": [],
               "url": r.get("url"), "homepage": None, "reason": scrub(first_sentence(r.get("reason") or "no reason given")),
               "reason_full": scrub(r.get("reason")), "operator": scrub(r.get("operator")), "access_detail": "", "history": None, "machine_readable": None, "origin": "register",
               "unlock": r.get("unlock")}
        for st in sts:
            per_state[st].append(row)
    for rx_row, rx_line, label, gate in DECISION_LINKS:          # a decision on a source we do collect: show what it holds back
        ln = docs.decision_line(rx_line)
        if gate and ln and gate["state"] in per_state and not any(
                r.get("link") and f"#L{ln}" in r["link"] for r in per_state[gate["state"]]):
            per_state[gate["state"]].append({
                "id": f"decision-line-{ln}", "name": gate["name"], "status": "watch", "role": gate["role"], "access": [],
                "url": "decision", "homepage": None, "reason": gate["reason"], "reason_full": "", "operator": "",
                "access_detail": "", "history": "2022 onward", "machine_readable": True, "origin": "decision",
                "unlock": label})
    for st, rows in per_state.items():
        for row in rows:
            if row.get("origin") != "decision":
                row["unlock"], row["link"] = classify(row, docs)
            else:
                row["link"] = doc_link("docs/decisions.md", docs.decision_line(next(g[1] for g in DECISION_LINKS if g[3] and g[3]["name"] == row["name"])))
            row["tier"] = tier_of(row, row["unlock"])
            row["opportunity"] = is_opportunity(row, row["unlock"])
        rows.sort(key=lambda r: (r["tier"], STATUS_RANK.get(r["status"], 1), UNLOCK_RANK.get(r["unlock"], 99), r["name"].lower()))
    return per_state, stats


def row_line(r: dict) -> str:
    bits = [f"**{clip(r['name'], 80)}**", f"({r['status']}, {r['role'] or 'n/a'})"]
    line = f"- {' '.join(bits)}: {r['reason'] or 'no reason given'}. Unlock: {r['unlock']}"
    if r.get("link"):
        line += f" - {r['link']}"
    return line


def render(inp: Inputs, now: datetime) -> tuple[str, dict]:
    set_live_states(inp.root)
    scrub = Scrubber(inp.root)
    reg = load_registry(inp)
    sources = inp.json("out/sources.json", {}) or {}
    coverage = inp.json("out/coverage.json", {}) or {}
    feeds = [f for f in sources.get("feeds", []) if isinstance(f, dict) and f.get("source_id") and not f.get("fixture")]
    docs = DocIndex(inp)
    register, register_src = register_rows(inp)
    fstates = feed_states_map(feeds, coverage, reg)
    not_collected, ncstats = build_not_collected(inp, reg, feeds, register, docs, scrub)
    waters = water_blocks(inp, scrub)
    meta = waters.pop("_meta")
    cov_states = (coverage or {}).get("states") or {}
    feeds_by_id = {f["source_id"]: f for f in feeds}
    reg_rows_in = Counter(st for r in register for st in r["states"])         # register rows per state (any monitored value)

    summary: dict[str, dict] = {}
    sections: list[str] = []
    for st in STATES:
        c = cov_states.get(st) or {}
        collected = []
        cov_by_id = {cf["source_id"]: cf for cf in c.get("feeds") or []}
        for f in feeds:
            if st in fstates.get(f["source_id"], []):
                collected.append(feed_line_fields(f, cov_by_id.get(f["source_id"]), reg))
        collected.sort(key=lambda d: d["name"].lower())
        mon = [r for r in register if r["monitored"] and st in r["states"]]
        nc = not_collected[st]
        opps = [r for r in nc if r["opportunity"]]
        wb = waters[st]
        have_reg = bool(register_src) and reg_rows_in[st] > 0
        summary[st] = {"grade": c.get("grade") or "-", "feeds": len(collected), "channels": len(mon) if have_reg else None,
                       "not_collected": len(nc), "opportunities": len(opps), "records": wb["records"],
                       "outfalls_no_record": wb["outfalls_no_record"], "outfalls": wb["outfalls"],
                       "unplaced": wb["unplaced"], "reports": wb["reports"]}

        s = [f"## {STATE_NAMES[st]} ({st}): {c.get('grade') or 'no coverage grade'}\n"]
        s.append(f"{scrub(c.get('sentence')) or 'No coverage sentence in out/coverage.json.'}\n")
        chan = f"{len(mon)} monitored" if have_reg else ("no rows in the register yet" if register_src else "register not available")
        s.append(f"Feeds on {len(collected)} | channels {chan} | not collected {len(nc)} | opportunities {len(opps)} | "
                 f"water records {n(wb['records'])} | outfalls without a record {n(wb['outfalls_no_record'])} | "
                 f"reports unplaced {n(wb['unplaced'])} ({pct(wb['unplaced'], wb['reports'])})\n")

        s.append(f"### Collected now ({len(collected)})\n")
        if collected:
            s.append("| Feed | Gives | Precision | Cadence | Reports, 12 months | Last good fetch | Stale |")
            s.append("|---|---|---|---|---|---|---|")
            for d in collected:
                s.append(f"| {clip(scrub(d['name']), 70).replace('|', '/')} | {clip(d['gives'], 40)} | {d['precision']} | "
                         f"{d['cadence']} | {d['records']} | {d['last_ok']} | {d['stale']} |")
        else:
            s.append("No feed runs for this state.")
        s.append("")

        s.append(f"### Monitored channels ({len(mon) if have_reg else 'n/a'})\n")
        if not register_src:
            s.append("The notice-channel register (data/notice-channels.json, or the draft) is not present yet; "
                     "this section fills in when it is.")
        elif not have_reg:
            s.append("The register has no rows for this state yet; this section fills in when it does.")
        elif mon:
            for r in sorted(mon, key=lambda r: (str(r["operator"] or ""), str(r["channel"] or ""), str(r["id"] or ""))):
                last = f"; monitor: {clip(scrub(r['last_state']), 70)}" if r.get("last_state") else ""
                pub = f"; publishes {r['publishes']}" if r.get("publishes") else ""
                host = f" [{clip(r['host'], 40)}]" if r.get("host") else ""
                op, ch = clip(scrub(r["operator"]) or "operator not named", 60), clip(scrub(r["channel"]) or scrub(r["id"]) or "channel", 60)
                s.append(f"- {op} - {ch}{host}{pub}{last}")
        else:
            s.append("No channel for this state is monitored.")
        ingested = [r for r in register if r.get("ingested") and st in r["states"]]
        if ingested:
            s.append("")
            s.append("Read as feeds (register rows the monitor does not fetch, so not counted above): "
                     + ", ".join(clip(scrub(r["operator"]) or scrub(r["id"]), 40) + (f" ({r['feed']})" if r.get("feed") else "")
                                 for r in ingested) + ".")
        s.append("")

        s.append(f"### Not collected ({len(nc)})\n")
        if nc:
            counts = Counter(r["unlock"] for r in nc)
            s.append("By unlock: " + ", ".join(f"{u} {counts[u]}" for u in UNLOCKS if counts[u]) + ".\n")
            for r in nc:
                s.append(row_line(r))
        else:
            s.append("Nothing recorded as not collected.")
        s.append("")

        s.append(f"### Opportunities ({len(opps)})\n")
        if opps:
            tcount = Counter(r["tier"] for r in opps)
            s.append("Ranked: " + ", ".join(f"{TIERS[t]} {tcount[t]}" for t in (1, 2, 3)) + ". Top ten below; the rest are in Not collected.\n")
            for i, r in enumerate(opps[:10], 1):
                s.append(f"{i}. {clip(r['name'], 70)} - {TIERS[r['tier']]}; {r['status']}; {r['unlock']}"
                         + (f" - {r['link']}" if r.get("link") else ""))
        else:
            s.append("None ranked.")
        s.append("")

        s.append("### Water records\n")
        s.extend(water_lines(wb, meta))
        s.append("")
        sections.append("\n".join(s))

    # global opportunity groups
    groups: Counter = Counter()
    for st in STATES:
        for r in not_collected[st]:
            if r["opportunity"]:
                groups[(r["tier"], r["unlock"])] += 1
    top = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))

    head = ["# Source tally\n",
            f"Generated by `scripts/gen_source_tally.py` ({now:%Y-%m-%d %H:%M}Z) at the end of every refresh; do not edit by hand. "
            f"Built from out/coverage.json ({coverage.get('built', 'missing')}), out/sources.json ({sources.get('built', 'missing')}), "
            f"docs/source-checklist.json ({ncstats['rows_considered']} rows), data/sources/*.yaml ({len(reg)} rows) and the water files.\n",
            "What each state gives us and what it does not, so the opportunities stay in view. It is a map of sources, "
            "never a safety verdict: a state with few feeds is a state we read little of, not a clean one. States run New England "
            "then the mid-Atlantic. A source spanning several states is listed in each. `Unlock` says what it would take: an owner "
            "sign-up, an owner contact, a licence decision, a records request, a bot wall to get round, an image-only posting, no URL "
            "found, or engineering work; owner items link to the line in docs/owner-signups.md or docs/decisions.md.\n"]
    head.append("## Summary\n")
    head.append("| State | Grade | Feeds on | Channels monitored | Not collected | Opportunities | Water records | Outfalls without a record | Reports unplaced |")
    head.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    tot = Counter()
    for st in STATES:
        d = summary[st]
        head.append(f"| {st} | {d['grade']} | {d['feeds']} | {d['channels'] if d['channels'] is not None else '-'} | "
                    f"{d['not_collected']} | {d['opportunities']} | {n(d['records'])} | {n(d['outfalls_no_record'])} of {n(d['outfalls'])} | "
                    f"{n(d['unplaced'])} ({pct(d['unplaced'], d['reports'])}) |")
        for k in ("feeds", "not_collected", "opportunities", "records", "outfalls_no_record", "outfalls", "unplaced", "reports"):
            tot[k] += d[k]
        tot["channels"] += d["channels"] or 0
    head.append(f"| **All** | | **{tot['feeds']}** | **{tot['channels'] if register_src else '-'}** | **{tot['not_collected']}** | "
                f"**{tot['opportunities']}** | **{n(tot['records'])}** | **{n(tot['outfalls_no_record'])} of {n(tot['outfalls'])}** | "
                f"**{n(tot['unplaced'])} ({pct(tot['unplaced'], tot['reports'])})** |")
    head.append("")
    head.append("Totals add the state rows, so a feed or source that serves several states counts once in each "
                f"({len({f['source_id'] for f in feeds if fstates.get(f['source_id'])})} distinct feeds run). "
                f"Water records: {n(meta['waters'])} loaded in all"
                + (f", {n(meta['on_site_total'])} on the site (out/waters.json)" if meta.get("on_site_total") is not None else "") + ".\n")
    head.append("### Opportunity groups, all states\n")
    if top:
        head.append("| Group | Unlock | Rows |")
        head.append("|---|---|---:|")
        for (t, u), k in top[:12]:
            head.append(f"| {TIERS[t]} | {u} | {k} |")
        head.append("")
    head.append("### Inputs\n")
    notes = []
    if not register_src:
        notes.append("Notice-channel register: neither data/notice-channels.json nor data/notice-channels.draft.json exists, "
                     "so Monitored channels is empty and register rows are not in Not collected.")
    else:
        notes.append(f"Notice-channel register: {register_src} ({len(register)} rows, {sum(1 for r in register if r['monitored'])} monitored).")
    if inp.missing:
        notes.append("Missing inputs (their sections are thin): " + ", ".join(sorted(set(inp.missing))) + ".")
    notes += inp.notes
    if ncstats["already_collected"]:
        notes.append(f"{ncstats['already_collected']} checklist rows marked candidate or watch are collected now (a feed carries them) and are not repeated under Not collected.")
    if ncstats["registry_only"]:
        notes.append(f"{ncstats['registry_only']} registry rows have no feed and no checklist row; they are listed with status registered.")
    if ncstats["unassigned"]:
        notes.append("Checklist rows tied to no state (federal, international, science), left out of the sections: "
                     + ", ".join(f"{a} {k}" for a, k in sorted(ncstats["unassigned"].items())) + ".")
    unassigned_feeds = [f["source_id"] for f in feeds if not fstates.get(f["source_id"])]
    if unassigned_feeds:
        notes.append("Feeds tied to no state: " + ", ".join(sorted(unassigned_feeds)) + ".")
    if not waters[STATES[0]]["obl_checked"]:
        notes.append("openboatlaunch's water files were not found, so geometry for its records is not checked (see --obl-dir).")
    notes.append("Reports unplaced and no receiving water count each state's live reports in out/events.json "
                 "(not superseded, not a duplicate) against data/build/status.json's lists"
                 + (f"; that file lists {n(meta['unplaced_listed'])} unplaced including superseded and duplicate rows" if meta.get("status") else "; that file is missing") + ".")
    head += [f"- {x}" for x in notes] + [""]
    text = "\n".join(head) + "\n" + "\n".join(sections)
    text = scrub(text)         # last guard: no email, phone or blocklisted name leaves this file
    return text.rstrip() + "\n", {"summary": summary, "totals": dict(tot), "groups": top, "not_collected": not_collected}


def water_lines(b: dict, meta: dict) -> list[str]:
    o = b["origins"]
    out = []
    org = ", ".join(f"{label} {o[k]}" for k, label in ORIGINS)
    site = f" ({b['on_site']} on the site)" if b["site_known"] else ""
    out.append(f"- Records: {n(b['records'])}{site}. By origin: {org}.")
    geo = f"{b['approx']} flagged approximate"
    geo += f", {b['no_geom']} with no geometry"
    if b["geom_unchecked"]:
        geo += f", {b['geom_unchecked']} not checked (openboatlaunch geometry unavailable)"
    out.append(f"- Geometry: {geo}. Approximate means the record's own flag or note says so; no other record is guessed to be.")
    if b["outfalls"]:
        top = ", ".join(f"{pm} ({clip(b['permit_names'].get(pm) or 'unnamed', 30)}) {k}" for pm, k in b["permits"].most_common(5))
        out.append(f"- Outfalls in the registry with no water record: {n(b['outfalls_no_record'])} of {n(b['outfalls'])} "
                   f"({pct(b['outfalls_no_record'], b['outfalls'])})" + (f". Most: {top}." if top else "."))
    else:
        out.append("- Outfalls in the registry: none listed for this state.")
    if b["plant_outfalls"]:
        out.append(f"- Treatment plant outfalls without a water record: {n(b['plant_no_record'])} of "
                   f"{n(b['plant_outfalls'])} ({pct(b['plant_no_record'], b['plant_outfalls'])}).")
    if b["reports"]:
        names = ", ".join(f"{clip(b['unplaced_raw'][k], 36)} ({v})" for k, v in b["unplaced_names"].most_common(5))
        out.append(f"- Reports unplaced: {n(b['unplaced'])} of {n(b['reports'])} ({pct(b['unplaced'], b['reports'])})"
                   + (f". Largest names: {names}." if names else "."))
        out.append(f"- Reports classed no receiving water: {n(b['no_water'])} ({pct(b['no_water'], b['reports'])}).")
    else:
        out.append("- Reports: none in out/events.json for this state" + ("" if meta.get("events") else " (file missing)") + ".")
    if b["dup_names"]:
        un = ", ".join(clip(x, 28) for x in b["dup_unresolved"][:3])
        out.append(f"- Duplicate-name waters resolved by town: {b['dup_names']} name{'s' if b['dup_names'] != 1 else ''} on {b['dup_records']} records; "
                   f"{b['dup_resolved']} resolvable by town (every record lists a town, none shared)"
                   + (f"; {len(b['dup_unresolved'])} not ({un})" if b["dup_unresolved"] else "")
                   + f"; {n(b['dup_reports'])} reports placed on them.")
    else:
        out.append("- Duplicate-name waters: none (no two records share a name in this state).")
    return out


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(ROOT), help="project root (default: this project)")
    ap.add_argument("--out", help="output file (default: <root>/docs/source-tally.md)")
    ap.add_argument("--now", help="timestamp to print (default: the current time, UTC)")
    ap.add_argument("--obl-dir", help="openboatlaunch out/water directory (default: $OBL_WATER_DIR or <root>/../openboatlaunch/out/water)")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    obl = Path(a.obl_dir) if a.obl_dir else Path(os.environ.get("OBL_WATER_DIR") or root.parent / "openboatlaunch" / "out" / "water")
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(UTC)
    inp = Inputs(root, obl)
    text, info = render(inp, now)
    out = Path(a.out) if a.out else root / "docs" / "source-tally.md"
    atomic_write(out, text)
    t = info["totals"]
    print(f"source tally: {out} ({len(text.splitlines())} lines; feeds {t.get('feeds', 0)}, not collected {t.get('not_collected', 0)}, "
          f"opportunities {t.get('opportunities', 0)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
