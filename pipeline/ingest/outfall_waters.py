"""Every registered outfall's water record: data/outfalls-ne.json and data/outfalls-mid-atlantic.json (a registry
helper, not a feed: run by hand after ingest.waters_from_nhd; it writes no events file).

    python -m ingest.outfall_waters [--dry-run] [--offline] [--plants] [--state XX ...]

Owner, 2026-11-03: every registered outfall must have a water record. scripts/match_outfalls.py gave each outfall
of EPA's CSO inventory the openboatlaunch water within 400 m of EPA's point, or the only same-named one in the
state; 1,403 of 3,722 got none, mostly because their receiving water (a small stream, a tidal creek) had no
openboatlaunch record. The records exist now (data/waters-nhd.json from NHDPlus, OSM fallbacks and hand records,
data/waters-extra.json, data/waters-dc.json); this pass gives each such outfall the record of its receiving water and
says how in `water_match`. In order, the first that answers:

  1. "name": the receiving water's name (ECHO's text, or receiving_water_override) placed the way build/status.py
     places a report naming it (Resolver.by_name: the name among the state's records, kept by the placement guard
     against the outfall's own point; with no point, the record must reach the permittee's town, its Census
     outline within 1 km; short forms are tried too: 'Upper NY Bay', 'X Conduit'). An unnamed tributary
     ('Unnamed Trib To Sawmill Run') goes to the water it joins, as status.py and the NHD builder place it. When
     the text names one water that several records carry ('South Branch Park River Conduit': the South Branch Park
     River and the Park River Conduit), the longest name, then the nearest; when it names several waters
     ('Connecticut River and Mascoma River'), only the one at the point (within 400 m, twice as near as the next);
  2. "NHD builder": the NHD builder's answer for that name at that place (data/waters-nhd.json `targets`: the
     NHDPlus water NLDI and the MapServer found at the outfalls' points, 'Nashua River' at Fitchburg being the
     North Nashua River), the nearest of its records the guard keeps;
  3. "permit's receiving water": a text that names no water (a USGS HUC-12 watershed name such as 'Outlet Saugus
     River-Frontal Broad Sound', an MDE basin label such as 'Upper Potomac River - Allegany County', a street ditch)
     or no text: the receiving waters the research lists for the permit (data/dischargers.json), the one whose
     record lies within 400 m of the point, or the only one when the outfall has no point;
  4. "point": no usable name: the water record at the point within 150 m (status.OUTFALL_POINT_M; NHD records are
     NHD flowlines, so this is the snap to the nearest NHD flowline that has a record), never one whose name
     disagrees with the text;
  5. "name and town": the point is missing, or lies far from every water of that name (a mistyped latitude, a
     point in another county): the only record of that name, or of a name one letter off ('Tem Mile River'), that
     reaches the permittee's town (data/dischargers.json towns and the inventory's city; Census outlines); the name
     without a qualifier ('Potomac River' for the North Branch Potomac River at Cumberland) only when the research
     lists that water for the permit. A point more than POINT_WRONG_M from that water is moved to echo_lat/echo_lon
     with coords_problem saying why, so placement, reaches and the rain check do not use it; a point within it that
     the guard rejects counts only when the permit's outfalls share it (one point per permit).

Step 5 does not override a point that lies within 150 m of another named water (Harrisburg's 'Conodoguinet Creek'
outfalls on Paxton Creek): the inventory's name and point disagree, and the row gets no record.

A row with no record keeps water_slug null and gets no_water_reason (the cause, and what the NHD builder found).
Rows scripts/match_outfalls.py matched keep their slug and their water_match restates that match, except its
name-only matches that name another water (its words() drops kind words: 'Onondaga Creek' went to Onondaga Lake,
'Upper New York Bay' to Upper Little York Lake; build/status.py's Resolver.row_water check) or that the placement
guard rejects at the outfall's point: those are matched again here, the old match kept in replaced_match. Every row gets
water_match and water_matched_by. `match` keeps match_outfalls' vocabulary ('geometry+name', 'geometry',
'name_only', 'none'; build/status.py and build/rain_likely.py read it) and distance_m the metres from the point
to the record. Nothing here says where a discharge goes beyond the receiving water the permit or the inventory
names; it only says which water record that is.

The per-outfall diagnosis of the rows match_outfalls left without a water (no coordinates, coordinates shared by
the permit's outfalls or outside the state, no receiving-water text, a text that names no water, a name with no
record, a name whose record the guard rejected) is written to data/build/outfall-waters.json with the counts per
state (docs/reviews/2026-11-03-outfalls-without-water.md).

The registry files are written only when something changed, atomically, in their own format (indent 1, ASCII).

A state build (`--state XX`, 2026-11-04; after `ingest.waters_from_nhd --state XX`): every row of that state in
data/outfalls-us.json (CSO rows: the steps above), data/outfalls-plants-us.json (plant rows: the plant steps below) and
any data/outfalls-<st>.json, live or not, in place. Two steps are added for these rows: "reach", the record the NHD
builder made from the outfall's own EPA NHDPlus id or reach code (data/waters-nhd.json target rows' reach_slugs; not
when the text names another water), after the name steps; and, for an outfall whose permit names no water, the
record the builder made at that outfall (its reach, or its point snapped by NLDI; the target row's outfall_ref).
match_outfalls' matches are kept only where their slug is an openboatlaunch record. The counts and the rows left
without a record are written to data/build/outfall-waters-<st>.json.

Plant outfalls (`--plants`, 2026-11-03): the same pass over the live states' rows of data/outfalls-plants-us.json
(status.states(); scripts/match_outfalls.py --plants has given them its geometry+name match first; see there and
research/federal/plant-outfalls.md), instead of the two CSO files, which this flag does not read or write. Only the
match fields are written onto the rows (water_slug, water_name, water_kind, distance_m, match, water_match,
water_matched_by, no_water_reason, and replaced_match when a name-only match is replaced); every other field stays,
no point is moved, no water record is made. A plant row also carries the reach EPA's catchment index puts the point
on (reach_id and reach_gnis_name, the NHDPlus GNIS name), which is evidence the CSO rows lack. Per row, the first that
answers: 1 and 2 as above on the permit's receiving water; "reach name": the reach's GNIS name placed the same two ways
(not when it names another water than the permit's text does: the text decides); 3 to 5 as above, the point step also
refusing a record whose name disagrees with the reach's. Rows match_outfalls.py gave 'geometry+name' or 'geometry' keep
them; its 'name_only' matches are tried again by these steps first (a record named for the receiving water, not just
containing its words, replaces them; the old match is kept in replaced_match). A row whose point is the facility's
(coords_from 'facility') has no point here: it is placed by name and the permittee's town only. A point step 5 finds
more than POINT_WRONG_M from the named water is not moved (the file's points are left as EPA gave them): the row gets no
record and says why. The receiving waters left without a record are listed by state, name and reach code in
data/build/plant-outfall-waters.json ("unrecorded") for the NHD water-record builder, and in
docs/reviews/2026-11-03-plant-outfall-waters.md.
Pennsylvania: EPA's points are collapsed to one per permit for some permits; DEP's own outfall layer (eMapPA layer
293, research/pa/sources.json pa-dep-sewage-discharge-points-layer) and its permit files were unreachable from
here on 2026-11-03 (gis.dep.pa.gov and files.dep.state.pa.us time out; the open-data hub's download stays
'Pending'; the attempts are logged in data/raw/outfall-waters/pa-dep/), so no point is replaced. Retried at 18:11
UTC the same day, one request each (retry-2026-11-03.log there): both DEP hosts gave no TCP connection in 76 s, the
hub download answered 202 'Pending', PASDA's layer 34 answered with no rows for the CSO permits.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date

from build import status as S
from common import BUILD_DIR, DATA_DIR, now_iso, read_json
from ingest import waters_from_nhd as N

FILES = ("outfalls-ne.json", "outfalls-mid-atlantic.json")
SUMMARY = BUILD_DIR / "outfall-waters.json"
PLANTS_FILE = "outfalls-plants-us.json"
PLANTS_SUMMARY = BUILD_DIR / "plant-outfall-waters.json"
PLANT_FIELDS = ("water_slug", "water_name", "water_kind", "distance_m", "match", "water_match", "water_matched_by")
BY_MATCHER = "scripts/match_outfalls.py (2026-11-01)"
BY_HERE = "ingest.outfall_waters"
LINE_ONLY_FCODES = {55800, 56600}   # NHDPlus artificial path, coastline (Matcher.line_only)
TIGHT_M = 400               # match_outfalls' distance: a record this close to the point is "geometry"
POINT_M = S.OUTFALL_POINT_M  # the snap for an outfall with no usable name
POINT_WRONG_M = 10_000      # a point this far from its named water in the permittee's town is not the outfall's
OUTSIDE_STATE_M = 2_000     # a point this far outside its state's (shoreline-clipped) outline is outside the state

# texts that name a watershed or a basin, not a water
HUC12 = re.compile(r"(^outlet\s+.+-|.+-\s*frontal\s+.+)", re.I)          # USGS HUC-12 names
BASIN = re.compile(r"\s+-\s+(alleg(h)?any|garrett|washington|frederick)\s+county\s*$|^upper potomac river$", re.I)
CONDUIT = re.compile(r"\b(conduit|culvert(ed)?|ditch)\b", re.I)
ABBREV = [(re.compile(r"\bNY\b(?=\s+(bay|harbor|harbour))", re.I), "New York"),
          (re.compile(r"\bNJ\b(?=\s+(bay|harbor|harbour))", re.I), "New Jersey"),
          (re.compile(r"\bAux\.?(?=\s)", re.I), "Auxiliary")]


def today() -> str:
    return date.today().isoformat()


def m(d) -> int | None:
    return None if d is None else int(round(d))


NO_OUTLINE_NOTE = "; the record's outline was not available to this run, so no distance was measured"
# A record with no outline here (an openboatlaunch record whose out/water file is not on this machine) is tied only on
# evidence (Matcher.unmeasured): its own town list names the permittee's town; its bounding box puts the whole water
# within the limit of EPA's point (the box's far bound); or EPA's NHDPlus reach at the point carries its name. A box that
# merely holds the point is no measurement (review 2026-11-04 water-followups P1-1: Valdosta's 'Suwannee River' plant,
# 64 km from that river, inside the box of a 190 km record); without evidence the row is held with a reason until a run
# with the outlines.
HELD = "held until a run with the record's outline"


def far(d) -> float:
    """A distance for ranking: a record with no geometry here (an openboatlaunch record whose out/water file is not on
    this machine) or no point ranks after every measured one, never as the nearest."""
    return float("inf") if d is None else d


def key(o: dict) -> tuple:
    return (o.get("npdes_permit"), str(o.get("outfall")))


STATE_TEXT = False      # run_state(): EPA's receiving-water text read the way the national list reads it


def text_of(o: dict) -> str:
    """The receiving-water text: the override, else ECHO's. In a state build (STATE_TEXT) the waters it names as the
    NHD builder's state targets read them (waters_from_nhd.national_parts: 'St Johns R Class III Marine WBID 2213H' is
    the St Johns River, 'BOGGY CRK/SPRING CRK/FLINT RIVER' is Boggy Creek), joined by 'and'; a text that names none
    stays as it is."""
    raw = str((o.get("receiving_water_override") or {}).get("water") or o.get("receiving_water_echo") or "").strip()
    if STATE_TEXT and raw and not (o.get("receiving_water_override") or {}).get("water"):
        parts, _ = N.national_parts(raw)
        if parts:
            return " and ".join(parts)
    return raw


def variants(text: str) -> list[str]:
    """The text and its short forms: 'Upper NY Bay' -> 'Upper New York Bay'; 'X Conduit' -> 'X'."""
    out = [text]
    t = text
    for rx, rep in ABBREV:
        t = rx.sub(rep, t)
    if t != text:
        out.append(t)
    c = re.sub(r"\s+(conduit|tube)\b.*$", "", t, flags=re.I).strip()
    if c and c != t:
        out.append(c)
    tr = re.sub(r"\s+(tr|trib|tributary)\.?\s*#?\s*\d+[a-z]?$", "", t, flags=re.I).strip()
    if tr and tr != t:
        out.append(tr)      # 'SENECA TR#14': a numbered tributary of the Seneca, placed on it like 'Unnamed Trib To X'
    return list(dict.fromkeys(out))


def why_not_a_name(text: str) -> str | None:
    """Why a receiving-water text names no water (None when it may name one)."""
    if not text:
        return "no receiving-water text"
    if HUC12.match(text):
        return f"'{text}' is a USGS HUC-12 watershed name, not a water"
    if BASIN.search(text):
        return f"'{text}' is a basin label (MDE's watershed names), not the stream at the outfall"
    if re.search(r"\b(final\s+d(i)?sch(ar)?ge?|wwtf|wpad|treatment)\b", text, re.I):
        return f"'{text}' names a treatment plant's discharge, not a water"
    if re.search(r"\bditch\b", text, re.I) and not re.search(r"\b(great|queen|peripheral)\s+ditch\b", text, re.I):
        return f"'{text}' describes a street ditch, not a named water"
    if N.split_names(text, False):      # the NHD builder's reading: 'Unnamed Trib To Sawmill Run' names Sawmill Run
        return None
    w = N.not_water(text) or "no water name"
    if w == "the open ocean (no NHD record)":
        return None
    return f"'{text}': {w}"


def index_targets(rows: list[dict]) -> tuple[dict, dict, dict]:
    """(targets, reach_slugs, outfall_slugs) from data/waters-nhd.json's target rows (Matcher). A report name's row
    (waters_from_nhd --names, from: "reports") names the water of a report, not of an outfall: it is left out, so a
    report-name build changes no outfall's tie by the builder's rows."""
    targets, reach_slugs, outfall_slugs = {}, {}, {}
    for t in rows:
        if t.get("from") == "reports":
            continue
        if t.get("name"):
            targets[(t["state"], N.compact(t["name"]))] = t
        for x in t.get("texts") or []:
            targets.setdefault((t["state"], N.compact(x)), t)
        for k, v in (t.get("reach_slugs") or {}).items():
            reach_slugs.setdefault(str(k), v)
        if t.get("outfall_ref") and t.get("slugs"):
            ref = (t["outfall_ref"][0], str(t["outfall_ref"][1]))
            outfall_slugs[ref] = (t["slugs"][0], "; ".join(x for x in t.get("how") or [] if x)[:200])
    return targets, reach_slugs, outfall_slugs


class Matcher:
    def __init__(self, offline: bool = False, states=None):
        """states: a state build (--state): these states are placed as if live (derive_states(live_only=False))."""
        self.waters = S.load_waters()
        S._STATES = S.derive_states(self.waters, S.load_rules())
        if states:
            S._STATES = S.derive_states(self.waters, S.load_rules(), live_only=False) | set(states)
        S._GEOM_CACHE.clear()
        self.resolver = S.make_resolver(self.waters)
        self.dis_waters = S.load_discharger_waters()
        self.dis_towns = S.load_discharger_towns()
        nhd = read_json(DATA_DIR / "waters-nhd.json") or {}
        # targets: the NHD builder's rows by (state, name); reach_slugs: a state build's EPA reach code or NHDPlus id ->
        # the record it named; outfall_slugs: a state build's unnamed outfalls, (permit, outfall) -> (slug, how)
        self.targets, self.reach_slugs, self.outfall_slugs = index_targets(nhd.get("targets") or [])
        self.states = N.States()
        self.offline = offline
        self.towns = N.Towns(N.Http(offline=offline))       # Census county subdivisions (cached TIGERweb answers)
        self._outlines = {}

    # ------------------------------------------------ helpers

    def canon(self, slug):
        return self.resolver.canon(slug)

    def dist(self, slug, lat, lon):
        if lat is None or lon is None:
            return None
        return self.resolver.distance_m(slug, lat, lon)

    def fake(self, o: dict, text: str) -> dict:
        permit = str(o.get("npdes_permit") or "")
        return {"npdes_permit": permit, "lat": o.get("lat"), "lon": o.get("lon"), "waterbody_text": text,
                "raw": {"state": o.get("state"), "town": o.get("city") or ""}}

    def towns_of(self, o: dict) -> set[str]:
        out = {S.norm_town(o.get("city") or "")}
        out |= {S.norm_town(t) for t in self.dis_towns.get(o.get("npdes_permit")) or []}
        return {N.town_key(t) for t in out if t}

    def record_towns(self, slug) -> set[str]:
        return {N.town_key(t) for t in self.waters[slug].get("towns") or [] if t}

    def town_outlines(self, o: dict) -> list:
        k = (o.get("state"), tuple(sorted(self.towns_of(o))))
        if k not in self._outlines:
            try:
                self._outlines[k] = self.towns.outlines(o["state"], list(k[1])) if k[1] else []
            except Exception:           # TIGERweb not cached and not reachable: the town lists decide
                self._outlines[k] = None
        return self._outlines[k]

    def reaches_town(self, slug, o: dict) -> bool | None:
        """Whether the water's record reaches the permittee's town (its Census outline, within 1 km; openboatlaunch's
        town lists name only the towns with launches); None when the town is unknown. A record whose outline is not on
        this machine (no_outline: an openboatlaunch record without its out/water file) reaches the town when its town
        list names it, does not when its bounding box lies more than 1 km from every outline of the town (the box holds
        the whole water, so this is sure), and is unknown (None) otherwise."""
        outs = self.town_outlines(o)
        if outs is None:
            towns = self.towns_of(o)
            return bool(self.record_towns(slug) & towns) if towns and self.record_towns(slug) else None
        if not outs:
            return None
        g = S.water_geometry(slug, self.waters)
        if g is None:
            if self.record_towns(slug) & self.towns_of(o):
                return True
            b = self.box_of(slug)
            if b is not None and all(N.geom_dist_m(b, t) > 1000 for t in outs):
                return False
            return None
        return any(N.geom_dist_m(g, t) <= 1000 for t in outs)

    def no_outline(self, slug) -> bool:
        """Whether the record has no outline here (an openboatlaunch record whose out/water file is not on this
        machine: a cloud session or a runner without the sibling snapshot). Its distances are then unknown."""
        return S.water_geometry(slug, self.waters) is None

    def box_of(self, slug):
        """The record's bounding box as a shapely box, or None."""
        b = self.waters.get(slug, {}).get("bbox")
        if not b or len(b) != 4:
            return None
        from shapely.geometry import box
        return box(*b)

    def evidence_of(self, held: bool = False) -> dict:
        """This row's notes on records with no outline here: {slug: the evidence it was kept on} (water_match says it),
        or with held, {slug: why it was held}. Cleared per row (clear_row)."""
        k = "_held" if held else "_evidence"
        if not isinstance(self.__dict__.get(k), dict):
            self.__dict__[k] = {}
        return self.__dict__[k]

    def clear_row(self) -> None:
        self._aside = self._several = self._conflict = self._builder_far = None
        self._evidence, self._held = {}, {}
        self._refused = []

    def line_only(self, s: str | None) -> bool:
        """An unnamed NHD record made only of NHDPlus artificial paths (FCode 55800: the line NHDPlus draws through a
        lake, a bay, a ship canal or a wide river) or coastline (56600: the edge of the sea). It stands for no water of
        its own: an outfall on it discharges to the lake, bay or sound around it. An outfall is never tied to one; the
        row keeps the water its point or name finds, or a reason (review 2026-11-04 WA: Seattle's CSO outfalls on Lake
        Union, Portage Bay and Elliott Bay had become 'Unnamed stream near Seattle')."""
        w = self.waters.get(s) or {}
        fc = w.get("nhd_fcodes") or []
        return (bool(fc) and all(int(f) in LINE_ONLY_FCODES for f in fc)
                and str(w.get("name") or "").lower().startswith("unnamed"))

    def usable(self, s: str | None, o: dict, step: str) -> bool:
        """Whether a step's record may be the row's water: not a line_only record, and for the NHD builder's record
        for the outfall (by_outfall_ref, found at the point of the permit and outfall in whichever file the builder
        read) one that lies within TIGHT_M of this row's own point (outfall 170 of WA0031682: EPA's point is 20 km from
        the operator's, and its snap was Blackjack Creek, 29 km from the outfall). A refused record is named in the
        reason."""
        if not s:
            return False
        if self.line_only(s):
            self._refused.append(f"the NHD record at the outfall ({s}) is an unnamed NHDPlus artificial path or "
                                 f"coastline, the line through a lake, bay or sound and not a water of its own")
            return False
        if step == "NHD builder (outfall)" and o.get("lat") is not None:
            d = self.dist(s, o.get("lat"), o.get("lon"))
            if d is not None and d > TIGHT_M:
                self._refused.append(f"the NHD builder's record for this outfall ({s}) lies {m(d)} m from the row's "
                                     f"point (found at another file's point for the same outfall)")
                return False
        return True

    def town_unknown(self, o: dict) -> bool:
        """Whether the permittee's town has no Census outline to check a water against (none named, none found, or no
        town service), as reaches_town's None means for a measured record."""
        if not self.towns_of(o) or getattr(self, "towns", None) is None:
            return True
        outs = self.town_outlines(o)
        return outs is not None and not outs

    def box_far(self, slug, lat, lon) -> float | None:
        """Metres within which the record's water surely lies from the point: the water touches every side of its
        bounding box, so it is no farther than the nearer of each side's two ends, and no farther than the least of
        those over the four sides (an upper bound; box_dist is the lower)."""
        b = self.waters.get(slug, {}).get("bbox")
        if not b or len(b) != 4 or lat is None or lon is None:
            return None
        from shapely.geometry import Point
        x0, y0, x1, y1 = b
        sides = [((x0, y0), (x1, y0)), ((x0, y1), (x1, y1)), ((x0, y0), (x0, y1)), ((x1, y0), (x1, y1))]
        return min(max(N.dist_m(Point(c), lon, lat) for c in side) for side in sides)

    def unmeasured(self, slug, o: dict, limit: float, basis: str = "", town_first: bool = False) -> tuple[bool, str]:
        """(kept, why) for a record with no outline here at row o: the evidence it is the water within `limit` of
        EPA's point (or, with no point, at the permittee's town), else why it is held. Kept on: its town list naming
        the permittee's town; with no point and no known town, nothing to check (as for a measured record); its
        bounding box within `limit` of the point at its far bound (box_far); EPA's NHDPlus reach at the point carrying
        its name (gnis_of) with the box within the limit. Set aside when the box is beyond the limit (a lower bound:
        sure; before the town list, as the guard does, unless town_first: the builder's record for the permit, which
        the permittee's town decides however far EPA's point), or beyond the guard's own distance with the report's
        town not among the water's towns (the guard's town check, which an unmeasured record would otherwise skip)."""
        w = self.waters.get(slug) or {}
        towns = self.towns_of(o)
        common = sorted(self.record_towns(slug) & towns)
        lat, lon = o.get("lat"), o.get("lon")
        lb = self.box_dist(slug, lat, lon) if lat is not None and lon is not None else None
        lim = f"limit {limit / 1000:.1f} km" + (f": {basis}" if basis else "")
        if lb is not None and lb > limit and not town_first:
            return False, f"its bounding box is {lb / 1000:.1f} km from the point ({lim})"
        if common:
            return True, f"its town list names the permittee's town ({', '.join(common[:3])})"
        if lat is None or lon is None:
            if towns and self.reaches_town(slug, o) is False:
                return False, (f"no point, and its bounding box lies more than 1 km from the permittee's town "
                               f"({', '.join(sorted(towns))})")
            if not towns or self.town_unknown(o):
                return True, "no point and no known town to check it against"
            return False, (f"no point, and its town list does not name the permittee's town ({', '.join(sorted(towns))}): "
                           f"{HELD}")
        if lb is not None and lb > limit:
            return False, f"its bounding box is {lb / 1000:.1f} km from the point ({lim})"
        ub = self.box_far(slug, lat, lon)
        g = gnis_of(o)
        names = {S.norm_name(w.get("name") or "")} | {S.norm_name(a) for a in w.get("aliases") or []}
        if ub is not None and ub <= limit:
            why = f"its bounding box puts the whole water within {ub / 1000:.1f} km of the point ({lim})"
        elif g and S.norm_name(g) in names and lb is not None:
            why = f"EPA's NHDPlus reach at the point is named '{g}', and its bounding box is within the limit ({lim})"
        elif not w.get("bbox"):
            return False, f"it has neither an outline here nor a bounding box: {HELD}"
        else:
            return False, (f"its bounding box ({(ub or 0) / 1000:.1f} km at its far bound) cannot place it within the "
                           f"limit of the point ({lim}), its town list does not name the permittee's town, and EPA's "
                           f"reach at the point is " + (f"named '{g}'" if g else "unnamed") + f": {HELD}")
        tight = S.WIDE_NAME_MATCH_M if w.get("kind") in S.WIDE_KINDS else S.NAME_MATCH_M
        if lb is not None and lb > tight:
            conflict = self.resolver.town_conflict(self.fake(o, w.get("name") or ""), slug)
            if conflict:
                return False, f"its bounding box is {lb / 1000:.1f} km from the point and {conflict}"
        return True, why

    def box_dist(self, slug, lat, lon) -> float | None:
        """Metres from the point to the record's bounding box: never more than the distance to the water itself, so a
        box farther than a limit puts the water farther too (used only to set a record aside)."""
        b = self.box_of(slug)
        if b is None or lat is None or lon is None:
            return None
        return N.dist_m(b, lon, lat)

    def source_of(self, slug) -> str:
        w = self.waters[slug]
        if not w.get("extra"):
            return "openboatlaunch"
        if w.get("hand"):
            return "hand record, " + ("NHD high resolution" if "high resolution" in (w.get("note") or "") else w.get("source") or "")
        return {"nhd": "NHDPlus V2.1 record", "osm": "OpenStreetMap record"}.get(w.get("source"), "waters-extra record")

    def guard_ok(self, slug, o, text) -> tuple[bool, str | None]:
        kept, aside, _ = self.resolver.guard_detail([slug], self.fake(o, text))
        if kept and self.no_outline(slug):          # unmeasured here: kept on evidence only (unmeasured)
            limit, basis = self.resolver.name_limit_m(slug)
            ok, why = self.unmeasured(slug, o, limit, basis)
            if not ok:
                return False, why
            self.evidence_of()[slug] = why
        return bool(kept), (aside[0][1] if aside else None)

    def in_state(self, o: dict) -> tuple[bool, float]:
        st, lat, lon = o.get("state"), o.get("lat"), o.get("lon")
        shp = self.states.shapes.get(st)
        if shp is None or lat is None:
            return True, 0.0
        d = N.dist_m(shp, lon, lat)
        return d <= OUTSIDE_STATE_M, d

    # ------------------------------------------------ the steps

    def by_name(self, o: dict, text: str):
        """Step 1."""
        st, lat, lon = o["state"], o.get("lat"), o.get("lon")
        for v in variants(text):
            slugs, _, _ = self.resolver.by_name(v, st, lat, lon, self.fake(o, v))
            slugs = list(dict.fromkeys(self.canon(s) for s in slugs if self.canon(s) in self.waters))
            if not slugs:
                continue
            kept, aside, _ = self.resolver.guard_detail(slugs, self.fake(o, v))
            # the guard keeps a record it cannot measure (no outline here): kept on evidence only (unmeasured)
            held = []
            for x in [x for x in kept if self.no_outline(x) and self.dist(x, lat, lon) is None]:
                limit, basis = self.resolver.name_limit_m(x)
                ok, why = self.unmeasured(x, o, limit, basis)
                if ok:
                    self.evidence_of()[x] = why
                else:
                    kept.remove(x)
                    aside = list(aside) + [(x, why)]
                    if HELD in why:
                        held.append(x)
            if lat is None:
                # no point for the guard: the record must reach the permittee's town (Cumberland's 'Potomac River'
                # is the North Branch there, not the main stem's record, which begins downstream)
                towns = self.towns_of(o)
                off = [x for x in kept if self.reaches_town(x, o) is False]
                aside = list(aside) + [(x, f"no point, and the water does not reach the permittee's town "
                                           f"({', '.join(sorted(towns))})") for x in off]
                kept = [x for x in kept if x not in off]
            read = f" (read as '{v}')" if v != text else ""
            if held and kept and len(N.split_names(v, False)) > 1:
                # the text names several waters and one is held for want of its outline: it may be the one at the
                # point, so none is chosen
                self._several = kept + held
                return None, None
            if len(kept) == 1:
                s = kept[0]
                return s, f"its receiving water '{text}'{read} by name"
            parts = N.split_names(v, False)
            if len(kept) > 1 and len(parts) > 1:
                # the text names several waters ('Connecticut River and Mascoma River'): the one at the point only
                near = sorted((far(self.dist(x, lat, lon)), x) for x in kept) if lat is not None else []
                # every record measured: one with no geometry here cannot be ruled out at the point
                if near and near[-1][0] < float("inf") and near[0][0] <= TIGHT_M and \
                        (len(near) == 1 or near[1][0] > 2 * near[0][0]):
                    return near[0][1], (f"its receiving water '{text}'{read} names {len(parts)} waters; the one "
                                        f"at the point ({m(near[0][0])} m)")
                self._several = [x for x in kept]
                return None, None
            if len(kept) > 1:
                nv = f" {S.norm_name(v)} "

                def matched_len(s):
                    n = S.norm_name(self.waters[s].get("name") or "")
                    names = [n] + [S.norm_name(a) for a in self.waters[s].get("aliases") or []]
                    return max((len(x) for x in names if x and f" {x} " in nv), default=0)
                kept.sort(key=lambda s: (-matched_len(s), far(self.dist(s, lat, lon))))
                s = kept[0]
                return s, (f"its receiving water '{text}' by name; it names {len(kept)} records ({', '.join(kept)}), "
                           f"the one with the longest name in the text taken")
            if aside:
                self._aside = aside
        return None, None

    def by_nhd_target(self, o: dict, text: str):
        """Step 2."""
        st, lat, lon = o["state"], o.get("lat"), o.get("lon")
        parts = N.split_names(text, False) or [text]
        for p in parts:
            t = self.targets.get((st, N.compact(p))) or self.targets.get((st, N.compact(text)))
            if not t or not t.get("slugs"):
                continue
            cands, aside = [], []
            for s in t["slugs"]:
                s = self.canon(s)
                if s not in self.waters:
                    continue
                ok, why = self.guard_ok(s, o, text)
                if ok:
                    cands.append((far(self.dist(s, lat, lon)), s))
                elif why and HELD in why:
                    aside.append((s, why))
            if aside and not cands and not self._aside:
                self._aside = aside             # held, not elsewhere: reason() says so
            if cands:
                d, s = min(cands)
                how = "; ".join(x for x in t.get("how") or [] if x)[:200]
                return s, f"the NHD builder's water for '{p}' in {st} (as found for the permits that name it: {how})"
        return None, None

    def by_reach(self, o: dict, text: str):
        """A state build's step: the record the NHD builder made from this outfall's own EPA reach (its NHDPlus id or
        reach code, data/waters-nhd.json targets' reach_slugs), when the receiving-water text does not name another
        water."""
        for x in (o.get("nhdplus_id"), o.get("reach_id")):
            s = self.reach_slugs.get(str(x)) if x else None
            s = self.canon(s) if s else None
            if not s or s not in self.waters or self.waters[s].get("state") != o.get("state"):
                continue
            if text and not why_not_a_name(text) and S.names_disagree(text, self.waters[s].get("name")):
                continue
            if self.no_outline(s):
                self.evidence_of()[s] = f"EPA's own NHD reach for the outfall ({x}) is on the NHD feature taken for this water"
            return s, f"the NHD builder's record for the outfall's own NHD reach {x} (EPA), no snapping"
        return None, None

    def by_builder_permit(self, o: dict, text: str):
        """A state build's step: the record the NHD builder made for this receiving water for this very permit (the
        target row's permits; its record was chosen by EPA's reach, or by the name nearest the operators' towns, or at
        their points). EPA's treatment-plant points are often the facility's, kilometres from the water the permit
        names, so the placement guard's distance check is not applied here; the note gives the distance. The builder
        keeps one target per name and state, pooling every permit that names it, so its record can be another water of
        that name (2026-11-04 review: Raeford's plants on the Rockfish Creek at Wallace, 110 km away): the record is
        taken only when EPA's point lies on it (TIGHT_M) or it reaches the permittee's town (reaches_town), or, with
        neither a point nor a known town, as the builder chose it; otherwise none, and reason() says why. A record with
        no outline here has no distance although the row has a point: it is taken on the evidence unmeasured() finds
        (its town list, or its box at EPA's point), never as 'neither can be checked'."""
        st, permit = o.get("state"), o.get("npdes_permit")
        lat, lon = o.get("lat"), o.get("lon")
        self._builder_far = None
        keys = [N.compact(text)] + [N.compact(p) for p in N.national_parts(text)[0]]
        for k in keys:
            t = self.targets.get((st, k))
            if not t or not t.get("define_by") or permit not in (t.get("permits") or []) or not t.get("slugs"):
                continue
            cands = list(dict.fromkeys(self.canon(x) for x in t["slugs"] if self.canon(x) in self.waters))
            if not cands:
                continue
            ranked = []
            for x in cands:
                d = self.dist(x, lat, lon)
                rt = self.reaches_town(x, o)
                if d is None and self.no_outline(x):
                    # unmeasured here: 'no distance' is not 'no point', so the builder's choice does not stand on its
                    # own; the point (TIGHT_M) or the town by evidence (unmeasured)
                    ok, why = self.unmeasured(x, o, TIGHT_M, "EPA's point on the water", town_first=True)
                    if ok:
                        self.evidence_of()[x] = why
                    else:
                        self.evidence_of(held=True)[x] = why
                else:
                    ok = (d is not None and d <= TIGHT_M) or rt is True or (rt is None and d is None)
                ranked.append((not ok, rt is not True, far(d), x, d, rt))
            ranked.sort(key=lambda r: r[:4])
            bad, _, _, slug, d, rt = ranked[0]
            if bad:
                towns = ", ".join(sorted(self.towns_of(o))) or "unknown"
                self._builder_far = (f"the NHD builder's record for '{text}' for this permit, {slug}, "
                                     + (f"is {m(d) / 1000:.1f} km from EPA's point and " if d is not None else "")
                                     + (f"is not measured here: {self.evidence_of(held=True)[slug]}"
                                        if slug in self.evidence_of(held=True) and rt is not False else
                                        f"does not reach the permittee's town ({towns}): likely another water of that "
                                        f"name, not matched" if rt is False else
                                        f"the permittee's town ({towns}) could not be checked against it: not matched"))
                return None, None
            how = "; ".join(x for x in t.get("how") or [] if x)[:200]
            where = "" if lat is None or d is None or d <= TIGHT_M else f"; EPA's point is {m(d) / 1000:.1f} km from it"
            if rt is True and where:
                where += ", and it reaches the permittee's town"
            return slug, f"its receiving water '{text}': the NHD builder's record for it for this permit ({how}){where}"
        return None, None

    def by_outfall_ref(self, o: dict):
        """A state build's step for an outfall whose permit names no water: the NHD builder's record for this outfall
        (its reach or its point snapped by NLDI; data/waters-nhd.json targets' outfall_ref)."""
        hit = self.outfall_slugs.get((o.get("npdes_permit"), str(o.get("outfall"))))
        if not hit:
            return None, None
        s = self.canon(hit[0])
        if s not in self.waters:
            return None, None
        if self.no_outline(s):
            self.evidence_of()[s] = "the outfall's own point or reach led to the NHD feature taken for this water"
        return s, f"no receiving-water name; the NHD builder's water for this outfall ({hit[1]})"

    def by_permit_waters(self, o: dict):
        """Step 3: the permit's listed receiving waters (research), the one within TIGHT_M of the point."""
        dw = self.dis_waters.get(o.get("npdes_permit"))
        if not dw:
            return None, None
        st, lat, lon = o["state"], o.get("lat"), o.get("lon")
        cands, unrecorded = {}, []
        for name in dw["names"]:
            before = len(cands)
            for v in variants(name):
                slugs, _, _ = self.resolver.by_name(v, st, lat, lon, self.fake(o, v))
                for s in slugs:
                    s = self.canon(s)
                    if s in self.waters:
                        cands.setdefault(s, name)
                t = self.targets.get((st, N.compact(v)))
                for s in (t or {}).get("slugs") or []:
                    s = self.canon(s)
                    if s in self.waters:
                        cands.setdefault(s, name)
            if len(cands) == before and name not in cands.values():
                unrecorded.append(name)
        if not cands:
            return None, None
        only = len({S.norm_name(x) for x in dw["names"]}) == 1      # 'CONNECTICUT R.' and 'CONNECTICUT RIVER'
        if lat is None:
            hit = [s for s in cands if self.reaches_town(s, o)]
            if only and len(hit) == 1:
                s = hit[0]
                return s, (f"no point; the permit's only listed receiving water '{cands[s]}' (data/dischargers.json), "
                           f"the record of that name that reaches the permittee's town")
            return None, None
        near = sorted((self.dist(s, lat, lon) or 1e12, s) for s in cands)
        if only and near[0][0] <= S.NAME_MATCH_M and (len(near) == 1 or near[1][0] > 2 * near[0][0]):
            d, s = near[0]
            return s, (f"the permit's only listed receiving water '{cands[s]}' (data/dischargers.json, from the research), "
                       f"{m(d)} m from the point")
        near = [x for x in near if x[0] <= TIGHT_M]
        if not near or unrecorded:
            return None, None                   # a listed water with no record may be the one at the point
        if len(near) > 1 and near[1][0] < 2 * near[0][0]:
            return None, None                   # two listed waters about as close: not decided here
        d, s = near[0]
        return s, (f"the permit's receiving water '{cands[s]}' (data/dischargers.json, from the research), "
                   f"the listed water whose record lies at the point ({m(d)} m)")

    def by_point(self, o: dict, text: str):
        """Step 4: the record at the point within POINT_M, its name not disagreeing with a text."""
        lat, lon = o.get("lat"), o.get("lon")
        near = self.resolver.by_point(lat, lon, o["state"])
        if not near or near[0] > POINT_M:
            return None, None
        d, s = near
        s = self.canon(s)
        if text and not why_not_a_name(text) and S.names_disagree(text, self.waters[s].get("name")):
            return None, None
        return s, f"the water record at the outfall's point ({m(d)} m; snapped within {POINT_M} m)"

    def by_name_and_town(self, o: dict, text: str):
        """Step 5: the only record of that name (or one letter off) that reaches the permittee's town."""
        st = o["state"]
        towns = self.towns_of(o)
        if not towns:
            return None, None
        ws = N.words(text)
        listed = {S.norm_name(x) for x in (self.dis_waters.get(o.get("npdes_permit")) or {}).get("names") or []}
        cands = []
        for s, w in self.waters.items():
            if w.get("state") != st or not w.get("name"):
                continue
            sc = max([N.name_score(ws, w["name"])] + [N.name_score(ws, a) for a in w.get("aliases") or []])
            # 0.7: the name without its qualifier ('Potomac River' for the North Branch Potomac River at
            # Cumberland), only when the research lists that water for the permit
            if (sc >= 0.8 or (sc >= 0.7 and S.norm_name(w["name"]) in listed)) and self.reaches_town(s, o):
                cands.append((sc, s))
        best = [s for sc, s in cands if sc == max((c[0] for c in cands), default=0)]
        if len(best) != 1:
            return None, None
        s = best[0]
        if S.norm_name(text) != S.norm_name(self.waters[s]["name"]) and \
                any(HELD in why for _, why in (self._aside or [])):
            # the text's own water has a record, held for want of its outline: not a near-named one instead
            # ('Northeast Cape Fear River' is not the Cape Fear River at Wilmington)
            return None, None
        if self.no_outline(s):
            self.evidence_of()[s] = f"its town list names the permittee's town ({', '.join(sorted(towns))})"
        tw = sorted(towns)
        listed_note = (f"; the research lists {self.waters[s]['name']} for the permit (data/dischargers.json)"
                       if S.norm_name(self.waters[s]["name"]) in listed else "")
        return s, (f"its receiving water '{text}' by name and the permittee's town ({', '.join(tw)}): the only record "
                   f"of that name there" + ("" if S.norm_name(text) == S.norm_name(self.waters[s]["name"]) else
                                            f" (the text reads '{text}', the record '{self.waters[s]['name']}')")
                   + listed_note)

    # ------------------------------------------------ one row

    def diagnose(self, o: dict, shared: Counter) -> dict:
        """The causes match_outfalls left this row without a water (flags)."""
        text = text_of(o)
        lat, lon = o.get("lat"), o.get("lon")
        f = {"no_coordinates": lat is None or lon is None,
             "collapsed": lat is not None and shared[(o["npdes_permit"], round(lat, 4), round(lon, 4))] > 1,
             "no_text": not text}
        ok, d = self.in_state(o) if not f["no_coordinates"] else (True, 0)
        f["outside_state"] = not ok
        f["not_a_name"] = bool(text) and bool(why_not_a_name(text))
        return f

    def match(self, o: dict, flags: dict | None = None) -> dict:
        """{slug, how, step, coords_problem?} or {slug None, reason}. flags: diagnose()'s."""
        self.clear_row()
        text = text_of(o)
        lat, lon = o.get("lat"), o.get("lon")
        not_name = why_not_a_name(text)
        if text and not not_name:
            for step, fn in (("name", self.by_name), ("NHD builder", self.by_nhd_target), ("reach", self.by_reach),
                             ("NHD builder for the permit", self.by_builder_permit)):
                s, how = fn(o, text)
                if s and self.usable(s, o, step):
                    return {"slug": s, "how": how, "step": step}
        if not text or not_name:
            for step, fn in (("reach", lambda x: self.by_reach(x, text)), ("NHD builder (outfall)", self.by_outfall_ref)):
                s, how = fn(o)
                if s and self.usable(s, o, step):
                    return {"slug": s, "how": f"{not_name}; {how}" if not_name else how,
                            "step": "NHD builder" if step == "NHD builder (outfall)" else step}
        s, how = self.by_permit_waters(o) if (not text or not_name) else (None, None)
        if s and self.usable(s, o, "permit's receiving water"):
            return {"slug": s, "how": f"{not_name}; {how}" if not_name else how, "step": "permit's receiving water"}
        if lat is not None:
            s, how = self.by_point(o, text)
            if s and self.usable(s, o, "point"):
                return {"slug": s, "how": f"{not_name}; {how}" if not_name else how, "step": "point"}
        if text and not not_name:
            s, how = self.by_name_and_town(o, text)
            d = self.dist(s, lat, lon) if s else None
            near = self.resolver.by_point(lat, lon, o["state"]) if lat is not None else None
            if near and near[0] <= POINT_M and not self.line_only(self.canon(near[1])) \
                    and S.names_disagree(text, self.waters[self.canon(near[1])].get("name")) \
                    and not (d is not None and d > POINT_WRONG_M):
                # the point lies on another named water and is not a far-off mistake: the name and the point disagree
                self._conflict = (f"EPA's point lies on {self.waters[self.canon(near[1])]['name']} ({m(near[0])} m), "
                                  f"not on a water named '{text}': the inventory's name and point disagree")
                return {"slug": None, "reason": self.reason(o, text, not_name)}
            if s:
                out = {"slug": s, "how": how, "step": "name and town"}
                if d is not None and d > POINT_WRONG_M:
                    out["coords_problem"] = (f"ECHO's point ({lat}, {lon}) is {d / 1000:.1f} km from {s}, the only "
                                             f"'{self.waters[s]['name']}' in the permittee's town; it cannot be this "
                                             f"outfall's (a mistyped coordinate or another place's point)")
                elif d is not None and not self.guard_ok(s, o, text)[0]:
                    out["how"] += (f"; EPA's point, {d / 1000:.1f} km from it, is "
                                   + ("shared by several outfalls of the permit (one point per permit)"
                                      if (flags or {}).get("collapsed") else "not at that water")
                                   + ", so the town decides")
                return out
        return {"slug": None, "reason": self.reason(o, text, not_name)}

    def reason(self, o: dict, text: str, not_name: str | None) -> str:
        st, lat, lon = o["state"], o.get("lat"), o.get("lon")
        bits = []
        if not text:
            bits.append("no receiving-water text in EPA's inventory")
        elif not_name:
            bits.append(not_name)
        if lat is None:
            bits.append("no point in EPA's inventory")
        if text and not not_name:
            parts = N.split_names(text, False) or [text]
            t = self.targets.get((st, N.compact(parts[0]))) or self.targets.get((st, N.compact(text)))
            if self._conflict:
                bits.append(self._conflict)
            if self._several:
                bits.append(f"the text names {len(parts)} waters ({', '.join(self._several)}) and "
                            + ("there is no point to choose one" if lat is None else "the point does not choose one"))
            elif self._aside:
                bits.append(f"the record of that name was set aside by the placement guard: "
                            f"{self._aside[0][0]}, {self._aside[0][1]}")
            if getattr(self, "_builder_far", None):
                bits.append(self._builder_far)
            elif t and not t.get("slugs") and t.get("reason"):
                bits.append(f"NHD builder: {t['reason']}")
            elif t and t.get("slugs") and not (self._aside and self._aside[0][0] in [self.canon(x) for x in t["slugs"]]):
                bits.append(f"the NHD builder's records for '{parts[0]}' ({', '.join(t['slugs'])}) lie elsewhere in the state")
            elif not t and not self.resolver.by_name(parts[0], st, None, None, self.fake(o, parts[0]))[0]:
                bits.append(f"no record named '{parts[0]}' in {st}")
            fails = [p for p in (t or {}).get("places_failed") or []
                     if lat is not None and abs(p["lat"] - lat) < 0.03 and abs(p["lon"] - lon) < 0.03]
            if fails:
                bits.append(f"at this place: {fails[0]['reason']}")
        elif lat is not None:
            near = self.resolver.by_point(lat, lon, st)
            bits.append(f"no water record within {POINT_M} m of the point"
                        + (f" (nearest: {near[1]}, {m(near[0])} m)" if near else ""))
        dw = self.dis_waters.get(o.get("npdes_permit"))
        if dw and dw.get("names") and (not text or not_name):
            bits.append(f"the permit's listed receiving waters ({', '.join(dw['names'][:5])}) cannot be told apart "
                        f"for this outfall")
        bits += [x for x in dict.fromkeys(getattr(self, "_refused", None) or []) if x not in bits]
        return "; ".join(bits)


