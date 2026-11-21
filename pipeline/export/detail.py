"""What a source says about one report beyond the common fields, as named and typed fields, and the later
records of the same event (owner, 2026-11-17: "we would want to share as much detail as we had available
from the source"; site docs/decisions.md item 31).

    detail_of(e)         -> dict   the record's `detail`: only the fields in FIELDS, each read from a source key
                                    named in SOURCES (a key nobody named stays out), personal data scrubbed
    links_of(events)     -> {event_id: {"later_volume": {...}, "linked_records": [...]}}
    cell_detail(detail)  -> dict   the subset the report tables carry (events.json, waters/<slug>.json)
    enrich(events)       -> None   both, written onto each record in place (the export calls it on the public,
                                    redacted records; `python -m export.detail <out>` applies it to an existing
                                    out/ directory, for a check against a real export)

FIELDS (every value is the source's own, never converted; a field the source does not give is left out):
  report_kind           the source's name for this kind of record ("Verified Data Report", "Public Notification
                        Report, Initial-Ceased", NY-Alert "Close", EPA "Sewer Overflow/Bypass Event Report")
  cause                 the cause in the source's words
  weather               the weather in the source's words ("Rain 1-2\" per hour", "Dry")
  rainfall_in           rainfall the source reports, in inches (each mapped field is an inch field), as written
  rainfall_label        what that rainfall figure is, in the source's terms ("Rainfall", "Total rainfall",
                        "Rainfall before the event")
  duration_text         the duration as the source gives it ("0 hours, 20 minutes", "30 Minutes - Ended", "19.00 hours")
  volume_qualifier      how the source says the volume was found, one of QUALIFIERS, set only where the source or
                        the law behind it says so (SOURCES: MassDEP notices estimate by statute, Verified Data
                        Reports are the permittee's verified figure; NEORSD models its volumes)
  volume_method         how the volume was determined, in the source's words ("Best Professional Judgement",
                        "flow meter")
  volume_to_water_gal   gallons the source says reached a water (a number, as the source gives it)
  overflow_point        where the sewage came out, in the source's words ("Manhole", "Gravity Mainline")
  town                  the city or town the source names for the report
  description           the discharge as the source describes it ("Sanitary sewer overflowing into storm sewer")
  location_description  the place as the source describes it ("Manhole is in the street at the intersection of ...");
                        house numbers removed (common.strip_house_numbers)
  rate                  a rate the source states in place of a volume, as a value (export/estimates.py rate_of):
                        {text, unit, low, high, bound?, qualifier?}; the source's own figure, never a volume

Our own figures, apart from the source's (export/estimates.py; site docs/decisions.md items 47 and 48), are written
beside `detail`, never inside it: `volume_estimate` (rate x duration, both from the record) and `end_estimate` (the
record's start plus the duration it states, where it gives no end), each with its basis and inputs. A stated total
wins: a record whose later record of the same event gives a volume (`later_volume`) gets no computed volume.

The later record of the same event (links_of): records are one event only where the pipeline's own rules linked
them (parent_event_id within one source: MassDEP's Ceased updates and Verified Data Reports to their notice,
NY-Alert's notices of one chain; Georgia EPD's row to the EPA eRule report it was paired with, raw._epa_record; a
row of Houston's monthly SSO table to TCEQ's record of the same overflow, raw._other_source_record).
Nothing here pairs records itself. `later_volume` on a discharge record: the volume of the latest record of its
family published after it, with that record's qualifier and publication time, when it differs from the record's
own figure or qualifier. `linked_records`: its parent, its direct children and the other source's record, each with
the relation and the record's report_kind.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import (HOUSE_NUMBER_REMOVED, NAME_KEYS, PERSONAL_KEYS, VOLUME_RATE, _BEFORE_STREET_WORD,  # noqa: E402
                    drop_house_numbers, scrub_names, scrub_residence_numbers, scrub_text, strip_house_numbers)
from export import estimates as estimates_mod  # noqa: E402

FIELDS = ("report_kind", "cause", "weather", "rainfall_in", "rainfall_label", "duration_text", "volume_qualifier",
          "volume_method", "volume_to_water_gal", "overflow_point", "town", "description", "location_description", "rate")
NUMBER_FIELDS = {"volume_to_water_gal"}
QUALIFIERS = ("estimated", "measured", "modeled", "verified by the operator")
# a field whose value is a place description: its house numbers are removed as well as the usual scrub
ADDRESS_FIELDS = {"location_description", "description", "overflow_point"}
# fields whose value is an object the reader builds and checks itself (not a source string)
OBJECT_FIELDS = {"rate"}
# the fields the report tables carry (slim rows): the cell's cause, description and duration, the qualifier of its
# volume, and a rate given in place of a volume
CELL_FIELDS = ("cause", "description", "duration_text", "volume_qualifier", "rate")
DISCHARGE_TYPES = {"cso", "sso", "bypass", "blended", "plant_bypass", "unknown"}
MAX_TEXT = 300          # a field longer than this is cut at a word with "…" (the record's raw keeps the whole text)
MAX_LINKED = 12
# values that say the source gave nothing
EMPTY = re.compile(r"^(?:|n/?a|none|null|-+|unknown/not reported|not reported|not applicable)$", re.I)
PLAIN_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")


def _get(raw: dict, path: str):
    """raw at a dotted path ("row.cause"); a list on the way joins its members' values ("sewage[].causes")."""
    cur = [raw]
    for part in path.split("."):
        many = part.endswith("[]")
        key = part[:-2] if many else part
        nxt = []
        for c in cur:
            v = c.get(key) if isinstance(c, dict) else None
            if many and isinstance(v, list):
                nxt.extend(v)
            elif v is not None:
                nxt.append(v)
        cur = nxt
    flat = []
    for v in cur:
        flat.extend(v if isinstance(v, list) else [v])
    return flat


