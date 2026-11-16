"""Texas DSHS shellfish closures: the "Status of Shellfish Harvesting Areas" table.

Source
  https://www.dshs.texas.gov/seafood-aquatic-life-group/information-on-consumption-advisories-possession-bans-rescinded-orders-seafood-aquatic-life/shellfish-harvest-map
  (registry: tx-dshs-shellfish-harvest-status). The Seafood and Aquatic Life Group lists, under the heading "Status of
  Shellfish Harvesting Areas <date>" (11.16.2026 on 2026-11-16), a four-column table: Harvest Area ("TX 14"), Public
  Harvest Area Status, Private Oyster Area Status (Open, Closed, n/a) and Reason for Status ("TPWD Action, Rainfall").
  DSHS: it may change an area's status because of "High rainfall and runoff", flooding, hurricanes, major spills,
  harmful algal blooms or the failure or poor operation of wastewater treatment facilities, and may close areas for
  shellfish resource or enforcement concerns; the Texas Parks and Wildlife Department (TPWD) sets oyster seasons. The
  page answers the pipeline's runner (runner probe 43885170112, 2026-11-16) and this project's machines.

Which closures make records (the site's rule)
  - A row Closed (public or private) whose reason names rainfall, runoff, flooding, a spill, wastewater or sewage
    (TAKEN) is a closure for pollution or runoff: one shellfish_closure record, DSHS's reason quoted whole
    (raw.reason) with the reasons taken (raw.reasons_taken). "TPWD Action, Rainfall" makes a record for the rainfall.
  - A row Closed only for "TPWD Action" (a season or resource management) or a harmful algal bloom or red tide
    (LEFT_OUT) is no sign of sewage or runoff: no record, counted in meta.left_out. A reason word the reader does not
    know (a hurricane, say) is unread (health false): the reader never guesses which side it falls on.
  - An Open row is no closure; an open area is never described as anything but open.

Times (America/Chicago: the Texas coast lies in the Central zone; DSHS gives a day only)
  - DSHS gives no closure date. started_at is this site's first read that listed the closure (time_precision poll);
    the heading's date is DSHS's publication of the table (published_at, source_updated_at), never a start.
  - End: a complete healthy read of a table with a new date in which the area is no longer closed for a reason taken
    (listed Open, or closed for a reason left out only, or gone from the table) ends it at that read (advisory_lifted,
    raw.ended_at_precision poll, an upper bound; raw.end_seen_as). An area gone from a table with the same date is an
    incomplete read (held, health false). raw._last_seen_in_source and raw._poll_confirmed: the colour runs to 14
    days after the last read that listed the closure. A closure listed again after an end is a new record.

Place: DSHS's harvest-area layer names its polygons by bay and class, not by the table's "TX" codes, so no area can be
tied to an outline here: each closure is listed with DSHS's code and placed on no water (raw._placement
listed_only). A model never supplies a place.

A bad read changes nothing: a failed request, a page without its closing tag, the title, the heading with its date,
or the table's four headings as expected, or a table with no row writes ok=False and keeps the earlier records. A row
that cannot be read is listed in meta.unread; the readable rows update, no earlier closure ends on that read
(raw._held_unread), health stays false. Privacy: only the heading and the table are read (the contact card is not).

Run from pipeline/:  python -m ingest.tx_dshs_shellfish [--file saved.html]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events
from ingest import nv_state_parks_hab as P

SOURCE_ID = "tx-dshs-shellfish-harvest-status"
URL = ("https://www.dshs.texas.gov/seafood-aquatic-life-group/information-on-consumption-advisories-possession-bans-"
       "rescinded-orders-seafood-aquatic-life/shellfish-harvest-map")
AUTHORITY = "Texas Department of State Health Services (DSHS), Seafood and Aquatic Life Group"
ZONE = ZoneInfo("America/Chicago")

TITLE = re.compile(r"<h1\b[^>]*>(?:\s*<[^>]+>)*\s*Shellfish Harvest Area Status and Maps\s*(?:</[^>]+>\s*)*</h1>", re.I)
HEADING = re.compile(r"<h2\b[^>]*>\s*Status of Shellfish Harvesting Areas\s+(?P<date>[0-9./-]+)\s*</h2>", re.I)
TABLE = re.compile(r"<table\b[^>]*>(?P<body>.*?)</table>", re.S | re.I)
EXPECTED_HEAD = ["Harvest Area", "Public Harvest Area Status", "Private Oyster Area Status", "Reason for Status"]
AREA = re.compile(r"^TX \d{1,2}[A-Z]?$")
STATUS = {"open": "open", "closed": "closed", "n/a": "n/a"}
TAKEN = re.compile(r"^(?:high )?(?:rainfall|rain|runoff|rainfall and runoff|flooding|flood|freshwater inflow|"
                   r"(?:major )?spills?|sewage(?: spill)?|wastewater(?: treatment facility)?(?: failure)?|"
                   r"wwtp(?: failure)?|bacteria|bacteriological)$", re.I)
LEFT_OUT = re.compile(r"^(?:tpwd action|tpwd|harmful algal blooms?|hab|red tide|biotoxins?|enforcement|"
                      r"resource concerns?|season)$", re.I)
START_BASIS = ("this site's first read of DSHS's table that listed the closure: the table gives no closure date, and "
               "its heading's date is the table's publication, not the closure's start")
END_BASIS = ("the first complete read of DSHS's table, republished with a new date, that no longer listed the area "
             "as closed for this reason, an upper bound: the table gives no reopening date")
LISTED_ONLY_NOTE = ("DSHS's area code has no outline here (DSHS's harvest-area map names its areas by bay and class): "
                    "listed with DSHS's code and placed on no water, so it colours none")


def text_of(fragment: str) -> str:
    return P.text_of(fragment).replace(" ", " ").strip()


def table_day(s: str) -> date:
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s.strip())
    if not m:
        raise ValueError("the table's date cannot be read")
    return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))


def parse(page: str, fetched: str | None = None) -> dict:
    """{updated, rows, unread}; ValueError for a page that is not a complete reading."""
    if not re.search(r"</html\s*>", page or "", re.I):
        raise ValueError("the page is not complete (no closing html tag)")
    if len(TITLE.findall(page)) != 1:
        raise ValueError("the page's title is not Shellfish Harvest Area Status and Maps")
    hs = list(HEADING.finditer(page))
    if len(hs) != 1:
        raise ValueError("the status heading is not on the page once")
    try:
        updated = table_day(hs[0].group("date"))
    except ValueError:
        raise ValueError("the table's date cannot be read") from None
    fetched_day = (datetime.fromisoformat(fetched.replace("Z", "+00:00")).astimezone(ZONE).date()
                   if fetched else date.today())
    if updated > fetched_day + timedelta(days=1):
        raise ValueError("the table's date is after the read")
    after = page[hs[0].end():]
    t = TABLE.search(after)
    if not t or re.search(r"<h[1-6]\b", after[:t.start()], re.I):
        raise ValueError("the status table does not follow its heading")
    body = t.group("body")
    head = [text_of(x) for x in re.findall(r"<th\b[^>]*>(.*?)</th>", body, re.S | re.I)]
    if head != EXPECTED_HEAD:
        raise ValueError("the status table's headings are not the four expected")
    tb = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", body, re.S | re.I)
    if not tb:
        raise ValueError("the status table has no body")
    trs = re.findall(r"<tr\b[^>]*>(.*?)</tr>", tb.group(1), re.S | re.I)
    if not trs or len(re.findall(r"<tr\b", tb.group(1), re.I)) != len(trs):
        raise ValueError("the status table's rows are not completely readable")
    rows, unread = [], []
    for n, tr in enumerate(trs, start=1):
        cells = [text_of(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", tr, re.S | re.I)]
        if len(cells) != 4 or len(re.findall(r"<td\b", tr, re.I)) != 4:
            raise ValueError("a row of the status table does not have four cells")
        area, pub, priv, reason = (re.sub(r"\s+", " ", c).strip() for c in cells)
        if not AREA.match(area):
            unread.append({"row": n, "reason": "an area code the reader cannot take"})
            continue
        if pub.lower() not in STATUS or priv.lower() not in STATUS:
            unread.append({"row": n, "area": area, "reason": "a status the reader does not take (not Open, Closed "
                                                             "or n/a)"})
            continue
        parts = [x.strip() for x in re.split(r"\s*[,;/]\s*|\s+and\s+(?=tpwd|rain|runoff|flood|spill|sewage|"
                                             r"wastewater|harmful|red tide)", reason, flags=re.I) if x.strip()]
        closed = "closed" in (pub.lower(), priv.lower())
        taken = [x for x in parts if TAKEN.match(x)]
        left = [x for x in parts if LEFT_OUT.match(x)]
        unknown = [x for x in parts if x.lower() != "n/a" and not TAKEN.match(x) and not LEFT_OUT.match(x)]
        if closed and (unknown or not parts or parts == ["n/a"]):
            unread.append({"row": n, "area": area, "reason": "a closure reason the reader does not know"})
            continue
        rows.append({"row": n, "area": area, "public_status": pub, "private_status": priv,
                     "reason": P.clean_text(reason)[0], "reasons_taken": taken, "reasons_left_out": left,
                     "kind": "closed" if closed and taken else "left_out" if closed else "open"})
    return {"updated": updated.isoformat(), "rows": rows, "unread": unread}


def key_of(area: str) -> str:
    return P.slug(area)


def saved_form(parsed: dict) -> str:
    """What the raw save keeps: the parsed table as JSON; never the page's markup."""
    return json.dumps(P.deep_clean({"url": URL, **parsed}), ensure_ascii=False, indent=1)


