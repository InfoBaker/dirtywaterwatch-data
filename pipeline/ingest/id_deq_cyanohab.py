"""Idaho DEQ's CyanoHAB Risk Data Table (harmful algal blooms) -> data/build/events/id-deq-cyanohab-risk-table.json.

Source
  https://www.deq.idaho.gov/water-quality/surface-water/cyanobacteria-harmful-algal-blooms/ (registry
  id-deq-cyanohab-risk-table): the Idaho Department of Environmental Quality's table "CyanoHAB Risk Data Table", one
  row per water with Risk Level, Waterbody, County, Data Type, Collection Date and More Information (19 rows on
  2026-11-14: 13 Health Advisory, 1 Alert, 5 Watch). The page explains the levels in DEQ's words: Idaho's response
  framework "includes two risk levels, Health Watch and Health Alert, that provide timely public information while
  toxin test results are pending", and "Health Advisories are issued as a press release through the DHW News webpage
  to inform news outlets and the public of where an active, toxic bloom has been confirmed"; "Using that information,
  DHW determines whether public health notifications are warranted." The table has no row identifier, no issue date
  and no lift date; the Collection Date is the date of the sample or image the row rests on, not an advisory's date.

  Points: the Idaho Department of Health and Welfare's map layer "Public Health Advisories for Recreational Waters in
  Idaho" (registry id-dhw-recreational-advisories; ArcGIS item 8f6fe24f43d044fc8a9e88aa721f101d,
  Public_Health_Advisories_for_Recreational_Waters_in_Idaho_V2_view/FeatureServer/0), the map DEQ's page points to,
  lists the same waters with DHW's own point and RiskTier. Only LocationDiscription, RiskTier, DisplayOnWebsite, Issue,
  Issue_other, WebNote and the point are requested: the layer's Name, Email, ContactInfo, Creator, Editor and
  InternalNote fields (staff and internal notes) are never requested or saved. DHW's Issue (a coded value:
  Cyanobacterial Bloom, Beach Closure, Swimmer's Itch, Other) decides what a row is: only a bloom row (or one with no
  Issue) is a bloom's point and tier; any other row is DHW's own listing (below), never a bloom. A DEQ row whose water DHW's layer names (case, apostrophes and dashes
  ignored) takes DHW's point, rounded to 0.001 degree (coord_source "source", raw.point_basis): the authority's own
  marker on the water, so the advisory draws there and a named arm (C. J. Strike's Bruneau and Snake River arms,
  Hayden Lake's north end) keeps its own place. The points of the last good read are kept in the state file, so a
  layer outage moves nothing; a row DHW does not map is placed by its name and county only.

Records (a list read as a snapshot; never an invented date)
  - Health Advisory: the authority's advisory (DHW issues it on DEQ's toxin results), event_type hab_advisory, status
    advisory_active while the table lists the water at that level, the table's words in advice_text. started_at is
    the first read that listed it at that level (time_precision poll; raw.start_basis says the advisory began before);
    sampled_at the row's Collection Date (a sample date, never an issue date); raw._last_seen_in_source the latest
    read that listed it, so the status build keeps it red while DEQ lists it. When a read shows the water at a lower
    level, the advisory record ends at that read (advisory_lifted, ended_at the read, raw.ended_at_precision "poll",
    raw.end_basis says which), an upper bound, not DHW's lift time. A water the table no longer lists ends only on
    evidence that the read is complete: every row of the read readable and DHW's layer, read in the same run, no longer
    showing the water at that level; until then it stays in effect (raw.first_unlisted_at, the feed's health false).
    A read after more than 14 days without one starts a new listing period (raw.listed_periods), so a later read never
    confirms the unread gap. A named part ("Hayden Lake - North") is raw.advisory_extent "part_of_water": DHW's marker,
    never the whole lake's colour.
  - Closure: a row whose More Information closes the water ("Waterbody closed to recreational use.", affirmative only)
    is the authority's closure whatever DEQ's level: advisory_active while listed, raw.closure_words, quoted as the
    table's (a level of its own, so the closure's end is the read that no longer shows it).
  - Watch and Alert (DEQ's risk levels while results are pending, or after a Health Alert expired): never an advisory
    here. Each is a hab_advisory record with status unknown, raw._agency_label_only (DEQ's level) and
    raw._caution_to_notice_end, and the source is in data/rules.json unresolved.sample_caution: the status build shows
    the site's caution, from the Collection Date (time_precision day) for 72 hours or until the read that no longer
    lists the water at that level (raw._notice_closed_at), whichever is later; while listed, 72 hours past the last
    read that listed it (raw._open_notice_caution_hours), so it holds between reads; DEQ's words are quoted, never as DHW's
    advisory. The interval's label is raw._sample_caution_label ("Health Watch, Idaho DEQ's risk level; no health
    advisory issued: the site's caution"; go-live audit 2026-11-16 P2), never the generic sample wording, since a Watch
    can follow an expired alert or rest on satellite imagery. An Alert row whose More Information says the water is "closed to recreational use" keeps that sentence
    in advice_text, quoted as the table's.
  - Identity: one record per water (the table's Waterbody, case and punctuation ignored, with its County) and level
    episode: source_record_id <water slug>:<county slug>:<level>:<the first read's UTC date>. A level change closes the
    episode and opens the next; a new Collection Date at the same level is kept in raw.collection_dates (the latest in
    sampled_at). A row the parser cannot read (a level it does not know, no water, a date it cannot read) is kept as an
    "unknown" record with parse_error, never dropped.
  - A page whose table cannot be found, or with no rows, is ok=False: the records stay and nothing ends.
  - Clock: the record's zone is its county's (pipeline/zones.py idaho_zone: Pacific north of the Salmon River, 49 CFR
    71.9), in raw.time_zone; the Collection Date is that zone's calendar day.
  - DHW's other listings (own-fixes 2026-11-21, after the Swim Guide review): a row of DHW's map whose Issue is not a
    cyanobacterial bloom and that the map shows (DisplayOnWebsite Yes) is a record of its own: Beach Closure ->
    beach_closure, Swimmer's Itch and Other -> beach_advisory, with DHW's Issue, its description of an Other issue and
    its web note in raw (dhw_issue, dhw_issue_other, dhw_web_note) and advice_text. It is in effect from the first read
    that showed it (time_precision poll) to the first complete read of the map that no longer shows it (or shows it
    as End or No); a failed or partial read ends nothing. data/rules.json beach_reason reads those three fields: a
    closure whose entry gives no water-quality reason is listed without a colour (decision 40). Identity:
    dhw:<location slug>:<issue slug>:<first read's UTC date>.
  - Toxin (DHW's coded name, not a concentration) and LongInfoURL (the map's health-advisory link) are retained
    with the map objectid, layer URL and observation time. They are episode detail, separate from the frozen point;
    a failed map read preserves the previous observation, and a closed episode never acquires a later toxin.
  Privacy: the table carries no personal data today; every row, DHW's names and the carried state go through
  ingest/ia_id_privacy.scrub before any save (raw, state, records, error text), and errors never quote the page.

Run from pipeline/: python -m ingest.id_deq_cyanohab [--file saved.html] [--layer-file layer.json] [--at ISO]
Cadence: daily is enough (DEQ edits the table a few times a week in season); it runs with the refresh.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import requests

import zones
from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json
from common import error_detail
from ingest.ia_id_privacy import scrub
from ingest.poll_periods import GAP_DAYS

SOURCE_ID = "id-deq-cyanohab-risk-table"
URL = "https://www.deq.idaho.gov/water-quality/surface-water/cyanobacteria-harmful-algal-blooms/"
LAYER = ("https://services1.arcgis.com/CNPdEkvnGl65jCX8/arcgis/rest/services/"
         "Public_Health_Advisories_for_Recreational_Waters_in_Idaho_V2_view/FeatureServer/0")
LAYER_QUERY = (LAYER + "/query?where=1%3D1&outFields=objectid,LocationDiscription,RiskTier,DisplayOnWebsite,Issue,"
               "Issue_other,WebNote,Toxin,LongInfoURL&returnGeometry=true&outSR=4326&f=json")
LAYER_ITEM = "https://www.arcgis.com/home/item.html?id=8f6fe24f43d044fc8a9e88aa721f101d"
STATE_PATH = BUILD_DIR / "id-deq-cyanohab-state.json"
AUTHORITY = ("Idaho Department of Health and Welfare and Idaho Department of Environmental Quality "
             "(CyanoHAB Risk Data Table)")
HEADERS_EXPECTED = ["Risk Level", "Waterbody", "County", "Data Type", "Collection Date", "More Information"]
# the table's levels -> (key, is the authority's advisory)
LEVELS = {"health advisory": ("advisory", True), "advisory": ("advisory", True),
          "alert": ("alert", False), "health alert": ("alert", False),
          "watch": ("watch", False), "health watch": ("watch", False)}
LEVEL_NAMES = {"advisory": "Health Advisory", "alert": "Health Alert", "watch": "Health Watch",
               "closure": "Closed to recreational use"}
# DHW's layer tier -> the table's level, for the cross-check before a disappearance ends anything
LAYER_LEVELS = {"health advisory": "advisory", "advisory": "advisory", "health alert": "alert", "alert": "alert",
                "health watch": "watch", "watch": "watch"}
# an explicit closure in the row's More Information ("Waterbody closed to recreational use."): the authority's own
# closure, red while listed and quoted as the table's; a negated, conditional or future closure is not one (lessons 1)
CLOSURE_RE = re.compile(r"(?i)\bclosed\s+to\s+(?:all\s+)?(?:recreation(?:al)?(?:\s+use)?|public\s+use|swimming|"
                        r"(?:all\s+)?water\s+contact|the\s+public)\b")
CLOSURE_NEG_RE = re.compile(r"(?i)\b(?:not|no\s+longer|never|if|unless|when|whether|may|might|could|would|should|will|"
                            r"shall|can|reopen\w*|re-open\w*|lift\w*|previously|was|were)\b")
CLOSURE_BASIS = "closed while DEQ's CyanoHAB Risk Data Table lists the closure (the table's own words)"
LEVEL_RULE = ("Idaho DEQ: Health Watch and Health Alert are risk levels “that provide timely public information "
              "while toxin test results are pending”; a Health Advisory is issued by the Department of Health and "
              "Welfare where “an active, toxic bloom has been confirmed”")
START_BASIS = ("the first read of DEQ's table that listed this water at this level: the table gives no issue date, so "
               "the advisory began before this time")
WINDOW_BASIS = "in effect while DEQ's CyanoHAB Risk Data Table lists the water as a Health Advisory"
END_GONE = "the first read of DEQ's table that no longer listed the water"
END_LEVEL = "the first read of DEQ's table that listed the water at another level ({})"
BLOOM_ISSUE = "cyanobacterial bloom"
DHW_AUTHORITY = "Idaho Department of Health and Welfare (Public Health Advisories for Recreational Waters map)"
DHW_START_BASIS = ("the first read of DHW's map that showed this listing: the map gives no issue date, so it began "
                   "before this time")
DHW_END_BASIS = "the first complete read of DHW's map that no longer showed it"
DHW_WINDOW_BASIS = "in effect while DHW's map shows it"


def clean(s) -> str:
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", str(s or ""))).replace("\xa0", " ").replace("​", " ")
    return re.sub(r"\s+", " ", s).strip()


def key(s: str) -> str:
    """'CJ Strike – Snake River Arm' and 'CJ Strike - Snake River Arm' -> 'cj strike snake river arm';
    "Henry's Lake" and 'Henrys Lake' -> 'henrys lake'."""
    s = clean(s).lower().replace("’", "").replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def slug(s: str) -> str:
    return key(s).replace(" ", "-")


def parse_table(page: str) -> list[dict]:
    """The table's rows as {level, water, county, data_type, collection_date, info}; ValueError when the table or its
    headers are not on the page, or it has no rows."""
    m = re.search(r"<table\b.*?</table>", page or "", re.S | re.I)
    if not m:
        raise ValueError("no table on DEQ's page")
    rows = re.findall(r"<tr\b.*?</tr>", m.group(0), re.S | re.I)
    cells = [[clean(c) for c in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", r, re.S | re.I)] for r in rows]
    if not cells or cells[0][:6] != HEADERS_EXPECTED:
        # the error names the column count only: the page's text never reaches the error metadata (lessons 6)
        raise ValueError(f"the table's headers are not DEQ's ({len(cells[0]) if cells else 0} header cells)")
    out = [dict(zip(("level", "water", "county", "data_type", "collection_date", "info"), c + [""] * (6 - len(c))))
           for c in cells[1:] if any(c)]
    if not out:
        raise ValueError("DEQ's table has no rows")
    return out


def read_date(s: str) -> str | None:
    """'10/08/2026' and '06/29/26' -> ISO date; None when unreadable."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", clean(s))
    if not m:
        return None
    mo, dy, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    yr = yr + 2000 if yr < 100 else yr
    try:
        return date(yr, mo, dy).isoformat()
    except ValueError:
        return None


