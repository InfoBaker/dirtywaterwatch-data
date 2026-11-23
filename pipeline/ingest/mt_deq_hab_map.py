"""Montana DEQ harmful algal bloom map -> algal-bloom advisories (source id mt-deq-hab-map).

Source
  The public layer behind DEQ's Harmful Algal Bloom Dashboard (portal item 10c34f5c7da24c4188b9ddc220d43970, web map
  779d34abdc404ae3a63a33cfd94ddc2f, layers "Algal Bloom Observations" and "Previous Years' Advisories"):
  https://gis.mtdeq.us/hosting/rest/services/Hosted/Harmful_Algal_Bloom_Survey_(Public_Web_Map)/FeatureServer/0
  A Survey123 layer of bloom reports (public and agency) with DEQ's advisory fields: advisory_lvl (Caution, Closure,
  "NA" = No Current Advisory, Green Algae/Other), advisory_issued and advisory_lifted (free text holding dates and
  DEQ's notes), sample_date, microcystin and anatoxin results, date_observed, the county and a point. The item's terms,
  quoted in raw.licence: "Data intended for reference and planning purposes only ... Data collected and/or created by
  members of the public as a public source dataset. DEQ cannot verify accuracy or contents of publicly editable data."
  On 2026-11-16 (03:19Z): 445 rows (2019 to 2026, 77 in 2026); 316 carry an issued advisory date (DEQ's 2023 year-first
  dates read), giving 314 advisories, 294 with DEQ's lift date; no row was at Caution or Closure (the season's
  advisories had all been lifted or lapsed).

Safe fields (requested by name; nothing else is read or saved): globalid, name, county, agency, sample_date,
  advisory_lvl, advisory_issued, advisory_lifted, date_observed, microcystin, anatoxin, cyano_density, public_accessible and the point
  (0.001 degree, WGS84). Never requested: desc_bloom (the reporter's description), pic_url, the illness questions and
  the survey's other answers. The advisory_issued and advisory_lifted texts can name people ("reported by ..."): only
  the dates read from them and the words caution, closure and toxin are kept; the text itself is never stored or saved.
  sample_date, microcystin and anatoxin are free text too: they are kept to their dates, numbers and the result
  vocabulary (safe_result: any other word withheld, decimals of a typed point rounded) on every save path.

cyano_density is retained as a typed sample_results item: analyte, text, value, units, qualifier and sample date,
  with its field/layer citation. The 2026-11-22 read gives qualitative text, no numeric cell counts with units;
  value and units remain null. A partial or multiple sample date stays in sample_date_text without an invented date.

Record rules
  - A row is a record when advisory_issued gives a date and does not say no advisory was issued, and DEQ's level is not
    "Green Algae/Other" (not a cyanobacteria bloom). event_type hab_advisory. started_at the earliest date in
    advisory_issued (DEQ's issue date, day precision, Mountain time); a date written without its year takes the year of
    date_observed, read in Mountain time.
  - advisory_lifted with an affirmative, completed lift date on or after the start: status advisory_lifted, ended_at
    that date (raw.ended_at_precision day; DEQ's own lift date). A negated or conditional note ("not yet lifted 8/3",
    "lift pending") is no lift, and a date the note labels as a sampling, test or report is not the lift date
    (lift_dates). advisory_lvl Caution or Closure at the read: advisory_active, confirmed at that read
    (raw._last_seen_in_source). Otherwise (no lift date, the layer at "No Current Advisory"): advisory_active with no
    end and no confirmation, so the status build's 14-day rule ages it from its issue date; raw.end_basis says so.
  - A row whose public_accessible answer is "No" (a private pond) keeps its county and no point.
  - Episodes are immutable: a row whose issue date or water is replaced at a later read gives a new record under its
    own id, and the earlier record is kept as it was. An earlier record a read does not reproduce (the row gone, its
    advisory fields unreadable) is kept, never ended; a read with fewer rows than the last good read, or missing or
    unreadable rows that made records, is incomplete: readable rows are updated, health is false, the exit non-zero.
  - Every save is sanitized: the raw save is an allowlist of fields (SAVED_ATTRS) with a private water's point removed
    and points rounded; records carried from earlier state and the failure path are sanitized again (sanitized()).
  - Placed by its point (an observation point at the water), else by the water's name in its county; the location the
    name adds ("Canyon Ferry - Duck Creek Camp") is kept in raw.place.

Run from pipeline/:  python -m ingest.mt_deq_hab_map [--file saved.json]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, scrub_text, write_events
from common import error_detail, error_text
from ingest.mountain_scrub import scrub

SOURCE_ID = "mt-deq-hab-map"
LAYER = ("https://gis.mtdeq.us/hosting/rest/services/Hosted/Harmful_Algal_Bloom_Survey_(Public_Web_Map)/FeatureServer/0")
DASHBOARD = "https://gis.mtdeq.us/portal/apps/dashboards/10c34f5c7da24c4188b9ddc220d43970"
FIELDS = ("globalid,name,county,agency,sample_date,advisory_lvl,advisory_issued,advisory_lifted,date_observed,"
          "microcystin,anatoxin,cyano_density,public_accessible")
AUTHORITY = "Montana Department of Environmental Quality (harmful algal bloom map)"
TZ = "America/Denver"
LICENCE = ("Data intended for reference and planning purposes only. DEQ takes no responsibility for misuse of data "
           "outside suggested use parameters. Data collected and/or created by members of the public as a public source "
           "dataset. DEQ cannot verify accuracy or contents of publicly editable data.")
DATE = re.compile(r"(?<![\d/.])(\d{1,2})[/.](\d{1,2})(?:[/.](\d{4}|\d{2}))?(?![\d/])")
# DEQ wrote its 2023 notes year first ("2023/07/06", "2023-07-05") and once month-day-year with dashes ("09-06-2023"):
# only these forms, with a four-digit year that fixes the order, are rewritten M/D/YYYY before DATE reads them; any
# other form ("20203/07/17") is left unread, never guessed (go-live audit 2026-11-16, fix 1a)
YEAR_FIRST = re.compile(r"(?<![\d/.-])(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?![\d/.-])")
DASHED = re.compile(r"(?<![\d/.-])(\d{1,2})-(\d{1,2})-(\d{4})(?![\d/.-])")
# a date at the opening of the lift note labelled at once as a sampling or test ("7/28 sampled", "8/10 test results
# pending") is that step's date, never the lift
STEP_LABEL = re.compile(r"[\s:,.-]*(?:sampl|test|result|collect)", re.I)


def normal_dates(text: str | None) -> str:
    """DEQ's year-first and dashed dates rewritten in its usual M/D/YYYY form; everything else unchanged."""
    t = YEAR_FIRST.sub(lambda m: f"{int(m.group(2))}/{int(m.group(3))}/{m.group(1)}", str(text or ""))
    return DASHED.sub(lambda m: f"{int(m.group(1))}/{int(m.group(2))}/{m.group(3)}", t)