def build(page: str, fetched: str, previous: list[dict]) -> tuple[list[dict], dict]:
    parsed = parse(page, fetched)
    unread = list(parsed["unread"])
    open_prev = {}
    for p in previous:
        raw = p.get("raw") or {}
        if p.get("status") == "advisory_active" and raw.get("area_key"):
            open_prev[raw["area_key"]] = p
    records: dict[str, dict] = {}
    opened = 0
    seen = set()
    for row in parsed["rows"]:
        if row["kind"] != "closed":
            continue
        k = key_of(row["area"])
        if k in seen:
            unread.append({"row": row["row"], "area": row["area"], "reason": "an area listed twice"})
            continue
        seen.add(k)
        prev = open_prev.get(k)
        praw = (prev or {}).get("raw") or {}
        srid = prev["source_record_id"] if prev else f"{k}:{P.episode_stamp(fetched)}"
        opened += prev is None
        updates = list(praw.get("table_updates") or [])
        if not updates or updates[-1].get("updated") != parsed["updated"] or updates[-1].get("reason") != row["reason"]:
            updates.append({"updated": parsed["updated"], "reason": row["reason"], "public_status": row["public_status"],
                            "private_status": row["private_status"], "seen_at": fetched})
        raw = {"area_key": k, "area_code": row["area"], "public_status": row["public_status"],
               "private_status": row["private_status"], "reason": row["reason"], "reasons_taken": row["reasons_taken"],
               "reasons_left_out": row["reasons_left_out"], "table_updated": parsed["updated"],
               "table_updates": P.deep_clean(updates), "start_basis": START_BASIS, "time_zone": "America/Chicago",
               "_first_seen_at": praw.get("_first_seen_at") or fetched, "_last_seen_in_source": fetched,
               "_poll_confirmed": True, "page_url": URL, "state": "TX", "_placement": "listed_only",
               "placement_note": LISTED_ONLY_NOTE}
        which = " and ".join(x for x, s in (("public harvest", row["public_status"]),
                                            ("private oyster leases", row["private_status"])) if s.lower() == "closed")
        records[srid] = event(
            source_id=SOURCE_ID, source_record_id=srid, event_type="shellfish_closure", status="advisory_active",
            waterbody_text=f"Shellfish harvest area {row['area']}", water_slugs=[], water_match="none",
            started_at=prev["started_at"] if prev else fetched, time_precision="poll",
            published_at=parsed["updated"], source_updated_at=parsed["updated"], fetched_at=fetched,
            authority=AUTHORITY, source_url=URL, raw=raw,
            advice_text=(f"Shellfish harvest closure (Texas DSHS): area {row['area']}, closed to {which}. DSHS's "
                         f"reason: {row['reason']}. DSHS's table dated {parsed['updated']}."))
    listed_any = {key_of(r["area"]) for r in parsed["rows"]}
    unread_keys = {key_of(u["area"]) for u in unread if u.get("area")}
    for p in previous:
        raw = p.get("raw") or {}
        if p.get("status") == "advisory_active" and raw.get("area_key") not in listed_any | unread_keys \
                and raw.get("table_updated") == parsed["updated"]:
            # an area gone from a table DSHS has not republished is an incomplete read, not a reopening (RI P1-1)
            unread.append({"row": None, "area": raw.get("area_code"),
                           "reason": "a closed area is missing from a table with the same date"})
    lifted = held = kept = 0
    for p in previous:
        sid = p.get("source_record_id")
        if sid in records:
            continue
        p = P.recleaned(p)
        raw = dict(p.get("raw") or {})
        if p.get("status") == "advisory_active":
            k = raw.get("area_key")
            if unread:
                raw["_held_unread"] = f"the read was partial ({len(unread)} row(s) unread): held as it was"
                held += 1
            else:
                # listed Open or closed only for a reason left out (the row's own words, whatever the date), or gone
                # from a table republished with a new date (a missing row under the same date was held above)
                p.update(status="advisory_lifted", ended_at=fetched)
                raw.update(ended_at_precision="poll", end_basis=END_BASIS, _unlisted_since=fetched,
                           end_seen_as=_seen_as(parsed, k))
                lifted += 1
        p["raw"] = raw
        records[sid] = p
        kept += 1
    out = sorted(records.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "table_updated": parsed["updated"],
            "rows": len(parsed["rows"]) + len(parsed["unread"]),
            "closed_for_pollution_or_runoff": sorted(r["area"] for r in parsed["rows"] if r["kind"] == "closed"),
            "left_out": {"areas": sorted(r["area"] for r in parsed["rows"] if r["kind"] == "left_out"),
                         "rule": "closed only for TPWD action (a season or resource management) or a harmful algal "
                                 "bloom: no sign of sewage or runoff, not a record"},
            "open": sum(1 for r in parsed["rows"] if r["kind"] == "open"), "unread": unread, "opened": opened,
            "lifted_this_read": lifted, "held_unread": held, "kept_from_previous": kept - lifted - held,
            "advisory_active": sum(1 for r in out if r["status"] == "advisory_active"),
            "cadence": "page read every run; DSHS dates the table each time it changes",
            "coverage": "the Texas Gulf coast: every harvest area DSHS's table lists"}
    return out, meta