def layer_problem(doc: dict) -> str | None:
    """Why DHW's layer answer cannot show that a water is gone, or None when it is a complete answer: an answer cut off
    at the server's transfer limit (exceededTransferLimit) or a feature with no name is a partial read (lessons 4)."""
    if not isinstance(doc, dict):
        return "DHW's layer answer is not a JSON object"
    if doc.get("exceededTransferLimit"):
        return "DHW's layer answer was cut off at the server's transfer limit"
    if any(not clean((f.get("attributes") or {}).get("LocationDiscription")) for f in doc.get("features") or []):
        return "a feature of DHW's layer has no name"
    return None


def parse_layer(doc: dict) -> dict[str, dict]:
    """{water key: {name, tier, lat, lon}} from DHW's layer answer (rounded to 0.001 degree); ValueError on an error.
    The name is scrubbed before its key is made (lessons 6). A feature without a point keeps its water and tier with
    lat and lon None: it still shows the water on DHW's map, so its advisory is never lifted for a missing point
    (Astra verification 2026-11-15)."""
    if not isinstance(doc, dict) or doc.get("error") or "features" not in doc:
        raise ValueError(f"DHW's layer answered no features: {str(doc.get('error') if isinstance(doc, dict) else doc)[:200]}")
    out = {}
    for f in doc["features"]:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        name = scrub(clean(a.get("LocationDiscription")))
        if not name or not is_bloom_issue(a.get("Issue")):
            continue                          # a closure, swimmer's itch or other listing is never a bloom's point
        lat = lon = None
        try:
            if g.get("x") is not None and g.get("y") is not None:
                lat, lon = round(float(g["y"]), 3), round(float(g["x"]), 3)
        except (TypeError, ValueError):
            lat = lon = None
        out[key(name)] = {"name": name, "tier": clean(a.get("RiskTier")) or None,
                          "shown": clean(a.get("DisplayOnWebsite")) or None, "lat": lat, "lon": lon,
                          "objectid": a.get("objectid"), "toxin": a.get("Toxin") if a.get("Toxin") in TOXINS else None,
                          "release_url": release_url(a.get("LongInfoURL"))}
    return out