NO_ADVISORY = re.compile(r"\bno advisory\b|\bnot issued\b", re.I)
WORDS = ("caution", "closure", "toxin")
# a lift note that is not a completed lift ("lift pending 8/3", "will lift 8/3 if no new info", "not lifted 8/3",
# "not yet lifted 8/3/2026", "to be lifted when", "remains in effect until lifted"): only an affirmative, completed lift
# ends an advisory (lessons, item 1; Astra review 2026-11-15 P1)
NOT_A_LIFT = re.compile(r"\b(?:not|never|no|pending|will|would|to be|expected to|planned to|may|might|can|could|should|"
                        r"yet to|until|unless|awaiting|await)\b(?:\s+\w+){0,2}?\s+(?:be\s+)?lift|"
                        r"\blift(?:ed|ing)?\s+(?:is\s+)?(?:not|pending|when|if|once|until|unless|after)\b|"
                        r"\bnot\s+yet\b|\bstill\s+(?:in\s+effect|active|in\s+place|posted)\b|"
                        # a planned, scheduled or expected lift is not a lift ("lift planned for 8/3/2026", "tentative")
                        r"\b(?:plann\w*|schedul\w*|anticipat\w*|expect\w*|propos\w*|tentativ\w*|estimat\w*|"
                        r"target\w*|projected|intend\w*)\b", re.I)
