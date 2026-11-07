"""Write out/ for the site (docs/plan.md §5).

    python -m export.build [--fixtures] [--include-nhdes]

Files:
  events-index.json  one small row per event, columnar: {"fields": INDEX_FIELDS, "rows": [[...]]}
  active.json        the events that make a water red or yellow now: index fields + reasons, kind
                     "event"; and the "discharge likely; no report received" episodes in effect,
                     kind "rain_likely" (no event page: permittee, rainfall record, reasons)
  rain.json          the "discharge likely" caution: per CSO permittee its rainfall threshold and
                     basis, the radar 24-hour total, the 24-hour forecast, its state now; the
                     episodes with their pieces (build/rain_likely.py, docs/rain-likely.md)
  waters/<slug>.json one tracked water: status record, its events (newest first, index fields
                     plus source, waterbody text, outfall, volume text, placement, file) and its
                     history strip and intervals; pages load only this
  events.json        the archive: every normalised event, newest first, each with `fixture`, its placement
                     (water_slugs, water_match), `state` (status.event_state read with raw: an overflow
                     outside its permit's state counts where it happened), `future_start` when its start lies
                     more than a day ahead as published (no status), and `file`. To keep the index small it omits null
                     fields and the long ones in SLIM_DROP (raw, advice text, fetch details);
                     the full record is in `file`.
  events/<f>.json    one event in full (raw included) plus the status intervals it set. <f> is the
                     event_id with every character outside [A-Za-z0-9._-] written as ~XX, the
                     UTF-8 bytes in upper-case hex (':' -> ~3A, '/' -> ~2F, '~' -> ~7E). The
                     encoding is reversible and needs no escaping in a URL; see event_file_name().
  waters.json        index of tracked waters: status now, since, reasons, event and outfall
                     counts, launches, covering sources and their health
  overlays.geojson   tracked waters' geometry (openboatlaunch out/water/<slug>.json, simplified
                     to ~20 m) with slug, name, kind, state, status, since, reason_short,
                     event_count, stale, fixture_only
  reaches.geojson    modeled downstream reaches (build/reaches.py): one feature per active event x
                     reach segment (km from the outfall, arrival hours typical / fast / leading
                     edge, gauge, flow, label per downstream-approach.md section 4) plus a stop
                     marker where the model stops (tidal, lake, 40 km cap). On the Great Lakes
                     (data/rules.json reach.shoreline) a reach is a shoreline stretch (model "shoreline"):
                     a segment each way along the shore from the outfall, no arrival times, a stop marker
                     at each end (cut_reason shoreline_limit or shoreline_end), properties.states and
                     waters (the lake's records in the states it touches); the lake itself is drawn as an
                     outline (overlays display "outline", stretch_model "shoreline")
  reach-paths.geojson every traced outfall path with its status now (replay with history.json reaches)
  reaches/<st>.geojson the same per live state (write_reach_state_files): the traced paths (feature "path"), the
                     active segments and stop markers of every reach that touches the state, each with
                     properties.states (the outfall's state first); a reach crossing a state line is in both files.
                     reaches/index.json lists them {state, file, features, paths, segments, stops, bytes, built}.
                     The national reaches.geojson and reach-paths.geojson stay until the site reads these.
                     An authority's advisory for a named stretch of a river (build/reaches.py "advisory_stretch")
                     is in the same files with properties.reach_kind "advisory_stretch", its category (beach), no
                     arrival hours, the advisory's authority and link, both ends with their basis and citation
                     (properties.stretch) and its own label and stop wording (ADVISORY_LABEL, ADVISORY_STOP_TEXT);
                     its path only while the status build lists it. Sewage features are unchanged.
  launches.geojson   launches on tracked waters with access public, public_restricted, private,
                     commercial or club (openboatlaunch; unknown skipped), plus the editorial rows
                     in data/launches-extra.json (launches no source carries yet; each cites where
                     its position came from): slug, name, kind, town, state, water_slug, access,
                     operator/website/source where present, url (published only);
                     waters/<slug>.json lists the same objects with lat/lon
  advisory-points.geojson  beach, rain and HAB advisories that colour no water (not a lake, pond or
                     reservoir under 50 km², or not placed): one point each with its own status
  monthly-outfalls.json  the outfalls whose latest report is a monthly total (docs/plan.md §2.x: status
                     "monthly", days, month, received_at, label), merged into out/outfalls.json
  outfalls.json      every registry outfall in a live state (export/outfalls.py; docs/national-outfalls.md): kind,
                     status, operator, permit and outfall, receiving water, water record, the rain caution of its
                     operator and the monthly marks; the map's points and the Worker's live layer
  history.json       hourly strips for the last 90 days (build/status.py) plus the intervals
  dischargers.json   data/dischargers.json when it exists, else research/*/dischargers.json merged
                     by npdes_permit; with the outfalls of all its permits from the registry (every
                     data/outfalls-*.json, live states: `outfalls`, CSO and plant; `provisional_outfalls`, the
                     places its overflow reports give, data/build/outfalls-reported.json) and event totals
  sources.json       feeds (events files) with health, and the registry rows (data/sources/*.yaml)
  rules.json         data/rules.json copied unchanged (advisory windows and their rationale)
  conditions.json    conditions at the nearest USGS gauge per tracked water (ingest/gauges.py:
                     flow, water level, temperature, turbidity, conductance, NWS flood stages and
                     the cold / turbid / high-flow flags), shown beside the status, never changing
                     it; also as `conditions` in waters/<slug>.json (null when the water has none)
  csv/               the reports as CSV downloads (export/csv.py, docs/data-downloads.md): water/<slug>.csv,
                     operator/<id>.csv, state/<st>.csv and all-reports-<year>.csv; the site serves them at /csv/...
  coverage.json      what is reported, state by state (docs/plan.md §2.y); rain_caution_states: where the
                     "discharge likely" caution is computed and how (radar, or New Jersey's shared site);
                     states.<ST>.notification_pages: the public-notice page health (ingest/notification_pages.py)
  meta.json          build times, fixture flag, counts by state and status, by event type, csv_files

Placement texts and status lines that quote a record pass through the same redactor as the records' free text
(public_placement, redact_status_texts), and the export ends with a self-check: a name of the owner's blocklist in
events.json, waters/*.json or events/*.json fails it and leaves data/build/export-blocked.json, which stops
scripts/refresh.sh before any upload or deploy (enforce_blocklist; review 2026-11-03 P1-1).

Status comes from data/build/status.json; it is rebuilt here when it is missing, older than an
events file, or built with other fixture/restricted settings. Fixture events (research traces, see
build/fixtures.py) are left out unless --fixtures, which also needs DWW_ALLOW_FIXTURES=1; Events files
marked distribution_discouraged (NHDES Healthy Swimming) are left out unless --include-nhdes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from build import status as status_mod
from build.redact import BlockScan, Redactor, blocklist, quote_swaps, redact_events, redactor_for
from common import scrub_residence_numbers
from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, OUT_DIR, OUTFALL_REGISTRY_GLOB, OUTFALL_REGISTRY_SKIPPED,
                    PROVISIONAL_FIELDS, REPORTED_OUTFALLS, ROOT, STATE_CODE, discharger_alias_map, is_provisional, now_iso, read_json,
                    scrub_names, split_path_notes, strip_personal, write_json)
from export import outfalls as outfalls_mod

SIMPLIFY_DEG = 20 / 111_320          # ~20 m
COORD_DIGITS = 5                     # ~1 m
STATUS_ORDER = {"red": 0, "yellow": 1, "unresolved": 2, "monthly": 3, "grey": 4}
ACTIVE_STATES = ("red", "yellow", "unresolved")
REGISTRY_KEYS = ["id", "name", "url", "homepage", "kind", "level", "cadence", "license", "attribution",
                 "enabled", "role", "event_types", "states", "access"]
SAFE = re.compile(r"[A-Za-z0-9._-]")
SLIM_DROP = {"raw", "advice_text", "advice_window_basis", "fetched_at", "coord_source", "coord_precision_m",
             "placement_note"}
INDEX_FIELDS = ["event_id", "event_type", "status", "state", "started_at", "ended_at", "water_slugs",
                "discharger_name", "npdes_permit", "outfall_id", "volume_gal", "lat", "lon", "fixture"]
WATER_EVENT_EXTRA = ["source_id", "waterbody_text", "outfall_name", "volume_text", "water_match", "superseded",
                     "duplicate_of", "file"]
SLIM_KEEP = {"event_id", "source_id", "event_type", "status", "water_slugs", "started_at", "ended_at", "fixture", "file"}


def event_file_name(event_id: str) -> str:
    return "".join(c if SAFE.fullmatch(c) else "".join(f"~{b:02X}" for b in c.encode()) for c in event_id) + ".json"


def event_id_from_file(name: str) -> str:
    stem = name[:-5] if name.endswith(".json") else name
    return re.sub(r"(?:~[0-9A-F]{2})+", lambda m: bytes.fromhex(m.group(0).replace("~", "")).decode(), stem)


def index_obj(rec: dict) -> dict:
    o = {k: rec.get(k) for k in INDEX_FIELDS}
    o["state"] = rec.get("state") or status_mod.event_state(rec)     # public_record's, read with raw
    for k in ("lat", "lon"):
        if o[k] is not None:
            o[k] = round(float(o[k]), 5)
    return o


def time_key(rec: dict) -> float:
    for k in ("started_at", "reported_at", "published_at"):
        t = status_mod.parse_time(rec.get(k))
        if t:
            return t.timestamp()
    return float("-inf")


def hours_text(h) -> str:
    if h is None:
        return "an unknown time"
    return "under an hour" if h < 1 else f"about {round(h)} hour{'s' if round(h) != 1 else ''}"


STOP_TEXT = {
    "tidal": "Below this point the river is tidal. Water moves back and forth with the tide and wind, so we do not "
             "model where the discharge goes. See the official notice and local beach or shellfish advisories.",
    "estuary": "Below this point the water is an estuary or the sea. Water moves back and forth with the tide and "
               "wind, so we do not model where the discharge goes. See the official notice and local beach or "
               "shellfish advisories.",
    "lake_or_reservoir": "Below this point the river enters a lake or reservoir. Water does not move in a line there, "
                         "so we do not model where the discharge goes. See the official notice.",
    "cap_km": "Model stops here ({cap:g} km from the outfall): the cap is a product decision, not a sign the water "
              "is clean below this point.",
    "end_of_trace": "The mapped river network ends here.",
    "attributes unavailable": "The model stops here: the stream network's attributes (tidal, lake) are not available "
                              "for the next stretch, so we cannot say how the water moves beyond this point.",
}
LINE_TEXT = "Modeled downstream path (estimate, not verified by sampling)."
# shoreline stretches on the Great Lakes (build/shoreline.py; data/rules.json reach.shoreline): their own wording
SHORE_STOP_TEXT = {
    "shoreline_limit": "The modeled shoreline stretch stops here ({each:g} km along the shore from the outfall): the "
                       "distance is this site's estimate from published studies of Great Lakes overflows, not a sign "
                       "the water is clean beyond this point.",
    "shoreline_end": "The modeled shoreline stretch stops here, where the mapped shore of this lake ends. "
                     "Contamination can travel beyond this point.",
}
SHORE_LINE_TEXT = "Modeled shoreline stretch (estimate, not verified by sampling)."
# the open ocean (data/rules.json reach.shoreline.oceans): the same stretch on the state's ocean shore, in its own words
OCEAN_STOP_TEXT = {
    "shoreline_limit": "The modeled shoreline stretch stops here ({each:g} km along the shore from the point): the "
                       "distance is this site's estimate from published studies of sewage carried along ocean beaches, "
                       "not a sign the water is clean beyond this point.",
    "shoreline_end": "The modeled shoreline stretch stops here, where the state's mapped coast ends. Contamination can "
                     "travel beyond this point.",
}
# a sound under the lake model (Puget Sound; reach.shoreline.lakes with kinds ["sound"], 2026-11-06): its own words
SOUND_STOP_TEXT = {
    "shoreline_limit": "The modeled shoreline stretch stops here ({each:g} km along the shore from the outfall): the "
                       "distance is this site's estimate from published studies of sewage carried along large lakes' "
                       "and ocean shores, not a sign the water is clean beyond this point.",
    "shoreline_end": "The modeled shoreline stretch stops here, where the mapped shore of this sound ends. "
                     "Contamination can travel beyond this point.",
}
SOUND_LABEL = ("Modeled stretch of {lake} shore at {where_from}. Tides and wind move the water along the shore, and can "
               "carry sewage either way, so this stretch runs up to {each:g} km each way from that point, a distance "
               "this site estimates from published studies of sewage along large lakes' and ocean shores. This is an "
               "estimate, not a measurement of bacteria. The shore is not necessarily unsafe here, and the rest of the "
               "sound is not necessarily safe.")
OCEAN_LABEL = ("Modeled stretch of {lake} shore at {where_from}. Waves and wind drive currents along an ocean beach "
               "that can carry sewage either way, so this stretch runs up to {each:g} km each way from that point, a "
               "distance this site estimates from published studies of sewage along ocean beaches. This is an "
               "estimate, not a measurement of bacteria. The shore is not necessarily unsafe here, and the rest of the "
               "coast and the open water are not necessarily safe.")
# a bay under the lake model (data/rules.json reach.shoreline.lakes with kinds ["bay"]: San Francisco Bay), its own words
BAY_STOP_TEXT = {
    "shoreline_limit": "The modeled shoreline stretch stops here ({each:g} km along the shore from the outfall): the "
                       "distance is this site's estimate from published studies of sewage along lake and ocean shores, "
                       "not a sign the water is clean beyond this point.",
    "shoreline_end": "The modeled shoreline stretch stops here, where the mapped shore of this bay ends. "
                     "Contamination can travel beyond this point.",
}
BAY_LABEL = ("Modeled stretch of {lake} shore at {where_from}. Tides and wind move the bay's water back and forth along "
             "the shore, so this stretch runs up to {each:g} km each way from that point, a distance this site uses on "
             "large lakes and the ocean shore and has not measured in this bay. This is an estimate, not a measurement "
             "of bacteria. The shore is not necessarily unsafe here, and the rest of the bay is not necessarily safe.")
SHORE_LABEL = ("Modeled stretch of {lake} shore at {where_from}. Wind-driven currents along the shore can carry sewage "
               "either way, so this stretch runs up to {each:g} km each way from that point, a distance this site "
               "estimates from published studies of Great Lakes overflows. This is an estimate, not a measurement of "
               "bacteria. The shore is not necessarily unsafe here, and the rest of the lake is not necessarily safe.")


# an authority's advisory for a named stretch of a river (build/reaches.py ADVISORY_KIND): its own kind
# (properties.reach_kind "advisory_stretch"), the advisory's category (beach), no travel time, and its own words
ADVISORY_KIND = "advisory_stretch"
ADVISORY_LINE_TEXT = "Stretch named in an authority's advisory, drawn along the mapped river channel."
ADVISORY_LABEL = ("{authority}'s {noun} covers the {water} from the {start} to the {end}. This line follows that "
                  "stretch along the mapped river channel (U.S. Geological Survey NHDPlus), from the point of the "
                  "{start} to the point of the {end}; the advisory's own words set its extent.{short} "
                  "Upstream end: {start_source}. Downstream end: {end_source}.")
ADVISORY_SHORT = " The line stops short of the {end}: {why}."
ADVISORY_STOP_TEXT = {
    "stretch_end": "The advisory's stretch ends here, at the {end}, as {authority} names it. It marks the end of the "
                   "advisory's stretch, not the end of any contamination.",
    "cap_km": "The line stops here, {km:g} km below the {start}: this site draws no stretch longer than {cap:g} km. The "
              "advisory names a stretch that runs on to the {end}.",
    "tidal": "The line stops here, where the mapped river becomes tidal. The advisory names a stretch that runs on to "
             "the {end}.",
    "estuary": "The line stops here, where the mapped river meets an estuary or the sea. The advisory names a stretch "
               "that runs on to the {end}.",
    "lake_or_reservoir": "The line stops here, where the mapped river enters a lake or reservoir. The advisory names a "
                         "stretch that runs on to the {end}.",
}
ADVISORY_STOP_OTHER = ("The line stops here, where the mapped river network gives out. The advisory names a stretch that "
                       "runs on to the {end}.")


def advisory_words(r: dict, cap: float, e: dict | None = None) -> dict:
    """The label, stop label and public properties of an advisory stretch (ADVISORY_KIND)."""
    adv, st = r.get("advisory") or {}, r.get("stretch") or {}
    a, b = st.get("start") or {}, st.get("end") or {}
    authority = re.sub(r"\s*\([^)]*\)\s*$", "", str(adv.get("authority") or "The authority")).strip()
    noun = str((((e or {}).get("raw") or {}).get("advisory_noun")) or "advisory").lower()
    water = st.get("water") or r.get("river") or "river"

    def cite(x):
        return "; ".join(v for v in (x.get("source"), x.get("url")) if v) or "not given"
    end_info = (r.get("stretch_trace") or {}).get("end") or {}
    cut = r.get("cut_reason")
    names = {"authority": authority, "water": water, "start": a.get("name") or "upstream end",
             "end": b.get("name") or "downstream end", "cap": cap, "km": float(r.get("length_km") or 0)}
    stop = ADVISORY_STOP_TEXT.get(cut, ADVISORY_STOP_OTHER).format(**names)
    short = "" if cut == "stretch_end" else ADVISORY_SHORT.format(
        end=names["end"], why={"cap_km": f"this site draws no stretch longer than {cap:g} km",
                               "tidal": "the mapped river becomes tidal",
                               "estuary": "the mapped river meets an estuary or the sea",
                               "lake_or_reservoir": "the mapped river enters a lake or reservoir"}.get(
                                   cut, "the mapped river network gives out"))
    label = ADVISORY_LABEL.format(**names, noun=noun, short=short, start_source=cite(a), end_source=cite(b))
    props = {"reach_kind": ADVISORY_KIND, "event_id": adv.get("event_id"), "authority": authority,
             "source_url": adv.get("source_url"),
             "stretch": {"water": water,
                         "start": {k: a.get(k) for k in ("name", "lat", "lon", "basis", "source", "url")},
                         "end": {k: b.get(k) for k in ("name", "lat", "lon", "basis", "source", "url")},
                         "end_reached": bool(end_info.get("reached")), "end_km": end_info.get("km"),
                         **({"end_beyond_cap": True} if end_info.get("beyond_cap") else {})},
             "rule_applied": r.get("rule")}
    return {"label": label, "stop_label": stop, "props": props}


def advisory_event_features(a: dict, r: dict, e: dict, waters_by_reach: dict, cap: float) -> list:
    """An active advisory's features on its named stretch: one segment per flowline (no travel time) and a stop
    marker at the end, in the advisory's category."""
    w = advisory_words(r, cap, e)
    common_props = {"category": a.get("category") or "beach", "event_id": a["event_id"], "reach": a["reach"],
                    "status": a["status"], **w["props"],
                    "waters": waters_by_reach.get(a["reach"]) or [r.get("water_slug")]}
    out = []
    for sg in r["segments"]:
        out.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": sg["coords"]},
                    "properties": {**common_props, "feature": "segment", "rule": a["rule"], "short": a["short"],
                                   "outfall": None, "permit": None, "river": r.get("river"), "comid": sg.get("comid"),
                                   "km_from_outfall": sg["km_end"], "km_start": sg["km_start"],
                                   "arrival_hours_typical": None, "arrival_hours_fast": None,
                                   "arrival_hours_leading_edge": None, "reached_fast": None, "reached_typical": None,
                                   "hours_since_start": a.get("hours_since_start"), "gauge": None, "flow_cfs": None,
                                   "flow_time": None, "flow_basis": None, "cut_reason": r.get("cut_reason"),
                                   "line_text": ADVISORY_LINE_TEXT, "label": w["label"],
                                   "fixture": bool(e.get("fixture"))}})
    out.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": r["segments"][-1]["coords"][-1]},
                "properties": {**common_props, "feature": "stop", "cut_reason": r.get("cut_reason"),
                               "km_from_outfall": r.get("length_km"), "label": w["stop_label"]}})
    return out