def text(*paths: str, join: str = "; "):
    """The first path that gives a value: its strings joined (each once, in order), else None."""
    def read(raw: dict):
        for p in paths:
            vals = []
            for v in _get(raw, p):
                if isinstance(v, dict):         # a coded list's entry ({"code", "desc"}): its description, a string only
                    v = v.get("desc") if isinstance(v.get("desc"), str) else v.get("description")
                if isinstance(v, bool) or not isinstance(v, (str, int, float)):
                    continue                    # a nested container never becomes text (review P1: unnamed fields)
                s = " ".join(str(v).split())
                if s and not EMPTY.match(s) and s not in vals:
                    vals.append(s)
            if vals:
                return join.join(vals)
        return None
    return read


def number(*paths: str):
    def read(raw: dict):
        for p in paths:
            for v in _get(raw, p):
                s = str(v).replace(",", "").strip()
                if PLAIN_NUMBER.match(s):
                    f = float(s)
                    return int(f) if f == int(f) else f
        return None
    return read


def plain_inches(*paths: str):
    """A rainfall field in inches: kept only when it is a plain number of zero or more, as written."""
    def read(raw: dict):
        v = text(*paths)(raw)
        return v if v and re.fullmatch(r"\d*\.?\d+", v) else None
    return read


def with_unit(path: str, unit: str):
    """A bare number from a field whose unit is in its name ("duration_hours"): the number as written and the unit."""
    def read(raw: dict):
        v = text(path)(raw)
        if not v:
            return None
        return f"{v} {unit}" if re.fullmatch(r"\d*\.?\d+", v) else v
    return read


def const(value):
    return lambda raw: value


def _ma_duration(raw: dict):
    h, m = text("hours")(raw), text("minutes")(raw)
    if h is None and m is None:
        return None
    if not all(x is None or re.fullmatch(r"\d+", x) for x in (h, m)):
        return None
    h, m = h or "0", m or "0"
    return f"{h} hour{'' if h == '1' else 's'}, {m} minute{'' if m == '1' else 's'}"


def _ma_kind(raw: dict):
    cls = text("reporterClass", "_report_class")(raw)
    rtype = text("reportingType")(raw)
    return ", ".join(x for x in (cls, rtype) if x) or None


def _ma_qualifier(raw: dict):
    if text("volumnOfEvent")(raw) is None:
        return None
    cls = text("reporterClass", "_report_class")(raw)
    if cls == "Verified Data Report":
        return "verified by the operator"
    if cls == "Public Notification Report":
        return "estimated"          # M.G.L. c. 21 s. 43A(b): a notice estimates from the prior three years' average
    return None


def _md_duration(raw: dict):
    parts = [(text(f"row.duration_{k}")(raw), k) for k in ("day", "hour", "minute")]
    if not any(v for v, _ in parts) or not all(v is None or re.fullmatch(r"\d+", v) for v, _ in parts):
        return None
    return ", ".join(f"{v} {k}{'' if v == '1' else 's'}" for v, k in parts if v is not None)