LIFT_WORD = re.compile(r"\blift(?:ed)?\b|\brescinded\b|\bremoved\b", re.I)
# a date labelled as something else in the lift note ("sampled 7/28, lifted 8/3"): not the lift date
OTHER_DATE_WORD = re.compile(r"\b(?:sampl\w*|test\w*|result\w*|collect\w*|observ\w*|issued|report\w*|photo\w*|"
                             r"visit\w*|check\w*|inspect\w*)", re.I)
NOT_A_LIFT_MARK = "not-a-lift"      # kept in the raw save so a rebuild from it reads the same
REQUIRED = ("globalid", "name", "advisory_lvl", "advisory_issued", "advisory_lifted", "date_observed",
            "public_accessible")
COORD = re.compile(r"-?\d{1,3}\.\d{4,}")


def query_url() -> str:
    return (f"{LAYER}/query?where=1%3D1&outFields={FIELDS}&returnGeometry=true&outSR=4326&geometryPrecision=3"
            "&orderByFields=objectid&resultRecordCount=2000&f=json")


def observed_year(ms) -> int | None:
    if ms in (None, ""):
        return None
    return datetime.fromtimestamp(float(ms) / 1000, timezone.utc).astimezone(ZoneInfo(TZ)).year


def dates_in(text: str | None, year: int | None) -> list[str]:
    out = []
    for m in DATE.finditer(normal_dates(text)):
        mo, dy = int(m.group(1)), int(m.group(2))
        yr = m.group(3)
        y = (int(yr) + 2000 if len(yr) == 2 else int(yr)) if yr else year
        if y is None:
            continue
        try:
            out.append(date(y, mo, dy).isoformat())
        except ValueError:
            continue
    return out


def lift_dates(text: str | None, year: int | None) -> list[str]:
    """The dates of an affirmative, completed lift in DEQ's advisory_lifted note. A negated or conditional note gives
    none. The note is read clause by clause: when it says "lifted" anywhere, only the dates in a clause that says so
    count (each date belongs to the label written before it, or with none before it to the label after it, so in
    "sampled 7/28 then lifted 8/3" only 8/3 is the lift); a planned, scheduled or expected lift is none; otherwise a clause
    of bare dates, or one that names no other dated step, is the lift date (the field is DEQ's lift field), and a date
    that opens the note is DEQ's lift date whatever reason follows it ("9/14 based on ... test results", "2023/08/17 no
    new observations"; go-live audit 2026-11-16, fix 1b), unless the word right after it labels it a sampling or test
    ("7/28 sampled"). Any later date labelled as a sampling, a test or a report is never the lift date."""
    t = normal_dates(text)
    if not t or NOT_A_LIFT_MARK in t or NOT_A_LIFT.search(t):
        return []
    clauses = [c for c in re.split(r"[;,\n]|\.\s", t) if c.strip()]
    if any(LIFT_WORD.search(c) for c in clauses):
        out = []
        for i, c in enumerate(clauses):
            m = LIFT_WORD.search(c)
            if not m:
                continue
            found = list(DATE.finditer(c))
            if not found:   # "8/3/2026 no new info, lifted": the date in the clause beside it, if not another step's
                for j in (i - 1, i + 1):
                    if 0 <= j < len(clauses) and not LIFT_WORD.search(clauses[j]) \
                            and not OTHER_DATE_WORD.search(clauses[j]) and dates_in(clauses[j], year):
                        out += dates_in(clauses[j], year)
                        break
                continue
            # each date belongs to the label written before it ("sampled 7/28 then lifted 8/3": 7/28 the sampling,
            # 8/3 the lift), or, with none before it, to the label after it ("8/3 lifted"); only a lift's dates count
            labels = sorted([(x.start(), "lift") for x in LIFT_WORD.finditer(c)]
                            + [(x.start(), "other") for x in OTHER_DATE_WORD.finditer(c)])
            for d in found:
                before = [k for p, k in labels if p < d.start()]
                after = [k for p, k in labels if p > d.start()]
                if (before[-1] if before else after[0] if after else None) == "lift":
                    out += dates_in(d.group(0), year)
        return out
    out = []
    first = DATE.match(t, len(t) - len(t.lstrip()))
    if first and not STEP_LABEL.match(t, first.end()):
        out += dates_in(first.group(0), year)
    out += [d for c in clauses if not OTHER_DATE_WORD.search(c) for d in dates_in(c, year)]
    return list(dict.fromkeys(out))


