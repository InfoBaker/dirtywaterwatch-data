"""Wyoming DEQ harmful cyanobacteria bloom bulletins -> bloom and toxin advisories (source id wy-deq-hcb-bulletins).

Source
  The Wyoming Department of Environmental Quality's public GovDelivery topic for harmful cyanobacteria blooms (HCB),
  read as its RSS feed: https://public.govdelivery.com/topics/WYDEQ_42/feed.rss (no key, no login; about 25 bulletins
  with the full bulletin HTML in each item). The bulletins are issued with the Wyoming Department of Health, which
  issues the advisories. Each "New HCB Recreational Use Advisory" bulletin, and most others, carries the table
  "Current HCB Recreational Use Advisories" (Waterbody Name | Observation or Sampling Location(s) | Advisory Type |
  Date Issued); a "... Advisory Lifted for <water>" bulletin states the lift. On 2026-11-14 the feed held 25
  bulletins (2026-07-31 to 2026-10-28). The program page (deq.wyoming.gov, HCB FAQ): a toxin advisory holds until two
  samples a day apart are below the recreational levels "or December 31st, whichever comes first"; a bloom advisory
  until the bloom has dissipated "or December 31st, whichever comes first".

Privacy
  The bulletins name staff with their e-mail addresses and telephones. Nothing of a bulletin is saved but the parsed
  rows: data/raw/ gets, per bulletin, its id, link, sent time, title, the table rows and a lift's one sentence (which
  names an agency and a water). The water and location cells are scrubbed (common.scrub_text, scrub_names); a point
  written in a water's name ("Unnamed Lake- Wind River Range (42.808, -109.327)") is rounded to three decimals before
  anything is saved.

Record rules
  - A row is keyed by water, location, advisory type and Date Issued (the agency's date, day precision, America/Denver);
    the key never depends on the order of rows or bulletins, so a reread or a reordering never duplicates a record.
    A row with a new Date Issued is a new advisory (a reissue), never a change to the earlier record.
  - Only a bulletin whose table was read whole counts as an observation: every row with four cells, the type Bloom or
    Toxin, a valid date. A bulletin whose table cannot be read is listed in meta.unread with its reason, observes
    nothing, and the run's health is false (write_events partial) while the readable bulletins still update records.
  - started_at is Date Issued (day). Every bulletin whose table lists the row confirms it (raw._last_seen_in_source,
    the bulletin's sent time, UTC). The first readable table after that which no longer lists it ends it as seen by a
    poll: ended_at that bulletin's sent time, raw.ended_at_precision "poll", raw._unlisted_since, and
    raw._ages_after_confirmation, so the colour stops 14 days after the last confirmation however late the absence is
    seen (lessons, item 2). A row listed again after an absence is a new record from that bulletin (time_precision
    "poll", id suffix "relisted-<local day>").
  - A lift bulletin ends the rows of its water that it no longer lists, only on an affirmative, completed sentence
    ("has lifted the ... advisory for Lake DeSmet"); a negated or conditional sentence ("will be lifted when", "has not
    lifted") ends nothing. ended_at is the bulletin's sent time, raw.ended_at_precision "bound" (lifted by then),
    status advisory_lifted.
  - A row still listed has no end: the status build ages it 14 days after its last confirming bulletin. The program's
    December 31 limit is kept as raw.program_end_bound (an upper bound from the FAQ, never an observed end).
  - No point except the one the agency writes in a name; otherwise placed by the water's name (state WY).

Run from pipeline/:  python -m ingest.wy_deq_hcb_bulletins [--file saved.rss]
"""
from __future__ import annotations

import html as H
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, scrub_names, scrub_text, write_events

SOURCE_ID = "wy-deq-hcb-bulletins"
URL = "https://public.govdelivery.com/topics/WYDEQ_42/feed.rss"
LANDING = "https://deq.wyoming.gov/water-quality/watershed-protection/cyanobacteria/"
AUTHORITY = "Wyoming Department of Health and Wyoming Department of Environmental Quality (HCB bulletins)"
TZ = "America/Denver"
ZONE = ZoneInfo(TZ)
HEADER = ("waterbody name", "observation or sampling location(s)", "advisory type", "date issued")
TYPES = {"bloom": "Bloom", "toxin": "Toxin"}
FAQ_END = ("WDEQ's HCB page: an advisory remains in effect until the bloom has dissipated or toxins are below the "
           "recreational-use levels, \"or December 31st, whichever comes first\"")
LIFT_RE = re.compile(r"\b(?:has|have)\s+(?:officially\s+)?lifted\s+the\s+[^.]*?advisor(?:y|ies)\s+for\s+([^.]+?)\s*\.",
                     re.I)
