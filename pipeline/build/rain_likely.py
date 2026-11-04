"""The "discharge likely; no report received" caution (docs/rain-likely.md), for build/status.py.

When rules.rain_likely.enabled is true: for each permittee with CSO outfalls, while the NOAA MRMS
radar 24-hour rainfall total at any of its outfall points is at or above the permittee's threshold
(build/rain_thresholds.py: the 10th percentile of the rainfall on its past discharge days, or the
published fallback), and no discharge notice from that permittee has started in the last 24 hours,
its modeled river reaches, the rivers they run along, and the lakes and ponds its outfalls discharge
to are yellow with the rule "rain_likely". The caution lasts until 48 hours after the 24-hour total
falls below the threshold (rules.rain_likely.tail_hours). Being yellow it never overrides red.

Inputs: data/build/rainfall.json and rainfall-history.json (ingest/rainfall.py) and
data/build/rain-thresholds.json. Everything here is pure except load_inputs().

Mid-Atlantic (2026-11-03): the radar reading covers New York, Pennsylvania, Maryland, Virginia and DC too (the
mid-Atlantic outfall registry), read as one MRMS grid an hour sampled at every outfall point (ingest/rainfall.py,
ingest/mrms_grid.py); their thresholds are the state's published rain trigger where one is documented
(rules.rain_likely.fallback.by_state), else the default. Every record names the product and how it was read
(rainfall_product, rainfall_read) and the threshold's source (threshold_source).

New Jersey (2026-11-03): the 15 New Jersey CSO permits on the permittees' shared site keep the site, not the radar;
New Jersey's other CSO permits (Camden City, Hoboken's Adams Street, Gloucester City, River Road, Camden County,
Trenton) are read by the radar like every other state's, at the site default threshold (New Jersey publishes no
rain trigger), and coverage names both methods. For the 15 New Jersey
CSO permits on the permittees' shared notification site (njcsonotifications.com, ingest/nj_cso_likely.py), the
site's own flag stands in for the radar total: an hour with the 1-hour or 4-hour rainfall over the permittee's
threshold on that site is "above", the same episodes, 48-hour tail, notice suppression and placement follow, and
the record cites the site (rain.basis "site_flag", source_id nj-cso-likely). Its history is
data/build/nj-cso-likely-history.json (one observation per hourly fetch). caution_coverage() says, per state,
whether and how the caution is computed (out/coverage.json rain_caution_states).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from common import BUILD_DIR, DATA_DIR, load_outfall_registry, read_json

RULE = "rain_likely"
# the site default where the state publishes no rain trigger of its own (owner, 2026-11-03: no other operator's
# permit is named; the methods page is its citation)
SITE_DEFAULT_TEXT = ("this site's default: 0.1 inch of rain in 24 hours at a combined sewer outfall, applied where the "
                     "state publishes no rain trigger of its own")
SITE_DEFAULT_SOURCE = "This site's methods page"
SITE_SOURCE_ID = "nj-cso-likely"
SITE_NAME = "the New Jersey CSO permittees' shared notification site (njcsonotifications.com)"
SITE_URL = "https://njcsonotifications.com/"
SITE_RAIN = "rainfall estimates on the permittees' shared site (Iowa Environmental Mesonet), 1-hour and 4-hour totals"
LABEL = "Discharge likely: heavy rain, no report received"
# Which amount set the caution (owner, 2026-11-04 evening): the operator's own discharge history ("operator"; New
# Jersey's shared site flags on each permittee's own threshold count as the operator's), a trigger the state
# publishes ("state"), or this site's default of 0.1 inch ("default"). The label follows it: where only the
# default applies the caution reads "Discharge possible", because at that amount no overflow followed on about
# half of past rainy days (rules.rain_likely.label_by_basis, fallback.default.cost_rationale). The colour, the
# rule id and the tail do not change.
TRIGGER_BASES = ("operator", "state", "default")
LABEL_POSSIBLE = "Discharge possible: heavy rain, no report received"
LABELS = {"operator": LABEL, "state": LABEL, "default": LABEL_POSSIBLE}
BASIS_OF_KIND = {"operator_history": "operator", "shared_site": "operator", "state": "state", "site_default": "default"}
SOURCE_ID = "noaa-mrms-qpe-imageserver"
QPF_SOURCE_ID = "nws-api-gridpoint-qpf"
RAINFALL_SOURCE = "NOAA MRMS radar-only rainfall estimate (1 km), 24-hour total"
PRODUCT = "NOAA MRMS radar-only quantitative precipitation estimate, 1 km, 24-hour total (conus_QPE_24H)"
MRMS_SERVICE = "https://mapservices.weather.noaa.gov/raster/rest/services/obs/mrms_qpe/ImageServer"
READ_TEXT = {"grid": "one radar grid an hour, sampled at each outfall", "point": "read hourly at each outfall point",
             "plant_point": "rainfall read at the treatment plant; the outfalls' own locations are not published"}
DISCHARGE_TYPES = {"cso", "sso", "bypass", "blended", "plant_bypass"}
WHOLE_WATER_KINDS = {"lake", "pond", "reservoir"}
RIVER_KINDS = {"river", "stream", "canal"}
DEFAULTS = {"tail_hours": 48, "notice_suppress_hours": 24, "rainfall_stale_hours": 3, "cadence_hours": 2}
H = timedelta(hours=1)
INSIDE_M = 30                  # an outfall this close to a lake (or in it) discharges to it


def parse_t(s) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        from build.status import LOCAL
        t = t.replace(tzinfo=LOCAL)
    return t.astimezone(UTC)


def iso(t: datetime | None) -> str | None:
    return t.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z") if t else None


def settings(rules: dict) -> dict:
    rl = (rules or {}).get(RULE) or {}
    return {**DEFAULTS, **{k: rl[k] for k in DEFAULTS if rl.get(k) is not None},
            "enabled": rl.get("enabled") is True, "doc": rl.get("doc"), "source": rl.get("source"),
            "label": rl.get("label") or LABEL, "labels": labels(rules)}


def labels(rules: dict) -> dict[str, str]:
    """The caution's label by trigger basis (rules.rain_likely.label_by_basis, else LABELS)."""
    rl = (rules or {}).get(RULE) or {}
    given = rl.get("label_by_basis") or {}
    base = rl.get("label") or LABEL
    return {b: given.get(b) or (LABEL_POSSIBLE if b == "default" else base) for b in TRIGGER_BASES}


