"""Nevada operator rows for data/dischargers.json: one row per operator, every Nevada permit in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_nv_operators.py [--dry-run]

Inputs
  1. data/outfalls-plants-us.json: EPA ICIS-NPDES's sewage permits with state NV (17 permits, 37 discharge points):
     16 Nevada permits NV... and the Bureau of Reclamation's Hoover Dam plant (AZ0025160), which ICIS places in Nevada
     but which Arizona's row az-usbr-lower-colorado already holds (left there, named in the notes below).
     permit_name is the owner as EPA records it, permittee the facility.
  2. research/nv/dischargers.json (9 rows: the eight major permits and the City of Sparks's collection system, which
     holds no NPDES permit of its own): each research id stays as an alias of the row that holds its permit.
  3. research/nv/private-utilities-candidates.json (1 permit: NV0024112, a groundwater remediation system in Henderson
     that EPA codes as sewerage, SIC 4952, NAICS 562910).
  4. EPA's overflow tables (the 2026-11-12 current and all-versions extracts): no Nevada report and no Nevada
     collection system, so every permit row is kind "plant"; Sparks's system is "collection_system".
  5. NDEP is not a source here: its permit search and spill intake were not reachable from the collector (2026-11-14).
Rules
  - OWNERS gives every permit its row: the permittee of record as the body calls itself (EPA's spelling in the
    notes), legal_form from docs/legal-forms.md, never an individual's name, never a plant's name as an operator. A
    permit whose holder EPA does not name (only the plant: Truckee Meadows) is a permit-only row ("Permit NV0020150
    (...)", permit_only true, legal_form null), left out of operator counts. Hawthorne Army Depot's permittee of
    record is the company Amentum Services, Inc., and its row is named for it (the depot, a federal facility, in the
    notes). No
    Nevada sewage permit in ICIS is on tribal land; Pyramid Lake (the Pyramid Lake Paiute Tribe's) receives the
    Truckee River below Reno and Sparks.
  - notification_channel: NDEP issues Nevada's NPDES permits; NRS 445A.467 (2025) requires a city, county, town,
    general improvement district, wastewater district or water authority aware of a sewage discharge to notify NDEP
    online or by telephone, and NDEP notifies an affected tribe; no public notice and no published list. The permit's
    24-hour and five-day reports (40 CFR 122.41(l)(6)) go to NDEP; EPA's tables hold no Nevada report.
  - Idempotent: a rerun replaces the rows it wrote (state NV, source_areas ["nv"]) and leaves every other row as it is.
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
RESEARCH = ROOT / "research" / "nv" / "dischargers.json"
CANDIDATES = ROOT / "research" / "nv" / "private-utilities-candidates.json"
CHECKED = "2026-11-14"
STATUTE = "https://www.leg.state.nv.us/NRS/NRS-445A.html#NRS445ASec467"
LAW = ("The Nevada Division of Environmental Protection (NDEP) issues Nevada's NPDES permits: the permit's 24-hour and "
       "five-day noncompliance reports go to NDEP (40 CFR 122.41(l)(6)), which publishes no list of them, and EPA's "
       "overflow tables hold no Nevada report (2026-11-12 extract). NRS 445A.467 (2025) requires a city, county, "
       "unincorporated town, general improvement district, wastewater district or water authority aware of a sewage "
       "discharge to notify NDEP on its website or by telephone; NDEP notifies an Indian tribe that may be affected. "
       f"No public notice is required and none is published ({STATUTE}).")
FEDERAL = ("A federal installation under an NDEP permit: the permit's 24-hour and five-day noncompliance reports go to "
           "NDEP (40 CFR 122.41(l)(6)), which publishes no list of them; NRS 445A.467 binds local governments, not "
           "the federal government. No public notice is required and none is published.")
PRIVATE = ("A private permittee under an NDEP permit: the permit's 24-hour and five-day noncompliance reports go to NDEP "
           "(40 CFR 122.41(l)(6)), which publishes no list of them; NRS 445A.467 binds local governments only. No "
           "public notice is required and none is published.")
OWN = " The operator's own pages were not searched individually."
FED_HELD = {"AZ0025160": "az-usbr-lower-colorado"}
# a permit whose holder is not established (EPA names only the plant): a permit-only row, legal form unknown, left out
# of operator counts (main's rule, scripts/icis_operators.py), never named after the plant as an operator (Astra P2-9)
PERMIT_ONLY = "permit only"
PERMIT_ONLY_CHANNEL = ("The permit's 24-hour and five-day noncompliance reports go to NDEP (40 CFR 122.41(l)(6)), which "
                       "publishes no list of them. Whether NRS 445A.467 also binds the permittee depends on who holds "
                       "the permit, which is not established here. No public notice is required and none is published.")

# permit -> (row id, name, short name, legal form, note)
OWNERS = {
    "NV0020061": ("nv-city-of-fallon", "City of Fallon", "City of Fallon", "city", None),
    "NV0020133": ("nv-city-of-las-vegas", "City of Las Vegas (Water Pollution Control Facility)", "City of Las Vegas",
                  "city", None),
    "NV0020150": ("nv-truckee-meadows-wrf", "Permit NV0020150 (Truckee Meadows Water Reclamation Facility)",
                  "Permit NV0020150 (Truckee Meadows Water Reclamation Facility)", PERMIT_ONLY,
                  "Permit only: EPA ICIS-NPDES gives only the plant's name ('Truckee Meadows Water Reclamation "
                  "Facility') as both owner and facility, not the body that holds the permit; the operator is not "
                  "established here, so this row is not counted as an operator (EPA's facility type: Municipality). The "
                  "plant is said to treat the sewage of Reno and Sparks; who holds the permit was not read. The City "
                  "of Sparks's collection system is its own row (nv-city-of-sparks)."),
    "NV0020168": ("nv-city-of-reno", "City of Reno (Stead Water Reclamation Facility)", "City of Reno", "city",
                  "EPA records the owner as \"RENO, CITY OF\" and the permit as expired (EXP)."),
    "NV0020311": ("nv-city-of-lovelock", "City of Lovelock", "City of Lovelock", "city", None),
    "NV0020451": ("nv-storey-county", "Storey County Public Works (Virginia City and Gold Hill plants)",
                  "Storey County", "county", None),
    "NV0024237": ("nv-storey-county", None, None, None, None),
    "NV0021261": ("nv-clark-county-water-reclamation-district", "Clark County Water Reclamation District (Flamingo and "
                  "Laughlin water resource centers)", "Clark County Water Reclamation District", "special district",
                  None),
    "NV0021563": ("nv-clark-county-water-reclamation-district", None, None, None, None),
    "NV0021946": ("nv-amentum-services-hawthorne", "Amentum Services, Inc. (Hawthorne Army Depot)",
                  "Amentum Services, Inc.", "business or industrial",
                  "EPA records Amentum Services, Inc. as the owner (its permittee of record) and the facility, the Army's "
                  "Hawthorne Army Depot, as a federal facility; the row is named for the permittee of record. Six "
                  "discharge points, the receiving water given as an evaporation pond."),
    "NV0022098": ("nv-city-of-henderson", "City of Henderson (Kurt R. Segler Water Reclamation Facility)",
                  "City of Henderson", "city", None),
    "NV0023167": ("nv-lander-county", "Lander County (Battle Mountain sewage treatment facility)", "Lander County",
                  "county", None),
    "NV0023507": ("nv-nnsa-north-las-vegas", "U.S. Department of Energy, National Nuclear Security Administration (North "
                  "Las Vegas Facility)", "NNSA North Las Vegas Facility", "federal facility", None),
    "NV0023582": ("nv-churchill-county", "Churchill County Public Works (Moody Lane Regional Water Reclamation "
                  "Facility)", "Churchill County", "county", None),
    "NV0023647": ("nv-city-of-north-las-vegas", "City of North Las Vegas", "City of North Las Vegas", "city", None),
    "NV0110001": ("nv-naval-air-station-fallon", "U.S. Navy, Naval Air Station Fallon", "Naval Air Station Fallon",
                  "federal facility", None),
    # the private candidate (research/nv/private-utilities-candidates.json)
    "NV0024112": ("nv-endeavour-llc-agts", "Endeavour, LLC (AGTS groundwater treatment system, Henderson)",
                  "Endeavour, LLC", "business or industrial",
                  "A groundwater remediation system (NAICS 562910) that EPA codes as sewerage (SIC 4952); not a sewage "
                  "plant. EPA types the permittee a corporation; not in the plant registry, so no discharge point is "
                  "counted here."),
}
SPARKS = {"id": "nv-city-of-sparks", "name": "City of Sparks (sewer collection system)", "short_name": "City of Sparks",
          "legal_form": "city", "kind": "collection_system", "towns": ["Sparks"],
          "notes": ("The city's sewers deliver to the Truckee Meadows Water Reclamation Facility (NV0020150); the system "
                    "holds no NPDES permit of its own. A 2022 spill from its system into the Truckee River was not "
                    "reported to NDEP (NDEP's later findings, as reported by the press), the case that led to NRS "
                    "445A.467 (the site repository's research/nv/report.md §2.3).")}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}


def title(s: str) -> str:
    return " ".join(w.title() if w.isupper() or w.islower() else w for w in (s or "").split())


def plants() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "NV" and r.get("npdes_permit"):
            out[r["npdes_permit"].upper()].append(r)
    return out


def channel(lf: str | None) -> str:
    if lf == PERMIT_ONLY:
        return PERMIT_ONLY_CHANNEL
    if lf == "federal facility":
        return FEDERAL
    if lf in PRIVATE_FORMS:
        return PRIVATE
    return LAW + OWN


def build(dis: list[dict]) -> tuple[list[dict], dict]:
    keep = [d for d in dis if not (d.get("state") == "NV" and "nv" in (d.get("source_areas") or []))]
    held = {str(p).upper(): d["id"] for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    pl = plants()
    research: dict[str, list[dict]] = defaultdict(list)
    sparks_aliases = []
    for r in json.loads(RESEARCH.read_text()):
        if r.get("npdes_permit"):
            research[r["npdes_permit"]].append(r)
        else:
            sparks_aliases.append(r["id"])
    cand = json.loads(CANDIDATES.read_text())
    cands = {c["npdes_permit"]: c for c in cand["candidates"] + cand.get("public_by_name", [])}
    permits = sorted(set(pl) | set(research) | set(cands))
    elsewhere = sorted(p for p in permits if p in held)
    for p in elsewhere:
        if FED_HELD.get(p) != held[p]:
            raise SystemExit(f"{p} is held by {held[p]}, not the row expected")
    permits = [p for p in permits if p not in held]
    unknown = [p for p in permits if p not in OWNERS]
    if unknown:
        raise SystemExit(f"permits without an owner in OWNERS: {unknown}")
    meta, by_row = {}, defaultdict(list)
    for p in permits:
        rid, name, short, lf, note = OWNERS[p]
        if name:
            meta[rid] = {"name": name, "short": short, "lf": lf, "note": note}
        by_row[rid].append(p)
    new = []
    for rid, ps in by_row.items():
        m = meta[rid]
        rows = [r for p in ps for r in pl.get(p, [])]
        towns = sorted({title(r["city"]) for r in rows if r.get("city") and "COUNTY" not in r["city"].upper()}
                       | {title(cands[p]["city"]) for p in ps if p in cands and cands[p].get("city")})
        waters = list(dict.fromkeys(r["receiving_water_echo"].strip() for r in rows if r.get("receiving_water_echo")))[:8]
        facs = "; ".join(f"{p} {title((pl.get(p) or [{}])[0].get('permittee') or (cands.get(p) or {}).get('facility') or '')}"
                         .strip() for p in ps)
        note = f"EPA ICIS-NPDES: {facs}. No report under these permits is in EPA's overflow tables (2026-11-12 extract)."
        if m["note"]:
            note += " " + m["note"]
        rids = [r["id"] for p in ps for r in research.get(p, [])]
        po = m["lf"] == PERMIT_ONLY
        new.append({"id": rid, "name": m["name"], "short_name": m["short"], "legal_form": None if po else m["lf"],
                    **({"permit_only": True} if po else {}), "state": "NV",
                    "kind": "plant", "npdes_permit": ps[0], "npdes_permits": ps, "receiving_waters": waters,
                    "water_slugs": [], "outfall_count": len(rows) or None,
                    "outfalls_source": (f"EPA ICIS-NPDES discharge points (data/outfalls-plants-us.json, {len(rows)} rows)"
                                        if rows else None),
                    "notification_channel": channel(m["lf"]), "notification_feed_machine_readable": False,
                    "notification_signup_url": None, "towns": towns, "notes": note, "verified": "fetched",
                    "checked": CHECKED, "aliases": list(dict.fromkeys([rid] + rids)), "source_areas": ["nv"]})
    new.append({**SPARKS, "state": "NV", "npdes_permit": None, "npdes_permits": [], "receiving_waters": [],
                "water_slugs": [], "outfall_count": None, "outfalls_source": None,
                "notification_channel": LAW + OWN, "notification_feed_machine_readable": False,
                "notification_signup_url": None, "verified": "fetched", "checked": CHECKED,
                "aliases": list(dict.fromkeys([SPARKS["id"]] + sparks_aliases)), "source_areas": ["nv"]})
    new.sort(key=lambda r: r["id"])
    ids = Counter(r["id"] for r in keep + new)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup}")
    stats = {"rows": len(new), "permits": sum(len(r["npdes_permits"]) for r in new),
             "discharge_points": sum(r["outfall_count"] or 0 for r in new), "held_elsewhere": elsewhere,
             "permit_only_rows": sum(1 for r in new if r.get("permit_only")),
             "operators": sum(1 for r in new if not r.get("permit_only")),
             "legal_form": dict(Counter(r["legal_form"] for r in new)), "kind": dict(Counter(r["kind"] for r in new))}
    return keep + new, stats


def main(argv: list[str]) -> int:
    out, stats = build(json.loads(DIS.read_text()))
    print(json.dumps(stats, indent=1))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
