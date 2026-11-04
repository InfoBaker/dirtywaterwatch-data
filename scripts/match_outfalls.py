"""Match CSO outfalls (EPA ECHO national CSO inventory CSV) to openboatlaunch water bodies.

Usage: pipeline/.venv/bin/python -I scripts/match_outfalls.py <ALL_CSO_DOWNLOADS.csv> <openboatlaunch out/water dir> <out json> [--append] [--national]
       pipeline/.venv/bin/python -I scripts/match_outfalls.py data/outfalls-plants-us.json ../openboatlaunch/out/water data/outfalls-plants-us.json --plants
(shapely and numpy are needed; the national file: ... research/federal/raw/cso_inventory/ALL_CSO_DOWNLOADS.csv ../openboatlaunch/out/water data/outfalls-us.json --national)
Writes one row per outfall with coordinates in the states of DWW_STATES (comma-separated; default
the New England pilot MA,CT,RI,NH,VT,ME; data/outfalls-mid-atlantic.json was made with NJ,NY,PA,
its VA rows with VA and its MD rows with MD, appended; the two MD0067407 points ECHO places in Prince
George's County were un-matched by hand): permit, outfall number, name, receiving
water as ECHO names it, lat/lon, the nearest openboatlaunch water within 400 m (slug, name, kind,
distance in m) and up to three alternatives, plus a `match` verdict: 'geometry+name' when the
nearest water's name shares a distinctive word with ECHO's receiving water, 'geometry' when only
the distance says so, 'name_only' when no water is within range but a same-named one exists in the
state, 'none' otherwise. Nothing here is a judgement about where a discharge goes; it only says
which water record the outfall sits on. "Run" is a generic word like "Brook", and a name-only match
needs the generic words to agree (added for Virginia: "Hooff Run" and "Stoney Run" must not land on
"Mill Run", nor "Hunting Creek" on "Hunting Run Reservoir").

Washington DC (DWW_STATES=DC; DC Water's 56 DC0021199 rows): openboatlaunch has no DC waters, so the
candidate waters are the records of data/waters-dc.json (ingest/dc_waters.py: NHD flowlines cut to
the District, slugs <name>-dc); they are used only for state DC. OVERRIDES corrects the receiving water
where ECHO's own fields disagree with the permit: CSO 019 carries PF_STATE_AUTO_NAME "Potomac River"
but is on the Anacostia (below); the corrected water is written as `receiving_water_override` with its
basis and is what the match uses. NOTES keeps a conflict that is not an override. A 4th argument
`--append` replaces the rows of the selected states in an existing <out json> and keeps the others
(how DC was added to data/outfalls-mid-atlantic.json without rerunning NJ, NY, PA, MD and VA).

After this script, run `cd pipeline && python -m ingest.outfall_waters` (2026-11-03): it gives the outfalls this
script leaves without a water the record of their receiving water (NHD, OSM, hand records), redoes the name-only
matches here that name another water (words() drops kind words, so 'Onondaga Creek' matched Onondaga Lake), and adds
water_match, water_matched_by, no_water_reason, replaced_match and coords_problem. A rerun of this script rewrites
the rows from EPA's file and drops those fields until that pass runs again.

National registry (2026-11-03, `--national`; data/outfalls-us.json): every state and territory in the inventory
outside the 12 live ones (REGIONAL_STATES, read from the regional files: the New England six in data/outfalls-ne.json and
NJ, NY, PA, MD, VA, DC in data/outfalls-mid-atlantic.json, which this mode never writes); DWW_STATES, when set, narrows the list (with
--append, to rewrite only those states' rows). The 12 live states' files are not made by this mode and its changes
below do not apply to them. Same row schema, plus on every row:
  outfall_kind  "cso" (EPA's CSO inventory lists CSO outfalls only; plant outfalls are another file) and country "US";
  coords_from   "permitted_feature" (the inventory's own point for the outfall, PF_LAT/PF_LON) or "facility" (PF_LAT is
                empty and the facility's point, FACILITY_LAT/LON, is used: a point for the treatment plant or the
                permittee's address, NOT the outfall's own point; the row says so in coords_note, and no water is
                matched by distance to it, only by name); null when the row has no point. coords_note also says when the
                outfall's point is the same as the facility's (EPA often gives a plant's outfalls the plant's point), and
                point_shared_by counts the permit's outfalls that share one point (one point per permit);
  coords_problem  a point more than 2 km outside the state's Census outline (cb_2023_us_state_500k, the file
                waters_from_nhd reads, from openboatlaunch/data/raw; DWW_STATES_ZIP overrides) cannot be this outfall's: it
                is moved to echo_lat/echo_lon (echo_coords_from says which point it was), lat/lon are null and the text
                says why, with a hint when the longitude's sign or lat/lon order would put it inside the state; the
                same convention as the Mid-Atlantic pass (ingest.outfall_waters). A point far from its named water is NOT
                flagged here: openboatlaunch maps few rivers and creeks (and only part of some), so distance to a record
                is no evidence the point is wrong; a same-named water more than 10 km away is simply not matched;
  receiving_water_source  "state" (the state's own text, PF_STATE_WATERBODY_NAME), "auto" (only EPA's HUC-12 watershed
                name PF_STATE_AUTO_NAME, 'Bullerman Ditch-Maumee River': used for the geometry match, never for a
                name-only match) or null;
  water_match, water_matched_by ("scripts/match_outfalls.py (2026-11-03)") and, for a row with no water, no_water_reason:
                written here in the wording ingest.outfall_waters gives a match_outfalls row, so the site can say how a water
                was found or why none was.
One row per (permit, outfall): the inventory repeats an outfall once per ICIS permit version (184 extra rows, all with
IN_ICIS 'NO', mostly Indiana); the IN_ICIS 'YES' row is kept and `source_rows` says how many rows the inventory had. Two rows are not outfalls and are
dropped (PERM_FEATURE_TYPE_CODE SUM: CA0079111's mercury mass-emission summary; INF: IN0032476 030, an influent point).
Other differences from the older files (all stricter but the exact-name rule): name words and kind words also drop
bayou, slough, fork, ditch, drain, channel, tributary/trib/unnamed, via/from; 'geometry+name' needs the kinds to agree
and no opposite compass words ('Rock Creek' is not 'Rock River', 'North Branch' is not 'South Branch': 'geometry'
only); a name-only match needs the record's name inside the receiving water's text, or the text inside the record's
name, as whole words after R/CR/CK/FK expansion (build/status.py's test: 'Suburban Chicago Areas' is not 'North Branch
Chicago River', 'Grand Calumet River' is not 'Little Calumet River'); a name that is exactly the receiving water's counts
as named even when every word is generic ('Mill Creek'); a name-only match to a record more than 10 km from the point is
refused (the one record of that name is another creek of that name: 'Sugar Creek' in Illinois). Alaska and Puerto Rico
have no MRMS radar (noted only). openboatlaunch has no Puerto Rico waters: those rows get no match. A run prints, to
stderr, the totals and how many matches each strict rule refused.

Plant outfalls (`--plants`, 2026-11-03; data/outfalls-plants-us.json, research/federal/plant-outfalls.md): the first
argument is the plants registry file instead of the CSV and the output is that same file (written atomically). The
rows of the live states (DWW_STATES narrows the list) are matched with the national rules above (the same code, no
second copy of it) and only the match fields are written onto them: water_slug, water_name, water_kind, distance_m,
match, water_match, water_matched_by and, for a row with no water, no_water_reason; every other row and field stays as
it was, and a rerun starts from the match fields again (a row ingest.outfall_waters --plants matched is matched again
by this pass first, as for the CSO rows). A plant row carries the reach EPA's catchment index gives its point
(reach_id, reach_gnis_name, the NHDPlus GNIS name): a water record counts as 'geometry+name' when its name shares a
word with the permit's receiving water OR with that reach name, and water_match says which reach the point is on.
A row whose point is the facility's (coords_from 'facility') is matched by name only, as the CSO rows are; a row with
no usable point (coords_problem) by name only. The rows' own points are not re-checked against the state outline (the
file's build did, and moved a bad point to echo_lat/echo_lon). The step after this one is
`cd pipeline && python -m ingest.outfall_waters --plants`.
"""
import csv, json, sys, re, glob, math, struct, zipfile
from collections import Counter, defaultdict
from shapely.geometry import shape, Point, Polygon, LinearRing
from shapely.strtree import STRtree
from shapely.ops import nearest_points, unary_union
from shapely.prepared import prep

