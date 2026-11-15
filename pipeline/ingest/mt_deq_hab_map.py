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
  On 2026-11-14: 445 rows (2019 to 2026, 77 in 2026); 322 carry an issued advisory date; no row was at Caution or
  Closure (the season's advisories had all been lifted or lapsed).

Safe fields (requested by name; nothing else is read or saved): globalid, name, county, agency, sample_date,
  advisory_lvl, advisory_issued, advisory_lifted, date_observed, microcystin, anatoxin, public_accessible and the point
  (0.001 degree, WGS84). Never requested: desc_bloom (the reporter's description), pic_url, the illness questions and
  the survey's other answers. The advisory_issued and advisory_lifted texts can name people ("reported by ..."): only
  the dates read from them and the words caution, closure and toxin are kept; the text itself is never stored or saved.

Record rules
  - A row is a record when advisory_issued gives a date and does not say no advisory was issued, and DEQ's level is not
    "Green Algae/Other" (not a cyanobacteria bloom). event_type hab_advisory. started_at the earliest date in
    advisory_issued (DEQ's issue date, day precision, Mountain time); a date written without its year takes the year of
    date_observed, read in Mountain time.
  - advisory_lifted with a date on or after the start: status advisory_lifted, ended_at that date (raw.ended_at_precision
    day; DEQ's own lift date). advisory_lvl Caution or Closure at the read: advisory_active, confirmed at that read
    (raw._last_seen_in_source). Otherwise (no lift date, the layer at "No Current Advisory"): advisory_active with no
    end and no confirmation, so the status build's 14-day rule ages it from its issue date; raw.end_basis says so.
  - A row whose public_accessible answer is "No" (a private pond) keeps its county and no point.
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

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, scrub_names, scrub_text, write_events

SOURCE_ID = "mt-deq-hab-map"
LAYER = ("https://gis.mtdeq.us/hosting/rest/services/Hosted/Harmful_Algal_Bloom_Survey_(Public_Web_Map)/FeatureServer/0")
DASHBOARD = "https://gis.mtdeq.us/portal/apps/dashboards/10c34f5c7da24c4188b9ddc220d43970"
FIELDS = ("globalid,name,county,agency,sample_date,advisory_lvl,advisory_issued,advisory_lifted,date_observed,"
          "microcystin,anatoxin,public_accessible")
AUTHORITY = "Montana Department of Environmental Quality (harmful algal bloom map)"
TZ = "America/Denver"
LICENCE = ("Data intended for reference and planning purposes only. DEQ takes no responsibility for misuse of data "
           "outside suggested use parameters. Data collected and/or created by members of the public as a public source "
           "dataset. DEQ cannot verify accuracy or contents of publicly editable data.")
DATE = re.compile(r"(?<![\d/.])(\d{1,2})[/.](\d{1,2})(?:[/.](\d{4}|\d{2}))?(?![\d/])")
NO_ADVISORY = re.compile(r"\bno advisory\b|\bnot issued\b", re.I)
WORDS = ("caution", "closure", "toxin")
# a lift note that is not a completed lift ("lift pending 8/3", "will lift 8/3 if no new info", "not lifted 8/3")
NOT_A_LIFT = re.compile(r"\b(?:not|never|pending|will|would|to be|expected to|planned to|may|can)\s+(?:be\s+)?lift|"
                        r"\blift(?:ed|ing)?\s+(?:is\s+)?(?:pending|when|if|once|until|unless|after)\b", re.I)
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
    for m in DATE.finditer(text or ""):
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
    n = scrub_names(scrub_text(" ".join(str(name or "").split())))
    n = COORD.sub("[point removed]", n)
    if private and re.search(r"\w'\s?s\b", n):
        return "Private water (name withheld)"
    return n


def build(doc: dict, fetched: str, previous: list[dict] | None = None) -> tuple[list[dict], dict]:
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
    recs, n = [], {"rows": len(feats), "records": 0, "lifted": 0, "current": 0, "lapsed": 0, "no_issue_date": 0,
                   "no_advisory_text": 0, "green_algae": 0, "private_point_withheld": 0}
    for f in feats:
        a = f.get("attributes") or {}
        issued_text = a.get("advisory_issued") or ""
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
            continue
        lift_text = a.get("advisory_lifted") or ""
        lifts = [] if NOT_A_LIFT.search(lift_text) or NOT_A_LIFT_MARK in lift_text else [d for d in dates_in(lift_text, year) if d >= min(starts)]
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
               "agency_field": scrub_names(scrub_text(clean(a.get("agency")) or "")) or None,
               "sample_date": clean(a.get("sample_date")), "microcystin": clean(a.get("microcystin")),
               "anatoxin": clean(a.get("anatoxin")), "licence": LICENCE, "dashboard": DASHBOARD,
               "start_basis": "the earliest date in DEQ's advisory_issued field (its issue date)",
               "text_note": "DEQ's advisory notes are not reproduced: they can name the people who reported a bloom"}
        if private:
            raw["point_withheld"] = "the report says the water is not publicly accessible: its county only"
        gid = str(a.get("globalid") or "").strip("{}").lower()
        pers = periods(starts, lifts)
        for i, (start, lift) in enumerate(pers):
            last = i == len(pers) - 1
            r_raw = dict(raw)
            srid = gid if i == 0 else f"{gid}:{start}"
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
    recs.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    return recs, {"registry_ids": [SOURCE_ID], "url": LAYER, **n,
                  "cadence": "the layer is read every run; DEQ edits it through the season"}


def safe_rows(doc: dict) -> dict:
    """The answer with the free-text advisory fields reduced to the dates and words the records use (the raw save)."""
    out = []
    for f in doc.get("features") or []:
        a = dict(f.get("attributes") or {})
        y = observed_year(a.get("date_observed"))
        for k in ("advisory_issued", "advisory_lifted"):
            t = a.get(k) or ""
            neg = " no advisory" if k == "advisory_issued" and NO_ADVISORY.search(t) else ""
            ds = [f"{int(d[5:7])}/{int(d[8:10])}/{d[:4]}" for d in dates_in(t, y)]
            mark = [NOT_A_LIFT_MARK] if k == "advisory_lifted" and NOT_A_LIFT.search(t) else []
            a[k] = " ".join(ds + [w for w in WORDS if w in t.lower()] + mark) + neg if t else t
        out.append({"attributes": a, "geometry": f.get("geometry")})
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
        prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
        recs, meta = build(doc, fetched, prev)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['rows']} rows, {meta['records']} advisories ({meta['lifted']} lifted, "
          f"{meta['current']} current, {meta['lapsed']} with no lift date) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