def reach_waters(st: dict) -> dict[str, list[str]]:
    """reach key -> the water slugs whose status that reach feeds (status.json waters[slug].reaches, inverted),
    the outfall's own water first, then downstream waters in slug order."""
    own = {k: (v or {}).get("water_slug") for k, v in (st.get("reaches") or {}).items()}
    out: dict[str, set[str]] = defaultdict(set)
    for slug, w in (st.get("waters") or {}).items():
        for k in (w or {}).get("reaches") or []:
            out[k].add(slug)
    return {k: ([own[k]] if own.get(k) else []) + sorted(s - {own.get(k)}) for k, s in out.items()}


def reach_features(st: dict, by_event: dict, cached: dict | None = None) -> tuple[list, list]:
    """(active event x segment features plus stop markers, one path feature per traced outfall). cached: the trace
    records (build/reaches.load_reaches()), read here when not given."""
    from build import reaches as reaches_mod
    cached = reaches_mod.load_reaches() if cached is None else cached
    cap = reaches_mod.cap_km()
    waters_by_reach = reach_waters(st)
    feats = []
    for a in st.get("reach_events_active") or []:
        r = cached.get(a["reach"])
        if not r or not r.get("segments"):
            continue
        e = by_event.get(a["event_id"]) or {}
        if r.get("model") == SHORELINE:
            feats.extend(shore_event_features(a, r, e, waters_by_reach))
            continue
        if r.get("kind") == ADVISORY_KIND:
            feats.extend(advisory_event_features(a, r, e, waters_by_reach, cap))
            continue
        start = status_mod.parse_time(e.get("started_at"))
        start_txt = start.astimezone(status_mod.LOCAL).strftime("%b %-d %H:%M") if start else "an unknown time"
        flow_txt = (f"at the river flow measured at {a.get('gauge_name') or a.get('gauge')} ({a['flow_cfs']:g} cfs) "
                    f"at {a.get('flow_time')}" if a.get("gauge") else
                    "at the river's average flow (NHDPlus mean annual; no current gauge reading)")
        for sg, band in zip(r["segments"], a["segments"]):
            where_from = f"outfall {r['outfall']}" if r.get("outfall") else "the reported location"
            if band["hours_typical"] is None:
                label = (f"Modeled downstream of {where_from}. No travel time is given here: the stream network "
                         f"attributes it needs (drainage area, mean flow) are missing for this stretch. The river is "
                         f"not necessarily unsafe here, and it is not necessarily safe outside the line.")
            else:
                label = (f"If sewage entered the river at {where_from} at {start_txt}, water from that point "
                         f"would typically reach here in {hours_text(band['hours_typical'])} (it could be as soon as "
                         f"{hours_text(band['hours_fast'])}) {flow_txt}. This is a calculation from published USGS "
                         f"methods, not a measurement of bacteria. The river is not necessarily unsafe here, and it "
                         f"is not necessarily safe outside the line.")
            feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": sg["coords"]},
                          "properties": {"category": "sewage",
                              "feature": "segment", "event_id": a["event_id"], "reach": a["reach"], "status": a["status"],
                              "rule": a["rule"], "short": a["short"], "outfall": r["outfall"], "permit": r["permit"],
                              "river": r.get("river"), "waters": waters_by_reach.get(a["reach"]) or [r.get("water_slug")],
                              "comid": sg["comid"], "km_from_outfall": sg["km_end"],
                              "km_start": sg["km_start"], "arrival_hours_typical": band["hours_typical"],
                              "arrival_hours_fast": band["hours_fast"],
                              "arrival_hours_leading_edge": band["hours_leading_edge"],
                              "reached_fast": band["reached_fast"], "reached_typical": band["reached_typical"],
                              "hours_since_start": a["hours_since_start"], "gauge": a.get("gauge"),
                              "flow_cfs": a.get("flow_cfs"), "flow_time": a.get("flow_time"),
                              "flow_basis": a.get("flow_basis"), "cut_reason": r.get("cut_reason"),
                              "line_text": LINE_TEXT, "label": label, "fixture": bool(e.get("fixture"))}})
        last = r["segments"][-1]["coords"][-1]
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": last},
                      "properties": {"category": "sewage", "feature": "stop", "event_id": a["event_id"], "reach": a["reach"],
                                     "status": a["status"], "cut_reason": r.get("cut_reason"),
                                     "km_from_outfall": r.get("length_km"),
                                     "label": STOP_TEXT.get(r.get("cut_reason"), "").format(cap=cap)}})
    status_by_reach = st.get("reaches") or {}
    paths = []
    for key, r in sorted(cached.items()):
        if not r.get("segments"):
            continue
        if r.get("kind") == ADVISORY_KIND:
            if key in status_by_reach:          # an advisory's stretch: while the status build lists it
                paths.append(advisory_path(key, r, status_by_reach[key], waters_by_reach, cap,
                                           by_event.get((r.get("advisory") or {}).get("event_id"))))
            continue
        paths.append({"type": "Feature", "id": key,
                      "geometry": {"type": "MultiLineString", "coordinates": [sg["coords"] for sg in r["segments"]]},
                      "properties": {"category": "sewage", "reach": key, "permit": r.get("permit"), "outfall": r.get("outfall"),
                                     "water_slug": r.get("water_slug"), "river": r.get("river"),
                                     # every water record the modeled stretch runs through (the status build's
                                     # per-water reach list, inverted), the outfall's own water first: a reach
                                     # that crosses a state line belongs to the downstream state's page too
                                     "waters": waters_by_reach.get(key) or [r.get("water_slug")],
                                     "length_km": r.get("length_km"), "cut_reason": r.get("cut_reason"),
                                     "status": (status_by_reach.get(key) or {}).get("status", "grey"),
                                     # yellow only from "Discharge likely: heavy rain, no report received"
                                     "rain_likely": bool((status_by_reach.get(key) or {}).get("rain_likely"))
                                     and not (status_by_reach.get(key) or {}).get("active"),
                                     "segments_km": [[sg["km_start"], sg["km_end"]] for sg in r["segments"]],
                                     "stop_label": STOP_TEXT.get(r.get("cut_reason"), "").format(cap=cap),
                                     "line_text": LINE_TEXT, **shore_path_props(r)}})
    return feats, paths


def advisory_path(key: str, r: dict, sr: dict, waters_by_reach: dict, cap: float, e: dict | None) -> dict:
    """The path feature of an advisory's named stretch (ADVISORY_KIND): its status now, kind, category and words."""
    w = advisory_words(r, cap, e)
    return {"type": "Feature", "id": key,
            "geometry": {"type": "MultiLineString", "coordinates": [sg["coords"] for sg in r["segments"]]},
            "properties": {"category": sr.get("category") or "beach", "reach": key, "permit": None, "outfall": None,
                           "water_slug": r.get("water_slug"), "river": r.get("river"),
                           "waters": waters_by_reach.get(key) or [r.get("water_slug")],
                           "length_km": r.get("length_km"), "cut_reason": r.get("cut_reason"),
                           "status": sr.get("status", "grey"), "rain_likely": False,
                           "segments_km": [[sg["km_start"], sg["km_end"]] for sg in r["segments"]],
                           "stop_label": w["stop_label"], "line_text": ADVISORY_LINE_TEXT, "label": w["label"],
                           **w["props"]}}


SHORELINE = "shoreline"


def shore_stop_text(r: dict) -> dict:
    """The stop wording of a shoreline stretch: the ocean's, a bay's or a sound's (under the lake model) or a lake's."""
    return (OCEAN_STOP_TEXT if r.get("ocean") else BAY_STOP_TEXT if r.get("bay") else SOUND_STOP_TEXT if r.get("sound")
            else SHORE_STOP_TEXT)


