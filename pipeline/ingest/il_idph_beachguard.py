"""Illinois Department of Public Health, Illinois BeachGuard System -> data/build/events/il-idph-beachguard.json.

Source (registry il-idph-beachguard; research/il/report.md section 2.5)
  - The RSS feed of current beach advisories and closures, https://idph.illinois.gov/envhealth/ilbeaches/public/
    RssFeed.aspx: one item per beach with an advisory in effect, titled "<type> - <water> - <beach>" ("Closure - Deep
    Lake - Glacier Park", "Contamination Advisory - ...", "Beach Closed by Operator - ...") and a link to the beach's
    page (BeachDetail.aspx?BeachId=N). The feed carries no dates.
  - The beach's page (one GET per listed beach, at most DETAIL_MAX a run, again when its RSS title changes or after
    DETAIL_EVERY_H hours): the advisory type, "Start Date" (local time), "Issued By" (the health department or park
    district that entered it), the comment, the beach's central latitude/longitude, county and accessibility (public
    or private). Nothing else on the page is read. County health departments and park districts enter the advisories;
    Illinois licenses 245 public and 222 private beaches, Lake Michigan's included.
  No licence is stated.

Records
  - One record per beach and advisory start: source_record_id "<BeachId>-<start, YYYYMMDDTHHMM>". event_type
    beach_closure for a closure (the operator's closure included: raw.closure_kind, its reason is not given)
    and beach_advisory for a contamination advisory or any other type (the type kept in raw.advisory_type).
    status advisory_active while the feed lists it; started_at the page's start date (America/Chicago, minute; a
    start more than a year old is kept as published: the list holds some advisories years old, raw.age_note);
    published_at and reported_at null (not published).
  - When the feed stops listing a beach, its record becomes advisory_lifted with ended_at the first poll that did not
    list it (time_precision of the end: poll; raw.lift_observed_between). The feed is the authority's list of what is
    in effect, so leaving it is the lift as published; the lift time itself is not published. A failed fetch lifts
    nothing.
  - waterbody_text the water the title names (none for a bare "Lake" or "Pond"); the page's point (coord_source
    source); authority the issuer the page names.
  Privacy: the feed and the page name agencies and beaches; the comment is free text: a name after a contact cue
  ("call <Name>") is cut and the full scrub runs (mi_egle_mienviro.free_text) as the page is read, so the state file
  never holds it, and common.strip_personal runs on the record; the page's contact links and phone lines are not read.

State: data/build/il-idph-beachguard-state.json (every advisory seen and the pages read): the archive, do not delete.
Run from pipeline/: python -m ingest.il_idph_beachguard [--rss saved.xml --detail-dir DIR --out events.json]
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, write_events, write_json

SOURCE_ID = "il-idph-beachguard"
BASE = "https://idph.illinois.gov/envhealth/ilbeaches/public/"
RSS_URL = BASE + "RssFeed.aspx"
DETAIL_URL = BASE + "BeachDetail.aspx?BeachId={id}"
STATE_PATH = BUILD_DIR / "il-idph-beachguard-state.json"
TZ = ZoneInfo("America/Chicago")
DETAIL_MAX = 40
DETAIL_EVERY_H = 20
DETAIL_BUDGET_S = 120
CREDIT = "Illinois Department of Public Health, Illinois BeachGuard System"
GENERIC_WATER = re.compile(r"^(lake|pond|beach|river|reservoir|quarry)$", re.I)


def parse_rss(xml: bytes | str) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for it in root.iter("item"):
        title = " ".join((it.findtext("title") or "").split())
        link = (it.findtext("link") or "").strip()
        m = re.search(r"BeachId=(\d+)", link)
        if not m:
            continue
        parts = [p.strip() for p in title.split(" - ")]
        out.append({"beach_id": m.group(1), "title": title, "type": parts[0] if parts else None,
                    "water": parts[1] if len(parts) > 2 else None,
                    "beach": " - ".join(parts[2:]) if len(parts) > 2 else (parts[1] if len(parts) > 1 else None)})
    return out


def _span(page: str, sid: str) -> str | None:
    m = re.search(rf'id="{sid}"[^>]*>(.*?)</span>', page, re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split()) if m else None


def _cell(page: str, label: str) -> str | None:
    m = re.search(rf">\s*{re.escape(label)}\s*</td>\s*<td[^>]*>(.*?)</td>", page, re.S)
    if not m:
        return None
    v = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).replace("\xa0", " ").split())
    return v or None


CALL_NAME = re.compile(r"\b((?i:call|contact|e-?mail|ask\s+for|reach|speak\s+(?:to|with)))(\s+)((?:Mr\.?\s+|Mrs\.?\s+|Ms\.?\s+|Dr\.?\s+)?"
                       r"[A-Z][a-z'-]+(?:\s+[A-Z][a-z'-]+){0,2})")


def scrub_comment(v: str | None) -> str | None:
    """The comment as the record keeps it: a name after a contact cue ("call <Name>") cut, then the full scrub."""
    if not v:
        return None
    from ingest.mi_egle_mienviro import free_text
    return free_text(CALL_NAME.sub(lambda m: m.group(1) + m.group(2) + "[name removed]", v))


def parse_detail(page: str) -> dict:
    """The safe fields of a beach page (module docstring)."""
    issued = re.search(r"Issued By:\s*([^<]+)", page)
    latlon = re.match(r"\s*(-?\d+\.\d+)\s*/\s*(-?\d+\.\d+)", _cell(page, "Central Latitude/Longitude:") or "")
    return {"name": _span(page, "Main_lblWaterbodyAndBeachName"),
            "advisory_type": _span(page, "Main_lblAdvisoryType"),
            "start_text": _span(page, "Main_lblAdvisoryStartDate"),
            "issued_by": " ".join(issued.group(1).split()) if issued else None,
            "comment": scrub_comment(_span(page, "Main_lblAdvisoryComment")),
            "lat": float(latlon.group(1)) if latlon else None, "lon": float(latlon.group(2)) if latlon else None,
            "county": _cell(page, "County:"), "accessibility": _cell(page, "Accessibility:")}


def start_time(text: str | None) -> tuple[str | None, str | None]:
    """'9/01/2026 8:00 AM' -> ('2026-09-01T08:00:00-05:00', 'minute'); a date alone at day precision."""
    t = (text or "").strip()
    for fmt, prec in (("%m/%d/%Y %I:%M %p", "minute"), ("%m/%d/%Y %I:%M:%S %p", "minute"), ("%m/%d/%Y", "day")):
        try:
            dt = datetime.strptime(t, fmt)
        except ValueError:
            continue
        return (dt.replace(tzinfo=TZ).isoformat() if prec == "minute" else dt.date().isoformat()), prec
    return None, None


def apply(state: dict, items: list[dict], details: dict[str, dict], now: str) -> dict:
    """Open, keep and lift advisories for one poll; returns counts."""
    recs, open_ = state.setdefault("records", {}), state.setdefault("open", {})
    counts = {"opened": 0, "kept": 0, "lifted": 0}
    listed = set()
    for it in items:
        bid = it["beach_id"]
        listed.add(bid)
        d = details.get(bid) or {}
        start, prec = start_time(d.get("start_text"))
        key = f"{bid}-{re.sub(r'[^0-9T]', '', start[:16]) if start else 'nostart'}"
        cur = open_.get(bid)
        if cur and cur != key and recs[cur].get("start") is None and start:
            recs[key] = recs.pop(cur)           # the page was read after the first poll: same advisory, now dated
            cur = None
        elif cur and cur != key:
            recs[cur].update(lifted_at=now, lift_between=[recs[cur]["last_listed_at"], now])
            counts["lifted"] += 1
            cur = None
        rec = recs.setdefault(key, {"beach_id": bid, "first_listed_at": now})
        rec.update(item=it, detail=d, start=start, precision=prec, last_listed_at=now)
        rec.pop("lifted_at", None)
        rec.pop("lift_between", None)
        counts["kept" if cur else "opened"] += 1
        open_[bid] = key
    for bid in list(open_):
        if bid not in listed:
            r = recs[open_[bid]]
            r.update(lifted_at=now, lift_between=[r["last_listed_at"], now])
            del open_[bid]
            counts["lifted"] += 1
    return counts


def to_record(key: str, r: dict) -> dict:
    it, d = r["item"], r.get("detail") or {}
    typ = d.get("advisory_type") or it.get("type") or ""
    closure = bool(re.search(r"(?i)clos", typ))
    water = it.get("water")
    lifted = r.get("lifted_at")
    raw = {"title": it["title"], "advisory_type": typ, "beach": it.get("beach"), "start_text": d.get("start_text"),
           "issued_by": d.get("issued_by"), "comment": d.get("comment"),
           "county": d.get("county"), "accessibility": d.get("accessibility"), "first_listed_at": r["first_listed_at"],
           "last_listed_at": r["last_listed_at"],
           "start_basis": ("the beach page's start date" if r.get("start") else
                           "the beach page showed no advisory in effect when read; the feed still listed it" if d else
                           "not read: the beach page was not reached; the record is the feed's listing only")}
    if re.search(r"(?i)by operator", typ):
        raw["closure_kind"] = "closed by the beach's operator (reason not given)"
    if lifted:
        raw.update(lift_observed_between=r["lift_between"], ended_at_precision="poll",
                   lift_basis="the feed of advisories in effect stopped listing the beach")
    if r.get("start") and r.get("precision"):
        st = datetime.fromisoformat(r["start"]) if "T" in r["start"] else datetime.fromisoformat(r["start"] + "T00:00:00+00:00")
        if datetime.now(UTC) - st.astimezone(UTC) > timedelta(days=365):
            raw["age_note"] = "the list still showed this advisory more than a year after its start date"
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="beach_closure" if closure else "beach_advisory",
        status="advisory_lifted" if lifted else "advisory_active",
        outfall_name=None, waterbody_text=None if not water or GENERIC_WATER.match(water) else water,
        lat=d.get("lat"), lon=d.get("lon"), coord_source="source" if d.get("lat") is not None else None,
        started_at=r.get("start"), ended_at=lifted, time_precision=r.get("precision") or "poll",
        authority=(f"{d['issued_by']} (Illinois BeachGuard System)" if d.get("issued_by") else CREDIT),
        advice_text=f"{typ}: {it.get('beach') or ''}".strip(": ") or None,
        source_url=DETAIL_URL.format(id=r["beach_id"]), raw=raw)


def fetch_details(items: list[dict], state: dict, now: str, sess) -> dict[str, dict]:
    pages = state.setdefault("pages", {})
    t0, n = time.monotonic(), 0
    for it in items:
        p = pages.get(it["beach_id"])
        fresh = p and p.get("title") == it["title"] and \
            datetime.fromisoformat(now.replace("Z", "+00:00")) - datetime.fromisoformat(p["read_at"].replace("Z", "+00:00")) \
            < timedelta(hours=DETAIL_EVERY_H)
        if fresh or n >= DETAIL_MAX or time.monotonic() - t0 > DETAIL_BUDGET_S:
            continue
        try:
            r = sess.get(DETAIL_URL.format(id=it["beach_id"]), timeout=45)
            r.raise_for_status()
        except requests.RequestException:
            break
        n += 1
        pages[it["beach_id"]] = {"title": it["title"], "read_at": now, "detail": parse_detail(r.text)}
    return {k: v["detail"] for k, v in pages.items()}


def run(state: dict, rss: bytes | str, details: dict[str, dict], now: str) -> tuple[list[dict], dict]:
    items = parse_rss(rss)
    counts = apply(state, items, details, now)
    state["last_poll"] = {"at": now, "listed": len(items), **counts}
    recs = [to_record(k, r) for k, r in state["records"].items()]
    recs.sort(key=lambda x: (x["started_at"] or "", x["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "rss": RSS_URL, "poll": state["last_poll"], "credit": CREDIT,
            "time_note": "Start dates are the beach pages' (Central time); a lift is the first poll that no longer "
                         "listed the beach."}
    return recs, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rss", help="a saved RSS answer (with --detail-dir and --out; nothing fetched)")
    ap.add_argument("--detail-dir", help="saved beach pages named <BeachId>.html")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    now = now_iso()
    if a.rss:
        if not a.out:
            ap.error("--rss needs --out (only live polls reach the archive)")
        out = Path(a.out)
        st_path = out.with_suffix(".state.json")
        state = read_json(st_path, {}) or {}
        details = {p.stem: parse_detail(p.read_text(errors="replace"))
                   for p in sorted(Path(a.detail_dir).glob("*.html"))} if a.detail_dir else {}
        recs, meta = run(state, Path(a.rss).read_bytes(), details, now)
        write_json(st_path, state)
        write_events(SOURCE_ID, recs, meta=meta, path=out)
        print(f"{SOURCE_ID}: {len(recs)} records (file) -> {out}")
        return 0
    sess = requests.Session()
    sess.headers.update(HEADERS)
    state = read_json(STATE_PATH, {}) or {}
    try:
        r = sess.get(RSS_URL, timeout=45)
        r.raise_for_status()
        items = parse_rss(r.content)
    except (requests.RequestException, ET.ParseError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"RSS: {type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    details = fetch_details(items, state, now, sess)
    recs, meta = run(state, r.content, details, now)
    write_json(STATE_PATH, state)
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} records, {meta['poll']['listed']} listed now -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