def label_for(basis: str | None, rules_or_cfg: dict | None = None) -> str:
    """The label for one trigger basis; an unknown or missing basis reads as "likely" (the label it had before)."""
    cfg = rules_or_cfg or {}
    lab = cfg["labels"] if "labels" in cfg else labels(cfg)
    return lab.get(basis or "operator") or lab["operator"]


def basis_of(row: dict) -> str:
    """A permittee row's or rain record's trigger basis, worked out from its threshold fields when it carries none."""
    if row.get("trigger_basis") in TRIGGER_BASES:
        return row["trigger_basis"]
    if row.get("threshold_kind") in BASIS_OF_KIND:
        return BASIS_OF_KIND[row["threshold_kind"]]
    if row.get("threshold_basis") == "published":
        return "default" if str(row.get("threshold_rule") or "").endswith("fallback.default") else "state"
    return "operator"


def strongest_basis(bases) -> str | None:
    """The basis a water or state shows when several operators' cautions meet: an operator's own amount, else a
    state's, else the default (the label reads "likely" whenever any caution there rests on more than the default)."""
    got = {b for b in bases if b}
    return next((b for b in TRIGGER_BASES if b in got), None)


def enabled(rules: dict) -> bool:
    return settings(rules)["enabled"]


def load_inputs() -> dict:
    return {"rainfall": read_json(BUILD_DIR / "rainfall.json") or {},
            "history": read_json(BUILD_DIR / "rainfall-history.json") or {},
            "thresholds": read_json(BUILD_DIR / "rain-thresholds.json") or {},
            "dischargers": discharger_index(), "site_flags": site_inputs()}


def shared_site_permits(build_dir=None) -> set[str]:
    """The permits New Jersey's shared notification site flags (its latest snapshot and its history): their caution
    comes from the site; every other combined sewer permit, New Jersey's included, is read by the radar."""
    d = BUILD_DIR if build_dir is None else build_dir
    snap = read_json(d / "nj-cso-likely.json") or {}
    hist = read_json(d / "nj-cso-likely-history.json") or {}
    return {r.get("npdes_permit") for r in snap.get("permittees") or [] if r.get("npdes_permit")} \
        | set(hist.get("observations") or {})


def site_inputs() -> dict:
    """New Jersey's shared notification site: the latest snapshot, the history of its flags and the registry
    outfalls of its permits (every data/outfalls-*.json through common.load_outfall_registry; combined sewer
    outfalls only, closed ones left out)."""
    snap = read_json(BUILD_DIR / "nj-cso-likely.json") or {}
    hist = read_json(BUILD_DIR / "nj-cso-likely-history.json") or {}
    permits = {r.get("npdes_permit") for r in snap.get("permittees") or []} | set(hist.get("observations") or {})
    rows = load_outfall_registry(DATA_DIR) if permits else []
    outs = [{"permit": r["npdes_permit"], "outfall": r.get("outfall"), "water_slug": r.get("water_slug"),
             "water_match": r.get("match"), "distance_m": r.get("distance_m"), "lat": r.get("lat"), "lon": r.get("lon")}
            for r in rows if r.get("npdes_permit") in permits and cso_open(r)]
    return {"snapshot": snap, "history": hist, "outfalls": outs, "permits": sorted(p for p in permits if p)} \
        if (snap or hist) else {}


def cso_open(o: dict) -> bool:
    """A registry row the caution reads: a combined sewer outfall (outfall_kind "cso"; plant outfalls never drive
    it) that is not closed (outfall_status CLS)."""
    return (o.get("outfall_kind") or "cso") == "cso" and not str(o.get("outfall_status") or "").upper().startswith("CLS")


def discharger_index() -> dict[str, dict]:
    """{npdes permit: {id, name}} from data/dischargers.json (the discharger pages)."""
    d = read_json(DATA_DIR / "dischargers.json") or {}
    rows = d.get("dischargers", d) if isinstance(d, dict) else d
    out = {}
    for r in rows if isinstance(rows, list) else []:
        for p in [r.get("npdes_permit")] + list(r.get("npdes_permits") or []):
            if p and r.get("id"):
                out.setdefault(p, {"id": r["id"], "name": r.get("name")})
    return out


def threshold_for(permit: str, state: str | None, thresholds: dict, rules: dict) -> dict:
    """The permittee's own threshold from its reporting history (rain-thresholds.json basis "history"), else the
    published rule for its state (rules.json rain_likely.fallback.by_state), else the site default; the published
    rule is read from rules.json on every path, so a row of rain-thresholds.json built before a state's rule was
    written never carries the default into that state (owner, 2026-11-03). kind: operator_history, state or
    site_default. trigger_basis: operator, state or default (TRIGGER_BASES); a state's entry that applies this site's
    default amount rather than a trigger of its own says so with "trigger_basis": "default" (Maryland, the District)."""
    row = ((thresholds or {}).get("permits") or {}).get(permit) or {}
    if row.get("threshold_in") is not None and row.get("basis") == "history":
        return {"threshold_in": float(row["threshold_in"]), "basis": row.get("basis"), "rule": row.get("rule"),
                "text": row.get("basis_text"), "source": row.get("source"), "n_discharge_days": row.get("n_discharge_days"),
                "since": row.get("since"), "until": row.get("until"), "name": row.get("name"), "kind": "operator_history",
                "trigger_basis": "operator"}
    fb = ((rules or {}).get(RULE) or {}).get("fallback") or {}
    r = (fb.get("by_state") or {}).get((state or "").upper())
    key = f"rain_likely.fallback.by_state.{(state or '').upper()}" if r else "rain_likely.fallback.default"
    r = r or fb.get("default") or {"inches": 0.1, "basis": SITE_DEFAULT_TEXT, "source": SITE_DEFAULT_SOURCE}
    kind = "state" if key.endswith(f".{(state or '').upper()}") and (state or "") else "site_default"
    basis = r.get("trigger_basis") if r.get("trigger_basis") in TRIGGER_BASES else BASIS_OF_KIND[kind]
    return {"threshold_in": r.get("inches"), "basis": "published", "rule": key, "text": r.get("basis"),
            "source": r.get("source"), "n_discharge_days": row.get("n_discharge_days"), "since": row.get("since"),
            "until": row.get("until"), "name": row.get("name"), "kind": kind, "trigger_basis": basis}


