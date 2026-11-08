"""TDEC's posted streams (Tennessee): the standing bacteriological water-contact advisories on TDEC's list of posted
streams, rivers and reservoirs, as advisory records in TDEC's own words.

Source
  https://www.tn.gov/content/dam/tn/environment/water/watershed-planning/wr_wq_fish-advisories.pdf (registry:
  tn-tdec-bacteriological-advisories; linked from TDEC's Bacteriological and Fishing Advisories page), "Posted
  Streams, Rivers & Reservoirs in Tennessee", revised in place (Rev. August 2026 on 2026-11-07). Its section
  "Bacteriological Advisories in Tennessee" is a table (Stream | Portion | County | Comments) by region: 25 stream
  segments on 2026-11-07, 21 of them naming sewer collection systems or a sewage plant among the sources. TDEC's
  words in the same document: "it is the responsibility of the Department of Environment and Conservation to post
  warning signs so that the public will be aware of the threat to public health"; "streams and lakes with high levels
  of bacteria or other contaminants are not suitable for recreational activities such as swimming or wading".

Record rules
  - One record per segment: event_type beach_advisory (the water-contact advisory category, as Mississippi's water
    contact advisories), status advisory_active while the list carries it, authority TDEC, advice_text TDEC's
    sentence above, raw.portion (the stretch, "From Neyland Drive to Topeka Street near I-640 (Mile 0.2 to 4.0)"),
    raw.cause (TDEC's comment, "Knoxville urban runoff and collection system issues"), raw.county, raw.region.
  - Dates: the list gives no date for any posting. started_at is the time of this site's first read of the list
    that found the segment (time_precision poll; raw.start_basis says the posting began earlier, on a date TDEC does
    not give); the list's own revision ("Rev. August 2026") is kept as given in raw.list_revision, never as a day.
    published_at and reported_at stay null; fetched_at is each read. Each read that finds the segment confirms it
    (raw._last_seen_in_source); the first read that no longer finds it ends it (raw._unlisted_since: TDEC took it
    off its list). A failed read confirms nothing.
  - Place, by rules only: waterbody_text is the stream TDEC names and raw.county its county (the status build's
    county-aware name placement, build/status.py COUNTY_FIELD_STATES), and raw._placement "named_water_only", so a
    posting is never tied by its point to the water downstream (Boone Lake for Beaver Creek: final audit 2026-11-08
    P1-1); a posting whose stream has no record is unplaced and drawn as its marker. The point is the stream's mouth in the USGS
    Geographic Names Information System for that name in that county (MOUTHS: the GNIS feature id, read from The
    National Map's geonames service, Streams (Mouth), on 2026-11-07; coord_source "gnis"), so on a stream the advisory
    is a marker, never the whole stream's colour (advisory_on_river); raw.advisory_extent "named_water". A segment
    whose stream has no mouth in Tennessee (the Cumberland River in Davidson County) takes the downstream end of TDEC's
    portion from the National Bridge Inventory (BRIDGES: the Woodland Street Bridge; coord_source "hand").
  - The PDF's text is read with ingest.nh_pdftext (positioned text): the stream column's lines grouped by their gaps
    are the segments; every other cell is assigned to the segment whose band holds it. Some words are set in a font
    whose text comes out shifted ("1 H H O H \\ ¶ V" for "Neeley's"): they are shifted back (unshift).
Privacy: the list names no person; the contact on TDEC's page is not read.
Run from pipeline/:  python -m ingest.tn_tdec_posted_streams [--file list.pdf] [--force]
(read at most once in EVERY_HOURS; the status build ages an advisory out 14 days after its last confirmation)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

import common
from common import HEADERS, event, now_iso, read_json, save_raw, write_events
from ingest import nh_pdftext as P

SOURCE_ID = "tn-tdec-bacteriological-advisories"
URL = "https://www.tn.gov/content/dam/tn/environment/water/watershed-planning/wr_wq_fish-advisories.pdf"
PAGE = ("https://www.tn.gov/content/tn/environment/program-areas/wr-water-resources/watershed-stewardship/"
        "bacteriological-and-fishing-advisories.html")
AUTHORITY = "Tennessee Department of Environment and Conservation (posted streams: water-contact advisory)"
ADVICE = ("TDEC: “streams and lakes with high levels of bacteria or other contaminants are not suitable for "
          "recreational activities such as swimming or wading”; this stream is posted for bacteriological "
          "contamination.")
NOUN = "Water contact advisory (posted stream)"
EXTENT = "named_water"
REGION = re.compile(r"^\s*(East|Southeast|Middle|West)\s+Tennessee\s*$")
EMPTY = 2e3           # the cost of a row with nothing in a column (a blank cell is rare)
GAP = 14.2            # points: the lines of a cell are 13.8 apart; two cells at least 14.5
SEWER = re.compile(r"collection\s+system|\bSTP\b|sewage|sewer", re.I)
# the GNIS mouth of each posted stream in its county (The National Map geonames, layer 6 Streams (Mouth), read
# 2026-11-07): (name, county) -> (GNIS feature id, lat, lon)
MOUTHS = {
    ("Beaver Creek", "Sullivan"): (1327543, 36.4884, -82.319),
    ("Coal Creek", "Anderson"): (1306000, 36.2065, -84.1224),
    ("East Fork Poplar Creek", "Roane"): (1283359, 35.9495, -84.3874),
    ("First Creek", "Knox"): (1284297, 35.9604, -83.9127),
    ("Second Creek", "Knox"): (1301020, 35.9556, -83.9213),
    ("Goose Creek", "Knox"): (1285668, 35.9462, -83.9227),
    ("Sinking Creek", "Washington"): (1327021, 36.3393, -82.2935),     # the one flowing to the Watauga River
    ("Third Creek", "Knox"): (1272458, 35.9429, -83.9352),
    ("Turkey Creek", "Hamblen"): (1304193, 36.2612, -83.2882),         # the one from Cherokee Reservoir to Morristown
    ("Dudley Creek", "Sevier"): (1283062, 35.7262, -83.5124),
    ("Citico Creek", "Hamilton"): (1280568, 35.0537, -85.2891),
    ("Chattanooga Creek", "Hamilton"): (1305869, 35.0187, -85.3333),
    ("Stringers Branch", "Hamilton"): (1271598, 35.087, -85.3347),
    ("Little Duck River", "Coffee"): (1291484, 35.4795, -86.1105),
    ("Browns Creek", "Davidson"): (1278624, 36.162, -86.7433),
    ("Dry Creek", "Davidson"): (1282943, 36.2873, -86.6875),
    ("Gibson Creek", "Davidson"): (1306479, 36.2464, -86.7019),
    ("McCrory Creek", "Davidson"): (1303497, 36.1665, -86.6306),
    ("Richland Creek", "Davidson"): (1299362, 36.1642, -86.8883),
    ("Trace Creek", "Clay"): (1304147, 36.6095, -85.783),
    ("Wilson Branch", "Clay"): (1274793, 36.5562, -85.7805),
    ("East Fork Third Creek", "Knox"): (1283411, 35.9551, -83.948),       # GNIS's name: East Third Creek
    ("Cypress Creek", "Shelby"): (1281924, 35.1865, -90.0159),          # the tributary to the Wolf River
}


def unshift(t: str) -> str:
    """Text set in a font whose characters come out shifted by 29, with a NUL between them ('1 H H O H \\ ¶ V' ->
    "Neeley's"): shifted back; the curly apostrophe's code comes out as '¶'. Other text is returned as it is."""
    if "\x00" not in (t or ""):
        return t
    out = []
    for c in t.replace("\x00", ""):
        if c == "\u00b6":
            out.append("'")
        elif 0 <= ord(c) + 29 < 127:
            out.append(chr(ord(c) + 29))
        else:
            out.append(c)
    return "".join(out)