TOXINS = {"Anatoxin a", "Cylindrospermopsin", "Microcystins", "Other"}  # DHW field domain, 2026-11-22


def release_url(value) -> str | None:
    """Keep a public HTTP(S) agency link, never credentials, contact text or tracking/query data."""
    if not isinstance(value, str) or scrub(value) != value or re.search(r"[\s<>]", value):
        return None
    try:
        u = urlsplit(value)
        if u.scheme not in {"https", "http"} or not u.hostname or u.username or u.password or u.query or u.fragment:
            return None
    except ValueError:
        return None
    return value


def is_bloom_issue(issue) -> bool:
    """True for DHW's Issue "Cyanobacterial Bloom" or none given (the layer's rows before the field was filled)."""
    k = key(issue or "")
    return not k or k == BLOOM_ISSUE


def _point(g: dict) -> tuple[float | None, float | None]:
    try:
        if g.get("x") is not None and g.get("y") is not None:
            return round(float(g["y"]), 3), round(float(g["x"]), 3)
    except (TypeError, ValueError):
        pass
    return None, None


def parse_issues(doc: dict) -> list[dict]:
    """DHW's rows whose Issue is not a cyanobacterial bloom (Beach Closure, Swimmer's Itch, Other), each as {name,
    issue, issue_other, web_note, shown, lat, lon}, every text scrubbed; ValueError on an error answer."""
    if not isinstance(doc, dict) or doc.get("error") or "features" not in doc:
        raise ValueError("DHW's layer answered no features")
    out = []
    for f in doc["features"]:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        name = scrub(clean(a.get("LocationDiscription")))
        if not name or is_bloom_issue(a.get("Issue")):
            continue
        lat, lon = _point(g)
        out.append({"objectid": a.get("objectid"), "name": name, "issue": scrub(clean(a.get("Issue"))),
                    "issue_other": scrub(clean(a.get("Issue_other"))) or None,
                    "web_note": scrub(clean(a.get("WebNote"))) or None,
                    "release_url": release_url(a.get("LongInfoURL")),
                    "shown": clean(a.get("DisplayOnWebsite")) or None, "lat": lat, "lon": lon})
    return out