# ---------------------------------------------------------------- the rule in time

def runs(values: list, start: datetime, threshold: float, now: datetime, tail_hours: float = 48,
         stale_hours: float = 3) -> list[dict]:
    """Episodes from an hourly series of 24-hour totals (values[i] is the total for the 24 hours
    ending at start + i hours; None = no reading). An episode begins at the first hour at or above
    the threshold and ends tail_hours after the first later reading below it. A run still above at
    the latest reading is open (end None) while that reading is at most stale_hours old; with older
    readings it ends tail_hours after the last reading above (rainfall_stale). Episodes that touch
    are merged. Readings after now are ignored."""
    tail = timedelta(hours=tail_hours)
    out, cur, last_reading = [], None, None
    for i, v in enumerate(values or []):
        t = start + i * H
        if t > now:
            break
        if v is None:
            continue
        last_reading = t
        if v >= threshold:
            if cur is None:
                cur = {"start": t, "peak": v, "peak_at": t, "last_above": t}
            else:
                cur["last_above"] = t
                if v > cur["peak"]:
                    cur["peak"], cur["peak_at"] = v, t
        elif cur is not None:
            cur.update(dropped_at=t, end=t + tail)
            out.append(cur)
            cur = None
    if cur is not None:
        if last_reading is not None and now - last_reading <= timedelta(hours=stale_hours):
            cur.update(dropped_at=None, end=None)
        else:
            cur.update(dropped_at=None, end=cur["last_above"] + tail, rainfall_stale=True)
        out.append(cur)
    merged = []
    for r in out:
        if merged and (merged[-1]["end"] is None or r["start"] <= merged[-1]["end"]):
            m = merged[-1]
            if r["peak"] > m["peak"]:
                m["peak"], m["peak_at"] = r["peak"], r["peak_at"]
            m["last_above"] = max(m["last_above"], r["last_above"])
            m["dropped_at"], m["end"] = r.get("dropped_at"), r["end"]
            if r.get("rainfall_stale"):
                m["rainfall_stale"] = True
        else:
            merged.append(dict(r))
    return merged


def subtract(a: datetime, b: datetime | None, blocks: list[tuple[datetime, datetime]]) -> list[tuple]:
    """[a, b) (b None: open) minus the union of the blocks, as a list of (start, end) pieces."""
    pieces = [(a, b)]
    for s, e in sorted(blocks):
        nxt = []
        for x, y in pieces:
            if (y is not None and s >= y) or e <= x:
                nxt.append((x, y))
                continue
            if s > x:
                nxt.append((x, s))
            if y is None or e < y:
                nxt.append((e, y))
        pieces = nxt
    return [(x, y) for x, y in pieces if y is None or y > x]


def discharge_starts(events: list[dict]) -> dict[str, list[tuple[datetime, str]]]:
    """{permit: [(start, event_id)]} for every discharge notice with a permit and a start (any
    source, any status; month and year records are not notices of a start)."""
    out = defaultdict(list)
    for ev in events:
        if ev.get("time_precision") in ("month", "year") or not ev.get("npdes_permit"):
            continue
        et = ev.get("event_type")
        if et not in DISCHARGE_TYPES and not (et == "unknown" and ev.get("status") == "ongoing"):
            continue
        t = parse_t(ev.get("started_at"))
        if t is not None:
            out[ev["npdes_permit"]].append((t, ev["event_id"]))
    return out


# ---------------------------------------------------------------- where it goes

def targets(permit: str, waters: dict, outfalls: list[dict], rain_outfalls: list[dict], reaches: dict,
            reach_waters_fn) -> tuple[list[str], dict, dict, list[dict]]:
    """(reach keys, {water slug: placement tag}, {slug: reach keys}, set aside) for a permittee: its
    traced reaches and the rivers they run along ("reach"), the waters its outfalls discharge to:
    lakes, ponds and reservoirs whole (None), rivers with no traced reach ("unmodeled"), bays, sounds
    and outfalls already tidal ("tidal"). A lake, pond or reservoir is filled only when the outfall
    registry matched it by name (the receiving water the permit names agrees) or the outfall lies in
    it or at its shore (within INSIDE_M); a match by distance alone further off is set aside, since
    filling a whole lake is a strong claim."""
    keys, tags, reach_of, aside = [], {}, defaultdict(set), []
    for key, r in sorted((reaches or {}).items()):
        if r.get("permit") != permit or r.get("cut_reason") == "no_trace":
            continue
        if r.get("model") == "shoreline" and r.get("outfall_kind") == "plant":
            continue        # a treatment plant's shoreline stretch: the permittee's CSO rain caution never reads it
        if r.get("segments"):
            keys.append(key)
            on = set(reach_waters_fn(r, waters))
            if r.get("water_slug") in waters:
                on.add(r["water_slug"])
            for s in on:
                tags[s] = "reach"
                reach_of[s].add(key)
        elif r.get("water_slug") in waters and r.get("cut_reason") in ("tidal_at_outfall", "lake_at_outfall"):
            tags.setdefault(r["water_slug"], "tidal")
    found = {}
    for o in outfalls or []:
        if o.get("npdes_permit") == permit and cso_open(o) and o.get("water_slug"):
            found.setdefault(o["water_slug"], []).append((o.get("outfall"), o.get("match"), o.get("distance_m")))
    for o in rain_outfalls or []:
        if o.get("water_slug"):
            found.setdefault(o["water_slug"], []).append((o.get("outfall"), o.get("water_match"), o.get("distance_m")))
    for s in sorted(found):
        if s not in waters or s in tags:
            continue
        kind = waters[s].get("kind")
        if kind in RIVER_KINDS:
            tags[s] = "unmodeled"
        elif kind in ("bay", "sound"):
            tags[s] = "tidal"
        elif kind in WHOLE_WATER_KINDS and not any("name" in str(m or "") or m == "outfall_registry"
                                                   or (d is not None and d <= INSIDE_M) for _, m, d in found[s]):
            aside.append({"water_slug": s, "outfalls": sorted({str(o) for o, _, _ in found[s] if o}),
                          "reason": "outfall matched to this water by distance only; the permit names another water"})
        else:
            tags[s] = None
    return keys, tags, {k: sorted(v) for k, v in reach_of.items()}, aside