def _ny_qualifier(raw: dict):
    q = text("row.quantity")(raw) or ""
    return "estimated" if re.search(r"\bestimated\b", q, re.I) else "measured" if re.search(r"\bmeasured\b", q, re.I) else None


def _va_duration(raw: dict):
    hs = [str(s.get("duration_h")) for s in raw.get("sewage") or [] if isinstance(s, dict) and s.get("duration_h") not in (None, "")]
    return "; ".join(f"{h} hours" for h in hs) or None


def _neorsd_qualifier(raw: dict):
    return "modeled" if re.search(r"\bmodell?ed\b", str(raw.get("measurement") or ""), re.I) else None


def _nc_duration(raw: dict):
    v = text("dwr_duration_5d")(raw)
    return f"{v} (hours:minutes)" if v and re.fullmatch(r"\d+:\d{2}", v) else v


CT = {
    "report_kind": text("Report Type"),
    "cause": text("Cause of Bypass", "BYPASS_CAUSE"),
    "weather": text("Weather Conditions", "WEATHER_CONDITION"),
    "rainfall_in": plain_inches("Total Rainfall"), "rainfall_label": lambda raw: "Total rainfall" if plain_inches("Total Rainfall")(raw) else None,
    "volume_method": text("Describe how final volume was determined", "How was estimated quantity or rate determined",
                          "How was estimated Quantity or Rate Determined"),
    "overflow_point": text("Location of Bypass", "BYPASS_LOCATION"),
    "town": text("Municipality", "Muncipality", "CSO Town", "CSO_TOWN", "REPORTING_TOWN"),
}
def _ny_own_number(raw: dict) -> list[tuple[str, str | None]]:
    """The notice's own street number and the first word of its street ([("749", "Colvin")]), from the workbook row
    or the web message's "Discharge location", so a description that repeats the address loses the number
    (common.drop_house_numbers)."""
    row = raw.get("row") if isinstance(raw.get("row"), dict) else {}
    num, street = str(row.get("streetNumber") or "").strip(), str(row.get("streetName") or row.get("sprtkStreetName") or "").strip()
    if not num:
        parsed = raw.get("parsed") if isinstance(raw.get("parsed"), dict) else {}
        m = re.match(r"\s*(\d{1,6}[A-Za-z]?(?:-\d{1,6}[A-Za-z]?)?)\s+((?:[NSEW]\.?\s+)?[\w']+)", str(parsed.get("discharge_location") or ""))
        num, street = (m.group(1), m.group(2)) if m else ("", "")
    if not re.fullmatch(r"\d{1,6}[A-Za-z]?(?:-\d{1,6}[A-Za-z]?)?", num):
        return []
    word = street.split()[0] if street.split() else None
    return [(num, word)] if word else []


def ny_place_text(*paths: str):
    """A NY-Alert description that can repeat the notice's address: the text without the notice's own house number."""
    def read(raw: dict):
        v = text(*paths)(raw)
        return drop_house_numbers(v, _ny_own_number(raw)) if v else None
    return read


def _ny_component(raw: dict, e: dict):
    """Where the sewage came out, as NY-Alert's form gives it: the system component picked from its list (each once,
    "CSO Outfall,CSO Outfall -" read as "CSO Outfall"), and the notifier's component description after it when it is
    not already the record's outlet name."""
    comp = text("row.systemComponent")(raw) or ""
    picked = []
    for x in re.split(r"\s*,\s*", comp.split(" - ", 1)[0].rstrip(" -")):
        if x and x != "-" and x not in picked:
            picked.append(x)
    desc = ny_place_text("row.componentDescription")(raw)
    if desc and _same(desc, e.get("outfall_name")):
        desc = None
    out = " - ".join(x for x in (", ".join(picked), desc) if x)
    return out or None


_ny_component.with_record = True


def _rate(source_id: str):
    """The rate the source states (export/estimates.py rate_of), read from the record's raw as the export holds it."""
    return lambda raw: estimates_mod.rate_of({"source_id": source_id, "raw": raw})