def shore_path_props(r: dict) -> dict:
    """The path properties of a shoreline stretch that differ from a river trace's (none for a river trace)."""
    if r.get("model") != SHORELINE:
        return {}
    each = float(r.get("each_way_km") or r.get("cap_km") or 0)
    stop_text = shore_stop_text(r)
    return {"model": SHORELINE, "states": list(r.get("states") or []), "lake": r.get("lake") or r.get("river"),
            "each_way_km": each, "line_text": SHORE_LINE_TEXT, **({"ocean": True} if r.get("ocean") else {}),
            **({"bay": True} if r.get("bay") else {}),
            **({"sound": True} if r.get("sound") else {}),
            "stops": [{"coordinates": s["coords"], "km_from_outfall": s.get("km_from_outfall"),
                       "cut_reason": s.get("cut_reason"),
                       "label": stop_text.get(s.get("cut_reason"), "").format(each=each)}
                      for s in r.get("stops") or []],
            "stop_label": "; ".join(dict.fromkeys(stop_text.get(s.get("cut_reason"), "").format(each=each)
                                                  for s in r.get("stops") or [])) or None}


def shore_event_features(a: dict, r: dict, e: dict, waters_by_reach: dict) -> list:
    """An active event's features on a shoreline stretch: one segment per side of the outfall (no travel time: a
    lake shore has no flow to time) and a stop marker at each end, with the lake's states."""
    each = float(r.get("each_way_km") or r.get("cap_km") or 0)
    where_from = f"outfall {r['outfall']}" if r.get("outfall") else "the reported location"
    lake = r.get("lake") or r.get("river") or ("the ocean" if r.get("ocean") else "the bay" if r.get("bay") else
                                               "the sound" if r.get("sound") else "the lake")
    label = (OCEAN_LABEL if r.get("ocean") else BAY_LABEL if r.get("bay") else SOUND_LABEL if r.get("sound") else
             SHORE_LABEL).format(lake=lake, where_from=where_from, each=each)
    stop_text = shore_stop_text(r)
    common_props = {"category": "sewage", "event_id": a["event_id"], "reach": a["reach"], "status": a["status"],
                    "model": SHORELINE, "states": list(r.get("states") or []),
                    "waters": waters_by_reach.get(a["reach"]) or list(r.get("waters") or [r.get("water_slug")])}
    out = []
    for sg in r["segments"]:
        out.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": sg["coords"]},
                    "properties": {**common_props, "feature": "segment", "rule": a["rule"], "short": a["short"],
                                   "outfall": r.get("outfall"), "permit": r.get("permit"), "river": lake,
                                   "comid": None, "km_from_outfall": sg["km_end"], "km_start": sg["km_start"],
                                   "arrival_hours_typical": None, "arrival_hours_fast": None,
                                   "arrival_hours_leading_edge": None, "reached_fast": None, "reached_typical": None,
                                   "hours_since_start": a["hours_since_start"], "gauge": None, "flow_cfs": None,
                                   "flow_time": None, "flow_basis": None, "cut_reason": r.get("cut_reason"),
                                   "line_text": SHORE_LINE_TEXT, "label": label, "fixture": bool(e.get("fixture"))}})
    for s in r.get("stops") or []:
        out.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": s["coords"]},
                    "properties": {**common_props, "feature": "stop", "cut_reason": s.get("cut_reason"),
                                   "km_from_outfall": s.get("km_from_outfall"),
                                   "label": stop_text.get(s.get("cut_reason"), "").format(each=each)}})
    return out


# ---------------------------------------------------------------- the reaches per state

# out/reaches/<st>.geojson, one per live state, and out/reaches/index.json (docs/national-approach.md §7 item 1): the
# map loads a state's file instead of every reach in the country. The national out/reaches.geojson and
# out/reach-paths.geojson are still written unchanged until the site and the Worker read the state files.
REACH_STATE_DIR = "reaches"
REACH_STATE_FILE = re.compile(r"^[a-z]{2}\.geojson$")
REACH_STATE_MAX = 64            # 50 states, DC and the territories: scripts/upload-current.sh puts no more than this


def reach_states(rec: dict | None, waters: list[str], state_of) -> list[str]:
    """The states a reach touches: its outfall's first (the trace record's state, else its permit's two letters),
    then the state of every water record the modeled stretch runs through (state_of: slug -> state or None),
    sorted. A reach that crosses a state line names both."""
    rec = rec or {}
    own = str(rec.get("state") or "").upper()
    if not STATE_CODE.fullmatch(own):
        own = str(rec.get("permit") or "")[:2].upper()
    head = [own] if STATE_CODE.fullmatch(own) else []
    rest = {state_of(s) for s in waters or [] if s} - {None, ""} - set(head)
    # a shoreline stretch names the states whose shore it runs along (build/shoreline.py), with or without a record
    rest |= {str(x).upper() for x in rec.get("states") or [] if STATE_CODE.fullmatch(str(x).upper())} - set(head)
    return head + sorted(rest)


def water_state_of(st: dict, live: set[str]):
    """slug -> its state: the status build's water record, else a slug ending in a live state's code
    ("susquehanna-river-ny"), as the site's map reads it; None when neither says."""
    known = {slug: str((w or {}).get("state") or "").upper() for slug, w in (st.get("waters") or {}).items()}

    def state_of(slug: str) -> str | None:
        v = known.get(slug)
        if v and STATE_CODE.fullmatch(v):
            return v
        m = re.search(r"-([a-z]{2})$", str(slug or ""))
        return m.group(1).upper() if m and m.group(1).upper() in live else None
    return state_of


def reaches_by_state(feats: list, paths: list, st: dict, cached: dict, live: set[str]) -> tuple[dict[str, list], list]:
    """({state: features} for every live state (an empty list when none touches it), the reach keys no live state
    could be found for). The traced paths (marked feature "path") come first, then the active event segments and stop
    markers, each in every state file its reach touches, with those states in properties.states. The features are
    copies: the national files are not changed."""
    live = {str(s).upper() for s in live}
    state_of = water_state_of(st, live)
    by_reach = reach_waters(st)
    memo: dict[str, list[str]] = {}

    def states_of(f: dict) -> list[str]:
        p = f.get("properties") or {}
        key = p.get("reach") or f.get("id")
        if key not in memo:
            rec = cached.get(key) or {}
            waters = p.get("waters") or by_reach.get(key) or [rec.get("water_slug") or p.get("water_slug")]
            memo[key] = reach_states(rec or {"permit": p.get("permit")}, waters, state_of)
        return memo[key]

    out: dict[str, list] = {s: [] for s in sorted(live)}
    homeless: dict[str, None] = {}
    for kind, group in (("path", paths), (None, feats)):
        for f in group:
            sts = states_of(f)
            props = {**(f.get("properties") or {}), **({"feature": kind} if kind else {}), "states": sts}
            g = {**f, "properties": props}
            placed = [s for s in sts if s in out]
            for s in placed:
                out[s].append(g)
            if not placed:
                homeless[str(props.get("reach") or f.get("id"))] = None
    return out, list(homeless)


def write_reach_state_files(by_state: dict[str, list], out_dir: Path = OUT_DIR, built: str | None = None,
                            without_state: list | None = None) -> dict:
    """out/reaches/<st>.geojson per state and out/reaches/index.json {built, national, paths, states_property,
    files: [{state, file, features, paths, segments, stops, bytes, built}], without_state}; a state file left from
    an earlier export whose state is no longer listed is removed. without_state: the reach keys in no state file
    (counted in the index; they stay in the national files). Returns the index."""
    if len(by_state) > REACH_STATE_MAX:
        raise ValueError(f"reaches per state: {len(by_state)} states, more than {REACH_STATE_MAX}")
    d = Path(out_dir) / REACH_STATE_DIR
    built = built or now_iso()
    files, written = [], set()
    for s in sorted(by_state):
        if not STATE_CODE.fullmatch(s):
            raise ValueError(f"reaches per state: {s!r} is not a state code")
        name = f"{s.lower()}.geojson"
        assert REACH_STATE_FILE.fullmatch(name)
        path = d / name
        fs = by_state[s]
        write_compact(path, {"type": "FeatureCollection", "state": s, "built": built, "features": fs})
        written.add(name)
        kinds = Counter((f.get("properties") or {}).get("feature") for f in fs)
        files.append({"state": s, "file": f"{REACH_STATE_DIR}/{name}", "features": len(fs), "paths": kinds["path"],
                      "segments": kinds["segment"], "stops": kinds["stop"], "bytes": path.stat().st_size, "built": built})
    for p in d.glob("*.geojson"):
        if p.name not in written:
            p.unlink()
    index = {"built": built, "national": "reaches.geojson", "paths": "reach-paths.geojson", "states_property": "states",
             "about": "Modeled downstream reaches per state: the traced paths (feature \"path\"), the active events' "
                      "segments and the stop markers. A reach is in the file of every state it touches.",
             "files": files, "without_state": len(without_state or [])}
    write_compact(d / "index.json", index)
    return index


# ---------------------------------------------------------------- public wording

RULES_FILE_PREFIXES = ("red.by_state.", "red.by_discharger.", "red.none", "yellow.", "unresolved.", "rain_likely")
# feed meta keys that describe the source to the public; the rest is ingester bookkeeping
PUBLIC_FEED_META = {"credit", "disclaimer", "terms", "attribution", "license", "url", "api", "portal", "homepage",
                    "cadence", "poll_cadence", "time_note", "timezone", "timezone_note", "window", "since",
                    # what a feed reads but does not show, counted (ingest/fl_dep_pnp.py left_out_meta)
                    "left_out", "listed_without_status", "left_out_note"}
INTERNAL_WORDING = re.compile(r"\bowner(?:'s|s)?\b|\bdocs/|(?<![\w.-])research/|\bfixture|\bcoordinator", re.I)  # "ownership" in a quoted term is fine
ARCGIS_OWNER = re.compile(r"\s*\((?:[^()]*\bArcGIS\b[^()]*\bowner\b[^()]*)\)", re.I)


# top-level free text that can quote a record (outfall and water names, advice, volume wording)
FREE_TEXT_FIELDS = ("outfall_name", "waterbody_text", "advice_text", "material", "volume_text")


def public_event(e: dict) -> dict:
    """An event as out/ carries it: raw with personal fields and staff names stripped again under the
    current rules (events files written before a rule was added are covered too) and without
    pipeline notes that name repository files; staff names, and the house number of an address tied to a residence or
    a resident (common.scrub_residence_numbers: raw loses it, so must an outfall name or a water text quoting the same
    sentence), scrubbed from the free-text fields."""
    raw, _notes = split_path_notes(strip_personal(e.get("raw") or {}))
    out = {**e, "raw": raw}
    for k in FREE_TEXT_FIELDS:
        if isinstance(out.get(k), str):
            out[k] = scrub_residence_numbers(scrub_names(out[k]))
    return out


# Repository paths in the placement texts (review 2026-11-03 P3-7): the registry files are named in words, any
# other path is dropped. The event page hid them (site publicText), the archive JSON served them as written.
OUTFALL_FILE = r"data/outfalls-[\w-]+\.json"
REPO_PATH = re.compile(r"(?<![\w.-])(?:data|docs|research|pipeline|out|site)/[\w./<>-]*\.(?:json|geojson|csv|py|md|yaml|ts)\b")
NOTE_FIELDS = ("placement_note", "unplaced_reason", "no_receiving_water")


# The registries in public words (wording scan 2026-11-03; copy review 2026-11-02, "EPA and state outlet records"):
# the pipeline's "outfall registry", "registry outfalls" and "operator registry" are its own file names for them.
REGISTRY_WORDS = (
    (re.compile(r"\bno outfall the (?:outfall )?registry lists\b"), "no outlet listed in EPA and state records"),
    (re.compile(r"\bregistry outfalls\b"), "listed outlets"),
    (re.compile(r"\(outfall registry\)"), "(EPA and state outlet records)"),
    (re.compile(r"\b(?:the|an?) outfall registry\b"), "the outlet list in EPA and state records"),
    (re.compile(r"\b(?:ECHO )?outfall registry\b"), "outlet list in EPA and state records"),
    (re.compile(r"\bour operator registry\b"), "our list of sewer operators"),
    (re.compile(r"\bthe operator registry\b"), "our list of sewer operators"),
)


def public_note(t):
    """A placement text without repository paths: "(data/outfalls-new-england.json)" and "; data/outfalls-new-england.json)" after a
    text that already names the outlet list are dropped, data/dischargers.json reads "our list of sewer operators",
    an outfall file elsewhere "the outlet list in EPA and state records", and any other path goes; the registries
    the pipeline names in words ("outfall registry", "registry outfalls") are named as the public knows them."""
    if not isinstance(t, str):
        return t
    if "/" in t:
        t = re.sub(rf"\s*\((?:{OUTFALL_FILE}(?:,\s*)?)+\)", "", t)
        t = re.sub(rf";\s*(?:{OUTFALL_FILE}(?:,\s*)?)+(?=\))", "", t)
        t = re.sub(rf"(?:{OUTFALL_FILE}(?:,\s*)?)+", "the outfall registry", t)
        t = t.replace("data/dischargers.json", "our operator registry")
        t = REPO_PATH.sub("", t)
        t = re.sub(r"\(\s*[,;]?\s*\)", "", t)
        t = re.sub(r"\s+([,;:)])", r"\1", re.sub(r"\(\s+", "(", t))
    if "registry" in t:
        for pat, words in REGISTRY_WORDS:
            t = pat.sub(words, t)
    return re.sub(r"\s{2,}", " ", t).strip()