def _lines(items: list[dict]) -> list[list[dict]]:
    """Items grouped into lines (the same y within 2 points), top to bottom."""
    out: list[list[dict]] = []
    for i in sorted(items, key=lambda i: -i["y"]):
        if out and abs(out[-1][0]["y"] - i["y"]) < 2:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def _join(items: list[dict]) -> str:
    """A cell's text from its pieces: lines top to bottom, pieces left to right, a space where the gap between two
    pieces is wider than a character."""
    out = []
    for line in _lines(items):
        text, prev = "", None
        for i in sorted(line, key=lambda i: i["x"]):
            t = unshift(i["text"])
            if prev is not None:
                end = prev["x"] + 5.6 * len(unshift(prev["text"]))
                short_word = re.search(r"\b(?:to|of|and|the|in|at|from)$", prev["text"], re.I)
                if i["x"] - end > 6 or prev["text"].endswith(" ") or t.startswith(" ") \
                        or (short_word and i["x"] - end > 1):
                    text += " "
            text += t
            prev = i
        out.append(text)
    t = re.sub(r"\s+", " ", " ".join(out)).strip()
    t = re.sub(r"\s+([.,;:)])", r"\1", re.sub(r"\(\s+", "(", t))
    return re.sub(r"\s*-\s*(?=\d)", "-", t)