def update_issues(state: dict, issues: list[dict] | None, at: str, layer_partial: str | None = None) -> None:
    """Open, continue and end DHW's own listings (parse_issues). None (the map was not read) changes nothing; a partial
    read opens and continues but ends nothing; a listing the map no longer shows as Yes ends at the first complete
    read without it."""
    eps = state.setdefault("dhw_episodes", {})
    if issues is None:
        return
    # a listing is DHW's row (objectid) with its issue: two rows of one name are two listings, and a renamed row
    # keeps its listing (Astra 2026-11-21 P1); a row without an objectid falls back to its name and issue
    shown = {}
    for it in issues:
        if str(it.get("shown") or "").strip().lower() == "yes":
            oid = it.get("objectid")
            shown[f"oid{oid}:{slug(it['issue'])}" if oid is not None else f"{slug(it['name'])}:{slug(it['issue'])}"] = it
    open_by = {ep["key"]: sid for sid, ep in eps.items() if not ep.get("ended_at")}
    for wk, it in shown.items():
        sid = open_by.get(wk)
        if sid is None:
            base = f"dhw:{slug(it['name'])}:{slug(it['issue'])}:{at[:10]}"
            sid, n = base, 2
            while sid in eps:
                sid, n = f"{base}~{n}", n + 1
            eps[sid] = {"key": wk, "first_seen": at}
        ep = eps[sid]
        ep.update(last_seen=at, row=dict(it))
        ep.pop("pending", None)
        if not ep.get("point") and it.get("lat") is not None and it.get("lon") is not None:
            ep["point"] = {"name": it["name"], "lat": it["lat"], "lon": it["lon"]}
    for sid, ep in eps.items():
        if ep.get("ended_at") or ep["key"] in shown:
            continue
        if layer_partial:
            ep["pending"] = f"DHW's map was read only in part ({layer_partial})"
            continue
        ep.pop("pending", None)
        ep.update(ended_at=at, end_basis=DHW_END_BASIS)


def _placed(pt: dict | None) -> dict | None:
    """The point when it has coordinates, else None."""
    return pt if pt and pt.get("lat") is not None and pt.get("lon") is not None else None


def split_water(water: str) -> tuple[str, str | None]:
    """('C J Strike Reservoir', 'Snake River Arm') for a qualified name; the name and None otherwise. A dash after
    the water's name gives the part DEQ means; the record keeps the whole name as listed."""
    m = re.match(r"^(.*?)\s+[–—-]\s+(.+)$", clean(water))
    if not m:
        return clean(water), None
    base, part = m.group(1).strip(), m.group(2).strip()
    if re.fullmatch(r"(?i)cj\s+strike", base):
        base = "C J Strike Reservoir"
    return base, part


def closure_words(info: str) -> str | None:
    """The sentence of the row's More Information that closes the water ("Waterbody closed to recreational use."),
    or None; "will be closed if", "is not closed", "was closed" are not a closure in effect (lessons 1)."""
    for sentence in re.split(r"(?<=[.!?;])\s+", clean(info)):
        m = CLOSURE_RE.search(sentence)
        if m and not CLOSURE_NEG_RE.search(sentence[:m.start()]):
            return sentence
    return None


def row_level(r: dict) -> str | None:
    """The row's level key ('advisory', 'alert', 'watch'), 'closure' where its More Information closes the water, or
    None when the reader cannot read the level."""
    lv = LEVELS.get(clean(r.get("level")).lower())
    if not lv:
        return None
    return "closure" if closure_words(r.get("info") or "") else lv[0]


def scrub_row(r: dict) -> dict:
    """Every text field of a row through the Iowa and Idaho scrub (ingest/ia_id_privacy.py) before any save."""
    return {k: (scrub(v) if isinstance(v, str) else v) for k, v in r.items()}


def _scrub_points(points: dict) -> dict:
    """DHW's names scrubbed and their keys made again from the scrubbed names (a key is derived text, lessons 6)."""
    out = {}
    for v in points.values():
        if isinstance(v, dict):
            v = dict(v, name=scrub(clean(v.get("name"))))
            if "toxin" in v:
                v["toxin"] = v["toxin"] if v["toxin"] in TOXINS else None
            if "release_url" in v:
                v["release_url"] = release_url(v["release_url"])
            out[key(v["name"] or "")] = v
    return out