NY = {
    "report_kind": text("row.notificationStatus"), "cause": text("row.dischargeReason"),
    "duration_text": text("row.dischargeDuration"), "volume_qualifier": _ny_qualifier, "town": text("row.city"),
    "overflow_point": _ny_component, "description": ny_place_text("row.dischargeDescription"),
    "location_description": ny_place_text("row.addressDescription"), "rate": _rate("ny-dec-sprtk"),
}
# the NY-Alert web page as ny_sprtk_web reads it (raw.parsed)
NY_WEB = {
    "report_kind": text("parsed.word"), "cause": text("parsed.reason"), "duration_text": text("parsed.duration"),
    "volume_qualifier": lambda raw: _ny_qualifier({"row": {"quantity": text("parsed.volume")(raw)}}),
    "description": ny_place_text("parsed.discharge_description"), "location_description": ny_place_text("parsed.location_details"),
    "rate": _rate("ny-dec-sprtk-web"),
}

# source id -> {field: reader of the record's raw}. A source not listed gets no detail (its raw stays on the page as
# the source data); add a source here with the source key named.
SOURCES: dict[str, dict] = {
    "ma-massdep": {
        "report_kind": _ma_kind, "rainfall_in": plain_inches("rainfallData"),
        "rainfall_label": lambda raw: "Rainfall" if plain_inches("rainfallData")(raw) else None,
        "duration_text": _ma_duration, "volume_qualifier": _ma_qualifier, "town": text("municipality"),
    },
    "mi-egle-mienviro-cso-sso-list": {
        "weather": text("precipitationType"), "rainfall_in": plain_inches("precipitationAmount"),
        "rainfall_label": lambda raw: "Precipitation" if plain_inches("precipitationAmount")(raw) else None,
    },
    "tx-tceq-sso-opendata": {"cause": text("_cause", "cause")},
    # Houston's monthly SSO table (ingest/tx_houston_sso_monthly.py): its columns as written; "Est. Volume (Gallons)"
    # is an estimate, and a "0" is no figure (the City's note, kept as raw.volume_note)
    "tx-houston-sso-monthly": {"report_kind": const("Monthly SSO Report"),
                               "cause": text("cause", "structure_and_cause_as_written"),
                               "overflow_point": text("structure_type"), "town": text("city"),
                               "volume_qualifier": lambda raw: "estimated" if not raw.get("volume_note") else None,
                               "volume_method": text("volume_note")},
    # the notice's own form fields as the ingester reads them from its text (fl_dep_pnp.template_fields: "Cause:")
    "fl-dep-pnp": {"cause": text("_template.cause"), "town": text("FACILITY_CITY")},
    "ct-deep": CT, "ct-deep-annual": CT, "ct-deep-archive": CT,
    "ny-dec-sprtk": NY, "ny-dec-sprtk-web": NY_WEB,
    "md-mde-overflows": {"cause": text("row.overflow_cause"), "duration_text": _md_duration},
    "nc-dwr-sso-2022-2025": {"cause": text("incident_cause"), "volume_to_water_gal": number("volume_reach_water"),
                             "town": text("city")},
    # the five-day report's fields first, then the 24-hour report's (nc_dwr_sso keeps either naming)
    "nc-dwr-sso-2026": {"cause": text("dwr_cause_5d", "dwr_cause", "cause"), "weather": text("dwr_weather_5d", "dwr_weather", "weather"),
                        "duration_text": _nc_duration,
                        "volume_to_water_gal": number("dwr_volume_waterbody_5d", "dwr_volume_waterbody", "volume_waterbody"),
                        "town": text("deq_municipality", "municipality")},
    "echo-sewer-overflow": {
        "report_kind": text("program_report_npdes_data_group_desc"), "cause": text("causes[]"),
        "duration_text": with_unit("sewer_overflow_bypass_duration_hours", "hours"),
        "volume_method": text("discharge_quantification_method_desc"),
        "overflow_point": text("sewer_overflow_structure_type_desc"),
    },
    "va-deq-prep": {"cause": text("sewage[].causes"), "duration_text": _va_duration,
                    "rainfall_in": plain_inches("sewage[].precipitation_in"),
                    "rainfall_label": lambda raw: "Precipitation" if plain_inches("sewage[].precipitation_in")(raw) else None,
                    "overflow_point": text("sewage[].component"), "town": text("report.city")},
    "ga-epd-spills": {"cause": text("row.cause"), "overflow_point": text("row.spill_source"), "town": text("row.city")},
    "wa-ecology-sewage-spills": {"duration_text": with_unit("row.final_event_duration_hours", "hours")},
    "oh-bowling-green-cso-events": {"rainfall_in": plain_inches("row.RAINFALL_BEFORE_EVENT"),
                                    "rainfall_label": lambda raw: "Rainfall before the event" if plain_inches("row.RAINFALL_BEFORE_EVENT")(raw) else None},
    "oh-clyde-cso-notification": {"cause": text("row.cause"), "rainfall_in": plain_inches("row.rain_total_in"),
                                  "rainfall_label": lambda raw: "Total rainfall" if plain_inches("row.rain_total_in")(raw) else None},
    "oh-neorsd-cso-notification-map": {"volume_qualifier": _neorsd_qualifier},
    "va-richmond-cso": {"rainfall_in": plain_inches("rain_in"),
                        "rainfall_label": lambda raw: "Rainfall" if plain_inches("rain_in")(raw) else None,
                        "duration_text": with_unit("overflow_duration_hours", "hours")},
    "nh-permittees": {"duration_text": with_unit("duration_min", "minutes")},
    "ca-swrcb-ciwqs-spills-flatfile": {"report_kind": text("spill_type"), "cause": text("causes"),
                                       "overflow_point": text("appearance_points")},
    "or-deq-oers-spills-2013-2025": {"cause": text("cause")},
    "ca-beachwatch-advisories": {"cause": text("cause")},
    # feeds built after the 2026-11-14 export (fields as their ingesters keep them)
    "ar-deq-overflow-incidents": {"cause": text("cause", "row.cause")},
    "wy-deq-spills": {"cause": text("CauseDescription", "row.CauseDescription")},
    "sc-florence-sso": {"cause": text("cause_text")},
    # Somerville's discharge table (ingest/ma_somerville_cso.py): the cells as written; the page calls its volumes
    # "estimated" ("their estimated discharge duration and volume")
    "ma-somerville-cso-table": {"rainfall_in": plain_inches("row.rainfall_in"),
                                "rainfall_label": lambda raw: "Event rainfall" if plain_inches("row.rainfall_in")(raw) else None,
                                "duration_text": text("row.duration"),
                                "volume_qualifier": lambda raw: "estimated" if text("row.volume_mg")(raw) else None},
}


