"""South Carolina DES's swimming advisories at beach monitoring stations and its harmful algal bloom watches and
advisories -> data/build/events/sc-des-beach-monitoring.json and sc-des-hab.json

Sources
  - Beach monitoring (registry sc-des-beach-monitoring): the S.C. Beach Access Guide's station layer,
    https://gis.des.sc.gov/gisserver/rest/services/water/BW_Monitoring_Stations/MapServer/0 (fields STAT, the
    station; COUNTY; ADVISORY; HUC_12; the point). 123 stations on 2026-11-14: 102 "No Advisory", 21 "Long-Term"
    (18 in Horry County on the Grand Strand, LC-080 to LC-082 at Edisto Beach in Colleton County). DES samples about
    122 points weekly from May 1 to October 1; a short-term advisory (one to two days) is issued after two consecutive
    results above 104 per 100 mL, or one above 500, and lifted when results fall below the standard; a long-term
    advisory stands, reassessed yearly, where stormwater makes high bacteria likely after rain. The guide's legend
    names four states: no active advisory, long-term, temporary (short-term) and emergency closure.
  - Harmful algal blooms (registry sc-des-hab): DES's bloom delineations, the layer the HAB Monitoring Map (ArcGIS web
    app 4344886507b04e32987fd8b44f8ed7ed, web map 1795d065b91f4f659d131e31c2567b98) draws,
    https://services5.arcgis.com/OMDIQXm11z4wcK26/arcgis/rest/services/algal_hydro_2_view/FeatureServer/0 (NAME, the
    water; Algal_Bloom, the organism; Date; Advisory_Tier: "HAB Not Present", "Watch", "Advisory"; Recreational_Guidance;
    GlobalID; the polygon), and the program page's table "HAB Watches & Advisories"
    (https://des.sc.gov/programs/bureau-water/aquatic-science/harmful-algal-blooms: Advisory Level, Advisory Area,
    Waterbody, Date Issued; "Any active, recreational watches and/or advisories will appear in the table below. If it
    is empty, there are no current watches and/or advisories listed."). 897 delineations on 2026-11-14, one a Watch
    (Microcystis, J. Strom Thurmond Reservoir, dated 2026-10-16; the table: Watch, Cedar Point Cove, J. Strom Thurmond,
    10/16/2026).

Records (rules only; a snapshot read as a sequence of polls)
  - Beach: a station whose ADVISORY is not "No Advisory" is a record. "Long-Term": a standing advisory in DES's words
    (event_type beach_advisory, status advisory_active, raw.advisory_kind "long-term"); "Temporary"/"Short-Term": a
    short-term advisory; "Emergency Closure" (or any "closure"): beach_closure; any other value is kept with the
    site's caution only (raw._agency_label_only, the label quoted), never dropped and never grey. The layer gives no
    date: started_at is the first poll that showed the advisory (time_precision poll; raw.start_basis says a
    long-term advisory has stood since before it), and the record ends at the first poll that no longer shows it
    (ended_at, raw.ended_at_precision poll, advisory_lifted). "No Advisory" is no record: grey, "no report", never
    clean. Out of season DES does not sample: no short-term advisory is not a finding.
  - Bloom: a delineation whose Advisory_Tier is Watch or Advisory is a record (hab_advisory, plum; raw.advisory_level
    quotes DES's tier, "Watch" or "Advisory", both DES's own recreational notices). started_at is the Date field (a
    date stored at midnight Eastern: precision day); the advisory's area is the table's Advisory Area when the table
    lists the same water and date (raw.advisory_area), the water is NAME. A record ends at the first poll where
    neither the layer nor the table shows it (DES's table lists only active watches and advisories; ended_at the
    poll, raw.ended_at_precision poll). A table row the layer does not hold is kept from the table alone (placed by
    name, no point). The polygon itself is not drawn: its centroid, rounded to three decimals, is the record's point
    (coord_source "des_delineation"), so the marker sits on the cove DES delineated and the whole reservoir is never
    coloured. "HAB Not Present" is no record.
  - Keys: beach "<STAT>-<first poll date>"; bloom "<GlobalID>-<date>" (the table-only row: "table-<water>-<date>").

Privacy: the layers' Creator and Editor fields (staff accounts) and the beach layer's GlobalID are never requested;
the fields read hold no person. data/raw keeps only the fields read.
Cadence: hourly with the refresh. Run from pipeline/: python -m ingest.sc_des_advisories [--file saved.json] [--at ISO]
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json
from ingest.de_dnrec_derns import scrub

# the attributes read from each layer: nothing else is kept, and their text is scrubbed (re-review P1-5)
BEACH_FIELDS = ("OBJECTID", "STAT", "HUC_12", "COUNTY", "ADVISORY")
HAB_FIELDS = ("OBJECTID", "NAME", "Algal_Bloom", "Date", "Advisory_Tier", "Recreational_Guidance", "GlobalID")

BEACH_ID = "sc-des-beach-monitoring"
HAB_ID = "sc-des-hab"
BEACH_LAYER = ("https://gis.des.sc.gov/gisserver/rest/services/water/BW_Monitoring_Stations/MapServer/0/query?"
               "where=1%3D1&outFields=OBJECTID,STAT,HUC_12,COUNTY,ADVISORY&returnGeometry=true&outSR=4326&f=json")
HAB_LAYER = ("https://services5.arcgis.com/OMDIQXm11z4wcK26/arcgis/rest/services/algal_hydro_2_view/FeatureServer/0/"
             "query?where=Advisory_Tier%3C%3E%27HAB+Not+Present%27&outFields=OBJECTID,NAME,Algal_Bloom,Date,"
             "Advisory_Tier,Recreational_Guidance,GlobalID&returnGeometry=false&returnCentroid=true&outSR=4326&f=json")
HAB_PAGE = "https://des.sc.gov/programs/bureau-water/aquatic-science/harmful-algal-blooms"
BEACH_PAGE = "https://des.sc.gov/programs/bureau-water/aquatic-science/beach-monitoring"
BEACH_GUIDE = "https://gis.des.sc.gov/beachaccess/"
HAB_MAP = "https://scdes.maps.arcgis.com/apps/webappviewer/index.html?id=4344886507b04e32987fd8b44f8ed7ed"
TZ = ZoneInfo("America/New_York")
STATE_PATH = BUILD_DIR / "sc-des-advisories-state.json"
SAFE_FORMAT = "dww-sc-des-advisories-safe/1"
TIMEOUT = (60, 300)
BEACH_AUTHORITY = "South Carolina Department of Environmental Services, Beach Monitoring"
HAB_AUTHORITY = "South Carolina Department of Environmental Services, Harmful Algal Bloom Monitoring"
BOUNDS = (-83.4, 32.0, -78.5, 35.25)        # South Carolina; a point outside is not used

BEACH_KINDS = [(re.compile(r"long", re.I), ("beach_advisory", "long-term")),
               (re.compile(r"closure|closed", re.I), ("beach_closure", "closure")),
               (re.compile(r"short|temporar", re.I), ("beach_advisory", "short-term"))]
NO_ADVISORY = re.compile(r"^\s*(?:no\s+advisory|none|no\s+active\s+advisory)\s*$", re.I)
LONG_TERM_ADVICE = ("SCDES: \"Long-term swimming advisories ... are issued for beach water monitoring locations that "
                    "have an increased possibility of high bacteria levels -- especially following rain events -- due "
                    "to stormwater runoff.\" \"An advisory means that SCDES advises you NOT to swim in those areas.\" "
                    "Wading, fishing and shell collecting are not affected.")
SHORT_TERM_ADVICE = ("SCDES: \"An advisory means that SCDES advises you NOT to swim in those areas.\" Short-term "
                     "advisories typically last one to two days and are lifted when sample results fall below the "
                     "standard.")
HAB_TIERS = {"watch": "Watch", "advisory": "Advisory"}
HAB_TEXT = ("SCDES lists this {tier} among its active recreational harmful algal bloom watches and advisories "
            "({organism}). SCDES: \"If a waterbody looks discolored, has a foul odor, noticeable algal mats, or dead "
            "fish or other animals, it's advisable to not enter the water or allow pets or animals near that water.\"")


def _in_sc(lat, lon) -> bool:
    return lat is not None and lon is not None and BOUNDS[1] <= lat <= BOUNDS[3] and BOUNDS[0] <= lon <= BOUNDS[2]


def _pt(geom: dict | None) -> tuple[float | None, float | None]:
    try:
        lat, lon = round(float(geom["y"]), 3), round(float(geom["x"]), 3)
    except (TypeError, KeyError, ValueError):
        return None, None
    return (lat, lon) if _in_sc(lat, lon) else (None, None)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def hab_table(page: str) -> list[dict] | None:
    """The program page's "HAB Watches & Advisories" rows, or None when the table is not on the page or is not in the
    shape DES publishes (a page that could not be read, an error row, changed columns, a cut-off table: nothing is
    ended). An empty list only from a whole table with no rows, or DES's "no current watches" line (re-review P1-3)."""
    i = page.find("HAB Watches")
    if i < 0:
        return None
    m = re.search(r"<table.*?</table>", page[i:], re.S)
    if not m:
        return [] if re.search(r"no current watches", page[i:i + 3000], re.I) else None
    head = [_text(c).lower() for c in re.findall(r"<th[^>]*>(.*?)</th>", m.group(0), re.S)]
    if head and not re.search(r"level|advisory|watch", head[0]):
        return None                                    # the columns changed: not read as DES's table
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S):
        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if not any(cells):
            continue                                   # a header row or an empty spacer
        if len(cells) < 4 or cells[0].strip().lower() not in HAB_TIERS or not _date(cells[3]) or not cells[2]:
            if len(cells) == 1 and re.search(r"no current watches", cells[0], re.I):
                continue
            return None                                # an error row or a row not in DES's shape
        rows.append({"level": cells[0], "area": cells[1], "water": cells[2], "issued": cells[3]})
    return rows