def water_name(name: str) -> tuple[str, str | None]:
    n = " ".join((name or "").split()).strip(" -,")
    if n.isupper() or n.islower():
        n = re.sub(r"\b(Of|And|The|At|On|In)\b", lambda m: m.group(1).lower(), n.title())
        n = n[0].upper() + n[1:] if n else n
    for sep in (" - ", ", ", " -", "- "):
        if sep in n:
            a, b = n.split(sep, 1)
            return a.strip(" -,"), b.strip(" -,") or None
    return n, None


def clean(v) -> str | None:
    s = " ".join(str(v).split()) if v not in (None, "") else ""
    return None if s.upper() in ("", "NA", "N/A", "NONE") else s


def periods(starts: list[str], lifts: list[str]) -> list[tuple[str, str | None]]:
    """[(start, lift or None)]: the earliest issue date starts a period and the first lift date on or after it ends it;
    an issue date after that lift starts a new period (a reissue in the same row is a second advisory, never one period
    over the gap)."""
    out, starts, lifts = [], sorted(set(starts)), sorted(set(lifts))
    while starts:
        s0 = starts[0]
        end = next((d for d in lifts if d >= s0), None)
        out.append((s0, end))
        if end is None:
            break
        starts = [d for d in starts if d > end]
    return out


def safe_name(name: str, private: bool) -> str:
    """The reported water name with e-mails, phones and staff names removed and long decimals (a point typed into the
    name) cut; a private water's name with a possessive ("Example's pond") is withheld, as it may name the owner."""
    n = COORD.sub("[point removed]", " ".join(str(name or "").split()))
    n = scrub(n)        # common's scrubbers and the forms they miss (ingest/mountain_scrub.py)
    if private and re.search(r"\w'\s?s\b", n):
        return "Private water (name withheld)"
    return n


# the words DEQ's sample_date, microcystin and anatoxin fields use (dates, results, units, test kinds); any other word
# in them is withheld, so a name, a street or a note can never reach a save (Astra verification 2026-11-15 P1)
RESULT_WORDS = frozenset("""detect detects detected detection nondetect non not nd no none na n a absent present
    positive negative pos neg low high moderate below above less greater than limit reporting rl mdl ug mg ng l ml
    ppb ppm per test tests tested testing strip strips kit lab laboratory sample samples sampled sampling result
    results pending based on as of at and or from for in new info id identification taxa taxon photo photos visual
    observed observation toxin toxins microcystin microcystins anatoxin cylindrospermopsin saxitoxin cyano
    cyanobacteria bloom elisa qpcr pcr water beach shore shoreline open surface dock ramp
    cell cells density dolichospermum aphanizomenon microcystis dominated by some until only algae green
    anabaena oscillatoria lyngbya sp taxa shows producing toxic non low sparse very absent dissipated
    identified description professional provided initial report active concentrated yellowish swirled coloration
    boat launch slight micro""".split())
