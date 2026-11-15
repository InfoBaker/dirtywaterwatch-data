"""Indiana outfall rows that improve on EPA's (data/outfalls-in.json): IDEM's CSO outfall layer.

Usage: pipeline/.venv/bin/python -I scripts/build_in_outfalls.py [--fetch | FEATURES.json]
  --fetch asks the layer once for the safe fields below and saves the answer to data/raw/in-idem-cso-outfalls/
  features.json (git-ignored); otherwise that saved answer (or the file named) is read.

Source: IDEM, "Indiana CSO Outfall Map" (https://www.in.gov/idem/cleanwater/information-about/combined-sewer-overflow-
cso-program/indiana-cso-outfall-map), its hosted layer
https://services5.arcgis.com/w1CjlfkUGYWS5MJd/arcgis/rest/services/CSO_Locations_Map_WFL1/FeatureServer/0 (read
2026-11-14: 981 points on 110 permits; Active 578, Inactive 318, "Active, Discharge Prohibited" 85; Untreated CSO 938,
Treated CSO 41, one sanitary overflow, one blank). The layer states no licence; it is IDEM's public map, credited.

Safe fields: OBJECTID, Agency_Interest_ID, City, NPDES_Number, CSO_Number, Receiving_Stream, waterbody_desc_2 to 4,
Status, County, Basin, Sub_Basin, Watershed, Wastewater_Type, X_Coordinate, Y_Coordinate and the point. Photo_Credit
(people's names) and GlobalID are never asked for.

Why: EPA's national CSO inventory (data/outfalls-us.json) lists 1,196 Indiana rows on 138 permits (664 not closed),
140 of them at the plant's point (coords_from "facility"). IDEM's layer is the permitting authority's own: each outfall
with its own point, its receiving stream and the chain of waters downstream (waterbody_desc_2 to 4: "Tippecanoe River",
"Wabash River"), its county and basin, and IDEM's status. Each IDEM point becomes a registry row here citing the layer;
a regional file outranks the national one (common.outfall_file_rank), so these rows replace EPA's for the same permit
and outfall, and EPA's row stays in data/outfalls-us.json untouched, named in `supersedes`.
  - outfall: the leading number of IDEM's CSO_Number ("002C -- CSO - Town Lake" is 002; the C marks a CSO and CP a
    treated or partly treated one, both dropped; another letter stays: "004Z", "11A"); "A38" (Indianapolis's lettered
    outfalls) stays as written.
  - A point with no geometry (136 on 2026-11-14, 131 of them Inactive) is no row: listed under no_point, and EPA's row
    for it, if any, stays.
  - outfall_name: IDEM's text after "--", a house number in it cut (scrub_name: "1234 S Example St" -> "[house number
    removed] S State St"; route and structure numbers stay).
  - outfall_status: IDEM's Status. "Inactive" is written "CLS (inactive in IDEM's layer)" so the registry reads it as
    closed (common._closed) and no rain caution is drawn there; "Active" is "active (IDEM layer)"; "Active, Discharge
    Prohibited" is "active, discharge prohibited (IDEM layer)", kept open: the structure is still there and an
    unauthorised overflow from it is still possible (default applied: the owner's question in the build report).
  - outfall_kind: "cso" for IDEM's CSO types; Remington's one "Domestic (Sanitary) Wastewater" point, a former SSO
    (004Z), and Muncie's inactive manhole point with no type are "other" (no combined sewer outfall).
  - receiving_water_echo: IDEM's Receiving_Stream; downstream_waters: the chain IDEM gives. The water record is tied by
    the cloud batch (python -m ingest.outfall_waters --state IN), not here; until it runs, EPA's tie for the same
    outfall (water_slug, water_name, water_kind) is carried when IDEM's point lies within CARRY_TIE_M (500 m) of EPA's,
    so no outfall loses the water EPA's row gave it (match "carried from EPA's row").
  - County names are kept as IDEM writes them; the clock of a record at the outfall is its county's
    (zones.indiana_zone).
EPA's open rows that IDEM's layer lacks keep EPA's rows (listed under epa_not_in_state_layer).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "outfalls-in.json"
RAW = ROOT / "data" / "raw" / "in-idem-cso-outfalls" / "features.json"
SOURCE_ID = "in-idem-cso-outfall-layer"
LAYER = "https://services5.arcgis.com/w1CjlfkUGYWS5MJd/arcgis/rest/services/CSO_Locations_Map_WFL1/FeatureServer/0"
PAGE_URL = ("https://www.in.gov/idem/cleanwater/information-about/combined-sewer-overflow-cso-program/"
            "indiana-cso-outfall-map")
SAFE_FIELDS = ("OBJECTID", "Agency_Interest_ID", "City", "NPDES_Number", "CSO_Number", "Receiving_Stream",
               "waterbody_desc_2", "waterbody_desc_3", "waterbody_desc_4", "Status", "County", "Basin", "Sub_Basin",
               "Watershed", "Wastewater_Type", "X_Coordinate", "Y_Coordinate")
STATUS = {"active": "active (IDEM layer)",
          "active, discharge prohibited": "active, discharge prohibited (IDEM layer)",
          "inactive": "CLS (inactive in IDEM's layer)"}
HOUSE_NUMBER_REMOVED = "[house number removed]"
# a house number: 2 to 6 digits, not zero-led (an outfall or structure id: "009 Basin", "CS 009"), not after a route
# or structure word ("Highway 99", "Co Rd 99", "Alley 9-10"), before a street name (a direction, a capitalised word or
# a numbered street); distances ("900' North of") are not followed by a street word and stay
_HOUSE = re.compile(r"(?<![\w./&'#-])([1-9]\d{1,5}[A-Za-z]?)(?=\s+(?:[NSEW]\.?\s+)?(?:\d+(?:st|nd|rd|th)\b|[A-Z][a-z]))")
_ROUTE_BEFORE = re.compile(r"(?:\b(?:Highway|Hwy|Route|Rte|SR|US|U\.S\.|State Road|CR|Co\.? Rd\.?|County Road|Road|Rd|"
                           r"I|Interstate|Alley|Outfall|CSO|CS|Station|Manhole|MH|Lift Station|LS)\.?)\s*$", re.I)


def scrub_name(v: str | None) -> str | None:
    """IDEM's location text with a house number cut ("1234 S Example St" -> "[house number removed] S State St")."""
    if not v:
        return v

    def cut(m: re.Match) -> str:
        if _ROUTE_BEFORE.search(v[:m.start()]):
            return m.group(0)
        return HOUSE_NUMBER_REMOVED
    return " ".join(_HOUSE.sub(cut, v).split()) or None