# a hyphenated house number or a range of them before a street word ("123-45 Example Avenue", "12-14 Sample Road"),
# which common.strip_house_numbers does not take (review 1)
HYPHEN_NUMBER_RE = re.compile(rf"(?<![\w.,/:-])\d{{1,6}}[A-Za-z]?[ ]?-[ ]?\d{{1,6}}[A-Za-z]?(?={_BEFORE_STREET_WORD})")


def _clean(v, address: bool = False):
    """A source string through the same scrub as raw (emails, phones, staff names, a residence's house number), and for
    a place description every street address's house number (common.strip_house_numbers), cut at MAX_TEXT."""
    if not isinstance(v, str):
        return v
    v = scrub_residence_numbers(scrub_names(scrub_text(v)))
    if address:
        v = strip_house_numbers(HYPHEN_NUMBER_RE.sub(HOUSE_NUMBER_REMOVED, v))
    if len(v) > MAX_TEXT:
        cut = v[:MAX_TEXT].rsplit(" ", 1)[0].rstrip(",;:")
        v = f"{cut}…"
    return v


# fields the record's outlet name can already hold (NY-Alert's outlet name is its component or address description):
# left out where they say the same, so the page says it once
SAME_AS_OUTLET = {"location_description", "description"}


def _same(a, b) -> bool:
    """Whether two source strings say the same, ignoring spacing, case and a house number removed from one."""
    norm = lambda v: re.sub(r"[^a-z]+", " ", str(v or "").replace(HOUSE_NUMBER_REMOVED, " ").lower()).strip()   # noqa: E731
    return bool(norm(a)) and norm(a) == norm(b)


def detail_of(e: dict) -> dict:
    """The named detail fields of one record (FIELDS, in that order), empty when its source is not mapped."""
    spec = SOURCES.get(e.get("source_id") or "")
    raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
    if not spec or not raw:
        return {}
    out = {}
    for f in FIELDS:
        fn = spec.get(f)
        if fn is None:
            continue
        try:
            v = fn(raw, e) if getattr(fn, "with_record", False) else fn(raw)
        except Exception:  # noqa: BLE001 - a source's odd value never stops the export; the field is left out
            v = None
        if v is None or v == "":
            continue
        if f in SAME_AS_OUTLET and _same(v, e.get("outfall_name")):
            continue
        if f in NUMBER_FIELDS:
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
                continue
        elif f == "volume_qualifier":
            if v not in QUALIFIERS:
                continue
        elif f in OBJECT_FIELDS:
            v = _rate_checked(v)
            if not v:
                continue
        else:
            v = _clean(str(v), address=f in ADDRESS_FIELDS)
        out[f] = v
    if "rainfall_in" not in out:
        out.pop("rainfall_label", None)
    if out.get("volume_qualifier") and e.get("volume_gal") is None and (not e.get("volume_text") or out.get("rate")):
        out.pop("volume_qualifier")       # a qualifier with no volume says nothing (a rate carries its own)
    assert not any(PERSONAL_KEYS.search(k) or NAME_KEYS.search(k) for k in out), "a detail field name reads as personal"
    return out