import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = sys.argv[4:]
PLANTS = "--plants" in ARGS          # data/outfalls-plants-us.json: the national rules, the live states' plant rows
NATIONAL = "--national" in ARGS or PLANTS
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from common import live_states as _live_states  # noqa: E402
# the live states: data/rules.json live_states, the site's one list (common.live_states); --plants matches their rows
LIVE_STATES = set(_live_states())
# the states the regional registry files hold (data/outfalls-ne.json, data/outfalls-mid-atlantic.json, read from them):
# --national leaves them out of data/outfalls-us.json; a state going live keeps its national rows
REGIONAL_STATES = {str(r.get("state") or r["npdes_permit"][:2]).upper()
                   for n in ("outfalls-ne.json", "outfalls-mid-atlantic.json")
                   for r in json.load(open(os.path.join(ROOT, "data", n)))["outfalls"]}
NE = set((os.environ.get("DWW_STATES") or "MA,CT,RI,NH,VT,ME").split(","))
if PLANTS:
    NE = set(os.environ["DWW_STATES"].split(",")) if os.environ.get("DWW_STATES") else set(LIVE_STATES)
STOP = {"river", "lake", "pond", "brook", "bay", "harbor", "harbour", "cove", "creek", "stream",
        "reservoir", "the", "of", "and", "at", "to", "canal", "sound", "inlet", "north", "south",
        "east", "west", "branch", "little", "big", "upper", "lower", "outlet", "mill", "run"}