def section_items(items: list[dict]) -> list[dict]:
    """The positioned items of the bacteriological section, title to the mercury section."""
    out, on = [], False
    for i in items:
        if "Bacteriological Advisories in Tennessee" in i["text"]:
            on = True
            continue
        if on and re.search(r"Mercury\s+Contact", i["text"]):
            break
        if on:
            out.append(i)
    return out


def _partition(lines: list[list[dict]], anchors: list[float]) -> list[list[dict]]:
    """The column's lines (top to bottom) split, in order, into one group per row: every cell of the table is centred
    on its row, so the split puts each group's middle nearest its row's anchor (the middle of the stream cell), and
    never keeps a gap wider than a line's spacing inside one cell."""
    n, k = len(lines), len(anchors)
    ys = [sum(i["y"] for i in ln) / len(ln) for ln in lines]
    inf = float("inf")
    best = [[inf] * (n + 1) for _ in range(k + 1)]
    back = [[0] * (n + 1) for _ in range(k + 1)]
    best[0][0] = 0.0
    for r in range(1, k + 1):
        for j in range(n + 1):
            for s0 in range(j + 1):
                if best[r - 1][s0] == inf:
                    continue
                grp = ys[s0:j]
                # off-centre, plus a heavy cost for a wide gap inside one cell (lines of a cell are 13 to 14 points
                # apart; two cells are further apart, so a group holding a wide gap spans two rows)
                # and a cost for an empty cell, so that two rows' lines are never lumped into one centred group
                cost = (((sum(grp) / len(grp) - anchors[r - 1]) ** 2) * len(grp)
                        + 1e4 * sum(1 for a, b in zip(grp, grp[1:]) if a - b > GAP)) if grp else EMPTY
                if best[r - 1][s0] + cost < best[r][j]:
                    best[r][j], back[r][j] = best[r - 1][s0] + cost, s0
    groups, j = [], n
    for r in range(k, 0, -1):
        s0 = back[r][j]
        groups.append([i for ln in lines[s0:j] for i in ln])
        j = s0
    return groups[::-1]


def segments(items: list[dict]) -> list[dict]:
    """[{stream, portion, county, comments, region, page}] from the section's positioned items. Each block of the
    table starts at a header row (Stream, Portion, County, Comments), whose words give the block's column edges."""
    segs = []
    region = None
    for page in sorted({i["page"] for i in items}):
        its = [i for i in items if i["page"] == page and i["y"] > 45 and i["text"].strip()]
        heads = sorted({round(i["y"]) for i in its if i["text"].strip() == "Stream"}, reverse=True)
        regions = sorted(((i["y"], REGION.match(i["text"]).group(1)) for i in its if REGION.match(i["text"])),
                         reverse=True)
        for h, hy in enumerate(heads):
            hdr = {i["text"].strip(): i["x"] for i in its if abs(i["y"] - hy) < 2}
            if not {"Portion", "County", "Comments"} <= set(hdr):
                continue
            edge = [hdr["Portion"] - 6, hdr["County"] - 6, hdr["Comments"] - 6]
            floor = heads[h + 1] if h + 1 < len(heads) else 45
            floor = max([floor] + [ry for ry, _ in regions if ry < hy])
            reg = next((r for ry, r in sorted(regions) if ry > hy), None)
            region = reg or region
            body = [i for i in its if floor < i["y"] < hy - 2 and not REGION.match(i["text"])]
            col = {0: [], 1: [], 2: [], 3: []}
            for i in body:
                col[sum(i["x"] >= e for e in edge)].append(i)
            stream_lines = _lines(col[0])
            rows: list[list[list[dict]]] = []
            for ln in stream_lines:
                if rows and rows[-1][-1][0]["y"] - ln[0]["y"] <= 20:
                    rows[-1].append(ln)
                else:
                    rows.append([ln])
            if not rows:
                continue
            anchors = [sum(ln[0]["y"] for ln in r) / len(r) for r in rows]
            cells = {c: _partition(_lines(col[c]), anchors) for c in (1, 2, 3)}
            for k, r in enumerate(rows):
                segs.append({"stream": _join([i for ln in r for i in ln]), "portion": _join(cells[1][k]),
                             "county": _join(cells[2][k]), "comments": _join(cells[3][k]),
                             "region": f"{region} Tennessee" if region else None, "page": page})
    return segs


