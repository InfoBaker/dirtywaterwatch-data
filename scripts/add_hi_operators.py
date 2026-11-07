"""Hawaii operator rows for data/dischargers.json: one row per operator, every Hawaii sewage permit EPA lists in exactly
one row.

Usage: pipeline/.venv/bin/python -I scripts/add_hi_operators.py [--dry-run]

Inputs
  - data/outfalls-plants-us.json: the twelve Hawaii plant permit rows EPA lists (eleven NPDES permits and HIF014798, a
    second EPA record of the Wailua plant). Hawaii has no combined sewers: no row in data/outfalls-us.json.
  - research/hi/dischargers.json (6 rows): the counties, the City and County of Honolulu and the two military bases.
    Each keeps its research id.
  - research/hi/private-utilities-candidates.json: the two privately owned sewage permits EPA lists outside the plant
    table: HI0020303 (the East Honolulu plant, Hawaii-American Water) and HI0110141 (the Schofield Barracks plant,
    Aqua Engineers, Inc., which owns and runs the Army post's wastewater system), each with the permittee EPA records.
Rules
  - legal_form from the controlled list (docs/legal-forms.md): the City and County of Honolulu is "city" (a consolidated
    city-county); Hawaii, Kauai and Maui counties are "county"; the bases are "federal facility"; the two companies are
    "investor-owned utility" (their business is the sewer service of the area they serve).
  - kind: "sso" for an operator with sewage spill advisories in the Department of Health's list, "bypass" for the
    Marine Corps plant (its advisories are effluent above the permit's bacteria limit), "plant" for the Schofield
    Barracks plant (none in the list read on 2026-11-07).
  - notification_channel: HAR 11-62 Appendix B (read 2026-11-07): the operator notifies the Department's Clean Water
    Branch, sends a press release to the news media for large spills and posts warning signs; the Department posts its
    own advisory list and e-mail notices by island. The operators' own pages were not searched. notification_signup_url: the Department's portal, where the e-mail notices are subscribed.
  - Idempotent: every row with state HI is rebuilt; other states' rows are left as they are; the Hawaii rows are
    written after the last row of the file in id order.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "hi" / "dischargers.json"
PRIVATE = ROOT / "research" / "hi" / "private-utilities-candidates.json"
CHECKED = "2026-11-07"
PORTAL = "https://eha-cloud.doh.hawaii.gov/cwb/"
LAW = ("HAR 11-62 Appendix B (Responses for Wastewater Spills, Overflows, and Discharges, July 1, 2014; read in the "
       "Department's copy of chapter 11-62 on 2026-11-07) requires whoever owns or runs a wastewater system, for a spill "
       "into state waters, to notify the Hawaii Department of Health's Clean Water Branch immediately, send a press "
       "release to the news media for a spill of 1,000 gallons or more or one that threatens public health, post "
       "warning signs where the public has access, sample the affected waters until the Department says to stop, and "
       "report in writing within five working days; NPDES permits under HAR 11-55 add their own reporting conditions. "
       "The Department also posts an advisory on its Clean Water Branch website (a machine-readable list this site "
       "reads) and sends e-mail notices by island. The operator's own web pages were not searched.")
# advisories naming the operator's facilities in the Department's newest 500 events, read 2026-11-07
ADVISORIES = {"hi-honolulu-env": 18, "hi-hawaii-county": 2, "hi-kauai-county": 2, "hi-maui-county": 1,
              "hi-mcbh-kaneohe": 4, "hi-jbphh": 9, "hi-hawaii-american-water": 2}

PERMITS = {
    "HI0020877": "hi-honolulu-env", "HI0021954": "hi-honolulu-env", "HI0021296": "hi-honolulu-env",
    "HI0021953": "hi-honolulu-env", "HI0021956": "hi-honolulu-env",
    "HI0021377": "hi-hawaii-county", "HI0021113": "hi-hawaii-county", "HI0020770": "hi-hawaii-county",
    "HI0020257": "hi-kauai-county", "HIF014798": "hi-kauai-county",
    "HI0110078": "hi-mcbh-kaneohe", "HI0110086": "hi-jbphh",
    "HI0020303": "hi-hawaii-american-water", "HI0110141": "hi-aqua-engineers-schofield",
}
# id -> (name, short_name, legal_form, kind, note)
ROWS = {
    "hi-honolulu-env": ("City and County of Honolulu, Department of Environmental Services (Honouliuli, Sand Island, "
                        "Kailua Regional, Waianae and Wahiawa plants and the collection system)",
                        "City and County of Honolulu", "city", "sso",
                        "EPA lists two permits for the Honouliuli plant: HI0021954, and HI0020877, terminated "
                        "05/31/2026. The Wahiawa plant has "
                        "no permit in EPA's plant table."),
    "hi-hawaii-county": ("County of Hawaii, Department of Environmental Management (Hilo, Papaikou-Paukaa and Kulaimano "
                         "plants and the collection system)", "County of Hawaii", "county", "sso", None),
    "hi-kauai-county": ("County of Kauai, Wastewater Management Division (Wailua, Waimea and Lihue plants and the "
                        "collection system)", "County of Kauai", "county", "sso",
                        None),
    "hi-maui-county": ("County of Maui, Department of Environmental Management (Kihei, Lahaina and Wailuku-Kahului "
                       "plants and the collection system)", "County of Maui", "county", "sso",
                       "EPA lists no NPDES permit for the county's plants, which dispose of treated wastewater to "
                       "injection wells (research of 2026-11-03)."),
    "hi-mcbh-kaneohe": ("Marine Corps Base Hawaii (Kaneohe Bay water reclamation facility)", "Marine Corps Base Hawaii",
                        "federal facility", "bypass", None),
    "hi-jbphh": ("Joint Base Pearl Harbor-Hickam (wastewater treatment plant and collection system)",
                 "Joint Base Pearl Harbor-Hickam", "federal facility", "sso", None),
    "hi-hawaii-american-water": ("Hawaii-American Water Company (East Honolulu plant, Hawaii Kai)",
                                 "Hawaii-American Water", "investor-owned utility", "sso",
                                 "Privately owned: the company that provides sewer service in Hawaii Kai (EPA facility "
                                 "type Privately Owned Facility; SIC 4952); the permittee as EPA records it. Not in the "
                                 "plant outfall table."),
    "hi-aqua-engineers-schofield": ("Aqua Engineers, Inc. (Schofield Barracks plant, Wahiawa)", "Aqua Engineers",
                                    "investor-owned utility", "plant",
                                    "Privately owned: the company that owns and runs the Army post's wastewater "
                                    "system (EPA facility type Privately Owned Facility; SIC 4952); the permittee as "
                                    "EPA records it. Not in the plant outfall table."),
}
TOWN_FIX = {"Honolulu County": None, "Pearl Harbor": "Honolulu"}
# final audit 2026-11-07 P2-3, from EPA ECHO read 2026-11-07 (scripts/hi_outfall_corrections.py, data/outfalls-hi.json)
TERMINATED = {"HI0020877": "terminated 05/31/2026 (EPA ECHO: Terminated, individual NPDES permit)"}
NOT_SEWAGE = {"HIF014798": ("a general-permit coverage at the Wailua plant (EPA ECHO: General Permit Covered Facility under "
                            "master permit HIR000000, other id R90H876, effective 07/10/2025, no POTW component), very "
                            "probably its storm-water coverage, not a sewage discharge permit")}
# the research's receiving waters that name no water ("Oahu streams", "Kihei coast") are left out; "Nawiliwili" is the bay
WATER_FIX = {"Oahu streams": None, "Kihei coast": None, "Lahaina coast": None, "Nawiliwili": "Nawiliwili Bay"}


def title(s: str) -> str:
    s = (s or "").strip()
    return s.title() if s.isupper() or s.islower() else s


def load_epa() -> dict[str, dict]:
    """permit -> {facility, city, waters, outfalls}."""
    out: dict[str, dict] = {}
    doc = json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())
    for r in doc["outfalls"] if isinstance(doc, dict) else doc:
        p = str(r.get("npdes_permit") or "").upper()
        if not p.startswith("HI") or r.get("state") not in (None, "HI"):
            continue
        o = out.setdefault(p, {"facility": None, "city": None, "waters": [], "outfalls": 0})
        o["facility"] = o["facility"] or r.get("permittee")
        o["city"] = o["city"] or r.get("city")
        w = (r.get("receiving_water_echo") or "").strip()
        if w and w not in o["waters"]:
            o["waters"].append(w)
        o["outfalls"] += 1
    cand = json.loads(PRIVATE.read_text())
    for c in cand["candidates"] + cand.get("public_by_name", []):
        out.setdefault(c["npdes_permit"], {"facility": c["facility"], "city": c.get("city"),
                                           "waters": list(c.get("receiving_waters_echo") or []), "outfalls": 0})
    return out


def build(epa: dict[str, dict], research: list[dict]) -> tuple[list[dict], dict]:
    missing = sorted(set(epa) - set(PERMITS))   # HIF014798 is mapped so that its note lands on the Kauai row
    if missing:
        raise SystemExit(f"Hawaii permits with no row: {missing}")
    groups: dict[str, list[str]] = {rid: [] for rid in ROWS}
    for p in sorted(epa):
        groups[PERMITS[p]].append(p)
    res = {r["id"]: r for r in research}
    rows = []
    for rid in sorted(ROWS):
        permits = groups[rid]
        name, short, lf, kind, why = ROWS[rid]
        r0 = res.get(rid)
        first = [x.strip() for x in str((r0 or {}).get("npdes_permit") or "").split(";")][0].split(" ")[0]
        if first in permits:
            permits = [first] + [p for p in permits if p != first]
        other = [p for p in permits if p in NOT_SEWAGE]             # not a sewage permit: out of the permittee's list
        permits = [p for p in permits if p not in NOT_SEWAGE]
        permits = [p for p in permits if p not in TERMINATED] + [p for p in permits if p in TERMINATED]   # active first
        towns = list((r0 or {}).get("towns") or [])
        for p in permits:
            t = title(epa[p].get("city") or "")
            t = TOWN_FIX.get(t, t)
            if t and t not in towns:
                towns.append(t)
        waters = [WATER_FIX.get(w, w) for w in (r0 or {}).get("receiving_waters") or []]
        waters = list(dict.fromkeys([w for w in waters if w] + [title(w) for p in permits for w in epa[p]["waters"]]))
        n_out = sum(epa[p]["outfalls"] for p in permits if p not in TERMINATED)
        facs = "; ".join(f"{p} {epa[p]['facility']}" for p in permits)
        note = f"EPA ECHO ICIS-NPDES: {facs}." if facs else "EPA ECHO ICIS-NPDES: no permit."
        if why:
            note += " " + why
        if r0:
            note += f" Research row (research/hi/dischargers.json, checked {r0.get('checked')})."
        n_adv = ADVISORIES.get(rid)
        if n_adv:
            note += (f" The Department of Health's advisory list names its facilities in {n_adv} of the newest 500 "
                     "events (read 2026-11-07).")
        row = {"id": rid, "name": name, "state": "HI", "kind": kind, "npdes_permit": permits[0] if permits else None,
               "npdes_permits": permits, "receiving_waters": waters, "water_slugs": [], "outfall_count": n_out or None,
               "outfalls_source": ("EPA ECHO ICIS-NPDES discharge points (data/outfalls-plants-us.json: "
                                   f"{n_out} rows for these permits)") if n_out else None,
               "notification_channel": LAW, "notification_feed_machine_readable": True,
               "notification_signup_url": PORTAL, "towns": towns, "notes": note,
               "verified": "fetched", "checked": CHECKED, "aliases": [rid],
               "source_areas": ["hi"] + ([] if r0 else ["federal"]), "short_name": short, "legal_form": lf}
        pnote = [f"{p}: {TERMINATED[p]}" for p in permits if p in TERMINATED] + \
                [f"{p} is not listed as a sewage permit: {NOT_SEWAGE[p]}" for p in other]
        if pnote:
            row["permit_note"] = "; ".join(pnote) + "."
        rows.append(row)
    stats = {"rows": len(rows), "permits": sum(len(r["npdes_permits"]) for r in rows),
             "by_form": dict(Counter(r.get("legal_form") for r in rows)),
             "by_kind": dict(Counter(r["kind"] for r in rows))}
    return rows, stats


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    new, stats = build(load_epa(), json.loads(RESEARCH.read_text()))
    others = [r for r in dis if r.get("state") != "HI"]
    taken = {p for r in others for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])] if p}
    clash = sorted(p for r in new for p in r["npdes_permits"] if p in taken)
    if clash:
        raise SystemExit(f"permits already held by another state's row: {clash}")
    ids = Counter(r["id"] for r in others + new)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup}")
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(others + new, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