# ---------------------------------------------------------------- the intervals

def _point(key: str | None):
    try:
        lat, lon = (float(x) for x in str(key).split(","))
        return [lat, lon]
    except (TypeError, ValueError):
        return None


def compute(rain: dict, rules: dict, events: list[dict], now: datetime, h_start: datetime, waters: dict,
            outfalls: list[dict], reaches: dict, reach_waters_fn) -> tuple[dict, dict, dict]:
    """(intervals by water slug, intervals by reach key, the status.json "rain_likely" block).
    Each interval has the keys build.status gives an event's intervals, with event_id the episode
    id "rain_likely:<permit>:<start YYYYMMDDTHH>Z", rule "rain_likely" and a "rain" record for the
    page (the total, the threshold and its basis, the sources)."""
    cfg = settings(rules)
    rf = (rain or {}).get("rainfall") or {}
    hist = (rain or {}).get("history") or {}
    thresholds = (rain or {}).get("thresholds") or {}
    latest = rf.get("permits") or {}
    series = hist.get("permits") or {}
    start = parse_t(hist.get("start"))
    tail = float(cfg["tail_hours"])
    supp = timedelta(hours=float(cfg["notice_suppress_hours"]))
    starts = discharge_starts(events)
    fetched = parse_t(rf.get("fetched_at"))
    valid = parse_t((rf.get("mrms") or {}).get("valid_time"))
    stale = valid is None or now - valid > timedelta(hours=float(cfg["rainfall_stale_hours"]) + 1)
    by_water, by_reach = defaultdict(list), defaultdict(list)
    block = {"enabled": True, "rule": RULE, "label": cfg["label"], "label_by_basis": cfg["labels"], "tail_hours": tail,
             "notice_suppress_hours": supp.total_seconds() / 3600, "rainfall_stale_hours": cfg["rainfall_stale_hours"],
             "rainfall": {"source_id": SOURCE_ID, "source": RAINFALL_SOURCE, "fetched_at": iso(fetched),
                          "valid_time": iso(valid), "ok": rf.get("ok"), "last_ok_at": rf.get("last_ok_at"),
                          "error": rf.get("error"), "stale": stale, "points": (rf.get("mrms") or {}).get("points"),
                          "read": (rf.get("mrms") or {}).get("read"), "product": PRODUCT,
                          "states": (rf.get("mrms") or {}).get("states")},
             "forecast": {"source_id": QPF_SOURCE_ID, "window_hours": (rf.get("qpf") or {}).get("window_hours"),
                          "grids": (rf.get("qpf") or {}).get("grids")},
             "thresholds": {"built": thresholds.get("built"), "method": thresholds.get("method"),
                            "with_history": thresholds.get("with_history")},
             "permits": {}, "episodes": {}, "waters": {}, "problems": []}
    if not rf:
        block["problems"].append("no rainfall readings yet (data/build/rainfall.json missing)")
    site_permits = set(((rain or {}).get("site_flags") or {}).get("permits") or [])
    for permit in sorted(set(series) | set(latest)):
        if permit in site_permits:
            continue                    # its caution comes from the shared site (_site_flags), never twice
        info = latest.get(permit) or {}
        state = info.get("state") or permit[:2]
        thr = threshold_for(permit, state, thresholds, rules)
        if thr["threshold_in"] is None:
            continue
        t_in = float(thr["threshold_in"])
        dis = ((rain or {}).get("dischargers") or {}).get(permit) or {}
        name = dis.get("name") or thr.get("name") or info.get("name")
        keys, tags, reach_of, aside = targets(permit, waters, outfalls, info.get("outfalls") or [], reaches,
                                              reach_waters_fn)
        eps = runs(series.get(permit) or [], start, t_in, now, tail, float(cfg["rainfall_stale_hours"])) if start else []
        blocks = [(s, s + supp) for s, _ in starts.get(permit, []) if s <= now]
        h24 = info.get("h24")
        qpf = info.get("qpf_24h_in")
        prow = {"name": name, "discharger_id": dis.get("id"), "state": state, "threshold_in": t_in, "threshold_basis": thr["basis"],
                "threshold_rule": thr["rule"], "threshold_text": thr["text"], "threshold_source": thr.get("source"),
                "threshold_kind": thr["kind"], "trigger_basis": thr["trigger_basis"],
                "label": label_for(thr["trigger_basis"], cfg),
                "n_discharge_days": thr["n_discharge_days"],
                "history_since": thr["since"], "history_until": thr["until"],
                "rain_24h_in": h24, "rain_6h_in": info.get("h6"), "rain_12h_in": info.get("h12"),
                "rain_48h_in": info.get("h48"), "valid_time": info.get("valid_time"),
                "rainfall_product": info.get("product") or PRODUCT if h24 is not None else None,
                "rainfall_read": info.get("read") if h24 is not None else None,
                "rainfall_read_text": READ_TEXT.get(info.get("read")) if h24 is not None else None,
                "point": _point(info.get("h24_point")), "qpf_24h_in": qpf, "qpf_update_time": info.get("qpf_update_time"),
                "rain_expected": qpf is not None and qpf >= t_in,
                "status": "no_reading" if h24 is None else "below", "episode": None, "suppressed_by": [],
                "waters": sorted(tags), "reaches": keys, **({"set_aside": aside} if aside else {})}
        for ep in eps:
            eid = f"rain_likely:{permit}:{ep['start'].strftime('%Y%m%dT%H')}Z"
            pieces = [(a, b) for a, b in subtract(ep["start"], ep["end"], blocks)
                      if (b is None or b > h_start) and a <= now]
            by_notice = sorted({e for s, e in starts.get(permit, []) if s <= now
                                and s + supp > ep["start"] and (ep["end"] is None or s < ep["end"])})
            in_now = ep["start"] <= now and (ep["end"] is None or ep["end"] > now)
            active = any(a <= now and (b is None or b > now) for a, b in pieces)
            if in_now:
                prow["episode"] = eid
                prow["status"] = "likely" if active else "suppressed"
                prow["suppressed_by"] = [] if active else by_notice
            if not pieces and not in_now:
                continue
            rain_rec = {
                "permit": permit, "discharger_name": name, "discharger_id": dis.get("id"), "state": state,
                "threshold_in": t_in, "threshold_basis": thr["basis"], "threshold_rule": thr["rule"],
                "threshold_text": thr["text"], "threshold_source": thr.get("source"), "threshold_kind": thr["kind"],
                "trigger_basis": thr["trigger_basis"], "label": label_for(thr["trigger_basis"], cfg),
                "n_discharge_days": thr["n_discharge_days"],
                "history_since": thr["since"], "history_until": thr["until"],
                "peak_24h_in": round(ep["peak"], 2), "peak_at": iso(ep["peak_at"]),
                "above_from": iso(ep["start"]), "last_above_at": iso(ep["last_above"]),
                "dropped_below_at": iso(ep.get("dropped_at")), "until": iso(ep["end"]),
                "until_rule": f"{tail:g} hours after the 24-hour total falls below the threshold",
                "rain_24h_in": h24, "valid_time": info.get("valid_time"), "point": _point(info.get("h24_point")),
                "qpf_24h_in": qpf, "qpf_update_time": info.get("qpf_update_time"),
                "rainfall_source": RAINFALL_SOURCE, "rainfall_source_id": SOURCE_ID,
                # the product and how it was read (one grid an hour sampled at the outfall, or identify there)
                "rainfall_product": info.get("product") or PRODUCT, "rainfall_read": info.get("read"),
                "rainfall_read_text": READ_TEXT.get(info.get("read")),
                "rainfall_service": MRMS_SERVICE,
                "rainfall_stale": bool(ep.get("rainfall_stale")) or stale,
                "suppressed_by": by_notice,
            }
            rule_applied = {"rule": RULE, "threshold_in": t_in, "threshold_basis": thr["basis"], "tail_hours": tail,
                            "trigger_basis": thr["trigger_basis"], "rationale": cfg["doc"], "source": cfg["source"]}
            block["episodes"][eid] = {"permit": permit, "discharger_name": name, "discharger_id": dis.get("id"),
                                      "state": state, "trigger_basis": thr["trigger_basis"],
                                      "label": rain_rec["label"], "start": iso(ep["start"]),
                                      "end": iso(ep["end"]), "active": active, "in_effect": in_now,
                                      "pieces": [[iso(a), iso(b)] for a, b in pieces], "waters": sorted(tags),
                                      "reaches": keys, "rain": rain_rec}
            _emit(pieces, eid, ep, permit, rain_rec, rule_applied, cfg, tail, keys, tags, reach_of, by_water, by_reach,
                  SOURCE_ID, "NOAA MRMS radar estimate")
        block["permits"][permit] = prow
        for slug in tags:
            w = block["waters"].setdefault(slug, {"permits": [], "rain_24h_in": None, "qpf_24h_in": None,
                                                  "rain_expected": False, "likely": False, "sources": []})
            if SOURCE_ID not in w["sources"]:
                w["sources"].append(SOURCE_ID)
            w["permits"].append(permit)
            if h24 is not None:
                w["rain_24h_in"] = max(w["rain_24h_in"] or 0.0, h24)
            if qpf is not None:
                w["qpf_24h_in"] = max(w["qpf_24h_in"] or 0.0, qpf)
            w["rain_expected"] = w["rain_expected"] or prow["rain_expected"]
            w["likely"] = w["likely"] or prow["status"] == "likely"
    _site_flags((rain or {}).get("site_flags") or {}, cfg, now, h_start, waters, reaches, reach_waters_fn, starts, supp,
                tail, block, by_water, by_reach)
    # each water: the bases of its operators' amounts, and the one its caution reads by (the likely ones first)
    for w in block["waters"].values():
        rows = [block["permits"].get(p) or {} for p in w["permits"]]
        w["trigger_bases"] = sorted({r.get("trigger_basis") for r in rows if r.get("trigger_basis")},
                                    key=TRIGGER_BASES.index)
        w["trigger_basis"] = (strongest_basis(r.get("trigger_basis") for r in rows if r.get("status") == "likely")
                              or strongest_basis(w["trigger_bases"]))
        w["label"] = label_for(w["trigger_basis"], cfg)
    aside = sum(len(p.get("set_aside") or []) for p in block["permits"].values())
    if aside:
        block["problems"].append(f"{aside} lake or pond placement(s) set aside: outfall matched by distance only "
                                 "(permits[].set_aside)")
    block["counts"] = {"permits": len(block["permits"]),
                       "likely_now": sum(1 for p in block["permits"].values() if p["status"] == "likely"),
                       "suppressed_now": sum(1 for p in block["permits"].values() if p["status"] == "suppressed"),
                       "rain_expected": sum(1 for p in block["permits"].values() if p["rain_expected"]),
                       "episodes": len(block["episodes"])}
    return dict(by_water), dict(by_reach), block