def check_layer(js, required: tuple[str, ...]) -> list[dict]:
    """A layer query's features, or ValueError for an error, a cut-off (exceededTransferLimit) or changed fields: an
    incomplete response never ends a record (re-review P1-3)."""
    if not isinstance(js, dict) or js.get("error") or not isinstance(js.get("features"), list):
        raise ValueError("the layer returned an error or no feature list")
    if js.get("exceededTransferLimit"):
        raise ValueError("the layer response was cut off (exceededTransferLimit)")
    for f in js["features"]:
        a = (f or {}).get("attributes")
        if not isinstance(a, dict) or any(k not in a for k in required):
            raise ValueError(f"a feature lacks the fields {required}")
    return js["features"]


def _date(s: str | None) -> str | None:
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%B %d, %Y"):
        try:
            return datetime.strptime((s or "").strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _epoch_date(ms) -> tuple[str | None, str | None]:
    """A Date field stored as an epoch: midnight Eastern is a date (precision day), any other time a time."""
    try:
        dt = datetime.fromtimestamp(float(ms) / 1000, timezone.utc).astimezone(TZ)
    except (TypeError, ValueError, OverflowError, OSError):
        return None, None
    if (dt.hour, dt.minute, dt.second) == (0, 0, 0):
        return dt.date().isoformat(), "day"
    return dt.isoformat(), "minute"


def _norm(s: str | None) -> str:
    s = re.sub(r"\b(?:reservoir|lake|j\.?|strom)\b", " ", (s or "").lower())
    return re.sub(r"[^a-z0-9]", "", s)


# ---------------------------------------------------------------- the beach stations

def safe_features(features: list[dict] | None, geom_key: str, fields: tuple[str, ...] | None = None) -> list[dict] | None:
    """Features cut to the attributes read (fields; by default the layer's own, BEACH_FIELDS or HAB_FIELDS), their text
    scrubbed (names after "call"/"contact", phones, e-mails, house numbers) and their point rounded to three decimals
    (0.001 degree), before anything is saved (re-review P1-5)."""
    if features is None:
        return None
    fields = fields or (BEACH_FIELDS if geom_key == "geometry" else HAB_FIELDS)
    out = []
    for f in features:
        lat, lon = _pt(f.get(geom_key))
        g = {"x": lon, "y": lat} if lat is not None else None
        a = f.get("attributes") or {}
        out.append({"attributes": {k: (scrub(a[k]) if isinstance(a.get(k), str) else a.get(k))
                                   for k in fields if k in a}, geom_key: g})
    return out


def safe_table(rows: list[dict] | None) -> list[dict] | None:
    """The bloom table's rows with their area and water text scrubbed before anything is saved."""
    if rows is None:
        return None
    return [{**r, "area": scrub(r.get("area")) or "", "water": scrub(r.get("water")) or ""} for r in rows]


def beach_records(features: list[dict], prev: dict, now: str) -> tuple[list[dict], dict, dict]:
    state = {k: dict(v) for k, v in (prev.get("beach") or {}).items()}
    showing, explicit, counts = {}, {}, {"stations": len(features)}
    for f in features:
        a = f.get("attributes") or {}
        adv = (a.get("ADVISORY") or "").strip()
        counts[adv or "(blank)"] = counts.get(adv or "(blank)", 0) + 1
        if not adv:
            continue                                   # a blank field says nothing: no record opened or ended
        explicit[a.get("STAT")] = adv
        if NO_ADVISORY.match(adv):
            continue
        showing[a.get("STAT")] = (a, f.get("geometry"), adv)
    for stat, (a, geom, adv) in showing.items():
        cur = next((v for v in state.values() if v["station"] == stat and not v.get("ended_at") and v["label"] == adv),
                   None)
        lat, lon = _pt(geom)
        if cur is None:
            key = base = f"{stat}-{re.sub(r'[^0-9T]', '', now)[:13]}"
            n = 2
            while key in state:                        # a reopening within the same minute: its own episode
                key, n = f"{base}-{n}", n + 1
            state[key] = {"station": stat, "label": adv, "county": a.get("COUNTY"),
                                           "huc12": a.get("HUC_12"), "lat": lat, "lon": lon, "started_at": now,
                                           "last_seen_at": now}
        else:
            cur.update(last_seen_at=now, lat=lat if lat is not None else cur.get("lat"),
                       lon=lon if lon is not None else cur.get("lon"))
    for v in state.values():
        if v.get("ended_at"):
            continue
        if v["station"] in explicit and explicit[v["station"]] != v["label"]:
            v["ended_at"] = now                        # DES's layer now gives the station another value
            v.pop("missing_since", None)
        elif v["station"] not in explicit:
            v["missing_since"] = v.get("missing_since") or now    # absent or blank: not a lift
        else:
            v.pop("missing_since", None)
    recs = []
    for key, v in sorted(state.items()):
        etype, kind = next((k for rx, k in BEACH_KINDS if rx.search(v["label"])), ("beach_advisory", None))
        raw = {"state": "SC", "time_zone": "America/New_York", "station": v["station"], "county": v.get("county"),
               "huc12": v.get("huc12"), "advisory_label": v["label"], "advisory_kind": kind,
               "_last_seen_in_source": v.get("last_seen_at"),
               "point_basis": "DES's beach monitoring station (the S.C. Beach Access Guide's station layer)",
               "start_basis": ("the first poll of DES's station layer that showed this advisory; the layer gives no "
                               "date" + ("; a long-term advisory stands from season to season, so it began before "
                                         "this poll" if kind == "long-term" else ""))}
        if v.get("ended_at"):
            raw.update(ended_at_precision="poll",
                       end_basis="the first poll of DES's station layer that gave the station another value")
        if v.get("missing_since"):
            raw["_missing_from_source_since"] = v["missing_since"]
        if kind is None:
            raw.update(_agency_label_only=True, _agency_label=v["label"],
                       _label_basis="a value of DES's ADVISORY field this site does not know; kept with its caution")
            status = "unknown"
        else:
            status = "advisory_lifted" if v.get("ended_at") else "advisory_active"
        recs.append(event(
            source_id=BEACH_ID, source_record_id=key, event_type=etype, status=status,
            outfall_name=f"Beach monitoring station {v['station']}", waterbody_text=None,
            lat=v.get("lat"), lon=v.get("lon"), coord_source="station" if v.get("lat") is not None else None,
            coord_precision_m=100 if v.get("lat") is not None else None,
            started_at=v["started_at"], ended_at=v.get("ended_at"), time_precision="poll", fetched_at=now,
            authority=BEACH_AUTHORITY, advice_text=LONG_TERM_ADVICE if kind == "long-term" else SHORT_TERM_ADVICE,
            source_url=BEACH_GUIDE, raw=raw))
    return recs, state, counts


# ---------------------------------------------------------------- blooms

def match_hab(state: dict, o: dict, seen: set) -> str | None:
    """The open record an observation continues: the same layer feature (GlobalID) first; else the same water and DES
    date, and the same area when both give one, only when exactly one open record fits (re-review P1-4)."""
    if o.get("layer_id"):
        for key, v in state.items():
            if key not in seen and not v.get("ended_at") and v.get("layer_id") == o["layer_id"]:
                return key
    fits = []
    for key, v in state.items():
        if key in seen or v.get("ended_at"):
            continue
        if _norm(v.get("water")) != _norm(o["water"]) or (v.get("started_at") or "") != (o["started_at"] or ""):
            continue
        if v.get("area") and o.get("area") and v["area"].lower() != o["area"].lower():
            continue
        if o.get("layer_id") and v.get("layer_id") and v["layer_id"] != o["layer_id"]:
            continue                                   # another delineation's record
        fits.append(key)
    if len(fits) == 1:
        return fits[0]
    if o.get("area"):
        same = [k for k in fits if (state[k].get("area") or "").lower() == o["area"].lower()]
        if len(same) == 1:
            return same[0]
    return None


def _row_fits(t: dict, water: str | None, start: str | None) -> bool:
    return bool(_norm(t["water"])) and _norm(t["water"]) in _norm(water) and _date(t["issued"]) == (start or "")[:10]


def hab_records(features: list[dict], table: list[dict] | None, prev: dict, now: str) -> tuple[list[dict], dict, dict]:
    """Layer delineations and table rows, reconciled. A delineation is tied to a table row (and so to its named area)
    only by evidence: its GlobalID was tied to that area before, or it is the only delineation and the row the only
    row for that water and DES date. Where two or more share a water and date with nothing to tell them apart, no
    point is assigned: the rows stand as table records without a point and the delineations are counted
    (meta.counts.ambiguous_delineations), never swapped between coves (re-review P1-4)."""
    state = {k: dict(v) for k, v in (prev.get("hab") or {}).items()}
    counts = {"delineations_listed": len(features), "table_rows": None if table is None else len(table),
              "ambiguous_delineations": 0}
    obs, used_rows = [], set()
    feats = []
    for f in features:
        a = f.get("attributes") or {}
        tier = HAB_TIERS.get((a.get("Advisory_Tier") or "").strip().lower())
        if not tier:
            continue
        start, prec = _epoch_date(a.get("Date"))
        lat, lon = _pt(f.get("centroid"))
        lid = a.get("GlobalID") or (f"oid-{a['OBJECTID']}" if a.get("OBJECTID") is not None else None)
        feats.append({"tier": tier, "water": a.get("NAME"), "organism": a.get("Algal_Bloom"),
                      "guidance": a.get("Recreational_Guidance"), "started_at": start, "precision": prec,
                      "area": None, "lat": lat, "lon": lon, "from": "layer", "layer_id": lid})
    rows = list(enumerate(table or []))
    # 1. a delineation already tied to an area keeps it: its row is the one naming that area
    known = {v["layer_id"]: v.get("area") for v in state.values() if v.get("layer_id") and not v.get("ended_at")}
    for o in feats:
        area = known.get(o["layer_id"])
        if area:
            o["area"] = area
            hit = next((i for i, t in rows if i not in used_rows and _row_fits(t, o["water"], o["started_at"])
                        and (t["area"] or "").lower() == area.lower()), None)
            if hit is not None:
                used_rows.add(hit)
            o["_tied"] = True
    # 2. the rest pair only one to one within a water and date
    for o in feats:
        if o.get("_tied"):
            continue
        cand = [i for i, t in rows if i not in used_rows and _row_fits(t, o["water"], o["started_at"])]
        others = [x for x in feats if x is not o and not x.get("_tied")
                  and any(_row_fits(rows[i][1], x["water"], x["started_at"]) for i in cand)]
        if len(cand) == 1 and not others:
            used_rows.add(cand[0])
            o["area"] = rows[cand[0]][1]["area"] or None
            o["_tied"] = True
        elif cand:
            o["_ambiguous"] = True
    for o in feats:
        if o.pop("_ambiguous", False):
            counts["ambiguous_delineations"] += 1
            continue                                   # its rows stand as table records; its point is not assigned
        o.pop("_tied", None)
        obs.append(o)
    for i, t in rows:
        if i in used_rows:
            continue
        start = _date(t["issued"])
        obs.append({"tier": HAB_TIERS.get(t["level"].strip().lower(), t["level"].strip()), "water": t["water"],
                    "organism": None, "guidance": None, "started_at": start, "precision": "day" if start else None,
                    "area": t["area"] or None, "lat": None, "lon": None, "from": "table", "layer_id": None})
    seen = set()
    for o in obs:
        key = match_hab(state, o, seen)
        if key is None:
            base = (f"hab-{_norm(o['water']) or 'water'}-{o['started_at'] or 'nodate'}-"
                    f"{re.sub(r'[^a-z0-9]+', '-', (o['area'] or 'area').lower()).strip('-')}")
            key, n = base, 2
            while key in state:
                key, n = f"{base}-{n}", n + 1
            state[key] = {**o, "first_seen_at": now}
        v = state[key]
        for k in ("tier", "area", "guidance", "organism", "lat", "lon", "layer_id"):
            if o.get(k) is not None:
                v[k] = o[k]                            # a table read keeps the layer's point and organism
        v["from"] = "layer" if (o["from"] == "layer" or v.get("from") == "layer") else "table"
        v["last_seen_at"] = now
        v.pop("ended_at", None)
        seen.add(key)
    for key, v in state.items():
        if key not in seen and not v.get("ended_at"):
            v["ended_at"] = now                        # neither the layer nor the table lists it (both were read)
    recs = []
    for key, v in sorted(state.items()):
        start = v.get("started_at") or v.get("first_seen_at")
        prec = v.get("precision") if v.get("started_at") else "poll"
        raw = {"state": "SC", "time_zone": "America/New_York", "advisory_level": v["tier"],
               "advisory_area": v.get("area"), "organism": v.get("organism"), "read_from": v.get("from"),
               "_last_seen_in_source": v.get("last_seen_at"), "first_seen_at": v.get("first_seen_at"),
               "start_basis": ("DES's date for the watch or advisory (a date, no time of day)" if v.get("started_at")
                               else "the first poll that listed it; DES gave no date")}
        if v.get("lat") is not None:
            raw["point_basis"] = "the centre of the area DES delineated for this bloom (HAB Monitoring Map)"
        if v.get("ended_at"):
            raw.update(ended_at_precision="poll",
                       end_basis=("the first poll at which DES's table and map no longer listed it (the table lists "
                                  "only active watches and advisories); DES's lift time is not published"))
        organism = v.get("organism") or "organism not given"
        recs.append(event(
            source_id=HAB_ID, source_record_id=key, event_type="hab_advisory",
            status="advisory_lifted" if v.get("ended_at") else "advisory_active",
            waterbody_text=v.get("water"), outfall_name=v.get("area"), lat=v.get("lat"), lon=v.get("lon"),
            coord_source="des_delineation" if v.get("lat") is not None else None,
            coord_precision_m=500 if v.get("lat") is not None else None,
            started_at=start, ended_at=v.get("ended_at"), time_precision=prec, fetched_at=now,
            authority=HAB_AUTHORITY, advice_text=v.get("guidance") or HAB_TEXT.format(tier=v["tier"].lower(), organism=organism),
            source_url=HAB_PAGE, raw=raw))
    return recs, state, counts


BEACH_META = {"credit": "South Carolina Department of Environmental Services, Beach Monitoring (S.C. Beach Access Guide)",
              "license": "No licence statement on the service",
              "caveat": ("DES's station layer shows each station's current advisory and no dates; a long-term advisory "
                         "stands where stormwater makes high bacteria likely after rain. DES samples from May 1 to "
                         "October 1: outside the season no short-term advisory is not a finding."),
              "time_basis": "Dated by the poll that first showed each advisory (the layer gives no dates)."}
HAB_META = {"credit": "South Carolina Department of Environmental Services, Harmful Algal Bloom Monitoring",
            "license": "No licence statement on the service",
            "caveat": "DES's watches and advisories as its program page and map list them; the area is DES's delineation.",
            "time_basis": "DES's issue date (no time of day); an end is the poll that no longer lists it."}


def run(args) -> int:
    now = args.at or now_iso()
    prev = {} if args.file else (read_json(STATE_PATH, {}) or {})
    if args.file:
        saved = json.loads(open(args.file).read())
        beach, hab, table = saved["beach"], saved["hab"], saved.get("hab_table")
        ok_b = ok_h = True
    else:
        beach = hab = table = None
        ok_b = ok_h = True
        try:
            r = requests.get(BEACH_LAYER, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            beach = check_layer(r.json(), ("STAT", "ADVISORY"))
            if not beach:
                raise RuntimeError("no stations")
        except (requests.RequestException, ValueError, KeyError, RuntimeError) as e:
            ok_b = False
            write_events(BEACH_ID, [], ok=False, error=f"{type(e).__name__}: {e}", meta=BEACH_META)
        try:
            r = requests.get(HAB_LAYER, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            hab = check_layer(r.json(), ("NAME", "Date", "Advisory_Tier"))
            p = requests.get(HAB_PAGE, headers=HEADERS, timeout=TIMEOUT)
            p.raise_for_status()
            table = safe_table(hab_table(p.text))
            if table is None:
                raise ValueError("the program page's watches and advisories table was not found")
        except (requests.RequestException, ValueError, KeyError) as e:
            ok_h = False
            write_events(HAB_ID, [], ok=False, error=f"{type(e).__name__}: {e}", meta=HAB_META)
        beach, hab = safe_features(beach, "geometry"), safe_features(hab, "centroid")
        save_raw("sc-des-advisories", json.dumps({"format": SAFE_FORMAT, "beach": beach, "hab": hab,
                                                  "hab_table": table}), "json")
    new = dict(prev)
    if ok_b:
        recs, new["beach"], n = beach_records(beach, prev, now)
        write_events(BEACH_ID, recs, meta={**BEACH_META, "counts": n}, path=args.out_beach)
        print(f"{BEACH_ID}: {len(recs)} records; {n}")
    if ok_h:
        recs, new["hab"], n = hab_records(hab, table, prev, now)
        write_events(HAB_ID, recs, meta={**HAB_META, "counts": n}, path=args.out_hab)
        print(f"{HAB_ID}: {len(recs)} records; {n}")
    if not args.file:
        write_json(STATE_PATH, new)
    return 0 if (ok_b and ok_h) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="saved {beach, hab, hab_table} JSON (no network)")
    ap.add_argument("--at")
    ap.add_argument("--out-beach")
    ap.add_argument("--out-hab")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