def revision(items: list[dict]) -> str | None:
    """The list's revision as printed in its footer ('August 2026')."""
    for k, i in enumerate(items):
        if i["text"].strip() == "Rev.":
            nxt = [j["text"] for j in items[k + 1:k + 3] if abs(j["y"] - i["y"]) < 2]
            if nxt:
                return re.sub(r"\s+", " ", nxt[0]).strip()
    return None


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def counties_of(cell: str) -> list[str]:
    return [c.strip() for c in re.split(r",|\band\b", cell or "") if c.strip()]


def water_name(stream: str) -> tuple[str, str | None]:
    """(the water placed on, a note): 'Beaver Creek (Bristol)' -> 'Beaver Creek'; 'Citico Creek unnamed tributary'
    -> 'Citico Creek' with the note that the posting is its unnamed tributary; 'Tributary to McCrory Creek' ->
    'McCrory Creek' likewise."""
    s = re.sub(r"\s*\([^)]*\)\s*", " ", stream).strip()
    m = re.match(r"^(.+?)\s+unnamed\s+tributar", s, re.I)
    if m:
        return m.group(1).strip(), "the posting is an unnamed tributary of this stream"
    m = re.match(r"^tributary\s+to\s+(.+)$", s, re.I)
    if m:
        return m.group(1).strip(), "the posting is a tributary of this stream"
    m = re.match(r"^East Fork of (.+)$", s)
    if m:
        return f"East Fork {m.group(1)}", None
    return s, None


# a posted segment of a river with no mouth in Tennessee: the point is the downstream end TDEC's portion names, from
# the National Bridge Inventory (FHWA, NTAD National Bridge Inventory layer, read 2026-11-08): (name, county) ->
# (structure number, lat, lon, the end it is)
BRIDGES = {
    ("Cumberland River", "Davidson"): ("19M32440001", 36.16687, -86.77637,
                                       "the Woodland Street Bridge (river mile 190.6), the downstream end of the posting"),
}