KIND_WORDS = {"river", "lake", "pond", "brook", "bay", "harbor", "harbour", "cove", "creek", "stream", "reservoir",
              "canal", "sound", "inlet", "run", "branch", "outlet"}
if NATIONAL:
    STOP |= {"bayou", "slough", "fork", "ditch", "drain", "channel", "tributary", "trib", "unnamed", "via", "from"}
    KIND_WORDS |= {"bayou", "slough", "fork", "ditch", "drain", "channel"}
NATIONAL_BY = "scripts/match_outfalls.py (2026-11-03)"
OUTSIDE_STATE_M = 2_000        # a point this far outside its state's Census outline is not the outfall's
NAME_ONLY_MAX_M = 10_000       # a name-only match to a record farther than this from the point is refused


def words(s):
    return {w for w in re.findall(r"[a-z]+", (s or "").lower()) if w not in STOP and len(w) > 2}

# (permit, outfall) -> (water, basis). Applied after the row is read; the ECHO text stays in the row.
OVERRIDES = {
    ("DC0021199", "019"): (
        "Anacostia River",
        "ECHO's PF_STATE_AUTO_NAME says 'Potomac River' (research/dc/report.md section 2.2: CSO 019 is mis-tagged), "
        "but its PF_STATE_WATERBODY_NAME says 'Anacostia River, West Side', the NPDES permit's outfall table lists "
        "019 ('N.E. Boundary Trunk, Vic. of 25th and E Sts., SE') on the Anacostia River, West Side, the outfall point "
        "(38.8853, -76.9719) is on the Anacostia, and DC Water's reports call it the Anacostia River Tunnel overflow"),
}
# Conflicts kept as a note, not overridden (decision: both statements stay on the record).
NOTES = {
    ("DC0021199", "024"): (
        "A 2025-12-01 sewer overflow report (DWO AT CSO 024) typed the receiving water 'ROCK CREEK'; the ECHO inventory "
        "(PF_STATE_WATERBODY_NAME 'Potomac River, East Side'), the NPDES permit's outfall table (30th and K Streets, NW, "
        "in its Potomac River, East Side group) and DC Water's Q2 2026 CSO report all put CSO 024 on the Potomac River, "
        "so the outfall stays on the Potomac (research/dc/report.md section 4, contradiction 4)"),
}
EXTRA_WATER_FILES = {"DC": os.path.join(ROOT, "data", "waters-dc.json")}   # records with inline geometry
STATES_ZIP = os.environ.get("DWW_STATES_ZIP") or os.path.join(os.path.dirname(ROOT), "openboatlaunch", "data", "raw",
                                                              "cb_2023_us_state_500k.zip")


def same_kind(a, b):
    """'Hunting Creek' is not 'Hunting Run Reservoir': for a name-only match the generic words must
    overlap when both names have one."""
    if NATIONAL:       # 'Tippecanoe R (Lake Freeman)' has a river in it: R is river, CR and CK are creek
        a, b = norm_name(a), norm_name(b)
    ka = {w for w in re.findall(r"[a-z]+", (a or "").lower()) if w in KIND_WORDS}
    kb = {w for w in re.findall(r"[a-z]+", (b or "").lower()) if w in KIND_WORDS}
    return not ka or not kb or bool(ka & kb)


ABBREV = {"r": "river", "riv": "river", "bk": "brook", "brk": "brook", "hbr": "harbor", "harbour": "harbor", "pd": "pond",
          "lk": "lake", "chan": "channel", "ck": "creek", "cr": "creek", "crk": "creek", "st": "saint", "mt": "mount",
          "fk": "fork"}
COMPASS = {"north": "north", "n": "north", "no": "north", "south": "south", "s": "south", "so": "south",
           "east": "east", "e": "east", "west": "west", "w": "west"}


def norm_name(s):
    """Lower-case words with ECHO's usual abbreviations spelled out ('MILL CR' -> 'mill creek'), as build/status.py's
    norm_name does (plus fork and crk)."""
    s = re.sub(r"[^a-z0-9 ]", " ", str(s or "").lower().replace("'", ""))
    return " ".join(ABBREV.get(t, t) for t in s.split())


def names_contain(text, wname):
    """build/status.py's test for a name-only match: the record's name inside the receiving water's text or the text
    inside the record's name, as whole words ('Suburban Chicago Areas' is not 'North Branch Chicago River'; 'Grand
    Calumet River' is not 'Little Calumet River')."""
    a, b = norm_name(text), norm_name(wname)
    return bool(a and b) and (f" {b} " in f" {a} " or f" {a} " in f" {b} ")


def opposite_compass(a, b):
    ca = {COMPASS[w] for w in norm_name(a).split() if w in COMPASS}
    cb = {COMPASS[w] for w in norm_name(b).split() if w in COMPASS}
    return bool(ca and cb and not ca & cb)


def m_per_deg(lat):
    return 111_320.0, 111_320.0 * math.cos(math.radians(lat))


