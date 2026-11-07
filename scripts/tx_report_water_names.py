"""research/tx/receiving-waters-missing.json: the water names Texas's records give that data/receiving-waters-national.json
does not hold for TX, for `python -m ingest.waters_from_nhd --names ... --state TX` (the cloud water batch).

Usage (after `python -m ingest.generic tx-tceq-sso-opendata` and `tx-glo-beach-watch` have written data/build/events):
    pipeline/.venv/bin/python -I scripts/tx_report_water_names.py

TCEQ's table (tx-tceq-sso-opendata): a name is the record's waterbody_text (the receiving_water_body field, scrubbed),
counted once per report. Left out, with counts by reason in by_reason: records naming no water (TCEQ's "not provided"
wordings and segment numbers, which the ingester leaves empty), texts the status build reads as reaching no water or as
naming none ("CONTAINED ON SITE", "GROUND", "STORM DRAIN", "SPILLED INTO STREET"), watershed labels ("SAN JACINTO RIVER
BASIN"), texts with no water word (a street, a ditch, a manhole), and texts that keep a removed name or house number.
Several waters in one text ("Cypress Creek and Spring Creek") stay one row: the batch reads the name as given. A
leading "Spilled into", a trailing full stop and TCEQ's segment prefix ("1007 of the ...") are taken off. A name is
compared with the national list's names, keys, names seen and GNIS names, case and punctuation aside. Texas Beach Watch
names no water (its stations are placed by their points): it adds no row.
Each row is one name in one county (review 2026-11-07 P2-4: same-named creeks of different counties are different
waters): name, reports, county, towns (the reporting operators' towns, most reports first), permits (up to five),
sources, gnis_name_of (when the national list has the name only as a GNIS name of another water), the TCEQ segment
codes the reports give (river_segment), and the spellings seen (up to five; only those with no number, street or
plant word, so no address is quoted).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from build import status as S  # noqa: E402

EVENTS = ROOT / "data" / "build" / "events"
OUT = ROOT / "research" / "tx" / "receiving-waters-missing.json"
ARCHIVE = ROOT / "data" / "build" / "archive" / "tx-tceq-sso-opendata"
WATER_WORD = re.compile(r"\b(creek|cr\.?|river|bayou|lake|branch|br\.?|reservoir|bay|slough|tributary|trib\.?|draw|"
                        r"arroyo|canal|channel|pond|lagoon|gulf|harbou?r|cove|fork|run|springs?|marsh|estuary|resaca|"
                        r"laguna|inlet|pass|gully|prong|brazos|trinity|sabine|neches|guadalupe|nueces|colorado|"
                        r"rio grande|pecos|san antonio|san jacinto|san marcos|comal|llano|pedernales|blanco|medina|"
                        r"frio|lavaca|navidad|angelina|sulphur|wichita|canadian)\b", re.I)
LABEL = re.compile(r"\b(basin|watershed|drainage area|segment)\b", re.I)
SCRUBBED = re.compile(r"\[(?:name|house number|phone|email) removed\]")
NO_WATER_WORDS = re.compile(r"^\W*(?:spilled\s+)?(?:in(?:to)?\s+)?(?:the\s+)?(?:street|road|roadway|yard|grass|ground|soil|"
                            r"storm\s*(?:drain|sewer|water)\S*|ditch(?:es)?|roadside\s+ditch|drainage\s+ditch|manhole|"
                            r"parking\s+lot|sidewalk|curb|gutter|culvert)\W*$", re.I)


GENERIC = {"unnamed", "unamed", "un", "named", "unknown", "nearby", "near", "creek", "creeks", "river", "tributary",
           "trib", "tributaries", "drainage", "channel", "canal", "draw", "branch", "lake", "pond", "bay", "bayou",
           "stream", "waterway", "water", "body", "local", "intermittent", "dry", "small", "the", "a", "an", "of", "to",
           "into", "and", "or", "unk", "cr", "br", "unnamed", "storm", "ditch", "spring", "springs", "gully", "slough",
           "fork", "nearest", "adjacent", "surface", "waters", "receiving"}
STREETISH = re.compile(r"\b(?:street|st|road|rd|drive|dr|lane|ln|avenue|ave|blvd|boulevard|highway|hwy|fm|cr|court|ct|"
                       r"circle|cir|parkway|pkwy|trail|way|across from|wwtp|wwtf|plant|lift ?station|manhole|address)\b", re.I)


def proper(n: str) -> bool:
    """Whether a name has a word of its own beyond the generic water words ('Unnamed Creek' has none)."""
    return any(w not in GENERIC for w in re.findall(r"[a-z]+", n.lower()))


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def clean_name(t: str) -> str:
    t = " ".join(t.split()).strip(" .;,")
    t = re.sub(r"^(?:spilled|discharged|flowed|went)\s+(?:in)?to\s+(?:the\s+)?", "", t, flags=re.I)
    t = re.sub(r"^\d{3,4}[a-z]{0,2}\s+(?:of\s+the\s+|-\s*|:\s*)", "", t, flags=re.I)
    t = re.sub(r"^river\s*/\s*creek\b[,\s]*", "", t, flags=re.I)
    t = re.sub(r"\s*(?:\(\s*\d{3,4}[a-z]{0,2}\s*\)|,?\s*seg(?:ment)?\.?\s*(?:no\.?|#)?\s*\d{3,4}[a-z]{0,2}|\s\d{3,4}[a-z]{0,2})\s*$",
               "", t, flags=re.I).strip(" .;,-")
    return t.title() if t.isupper() or t.islower() else t


def records():
    """The live build's records and, when written, the yearly archive's (scripts/tx_tceq_archive.py)."""
    p = EVENTS / "tx-tceq-sso-opendata.json"
    if not p.exists():
        raise SystemExit("run `python -m ingest.generic tx-tceq-sso-opendata` first")
    yield from json.loads(p.read_text()).get("records", [])
    for f in sorted(ARCHIVE.glob("[12]*.json")):
        yield from json.loads(f.read_text()).get("records", [])


def main() -> int:
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["TX"]["waters"]
    have = {compact(n) for w in nat for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    gnis_of: dict[str, set] = defaultdict(set)          # a GNIS name -> the national waters that carry it as a part
    for w in nat:
        for g in w.get("gnis_names") or []:
            gnis_of[compact(g)].add(w["name"])
    towns_of = {r["id"]: r.get("towns") or [] for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
                if r.get("state") == "TX"}
    reports, permits, segments, towns = Counter(), defaultdict(Counter), defaultdict(set), defaultdict(Counter)
    spellings: dict[tuple, Counter] = defaultdict(Counter)
    shown: dict[str, str] = {}
    why = Counter()
    resolved = Counter()
    for r in records():
        if r.get("duplicate_of") or (r.get("raw") or {}).get("_missing_from_source_since"):
            continue
        t = r.get("waterbody_text")
        if not t:
            why["no water given (TCEQ's wordings, segment numbers, basin names)"] += 1
            continue
        if S.stated_no_water(t) or S.no_water_text(t) or NO_WATER_WORDS.match(t):
            why["the text names no water or says none was reached"] += 1
            continue
        if SCRUBBED.search(t):
            why["the text kept a removed name or house number"] += 1
            continue
        if LABEL.search(t):
            why["a watershed or segment label, not a water"] += 1
            continue
        if not WATER_WORD.search(t):
            why["no water word in the text"] += 1
            continue
        n = clean_name(t)
        k = compact(n)
        if not k or not proper(n):
            why["a generic wording, no water's own name ('Unnamed Creek')"] += 1
            continue
        if re.search(r"\d", n) or STREETISH.search(n):
            why["the text carries a number, a street or a plant, not only a water's name"] += 1
            continue
        if k in have:
            resolved[k] += 1
            continue
        raw = r.get("raw") or {}
        key = (shown.setdefault(k, n), raw.get("county") or "county not given")
        reports[key] += 1
        sp = " ".join(t.split())
        if not re.search(r"\d", sp) and not STREETISH.search(sp):     # a spelling is quoted only when it is a name
            spellings[key][sp] += 1
        if r.get("npdes_permit"):
            permits[key][r["npdes_permit"]] += 1
        if raw.get("_tceq_segment"):
            segments[key].add(raw["_tceq_segment"])
        for tw in towns_of.get(r.get("discharger_id"), [])[:3]:
            towns[key][tw] += 1
    rows = []
    for key in sorted(reports, key=lambda x: (-reports[x], x)):
        n, county = key
        rows.append({"name": n, "reports": reports[key], "county": county,
                     "towns": [t for t, _ in towns[key].most_common(3)],
                     "permits": [q for q, _ in permits[key].most_common(5)],
                     "sources": ["tx-tceq-sso-opendata"],
                     **({"gnis_name_of": sorted(gnis_of[compact(n)])} if gnis_of.get(compact(n)) else {}),
                     **({"segments": sorted(segments[key])} if segments[key] else {}),
                     "spellings": [s for s, _ in spellings[key].most_common(5)]})
    doc = {"about": ("Water names in TX's records that data/receiving-waters-national.json does not hold for TX: TCEQ's "
                     "Sanitary Sewer Overflows table (data.texas.gov 8kc5-95uk, read 2026-11-07, every report since "
                     "2010; the receiving water a report gives, once per report), one row per name and county, with the "
                     "towns of the operators that reported it (nearest first by reports), the permits and TCEQ segment "
                     "codes. A name the national list carries only as a GNIS name of another water is kept, with that "
                     "water in gnis_name_of (Post Oak Creek in Grayson County is not the Red River). Records naming no "
                     "water and texts that are not a water's name are left out (by_reason). Texas Beach Watch names no "
                     "water: its stations are placed by their points. Written by scripts/tx_report_water_names.py."),
           "state": "TX", "waters": len(rows), "names": len({r["name"] for r in rows}),
           "reports": sum(reports.values()), "reports_on_listed_waters": sum(resolved.values()),
           "by_reason": dict(why.most_common()), "rows": rows}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} rows ({doc['names']} names), {sum(reports.values())} reports; {sum(resolved.values())} reports on "
          f"listed waters; left out {dict(why)} -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