RATE_KEYS = ("text", "unit", "low", "high", "bound", "qualifier")


def _rate_checked(v) -> dict | None:
    """A rate object with its known keys only, its text scrubbed, its figures numbers of zero or more."""
    if not isinstance(v, dict) or not isinstance(v.get("text"), str) or not isinstance(v.get("unit"), str):
        return None
    out = {}
    for k in RATE_KEYS:
        x = v.get(k)
        if x is None:
            continue
        if k in ("low", "high"):
            if not isinstance(x, (int, float)) or isinstance(x, bool) or x < 0:
                return None
        elif not isinstance(x, str):
            return None
        out[k] = _clean(x) if k == "text" else x
    return out if ("low" in out or "high" in out) else None


def cell_detail(d: dict | None) -> dict:
    return {k: d[k] for k in CELL_FIELDS if isinstance(d, dict) and d.get(k) not in (None, "")}


# feeds whose records the pipeline links across the two (ny_sprtk_web gives a newer web notice the workbook chain's
# latest record as its parent): one NY-Alert notice chain
LINKED_FEEDS = ({"ny-dec-sprtk", "ny-dec-sprtk-web"},)


def same_feed(a: dict, b: dict) -> bool:
    sa, sb = a.get("source_id"), b.get("source_id")
    return sa == sb or any({sa, sb} == pair for pair in LINKED_FEEDS)


def _t(e: dict) -> float | None:
    """The record's publication (else report) time as an instant, for ordering; None when it has none."""
    from build import status as status_mod        # here: build.status reads the rules at import
    for k in ("published_at", "reported_at"):
        t = status_mod.parse_time(e.get(k)) if e.get(k) else None
        if t:
            return t.timestamp()
    return None


def _kind(e: dict) -> str | None:
    return (e.get("detail") or {}).get("report_kind") or detail_of(e).get("report_kind")


def _qualifier(e: dict) -> str | None:
    q = (e.get("detail") or {}).get("volume_qualifier") or detail_of(e).get("volume_qualifier")
    if q:
        return q
    return {"estimated": "estimated", "measured": "measured"}.get(e.get("estimate_flag") or "")


def _families(by_id: dict[str, dict]):
    """(children, family_of): each record's direct children within one feed, and the records joined to it by parent
    links within one feed (union-find), or None for a record in no family."""
    children = defaultdict(list)
    for e in by_id.values():
        p = e.get("parent_event_id")
        if p and p != e["event_id"] and p in by_id and same_feed(by_id[p], e):
            children[p].append(e)
    root = {}

    def find(x):
        while root.get(x, x) != x:
            root[x] = root.get(root[x], root[x])
            x = root[x]
        return x
    for p, cs in children.items():
        for c in cs:
            a, b = find(p), find(c["event_id"])
            if a != b:
                root[b] = a
    family = defaultdict(list)
    for eid in by_id:
        if eid in root or eid in children:
            family[find(eid)].append(by_id[eid])
    return children, (lambda eid: family.get(find(eid)) if (eid in root or eid in children) else None)


def states_total(e: dict) -> bool:
    """Whether a record states a total volume: a figure (volume_gal), or words with a figure that are not a rate
    ("more than 830,010 Gallons Estimated", "between 10,000 and 20,000 Gallons")."""
    if isinstance(e.get("volume_gal"), (int, float)) and not isinstance(e.get("volume_gal"), bool):
        return True
    vt = e.get("volume_text")
    return (isinstance(vt, str) and bool(re.search(r"\d", vt)) and not VOLUME_RATE.search(vt.lower())
            and not (isinstance(e.get("raw"), dict) and estimates_mod.rate_of(e)))