def read_state_outlines(codes):
    """Census cartographic state outlines (cb_2023_us_state_500k.zip), as ingest.waters_from_nhd reads them: shapefile
    polygons (outer rings clockwise, holes counter-clockwise) and the dbf's STUSPS."""
    z = zipfile.ZipFile(STATES_ZIP)
    stem = "cb_2023_us_state_500k"
    shp, dbf = z.read(f"{stem}.shp"), z.read(f"{stem}.dbf")
    nrec = struct.unpack("<I", dbf[4:8])[0]
    hlen, rlen = struct.unpack("<HH", dbf[8:12])
    fields, pos = [], 32
    while dbf[pos] != 0x0D:
        fields.append((dbf[pos:pos + 11].split(b"\0")[0].decode(), dbf[pos + 16]))
        pos += 32
    codes_by_rec = []
    for i in range(nrec):
        off, vals = hlen + i * rlen + 1, {}
        for name, flen in fields:
            vals[name] = dbf[off:off + flen].decode("latin-1").strip()
            off += flen
        codes_by_rec.append(vals.get("STUSPS"))
    import numpy as np
    out, pos, i = {}, 100, 0
    while pos + 8 <= len(shp):
        _, clen = struct.unpack(">ii", shp[pos:pos + 8])
        content = shp[pos + 8:pos + 8 + clen * 2]
        pos += 8 + clen * 2
        code = codes_by_rec[i]
        i += 1
        if code not in codes or struct.unpack("<i", content[:4])[0] != 5:
            continue
        nparts, npts = struct.unpack("<ii", content[36:44])
        parts = list(struct.unpack(f"<{nparts}i", content[44:44 + 4 * nparts])) + [npts]
        pts = np.frombuffer(content[44 + 4 * nparts:44 + 4 * nparts + 16 * npts], dtype="<f8").reshape(-1, 2)
        outers, holes = [], []
        for a, b in zip(parts, parts[1:]):
            ring = pts[a:b]
            if len(ring) < 4:
                continue
            (holes if LinearRing(ring).is_ccw else outers).append(Polygon(ring))
        g = unary_union(outers)
        if holes:
            g = g.difference(unary_union(holes))
        out[code] = g.buffer(0)
    return out


csv_path, water_dir, out_path = sys.argv[1:4]
PLANT_DOC = None
if PLANTS:
    # the plants registry's live-state rows, read as the inventory's rows (one pseudo-CSV row each; the point is the
    # feature's own or the facility's, as coords_from says; a row with its point moved aside has none)
    PLANT_DOC = json.load(open(csv_path))
    csv_rows = []
    for i, p in enumerate(PLANT_DOC["outfalls"]):
        if p["state"] not in NE or p.get("outfall_kind", "plant") != "plant":
            continue
        own = p.get("coords_from") == "permitted_feature"
        fac = p.get("coords_from") == "facility"
        csv_rows.append({
            "NPDES_ID": p["npdes_permit"], "FACILITY_NAME": p.get("permittee"), "STATE_CODE": p["state"],
            "FACILITY_CITY": p.get("city"), "PERM_FEATURE_NMBR": p.get("outfall") or "",
            "PERM_FEATURE_TEXT": p.get("outfall_name"), "PF_CHARACTER": p.get("outfall_status"),
            "PERM_FEATURE_TYPE_CODE": p.get("feature_type") or "",
            "PF_STATE_WATERBODY_NAME": p.get("receiving_water_echo") or "", "PF_STATE_AUTO_NAME": "",
            "PF_REACH_ID": p.get("reach_id") or "", "IN_ICIS": p.get("in_icis"), "PERMIT_STATUS_CODE": p.get("permit_status"),
            "ECHO_DFR_LINK": p.get("echo_url"),
            "PF_LAT": p["lat"] if own and p.get("lat") is not None else "", "PF_LON": p["lon"] if own and p.get("lon") is not None else "",
            "FACILITY_LAT": p["lat"] if fac and p.get("lat") is not None else "",
            "FACILITY_LON": p["lon"] if fac and p.get("lon") is not None else "",
            "_plant_index": i, "_gnis": p.get("reach_gnis_name") or ""})
else:
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        csv_rows = list(csv.DictReader(fh))

if PLANTS:
    STATE_SHAPES, STATE_PREP = {}, {}      # the file's own build screened the points against the state outlines
    print("states", sorted(NE), file=sys.stderr)
elif NATIONAL:
    present = {r["STATE_CODE"] for r in csv_rows} - REGIONAL_STATES
    wanted = set(os.environ["DWW_STATES"].split(",")) if os.environ.get("DWW_STATES") else present
    if wanted & REGIONAL_STATES:
        print("not national: the regional files' states left out:", sorted(wanted & REGIONAL_STATES), file=sys.stderr)
    NE = present & wanted
    STATE_SHAPES = read_state_outlines(NE)
    STATE_PREP = {k: prep(v) for k, v in STATE_SHAPES.items()}
    print("states", sorted(NE), file=sys.stderr)

waters, geoms = [], []


def add_water(d, st):
    if d.get("state") != st or not d.get("geometry"):
        return
    try:
        g = shape(d["geometry"])
    except Exception:
        return
    waters.append({"slug": d["slug"], "name": d["name"], "kind": d.get("kind"), "state": st,
                   "launches": [l["s"] if isinstance(l, dict) else l for l in d.get("launches") or []]})
    geoms.append(g)