def note_wording(rec: dict) -> list[str]:
    """The pipeline texts of a public record (NOTE_FIELDS, set_aside reasons) that still carry internal wording
    or a repository path (the export's self-check; source quotes in raw and the free-text fields are not ours)."""
    texts = [(k, rec.get(k)) for k in NOTE_FIELDS] + [("set_aside", a.get("reason")) for a in rec.get("set_aside") or []
                                                       if isinstance(a, dict)]
    return [k for k, v in texts if isinstance(v, str) and (INTERNAL_WORDING.search(v) or REPO_PATH.search(v))]


# the placement texts a public record carries (from status.json placements); each can quote the record's
# receiving-water, outfall or volume text, so each goes through the record's redaction (public_record)
PLACEMENT_TEXT_KEYS = ("note", "unplaced_reason", "no_receiving_water")


def public_placement(pl: dict, r: Redactor, swaps=()) -> dict:
    """A placement (status.json placements[event_id]) with every text that can quote the source (note,
    unplaced_reason, no_receiving_water, set_aside[].reason) through the same redaction as the record's
    free-text fields (Redactor.note with the record's quote_swaps; review 2026-11-03 P1-1), and the repository
    paths in them reworded (public_note). The input is not changed."""
    out = dict(pl)
    for k in PLACEMENT_TEXT_KEYS:
        if isinstance(out.get(k), str):
            out[k] = public_note(r.note(out[k], swaps))
    if out.get("set_aside"):
        out["set_aside"] = [{**a, "reason": public_note(r.note(a.get("reason"), swaps))} if isinstance(a, dict) else a
                            for a in out["set_aside"]]
    return out


def public_record(e: dict, pl: dict, r: Redactor, swaps=()) -> dict:
    """The record out/ writes for one event (redacted already): its own fields without "_" keys, `fixture`, and
    the placement fields from status.json (public_placement); `state` is the event's state (status.event_state,
    read from the full record: raw.state for an overflow outside its permit's state)."""
    pl = public_placement(pl or {}, r, swaps)
    rec = {k: v for k, v in e.items() if not k.startswith("_")}
    rec["fixture"] = bool(e.get("_fixture"))
    rec["state"] = status_mod.event_state(e)
    rec["category"] = status_mod.category_of(e.get("event_type"))       # sewage, beach or bloom (§2.z)
    rec["water_slugs"] = pl.get("water_slugs", rec.get("water_slugs") or [])
    rec["water_match"] = pl.get("water_match", rec.get("water_match"))
    rec["placement_note"] = pl.get("note")
    if pl.get("validation_error"):
        rec["parse_error"] = "; ".join(x for x in (rec.get("parse_error"), pl["validation_error"]) if x)
    rec["unplaced_reason"] = pl.get("unplaced_reason")
    # the report names no receiving water ("N/A", a storm drain, "did not reach a waterbody"): kept on the
    # record, colours no water, gets no reach (docs/plan.md §2; Maryland decision 3)
    rec["no_receiving_water"] = pl.get("no_receiving_water")
    rec["set_aside"] = pl.get("set_aside")
    rec["superseded"] = pl.get("superseded")
    rec["duplicate_of"] = pl.get("duplicate_of")
    rec["reach"] = pl.get("reach")
    if pl.get("future_start"):              # a start in the future as published: page and archive row, no status
        rec["future_start"] = True
    rec["file"] = f"events/{event_file_name(e['event_id'])}"
    return rec


# text fields of the monthly marks (status.json monthly_outfalls) copied from a record: the label quotes its volume
# text when it gives no days or events, and the outfall and operator names are the record's (review 2026-11-03 SOL P1-1)
MONTHLY_TEXT_KEYS = ("label", "outfall_name", "discharger_name")


def redact_status_texts(st: dict, r: Redactor, swaps_of: dict | None = None) -> int:
    """In place: the status lines out/ copies from status.json that can quote a record (reasons' `short`,
    `monthly_label` and the water's reason_short, which name the operator or authority or quote a volume text; a
    red.event rule's rationale, the record's own advice_window_basis; the advisory points' and active reach events'
    `short`; the monthly marks' label, outfall and operator names) through Redactor.note, each with the quote swaps
    of the record it comes from (swaps_of: event id -> quote_swaps). Returns how many changed."""
    n = 0
    swaps_of = swaps_of or {}

    def fix(d: dict, k: str, eid=None):
        nonlocal n
        v = d.get(k)
        if isinstance(v, str) and v:
            new = r.note(v, swaps_of.get(eid or d.get("event_id"), ()))
            if new != v:
                d[k] = new
                n += 1
    def deep(o, eid, skip=("event_id", "rule", "status", "water", "slug", "category", "from", "until", "file", "label",
                           "source_id", "water_slugs", "reach", "rid")):
        # every other string under a reason (placement notes, a rule's basis, a stretch's text) can quote the record
        nonlocal n
        if isinstance(o, dict):
            for k, v in o.items():
                if k in skip:
                    continue
                if isinstance(v, str) and v:
                    new = r.note(v, swaps_of.get(eid, ()))
                    if new != v:
                        o[k] = new
                        n += 1
                else:
                    deep(v, eid, skip)
        elif isinstance(o, list):
            for v in o:
                deep(v, eid, skip)
    WATER_SAFE = ("name", "slug", "kind", "state", "status", "since", "events", "covered_by", "stale", "stale_sources",
                  "fill", "stretch_model", "status_basis", "slug_aliases", "towns", "reasons", "reason_short", "bbox")
    for w in (st.get("waters") or {}).values():
        reasons = w.get("reasons") or []
        fix(w, "reason_short", reasons[0].get("event_id") if reasons else None)
        # the water's other texts (its summary, headline, per-category status, unresolved events) quote records too:
        # the second stop of run 41921379232 was in one of them
        for k, v in list(w.items()):
            if k in WATER_SAFE:
                continue
            if isinstance(v, str) and v:
                fix(w, k, reasons[0].get("event_id") if reasons else None)
            else:
                deep(v, reasons[0].get("event_id") if reasons else None)
        for x in reasons:
            fix(x, "short")
            fix(x, "monthly_label")
            fix(x, "authority")
            for key in ("red_rule", "rule_applied"):
                rr = x.get(key)
                if isinstance(rr, dict) and rr.get("rule") == "red.event":
                    fix(rr, "rationale", x.get("event_id"))
            # the rest of the reason, nested (the Old Tampa Bay water file carried a blocklisted name in a field
            # none of the lines above reach; the export's self-check stopped run 41915396147 on 2026-11-04)
            for k, v in x.items():
                if k not in ("short", "monthly_label", "authority") and not isinstance(v, str):
                    deep(v, x.get("event_id"))
                elif isinstance(v, str) and k not in ("short", "monthly_label", "authority", "event_id", "rule", "status",
                                                        "label", "category", "from", "until", "file", "water", "reach"):
                    fix(x, k)
    for x in (st.get("advisory_points") or []) + (st.get("reach_events_active") or []):
        fix(x, "short")
    for x in st.get("monthly_outfalls") or []:
        for k in MONTHLY_TEXT_KEYS:
            fix(x, k)
    return n


# ---------------------------------------------------------------- the blocklist self-check

def blocklist_hits(out_dir: Path, names: list[str]) -> list[str]:
    """The files of out_dir that carry a name of the owner's blocklist (data/build/name-blocklist.json),
    relative to out_dir: events.json, waters/*.json and the full records events/*.json (which the site serves as
    /event/<id>/ and /data/records/<month>.json). The names are never printed, only where they are."""
    scan = BlockScan(names)
    if not scan.phrases:
        return []
    out_dir = Path(out_dir)
    # the map and list payloads too: the monthly marks, overlays, advisory points, reaches, active rows, rain and
    # coverage files carry labels and names copied from records (review 2026-11-03 SOL P1-1)
    paths = [out_dir / n for n in ("events.json",) + PUBLIC_PAYLOADS] + sorted((out_dir / "waters").glob("*.json")) \
        + sorted((out_dir / "events").glob("*.json")) + sorted((out_dir / REACH_STATE_DIR).glob("*.geojson"))
    hits = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if scan.found(text):
            hits.append(str(p.relative_to(out_dir)))
    return hits


def wording_in_status(st: dict) -> list[str]:
    """Paths of status texts out/ publishes as written (reasons, their rule records, the monthly marks) that carry
    internal wording or a repository path (review 2026-11-03 SOL P2-8)."""
    hits = []
    for slug, w in (st.get("waters") or {}).items():
        for i, x in enumerate(w.get("reasons") or []):
            for k in ("short", "label", "monthly_label"):
                if isinstance(x.get(k), str) and (INTERNAL_WORDING.search(x[k]) or REPO_PATH.search(x[k])):
                    hits.append(f"waters.{slug}.reasons[{i}].{k}")
            rr = x.get("rule_applied")
            if isinstance(rr, dict) and not str(rr.get("rule") or "").startswith(RULES_FILE_PREFIXES):
                for k in ("rationale", "basis"):
                    v = rr.get(k)
                    if isinstance(v, str) and (INTERNAL_WORDING.search(v) or REPO_PATH.search(v)):
                        hits.append(f"waters.{slug}.reasons[{i}].rule_applied.{k}")
    for i, x in enumerate(st.get("monthly_outfalls") or []):
        for k in MONTHLY_TEXT_KEYS:
            if isinstance(x.get(k), str) and (INTERNAL_WORDING.search(x[k]) or REPO_PATH.search(x[k])):
                hits.append(f"monthly_outfalls[{i}].{k}")
    return hits


def shown_path(p: Path) -> str:
    try:
        return str(Path(p).relative_to(ROOT))
    except ValueError:
        return str(p)


PUBLIC_PAYLOADS = ("waters.json", "active.json", "monthly-outfalls.json", "overlays.geojson", "advisory-points.geojson",
                   "reaches.geojson", "reach-paths.geojson", "rain.json", "coverage.json", "dischargers.json",
                   "outfalls.json")
BLOCKED_MARK = BUILD_DIR / "export-blocked.json"     # the old hard stop; removed whenever the export runs
HITS_MARK = BUILD_DIR / "blocklist-hits.json"        # the files (never the name) a hit is in, for the next run's fix


def enforce_blocklist(out_dir: Path = OUT_DIR, names: list[str] | None = None) -> int:
    """The export's last step. A blocklisted name in out/ (blocklist_hits) is a warning, not a stop (owner,
    2026-11-05: operations are not disrupted for public-record text that can be corrected): the files are named in
    HITS_MARK and on the console, never the name, the run goes on and uploads, and the record is fixed with a rule
    on the next run. The old hard-stop mark is removed so the scripts never hold a publish. Returns the files checked."""
    names = blocklist(DATA_DIR) if names is None else names
    hits = blocklist_hits(out_dir, names)
    BLOCKED_MARK.unlink(missing_ok=True)
    if hits:
        write_json(HITS_MARK, {"at": now_iso(), "files": hits,
                               "why": "a name on the owner's blocklist is in these files of out/; the run uploaded; "
                                      "fix the record with a scrub rule (never a blocker, owner 2026-11-05)"})
        print(f"::warning::export: a blocklisted name is in {len(hits)} file(s) of out/ ({', '.join(hits[:5])}"
              f"{' ...' if len(hits) > 5 else ''}); uploaded anyway; see {shown_path(HITS_MARK)}")
    else:
        HITS_MARK.unlink(missing_ok=True)
    return 1 + len(list((Path(out_dir) / "waters").glob("*.json"))) + len(list((Path(out_dir) / "events").glob("*.json")))