def scrub_state(state: dict) -> dict:
    """The scrub again on everything carried from earlier state (rows, snapshots, DHW's names and their keys), lessons
    6. An episode's key and id are made from its row's water, scrubbed, so they are made again here too."""
    eps = {}
    for sid, ep in (state.get("episodes") or {}).items():
        if isinstance(ep.get("row"), dict):
            ep["row"] = scrub_row(ep["row"])
            if isinstance(ep.get("point"), dict):
                ep["point"] = next(iter(_scrub_points({"point": ep["point"]}).values()))
            old = ep.get("water_key") or ""
            new = (("unread-" + slug(" ".join(str(x) for x in ep["row"].values()))[:60]) if old.startswith("unread-")
                   else f"{slug(ep['row']['water'])}:{slug(ep['row']['county'])}")
            if new != old and sid.startswith(old):
                ep["water_key"], sid = new, new + sid[len(old):]
        if isinstance(ep.get("dhw_detail"), dict):
            d = ep["dhw_detail"]
            ep["dhw_detail"] = {"objectid": d.get("objectid"),
                                "toxin": d.get("toxin") if d.get("toxin") in TOXINS else None,
                                "release_url": release_url(d.get("release_url")), "observed_at": d.get("observed_at")}
        eps[sid] = ep
    if "episodes" in state:
        state["episodes"] = eps
    snap = state.get("last_snapshot")
    if isinstance(snap, dict):
        snap["rows"] = [scrub_row(r) for r in snap.get("rows") or [] if isinstance(r, dict)]
        if isinstance(snap.get("points"), dict):
            snap["points"] = _scrub_points(snap["points"])
    if isinstance(state.get("points"), dict):
        state["points"] = _scrub_points(state["points"])
    for ep in (state.get("dhw_episodes") or {}).values():
        if isinstance(ep.get("row"), dict):
            ep["row"] = scrub_row(ep["row"])
        if isinstance(ep.get("point"), dict):
            ep["point"] = dict(ep["point"], name=scrub(clean(ep["point"].get("name"))))
    return state


def _on_layer(layer: dict, ep: dict) -> bool:
    """True when DHW's layer, read in this run, still shows the episode's water at its level (a tier the reader does
    not know counts as shown: the disappearance waits)."""
    pt = layer.get(key(ep["row"]["water"]))
    if not pt:
        return False
    tier = LAYER_LEVELS.get(clean(pt.get("tier")).lower())
    want = "alert" if ep["level"] == "closure" else ep["level"]
    return tier is None or tier == want


def update(state: dict, rows: list[dict], at: str, layer: dict | None, layer_partial: str | None = None,
           issues: list[dict] | None = None) -> dict:
    """Fold one read of the table into the state: open, continue and close level episodes.

    A water shown at another level closes its episode at this read (DEQ's own row says so). A water the table no
    longer lists closes only on evidence that the read is complete (Astra 2026-11-15 P1-1): every row of this read is
    readable, and DHW's map, read in the same run, no longer shows the water at that level. Otherwise the episode stays
    open, pending (state.last_poll.pending, the feed's health false), and closes at the first read that has the
    evidence, never earlier (raw.first_unlisted_at keeps the first read that missed it). A layer answer that is partial
    (layer_partial: cut off at the transfer limit, a feature with no name) is no evidence of a disappearance; a water
    whose feature has no point keeps the point of the last good read (Astra verification 2026-11-15)."""
    if layer is not None:
        before = state.get("points") or {}
        merged = {k: (dict(v, lat=before[k]["lat"], lon=before[k]["lon"])
                      if not _placed(v) and _placed(before.get(k)) else v) for k, v in layer.items()}
        if layer_partial:
            merged = {**before, **merged}           # a cut-off answer drops nothing it did not show
        state["points"] = merged
        state["points_read_at"] = at
    eps = state.setdefault("episodes", {})
    seen = {}
    unread = 0
    for r in rows:
        lv = row_level(r)
        wk = f"{slug(r['water'])}:{slug(r['county'])}"
        if not lv or not r["water"]:
            wk = "unread-" + slug(" ".join(r.values()))[:60]
            unread += 1
        seen[wk] = (lv or "unknown", r)
    pending = []
    for sid, ep in eps.items():
        if ep.get("ended_at"):
            continue
        cur = seen.get(ep["water_key"])
        if cur is None:
            if ep["level"] == "unknown":         # an unreadable row read since, or gone: nothing coloured it
                ep.update(ended_at=at, end_basis=END_GONE)
                continue
            ep.setdefault("first_unlisted_at", at)
            why = ("rows of this read could not be read" if unread else
                   "DHW's map was not read in this run" if layer is None else
                   f"DHW's map was read only in part ({layer_partial})" if layer_partial else
                   "DHW's map still shows the water at this level" if _on_layer(layer, ep) else None)
            if why:
                ep["pending"] = why
                pending.append(sid)
                continue
            ep.pop("pending", None)
            ep.update(ended_at=at, end_basis=END_GONE,
                      end_evidence="every row of this read was readable and DHW's map, read in the same run, no "
                                   "longer showed the water at this level")
        elif cur[0] != ep["level"]:
            ep.update(ended_at=at, end_basis=END_LEVEL.format(LEVEL_NAMES.get(cur[0], cur[1]["level"])))
    open_by_key = {ep["water_key"]: sid for sid, ep in eps.items() if not ep.get("ended_at")}
    for wk, (lv, r) in seen.items():
        sid = open_by_key.get(wk)
        if sid is None:
            sid = f"{wk}:{lv}:{at[:10]}"
            n = 2
            while sid in eps:
                sid, n = f"{wk}:{lv}:{at[:10]}~{n}", n + 1
            eps[sid] = {"water_key": wk, "level": lv, "first_seen": at, "collection_dates": []}
        ep = eps[sid]
        for k in ("first_unlisted_at", "pending"):
            ep.pop(k, None)
        # listing periods: a read after an unread gap longer than the confirmation horizon starts a new period, so
        # a later listing never confirms the gap (lessons 2; build/status.py colours each period on its own)
        periods = ep.setdefault("periods", [{"from": ep["first_seen"], "to": ep.get("last_seen") or ep["first_seen"]}])
        last = periods[-1]
        if _days(last["to"], at) > GAP_DAYS:
            periods.append({"from": at, "to": at})
        elif at > last["to"]:
            last["to"] = at
        ep.update(last_seen=at, row=r)
        # Detail is versioned with this episode, separately from its immutable placement point.
        current = (layer or {}).get(key(r["water"]))
        if current is not None:
            ep["dhw_detail"] = {"objectid": current.get("objectid"), "toxin": current.get("toxin"),
                                "release_url": release_url(current.get("release_url")), "observed_at": at}
        # the episode keeps the point it was first placed at: a later move of DHW's marker never rewrites an earlier
        # record's place (lessons 3); an episode with no point yet takes the first one the layer gives
        if not ep.get("point"):
            pt = _placed((state.get("points") or {}).get(key(r["water"])))
            if pt:
                ep["point"] = dict(pt)
        d = read_date(r["collection_date"])
        if d and d not in ep["collection_dates"]:
            ep["collection_dates"].append(d)
    update_issues(state, issues, at, layer_partial)
    state["last_poll"] = {"at": at, "rows": len(rows), "listed": sorted(seen), "unread_rows": unread,
                          "pending": sorted(pending),
                          "dhw_listings": sorted(ep["key"] for ep in (state.get("dhw_episodes") or {}).values()
                                                 if not ep.get("ended_at"))}
    return state