def later_totals(events: list[dict], duplicates: set[str] | frozenset = frozenset()) -> set[str]:
    """event ids of the records a later record of the same event (linked as links_of links them) gives a total for, as
    a figure or in words: our computed volume yields to it (a stated total wins; review 6). A record carrying
    `_states_total` (the applier's light copies) is read from that flag."""
    by_id = {e["event_id"]: e for e in events if e.get("event_id")}
    dup = lambda x: bool(x.get("duplicate_of")) or x["event_id"] in duplicates   # noqa: E731
    _children, family_of = _families(by_id)
    out = set()
    for eid, e in by_id.items():
        fam = family_of(eid)
        mine = _t(e) if fam else None
        if not fam or mine is None:
            continue
        for x in fam:
            if x is e or dup(x):
                continue
            tx = _t(x)
            total = x["_states_total"] if "_states_total" in x else states_total(x)
            if tx is not None and tx > mine and total:
                out.add(eid)
                break
    return out


def links_of(events: list[dict], duplicates: set[str] | frozenset = frozenset()) -> dict[str, dict]:
    """{event_id: {"later_volume": ..., "linked_records": [...]}} for every record with a link (see the docstring).
    duplicates: records the status build marks duplicate_of (its placements), which neither give nor take a later
    volume, besides the records' own duplicate_of."""
    by_id = {e["event_id"]: e for e in events if e.get("event_id")}
    dup = lambda x: bool(x.get("duplicate_of")) or x["event_id"] in duplicates   # noqa: E731
    times = {eid: _t(e) for eid, e in by_id.items()}
    # families: the records joined by parent links within one source (union-find)
    children, family_of = _families(by_id)
    # another source's record of the same event, as the pipeline paired them (Georgia EPD and EPA's eRule report)
    other = defaultdict(set)
    for e in by_id.values():
        raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
        x = raw.get("_epa_record") or raw.get("_other_source_record")
        for y in ([x] if isinstance(x, str) else x if isinstance(x, list) else []):   # one EPA report, or several
            if isinstance(y, str) and y in by_id and y != e["event_id"]:
                other[e["event_id"]].add(y)
                other[y].add(e["event_id"])

    def ref(x: dict, relation: str) -> dict:
        # no figure here: a figure without its words and qualifier would read as unqualified (review P1); the
        # later figure of the same event is later_volume, with its qualifier
        r = {"event_id": x["event_id"], "relation": relation, "source_id": x.get("source_id"),
             "report_kind": _kind(x), "published_at": x.get("published_at")}
        return {k: v for k, v in r.items() if v is not None}

    out: dict[str, dict] = {}
    for eid, e in by_id.items():
        linked = []
        p = e.get("parent_event_id")
        if p in by_id and same_feed(by_id[p], e) and p != eid:
            linked.append(ref(by_id[p], "earlier"))
        for c in sorted(children.get(eid, []), key=lambda c: (times[c["event_id"]] is None, times[c["event_id"]] or 0)):
            linked.append(ref(c, "later"))
        for o in sorted(other.get(eid, ())):
            linked.append(ref(by_id[o], "other_source"))
        add = {}
        if linked:
            add["linked_records"] = linked[:MAX_LINKED]
        fam = family_of(eid)
        if fam and e.get("event_type") in DISCHARGE_TYPES and not dup(e):
            mine = times[eid]
            later = [x for x in fam if x is not e and isinstance(x.get("volume_gal"), (int, float)) and not dup(x)
                     and mine is not None and times[x["event_id"]] is not None and times[x["event_id"]] > mine]
            if later:
                x = max(later, key=lambda x: times[x["event_id"]])
                q = _qualifier(x)
                if not (x["volume_gal"] == e.get("volume_gal") and q == _qualifier(e)):
                    add["later_volume"] = {k: v for k, v in {
                        "event_id": x["event_id"], "volume_gal": x["volume_gal"], "volume_text": x.get("volume_text"),
                        "volume_qualifier": q, "report_kind": _kind(x), "published_at": x.get("published_at"),
                    }.items() if v is not None}
        if add:
            out[eid] = add
    return out


ESTIMATE_KEYS = ("volume_estimate", "end_estimate", "ended_at_ours")


def estimates(e: dict, later_total: bool) -> dict:
    """Our figures for one record (export/estimates.py), without a computed volume where a later record of the same
    event states a total (a stated total wins: later_totals)."""
    out = estimates_mod.estimates_of(e)
    if later_total:
        out.pop("volume_estimate", None)
    return out


def estimate_cell(v: dict | None) -> dict | None:
    """The report tables' copy of one of our figures: the figure and its basis (the record's own file has the inputs)."""
    if not isinstance(v, dict):
        return None
    out = {k: v[k] for k in ("gallons", "low", "high", "bound", "at", "precision", "basis", "basis_short") if v.get(k) is not None}
    return out or None