NOT_DONE = re.compile(r"\b(?:not|no|never|will|would|when|if|once|until|unless|may|expected|anticipate[sd]?|pending)\b",
                      re.I)
COORD_RE = re.compile(r"\(\s*(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*\)")


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def clean(s: str) -> str:
    return scrub_names(scrub_text(" ".join(H.unescape(s or "").replace("\xa0", " ").split())))


class _Tables(HTMLParser):
    """Every <table> as a list of rows of cell texts (nested markup flattened)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._stack: list[list[list[str]]] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._stack[-1].append([])
        elif tag in ("td", "th") and self._stack:
            if not self._stack[-1]:
                self._stack[-1].append([])
            self._cell = []
        elif tag in ("br", "p") and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._stack:
            self._stack[-1][-1].append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def plain_text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h or "")
    h = re.sub(r"(?i)<(br|/p|/tr|/div|/h\d|/li|/td)[^>]*>", "\n", h)
    return H.unescape(re.sub(r"<[^>]+>", " ", h)).replace("\xa0", " ")


def parse_date(s: str) -> str | None:
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


def split_water(name: str) -> tuple[str, float | None, float | None]:
    """'Unnamed Lake- Wind River Range (42.808, -109.327)' -> ('Unnamed Lake- Wind River Range', 42.808, -109.327)."""
    m = COORD_RE.search(name)
    if not m:
        return name, None, None
    lat, lon = round(float(m.group(1)), 3), round(float(m.group(2)), 3)
    if not (40.9 <= lat <= 45.1 and -111.1 <= lon <= -104.0):
        return COORD_RE.sub("", name).strip(" -"), None, None        # not a Wyoming point: dropped, never used
    return COORD_RE.sub("", name).strip(" -"), lat, lon


def read_table(desc: str) -> tuple[list[dict] | None, str | None]:
    """(rows, None) for a table read whole; (None, reason) when the bulletin has a table that cannot be read;
    ([], 'no table') is returned as (None, 'no table') so the caller can tell a release with no table apart."""
    p = _Tables()
    p.feed(desc or "")
    cands = [t for t in p.tables if t and any(c.lower().startswith("waterbody name") for c in t[0])]
    if not cands:
        if "current hcb recreational use advisories" in plain_text(desc).lower():
            return None, "the table's heading is there but its header row (Waterbody Name ...) was not found"
        return None, "no table"
    t = cands[0]
    head = tuple(c.lower().rstrip("* ").strip() for c in t[0])
    if head != HEADER:
        return None, f"the table's columns changed: {list(t[0])}"
    rows, seen = [], set()
    for i, cells in enumerate(t[1:], start=2):
        cells = [c for c in cells]
        if not any(cells):
            continue
        if len(cells) != 4:
            return None, f"table row {i} has {len(cells)} cells"
        water_raw, loc, typ, issued = (clean(c) for c in cells)
        typ_n = TYPES.get(typ.lower())
        day = parse_date(issued)
        if not water_raw or not typ_n or not day:
            return None, f"table row {i} could not be read (type {typ!r}, date {issued!r})"
        water, lat, lon = split_water(water_raw)
        point = f"-at-{lat:.3f}n-{abs(lon):.3f}w" if lat is not None else ""
        key = ":".join((slug(water) + point, slug(loc) or "no-location", typ_n.lower(), day))
        if key in seen:
            continue
        seen.add(key)
        place = None
        if ":" in water:                    # "Granite Reservoir: West Causeway": the part is a place on the water
            water, place = (x.strip() for x in water.split(":", 1))
        rows.append({"key": key, "water": water, "place": place or None, "location": loc or None, "type": typ_n,
                     "issued": day, "lat": lat, "lon": lon})
    return rows, None


def lift_of(title: str, desc: str) -> dict | None:
    """The water a bulletin affirmatively lifts, with the sentence, or None."""
    if "lifted" not in (title or "").lower():
        return None
    text = " ".join(plain_text(desc).split())
    for m in LIFT_RE.finditer(text):
        start = max(text.rfind(".", 0, m.start()) + 1, 0)
        sentence = text[start:m.end()].strip()
        if title and title in sentence:     # no full stop between the bulletin's heading and its first sentence
            sentence = sentence.rsplit(title, 1)[-1].strip()
        before = sentence[: sentence.lower().find("lifted")]
        if NOT_DONE.search(before):
            continue
        water = clean(m.group(1))
        tm = re.search(r"lifted\s+for\s+(.+)$", title or "", re.I)
        if tm and slug(clean(tm.group(1))) != slug(water):
            continue                        # the title and the sentence must name the same water
        return {"water": water, "sentence": clean(sentence)}
    return None


def read_feed(text: str) -> list[dict]:
    root = ET.fromstring(text)
    items = root.findall(".//item")
    if not items:
        raise ValueError("the feed has no items")
    out = []
    for it in items:
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate") or ""
        try:
            sent = parsedate_to_datetime(pub).astimezone(timezone.utc)
        except (TypeError, ValueError):
            raise ValueError(f"an item's pubDate could not be read: {pub!r}") from None
        title = clean(it.findtext("title") or "")
        desc = it.findtext("description") or ""
        if not link or not desc.strip():
            raise ValueError(f"an item has no link or no body: {title!r}")
        rows, why = read_table(desc)
        out.append({"id": link.rstrip("/").rsplit("/", 1)[-1], "link": link,
                    "sent": sent.strftime("%Y-%m-%dT%H:%M:%SZ"), "title": title, "rows": rows,
                    "table_issue": None if rows is not None or why == "no table" else why,
                    "lift": lift_of(title, desc)})
    return sorted(out, key=lambda b: (b["sent"], b["id"]))


def local_day(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZONE).date().isoformat()


def build(text: str, fetched: str, previous: list[dict]) -> tuple[list[dict], dict, list[dict]]:
    bulletins = read_feed(text)
    tables = [b for b in bulletins if b["rows"] is not None]
    unread = [{"bulletin": b["id"], "sent": b["sent"], "title": b["title"], "reason": b["table_issue"]}
              for b in bulletins if b["table_issue"]]
    if not tables:
        raise ValueError("no bulletin in the feed has a readable advisory table")
    # observations per key: times listed (with the bulletin) and times a readable table did not list it
    info: dict[str, dict] = {}
    seen: dict[str, dict[str, str]] = {}
    absent: dict[str, set[str]] = {}
    lifts: dict[str, list[dict]] = {}
    for p in previous:                      # what earlier runs observed (the feed keeps only ~25 bulletins)
        raw = p.get("raw") or {}
        k = raw.get("row_key")
        if not k:
            continue
        info.setdefault(k, {kk: raw.get(kk) for kk in ("water", "place", "location", "advisory_type", "issued", "lat", "lon")})
        seen.setdefault(k, {}).update(raw.get("_listed_in") or {})
        absent.setdefault(k, set()).update(raw.get("_absent_in") or [])
        if raw.get("_lift"):
            lifts.setdefault(slug(raw["water"]), [])
            if raw["_lift"] not in lifts[slug(raw["water"])]:
                lifts[slug(raw["water"])].append(raw["_lift"])
    for b in bulletins:
        if b["lift"]:
            lf = {"sent": b["sent"], "link": b["link"], "sentence": b["lift"]["sentence"],
                  "listed": sorted(r["key"] for r in (b["rows"] or [])), "has_table": b["rows"] is not None}
            lifts.setdefault(slug(b["lift"]["water"]), [])
            if lf not in lifts[slug(b["lift"]["water"])]:
                lifts[slug(b["lift"]["water"])].append(lf)
        if b["rows"] is None:
            continue
        here = {r["key"] for r in b["rows"]}
        for r in b["rows"]:
            info[r["key"]] = ({"water": r["water"], "place": r["place"], "location": r["location"],
                                       "advisory_type": r["type"],
                                       "issued": r["issued"], "lat": r["lat"], "lon": r["lon"]})   # this read's parse wins
            seen.setdefault(r["key"], {})[b["sent"]] = b["link"]
        for k in list(seen):
            if k not in here and min(seen[k]) < b["sent"]:
                absent.setdefault(k, set()).add(b["sent"])
    records = []
    n = {"bulletins": len(bulletins), "tables_read": len(tables), "rows_latest_table": len(tables[-1]["rows"]),
         "advisories": 0, "current": 0, "unlisted": 0, "lifted": 0, "relisted": 0}
    for k, inf in info.items():
        marks = sorted([(t, "seen") for t in seen.get(k, {})] + [(t, "absent") for t in absent.get(k, set())])
        periods, cur = [], None
        for t, kind in marks:
            if kind == "seen":
                if cur is None:
                    cur = {"from": t, "seen": [t], "absent": None}
                else:
                    cur["seen"].append(t)
            elif cur is not None and cur["absent"] is None and t > cur["seen"][-1]:
                cur["absent"] = t
                periods.append(cur)
                cur = None
        if cur is not None:
            periods.append(cur)
        for i, per in enumerate(periods):
            last = per["seen"][-1]
            lift = None
            for lf in sorted(lifts.get(slug(inf["water"]), []), key=lambda x: x["sent"]):
                if lf["sent"] > last and (per["absent"] is None or lf["sent"] <= per["absent"]) \
                        and k not in lf["listed"]:
                    lift = lf
                    break
            srid = k if i == 0 else f"{k}:relisted-{local_day(per['from'])}"
            year_end = f"{inf['issued'][:4]}-12-31" if i == 0 else f"{local_day(per['from'])[:4]}-12-31"
            raw = {"row_key": k, "water": inf["water"], "place": inf.get("place"), "location": inf["location"],
                   "advisory_type": inf["advisory_type"], "issued": inf["issued"], "lat": inf["lat"],
                   "lon": inf["lon"], "time_zone": TZ, "_agency_label": f"{inf['advisory_type']} advisory",
                   "_listed_in": {t: seen[k][t] for t in per["seen"]},
                   "_absent_in": sorted(absent.get(k, set())),
                   "_last_seen_in_source": last, "_first_seen_at": per["from"],
                   "program_end_bound": {"date": year_end, "basis": FAQ_END},
                   "placement_hint": {"name": inf["water"], "state": "WY",
                                      "basis": ("the point the agency writes in the water's name" if inf["lat"]
                                                is not None else "the water the bulletin names; it gives no point")},
                   "date_note": ("Date Issued is the agency's date for the advisory (day, Mountain time); the "
                                 "bulletin's sent time confirms it is still listed")}
            if i:
                raw["start_basis"] = ("listed again in the bulletin of this time after a readable bulletin had not "
                                      "listed it: a new period, its start the first bulletin that showed it again")
            status, end = "advisory_active", None
            if lift:
                status, end = "advisory_lifted", lift["sent"]
                raw.update({"ended_at_precision": "bound", "_lift": lift,
                            "end_basis": f"the agency's lift bulletin: \"{lift['sentence']}\""})
                n["lifted"] += 1
            elif per["absent"]:
                end = per["absent"]
                raw.update({"ended_at_precision": "poll", "_unlisted_since": per["absent"],
                            "_ages_after_confirmation": True,
                            "end_basis": ("the first readable bulletin table that no longer listed it (a poll bound; "
                                          "the agency sent no lift for it)")})
                n["unlisted"] += 1
            else:
                raw["end_basis"] = "still listed in the latest readable bulletin table"
                n["current"] += 1
            n["relisted"] += bool(i)
            loc = ", ".join(x for x in (inf.get("place"), inf["location"]) if x)
            loc = f" ({loc})" if loc else ""
            advice = (f"{inf['advisory_type']} advisory for {inf['water']}{loc}, issued {inf['issued']} by the "
                      "Wyoming Department of Health with WDEQ: avoid contact with water near the bloom; keep pets "
                      "and livestock away.")
            rec = event(source_id=SOURCE_ID, source_record_id=srid, event_type="hab_advisory", status=status,
                        waterbody_text=inf["water"], lat=inf["lat"], lon=inf["lon"],
                        coord_source="agency point in the bulletin's water name" if inf["lat"] is not None else None,
                        started_at=inf["issued"] if i == 0 else per["from"],
                        time_precision="day" if i == 0 else "poll", ended_at=end,
                        published_at=per["from"], fetched_at=fetched, authority=AUTHORITY, advice_text=advice,
                        source_url=seen[k][last], raw=raw)
            records.append(rec)
            n["advisories"] += 1
    out = sorted(records, key=lambda r: (str(r["started_at"]), r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "landing": LANDING, **n, "unread": unread,
            "latest_bulletin": bulletins[-1]["sent"], "latest_table": tables[-1]["sent"],
            "cadence": "the topic feed is read every run; WDEQ sends a bulletin when an advisory is issued or lifted"}
    saved = [{k: b[k] for k in ("id", "link", "sent", "title", "rows", "table_issue", "lift")} for b in bulletins]
    return out, meta, saved


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fetched = now_iso()
    try:
        if "--file" in argv:
            text = Path(argv[argv.index("--file") + 1]).read_text(encoding="utf-8")
        else:
            r = requests.get(URL, headers=HEADERS, timeout=90)
            r.raise_for_status()
            text = r.content.decode("utf-8")
        prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
        recs, meta, saved = build(text, fetched, prev)
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}"[:300])
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    if "--file" not in argv:
        save_raw(SOURCE_ID, json.dumps(saved, indent=1), "json")      # the parsed rows only (no staff names)
    ok = not meta["unread"]
    path = write_events(SOURCE_ID, recs, ok=ok, partial=not ok, meta=meta,
                        error=None if ok else f"{len(meta['unread'])} bulletin table(s) unread")
    print(f"{SOURCE_ID}: {meta['bulletins']} bulletins ({meta['tables_read']} tables), {meta['advisories']} advisories "
          f"({meta['current']} listed, {meta['unlisted']} unlisted, {meta['lifted']} lifted, {meta['relisted']} "
          f"relisted periods), {len(meta['unread'])} unread -> {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