def public_rules(o):
    """data/rules.json for out/: every key starting with "_" dropped, at any depth."""
    if isinstance(o, dict):
        return {k: public_rules(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, list):
        return [public_rules(v) for v in o]
    return o


US_JURISDICTIONS = frozenset("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
                             "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR VI GU AS MP".split())


def live_jurisdiction_events(events: list[dict], live: set[str]) -> tuple[list[dict], int]:
    """Every public output is the live states' (rules.json live_states): a record whose state the status build
    could place (status.event_state reads the live list) stays; one it could not, from a feed whose id opens with
    a jurisdiction's prefix (fl-dep-habs, wa-ecology-spills) that is not live, is left out, with its advisory
    point and event page. Florida's bloom points reached the live map before its switch this way (2026-11-04).
    Records with no jurisdiction prefix (epa-echo) are kept as before."""
    kept, n = [], 0
    for e in events:
        if status_mod.event_state(e):
            kept.append(e)
            continue
        pref = None
        for sid in (str(e.get("event_id") or "").split(":", 1)[-1], str(e.get("source_id") or "")):
            m = re.match(r"(?:fixture-)?([a-z]{2})-", sid)
            if m and m.group(1).upper() in US_JURISDICTIONS:
                pref = m.group(1).upper()
                break
        if pref and pref not in live:
            n += 1
            continue
        kept.append(e)
    return kept, n


NATIONAL = "US"          # a registry row's states value for a national source


def live_registry_rows(rows: list[dict], live: set[str]) -> list[dict]:
    """The registry rows of the live states and the national ones: a row whose `states` list names only states not
    yet live stays home (docs/national-approach.md §8 item 3: nothing outside live_states reaches out/). A national
    row is one with no states or with "US" (EPA's eRule tables, fed-echo-sewer-overflow-bypass-events: without it the
    echo-sewer-overflow feed, which lists only that row, left /sources/ from 2026-11-04 to the 2026-11-07 review)."""
    out = []
    for r in rows:
        sts = {str(x).upper() for x in (r.get("states") or [])}
        if not sts or NATIONAL in sts or sts & live:
            out.append(r)
    return out


def live_feeds(feeds: list[dict], kept_registry_ids: set[str]) -> list[dict]:
    """The feeds whose registry rows survive live_registry_rows (a feed with no registry row is kept: its state is
    not known here, and its events are already limited to the live waters)."""
    return [f for f in feeds if not (f.get("registry_ids") or []) or any(r in kept_registry_ids for r in f["registry_ids"])]


def live_dischargers(rows: list[dict], live: set[str]) -> list[dict]:
    """Operator rows of the live states only (a row with no state is kept)."""
    return [d for d in rows if not d.get("state") or str(d["state"]).upper() in live]


def live_rules(rules: dict, live: set[str]) -> dict:
    """out/rules.json keeps the per-state and per-operator windows of the live states only; the shared rules and
    their rationale stay whole (the site shows a rule only when one of its sources covers a live water)."""
    out = dict(rules)
    red = dict(out.get("red") or {})
    if isinstance(red.get("by_state"), dict):
        red["by_state"] = {k: v for k, v in red["by_state"].items() if str(k).upper() in live}
    if isinstance(red.get("by_discharger"), dict):
        low = {x.lower() for x in live}
        red["by_discharger"] = {k: v for k, v in red["by_discharger"].items() if str(k).split("-", 1)[0].lower() in low}
    out["red"] = red
    return out


def publicize(o):
    """Rule records that come from data/rules.json carry a pointer into out/rules.json ("rules_ref")
    instead of the file's rationale and internal source paths; the methods page prints rules.json.
    Records quoting a source notice (red.event, red.authority_advisory) keep their text."""
    if isinstance(o, dict):
        d = {k: publicize(v) for k, v in o.items()}
        r = d.get("rule")
        if isinstance(r, str) and r.startswith(RULES_FILE_PREFIXES) and ("rationale" in d or "source" in d):
            d.pop("rationale", None)
            d.pop("source", None)
            d["rules_ref"] = r
        return d
    if isinstance(o, list):
        return [publicize(v) for v in o]
    return o


def internal_wording(o, path="", skip_urls=True) -> list[str]:
    """Paths of string values that read as internal project wording (for the export's self-check)."""
    hits = []
    if isinstance(o, dict):
        for k, v in o.items():
            hits += internal_wording(v, f"{path}.{k}", skip_urls)
    elif isinstance(o, list):
        for v in o:
            hits += internal_wording(v, f"{path}[]", skip_urls)
    elif isinstance(o, str) and INTERNAL_WORDING.search(o):
        if not (skip_urls and o.startswith(("http://", "https://"))):
            hits.append(path)
    return hits


def public_constants(c: dict) -> dict:
    u, r = c.get("unresolved") or {}, c.get("reach") or {}
    return {"history_days": c.get("history_days"), "confirm_days": c.get("confirm_days"),
            "advisory_no_end_days": c.get("advisory_no_end_days"),
            "ongoing_red_days": u.get("ongoing_red_days"), "unresolved_until_day": u.get("unresolved_yellow_days"),
            "unknown_status_yellow_days": u.get("unknown_status_yellow_days"), "reach_cap_km": r.get("cap_km")}


def rain_caution_states(rain_block: dict) -> dict:
    """{state: {covered, methods, permits, waters, sources, sentence}}: where the "discharge likely" caution is
    computed, for every state the rain watch reads or whose registry lists open combined sewer outfalls."""
    from build import rain_likely as rain_mod
    cso: dict[str, set] = defaultdict(set)
    for o in status_mod.live_outfalls(status_mod.load_registry_outfalls(provisional=True)):
        if rain_mod.cso_open(o) and o.get("npdes_permit"):
            cso[status_mod.outfall_state(o)].add(o["npdes_permit"])
    live = status_mod.states()
    return {st: v for st, v in rain_mod.caution_coverage(rain_block, dict(cso)).items() if st in live}


def public_rain(block: dict) -> dict:
    """status.json "rain_likely" for out/rain.json: the switch, the rainfall and forecast sources with
    their times, each permittee's threshold, radar total, forecast and state now, and the episodes
    (each with its pieces and rainfall record). Build notes stay home."""
    if not block or not block.get("enabled"):
        return {"enabled": False, "label": (block or {}).get("label")}
    keep = ("enabled", "rule", "label", "label_by_basis", "tail_hours", "notice_suppress_hours", "rainfall", "forecast", "site_flags",
            "counts", "permits", "episodes")
    out = {k: block.get(k) for k in keep}
    out["thresholds_built"] = (block.get("thresholds") or {}).get("built")
    out["rules_ref"] = "rain_likely"
    return out


LAUNCH_URL = "https://openboatlaunch.org/launch/{slug}/"


# Every launch with a known access class is shown (owner, 2026-11-02: a discharge affects the users of
# private and commercial launches too); "unknown" is skipped. openboatlaunch's build data
# (data/build/<ST>/launches.json) has them all; its out/water/<slug>.json only the published ones.
# "club" is openboatlaunch's members-only class (yacht and boat clubs; 15 launches in PA, NY and NJ
# as of 2026-11-02): shown and styled as private on the site.
ACCESS_SHOWN = ("public", "public_restricted", "private", "commercial", "club")
OBL_BUILD_DIR = Path(os.environ.get("OBL_BUILD_DIR", str(ROOT.parent / "openboatlaunch" / "data" / "build")))
_OBL_BUILD: dict[str, dict[str, list]] = {}
# Editorial launches: rows in the launch object shape for launches no upstream source carries yet
# (e.g. a members-only club whose ramp is not in OpenStreetMap). Each cites its position's source;
# keys starting with "_" are notes and never exported. A row whose slug openboatlaunch also has is
# skipped, so the editorial row drops away once the source catches up.
LAUNCHES_EXTRA = Path(os.environ.get("DWW_LAUNCHES_EXTRA", str(ROOT / "data" / "launches-extra.json")))
_LAUNCHES_EXTRA: dict[str, list] | None = None


def extra_launches(water_slug: str) -> list[dict]:
    """data/launches-extra.json rows for one water (cached), public keys only."""
    global _LAUNCHES_EXTRA
    if _LAUNCHES_EXTRA is None:
        idx: dict[str, list] = defaultdict(list)
        try:
            rows = json.loads(LAUNCHES_EXTRA.read_text()) if LAUNCHES_EXTRA.exists() else []
        except (OSError, ValueError):
            rows = []
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and r.get("slug") and r.get("water_slug") and r.get("access") in ACCESS_SHOWN:
                idx[r["water_slug"]].append({k: v for k, v in r.items() if not str(k).startswith("_")})
        _LAUNCHES_EXTRA = idx
    return list(_LAUNCHES_EXTRA.get(water_slug, []))


def obl_build_launches(state: str | None) -> dict[str, list]:
    """water slug -> openboatlaunch build records with a shown access class, for one state (cached)."""
    if not state:
        return {}
    if state not in _OBL_BUILD:
        idx: dict[str, list] = defaultdict(list)
        p = OBL_BUILD_DIR / state / "launches.json"
        try:
            rows = json.loads(p.read_text()) if p.exists() else []
        except (OSError, ValueError):
            rows = []
        for r in rows if isinstance(rows, list) else []:
            w = r.get("water")
            ws = w.get("slug") if isinstance(w, dict) else w
            if ws and r.get("slug") and r.get("access") in ACCESS_SHOWN:
                idx[ws].append(r)
        _OBL_BUILD[state] = idx
    return _OBL_BUILD[state]


def obl_launch_row(r) -> dict | None:
    """A launch of an openboatlaunch water record in the long keys (ingest/obl_waters.py launch: either shape)."""
    from ingest.obl_waters import launch
    return launch(r)


def launches_for(water_slug: str, state: str | None = None) -> list[dict]:
    """The water's launches as objects with coordinates: the published ones from openboatlaunch's
    out/water/<slug>.json (the API's long keys slug, name, kind, state, town, lon, lat, fee, access, visibility;
    or the older short keys s n k st t x y f, a 'r' when restricted), then the build data's private, commercial and other unpublished launches on the same
    water. Each has an access class, operator and website where present, and the openboatlaunch page
    as url only when the launch is published there."""
    p = status_mod.OBL_WATER_DIR / f"{water_slug}.json"
    try:
        rows = (json.loads(p.read_text()) or {}).get("launches") or [] if p.exists() else []
    except (OSError, ValueError):
        rows = []
    build = {r["slug"]: r for r in obl_build_launches(state).get(water_slug, [])}
    out, seen = [], set()
    for r in rows:
        # openboatlaunch's long launch keys (its API, 2026-11-07) or the short ones of the older copy; a launch the API
        # serves as "unpublished" (private, commercial, club: a point with no personal fields) is not shown from here,
        # as before: only the build folder's records add those (the export's rule is unchanged)
        r = obl_launch_row(r)
        if r is None or r["slug"] in seen or r["visibility"] != "published":
            continue
        seen.add(r["slug"])
        b = build.get(r["slug"]) or {}
        lat, lon = r.get("lat"), r.get("lon")
        o = {"slug": r["slug"], "name": r.get("name"), "kind": r.get("kind"), "town": r.get("town"),
             "state": r.get("state"), "water_slug": water_slug,
             "lat": round(float(lat), 6) if lat is not None else None,
             "lon": round(float(lon), 6) if lon is not None else None, "fee": r.get("fee"),
             "access": b.get("access") or r.get("access") or "public",
             "url": LAUNCH_URL.format(slug=r["slug"])}
        for k in ("operator", "website"):
            if b.get(k):
                o[k] = b[k]
        out.append(o)
    for slug, b in sorted(build.items()):
        if slug in seen:
            continue
        seen.add(slug)
        lat, lon = b.get("lat"), b.get("lon")
        o = {"slug": slug, "name": b.get("name"), "kind": b.get("kind"), "town": b.get("town"),
             "state": b.get("state") or state, "water_slug": water_slug,
             "lat": round(float(lat), 6) if lat is not None else None,
             "lon": round(float(lon), 6) if lon is not None else None, "fee": b.get("fee"), "access": b.get("access"),
             "url": LAUNCH_URL.format(slug=slug) if b.get("visibility") == "published" else None}
        for k in ("operator", "website"):
            if b.get(k):
                o[k] = b[k]
        out.append(o)
    for r in extra_launches(water_slug):
        if r["slug"] in seen:
            continue
        seen.add(r["slug"])
        lat, lon = r.get("lat"), r.get("lon")
        o = {"slug": r["slug"], "name": r.get("name"), "kind": r.get("kind"), "town": r.get("town"),
             "state": r.get("state") or state, "water_slug": water_slug,
             "lat": round(float(lat), 6) if lat is not None else None,
             "lon": round(float(lon), 6) if lon is not None else None, "fee": r.get("fee"), "access": r.get("access"),
             "url": None}
        for k in ("operator", "website", "source"):
            if r.get(k):
                o[k] = r[k]
        out.append(o)
    return out


def point_effects(st: dict, effects: dict, active_now: dict) -> None:
    """Beach, rain and HAB advisories shown as markers (no water coloured): their own intervals go
    to the event's status_effects and, while red, yellow or unresolved, to active_now."""
    for ap in st.get("advisory_points") or []:
        cat = ap.get("category") or "sewage"
        for frm, until, color, rule in ap.get("intervals") or []:
            effects[ap["event_id"]].append({"water": None, "placement": "point", "status": color, "rule": rule,
                                            "from": frm, "until": until, "category": cat})
        if ap.get("status") in ACTIVE_STATES:
            active_now[ap["event_id"]].append({"water": None, "placement": "point", "status": ap["status"], "category": cat,
                                               "rule": ap.get("rule"), "label": ap.get("label"), "short": ap.get("short"),
                                               "from": ap.get("from"), "until": ap.get("until"), "reach": None,
                                               "rule_applied": None, "water_slugs": ap.get("water_slugs") or []})


def monthly_props(w: dict) -> dict:
    """The monthly mark's feature properties of a water whose status is monthly (docs/plan.md §2.x): days, month,
    received_at and label of its newest monthly report; {} otherwise."""
    if w.get("status") != "monthly":
        return {}
    ms = [r for r in w.get("reasons") or [] if r.get("rule") == "monthly"]
    if not ms:
        return {}
    r = max(ms, key=lambda x: (x.get("month") or "", x.get("days") or 0))
    return {"days": r.get("days"), "month": r.get("month"), "received_at": r.get("received_at"),
            "label": r.get("monthly_label") or r.get("short"), "monthly_reports": len(ms)}


def write_compact(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str))
    tmp.replace(path)


def round_coords(c):
    if isinstance(c, (list, tuple)):
        if c and isinstance(c[0], (int, float)):
            return [round(float(x), COORD_DIGITS) for x in c]
        return [round_coords(x) for x in c]
    return c


def geojson_geometry(g):
    """Simplified, rounded GeoJSON; a collection of one kind becomes a Multi* geometry."""
    from shapely.geometry import GeometryCollection, MultiLineString, MultiPolygon, mapping
    g = g.simplify(SIMPLIFY_DEG, preserve_topology=True)
    if g.is_empty:
        return None
    if isinstance(g, GeometryCollection) and not isinstance(g, (MultiPolygon, MultiLineString)):
        parts = []
        for p in g.geoms:
            parts.extend(getattr(p, "geoms", [p]))
        kinds = {p.geom_type for p in parts if not p.is_empty}
        if kinds == {"Polygon"}:
            g = MultiPolygon([p for p in parts if not p.is_empty])
        elif kinds == {"LineString"}:
            g = MultiLineString([p for p in parts if not p.is_empty])
    m = mapping(g)
    if m["type"] == "GeometryCollection":
        return {"type": "GeometryCollection",
                "geometries": [{"type": x["type"], "coordinates": round_coords(x["coordinates"])} for x in m["geometries"]]}
    return {"type": m["type"], "coordinates": round_coords(m["coordinates"])}


CONDITIONS_DROP = {"nwps_lid"}
CONDITIONS_SOURCE = ("U.S. Geological Survey, Water Data for the Nation (latest continuous and daily values); "
                     "NOAA National Weather Service, National Water Prediction Service (flood categories)")
CONDITIONS_NOTE = "Conditions are measured at the gauge, not at the water's outlets, and do not change the status."