def gnis_of(o: dict) -> str:
    """The NHDPlus GNIS name of the reach EPA's catchment index puts the outfall's point on (a plant row's reach_gnis_name)."""
    return str(o.get("reach_gnis_name") or "").strip()


def plant_view(o: dict) -> dict:
    """A plant row as the matcher reads an outfall row: a facility's point is not the outfall's, so the view has none
    (the row is placed by name and the permittee's town); the row itself keeps its point."""
    v = dict(o)
    v.pop("receiving_water_override", None)
    if o.get("coords_from") == "facility":
        v["lat"] = v["lon"] = None
    return v


def match_plant(mt: "Matcher", o: dict, flags: dict | None = None) -> dict:
    """Matcher.match for a plant row (a plant_view): the same steps, plus the reach's GNIS name after the permit's text."""
    mt._aside = None
    mt._several = None
    mt._conflict = None
    mt._builder_far = None
    mt._evidence, mt._held = {}, {}        # Matcher.evidence_of
    text, gnis = text_of(o), gnis_of(o)
    lat = o.get("lat")
    not_name = why_not_a_name(text)
    named = bool(text) and not not_name
    gnis_ok = bool(gnis) and not why_not_a_name(gnis) and not (named and S.names_disagree(text, gnis))
    if named:
        several = len(N.split_names(text, False)) > 1
        for step, fn in (("name", mt.by_name), ("NHD builder", mt.by_nhd_target)):
            if step == "NHD builder" and several and lat is None:
                continue                # a text naming several waters and no point to choose one
            s, how = fn(o, text)
            if s:
                return {"slug": s, "how": how, "step": step}
    s, how = mt.by_reach(o, text) if hasattr(mt, "by_reach") else (None, None)
    if s:
        return {"slug": s, "how": how, "step": "reach"}
    s, how = mt.by_builder_permit(o, text) if named and hasattr(mt, "by_builder_permit") else (None, None)
    if s:
        return {"slug": s, "how": how, "step": "NHD builder for the permit"}
    if not named and hasattr(mt, "by_outfall_ref"):
        s, how = mt.by_outfall_ref(o)
        if s:
            return {"slug": s, "how": f"{not_name}; {how}" if not_name else how, "step": "NHD builder"}
    if gnis_ok and not (named and S.norm_name(gnis) == S.norm_name(text)):
        reach = o.get("reach_id") or "?"
        for fn in (mt.by_name, mt.by_nhd_target):
            s, how = fn(o, gnis)
            if s:
                return {"slug": s, "step": "reach name",
                        "how": f"the NHDPlus GNIS name '{gnis}' of the reach {reach} EPA's catchment index puts the point on: {how}"}
    s, how = mt.by_permit_waters(o) if not named else (None, None)
    if s:
        return {"slug": s, "how": f"{not_name}; {how}" if not_name else how, "step": "permit's receiving water"}
    label_only = not text or bool(HUC12.match(text) or BASIN.search(text) or NO_WATER_NAMED.match(text))
    if lat is not None and label_only:
        # the snap to the record at the point only for a text with no water in it (none, a HUC-12 or basin label): a
        # text that says groundwater, a ditch or another water the point is near is not turned into the nearest record
        s, how = mt.by_point(o, text)
        if s and gnis_ok and S.names_disagree(gnis, mt.waters[s].get("name")):
            s = None                    # the record at the point is not the water the reach is named for
        if s:
            return {"slug": s, "how": f"{not_name}; {how}" if not_name else how, "step": "point"}
    if named:
        # step 5 as Matcher.match has it, without moving the point (a plant row's point stays as EPA gave it)
        res = mt.match(o, flags)
        if res.get("slug") and res.get("step") == "name and town":
            wn = mt.waters[res["slug"]].get("name")
            d = mt.dist(res["slug"], lat, o.get("lon"))
            if gnis_ok and S.names_disagree(gnis, wn):
                return {"slug": None, "reason": mt.reason(o, text, not_name) + f"; the town's only '{text}' record, {wn}, is not "
                        f"the water the NHDPlus reach {o.get('reach_id') or '?'} is named for ('{gnis}')"}
            if d is not None and d > TIGHT_M and S.norm_name(wn) not in (S.norm_name(text), S.norm_name(gnis)):
                return {"slug": None, "reason": mt.reason(o, text, not_name) + f"; the town's record {wn} is {d / 1000:.1f} km "
                        f"from the point and its name is not the receiving water's ('{text}'): not matched"}
            if res.get("coords_problem"):
                return {"slug": None, "reason": mt.reason(o, text, not_name) + "; " + res["coords_problem"].replace(
                    "it cannot be this outfall's", "it is left as EPA gave it and the row is not matched to that water")}
            return res
    reason = mt.reason(o, text, not_name)
    if gnis and not (named and S.norm_name(gnis) == S.norm_name(text)):
        reason += (f"; the NHDPlus reach {o.get('reach_id') or '?'} is named '{gnis}'"
                   + ("" if gnis_ok else " (not read: it names another water than the permit's text)")
                   + " and no record of that name is at the point")
    return {"slug": None, "reason": reason or "no water record found by the name, reach-name, point or town steps"}