def _emit(pieces, eid, ep, permit, rain_rec, rule_applied, cfg, tail, keys, tags, reach_of, by_water, by_reach,
          source_id, authority):
    """The intervals of one episode's pieces on its reaches and waters."""
    for a, b in pieces:
        iv = {"start": a, "end": b, "color": "yellow", "rule": RULE, "label": rain_rec.get("label") or cfg["label"],
              "trigger_basis": rain_rec.get("trigger_basis"),
              "rule_applied": rule_applied, "event_id": eid, "source_id": source_id, "fixture": False,
              "event_type": None, "event_status": None, "authority": authority,
              "window_hours": tail, "window_basis": rain_rec["until_rule"], "red_rule": None,
              "yellow_rule": {"rule": RULE, "hours": tail, "rationale": cfg["doc"], "source": cfg["source"]},
              "started_at": iso(ep["start"]), "ended_at": None, "permit": permit, "rain": rain_rec}
        for key in keys:
            by_reach[key].append({**iv, "placement": "reach", "reach": key})
        for slug, tag in tags.items():
            by_water[slug].append({**iv, "placement": tag,
                                   "reach": (reach_of.get(slug) or [None])[0] if tag == "reach" else None})


def _hour(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def site_series(obs: list, now: datetime) -> tuple[datetime | None, list]:
    """(start, values): an hourly series from the site's observations ([fetched_at, exceeded, ...]): 1.0 for an
    hour with a reading over the threshold, 0.0 for one with only readings under it, None without a reading."""
    rows = [(parse_t(o[0]), o[1]) for o in obs or [] if o and parse_t(o[0]) is not None]
    rows = [(t, ex) for t, ex in rows if t <= now]
    if not rows:
        return None, []
    t0 = _hour(min(t for t, _ in rows))
    vals = [None] * (int((_hour(now) - t0) / H) + 1)
    for t, ex in rows:
        if ex is None:
            continue
        i = int((_hour(t) - t0) / H)
        vals[i] = max(vals[i] or 0.0, 1.0 if ex else 0.0)
    return t0, vals


def _site_flags(site: dict, cfg: dict, now, h_start, waters, reaches, reach_waters_fn, starts, supp, tail, block,
                by_water, by_reach) -> None:
    """New Jersey's shared notification site: its exceedance flag as the caution at its permits' outfalls."""
    if not site:
        return
    snap, hist = site.get("snapshot") or {}, site.get("history") or {}
    rows = {r.get("npdes_permit"): r for r in snap.get("permittees") or [] if r.get("npdes_permit")}
    obs = hist.get("observations") or {}
    fetched = parse_t(snap.get("fetched_at"))
    last_ok = parse_t(snap.get("last_ok_at"))
    stale = last_ok is None or now - last_ok > timedelta(hours=float(cfg["rainfall_stale_hours"]) + 1) \
        or bool(snap.get("source_is_stale")) or bool(snap.get("source_is_historical"))
    block["site_flags"] = {"source_id": SITE_SOURCE_ID, "source": SITE_NAME, "url": SITE_URL, "rainfall": SITE_RAIN,
                           "fetched_at": iso(fetched), "ok": snap.get("ok"), "last_ok_at": iso(last_ok),
                           "error": snap.get("error"), "stale": stale, "disclaimer": snap.get("disclaimer"),
                           "permits": len(set(rows) | set(obs))}
    outs_by = defaultdict(list)
    for o in site.get("outfalls") or []:
        outs_by[o["permit"]].append(o)
    rule_applied = {"rule": RULE, "threshold_in": None, "threshold_basis": "site_flag", "tail_hours": tail,
                    "trigger_basis": "operator", "rationale": cfg["doc"], "source": cfg["source"]}
    for permit in sorted(set(rows) | set(obs)):
        row = rows.get(permit) or {}
        outs = [o for o in outs_by.get(permit, []) if o.get("water_slug")]
        keys, tags, reach_of, aside = targets(permit, waters, [], outs, reaches, reach_waters_fn)
        t0, vals = site_series(obs.get(permit) or [], now)
        eps = runs(vals, t0, 0.5, now, tail, float(cfg["rainfall_stale_hours"])) if t0 else []
        blocks = [(st, st + supp) for st, _ in starts.get(permit, []) if st <= now]
        pt = next(([o["lat"], o["lon"]] for o in outs_by.get(permit, []) if o.get("lat") is not None), None)
        short_in = (row.get("short_window") or {}).get("total_in")
        long_in = (row.get("long_window") or {}).get("total_in")
        now_windows = [w for w, k in (("1-hour", "short_window"), ("4-hour", "long_window"))
                       if (row.get(k) or {}).get("exceeded")]
        name = row.get("name")
        prow = {"name": name, "discharger_id": row.get("discharger_id"), "state": "NJ", "threshold_in": None,
                "threshold_basis": "site_flag", "threshold_rule": "rain_likely.site_flag", "threshold_kind": "shared_site",
                "trigger_basis": "operator", "label": label_for("operator", cfg),
                "threshold_text": f"the permittee's own 1-hour or 4-hour rainfall threshold on {SITE_NAME}",
                "n_discharge_days": None, "history_since": None, "history_until": None,
                "rain_24h_in": None, "rain_1h_in": short_in, "rain_4h_in": long_in, "site_alert": row.get("alert_label"),
                # the site's own times are labels with no year: kept as labels; our fetch time apart (SOL P1-4)
                "valid_time": None, "observed_label": row.get("latest_observation_label"),
                "site_updated_label": snap.get("source_last_updated_label"), "site_fetched_at": iso(fetched),
                "flag_windows": now_windows, "point": pt, "qpf_24h_in": None, "rain_expected": False,
                "status": "no_reading" if row.get("exceeded") is None or stale else "below", "episode": None,
                "suppressed_by": [], "waters": sorted(tags), "reaches": keys, "source_id": SITE_SOURCE_ID,
                "source_url": SITE_URL, **({"set_aside": aside} if aside else {})}
        for ep in eps:
            eid = f"rain_likely:{permit}:{ep['start'].strftime('%Y%m%dT%H')}Z"
            pieces = [(a, b) for a, b in subtract(ep["start"], ep["end"], blocks) if (b is None or b > h_start) and a <= now]
            by_notice = sorted({e for st, e in starts.get(permit, []) if st <= now
                                and st + supp > ep["start"] and (ep["end"] is None or st < ep["end"])})
            in_now = ep["start"] <= now and (ep["end"] is None or ep["end"] > now)
            active = any(a <= now and (b is None or b > now) for a, b in pieces)
            if in_now:
                prow["episode"] = eid
                prow["status"] = "likely" if active else "suppressed"
                prow["suppressed_by"] = [] if active else by_notice
            if not pieces and not in_now:
                continue
            seen = [o for o in obs.get(permit) or [] if o and o[1]
                    and ep["start"] <= _hour(parse_t(o[0])) <= ep["last_above"]]
            wins = sorted({w for o in seen for w, i in (("1-hour", 4), ("4-hour", 5)) if len(o) > i and o[i]})
            peak1 = max((o[2] for o in seen if len(o) > 2 and o[2] is not None), default=None)
            peak4 = max((o[3] for o in seen if len(o) > 3 and o[3] is not None), default=None)
            labels = [o[6] for o in seen if len(o) > 6 and o[6]]
            rain_rec = {
                "permit": permit, "discharger_name": name, "discharger_id": row.get("discharger_id"), "state": "NJ",
                "basis": "site_flag", "site": SITE_NAME, "site_url": SITE_URL, "site_alert": row.get("alert_label"),
                # the citation is the shared site: which window it flagged and its own observation labels
                "citation": {"name": SITE_NAME, "url": SITE_URL, "rainfall": SITE_RAIN,
                             "statement": snap.get("disclaimer")},
                "flag_windows": wins, "observed_labels": [labels[0], labels[-1]] if labels else [],
                "site_fetched_at": [o[0] for o in seen][-1] if seen else None,
                "threshold_in": None, "threshold_basis": "site_flag", "threshold_rule": "rain_likely.site_flag",
                "threshold_kind": "shared_site", "trigger_basis": "operator", "label": prow["label"],
                "threshold_text": prow["threshold_text"], "n_discharge_days": None,
                "rain_1h_in": peak1, "rain_4h_in": peak4, "peak_24h_in": None, "peak_at": iso(ep["peak_at"]),
                "above_from": iso(ep["start"]), "last_above_at": iso(ep["last_above"]),
                "dropped_below_at": iso(ep.get("dropped_at")), "until": iso(ep["end"]),
                "until_rule": f"{tail:g} hours after the site's rainfall flag clears",
                "rain_24h_in": None, "valid_time": None, "point": pt, "qpf_24h_in": None,
                "rainfall_source": SITE_RAIN, "rainfall_source_id": SITE_SOURCE_ID,
                "rainfall_stale": bool(ep.get("rainfall_stale")) or stale, "suppressed_by": by_notice}
            block["episodes"][eid] = {"permit": permit, "discharger_name": name, "discharger_id": row.get("discharger_id"),
                                      "state": "NJ", "trigger_basis": "operator", "label": rain_rec["label"],
                                      "start": iso(ep["start"]), "end": iso(ep["end"]), "active": active,
                                      "in_effect": in_now, "pieces": [[iso(a), iso(b)] for a, b in pieces],
                                      "waters": sorted(tags), "reaches": keys, "rain": rain_rec}
            _emit(pieces, eid, ep, permit, rain_rec, rule_applied, cfg, tail, keys, tags, reach_of, by_water, by_reach,
                  SITE_SOURCE_ID, "New Jersey CSO permittees' shared notification site")
        block["permits"][permit] = prow
        for slug in tags:
            w = block["waters"].setdefault(slug, {"permits": [], "rain_24h_in": None, "qpf_24h_in": None,
                                                  "rain_expected": False, "likely": False, "sources": []})
            if SITE_SOURCE_ID not in w["sources"]:
                w["sources"].append(SITE_SOURCE_ID)
            w["permits"].append(permit)
            w["likely"] = w["likely"] or prow["status"] == "likely"


def caution_coverage(block: dict, cso_states=()) -> dict[str, dict]:
    """Per state, whether the "discharge likely" caution is computed there and how (out/coverage.json
    rain_caution_states): {covered, methods ("radar", "site_flag"), permits, cso_permits, waters, sources,
    sentence}. cso_states: the states with open combined sewer outfalls in the registries, or {state: their
    permits}; a state there with no permittee here is covered: false, and cso_permits counts its operators."""
    cso = cso_states if isinstance(cso_states, dict) else {st: set() for st in cso_states or ()}
    out: dict[str, dict] = {}
    on = bool(block and block.get("enabled"))
    radar_read = ((block or {}).get("rainfall") or {}).get("read")
    amounts: dict[str, set] = defaultdict(set)
    at_plant: dict[str, int] = defaultdict(int)       # operators whose rainfall is read at the treatment plant
    for permit, p in ((block or {}).get("permits") or {}).items():
        st = (p.get("state") or permit[:2]).upper()
        method = "site_flag" if p.get("threshold_basis") == "site_flag" else "radar"
        e = out.setdefault(st, {"covered": on, "methods": [], "permits": 0, "waters": set(), "sources": []})
        e["permits"] += 1
        e["waters"].update(p.get("waters") or [])
        b = basis_of(p)
        if b not in e.setdefault("trigger_bases", []):
            e["trigger_bases"].append(b)
        if method not in e["methods"]:
            e["methods"].append(method)
        src = SITE_SOURCE_ID if method == "site_flag" else SOURCE_ID
        if src not in e["sources"]:
            e["sources"].append(src)
        if method == "radar":                # (amount, whose): a state's published trigger or this site's default
            amounts[st].add((p.get("threshold_in"), "site_default" if p.get("trigger_basis") == "default"
                             else p.get("threshold_kind") or "state")
                            if p.get("threshold_basis") == "published" else None)
            how = p.get("rainfall_read") or radar_read
            if how == "plant_point":
                at_plant[st] += 1
            if how and how not in e.setdefault("rainfall_read", []):
                e["rainfall_read"].append(how)
    for st in cso:
        out.setdefault(str(st).upper(), {"covered": False, "methods": [], "permits": 0, "waters": set(), "sources": []})
    covered_permits = {permit for permit in ((block or {}).get("permits") or {})}
    names = {"radar": "NOAA radar rainfall at their outfalls, against each operator's own threshold (or a published "
                      "one)", "site_flag": f"the rainfall flags of {SITE_NAME}"}
    for st, e in out.items():
        e["waters"] = len(e["waters"])
        e["trigger_bases"] = sorted(e.get("trigger_bases") or [], key=TRIGGER_BASES.index)
        if "radar" in e["methods"]:
            reads = sorted(e.get("rainfall_read") or [])
            e["rainfall_read"] = reads
            at_outfalls = [r for r in reads if r != "plant_point"] or reads
            e["method"] = "NOAA MRMS radar rainfall: " + (READ_TEXT.get(at_outfalls[0], at_outfalls[0])
                                                           if len(at_outfalls) == 1 else "read hourly at each outfall")
            a = amounts.get(st) or set()
            if len(a) == 1 and None not in a:
                e["threshold_in"], e["threshold_kind"] = next(iter(a))
        listed = set(cso.get(st) or ())
        e["cso_permits"] = len(listed | {p for p in covered_permits if p[:2] == st}) if listed else None
        missing = len(listed - covered_permits) if listed else 0
        if e["covered"] and e["permits"]:
            parts = dict(names)
            if e.get("threshold_in") is not None:
                whose = ("this site's default amount" if e.get("threshold_kind") == "site_default"
                         else "the published amount")
                parts["radar"] = f"NOAA radar rainfall at their outfalls, against {whose} of {e['threshold_in']:g} in"
            how = " and ".join(parts[m] for m in e["methods"])
            of = f" of the {e['cso_permits']}" if missing else ""
            bases = set(e["trigger_bases"])
            word = ('"discharge possible"' if bases == {"default"} else '"discharge likely" or "discharge possible"'
                    if "default" in bases else '"discharge likely"')
            e["sentence"] = (f"The {word} caution covers {e['permits']}{of} combined sewer operator"
                             f"{'' if e['permits'] == 1 and not missing else 's'} here, from {how}.")
            if at_plant.get(st):
                n = at_plant[st]
                e["sentence"] += (f" For {n} of them, rainfall is read at the treatment plant; the outfalls' own "
                                  f"locations are not published." if n > 1 else " For one of them, rainfall is read "
                                  "at the treatment plant; the outfalls' own locations are not published.")
            if missing:
                e["sentence"] += (f" For the other {missing}, heavy rain with no report shows nothing.")
        else:
            e["covered"] = False
            e["sentence"] = ("No \"discharge likely\" caution here yet: the site does not read rainfall at this "
                             "state's combined sewer outfalls, so heavy rain with no report shows nothing.")
    return dict(sorted(out.items()))


def site_health_file(rain: dict) -> dict | None:
    """The New Jersey site's snapshot header in the shape build.status.source_health reads."""
    snap = ((rain or {}).get("site_flags") or {}).get("snapshot") or {}
    if not snap:
        return None
    return {"source_id": SITE_SOURCE_ID, "ok": snap.get("ok"), "error": snap.get("error"),
            "fetched_at": snap.get("fetched_at"), "last_ok_at": snap.get("last_ok_at"), "fixture": False,
            "records": snap.get("count")}


def water_context(block: dict, slug: str) -> dict | None:
    """What a water page says about rain: the permittees discharging here, the radar total, the
    threshold, the forecast ("rain expected" when the next 24 hours' forecast reaches the threshold)."""
    w = (block.get("waters") or {}).get(slug)
    if not w:
        return None
    perms = [{"permit": p, **{k: (block["permits"].get(p) or {}).get(k) for k in
                              ("name", "threshold_in", "threshold_basis", "threshold_rule", "threshold_kind",
                               "trigger_basis", "rain_24h_in", "valid_time", "qpf_24h_in", "qpf_update_time",
                               "rain_expected", "status", "episode")}}
             for p in w["permits"]]
    return {"rain_24h_in": w["rain_24h_in"], "qpf_24h_in": w["qpf_24h_in"], "rain_expected": w["rain_expected"],
            "likely": w["likely"], "trigger_basis": w.get("trigger_basis"), "trigger_bases": w.get("trigger_bases") or [],
            "label": w.get("label") or label_for(w.get("trigger_basis")), "valid_time": (block.get("rainfall") or {}).get("valid_time"),
            "rainfall_source": RAINFALL_SOURCE, "forecast_source": "NWS gridpoint forecast (api.weather.gov), next 24 hours",
            "rainfall_stale": (block.get("rainfall") or {}).get("stale"), "permits": perms}


def health_file(rain: dict) -> dict | None:
    """The rainfall file's header in the shape build.status.source_health reads."""
    rf = (rain or {}).get("rainfall") or {}
    if not rf:
        return None
    return {"source_id": SOURCE_ID, "ok": rf.get("ok"), "error": rf.get("error"), "fetched_at": rf.get("fetched_at"),
            "last_ok_at": rf.get("last_ok_at"), "fixture": False, "records": (rf.get("mrms") or {}).get("points")}


def short(iv: dict, where: str = "") -> str:
    r = iv.get("rain") or {}
    label = r.get("label") or iv.get("label") or label_for(r.get("trigger_basis") or iv.get("trigger_basis"))
    who = f" · {r['discharger_name']}" if r.get("discharger_name") else ""
    if r.get("basis") == "site_flag":
        wins = " or ".join(r.get("flag_windows") or []) or "1-hour or 4-hour"
        return f"{label}{who} · {wins} rainfall over the threshold on the permittees' shared notification site{where}"
    peak = r.get("peak_24h_in")
    thr = r.get("threshold_in")
    kind = " (this site's default)" if (r.get("trigger_basis") or iv.get("trigger_basis")) == "default" else ""
    rain = f" · {peak:.2f} in in 24 h (radar), threshold {thr:.2f} in{kind}" if peak is not None and thr is not None else ""
    return f"{label}{who}{rain}{where}"