def _days(a: str, b: str) -> float:
    from datetime import datetime
    t = [datetime.fromisoformat(str(x).replace("Z", "+00:00")) for x in (a, b)]
    return (t[1] - t[0]).total_seconds() / 86400


def records(state: dict) -> list[dict]:
    points = state.get("points") or {}
    out = []
    for sid, ep in sorted(state.get("episodes", {}).items()):
        r = ep["row"]
        level, ended = ep["level"], ep.get("ended_at")
        base, part = split_water(r["water"])
        pt = _placed(ep.get("point")) or _placed(points.get(key(r["water"])))
        # the county decides; in Idaho County (split by the Salmon River) the listing's own point does (lessons 9)
        zone = zones.idaho_zone(county=r["county"] or None, lat=(pt or {}).get("lat"), lon=(pt or {}).get("lon"))
        sample = sorted(ep["collection_dates"])[-1] if ep["collection_dates"] else None
        raw = {"row": dict(r), "level_as_listed": r["level"], "waterbody_as_listed": r["water"], "part": part,
               "county": f"{r['county']} County" if r["county"] else None, "state": "ID",
               "collection_dates": sorted(ep["collection_dates"]), "first_seen_at": ep["first_seen"],
               "_last_seen_in_source": ep.get("last_seen"), "time_zone": zone,
               "timezone_note": ("Pacific time north of the Salmon River, Mountain time elsewhere (49 CFR 71.9): "
                                 f"{r['county'] or 'no county'} County; the Collection Date is a calendar day there"),
               "level_rule": LEVEL_RULE, "advisory_noun": "Algal bloom health advisory",
               "date_note": ("the Collection Date is the date of the sample or image the row rests on (DEQ's "
                             "column), not an advisory's issue date")}
        detail = ep.get("dhw_detail") or {}
        if detail:
            raw.update(dhw_objectid=detail.get("objectid"),
                       dhw_toxin=detail.get("toxin") if detail.get("toxin") in TOXINS else None,
                       dhw_release_url=release_url(detail.get("release_url")),
                       dhw_detail_observed_at=detail.get("observed_at"), dhw_detail_source_url=LAYER)
        lat = lon = None
        if pt:
            lat, lon = pt["lat"], pt["lon"]
            raw.update(point_basis=(f"Idaho Department of Health and Welfare's map point for “{pt['name']}” "
                                    "(Public Health Advisories for Recreational Waters in Idaho), rounded to 0.001 "
                                    "degree: the authority's marker on the water, not a sampling station"),
                       point_url=LAYER_ITEM, dhw_risk_tier=pt.get("tier"))
        if ended:
            raw.update(ended_at_precision="poll", end_basis=ep.get("end_basis"))
            if ep.get("end_evidence"):
                raw["end_evidence"] = ep["end_evidence"]
        if ep.get("first_unlisted_at"):
            raw.update(first_unlisted_at=ep["first_unlisted_at"], unlisted_pending=ep.get("pending"))
        periods = ep.get("periods") or []
        if len(periods) > 1:
            # listed again after an unread gap: each period is coloured on its own (build/status.py
            # POLL_END_HORIZON_SOURCES), so the reappearance never confirms the gap (Astra 2026-11-15 P2-3)
            raw.update(listed_periods=[dict(p) for p in periods],
                       periods_basis=(f"reads of DEQ's table that listed the water; a read after more than {GAP_DAYS} "
                                      "days without one starts a new period, and the time between is not confirmed"))
        if part:
            # an advisory for part of a water ("Hayden Lake - North", "CJ Strike - Bruneau Arm"): a marker at DHW's
            # point, never the whole water's colour (build/status.py part_of_water; Astra 2026-11-15 P2-5)
            raw["advisory_extent"] = "part_of_water"
        info = r["info"]
        common_f = dict(source_id=SOURCE_ID, source_record_id=sid, waterbody_text=base, water_slugs=[],
                        water_match="none", lat=lat, lon=lon, coord_source="source" if pt else None,
                        coord_precision_m=150 if pt else None, reported_at=None, published_at=None,
                        source_updated_at=None, authority=AUTHORITY, source_url=URL)
        if level == "closure":
            # the row's own closure ("Waterbody closed to recreational use."): the authority's closure, red while the
            # table lists it, quoted as the table's; DEQ's level is kept (Astra 2026-11-15 P1-2)
            words = closure_words(info)
            raw.update(start_basis=START_BASIS, closure_words=words,
                       _closure_level=LEVEL_NAMES.get(LEVELS.get(clean(r["level"]).lower(), ("",))[0], r["level"]))
            out.append(event(**common_f, event_type="hab_advisory",
                             status="advisory_lifted" if ended else "advisory_active",
                             started_at=ep["first_seen"], ended_at=ended, time_precision="poll", sampled_at=sample,
                             advice_text=(f"Closed to recreational use (DEQ's CyanoHAB Risk Data Table, {r['level']}, "
                                          f"{r['data_type'] or 'no data type given'}, collection date "
                                          f"{sample or 'not given'}): “{info}”"),
                             advice_window_hours=None, advice_window_basis=CLOSURE_BASIS, raw=raw))
        elif level == "advisory":
            raw["start_basis"] = START_BASIS
            out.append(event(**common_f, event_type="hab_advisory",
                             status="advisory_lifted" if ended else "advisory_active",
                             started_at=ep["first_seen"], ended_at=ended, time_precision="poll", sampled_at=sample,
                             advice_text=(f"Health Advisory (DEQ's CyanoHAB Risk Data Table, {r['data_type'] or 'no data type given'}"
                                          f", collection date {sample or r['collection_date'] or 'not given'}): "
                                          f"“{info}”" if info else "Health Advisory (DEQ's CyanoHAB Risk Data Table)"),
                             advice_window_hours=None, advice_window_basis=WINDOW_BASIS, raw=raw))
        elif level in ("alert", "watch"):
            name = LEVEL_NAMES[level]
            raw.update(_agency_label_only=True, _label_basis=f"DEQ's {name}: a risk level, not an advisory",
                       _agency_label=f"{name} (Idaho DEQ)",
                       _sample_caution_label=(f"{name}, Idaho DEQ's risk level; no health advisory issued: "
                                              "the site's caution"),
                       _caution_to_notice_end=True,
                       _notice_end_basis="DEQ's table still listed the water at this level")
            if ended:
                raw["_notice_closed_at"] = ended
            else:
                # a notice in DEQ's current listing stays in effect between reads: the caution holds the sample-caution
                # hours past the last read that listed it, so it never turns grey before the next read (Astra
                # 2026-11-15 P1-2; the status build's _open_notice_caution_hours, keyed on the record's field)
                raw["_open_notice_caution_hours"] = 72
            # no collection date: no calendar day is made from the read's UTC time; the start is the first read that
            # listed it, marked poll (the notice began before), as the advisories are (Astra verification 2026-11-15)
            start, precision = (sample, "day") if sample else (ep["first_seen"], "poll")
            if not sample:
                raw["start_basis"] = ("no collection date in the row: the first read of DEQ's table that listed the "
                                      "water at this level, so the notice began before this time")
            out.append(event(**common_f, event_type="hab_advisory", status="ended" if ended else "unknown",
                             started_at=start, ended_at=ended, time_precision=precision, sampled_at=sample,
                             advice_text=(f"{name} (DEQ's CyanoHAB Risk Data Table, {r['data_type'] or 'no data type given'}"
                                          f", collection date {sample or 'not given'}): “{info}”" if info
                                          else f"{name} (DEQ's CyanoHAB Risk Data Table)"),
                             advice_window_hours=None, advice_window_basis=None, raw=raw))
        else:
            out.append(event(**common_f, event_type="unknown", status="ended" if ended else "unknown",
                             started_at=ep["first_seen"], ended_at=ended, time_precision="poll", raw=raw,
                             parse_error=scrub(f"a row the reader cannot read: {r!r}")))
        if level != "unknown" and r["collection_date"] and not read_date(r["collection_date"]):
            out[-1]["parse_error"] = f"unreadable Collection Date {r['collection_date']!r}"
    out.extend(dhw_records(state))
    return out