def public_conditions(cond: dict | None, tracked) -> dict:
    """data/build/conditions.json for out/: tracked waters only, without working fields."""
    cond = cond or {}
    waters = {slug: {k: v for k, v in rec.items() if k not in CONDITIONS_DROP}
              for slug, rec in sorted((cond.get("waters") or {}).items()) if slug in tracked and rec.get("gauge_id")}
    return {"built": cond.get("built"), "thresholds": cond.get("thresholds"), "source": CONDITIONS_SOURCE,
            "note": CONDITIONS_NOTE, "count": len(waters), "waters": waters}


# ---------------------------------------------------------------- inputs

def status_inputs() -> list[Path]:
    """Every file the status build reads: events, rules, waters, outfalls, source registry, the
    reach cache and gauge readings."""
    from build import reaches as reaches_mod
    paths = list(EVENTS_DIR.glob("*.json")) + [DATA_DIR / "rules.json", reaches_mod.GAUGES_BY_RIVER,
                                               reaches_mod.GAUGES_LATEST]
    paths += list(DATA_DIR.glob(OUTFALL_REGISTRY_GLOB)) + [DATA_DIR / REPORTED_OUTFALLS]   # the outfall registry
    paths += list(DATA_DIR.glob("waters-*.json")) + list((DATA_DIR / "sources").glob("*.yaml"))
    if reaches_mod.REACH_DIR.exists():
        paths += list(reaches_mod.REACH_DIR.glob("*.json"))
    # the "discharge likely" caution: radar rainfall, its hourly history, the permittees' thresholds
    paths += [BUILD_DIR / "rainfall.json", BUILD_DIR / "rainfall-history.json", BUILD_DIR / "rain-thresholds.json"]
    return [p for p in paths if p.exists()]


def active_entries(active_now: dict, by_event: dict, rain_block: dict | None = None) -> list[dict]:
    """out/active.json rows: every event setting red, yellow or unresolved now (kind "event": the
    index fields, its file and the reasons), and every "discharge likely" episode in effect (kind
    "rain_likely": no event record and no event page; the permittee, the rainfall record and the
    reasons), red first, then newest first."""
    episodes = (rain_block or {}).get("episodes") or {}
    active = []
    for eid, rs in active_now.items():
        rs = [r for r in rs if r["status"] in ACTIVE_STATES]
        if not rs:
            continue
        if eid in by_event:
            active.append({"kind": "event", **index_obj(by_event[eid]), "file": by_event[eid]["file"], "reasons": rs})
        elif eid in episodes:
            ep = episodes[eid]
            rain = ep.get("rain") or {}
            pt = rain.get("point") or [None, None]
            active.append({"kind": "rain_likely", "event_id": eid, "event_type": None, "status": None,
                           # "Discharge possible: ..." where only the site's default amount applies (trigger_basis)
                           "label": ep.get("label") or status_mod.RULES["rain_likely"][1],
                           "trigger_basis": ep.get("trigger_basis"), "state": ep.get("state"),
                           "started_at": ep.get("start"), "ended_at": None, "until": ep.get("end"),
                           "water_slugs": sorted({r["water"] for r in rs if r.get("water")}),
                           "discharger_name": ep.get("discharger_name"), "discharger_id": ep.get("discharger_id"),
                           "npdes_permit": ep.get("permit"),
                           "outfall_id": None, "volume_gal": None, "lat": pt[0], "lon": pt[1], "fixture": False,
                           "reaches": ep.get("reaches") or [], "rain": rain, "file": None, "reasons": rs})
    active.sort(key=lambda a: (min(STATUS_ORDER[r["status"]] for r in a["reasons"]), -time_key(a)))
    return active


def stale_reason(st: dict | None, hist: dict | None, include_fixtures: bool, include_restricted: bool,
                 inputs: list[Path]) -> str | None:
    """Why the cached status cannot be exported as it is, or None."""
    if not st or not hist:
        return "status or history missing"
    if hist.get("built") != st.get("built"):
        return "status and history come from different builds"
    if st.get("fixtures_included") != include_fixtures or bool(st.get("restricted_included")) != include_restricted:
        return "built with another fixture/restricted setting"
    built = status_mod.parse_time(st.get("built"))
    if built is None:
        return "status has no build time"
    newer = [p.name for p in inputs if p.stat().st_mtime > built.timestamp()]
    if newer:
        return f"inputs newer than the status build: {', '.join(sorted(newer)[:5])}{' ...' if len(newer) > 5 else ''}"
    return None


def ensure_status(include_fixtures: bool, include_restricted: bool = False):
    st = read_json(BUILD_DIR / "status.json")
    hist = read_json(BUILD_DIR / "history.json")
    why = stale_reason(st, hist, include_fixtures, include_restricted, status_inputs())
    if why:
        print(f"export: rebuilding status ({why})")
        st, hist = status_mod.build(include_fixtures=include_fixtures, include_restricted=include_restricted)
    return st, hist


PERMIT_RE = re.compile(r"\b([A-Z]{2}\d{7})\b")


def load_dischargers() -> tuple[list[dict], str]:
    consolidated = read_json(DATA_DIR / "dischargers.json")
    if consolidated:
        rows = consolidated.get("dischargers", consolidated) if isinstance(consolidated, dict) else consolidated
        return [dict(r) for r in rows], "data/dischargers.json"
    merged: dict[str, dict] = {}
    for p in sorted((ROOT / "research").glob("*/dischargers.json")):
        area = p.parent.name
        try:
            rows = json.loads(p.read_text())
        except Exception:
            continue
        for r in rows if isinstance(rows, list) else []:
            permits = PERMIT_RE.findall(str(r.get("npdes_permit") or ""))
            key = permits[0] if permits else f"id:{r.get('id')}"
            cur = merged.get(key)
            if cur is None:
                cur = dict(r)
                cur["npdes_permit"] = permits[0] if permits else r.get("npdes_permit")
                cur["npdes_permit_text"] = r.get("npdes_permit")
                cur["research_areas"] = [area]
                cur["research_ids"] = [r.get("id")]
                merged[key] = cur
                continue
            cur["research_areas"] = sorted(set(cur["research_areas"]) | {area})
            cur["research_ids"] = sorted({x for x in cur["research_ids"] + [r.get("id")] if x})
            for k, v in r.items():
                if k in ("id", "npdes_permit"):
                    continue
                if isinstance(v, list):
                    old = cur.get(k) or []
                    cur[k] = old + [x for x in v if x not in old]
                elif cur.get(k) in (None, "", []) and v not in (None, ""):
                    cur[k] = v
                elif k == "notes" and v and v != cur.get(k):
                    cur[k] = f"{cur[k]} | {area}: {v}"
    return list(merged.values()), "research/*/dischargers.json (merged by npdes_permit)"


# ---------------------------------------------------------------- discharger ids

def canonicalize_events(events: list[dict], aliases: dict[str, str]) -> tuple[list[dict], int]:
    """(events, n): each event whose discharger_id is a registry alias gets the registry row's id; the id
    the source's ingester wrote stays in `discharger_id_source` (the public event objects take extra keys:
    the site's EventRec has an index signature, and the export already adds fixture, reach, file ...).
    Events with an unknown id, or none, are untouched. Returns new dicts for the rewritten ones."""
    out, n = [], 0
    for e in events:
        did = e.get("discharger_id")
        canon = aliases.get(did) if isinstance(did, str) else None
        if canon and canon != did:
            e = {**e, "discharger_id": canon, "discharger_id_source": did}
            n += 1
        out.append(e)
    return out, n


def rewrite_discharger_ids(o, aliases: dict[str, str]) -> int:
    """In place, at any depth: every "discharger_id" value that is a registry alias becomes the row's id
    (the status reasons and the rain block carry the operator's id). Returns how many were rewritten."""
    n = 0
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "discharger_id" and isinstance(v, str) and v in aliases:
                o[k] = aliases[v]
                n += 1
            else:
                n += rewrite_discharger_ids(v, aliases)
    elif isinstance(o, list):
        for v in o:
            n += rewrite_discharger_ids(v, aliases)
    return n


def events_by_discharger(dis: list[dict], events: list[dict]) -> dict[str, list[dict]]:
    """registry id -> its events (once each). An event belongs to the row its (canonical) discharger_id names;
    one with no id, or an id that is no row, belongs to the rows holding its npdes_permit as their permit
    (the site's dischargerOf takes the same order: id, then permit)."""
    row_ids = {d["id"] for d in dis if d.get("id")}
    rows_of_permit: dict[str, list[str]] = defaultdict(list)
    for d in dis:
        if d.get("id") and d.get("npdes_permit"):
            rows_of_permit[d["npdes_permit"]].append(d["id"])
    out: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        did = e.get("discharger_id")
        for rid in ([did] if did in row_ids else rows_of_permit.get(e.get("npdes_permit"), [])):
            out[rid].append(e)
    return out


def outfall_lists(outfalls: list[dict], aliases: dict[str, str] | None = None) -> tuple[dict, dict, dict]:
    """({water slug: rows}, {permit: rows}, {operator id: rows}) for the water and operator pages, from registry
    rows already kept to the live states (status.live_outfalls): every outfall, closed ones with outfall_status
    CLS, with or without a water record. The provisional places from the overflow reports carry record_status,
    confidence, report_count, last_report_at, event_ids and reached_water, and no street address (the point, the
    counts and the reports); one without a permit is listed under its operator (discharger_id, aliases resolved)."""
    aliases = aliases or {}
    by_water, by_permit, by_operator = defaultdict(list), defaultdict(list), defaultdict(list)
    for o in outfalls:
        if o.get("outfall_kind") == "other":
            continue                    # a row EPA flags CSO that is no sewage outfall (kind_note)
        slug = status_mod.SLUG_ALIASES.get(o["water_slug"], o["water_slug"]) if o.get("water_slug") else None
        prov = is_provisional(o)
        row = {"npdes_permit": o.get("npdes_permit"), "outfall": o.get("outfall"),
               "outfall_name": None if prov else o.get("outfall_name"),
               "outfall_kind": o.get("outfall_kind") or "cso", "state": status_mod.outfall_state(o),
               "permittee": o.get("permittee"), "receiving_water": outfalls_mod.receiving_water(o),
               "lat": o.get("lat"), "lon": o.get("lon"), "water_slug": slug, "match": o.get("match"),
               "distance_m": o.get("distance_m"), "outfall_status": o.get("outfall_status"),
               **({k: o.get(k) for k in PROVISIONAL_FIELDS} if prov else {}),
               **({"coords_from": "facility"} if o.get("coords_from") == "facility" else {})}
        if o.get("npdes_permit"):
            by_permit[o["npdes_permit"]].append(row)
        elif o.get("discharger_id"):
            by_operator[aliases.get(o["discharger_id"], o["discharger_id"])].append(row)
        slugs = [slug] if slug else []
        if prov:                        # a provisional place may sit on several waters
            slugs += [status_mod.SLUG_ALIASES.get(x, x) for x in o.get("water_slugs") or [] if isinstance(x, str)]
        for sl in dict.fromkeys(slugs):  # an older slug of a merged NHD record -> the record (status.SLUG_ALIASES)
            by_water[sl].append(row)
    return by_water, by_permit, by_operator


def official(rows: list[dict]) -> list[dict]:
    """The official listings of outfall_lists rows (no record_status)."""
    return [o for o in rows if not o.get("record_status")]


def provisional(rows: list[dict]) -> list[dict]:
    """The provisional places from the overflow reports among outfall_lists rows (record_status set)."""
    return [o for o in rows if o.get("record_status")]


def operator_outfalls(d: dict, by_permit: dict, by_operator: dict | None = None) -> list[dict]:
    """An operator page's outlets: those of every permit it holds (its own permit first), then the provisional
    places from its reports that have no permit (outfall_lists)."""
    permits = dict.fromkeys([d.get("npdes_permit"), *(d.get("npdes_permits") or [])])
    return [o for q in permits if q for o in by_permit.get(q, [])] + list((by_operator or {}).get(d.get("id"), []))


# ---------------------------------------------------------------- main