CARRY_TIE_M = 500


def _metres(lat1, lon1, lat2, lon2) -> float | None:
    import math
    if None in (lat1, lon1, lat2, lon2):
        return None
    k = math.cos(math.radians((float(lat1) + float(lat2)) / 2))
    return math.hypot((float(lat1) - float(lat2)) * 111_195, (float(lon1) - float(lon2)) * 111_195 * k)


def _name_key(name) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower())
    for pat, rep in ((r"\bfk\b", "fork"), (r"\bw\b", "west"), (r"\be\b", "east"), (r"\bn\b", "north"),
                     (r"\bs\b", "south"), (r"\bcr\b", "creek"), (r"\br\b", "river"), (r"\bof the\b", " ")):
        s = re.sub(pat, rep, s)
    return " ".join(s.split())


def names_agree(row: dict, e: dict) -> bool:
    """IDEM's receiving stream is the very water EPA's tie names (its water_name, abbreviations aside): only then is
    EPA's tie carried (review 2026-11-14 P1-3: IDEM's Little River is not EPA's tie, the Wabash River)."""
    idem = _name_key(row.get("receiving_water_echo"))
    return bool(idem) and idem == _name_key(e.get("water_name"))


def sanitize(doc: dict) -> dict:
    """The layer's answer as it may be saved: the safe fields only, the house numbers in IDEM's location text cut and
    every point rounded to three decimals (review 2026-11-14 P1-5: nothing else reaches data/raw)."""
    feats = []
    for f in doc.get("features") or []:
        a = {k: v for k, v in (f.get("attributes") or {}).items() if k in SAFE_FIELDS}
        head, sep, rest = str(a.get("CSO_Number") or "").partition("--")
        if sep:
            a["CSO_Number"] = f"{head.strip()} -- {scrub_name(' '.join(rest.split())) or ''}".strip()
        elif a.get("CSO_Number") is not None:
            # no '--': the whole text is scrubbed, whether or not the row will become a record (re-review P1-2)
            a["CSO_Number"] = scrub_name(" ".join(str(a["CSO_Number"]).split()))
        for k in ("X_Coordinate", "Y_Coordinate"):
            if isinstance(a.get(k), (int, float)):
                a[k] = round(float(a[k]), 3)
        g = f.get("geometry") or {}
        g = {k: round(float(g[k]), 3) for k in ("x", "y") if g.get(k) is not None} or None
        feats.append({"attributes": a, "geometry": g})
    return {"features": feats}