NO_WATER_NAMED = re.compile(r"^\s*(?:unnamed|unknown|unn?)\.?\s*(?:stream|creek|tributary|trib|ditch|waterway|water)?\s*$", re.I)   # 'Unnamed Stream'
UNNAMED = re.compile(r"\b(?:unnamed\s+trib(?:utary)?|trib(?:utary)?|untr?|ut|unn)\b\.?(?:\s+(?:to|of))?|\bestuary\b|"
                     r"\bzone\s+\d+\b|\([^)]*\)", re.I)


def same_water(o: dict, w: dict) -> bool:
    """Whether a water record IS the water a plant row names (the permit's text, or the reach's GNIS name): its name or an
    alias equals the text once abbreviations are spelled out and 'Unnamed Trib To', 'UT', '(Zone 4)' and 'Estuary' are
    dropped ('Mattaponi River, UT' and 'Hudson R UNTR' are the Mattaponi and the Hudson; 'Little Neshaminy Creek' is not
    the Neshaminy Creek, 'White Lake Brook' is not White Lake)."""
    names = {S.norm_name(n) for n in [w.get("name") or ""] + list(w.get("aliases") or []) if n}
    for t in (text_of(o), gnis_of(o)):
        if t and S.norm_name(UNNAMED.sub(" ", t)) in names:
            return True
    return False