def export(include_fixtures: bool = False, include_restricted: bool = False) -> dict:
    if include_fixtures and os.environ.get("DWW_ALLOW_FIXTURES") != "1":
        raise SystemExit("export: refusing to write out/ with research fixture events; "
                         "set DWW_ALLOW_FIXTURES=1 for a development export")
    st, hist = ensure_status(include_fixtures, include_restricted)
    waters = status_mod.live_waters(status_mod.load_waters())   # the live states' records only (rules.json live_states)
    # the outfall registry (every data/outfalls-*.json, national), kept to the live states for every public output
    outfalls = status_mod.live_outfalls(status_mod.load_registry_outfalls(provisional=True))
    problems_registry = [f"outfall registry: {x}" for x in OUTFALL_REGISTRY_SKIPPED]
    registry = status_mod.load_registry()
    files, events, problems = status_mod.load_events(EVENTS_DIR, include_fixtures, include_restricted)
    problems.extend(problems_registry)
    dropped = set(st.get("dropped_fixtures") or [])
    placements = st.get("placements") or {}
    events = [e for e in events if e["event_id"] not in dropped]
    events, n_foreign = live_jurisdiction_events(events, status_mod.states())
    if n_foreign:
        print(f"export: {n_foreign} record(s) of feeds whose jurisdiction is not live left out of every public output")
    # the records as the status build read them: a status line quotes these texts, so its swaps are taken against them
    as_read = {e["event_id"]: e for e in events}
    events = [public_event(e) for e in events]
    # the operator registry first: an event's discharger_id that the registry lists as an alias is written
    # as the row's id (the original in discharger_id_source) before anything is counted or written
    dis, dis_from = load_dischargers()
    dis = live_dischargers(dis, status_mod.states())          # operators of the live states only
    aliases = discharger_alias_map(dis)
    events, n_alias_events = canonicalize_events(events, aliases)
    n_alias_status = rewrite_discharger_ids(st, aliases)
    if n_alias_events or n_alias_status:
        print(f"export: {n_alias_events} events and {n_alias_status} status records carried a registry alias as "
              f"discharger_id; written with the registry id")
    # names of private individuals in quoted source text -> "[name removed]" before any record is written
    # (build/redact.py; owner's lists data/name-allowlist.json, data/name-blocklist.json; review: build/name_review.py).
    # The same redactor then runs over the placement texts and status lines that quote a record (public_record,
    # redact_status_texts), each record's quotes swapped for its redacted text first (quote_swaps)
    redactor = redactor_for(events)
    redacted = redact_events(events, redactor=redactor)
    swaps_of = {r["event_id"]: s for e, r in zip(events, redacted)
                if (s := quote_swaps(as_read.get(r["event_id"], e), r))}
    events = redacted
    n_status = redact_status_texts(st, redactor, swaps_of)
    if n_status:
        print(f"export: {n_status} status lines quoted a removed name or contact; written redacted")

    # intervals each event set (from the history), by event
    effects = defaultdict(list)
    for slug, ivs in (hist.get("intervals") or {}).items():
        for frm, until, color, rule, eid, *rest in ivs:      # [.., category] since docs/plan.md §2.z
            effects[eid].append({"water": slug, "status": color, "rule": rule, "from": frm, "until": until,
                                 "category": rest[0] if rest else "sewage"})
    active_now = defaultdict(list)
    point_effects(st, effects, active_now)
    for slug, w in st["waters"].items():
        for r in w["reasons"]:
            active_now[r["event_id"]].append({"water": slug, "status": r["status"], "rule": r["rule"], "label": r["label"],
                                              "category": r.get("category") or "sewage",
                                              "short": r["short"], "from": r["from"], "until": r["until"],
                                              "placement": r.get("placement"), "reach": r.get("reach"),
                                              "rule_applied": r.get("rule_applied"),
                                              **({"rain": r["rain"]} if r.get("rain") else {})})

    reach_band = {a["event_id"]: a for a in st.get("reach_events_active") or []}
    out_events, index, seen = [], [], set()
    csv_events = []                         # the full public records, for the CSV downloads (export/csv.py)
    ev_dir = OUT_DIR / "events"
    if ev_dir.exists():
        shutil.rmtree(ev_dir)
    ev_dir.mkdir(parents=True)
    wording = Counter()                     # placement texts still carrying internal wording (self-check)
    for e in events:
        if e["event_id"] in seen:
            continue
        seen.add(e["event_id"])
        pl = placements.get(e["event_id"]) or {}
        rec = public_record(e, pl, redactor, swaps_of.get(e["event_id"], ()))
        wording.update(note_wording(rec))
        full = dict(rec)
        full["status_effects"] = effects.get(e["event_id"], [])
        full["active_now"] = active_now.get(e["event_id"], [])
        full["reach"] = pl.get("reach")
        full["reach_band"] = reach_band.get(e["event_id"])
        write_compact(OUT_DIR / rec["file"], publicize(full))
        csv_events.append(rec)
        out_events.append({k: v for k, v in rec.items()
                           if k not in SLIM_DROP and (k in SLIM_KEEP or v not in (None, [], {}, ""))})
    out_events.sort(key=time_key, reverse=True)
    by_event = {e["event_id"]: e for e in out_events}
    write_compact(OUT_DIR / "events-index.json", {
        "built": now_iso(), "fixtures_included": include_fixtures, "fields": INDEX_FIELDS, "count": len(out_events),
        "rows": [[index_obj(e)[k] for k in INDEX_FIELDS] for e in out_events]})
    rain_block = st.get("rain_likely") or {}
    active = active_entries(active_now, by_event, rain_block)
    write_compact(OUT_DIR / "active.json", {"built": now_iso(), "fixtures_included": include_fixtures,
                                            "count": len(active), "events": publicize(active)})
    # the "discharge likely" caution: per permittee (threshold, radar total, forecast) and its episodes
    write_compact(OUT_DIR / "rain.json", {"built": now_iso(), **publicize(public_rain(rain_block))})
    write_compact(OUT_DIR / "events.json", {"built": now_iso(), "fixtures_included": include_fixtures,
                                            "count": len(out_events), "events": out_events})

    # outfalls by water, by permit and by operator: every registry outfall in a live state (outfall_lists)
    outfalls_by_water, outfalls_by_permit, outfalls_by_operator = outfall_lists(outfalls, aliases)

    # conditions at the nearest gauge (ingest/gauges.py), beside the status, never changing it
    conditions = public_conditions(read_json(BUILD_DIR / "conditions.json"), set(st["waters"]))
    write_compact(OUT_DIR / "conditions.json", conditions)

    # waters.json and overlays
    health = st.get("sources") or {}
    tracked, features, missing_geom = [], [], []
    launch_feats: dict[str, dict] = {}
    water_dir = OUT_DIR / "waters"
    if water_dir.exists():
        shutil.rmtree(water_dir)
    water_dir.mkdir(parents=True)
    for slug, w in sorted(st["waters"].items(), key=lambda kv: (STATUS_ORDER.get(kv[1]["status"], 9), kv[1]["name"] or kv[0])):
        rec = waters.get(slug, {})
        row = {"slug": slug, "name": w["name"], "kind": w["kind"], "state": w["state"], "towns": rec.get("towns") or [],
               "bbox": rec.get("bbox"), "status": w["status"], "since": w["since"], "reason_short": w["reason_short"],
               "reasons": w["reasons"], "event_count": len(w["events"]), "events": w["events"],
               "stale": w["stale"], "stale_sources": w["stale_sources"], "fixture_only": w.get("fixture_only", False),
               "covered_by": [{"source_id": s, "fixture": (health.get(s) or {}).get("fixture"),
                               "stale": (health.get(s) or {}).get("stale"), "last_ok_at": (health.get(s) or {}).get("last_ok_at")}
                              for s in w["covered_by"]],
               "outfalls": official(outfalls_by_water.get(slug, [])),
               # the provisional places from the overflow reports on this water, listed apart (never as a permitted outfall)
               "provisional_outfalls": provisional(outfalls_by_water.get(slug, [])),
               "launches": rec.get("launches") or [],
               "extra": bool(rec.get("extra")), "fill": w.get("fill", True), "status_basis": w.get("status_basis"),
               # "shoreline" on the Great Lakes (data/rules.json reach.shoreline): the lake is drawn as an outline and
               # its reports colour the shoreline stretches in reaches.geojson (model "shoreline"), never the lake
               **({"stretch_model": w["stretch_model"]} if w.get("stretch_model") else {}),
               "slug_aliases": rec.get("slug_aliases") or [],      # older slugs of this record (waters_from_nhd)
               "summary": w.get("summary"), "unresolved_events": w.get("unresolved_events") or [],
               # docs/plan.md §2.z: each category's status now and the headline (sewage first)
               "status_by_category": w.get("status_by_category"), "headline": w.get("headline"),
               "red_rule": w.get("red_rule"), "yellow_rule": w.get("yellow_rule"), "rule_applied": w.get("rule_applied"),
               "reaches": [{"key": k, **{f: (st.get("reaches") or {}).get(k, {}).get(f)
                                         for f in ("status", "river", "permit", "outfall", "length_km", "cut_reason", "active",
                                                   "rain_likely", "rain_trigger_basis")},
                            # an authority's advisory for a named stretch (ADVISORY_KIND): its kind and category
                            **({"reach_kind": ADVISORY_KIND, "category": (st.get("reaches") or {})[k].get("category")}
                               if (st.get("reaches") or {}).get(k, {}).get("kind") == ADVISORY_KIND else {})}
                           for k in w.get("reaches") or []],
               # radar rainfall over the permittees discharging here, their thresholds, the forecast
               # (build/rain_likely.py); null when no CSO permittee discharges to this water
               "rain": w.get("rain")}
        tracked.append(row)
        w_events = sorted((by_event[i] for i in w["events"] if i in by_event), key=time_key, reverse=True)
        launch_objs = launches_for(slug, w.get("state"))
        for lo in launch_objs:
            launch_feats.setdefault(lo["slug"], lo)
        write_compact(water_dir / f"{slug}.json", publicize({
            **{k: v for k, v in row.items() if k != "events"},
            "launches": launch_objs,
            "conditions": conditions["waters"].get(slug),
            "history": {"start": hist.get("start"), "step_hours": hist.get("step_hours", 1),
                        "strip": (hist.get("waters") or {}).get(slug), "intervals": (hist.get("intervals") or {}).get(slug, [])},
            "events": [{k: v for k, v in {**index_obj(e), **{k: e.get(k) for k in WATER_EVENT_EXTRA}}.items()
                        if v not in (None, [], "")} for e in w_events]}))
        g = status_mod.water_geometry(slug, waters)
        geom = geojson_geometry(g) if g is not None else None
        if geom is None:
            missing_geom.append(slug)
            continue
        features.append({"type": "Feature", "id": slug, "geometry": geom, "properties": {
            # rivers, bays and sounds are drawn as grey outlines only (coverage); their discharge colour is on
            # out/reaches.geojson and the outfall markers; lakes, ponds and reservoirs are filled by status
            "slug": slug, "name": w["name"], "kind": w["kind"], "state": w["state"],
            # a monthly mark is a dotted outline on every kind of water (docs/plan.md §2.x); other colours fill
            # lakes and ponds only
            "status": w["status"] if w.get("fill", True) or w["status"] == "monthly" else "grey",
            "water_status": w["status"], **monthly_props(w),
            "category": (w.get("headline") or {}).get("category") or "sewage",
            "status_by_category": w.get("status_by_category"),
            "headline_status": (w.get("headline") or {}).get("status"),
            "display": "fill" if w.get("fill", True) else "outline", "summary": w.get("summary"),
            **({"stretch_model": w["stretch_model"]} if w.get("stretch_model") else {}),
            "since": w["since"], "reason_short": w["reason_short"], "event_count": len(w["events"]),
            "stale": w["stale"], "stale_since": min((s["last_ok_at"] for s in w["stale_sources"] if s.get("last_ok_at")), default=None),
            "fixture_only": w.get("fixture_only", False), "extra": bool(rec.get("extra")),
            # the colour comes from "Discharge likely: heavy rain, no report received" (its own legend entry)
            "rain_likely": bool(w["reasons"]) and w["reasons"][0]["rule"] == "rain_likely",
            # which amount set it (operator, state, default: "Discharge possible" for the default), else absent
            **({"rain_trigger_basis": w["reasons"][0].get("trigger_basis")}
               if w["reasons"] and w["reasons"][0]["rule"] == "rain_likely" else {})}})
    # waters.json is the index: per-water event ids and outfalls are in waters/<slug>.json
    index_rows = [{**{k: v for k, v in r.items() if k not in ("events", "outfalls", "provisional_outfalls")},
                   "outfall_count": len(r["outfalls"])}
                  for r in tracked]
    write_compact(OUT_DIR / "waters.json", {"built": now_iso(), "status_built": st["built"], "fixtures_included": include_fixtures,
                                            "count": len(tracked), "waters": publicize(index_rows)})
    write_compact(OUT_DIR / "overlays.geojson", {"type": "FeatureCollection", "features": features})
    write_compact(OUT_DIR / "launches.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": lo["slug"], "geometry": {"type": "Point", "coordinates": [lo["lon"], lo["lat"]]},
         "properties": {k: v for k, v in lo.items() if k not in ("lat", "lon")}}
        for lo in launch_feats.values() if lo["lat"] is not None and lo["lon"] is not None]})

    # advisory markers: beach, rain and HAB advisories that colour no water
    pts = []
    for ap in st.get("advisory_points") or []:
        e = by_event.get(ap["event_id"])
        if not e or e.get("lat") is None or e.get("lon") is None:
            continue
        lon, lat = round(float(e["lon"]), 5), round(float(e["lat"]), 5)
        pts.append({"type": "Feature", "id": e["event_id"], "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {"event_id": e["event_id"], "lat": lat, "lon": lon, "status": ap["status"],
                                   "rule": ap.get("rule"), "type": e["event_type"], "event_status": e.get("status"),
                                   "category": ap.get("category") or status_mod.category_of(e["event_type"]),
                                   "authority": e.get("authority"), "name": e.get("waterbody_text"),
                                   "started": e.get("started_at"), "ended": e.get("ended_at"), "until": ap.get("until"),
                                   "water_slugs": ap.get("water_slugs") or [], "why": ap.get("why"),
                                   # replay: the strictest of these for the hour, not today's status
                                   "intervals": ap.get("intervals") or [],
                                   "fixture": e.get("fixture", False), "file": e.get("file")}})
    write_compact(OUT_DIR / "advisory-points.geojson", {"type": "FeatureCollection", "features": pts})
    # the outfalls whose latest report is a monthly total (docs/plan.md §2.x); scripts/export-outfalls.py merges
    # them into out/outfalls.json (`status: "monthly"`, days, month, received_at, label) for the map's points
    write_compact(OUT_DIR / "monthly-outfalls.json", {"built": now_iso(), "status_now": st.get("now"),
                                                      "outfalls": publicize(st.get("monthly_outfalls") or [])})

    # modeled reaches: active events x segments, the stop markers, and every traced path for replay
    from build import reaches as reaches_mod
    reach_cache = reaches_mod.load_reaches()
    reach_feats, path_feats = reach_features(st, by_event, reach_cache)
    write_compact(OUT_DIR / "reaches.geojson", {"type": "FeatureCollection", "features": reach_feats})
    write_compact(OUT_DIR / "reach-paths.geojson", {"type": "FeatureCollection", "features": path_feats})
    # the same features per state (out/reaches/<st>.geojson, index.json), for the map to load by state
    by_state, no_state = reaches_by_state(reach_feats, path_feats, st, reach_cache, status_mod.states())
    reach_index = write_reach_state_files(by_state, without_state=no_state)
    if no_state:
        print(f"export: {len(no_state)} reach(es) touch no live state and are only in the national files: "
              f"{', '.join(no_state[:5])}{' ...' if len(no_state) > 5 else ''}")

    # history: only tracked waters (all are, by construction)
    hist_out = dict(hist)
    hist_out["waters"] = {s: v for s, v in hist["waters"].items() if s in st["waters"]}
    hist_out["intervals"] = {s: v for s, v in (hist.get("intervals") or {}).items() if s in st["waters"]}
    write_compact(OUT_DIR / "history.json", hist_out)

    # dischargers (loaded above; event counts by the canonical discharger_id, else by permit)
    ev_by_permit = defaultdict(list)
    for e in out_events:
        if e.get("npdes_permit"):
            ev_by_permit[e["npdes_permit"]].append(e)
    ev_by_discharger = events_by_discharger(dis, out_events)
    dis_permits = set()
    for d in dis:
        p = d.get("npdes_permit")
        dis_permits.add(p)
        evs = ev_by_discharger.get(d.get("id"), [])
        # the outlets of every permit the operator holds (its own permit first), from the whole registry
        listed = operator_outfalls(d, outfalls_by_permit, outfalls_by_operator)
        d["outfalls"] = official(listed)                    # EPA's and the states' listings: CSO and plant outfalls
        # the places its own overflow reports put an overflow, under their own heading: "Provisional location from
        # overflow reports" (record_status, confidence, report_count, last_report_at, event_ids, reached_water, on_map)
        d["provisional_outfalls"] = provisional(listed)
        d["outfall_water_slugs"] = sorted({o["water_slug"] for o in d["outfalls"] if o.get("water_slug")})
        d["event_count"] = len(evs)
        d["event_count_by_type"] = dict(Counter(e["event_type"] for e in evs))
        # the latest report: a start in the future as published is not one (status.FUTURE_START_H)
        d["last_event_at"] = max((e.get("started_at") or "" for e in evs if not e.get("future_start")), default=None) or None
    unknown_permits = sorted(p for p in ev_by_permit if p not in dis_permits)
    write_compact(OUT_DIR / "dischargers.json", {"built": now_iso(), "from": dis_from, "count": len(dis),
                                                 "permits_with_events_not_listed": unknown_permits, "dischargers": dis})
    # the map's outfall points and the live layer's lookups (export/outfalls.py): the same registry rows, the operator
    # by permit, the rain caution by permit and the monthly marks
    outfall_points = outfalls_mod.outfall_rows(
        outfalls, status_mod.states(), waters=set(waters), canon=lambda s: status_mod.SLUG_ALIASES.get(s, s),
        dischargers=dis, rain_permits=rain_block.get("permits") or {}, ma_layer=outfalls_mod.ma_layer_rows(),
        marks=publicize(st.get("monthly_outfalls") or []))
    outfalls_mod.write(outfall_points, OUT_DIR, now_iso())
    print(f"export: {outfalls_mod.summary(outfall_points)}")

    # sources
    feed_of = {}
    for sid, h in health.items():
        for rid in h.get("registry_ids") or []:
            feed_of.setdefault(rid, sid)
    reg_rows = []
    for rid, r in sorted(registry.items()):
        row = {k: r.get(k) for k in REGISTRY_KEYS}
        row["id"] = row["id"] or rid
        row["feed"] = feed_of.get(rid)
        row["health"] = health.get(feed_of.get(rid)) if feed_of.get(rid) else None
        for k in ("attribution", "name"):
            if isinstance(row.get(k), str):
                row[k] = ARCGIS_OWNER.sub("", row[k])       # an ArcGIS account name is not attribution
        reg_rows.append(row)
    reg_rows = live_registry_rows(reg_rows, status_mod.states())  # the live states' and the national rows only
    kept_rids = {r["id"] for r in reg_rows}
    feeds = []
    for sid, h in sorted(health.items()):
        f = files.get(sid) or {}
        meta_pub = {k: v for k, v in (f.get("meta") or {}).items() if k in PUBLIC_FEED_META}
        feeds.append({**h, "file": f.get("file"), "meta": meta_pub,
                      "waters_covered": sum(1 for w in st["waters"].values() if sid in w["covered_by"])})
    feeds = live_feeds(feeds, kept_rids)
    write_compact(OUT_DIR / "sources.json", {"built": now_iso(), "feeds": feeds, "registry": reg_rows})

    # what is reported, state by state and water by water (docs/plan.md §2.y; export/coverage.py), with where the
    # "discharge likely" caution is computed (rain_caution_states: build/rain_likely.caution_coverage)
    from export import coverage as coverage_mod
    cov = coverage_mod.coverage(
        csv_events, tracked, feeds, reg_rows, dis, status_mod.load_rules(), st.get("now"),
        rain_states=rain_caution_states(rain_block), notification_pages=coverage_mod.load_notification_pages(),
        register=coverage_mod.load_register(),
        # the level of each feed's registry rows, read from the whole registry (not only the live rows)
        source_levels={sid: sorted({str((registry.get(rid) or {}).get("level") or "") for rid in h.get("registry_ids") or []}
                                   - {""}) for sid, h in health.items()})
    cov["states"] = {k: v for k, v in (cov.get("states") or {}).items() if k in status_mod.states()}   # live only
    write_compact(OUT_DIR / "coverage.json", {"built": now_iso(), "status_now": st.get("now"), **cov})

    # CSV downloads of the reports per water, operator and state, and all of them (export/csv.py,
    # docs/data-downloads.md). The same public records as above; a failure is logged and the export goes on.
    csv_files = 0
    try:
        from export import csv as csv_export
        active_ids = {a["event_id"] for a in active if a.get("kind") != "rain_likely" and a.get("event_id")}
        page_ids = csv_export.event_page_ids(csv_events, tracked, active_ids, as_of=st.get("now"))
        # a source's states as the site's sources list gives them (a feed: its registry rows'), the last fallback of
        # the site's eventState for a record's archive row (csv.SiteLinks)
        reg_states = {r["id"]: [str(x).upper() for x in r.get("states") or []] for r in reg_rows if r.get("id")}
        source_states = dict(reg_states)
        for f in feeds:
            source_states[f["source_id"]] = list(dict.fromkeys(x for rid in f.get("registry_ids") or []
                                                               for x in reg_states.get(rid, [])))
        csv_counts = csv_export.write_csvs(
            csv_events, tracked, dis, OUT_DIR / "csv", page_ids=page_ids,
            source_names=csv_export.source_labels(csv_events, feeds, reg_rows),
            states=set(status_mod.states()),
            as_of=st.get("now"), active_ids=active_ids, source_states=source_states)
        csv_files = csv_counts["files"]
        if csv_counts["oversize"]:          # the host takes no file over 25 MiB; scripts/mirror-csv.sh leaves them out
            note = f"csv files over 25 MiB are not published on the site: {', '.join(csv_counts['oversize'])}"
            print(f"export: {note}")
            problems.append(note)
    except Exception as exc:
        print(f"export: CSV files not written ({type(exc).__name__}: {exc})")
        problems.append(f"csv export failed: {type(exc).__name__}: {exc}")

    # meta
    by_state_status = defaultdict(lambda: Counter())
    for w in tracked:
        by_state_status[w["state"]][w["status"]] += 1
    totals = Counter(w["status"] for w in tracked)
    counted = [e for e in out_events if not e.get("duplicate_of")]
    ev_state = Counter()
    for e in counted:
        ev_state[e.get("state") or status_mod.event_state(e) or "unknown"] += 1
    meta = {
        "built": now_iso(), "status_built": st["built"], "status_now": st.get("now"),
        "fixture": include_fixtures and any(e["fixture"] for e in out_events),   # the site's sample-data banner
        "restricted_included": include_restricted, "withheld_sources": st.get("withheld_sources") or [],
        "advisory_points": len(pts), "duplicates": len(st.get("duplicates") or {}),
        "legend": st.get("legend"),
        "reaches": {"traced_paths": len(path_feats), "with_events": len(st.get("reaches") or {}),
                    "active_events": len(st.get("reach_events_active") or []),
                    "segment_features": sum(1 for f in reach_feats if f["properties"]["feature"] == "segment"),
                    "cut_reasons": dict(Counter(f["properties"]["cut_reason"] for f in path_feats)),
                    "state_files": {e["state"]: e["features"] for e in reach_index["files"]}},
        "counts": {
            "waters": len(tracked), "waters_by_status": dict(totals),
            "waters_by_state": {s: dict(c) for s, c in sorted(by_state_status.items())},
            "waters_stale": sum(1 for w in tracked if w["stale"]),
            # counts leave out duplicates (duplicate_of: ECHO copies, the CT annual sheet's dashboard rows);
            # the duplicates stay in events.json and on water and discharger pages
            "events": len(counted), "events_with_duplicates": len(out_events),
            "events_by_type": dict(Counter(e["event_type"] for e in counted)),
            "events_by_category": dict(Counter(e.get("category") or status_mod.category_of(e["event_type"]) for e in counted)),
            "waters_by_category": {c: dict(Counter((w.get("status_by_category") or {}).get(c, "grey") for w in tracked))
                                   for c in status_mod.CATEGORIES},
            "events_by_state": dict(ev_state), "events_by_source": dict(Counter(e["source_id"] for e in counted)),
            "events_placed": sum(1 for e in counted if e["water_slugs"]),
            "events_no_receiving_water": sum(1 for e in counted if not e["water_slugs"] and e.get("no_receiving_water")),
            "events_unplaced": sum(1 for e in counted if not e["water_slugs"] and not e.get("no_receiving_water")),
            "events_future_start": sum(1 for e in counted if e.get("future_start")),
            "dischargers": len(dis), "feeds": len(feeds), "registry_sources": len(reg_rows),
        },
        "stale_sources": [h["source_id"] for h in health.values() if h.get("stale")],
        "rules": st.get("rules"), "advisory_windows": {"file": "rules.json",
                                                       "version": (st.get("advisory_windows") or {}).get("version")},
        "constants": public_constants(st.get("constants") or {}),
        "event_file_encoding": "out/events/<f>.json: f is the event_id with every character outside [A-Za-z0-9._-] "
                               "written as ~XX (its UTF-8 bytes in upper-case hex), e.g. ':' -> '~3A'",
        "wording": "Grey means no current report, never clean or safe. There is no green state.",
        "overlay_geometry": "openboatlaunch out/water/<slug>.json (or the inline geometry of a data/waters-extra.json, waters-dc.json "
                            "or waters-nhd.json record, extra: true), simplified ~20 m, coordinates to 5 decimals",
        "active_events": len(active),
        "csv_files": csv_files,
        "rain_likely": {"enabled": bool(rain_block.get("enabled")), "label": status_mod.RULES["rain_likely"][1],
                        "label_by_basis": rain_block.get("label_by_basis"),
                        "rules_ref": "rain_likely", "file": "rain.json",
                        "rainfall_valid_time": (rain_block.get("rainfall") or {}).get("valid_time"),
                        "rainfall_stale": (rain_block.get("rainfall") or {}).get("stale"),
                        **(rain_block.get("counts") or {}),
                        "active": sum(1 for a in active if a.get("kind") == "rain_likely")},
        "conditions": {"built": conditions["built"], "waters_with_gauge": conditions["count"],
                       "with_flow": sum(1 for r in conditions["waters"].values() if r.get("flow_cfs") is not None),
                       "with_temperature": sum(1 for r in conditions["waters"].values() if r.get("temp_c") is not None),
                       "with_turbidity": sum(1 for r in conditions["waters"].values() if r.get("turbidity_ntu") is not None)},
        "waters_without_geometry": missing_geom,
        "problems": (st.get("problems") or []) + problems,
    }
    write_compact(OUT_DIR / "meta.json", meta)
    rules_src = DATA_DIR / "rules.json"
    if rules_src.exists():                  # the methods page prints it; internal "_" keys stay home
        write_json(OUT_DIR / "rules.json", live_rules(public_rules(json.loads(rules_src.read_text())), status_mod.states()))
    for name in ("meta.json", "sources.json", "waters.json", "conditions.json", "active.json", "dischargers.json",
                 "coverage.json", "monthly-outfalls.json", "outfalls.json"):
        hits = internal_wording(read_json(OUT_DIR / name))
        if hits:
            print(f"export: internal wording left in {name}: {', '.join(sorted(set(hits))[:5])}")
    for h in wording_in_status(st):         # reasons, rule records and monthly marks as published (SOL P2-8)
        wording[h.split("[")[0] + "[]"] += 1
    if wording:                             # the records' placement texts (public_note rewords the registry paths)
        note = (f"internal wording or a repository path left in the placement texts of the event records: "
                f"{', '.join(f'{k} {n}' for k, n in sorted(wording.items()))}")
        print(f"export: {note}")
        meta["problems"].append(note)
        write_compact(OUT_DIR / "meta.json", meta)
    # the owner's blocklist, checked in what was written: a name in events.json, waters/*.json or the full
    # records fails the export (review 2026-11-03 P1-1; scripts/refresh.sh then uploads and deploys nothing)
    checked = enforce_blocklist(OUT_DIR)
    print(f"export: blocklist self-check passed ({checked} files)")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixtures", action="store_true",
                    help="include the research fixture events (development only; needs DWW_ALLOW_FIXTURES=1)")
    ap.add_argument("--no-fixtures", action="store_true", help="the default; kept for old command lines")
    ap.add_argument("--include-nhdes", action="store_true",
                    help="include events files marked distribution_discouraged (NHDES Healthy Swimming)")
    a = ap.parse_args()
    m = export(include_fixtures=a.fixtures and not a.no_fixtures, include_restricted=a.include_nhdes)
    c = m["counts"]
    print(f"export: {c['waters']} waters {c['waters_by_status']}, {c['events']} events "
          f"(fixtures {'in' if m['fixture'] else 'out'}), {c['dischargers']} dischargers, {c['feeds']} feeds -> {OUT_DIR}")


if __name__ == "__main__":
    main()