def outfall_number(cso_number: str | None) -> str | None:
    """IDEM's CSO_Number as the permit's outfall number: '002C -- CSO - Town Lake' -> '002' (the C marks a CSO),
    '011CP -- CSO - ...' -> '011' (CP, a treated or partly treated CSO), '11AC' -> '11A', '004Z' -> '004Z',
    'A38' -> 'A38'; None when the text holds no number."""
    head = str(cso_number or "").split("--", 1)[0].strip().upper().replace(" ", "")
    for suffix in ("CP", "C"):
        if re.match(r"^\d+[A-Z]?" + suffix + "$", head):
            head = head[: -len(suffix)]
            break
    m = re.match(r"^(\d+)([A-Z]?)$", head)
    if m:
        return m.group(1).zfill(3) if not m.group(2) else m.group(1) + m.group(2)
    m = re.match(r"^([A-Z]\d+)$", head)
    return m.group(1) if m else None


def location_text(cso_number: str | None) -> str | None:
    """The text after '--' ('CSO - Town Lake - Inactive'), whitespace folded."""
    parts = str(cso_number or "").split("--", 1)
    return " ".join(parts[1].split()) if len(parts) == 2 and parts[1].strip() else None


def kind(attrs: dict) -> str:
    t = str(attrs.get("Wastewater_Type") or "").lower()
    return "cso" if "cso" in t else "other"


def _num_key(o) -> str:
    s = re.sub(r"\s+", "", str(o or "")).upper()
    return s.lstrip("0") or ("0" if s else "")


def _clean(v):
    s = " ".join(str(v or "").split())
    return s or None