def dhw_records(state: dict) -> list[dict]:
    """DHW's own listings (update_issues) as beach closures and advisories, never blooms."""
    out = []
    for sid, ep in sorted((state.get("dhw_episodes") or {}).items()):
        it, ended = ep["row"], ep.get("ended_at")
        issue = it["issue"]
        et = "beach_closure" if key(issue) == "beach closure" else "beach_advisory"
        base, part = split_water(it["name"])
        pt = _placed(ep.get("point"))
        zone = zones.idaho_zone(county=None, lat=(pt or {}).get("lat"), lon=(pt or {}).get("lon"))
        words = issue + (f": {it['issue_other']}" if it.get("issue_other") else "")
        raw = {"dhw_objectid": it.get("objectid"), "dhw_issue": issue, "dhw_issue_other": it.get("issue_other"),
               "dhw_web_note": it.get("web_note"),
               "dhw_release_url": release_url(it.get("release_url")),
               "dhw_detail_observed_at": ep.get("last_seen"), "dhw_detail_source_url": LAYER,
               "location_as_listed": it["name"], "part": part, "state": "ID", "first_seen_at": ep["first_seen"],
               "_last_seen_in_source": ep.get("last_seen"), "time_zone": zone, "start_basis": DHW_START_BASIS,
               "category_basis": ("DHW's Issue field: a Beach Closure is a beach closure, Swimmer's Itch and Other "
                                  "are beach advisories; only Cyanobacterial Bloom is a bloom")}
        if pt:
            raw.update(point_basis=(f"Idaho Department of Health and Welfare's map point for “{pt['name']}”, rounded "
                                    "to 0.001 degree"), point_url=LAYER_ITEM)
        if ended:
            raw.update(ended_at_precision="poll", end_basis=ep.get("end_basis"))
        if ep.get("pending"):
            raw["unlisted_pending"] = ep["pending"]
        if part:
            raw["advisory_extent"] = "part_of_water"
        note = it.get("web_note")
        out.append(event(source_id=SOURCE_ID, source_record_id=sid, event_type=et,
                         status="advisory_lifted" if ended else "advisory_active", waterbody_text=base,
                         water_slugs=[], water_match="none", lat=(pt or {}).get("lat"), lon=(pt or {}).get("lon"),
                         coord_source="source" if pt else None, coord_precision_m=150 if pt else None,
                         started_at=ep["first_seen"], ended_at=ended, time_precision="poll", reported_at=None,
                         published_at=None, source_updated_at=None, authority=DHW_AUTHORITY,
                         advice_text=(f"{words} (Idaho Department of Health and Welfare's map)"
                                      + (f": “{note}”" if note else "")),
                         advice_window_hours=None, advice_window_basis=DHW_WINDOW_BASIS, source_url=LAYER_ITEM,
                         raw=raw))
    return out