def record(seg: dict, rev: str | None, at: str) -> dict:
    water, note = water_name(seg["stream"])
    counties = counties_of(seg["county"])
    mouth = next((MOUTHS[(water, c)] for c in counties if (water, c) in MOUTHS), None)
    bridge = None if mouth else next((BRIDGES[(water, c)] for c in counties if (water, c) in BRIDGES), None)
    lat, lon = (mouth[1], mouth[2]) if mouth else (bridge[1], bridge[2]) if bridge else (None, None)
    raw = {"state": "TN", "county": f"{counties[0]} County" if counties else None,
           "counties": [f"{c} County" for c in counties], "region": seg["region"], "stream_as_listed": seg["stream"],
           "portion": seg["portion"], "cause": seg["comments"], "sewer_cause": bool(SEWER.search(seg["comments"] or "")),
           "list_revision": rev, "list_url": URL, "advisory_extent": EXTENT, "advisory_noun": NOUN,
           "start_basis": ("TDEC's list gives no date for the posting: the start is this site's first read of the list "
                           "that found it (time_precision poll); the posting began earlier"),
           # the point is the marker only: the posting is placed by its stream's name and county, never by the point,
           # which lies on the water downstream (final audit 2026-11-08 P1-1; build/status.py named_water_only)
           "_placement": "named_water_only",
           "coords_basis": (f"the stream's mouth in the USGS Geographic Names Information System (feature {mouth[0]}, "
                            f"Streams (Mouth), read 2026-11-07), the marker only" if mouth else
                            f"{bridge[3]}, from the National Bridge Inventory (structure {bridge[0]}, read 2026-11-08), "
                            f"the marker only" if bridge else
                            "no GNIS mouth of this name in this county: placed by its name and county only")}
    if note:
        raw["water_note"] = note
    return event(source_id=SOURCE_ID, source_record_id=slug(f"{seg['stream']}-{'-'.join(counties)}"),
                 event_type="beach_advisory", status="advisory_active", waterbody_text=water, lat=lat, lon=lon,
                 coord_source="gnis" if mouth else "hand" if bridge else None,
                 coord_precision_m=500 if mouth else 100 if bridge else None, started_at=at,
                 time_precision="poll", authority=AUTHORITY, advice_text=ADVICE, source_url=URL, fetched_at=at, raw=raw)


def run(items: list[dict], prev: list[dict], at: str) -> tuple[list[dict], dict]:
    """(records, stats): this read's segments, the previous records carried (a segment no longer listed is ended at
    this read by raw._unlisted_since)."""
    sec = section_items(items)
    segs = segments(sec)
    if len(segs) < 5:
        raise ValueError(f"only {len(segs)} segments read from the list: its layout changed")
    rev = revision(items)
    old = {r["event_id"]: r for r in prev}
    out, seen = {}, set()
    for s in segs:
        r = record(s, rev, at)
        o = old.get(r["event_id"])
        if o and not o["raw"].get("_unlisted_since"):
            r["started_at"] = o["started_at"]                 # the first read that found it
        r["raw"]["_last_seen_in_source"] = at
        out[r["event_id"]] = r
        seen.add(r["event_id"])
    for eid, o in old.items():
        if eid in seen:
            continue
        if not o["raw"].get("_unlisted_since"):
            o["raw"]["_unlisted_since"] = at                  # TDEC took it off its list
        o["fetched_at"] = at
        out[eid] = o
    recs = sorted(out.values(), key=lambda r: r["event_id"])
    stats = {"segments": len(segs), "sewer_cause": sum(1 for s in segs if SEWER.search(s["comments"] or "")),
             "with_point": sum(1 for r in recs if r["lat"] is not None and r["event_id"] in seen),
             "list_revision": rev, "unlisted": sum(1 for r in recs if r["raw"].get("_unlisted_since"))}
    return recs, stats


EVERY_HOURS = 20          # TDEC revises the list a few times a year: read it once a day, not every hour


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    doc = read_json(path, {}) or {}
    prev = doc.get("records") or []
    last = doc.get("last_ok_at") if doc.get("ok") else None
    if "--file" not in argv and last and "--force" not in argv:
        from datetime import datetime, timedelta, timezone
        if datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00")) < timedelta(hours=EVERY_HOURS):
            print(f"{SOURCE_ID}: read at {last}; next read after {EVERY_HOURS} hours")
            return 0
    try:
        if "--file" in argv:
            pdf = Path(argv[argv.index("--file") + 1]).read_bytes()
        else:
            r = requests.get(URL, headers=HEADERS, timeout=(15, 120))
            r.raise_for_status()
            pdf = r.content
            save_raw(SOURCE_ID, pdf, "pdf")              # TDEC's public list: it names no person
        items = P.text_items(pdf)
        recs, stats = run(items, prev, now_iso())
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, prev, ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    out = write_events(SOURCE_ID, recs, meta={"registry_ids": [SOURCE_ID], "url": URL, "page": PAGE, **stats,
                                              "credit": "Tennessee Department of Environment and Conservation, "
                                                        "Posted Streams, Rivers & Reservoirs in Tennessee"})
    print(f"{SOURCE_ID}: {len(recs)} records ({stats['segments']} listed, {stats['sewer_cause']} naming sewers) -> "
          f"{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