_WITHHELD = "[withheld]"


def safe_result(v):
    """A sample date or a toxin result kept to its dates, numbers and the result vocabulary: e-mails and phones are
    scrubbed, decimals of four places or more (a point typed into the field) rounded to three, and every other word
    withheld."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    t = clean(v)
    if not t:
        return None
    t = re.sub(r"\[[^\]]*\]", "\x00", scrub(t))        # the scrubbers' own marks become one withheld mark
    t = re.sub(r"-?\d{1,3}\.\d{4,}", lambda m: f"{float(m.group(0)):.3f}", t)
    t = re.sub(r"\d+-[A-Za-z]\b|[A-Za-z]+", lambda m: m.group(0) if m.group(0).lower() in RESULT_WORDS
               else "\x00", t)
    t = re.sub(r"\x00(?:[\s.,'&/-]*\x00)*", _WITHHELD, t)
    return " ".join(t.split()) or None


def density_results(raw: dict) -> list[dict]:
    """DEQ's cyano_density is free text, usually qualitative. Never turn dates or presence into a count.
    A single, fully dated sample field can be normalized; partial/multiple dates remain source text only.
    """
    text = safe_result(raw.get("cyano_density"))
    if text is None or str(text).strip().lower() in {"", "na", "n/a"}:
        return []
    sample = safe_result(raw.get("sample_date"))
    ds = dates_in(str(sample or ""), None) if re.fullmatch(
        r"(?:\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})|\d{4}[/.-]\d{2}[/.-]\d{2})", str(sample or "")) else []
    # No numeric density/unit pair is published in the checked layer (2026-11-22).
    # Keep the typed slots null until a source-backed numeric shape is established.
    return [{"analyte": "Cyanobacteria", "value": None, "units": None, "qualifier": None,
             "text": str(text), "sample_date": ds[0] if len(ds) == 1 else None,
             "sample_date_text": sample, "source_field": "cyano_density", "source_url": LAYER}]


def slug(v: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (v or "").lower()).strip("-") or "water"


RAW_KEPT = ("water", "place", "county", "time_zone", "advisory_level_at_read", "issued_dates", "lifted_dates", "words",
            "agency_field", "sample_date", "microcystin", "anatoxin", "cyano_density", "licence", "dashboard", "start_basis",
            "text_note", "point_withheld", "ended_at_precision", "end_basis", "_last_seen_in_source")


def retained(r: dict, why: str) -> dict:
    """An earlier record this read did not reproduce, kept as it was (never ended, never re-dated) and sanitized."""
    r = sanitized(r)
    r["raw"]["retained"] = why
    return r


def sanitized(r: dict) -> dict:
    """An earlier record carried into a save: its raw fields cut to the allowlist and sanitized again (the name
    scrubbed, a private water's point removed, a point rounded to 0.001 degree)."""
    r = json.loads(json.dumps(r))
    raw = {k: v for k, v in (r.get("raw") or {}).items() if k in RAW_KEPT}
    private = "point_withheld" in raw
    for k in ("water", "place"):
        if raw.get(k):
            raw[k] = safe_name(raw[k], private)
    for k in ("sample_date", "microcystin", "anatoxin", "cyano_density"):
        if k in raw:
            raw[k] = safe_result(raw[k])
    if raw.get("agency_field"):
        raw["agency_field"] = scrub(str(raw["agency_field"])) or None
    r["waterbody_text"] = safe_name(r.get("waterbody_text") or "", private) or r.get("waterbody_text")
    if private or r.get("lat") is None or r.get("lon") is None:
        r["lat"] = r["lon"] = None
    else:
        r["lat"], r["lon"] = round(float(r["lat"]), 3), round(float(r["lon"]), 3)
    if "retained" in (r.get("raw") or {}):
        raw["retained"] = r["raw"]["retained"]
    raw["sample_results"] = density_results(raw)
    r["raw"] = raw
    return r


def build(doc: dict, fetched: str, previous: list[dict] | None = None,
          prev_meta: dict | None = None) -> tuple[list[dict], dict]:
    feats = doc.get("features")
    if feats is None:
        raise ValueError(f"no features in the layer's answer: {str(doc)[:200]}")
    if doc.get("exceededTransferLimit"):
        raise ValueError("the layer has more rows than one query returns; page it")
    if not feats:
        raise ValueError("the layer answered no rows (it holds hundreds): a failed read")
    absent = sorted({k for f in feats for k in REQUIRED if k not in (f.get("attributes") or {})})
    if absent:
        raise ValueError(f"the layer's fields changed: missing {absent}")
    prev = {r["event_id"]: r for r in previous or []}
    prev_gids = {str(r.get("source_record_id") or "").split(":")[0] for r in previous or []}
    recs, n = [], {"rows": len(feats), "records": 0, "lifted": 0, "current": 0, "lapsed": 0, "no_issue_date": 0,
                   "no_advisory_text": 0, "green_algae": 0, "private_point_withheld": 0}
    seen_gids, made_gids, unreadable = [], set(), []
    for f in feats:
        a = f.get("attributes") or {}
        seen_gids.append(str(a.get("globalid") or "").strip("{}").lower())
        issued_text = str(a.get("advisory_issued") or "")
        level = clean(a.get("advisory_lvl"))
        year = observed_year(a.get("date_observed"))
        starts = dates_in(issued_text, year)
        if level == "Green Algae/Other":
            n["green_algae"] += 1
            continue
        if NO_ADVISORY.search(issued_text):
            n["no_advisory_text"] += 1
            continue
        if not starts:
            n["no_issue_date"] += 1
            if seen_gids[-1] in prev_gids:     # a row that made a record before and now reads no issue date
                unreadable.append(seen_gids[-1])
            continue
        lift_text = str(a.get("advisory_lifted") or "")
        lifts = [d for d in lift_dates(lift_text, year) if d >= min(starts)]
        g = f.get("geometry") or {}
        private = clean(a.get("public_accessible")) == "No"
        water, place = water_name(safe_name(a.get("name") or "", private))
        county = clean(a.get("county"))
        words = sorted({w for w in WORDS if w in issued_text.lower() or w in (a.get("advisory_lifted") or "").lower()})
        lat = None if private or g.get("y") is None else round(float(g["y"]), 3)
        lon = None if private or g.get("x") is None else round(float(g["x"]), 3)
        if private:
            n["private_point_withheld"] += 1
        raw = {"water": water, "place": place, "county": county.title() if county else None, "time_zone": TZ,
               "advisory_level_at_read": level or "No Current Advisory", "issued_dates": sorted(set(starts)),
               "lifted_dates": lifts, "words": words,
               "agency_field": scrub(clean(a.get("agency")) or "") or None,
               "sample_date": safe_result(a.get("sample_date")), "microcystin": safe_result(a.get("microcystin")),
               "anatoxin": safe_result(a.get("anatoxin")), "cyano_density": safe_result(a.get("cyano_density")), "licence": LICENCE, "dashboard": DASHBOARD,
               "start_basis": "the earliest date in DEQ's advisory_issued field (its issue date)",
               "text_note": "DEQ's advisory notes are not reproduced: they can name the people who reported a bloom"}
        raw["sample_results"] = density_results(raw)
        if private:
            raw["point_withheld"] = "the report says the water is not publicly accessible: its county only"
        gid = seen_gids[-1]
        pers = periods(starts, lifts)
        for i, (start, lift) in enumerate(pers):
            last = i == len(pers) - 1
            r_raw = dict(raw)
            srid = gid if i == 0 else f"{gid}:{start}"
            # an episode is immutable: a row whose issue date or water was replaced since an earlier read is a new
            # record under its own id, and the earlier record is kept as it was (Astra review 2026-11-15 P2)
            for alt in (f"{gid}:{start}", f"{gid}:{start}:{slug(water)}"):
                old = prev.get(f"{SOURCE_ID}:{srid}")
                if not old or (old.get("started_at"), old.get("waterbody_text")) == (start, water):
                    break
                srid = alt
            if i:
                r_raw["start_basis"] = ("an issue date in DEQ's advisory_issued field after the lift of the row's "
                                        "earlier advisory: a reissue, its own record")
            if lift:
                status, end = "advisory_lifted", lift
                r_raw["ended_at_precision"] = "day"
                r_raw["end_basis"] = ("the earliest date on or after the start in DEQ's advisory_lifted field (its lift "
                                      "date)")
                n["lifted"] += 1
            elif last and level in ("Caution", "Closure"):
                status, end = "advisory_active", None
                r_raw["_last_seen_in_source"] = fetched
                r_raw["end_basis"] = f"DEQ's map shows the level {level} at this read"
                n["current"] += 1
            else:
                status, end = "advisory_active", None
                seen = ((prev.get(f"{SOURCE_ID}:{srid}") or {}).get("raw") or {}).get("_last_seen_in_source")
                if seen:        # confirmed at earlier reads: those days stay confirmed (lessons, item 2)
                    r_raw["_last_seen_in_source"] = seen
                r_raw["end_basis"] = ("no lift date, and DEQ's map shows no current advisory at this read: the advisory "
                                      "is not confirmed after " + ("the last read that showed it" if seen else
                                                                   "its issue date") +
                                      ", so it ages out under the site's 14-day rule")
                n["lapsed"] += 1
            recs.append(event(source_id=SOURCE_ID, source_record_id=srid,
                              event_type="hab_advisory", status=status, waterbody_text=water, lat=lat, lon=lon,
                              coord_source="mt-deq-hab-map observation point" if lat is not None else None,
                              coord_precision_m=100 if lat is not None else None, started_at=start, ended_at=end,
                              time_precision="day", fetched_at=fetched, authority=AUTHORITY,
                              advice_text=(f"DEQ's harmful algal bloom advisory for "
                                           f"{water}{f' ({place})' if place else ''}"
                                           + (f" ({', '.join(words)})" if words else "") + f", issued {start}"
                                           + (f", lifted {end}." if end else "; no lift date given.")),
                              source_url=DASHBOARD, raw=r_raw))
            n["records"] += 1
            made_gids.add(gid)
    # earlier records this read did not reproduce are kept, never ended (lessons, item 4; Astra review 2026-11-15 P1):
    # a row gone from the layer, a row whose advisory fields no longer read, an episode whose dates were replaced
    made = {r["event_id"] for r in recs}
    present = set(seen_gids)
    for eid, r in prev.items():
        if eid in made:
            continue
        g = str(r.get("source_record_id") or "").split(":")[0]
        why = ("the row is no longer in DEQ's layer" if g not in present else
               "the row's advisory fields no longer read" if g in unreadable else
               "the row's issue date or water was replaced at a later read; this episode is kept as it was")
        recs.append(retained(r, why))
        n["retained"] = n.get("retained", 0) + 1
    missing = sorted(g for g in prev_gids - present if g)
    last_ok_rows = (prev_meta or {}).get("last_ok_rows") or (prev_meta or {}).get("rows")
    incomplete = []
    if last_ok_rows and len(feats) < int(last_ok_rows):
        incomplete.append(f"the layer answered {len(feats)} rows, fewer than the {last_ok_rows} of the last good read")
    if missing:
        incomplete.append(f"{len(missing)} rows that made records are not in this answer")
    if unreadable:
        incomplete.append(f"{len(unreadable)} rows that made records no longer read an issue date")
    n["incomplete"] = incomplete
    n["last_ok_rows"] = last_ok_rows if incomplete else len(feats)
    n["missing_rows"] = missing
    n["unreadable_rows"] = sorted(set(unreadable))
    recs.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    return recs, {"registry_ids": [SOURCE_ID], "url": LAYER, **n,
                  "cadence": "the layer is read every run; DEQ edits it through the season"}


SAVED_ATTRS = ("globalid", "county", "sample_date", "advisory_lvl", "advisory_issued", "advisory_lifted",
               "date_observed", "microcystin", "anatoxin", "cyano_density", "public_accessible", "name", "agency")


def safe_rows(doc: dict) -> dict:
    """The raw save: an explicit allowlist of the fields the records use (nothing else the layer answers is saved),
    the free-text advisory fields reduced to the dates and words the records read (the lift note to its affirmative
    lift dates, written "lifted M/D/YYYY", or the not-a-lift mark), the name and agency scrubbed, the point rounded to
    0.001 degree and a private water's point removed (Astra review 2026-11-15 P1)."""
    out = []
    for f in doc.get("features") or []:
        src = f.get("attributes") or {}
        a = {k: src[k] for k in SAVED_ATTRS if k in src}
        y = observed_year(a.get("date_observed"))
        private = clean(a.get("public_accessible")) == "No"
        if "name" in a:
            a["name"] = safe_name(a.get("name") or "", private)
        if a.get("agency") not in (None, ""):
            a["agency"] = scrub(clean(a.get("agency")) or "") or None
        for k in ("sample_date", "microcystin", "anatoxin", "cyano_density"):
            if k in a:
                a[k] = safe_result(a[k])
        t = str(a.get("advisory_issued") or "")
        if t:
            neg = " no advisory" if NO_ADVISORY.search(t) else ""
            ds = [f"{int(d[5:7])}/{int(d[8:10])}/{d[:4]}" for d in dates_in(t, y)]
            a["advisory_issued"] = " ".join(ds + [w for w in WORDS if w in t.lower()]) + neg
        t = str(a.get("advisory_lifted") or "")
        if t:
            ls = [f"lifted {int(d[5:7])}/{int(d[8:10])}/{d[:4]}" for d in lift_dates(t, y)]
            a["advisory_lifted"] = " ".join(ls + [w for w in WORDS if w in t.lower()] + ([] if ls else [NOT_A_LIFT_MARK]))
        g = f.get("geometry") or {}
        geom = None
        if not private and g.get("x") is not None and g.get("y") is not None:
            geom = {"x": round(float(g["x"]), 3), "y": round(float(g["y"]), 3)}
        out.append({"attributes": a, "geometry": geom})
    return {"features": out, "exceededTransferLimit": doc.get("exceededTransferLimit", False)}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fetched = now_iso()
    try:
        if "--file" in argv:
            doc = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
        else:
            r = requests.get(query_url(), headers=HEADERS, timeout=120)
            r.raise_for_status()
            doc = r.json()
            save_raw(SOURCE_ID, json.dumps(safe_rows(doc)), "json")
        prev_doc = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
        recs, meta = build(doc, fetched, prev_doc.get("records", []), prev_doc.get("meta") or {})
    except Exception as e:  # noqa: BLE001
        # the earlier records are kept, sanitized again on this save path too
        kept = [sanitized(r) for r in (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
                if isinstance(r, dict)]
        write_events(SOURCE_ID, kept, ok=False, partial=True, error=scrub_text(f"{error_text(e)}")[:300])
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    if meta["incomplete"]:
        # readable rows updated, the earlier records kept, health false and a non-zero exit (lessons, items 4 and 5)
        path = write_events(SOURCE_ID, recs, ok=False, partial=True, meta=meta,
                            error="incomplete answer: " + "; ".join(meta["incomplete"]))
        print(f"{SOURCE_ID}: INCOMPLETE {'; '.join(meta['incomplete'])} -> {path}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['rows']} rows, {meta['records']} advisories ({meta['lifted']} lifted, "
          f"{meta['current']} current, {meta['lapsed']} with no lift date) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