def enrich(events: list[dict], duplicates: set[str] | frozenset = frozenset()) -> None:
    """Writes `detail` (only when the source gives a mapped field), `later_volume`, `linked_records`, and our own
    `volume_estimate` and `end_estimate` (export/estimates.py) onto each record in place. duplicates: as links_of."""
    for e in events:
        d = detail_of(e)
        if d:
            e["detail"] = d
        else:
            e.pop("detail", None)
    links = links_of(events, duplicates)
    later = later_totals(events, duplicates)
    for e in events:
        e.pop("later_volume", None)
        e.pop("linked_records", None)
        e.update(links.get(e["event_id"], {}))
        for k in ESTIMATE_KEYS:
            e.pop(k, None)
        e.update(estimates(e, e["event_id"] in later or bool(e.get("later_volume"))))


LIGHT = ("event_id", "source_id", "event_type", "parent_event_id", "volume_gal", "volume_text", "estimate_flag",
         "published_at", "reported_at", "duplicate_of", "started_at", "ended_at", "time_precision", "fetched_at")


def _main(out_dir: str) -> None:
    """Adds the fields to an existing export (out/events/*.json, events.json, waters/*.json), for a check of the
    site against a real export before the next refresh writes them itself. Reads each record twice rather than
    holding the whole export in memory. The CSV downloads are not rewritten here: the full export (build.py) writes
    them from the same records."""
    out = Path(out_dir)
    files = sorted((out / "events").glob("*.json"))
    light = []
    for p in files:
        e = json.loads(p.read_text())
        x = {k: e.get(k) for k in LIGHT}
        d = detail_of(e)
        if d:
            x["detail"] = d
        raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
        keep = {k: raw[k] for k in ("_epa_record", "_other_source_record") if raw.get(k)}
        if keep:
            x["raw"] = keep
        ours = estimates_mod.estimates_of(e)
        if ours:
            x["_ours"] = ours
        x["_states_total"] = states_total(e)
        light.append(x)
    links = links_of(light)
    later = later_totals(light)
    add = {}
    for x in light:
        lk = links.get(x["event_id"], {})
        ours = dict(x.get("_ours") or {})
        if lk.get("later_volume") or x["event_id"] in later:
            ours.pop("volume_estimate", None)          # a stated total wins
        add[x["event_id"]] = {**({"detail": x["detail"]} if x.get("detail") else {}), **lk, **ours}
    for p, x in zip(files, light):
        a = add[x["event_id"]]
        e = json.loads(p.read_text())
        removed = [k for k in ("detail", "later_volume", "linked_records", *ESTIMATE_KEYS) if e.pop(k, None) is not None]
        if a or removed:                               # a field gone since the last run is removed from the file too
            e.update(a)
            p.write_text(json.dumps(e, separators=(",", ":"), ensure_ascii=False))

    def slim(r: dict) -> None:
        a = add.get(r.get("event_id")) or {}
        for k in ("detail", "later_volume", *ESTIMATE_KEYS):
            r.pop(k, None)
        c = cell_detail(a.get("detail"))
        if c:
            r["detail"] = c
        if a.get("later_volume"):
            r["later_volume"] = a["later_volume"]
        for k in ESTIMATE_KEYS:
            c = estimate_cell(a.get(k))
            if c:
                r[k] = c
    slim_path = out / "events.json"
    doc = json.loads(slim_path.read_text())
    for r in doc.get("events") or []:
        slim(r)
    slim_path.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
    flags = {x["event_id"]: x.get("estimate_flag") for x in light}
    for wp in sorted((out / "waters").glob("*.json")):
        w = json.loads(wp.read_text())
        for r in w.get("events") or []:
            slim(r)
            if flags.get(r.get("event_id")):
                r["estimate_flag"] = flags[r["event_id"]]
        wp.write_text(json.dumps(w, separators=(",", ":"), ensure_ascii=False))
    print(f"detail: {sum(1 for x in light if x.get('detail'))} records with detail, "
          f"{sum(1 for a in add.values() if a.get('later_volume'))} with a later volume, "
          f"{sum(1 for a in add.values() if a.get('volume_estimate'))} with our computed volume, "
          f"{sum(1 for a in add.values() if a.get('end_estimate'))} with our estimated end, of {len(light)}")


if __name__ == "__main__":
    _main(sys.argv[1])