def _seen_as(parsed: dict, k: str) -> str:
    row = next((r for r in parsed["rows"] if key_of(r["area"]) == k), None)
    if row is None:
        return "no longer listed"
    if row["kind"] == "open":
        return "listed open"
    return "listed closed for a reason not taken here only (" + row["reason"] + ")"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fetched = now_iso()
    try:
        if "--file" in argv:
            page = Path(argv[argv.index("--file") + 1]).read_text(errors="replace")
        else:
            r = requests.get(URL, headers=HEADERS, timeout=(30, 120))
            r.raise_for_status()
            page = r.text
        prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
        recs, meta = build(page, fetched, prev)
        if "--file" not in argv:
            save_raw(SOURCE_ID, saved_form(parse(page, fetched)), "json")   # the parsed table only, never the page
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        P.write_refused(SOURCE_ID, P.safe_error(e), EVENTS_DIR)
        print(f"{SOURCE_ID}: FAILED {P.safe_error(e)}", file=sys.stderr)
        return 1
    if meta["unread"]:
        why = "; ".join(f"row {u['row']}: {u['reason']}" for u in meta["unread"])
        path = write_events(SOURCE_ID, recs, ok=False, partial=True, error=f"unread rows: {why}", meta=meta)
        print(f"{SOURCE_ID}: PARTIAL {len(meta['unread'])} row(s) unread -> {path}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: table dated {meta['table_updated']}, {len(meta['closed_for_pollution_or_runoff'])} closed for "
          f"pollution or runoff, {len(meta['left_out']['areas'])} left out; {len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