for st in sorted(NE):
    # <slug>-<st>.json, and the duplicate-name records <slug>-<st>-2.json (none for the 12 live states)
    main_files = glob.glob(f"{water_dir}/*-{st.lower()}.json")
    for f in (sorted(main_files) if NATIONAL else main_files) + sorted(glob.glob(f"{water_dir}/*-{st.lower()}-[0-9]*.json")):
        add_water(json.load(open(f)), st)
    if st in EXTRA_WATER_FILES and os.path.exists(EXTRA_WATER_FILES[st]):
        for d in json.load(open(EXTRA_WATER_FILES[st])).get("waters", []):
            add_water(d, st)
tree = STRtree(geoms) if geoms else None
print(f"{len(waters)} waters with geometry", file=sys.stderr)
waters_in = Counter(w["state"] for w in waters)


def num(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def pick_records(recs):
    """National mode: one record per (permit, outfall): the IN_ICIS 'YES' one (the current ICIS record), then the one
    with a point, then the one with a receiving-water text."""
    by = defaultdict(list)
    for r in recs:
        by[(r["NPDES_ID"], r["PERM_FEATURE_NMBR"])].append(r)
    out = []
    for k, rs in by.items():
        rs.sort(key=lambda r: (r["IN_ICIS"] == "YES", bool(r["PF_LAT"]), bool(r["PF_STATE_WATERBODY_NAME"] or r["PF_STATE_AUTO_NAME"])),
                reverse=True)
        if rs[0]["PERM_FEATURE_TYPE_CODE"] in ("SUM", "INF"):     # a summary row, an influent point: not an outfall
            STATS["dropped: not an outfall (SUM or INF feature)"] += 1
            continue
        out.append((rs[0], len(rs)))
    return out


def outside_state(st, lat, lon):
    """None when the point is within OUTSIDE_STATE_M of the state's outline, else the text saying why not."""
    shp = STATE_SHAPES.get(st)
    if shp is None:
        return None
    p = Point(lon, lat)
    if STATE_PREP[st].contains(p):
        return None
    my, mx = m_per_deg(lat)
    q = nearest_points(shp, p)[0]
    d = math.hypot((q.x - p.x) * mx, (q.y - p.y) * my)
    if d <= OUTSIDE_STATE_M:
        return None
    hint = ""
    if STATE_PREP[st].contains(Point(-lon, lat)):
        hint = "; with the longitude's sign reversed the point would lie inside the state"
    elif -180 <= lat <= 180 and -90 <= lon <= 90 and STATE_PREP[st].contains(Point(lat, lon)):
        hint = "; with latitude and longitude swapped the point would lie inside the state"
    return f"{d / 1000:.1f} km outside {st}'s outline{hint}"


STATS = Counter()
rows = []
sel = [(r, 1) for r in csv_rows] if PLANTS else \
    pick_records([r for r in csv_rows if r["STATE_CODE"] in NE]) if NATIONAL else \
    [(r, 1) for r in csv_rows if r["STATE_CODE"] in NE]
for r, n_src in sel:
    lat, lon = r.get("PF_LAT"), r.get("PF_LON")
    coords_from = "permitted_feature" if (lat and lon) else None
    if NATIONAL and not coords_from and r.get("FACILITY_LAT") and r.get("FACILITY_LON"):
        lat, lon, coords_from = r["FACILITY_LAT"], r["FACILITY_LON"], "facility"
    row = {
        "npdes_permit": r["NPDES_ID"], "permittee": r["FACILITY_NAME"], "state": r["STATE_CODE"],
        "city": r["FACILITY_CITY"], "outfall": r["PERM_FEATURE_NMBR"], "outfall_name": r["PERM_FEATURE_TEXT"],
        "outfall_status": r["PF_CHARACTER"], "feature_type": r["PERM_FEATURE_TYPE_CODE"],
        "receiving_water_echo": r["PF_STATE_WATERBODY_NAME"] or r["PF_STATE_AUTO_NAME"] or None,
        "reach_id": r["PF_REACH_ID"] or None, "in_icis": r["IN_ICIS"],
        "permit_status": r["PERMIT_STATUS_CODE"], "echo_url": r["ECHO_DFR_LINK"],
        "lat": float(lat) if lat else None, "lon": float(lon) if lon else None,
        "water_slug": None, "water_name": None, "water_kind": None, "distance_m": None,
        "alternatives": [], "match": "none",
    }
    if NATIONAL:
        row.update(outfall_kind="cso", country="US", coords_from=coords_from,
                   receiving_water_source="state" if r["PF_STATE_WATERBODY_NAME"] else
                   "auto" if r["PF_STATE_AUTO_NAME"] else None)
        if n_src > 1:
            row["source_rows"] = n_src
        if coords_from == "facility":
            row["coords_note"] = ("EPA's inventory gives no point for this outfall; lat/lon are the facility's point "
                                  "(the treatment plant or the permittee's address), not the outfall's own")
        elif coords_from and num(r.get("FACILITY_LAT")) is not None and num(r.get("FACILITY_LON")) is not None \
                and abs(row["lat"] - num(r["FACILITY_LAT"])) < 1e-4 and abs(row["lon"] - num(r["FACILITY_LON"])) < 1e-4:
            row["coords_note"] = "EPA's point for this outfall is the same as the facility's point"
        if row["lat"] is not None and not PLANTS:
            why = outside_state(row["state"], row["lat"], row["lon"])
            if why:
                src = ("EPA's permitted-feature point" if coords_from == "permitted_feature" else "the facility's point")
                row["echo_lat"], row["echo_lon"], row["echo_coords_from"] = row["lat"], row["lon"], coords_from
                row["lat"] = row["lon"] = None
                row["coords_from"] = None
                row["coords_problem"] = (f"{src} ({row['echo_lat']}, {row['echo_lon']}) is {why}; it cannot be this "
                                         f"outfall's (a mistyped coordinate or another place's point)")
                row.pop("coords_note", None)
    key = (row["npdes_permit"], row["outfall"])
    if key in OVERRIDES:
        row["receiving_water_override"] = {"water": OVERRIDES[key][0], "basis": OVERRIDES[key][1],
                                           "echo_state_name": r["PF_STATE_WATERBODY_NAME"] or None,
                                           "echo_auto_name": r["PF_STATE_AUTO_NAME"] or None}
    if key in NOTES:
        row["receiving_water_note"] = NOTES[key]
    override = (row.get("receiving_water_override") or {}).get("water")
    rtext = override or row["receiving_water_echo"]
    kind_note = None
    geo_refused = None
    # a facility's point is not the outfall's: no match by distance to it
    if row["lat"] is not None and row["lon"] is not None and row.get("coords_from") != "facility":
        p = Point(row["lon"], row["lat"])
        my, mx = m_per_deg(row["lat"])
        deg = 400 / my
        cands = []
        for i in (tree.query(p.buffer(deg)) if tree is not None else []):
            g = geoms[i]; w = waters[i]
            if w["state"] != row["state"]:
                continue
            try:
                q = nearest_points(g, p)[0]
            except Exception:
                continue
            d_m = math.hypot((q.x - p.x) * mx, (q.y - p.y) * my)
            if d_m <= 400:
                cands.append((d_m, w))
        cands.sort(key=lambda c: c[0])
        rw = words(rtext)
        if PLANTS:
            # the permit's receiving water, or the name of the NHDPlus reach EPA's catchment index puts the point on
            gnis = r.get("_gnis") or None
            texts = [t for t in (rtext, gnis) if t]

            def shares(w, t):
                return bool(words(w["name"]) & words(t) or norm_name(w["name"]) == norm_name(t))
            shared = [c for c in cands if any(shares(c[1], t) for t in texts)]
            named = [c for c in shared if any(shares(c[1], t) and same_kind(c[1]["name"], t)
                                              and not opposite_compass(c[1]["name"], t) for t in texts)]
            if shared and not named:
                STATS["geometry+name refused: kind or compass differs"] += 1
                kind_note = (f"the nearest water's name ('{shared[0][1]['name']}') shares a word with the receiving water "
                             f"or reach name ('{' / '.join(texts)}') but not its kind of water or its compass word")
        elif NATIONAL:
            shared = [c for c in cands if words(c[1]["name"]) & rw or (rtext and norm_name(c[1]["name"]) == norm_name(rtext))]
            named = [c for c in shared if same_kind(c[1]["name"], rtext) and not opposite_compass(c[1]["name"], rtext)]
            if shared and not named:
                STATS["geometry+name refused: kind or compass differs"] += 1
                kind_note = (f"the nearest water's name ('{shared[0][1]['name']}') shares a word with the receiving water "
                             f"('{rtext}') but not its kind of water or its compass word")
        else:
            named = [c for c in cands if words(c[1]["name"]) & rw]
        if PLANTS and cands and not named and (words(rtext) or words(r.get("_gnis"))):
            # a plant's permit and reach both name a water: a record within 400 m that shares neither name is not that
            # water (Buffalo Creek's plant on the Susquehanna River's record 270 m away); the name steps decide
            geo_refused = cands[0]
            STATS["geometry refused: the receiving water and the reach name another water"] += 1
        best = named[0] if named else (None if geo_refused else (cands[0] if cands else None))
        if best:
            d_m, w = best
            row.update(water_slug=w["slug"], water_name=w["name"], water_kind=w["kind"],
                       distance_m=round(d_m), match="geometry+name" if named else "geometry")
            row["alternatives"] = [{"slug": c[1]["slug"], "name": c[1]["name"], "distance_m": round(c[0])}
                                   for c in cands if c[1]["slug"] != w["slug"]][:3]
    too_far = None
    if row["match"] == "none" and rtext and not (NATIONAL and row.get("receiving_water_source") == "auto" and not override):
        rw = words(rtext)
        same = [w for w in waters if w["state"] == row["state"] and words(w["name"]) & rw and words(w["name"]) <= rw | {"connecticut"}
                and same_kind(w["name"], row["receiving_water_echo"])]
        if NATIONAL:       # a name that is the receiving water's exactly counts even when every word is generic
            same += [w for w in waters if w["state"] == row["state"] and w not in same and norm_name(w["name"]) == norm_name(rtext)]
            kept = [w for w in same if names_contain(rtext, w["name"])]
            if len(kept) != len(same):
                STATS["name-only candidates refused: the record's name is not in the text"] += len(same) - len(kept)
            same = kept
        if len(same) == 1:
            d_km = None
            if NATIONAL and row["lat"] is not None:
                g = geoms[waters.index(same[0])]
                q = nearest_points(g, Point(row["lon"], row["lat"]))[0]
                my, mx = m_per_deg(row["lat"])
                d_km = math.hypot((q.x - row["lon"]) * mx, (q.y - row["lat"]) * my) / 1000
            if d_km is not None and d_km * 1000 > NAME_ONLY_MAX_M:
                STATS["name-only refused: the one record of that name is >10 km from the point"] += 1
                too_far = (same[0], d_km)
                row["alternatives"] = [{"slug": same[0]["slug"], "name": same[0]["name"], "distance_m": round(d_km * 1000)}]
            else:
                row.update(water_slug=same[0]["slug"], water_name=same[0]["name"], water_kind=same[0]["kind"], match="name_only")
                if d_km is not None and not (PLANTS and row.get("coords_from") == "facility"):
                    row["distance_m"] = round(d_km * 1000)      # (a plant's facility point: no distance is the outfall's)
        elif same:
            row["alternatives"] = [{"slug": w["slug"], "name": w["name"]} for w in same[:5]]
    if NATIONAL:
        text = rtext or "none given"
        d, nm, sl = row.get("distance_m"), row.get("water_name"), row.get("water_slug")
        if row["match"] == "geometry+name":
            row["water_match"] = (f"EPA's point lies {d} m from {nm} ({sl}), whose name shares a word with the receiving "
                                  f"water ('{text}'); openboatlaunch record, scripts/match_outfalls.py")
        elif row["match"] == "geometry":
            row["water_match"] = (f"EPA's point lies {d} m from {nm} ({sl}), the nearest openboatlaunch water within 400 m; "
                                  f"the receiving water ('{text}') does not share its name"
                                  + (f" ({kind_note})" if kind_note else "") + "; scripts/match_outfalls.py")
        elif row["match"] == "name_only":
            row["water_match"] = (f"no openboatlaunch water within 400 m of EPA's point; {nm} ({sl}) is the only water of "
                                  f"the receiving water's name ('{text}') in the state"
                                  + (f", {d / 1000:.1f} km from the point" if d is not None else "") + "; scripts/match_outfalls.py")
        else:
            bits = []
            if not rtext:
                bits.append("no receiving-water text in EPA's inventory")
            elif row.get("receiving_water_source") == "auto" and not override:
                bits.append(f"EPA's only text is a watershed name ('{rtext}'), not a water's; no name-only match is made from it")
            elif too_far:
                bits.append(f"the only openboatlaunch water of the receiving water's name ('{rtext}') in {row['state']}, "
                            f"{too_far[0]['name']} ({too_far[0]['slug']}), lies {too_far[1]:.0f} km from the point")
            elif row["alternatives"]:
                bits.append(f"{len(row['alternatives'])}+ openboatlaunch waters of the receiving water's name ('{rtext}') in "
                            f"{row['state']}; none within 400 m of the point")
            else:
                bits.append(f"no openboatlaunch water named '{rtext}' in {row['state']}"
                            + (" (openboatlaunch has no waters for this state or territory)" if not waters_in[row["state"]] else ""))
            if row["lat"] is None:
                bits.append("no usable point" + (" (the point EPA gave lies outside the state)" if row.get("coords_problem") else ""))
            elif row.get("coords_from") == "facility":
                bits.append("only the facility's point is known, which is not matched by distance")
            elif geo_refused:
                bits.append(f"the nearest openboatlaunch water within 400 m of the point, {geo_refused[1]['name']} "
                            f"({geo_refused[1]['slug']}, {round(geo_refused[0])} m), has another name than the receiving "
                            f"water ('{rtext or 'none given'}') and the NHDPlus reach ('{r.get('_gnis') or 'none'}')")
            elif not row["water_slug"]:
                bits.append("no openboatlaunch water within 400 m of the point")
            row["no_water_reason"] = "; ".join(bits)
            row["water_match"] = "none: " + row["no_water_reason"]
        if PLANTS:
            tail = "scripts/match_outfalls.py"
            if row["match"] in ("geometry+name", "geometry") and r.get("_gnis") and row["water_match"].endswith(tail):
                row["water_match"] = (row["water_match"][:-len(tail)].rstrip(" ,;") + f"; the point's NHDPlus reach "
                                      f"{r.get('PF_REACH_ID') or '?'} is '{r['_gnis']}'; " + tail)
            row["_plant_index"] = r["_plant_index"]
        row["water_matched_by"] = NATIONAL_BY
    rows.append(row)

if NATIONAL and not PLANTS:
    rows.sort(key=lambda r: (r["state"], r["npdes_permit"], r["outfall"]))
    sh = Counter((r["npdes_permit"], round(r["lat"], 4), round(r["lon"], 4)) for r in rows if r["lat"] is not None)
    for r in rows:
        if r["lat"] is not None and sh[(r["npdes_permit"], round(r["lat"], 4), round(r["lon"], 4))] > 1:
            r["point_shared_by"] = sh[(r["npdes_permit"], round(r["lat"], 4), round(r["lon"], 4))]

if PLANTS:
    MATCH_FIELDS = ("water_slug", "water_name", "water_kind", "distance_m", "match", "water_match", "water_matched_by")
    got = {r["_plant_index"]: r for r in rows}
    for i, p in enumerate(PLANT_DOC["outfalls"]):
        r = got.get(i)
        if r is None:
            continue
        p.pop("replaced_match", None)
        p.pop("no_water_reason", None)
        for f in MATCH_FIELDS:
            p[f] = r[f]
        if r.get("no_water_reason"):
            p["no_water_reason"] = r["no_water_reason"]
    # the file's own layout (research/federal/build_plant_outfalls.py): the header keys one per line, then the rows
    tmp = out_path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("{\n")
        for k, v in PLANT_DOC.items():
            if k not in ("outfalls", "cso_features_not_in_inventory"):
                fh.write(json.dumps(k) + ": " + json.dumps(v, ensure_ascii=False) + ",\n")
        fh.write('"cso_features_not_in_inventory": [\n' + ",\n".join(
            json.dumps(x, ensure_ascii=False) for x in PLANT_DOC.get("cso_features_not_in_inventory") or []) + "\n],\n")
        fh.write('"outfalls": [\n' + ",\n".join(json.dumps(x, ensure_ascii=False) for x in PLANT_DOC["outfalls"]) + "\n]\n}\n")
    os.replace(tmp, out_path)
    print("plant rows matched here", len(rows), Counter(r["state"] for r in rows), file=sys.stderr)
    print("match", Counter(r["match"] for r in rows), file=sys.stderr)
    print("coords_from", Counter(r["coords_from"] for r in rows), file=sys.stderr)
    for k, v in sorted(STATS.items()):
        print("  ", v, k, file=sys.stderr)
    sys.exit(0)

SOURCE = ("EPA ECHO national CSO inventory (ALL_CSO_DOWNLOADS.csv, fetched 2026-11-01 by the federal research agent) "
          "matched to openboatlaunch water geometry (snapshot 2026-11-01)")
RULE = ("nearest water of the same state within 400 m; a shared distinctive name word breaks ties; "
        "name_only when no geometry is within range")
if NATIONAL:
    SOURCE = ("EPA ECHO national CSO inventory (ALL_CSO_DOWNLOADS.csv, fetched 2026-11-01 by the federal research agent), "
              "the states and territories outside the 12 live ones, matched to openboatlaunch water geometry "
              "(out/water as on disk 2026-11-03); scripts/match_outfalls.py --national")
    RULE = ("nearest water of the same state within 400 m whose name shares a distinctive word and the kind of water, "
            "else the nearest within 400 m ('geometry'); name_only when no geometry is within range and exactly one water "
            "of the state has the receiving water's name and lies within 10 km of the point; a facility's point is "
            "matched by name only")
if "--append" in ARGS and os.path.exists(out_path):
    prev = json.load(open(out_path))
    rows = [r for r in prev["outfalls"] if r["state"] not in NE] + rows
    if NATIONAL:
        rows.sort(key=lambda r: (r["state"], r["npdes_permit"], r["outfall"]))
    out = {**prev, "count": len(rows), "outfalls": rows}
    out.setdefault("appended", []).append({"states": sorted(NE), "from": "ALL_CSO_DOWNLOADS.csv (federal research copy)",
                                           "waters": "data/waters-dc.json" if "DC" in NE else "openboatlaunch out/water"})
else:
    out = {"source": SOURCE, "rule": RULE, "count": len(rows), "outfalls": rows}
    if NATIONAL:
        out["states"] = sorted(NE)
        out["live_states_left_out"] = sorted(REGIONAL_STATES)
        out["waters_read"] = dict(sorted(waters_in.items()))
tmp = out_path + ".tmp"
with open(tmp, "w") as fh:
    json.dump(out, fh, indent=1)
os.replace(tmp, out_path)
print("rows", len(rows), Counter(r["state"] for r in rows), file=sys.stderr)
print("match", Counter(r["match"] for r in rows), file=sys.stderr)
print("status", Counter(r["outfall_status"] for r in rows), file=sys.stderr)
if NATIONAL:
    print("coords_from", Counter(r["coords_from"] for r in rows), file=sys.stderr)
    print("coords_problem", sum(1 for r in rows if r.get("coords_problem")), file=sys.stderr)
    for k, v in sorted(STATS.items()):
        print("  ", v, k, file=sys.stderr)