def fetch_page() -> str:
    r = requests.get(URL, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.text


def fetch_layer() -> dict:
    r = requests.get(LAYER_QUERY, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.json()


def read_layer(argv: list[str]) -> tuple[dict | None, list[dict] | None, str | None, str | None]:
    """(bloom points, DHW's other listings, why the read is partial, the error as it may be kept); (None, None, ...)
    when the layer was not read (an error, or --file without --layer-file)."""
    try:
        doc = (json.loads(Path(argv[argv.index("--layer-file") + 1]).read_text()) if "--layer-file" in argv
               else (None if "--file" in argv else fetch_layer()))
        if doc is None:
            return None, None, None, None
        layer, issues, partial = parse_layer(doc), parse_issues(doc), layer_problem(doc)
        err = (f"DHW's layer: {partial} (no water is ended on this read; the last good points are kept)"
               if partial else None)
        return layer, issues, partial, err
    except (requests.RequestException, OSError, ValueError) as e:
        return None, None, None, scrub(f"DHW's layer: {error_detail(e)} (the last good points are kept)")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = argv[argv.index("--at") + 1] if "--at" in argv else now_iso()
    try:
        page = Path(argv[argv.index("--file") + 1]).read_text() if "--file" in argv else fetch_page()
        # the scrub runs on every row before anything is saved or carried (lessons 6; Astra 2026-11-15 P1-5)
        rows = [scrub_row(r) for r in parse_table(page)]
        if not any(LEVELS.get(clean(r["level"]).lower()) and r["water"] for r in rows):
            # not one row the reader can read (renamed levels, shifted columns): a failed read, nothing ends
            raise ValueError("no row of DEQ's table could be read")
    except (requests.RequestException, OSError, ValueError) as e:
        err = scrub(str(e))
        # DEQ's table failed: nothing of the blooms changes, but DHW's own listings are read and kept up to date
        # (Astra 2026-11-21 P2); the feed stays unhealthy
        _, issues, layer_partial, layer_error = read_layer(argv)
        if issues is None:
            write_events(SOURCE_ID, [], ok=False, error=err)
            print(f"{SOURCE_ID}: {err}", file=sys.stderr)
            return 1
        state = scrub_state(read_json(STATE_PATH, {}) or {})
        update_issues(state, issues, at, layer_partial)
        write_json(STATE_PATH, state)
        write_events(SOURCE_ID, records(state), ok=False, partial=True, error=err,
                     meta={"layer_error": layer_error, "dhw_listings_read_at": at})
        print(f"{SOURCE_ID}: {err} (DHW's listings updated)", file=sys.stderr)
        return 1
    layer, issues, layer_partial, layer_error = read_layer(argv)
    state = scrub_state(read_json(STATE_PATH, {}) or {})
    snapshot = {"rows": rows, "points": layer, "dhw_listings": issues}
    if "--file" not in argv and state.get("last_snapshot") != snapshot:
        save_raw(SOURCE_ID, json.dumps({"fetched_at": at, **snapshot}, indent=1).encode(), "json")
    state["last_snapshot"] = snapshot
    state = update(state, rows, at, layer, layer_partial, issues=issues)
    write_json(STATE_PATH, state)
    recs = records(state)
    meta = {"registry_ids": [SOURCE_ID, "id-dhw-recreational-advisories"], "url": URL, "layer": LAYER,
            "last_poll": state.get("last_poll"), "points_read_at": state.get("points_read_at"),
            "layer_error": layer_error,
            "cadence": "with the refresh; DEQ edits the table a few times a week in season"}
    unread = [r for r in recs if r.get("parse_error") and not r.get("ended_at")]
    pending = (state.get("last_poll") or {}).get("pending") or []
    if unread or pending:
        # an unreadable row is kept (parse_error) and read again next run; a water the table no longer lists without
        # evidence that the read is complete stays open (pending); the feed is not healthy until both are settled
        meta["unread"] = [r["source_record_id"] for r in unread][:20]
        meta["pending_unlisted"] = pending[:20]
        why = []
        if unread:
            why.append(f"{len(unread)} row(s) of DEQ's table the reader cannot read")
        if pending:
            why.append(f"{len(pending)} water(s) no longer in DEQ's table without evidence the read is complete "
                       "(kept in effect)")
        path = write_events(SOURCE_ID, recs, ok=False, partial=True, meta=meta, error="; ".join(why))
    else:
        path = write_events(SOURCE_ID, recs, meta=meta)
    act = sum(1 for r in recs if r["status"] == "advisory_active")
    print(f"{SOURCE_ID}: {len(rows)} rows listed, {act} health advisories in effect; {len(recs)} records -> {path}"
          + (f"; {layer_error}" if layer_error else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