def write_plants(path, doc: dict) -> None:
    """data/outfalls-plants-us.json in the layout research/federal/build_plant_outfalls.py wrote (the header keys one
    per line, then the rows), atomically."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as fh:
        fh.write("{\n")
        for k, v in doc.items():
            if k not in ("outfalls", "cso_features_not_in_inventory"):
                fh.write(json.dumps(k) + ": " + json.dumps(v, ensure_ascii=False) + ",\n")
        fh.write('"cso_features_not_in_inventory": [\n' + ",\n".join(
            json.dumps(x, ensure_ascii=False) for x in doc.get("cso_features_not_in_inventory") or []) + "\n],\n")
        fh.write('"outfalls": [\n' + ",\n".join(json.dumps(x, ensure_ascii=False) for x in doc["outfalls"]) + "\n]\n}\n")
    tmp.replace(path)


def note_for_matcher_row(o: dict, waters: dict) -> str:
    slug, d, mt = o["water_slug"], o.get("distance_m"), o.get("match")
    name = (waters.get(slug) or {}).get("name") or o.get("water_name") or slug
    rw = text_of(o) or "none given"
    if mt == "geometry+name":
        return (f"EPA's point lies {d} m from {name} ({slug}), whose name shares a word with the receiving water "
                f"('{rw}'); openboatlaunch record, scripts/match_outfalls.py")
    if mt == "geometry":
        return (f"EPA's point lies {d} m from {name} ({slug}), the nearest openboatlaunch water within 400 m; the "
                f"receiving water ('{rw}') does not share its name; scripts/match_outfalls.py")
    if mt == "name_only":
        return (f"no openboatlaunch water within 400 m of EPA's point; {name} ({slug}) is the only water of the "
                f"receiving water's name ('{rw}') in the state; scripts/match_outfalls.py")
    if o.get("receiving_water_override"):
        return f"{name} ({slug}) by the receiving-water override; scripts/match_outfalls.py"
    return f"{name} ({slug}); scripts/match_outfalls.py ({mt})"


def apply(o: dict, res: dict, mt: Matcher) -> None:
    """Write one result into a registry row (in place)."""
    by = f"{BY_HERE} ({today()})"
    if res.get("slug"):
        s = res["slug"]
        w = mt.waters[s]
        if res.get("coords_problem"):
            o["echo_lat"], o["echo_lon"] = o.get("lat"), o.get("lon")
            o["lat"] = o["lon"] = None
            o["coords_problem"] = res["coords_problem"]
        d = mt.dist(s, o.get("lat"), o.get("lon"))
        text = text_of(o)
        named = bool(text) and not why_not_a_name(text) and not S.names_disagree(text, w.get("name"))
        o.update(water_slug=s, water_name=w.get("name"), water_kind=w.get("kind"), distance_m=m(d))
        # match_outfalls' vocabulary (status.Resolver.row_water, rain_likely, ny_sprtk and ma_massdep read it)
        o["match"] = ("geometry+name" if named and d is not None and d <= TIGHT_M else
                      "geometry" if d is not None and d <= TIGHT_M else "name_only")
        o["water_match"] = (f"{res['step']}: {res['how']}; {w.get('name')} ({s}, {mt.source_of(s)})"
                            + (f", {m(d)} m from the point" if d is not None else
                               ", no point" if o.get("lat") is None else ", distance not measured")
                            + ((NO_OUTLINE_NOTE + (f"; kept as {mt.evidence_of()[s]}" if mt.evidence_of().get(s) else ""))
                               if mt.no_outline(s) else ""))
        o["water_matched_by"] = by
        o.pop("no_water_reason", None)
    else:
        o.update(water_slug=None, water_name=None, water_kind=None, distance_m=None, match="none")
        o["water_match"] = "none: " + res["reason"]
        o["no_water_reason"] = res["reason"]
        o["water_matched_by"] = by


def is_matchers(o: dict) -> bool:
    return bool(o.get("water_slug")) and str(o.get("water_matched_by") or BY_MATCHER).startswith("scripts/match_outfalls")


def names_another_water(o: dict, waters: dict) -> bool:
    """A match_outfalls name-only match to a water of another name: its words() drop kind words, so 'Onondaga Creek'
    went to Onondaga Lake and 'Upper New York Bay' to Upper Little York Lake. The check is build/status.py's
    (Resolver.row_water): the record's name, or an alias, inside the receiving water's text or the text inside it."""
    if o.get("match") != "name_only":
        return False
    rn = S.norm_name(text_of(o))
    w = waters.get(o.get("water_slug")) or {}
    if not rn or not w:
        return False
    names = [S.norm_name(n) for n in [w.get("name") or ""] + list(w.get("aliases") or []) if n]
    return not any(f" {n} " in f" {rn} " or f" {rn} " in f" {n} " for n in names if n)


def match_cso_row(mt: Matcher, name: str, o: dict, shared: Counter, diag: list, counts, state_build: bool = False) -> None:
    """One CSO registry row (run(), run_state()): match_outfalls' match kept or re-matched, the result written in place.
    state_build: match_outfalls' match is kept only when its slug is an openboatlaunch record (its note says so); a slug
    no water file held when it matched, now an NHD record of the same slug, is matched again here."""
    st = o.get("state")
    if is_matchers(o) and mt.canon(o["water_slug"]) in mt.waters and \
            (not state_build or mt.source_of(mt.canon(o["water_slug"])) == "openboatlaunch"):
        slug0 = mt.canon(o["water_slug"])
        if names_another_water(o, mt.waters):
            why = "a name-only match to a water of another name"
        elif o.get("match") == "name_only" and o.get("lat") is not None and not mt.guard_ok(slug0, o, text_of(o))[0]:
            why = (f"a name-only match to a same-named water the placement guard rejects at EPA's point "
                   f"({mt.guard_ok(slug0, o, text_of(o))[1]})")
        else:
            why = None
        if why:
            o["replaced_match"] = {"water_slug": o["water_slug"], "water_name": o.get("water_name"),
                                   "match": o.get("match"), "by": BY_MATCHER, "why": why}
        else:
            o["water_match"] = note_for_matcher_row(o, mt.waters)
            o["water_matched_by"] = BY_MATCHER
            o.pop("no_water_reason", None)
            counts[st]["matched by match_outfalls.py"] += 1
            return
    if st in N.OTHER_BUILDER and o.get("water_slug"):
        return
    # a row this pass matched before: start again from ECHO's own values
    if o.get("coords_problem") and o.get("echo_lat") is not None:
        o["lat"], o["lon"] = o.pop("echo_lat"), o.pop("echo_lon")
        o.pop("coords_problem", None)
    o["water_slug"] = None
    flags = mt.diagnose(o, shared)
    res = mt.match(o, flags)
    apply(o, res, mt)
    rm = o.get("replaced_match")
    if rm:
        o["water_match"] += (f"; replaces scripts/match_outfalls.py's match by name alone to {rm.get('water_name')} "
                             f"({rm['water_slug']}): {rm['why']}")
        if not o.get("water_slug"):
            o["no_water_reason"] = o["water_match"][len("none: "):]
        flags["wrong_name_match"] = True
    counts[st]["re-matched (match_outfalls.py's name-only match was another water)" if rm else
               "without a water from match_outfalls.py"] += 1
    counts[st]["now with a record" if res.get("slug") else "still without a record"] += 1
    for k, v in flags.items():
        if v:
            counts[st][f"flag: {k}"] += 1
    step = res.get("step") or "none"
    counts[st][f"step: {step}"] += 1
    diag.append({"file": name, "state": st, "permit": o["npdes_permit"], "outfall": o["outfall"],
                 "permittee": o.get("permittee"), "city": o.get("city"), "receiving_water": text_of(o) or None,
                 "lat": o.get("lat") if o.get("lat") is not None else o.get("echo_lat"),
                 "lon": o.get("lon") if o.get("lon") is not None else o.get("echo_lon"),
                 "flags": [k for k, v in flags.items() if v], "step": step, "water_slug": o["water_slug"],
                 "source": mt.source_of(o["water_slug"]) if o["water_slug"] else None,
                 "water_match": o["water_match"], "coords_problem": o.get("coords_problem")})


def run(dry_run: bool = False, offline: bool = False) -> dict:
    mt = Matcher(offline=offline)
    docs = {}
    for name in FILES:
        docs[name] = json.loads((DATA_DIR / name).read_text())
    rows = [(name, o) for name in FILES for o in docs[name]["outfalls"]]
    shared = Counter((o["npdes_permit"], round(o["lat"], 4), round(o["lon"], 4)) for _, o in rows
                     if o.get("lat") is not None and o.get("lon") is not None)
    for _, o in rows:      # a point moved aside by an earlier run counts as the point ECHO gave
        if o.get("echo_lat") is not None and o.get("lat") is None:
            shared[(o["npdes_permit"], round(o["echo_lat"], 4), round(o["echo_lon"], 4))] += 1
    diag, counts = [], defaultdict(Counter)
    for name, o in rows:
        match_cso_row(mt, name, o, shared, diag, counts)
    changed = []
    if not dry_run:
        for name in FILES:
            path = DATA_DIR / name
            new = json.dumps(docs[name], indent=1)
            if new != path.read_text():
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(new)
                tmp.replace(path)
                changed.append(name)
    summary = {"built": now_iso(), "files_written": changed, "dry_run": dry_run,
               "counts": {st: dict(sorted(c.items())) for st, c in sorted(counts.items())}, "outfalls": diag}
    if not dry_run:
        SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY.write_text(json.dumps(summary, indent=1))
    return summary


def match_plant_row(mt: Matcher, o: dict, counts, diag: list, state_build: bool = False) -> None:
    """One plant row (run_plants(), run_state()): the match fields written in place. state_build: as match_cso_row."""
    st = o.get("state")
    counts[st]["plant rows"] += 1
    slug0 = mt.canon(o["water_slug"]) if o.get("water_slug") else None
    mine = bool(slug0 and slug0 in mt.waters and str(o.get("water_matched_by") or "").startswith("scripts/match_outfalls")
                and (not state_build or mt.source_of(slug0) == "openboatlaunch"))
    if mine and o.get("match") in ("geometry+name", "geometry"):
        counts[st]["kept: match_outfalls.py " + o["match"]] += 1
        return
    v = plant_view(o)
    v["water_slug"] = None
    res = match_plant(mt, v, mt.diagnose(v, Counter()))
    if mine:                    # a name-only match from match_outfalls.py: kept only for the water it names
        if res.get("slug") and mt.canon(res["slug"]) == slug0:
            counts[st]["kept: match_outfalls.py name_only"] += 1
            return
        why = "a record of the receiving water's own name was found by the name steps"
        if not res.get("slug"):
            if same_water(o, mt.waters[slug0]):
                counts[st]["kept: match_outfalls.py name_only"] += 1
                return
            d0 = o.get("distance_m")
            why = (f"{o.get('water_name')} ({o['water_slug']}"
                   + (f", {d0 / 1000:.1f} km from the point" if d0 is not None else "") + f") is not the water the permit "
                   f"('{text_of(o) or 'none given'}') and the NHDPlus reach ('{gnis_of(o) or 'none'}') name, and no record of "
                   f"that water was found")
            res = {"slug": None, "reason": "; ".join([why, res["reason"]])}
        o["replaced_match"] = {"water_slug": o["water_slug"], "water_name": o.get("water_name"), "match": o.get("match"),
                               "by": str(o.get("water_matched_by")), "why": why}
        counts[st]["name_only match replaced" if res.get("slug") else "name_only match set aside (another water)"] += 1
    apply(v, res, mt)
    for f in PLANT_FIELDS:
        o[f] = v[f]
    o.pop("no_water_reason", None)
    if v.get("no_water_reason"):
        o["no_water_reason"] = v["no_water_reason"]
    if o.get("replaced_match"):
        o["water_match"] += (f"; replaces scripts/match_outfalls.py's match by name alone to "
                             f"{o['replaced_match'].get('water_name')} ({o['replaced_match']['water_slug']})")
    step = res.get("step") or "none"
    counts[st]["step: " + step] += 1
    counts[st]["now with a record" if res.get("slug") else "still without a record"] += 1
    if not res.get("slug"):
        diag.append({"state": st, "permit": o["npdes_permit"], "outfall": o.get("outfall"), "permittee": o.get("permittee"),
                     "receiving_water": text_of(o) or None, "reach_id": o.get("reach_id"),
                     "reach_gnis_name": o.get("reach_gnis_name"), "coords_from": o.get("coords_from"),
                     "reason": o["no_water_reason"]})


def run_plants(dry_run: bool = False, offline: bool = False) -> dict:
    """The plant rows of the live states (module docstring, "Plant outfalls")."""
    mt = Matcher(offline=offline)
    live = S.states()
    path = DATA_DIR / PLANTS_FILE
    doc = json.loads(path.read_text())
    counts, diag = defaultdict(Counter), []
    for o in doc["outfalls"]:
        st = o.get("state")
        if st not in live or o.get("outfall_kind", "plant") != "plant":
            continue
        match_plant_row(mt, o, counts, diag)
    unrec = defaultdict(lambda: {"outfalls": 0, "permits": set(), "reach_ids": Counter(), "receiving_waters": Counter()})
    for d in diag:                  # the waters that have no record, for the NHD water-record builder
        text, gnis = d["receiving_water"], d["reach_gnis_name"]
        text_names = bool(text) and not why_not_a_name(text)
        if text and not text_names and not (HUC12.match(text) or BASIN.search(text) or NO_WATER_NAMED.match(text)):
            continue                # 'groundwater', a street ditch: no water to make a record for
        # the permit's own name when it names a water the reach is not named for (Pequabuck River on the Farmington's
        # reach), else the reach's name, else the text
        name = text if text_names and (not gnis or S.names_disagree(text, gnis)) else (gnis or text or "(no name)")
        u = unrec[(d["state"], name)]
        u["outfalls"] += 1
        u["permits"].add(d["permit"])
        if d["reach_id"]:
            u["reach_ids"][d["reach_id"]] += 1
        if d["receiving_water"]:
            u["receiving_waters"][d["receiving_water"]] += 1
    unrecorded = [{"state": st, "name": name, "outfalls": u["outfalls"], "permits": sorted(u["permits"]),
                   "reach_ids": dict(u["reach_ids"].most_common()), "receiving_waters": dict(u["receiving_waters"].most_common())}
                  for (st, name), u in sorted(unrec.items(), key=lambda kv: (kv[0][0], -kv[1]["outfalls"], kv[0][1]))]
    changed = []
    if not dry_run:
        old = path.read_text()
        write_plants(path, doc)
        if path.read_text() != old:
            changed.append(PLANTS_FILE)
    summary = {"built": now_iso(), "files_written": changed, "dry_run": dry_run,
               "counts": {st: dict(sorted(c.items())) for st, c in sorted(counts.items())},
               "unrecorded": unrecorded, "outfalls": diag}
    if not dry_run:
        PLANTS_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        PLANTS_SUMMARY.write_text(json.dumps(summary, indent=1))
    return summary


STATE_FILES = ("outfalls-us.json", PLANTS_FILE)      # the national rows a state build ties, with any outfalls-<st>.json


def state_summary_path(states) -> "Path":
    return BUILD_DIR / f"outfall-waters-{'-'.join(s.lower() for s in sorted(states))}.json"


def run_state(states, dry_run: bool = False, offline: bool = False) -> dict:
    """--state XX: every outfall row of these states (data/outfalls-us.json, data/outfalls-plants-us.json and any
    data/outfalls-<st>.json) tied to its water record or given a stated reason, in place, with the same steps as the CSO
    and plant passes (the CSO rows by Matcher.match, the plant rows by match_plant), plus the state build's own: the
    NHD builder's record for the outfall's own EPA reach (Matcher.by_reach) and, for an outfall whose permit names no
    water, the record the builder made at it (Matcher.by_outfall_ref). match_outfalls' matches are kept only where
    their slug is an openboatlaunch record. Rows of other states are not touched."""
    global STATE_TEXT
    states = sorted({x.upper() for x in states})
    STATE_TEXT = True
    try:
        return _run_state(states, dry_run, offline)
    finally:
        STATE_TEXT = False


def _run_state(states, dry_run: bool, offline: bool) -> dict:
    mt = Matcher(offline=offline, states=states)
    names = list(STATE_FILES) + [f"outfalls-{st.lower()}.json" for st in states
                                 if (DATA_DIR / f"outfalls-{st.lower()}.json").exists()]
    docs = {n: json.loads((DATA_DIR / n).read_text()) for n in names}
    counts, diag = defaultdict(Counter), []
    cso = [(n, o) for n in names if n != PLANTS_FILE for o in docs[n]["outfalls"] if (o.get("state") or "").upper() in states]
    shared = Counter((o["npdes_permit"], round(o["lat"], 4), round(o["lon"], 4)) for _, o in cso
                     if o.get("lat") is not None and o.get("lon") is not None)
    for n, o in cso:
        counts[o["state"]][f"rows in {n}"] += 1
        match_cso_row(mt, n, o, shared, diag, counts, state_build=True)
    for o in docs[PLANTS_FILE]["outfalls"]:
        if (o.get("state") or "").upper() in states:
            counts[o["state"]][f"rows in {PLANTS_FILE}"] += 1
            match_plant_row(mt, o, counts, diag, state_build=True)
    for n, o in cso + [(PLANTS_FILE, o) for o in docs[PLANTS_FILE]["outfalls"] if (o.get("state") or "").upper() in states]:
        counts[o["state"]]["tied to a record" if o.get("water_slug") else "with a stated reason"] += 1
    changed = []
    if not dry_run:
        for n in names:
            path = DATA_DIR / n
            old = path.read_text()
            if n == PLANTS_FILE:
                write_plants(path, docs[n])
            else:
                new = json.dumps(docs[n], indent=1)
                if new != old:
                    tmp = path.with_suffix(path.suffix + ".tmp")
                    tmp.write_text(new)
                    tmp.replace(path)
            if path.read_text() != old:
                changed.append(n)
    summary = {"built": now_iso(), "states": states, "files_written": changed, "dry_run": dry_run,
               "counts": {st: dict(sorted(c.items())) for st, c in sorted(counts.items())}, "outfalls": diag}
    if not dry_run:
        out = state_summary_path(states)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=1))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the counts, write nothing")
    ap.add_argument("--offline", action="store_true", help="use only cached responses")
    ap.add_argument("--plants", action="store_true",
                    help="the live states' rows of data/outfalls-plants-us.json instead of the two CSO files")
    ap.add_argument("--state", action="append", metavar="XX",
                    help="a state build (repeatable): every outfall row of the state in data/outfalls-us.json, "
                         "data/outfalls-plants-us.json and data/outfalls-<st>.json, after ingest.waters_from_nhd --state")
    args = ap.parse_args(argv)
    if args.state:
        summary = run_state(args.state, args.dry_run, args.offline)
    else:
        summary = (run_plants if args.plants else run)(args.dry_run, args.offline)
    tot = Counter()
    for st, c in summary["counts"].items():
        tot.update(c)
        print(f"{st}: " + ", ".join(f"{k} {v}" for k, v in c.items()))
    print("ALL: " + ", ".join(f"{k} {v}" for k, v in sorted(tot.items())))
    print(f"written: {', '.join(summary['files_written']) or 'nothing'}"
          + (f"; diagnosis in {N.shown(state_summary_path(args.state) if args.state else PLANTS_SUMMARY if args.plants else SUMMARY)}"
             if not args.dry_run else " (dry run)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