def _point_corrections():
    """scripts/outfall_point_corrections.py (cited point corrections a rebuild must write again), loaded by path: this
    script runs with python -I, which keeps the scripts folder off sys.path."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("outfall_point_corrections",
                                                  Path(__file__).resolve().parent / "outfall_point_corrections.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build(doc: dict, epa_rows: list[dict], fetched_at: str) -> dict:
    epa = {(r["npdes_permit"], _num_key(r["outfall"])): r for r in epa_rows if r.get("state") == "IN"}
    rows, unpaired, no_number, no_point = [], [], [], []
    for f in doc.get("features") or []:
        a = {k: v for k, v in (f.get("attributes") or {}).items() if k in SAFE_FIELDS}
        g = f.get("geometry") or {}
        permit = _clean(a.get("NPDES_Number"))
        num = outfall_number(a.get("CSO_Number"))
        if not permit:
            continue
        has_point = g.get("x") is not None and g.get("y") is not None
        if not has_point:
            no_point.append({"npdes_permit": permit, "outfall": num, "idem_status": a.get("Status"),
                             "objectid": a.get("OBJECTID")})
        if not num:
            no_number.append({"npdes_permit": permit, "objectid": a.get("OBJECTID")})
            continue
        status_word = str(a.get("Status") or "").strip().lower()
        e = epa.get((permit, _num_key(num)))
        row = {"npdes_permit": permit,
               "permittee": (e or {}).get("permittee") or _clean(a.get("City")),
               "state": "IN", "city": (e or {}).get("city"), "outfall": num,
               "outfall_name": scrub_name(location_text(a.get("CSO_Number"))),
               "outfall_status": STATUS.get(status_word, f"{a.get('Status')} (IDEM layer)"),
               "idem_status": a.get("Status"),
               "feature_type": "EXO",
               "receiving_water_echo": _clean(a.get("Receiving_Stream")),
               "downstream_waters": [w for w in (_clean(a.get(k)) for k in ("waterbody_desc_2", "waterbody_desc_3",
                                                                            "waterbody_desc_4")) if w],
               "county": _clean(a.get("County")), "basin": _clean(a.get("Basin")),
               "sub_basin": _clean(a.get("Sub_Basin")), "watershed": _clean(a.get("Watershed")),
               "wastewater_type": _clean(a.get("Wastewater_Type")),
               "lat": round(float(g["y"]), 3) if has_point else None,
               "lon": round(float(g["x"]), 3) if has_point else None,
               "coords_from": "state outfall layer" if has_point else None, "outfall_kind": kind(a), "country": "US",
               "source": SOURCE_ID, "source_url": LAYER, "page_url": PAGE_URL,
               "source_record_id": a.get("OBJECTID"), "idem_agency_interest_id": a.get("Agency_Interest_ID"),
               "fetched_at": fetched_at}
        if row["outfall_kind"] == "other":
            row["kind_note"] = ("IDEM's layer types this point " + (f"'{a.get('Wastewater_Type')}'" if
                                a.get("Wastewater_Type") else "with no wastewater type")
                                + ", not a combined sewer outfall")
        if e:
            row.update(echo_url=e.get("echo_url"), permit_status=e.get("permit_status"), in_icis=e.get("in_icis"),
                       supersedes={"file": "data/outfalls-us.json", "npdes_permit": permit, "outfall": e["outfall"],
                                   "outfall_status": e.get("outfall_status"), "coords_from": e.get("coords_from"),
                                   "note": "EPA's national CSO inventory row; IDEM's layer gives the outfall's own "
                                           "point, receiving stream, downstream waters and IDEM's status"})
            if not has_point:
                # IDEM's status still decides (an Inactive row closes EPA's open one: review 2026-11-14 P1-4); the
                # point is EPA's only where EPA gives the outfall's own feature point, never the plant's
                if e.get("coords_from") == "permitted_feature" and e.get("lat") is not None:
                    row.update(lat=round(float(e["lat"]), 3), lon=round(float(e["lon"]), 3),
                               coords_from="EPA permitted feature (IDEM's layer gives no point)")
                else:
                    row["point_note"] = "neither IDEM's layer nor EPA's inventory gives this outfall's own point"
            d = _metres(row["lat"], row["lon"], e.get("lat"), e.get("lon"))
            if e.get("water_slug") and d is not None and d <= CARRY_TIE_M and names_agree(row, e):
                row.update(water_slug=e["water_slug"], water_name=e.get("water_name"), water_kind=e.get("water_kind"),
                           match="carried from EPA's row",
                           water_match=(f"EPA's tie for this outfall (data/outfalls-us.json, {e.get('match')}), carried: "
                                        f"IDEM's point lies {d:.0f} m from EPA's and IDEM's receiving stream is the "
                                        "water EPA's row names; the water batch ties IDEM's point"))
        else:
            unpaired.append({"npdes_permit": permit, "outfall": num, "idem_status": a.get("Status")})
        rows.append(row)
    seen = {(r["npdes_permit"], _num_key(r["outfall"])) for r in rows}
    # EPA's open outfalls that IDEM's layer lacks and that EPA places only at the plant: a row with no point, so the
    # registry never puts their caution or reports at the plant (review 2026-11-14 P1-4)
    for (p, n), e in sorted(epa.items()):
        if (p, n) in seen or str(e.get("outfall_status") or "").upper().startswith("CLS") or e.get("coords_from") != "facility":
            continue
        rows.append({"npdes_permit": p, "permittee": e.get("permittee"), "state": "IN", "city": e.get("city"),
                     "outfall": e["outfall"], "outfall_name": e.get("outfall_name"),
                     "outfall_status": e.get("outfall_status"), "feature_type": e.get("feature_type") or "EXO",
                     "receiving_water_echo": e.get("receiving_water_echo"), "lat": None, "lon": None,
                     "coords_from": None, "outfall_kind": "cso", "country": "US",
                     "source": "fed-echo-national-cso-inventory", "echo_url": e.get("echo_url"),
                     "point_note": "EPA's inventory gives only the treatment plant's point; IDEM's layer lists no point",
                     "supersedes": {"file": "data/outfalls-us.json", "npdes_permit": p, "outfall": e["outfall"],
                                    "coords_from": "facility", "note": "the same row without the plant's point"}})
    # the outfalls IDEM lists without a point that EPA's ICIS places, and the true reason where no source does
    # (scripts/outfall_point_corrections.py, 2026-11-15)
    _point_corrections().for_builder(OUT.name, rows)
    rows.sort(key=lambda r: (r["npdes_permit"], r["outfall"], r["lat"] is None))
    epa_missing = [{"npdes_permit": p, "outfall": e["outfall"], "outfall_status": e.get("outfall_status"),
                    "reason": "open in EPA's CSO inventory but not in IDEM's CSO outfall layer; EPA's row is kept"}
                   for (p, n), e in sorted(epa.items())
                   if (p, n) not in seen and not str(e.get("outfall_status") or "").upper().startswith("CLS")]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("idem_status") or "EPA only"] = counts.get(r.get("idem_status") or "EPA only", 0) + 1
    return {"source": (f"IDEM Indiana CSO Outfall Map, hosted layer {LAYER}, fetched {fetched_at}; EPA's rows for the "
                       "same permit and outfall (data/outfalls-us.json) are kept and named in supersedes"),
            "rule": ("one row per point of IDEM's layer with an outfall number; IDEM's point, receiving stream, "
                     "downstream waters and status; Inactive written CLS (closed), the other statuses open"),
            "generated": datetime.now(UTC).date().isoformat(), "count": len(rows),
            "permits": len({r["npdes_permit"] for r in rows}), "by_idem_status": dict(sorted(counts.items())),
            "paired_with_epa": len(rows) - len(unpaired), "unpaired": unpaired, "no_outfall_number": no_number,
            "no_point": no_point,
            "epa_not_in_state_layer": epa_missing, "outfalls": rows}


def fetch() -> Path:
    import requests
    sys.path.insert(0, str(ROOT / "pipeline"))
    from common import HEADERS
    params = {"where": "1=1", "outFields": ",".join(SAFE_FIELDS), "returnGeometry": "true", "outSR": "4326",
              "orderByFields": "OBJECTID", "resultRecordCount": "2000", "f": "json"}
    r = requests.get(LAYER + "/query", params=params, headers=HEADERS, timeout=300)
    r.raise_for_status()
    doc = r.json()
    if doc.get("error") or doc.get("exceededTransferLimit"):
        # a category, never the answer's own text (re-review 2026-11-14 P1-2)
        code = (doc.get("error") or {}).get("code") if isinstance(doc.get("error"), dict) else None
        raise SystemExit("IDEM's layer answered " + (f"an error (code {int(code)})" if isinstance(code, int) else
                                                     "an error" if doc.get("error") else "more than one page"))
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps(sanitize(doc)))
    return RAW


def main(argv) -> int:
    path = fetch() if "--fetch" in argv else Path(argv[1]) if len(argv) > 1 else RAW
    doc = json.loads(Path(path).read_text())
    fetched = datetime.fromtimestamp(Path(path).stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    epa_rows = json.loads((ROOT / "data" / "outfalls-us.json").read_text())["outfalls"]
    out = build(doc, epa_rows, fetched)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{out['count']} IDEM outfalls on {out['permits']} permits ({out['paired_with_epa']} paired with EPA's rows; "
          f"{out['by_idem_status']}) -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
