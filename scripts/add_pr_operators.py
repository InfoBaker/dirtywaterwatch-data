"""Puerto Rico operator rows for data/dischargers.json: one row per operator, every Puerto Rico permit in exactly one row.

Usage (with EPA's current overflow ZIP saved at data/raw/echo-sewer-overflow/current.zip, and after
pipeline/ingest/echo_sewer_overflow_events.py has written its events file):
    pipeline/.venv/bin/python -I scripts/add_pr_operators.py [--dry-run]

Inputs
  1. data/outfalls-plants-us.json: EPA ICIS-NPDES's sewage permits in Puerto Rico (54 permits, 57 discharge points; EPA
     Region 2 writes every permit): 53 of the Puerto Rico Aqueduct and Sewer Authority (PRASA, Autoridad de Acueductos
     y Alcantarillados de Puerto Rico) and one EPA types municipal (Villas del Gigante, Carolina).
  2. data/outfalls-us.json: EPA's national CSO inventory: PRASA's Puerto Nuevo permit PR0021555 (12 outfalls).
  3. EPA's collection-system table in the saved ZIP (collection_system_permits.csv): 61 Puerto Rico permits; nine hold
     no plant in the plants file (a state agency's, two municipalities', six private systems).
  4. research/pr/dischargers.json (the row pr-prasa) and research/pr/private-utilities-candidates.json (3 private
     permits). The facility names of the nine are EPA ECHO's (cwa_rest_services.get_facility_info, read 2026-11-14).
Rules
  - OWNERS gives each permit outside PRASA its row, named from the permittee as EPA records it (never a person), with
    legal_form from docs/legal-forms.md; a body whose form was not read keeps null. Every PRASA permit (permittee "PRASA
    ...") is in the row pr-prasa (legal form "authority": a public corporation created by law, Ley Núm. 40 de 1 de mayo
    de 1945).
  - kind: "cso" for PRASA (its Puerto Nuevo permit holds the island's combined sewer outfalls); "sso" when a permit of
    the row has a collection system in EPA's table or a report in EPA's overflow tables; otherwise "plant".
  - notification_channel: the permits' federal 24-hour and five-day reports to EPA Region 2 (40 CFR 122.41(l)(6)),
    filed through NeT-SewerOverflow and published in EPA's overflow tables; no Puerto Rico statute requiring the public
    to be told was found; PRASA's Puerto Nuevo permit and its consent decree add a public notification duty for
    combined sewer overflows, with no event posting found.
  - Idempotent: a rerun replaces the rows it wrote (state PR, source_areas ["pr"]) where they stood; on a first run
    they go after the last row of the file.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
CSO = ROOT / "data" / "outfalls-us.json"
RESEARCH = ROOT / "research" / "pr" / "dischargers.json"
CANDIDATES = ROOT / "research" / "pr" / "private-utilities-candidates.json"
EVENTS = ROOT / "data" / "build" / "events" / "echo-sewer-overflow.json"
ZIP = ROOT / "data" / "raw" / "echo-sewer-overflow" / "current.zip"
CHECKED = "2026-11-14"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
LAW = ("EPA Region 2 issues the permit; its conditions require the 24-hour oral and five-day written report of an "
       "overflow, bypass or other noncompliance that may endanger health or the environment to EPA (40 CFR "
       "122.41(l)(6)), filed electronically through NeT-SewerOverflow and published in EPA's overflow tables "
       f"({ECHO}). No Puerto Rico statute or rule requiring the public to be told of a sewage discharge was found.")
PRASA_NOTE = (" PRASA's Puerto Nuevo permit (PR0021555, 2021) requires a public notification process for combined "
              "sewer overflows, and the 2023 modification of its consent decree (United States v. PRASA, No. "
              "3:15-cv-02283, D.P.R.) adds posting of the Puerto Nuevo overflows and their estimated volume on PRASA's "
              "website; PRASA's pages show the outfall locations, precautions and a form to report an overflow, and "
              "no overflow events were found posted there.")
PRIVATE_NOTE = " The permit binds a private permittee as it binds a public one."
OWN = " The operator's own pages were not searched individually."
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}

PRASA = ("pr-prasa", "Autoridad de Acueductos y Alcantarillados de Puerto Rico (PRASA)", "PRASA", "authority",
         "The island's public water and sewer authority: every PRASA plant, its collection systems and the Puerto "
         "Nuevo combined sewer system (San Juan), under one consent decree (United States v. PRASA, No. "
         "3:15-cv-02283, D.P.R., 2016, modified 2023).")
# permit -> (row id, name, short name, legal form, note) for the permits that are not PRASA's
OWNERS = {
    "PR0026042": ("pr-villas-del-gigante-plant", "Villas del Gigante wastewater plant (Carolina)",
                  "Villas del Gigante plant", None,
                  "EPA records the permittee as the facility (\"VILLAS DEL GIGANTE, CAROLINA\") and types it "
                  "\"Municipal or Water District\"; the owner was not read."),
    "PR0021326": ("pr-drna-cabo-rojo", "Departamento de Recursos Naturales y Ambientales (DRNA), Cabo Rojo facility",
                  "DRNA (Cabo Rojo)", "state facility",
                  "EPA's collection-system table types the owner State Government; the facility was not read."),
    "PR0025925": ("pr-centro-vacacional-maricao", "Centro Vacacional (Maricao)", "Centro Vacacional, Maricao",
                  "state facility",
                  "EPA's collection-system table types the owner State Government; the agency that runs it was not "
                  "read."),
    "PR0025917": ("pr-balneario-cana-gorda", "Balneario de Caña Gorda (Guánica)", "Balneario de Caña Gorda", None,
                  "EPA records the facility as \"BALNEARIO DE CANA GORDA\" and its collection-system table types the "
                  "owner Municipality; the owner was not read."),
    "PR0023396": ("pr-mayaguez-public-works", "Municipio de Mayagüez, Municipal Public Works", "Mayagüez Public Works",
                  "city", "EPA records the facility as \"MUNICIPAL PUBLIC WORKS\" (Mayagüez), owner type Municipality."),
    "PR0024333": ("pr-casa-castaner", "Casa Castañer, Inc. (Lares)", "Casa Castañer", "business or industrial", None),
    "PR0025283": ("pr-castaner-general-hospital", "Castañer General Hospital (Lares)", "Castañer General Hospital",
                  "institution", "EPA records the facility as \"CASTANER GENERAL\"; its collection-system table calls "
                  "it a hospital system."),
    "PR0021539": ("pr-isleta-marina", "Isleta Marina, Inc. (Fajardo)", "Isleta Marina", "campground or resort", None),
    "PR0026310": ("pr-consejo-condominios-costeros", "Consejo de Condominios Costeros, Inc. (Río Grande)",
                  "Consejo de Condominios Costeros", "homeowners' association",
                  "A council of coastal condominiums in Río Grande."),
    "PR0026425": ("pr-coco-beach-utility", "Coco Beach Utility Company, Inc. (Río Grande)", "Coco Beach Utility",
                  "investor-owned utility", None),
}
TOWNS = {"PR0021326": "Cabo Rojo", "PR0025925": "Maricao", "PR0025917": "Guánica", "PR0023396": "Mayagüez",
         "PR0024333": "Lares", "PR0025283": "Lares", "PR0021539": "Fajardo", "PR0026310": "Río Grande",
         "PR0026425": "Río Grande"}


def smart_title(s: str) -> str:
    return " ".join(w.title() if w.isupper() or w.islower() else w for w in (s or "").split())


def plants() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "PR" and r.get("npdes_permit"):
            out[r["npdes_permit"].upper()].append(r)
    return out


def csos() -> dict[str, list[dict]]:
    doc = json.loads(CSO.read_text())
    out: dict[str, list[dict]] = defaultdict(list)
    for r in doc["outfalls"] if isinstance(doc, dict) else doc:
        if str(r.get("npdes_permit") or "").startswith("PR"):
            out[r["npdes_permit"]].append(r)
    return out


def systems() -> dict[str, dict]:
    sys.path.insert(0, str(ROOT / "pipeline"))
    from ingest import echo_sewer_overflow_events as E
    tables, _ = E.read_zip(ZIP)
    return {s["permit_identifier"]: s for s in tables.get("systems", []) if s["permit_identifier"].startswith("PR")}


def epa_reports() -> Counter:
    n = Counter()
    for r in json.loads(EVENTS.read_text()).get("records", []):
        if str(r.get("npdes_permit") or "").startswith("PR"):
            n[r["npdes_permit"]] += 1
    return n


def owner(p: str, pl: dict, cs: dict) -> tuple:
    if p in OWNERS:
        return OWNERS[p]
    names = [r.get("permittee") or "" for r in pl.get(p, []) + cs.get(p, [])]
    if names and all(n.upper().startswith("PRASA") for n in names):
        return (PRASA[0], None, None, None, None)
    raise SystemExit(f"permit without an owner: {p} {names}")


def build(dis: list[dict]) -> tuple[list[dict], dict]:
    missing = [str(p.relative_to(ROOT)) for p in (EVENTS, ZIP) if not p.exists()]
    if missing:
        raise SystemExit("save EPA's current overflow ZIP at data/raw/echo-sewer-overflow/current.zip and run "
                         "pipeline/ingest/echo_sewer_overflow_events.py first; missing: " + ", ".join(missing))
    keep = [d for d in dis if not (d.get("state") == "PR" and "pr" in (d.get("source_areas") or []))]
    pl, cs, sy, reports = plants(), csos(), systems(), epa_reports()
    research = {r["npdes_permit"].split()[0]: r for r in json.loads(RESEARCH.read_text())}
    cands = {c["npdes_permit"] for c in json.loads(CANDIDATES.read_text())["candidates"]}
    permits = sorted(set(pl) | set(cs) | set(sy) | set(reports) | cands | set(research))
    by_row: dict[str, list[str]] = defaultdict(list)
    meta = {PRASA[0]: PRASA}
    for p in permits:
        o = owner(p, pl, cs)
        by_row[o[0]].append(p)
        if o[1]:
            meta[o[0]] = o
    new = []
    for rid, ps in by_row.items():
        _, name, short, lf, note = meta[rid]
        rows = [r for p in ps for r in pl.get(p, [])]
        cso_rows = [r for p in ps for r in cs.get(p, [])]
        towns = sorted({smart_title(r["city"]) for r in rows + cso_rows if r.get("city")})
        if not towns:     # the city ECHO gives the facility (read 2026-11-14)
            towns = sorted({TOWNS[p] for p in ps if p in TOWNS})
        waters = list(dict.fromkeys(r["receiving_water_echo"].strip() for r in rows + cso_rows
                                    if r.get("receiving_water_echo")))[:10]
        parts = []
        if rows:
            parts.append(f"EPA ICIS-NPDES: {len({r['npdes_permit'] for r in rows})} plant permit(s), {len(rows)} "
                         "discharge point(s).")
        if cso_rows:
            parts.append(f"EPA's CSO inventory: {len(cso_rows)} combined sewer outfalls of {', '.join(sorted(cs))} "
                         "(Puerto Nuevo, San Juan); PRASA's own layer gives each outfall's point and receiving water.")
        sys_ps = [p for p in ps if p in sy]
        if sys_ps and rid != PRASA[0]:
            parts.append("EPA's collection-system table: " + "; ".join(
                f"{p} {sy[p]['collection_system_name'].strip()} ({sy[p]['collection_system_owner_type_desc']})"
                for p in sys_ps) + ".")
        elif sys_ps:
            parts.append(f"EPA's collection-system table: {len(sys_ps)} PRASA systems.")
        n = sum(reports[p] for p in ps)
        if n:
            parts.append(f"EPA's overflow tables (2026-11-12 extract): {n} report(s) read as reaching a water, from "
                         f"{sum(1 for p in ps if reports[p])} permit(s).")
        elif sys_ps:
            parts.append("No report under these permits is in EPA's overflow tables (2026-11-12 extract).")
        if note:
            parts.append(note)
        kind = "cso" if cso_rows else "sso" if any(p in sy or reports[p] for p in ps) else "plant"
        channel = LAW + (PRASA_NOTE if rid == PRASA[0] else (PRIVATE_NOTE if lf in PRIVATE_FORMS else "") + OWN)
        new.append({"id": rid, "name": name, "short_name": short or name, "legal_form": lf, "state": "PR",
                    "kind": kind, "npdes_permit": ps[0], "npdes_permits": list(ps),
                    "receiving_waters": waters, "water_slugs": [], "outfall_count": len(rows) + len(cso_rows) or None,
                    "outfalls_source": ("; ".join(x for x in (
                        f"EPA ICIS-NPDES discharge points (data/outfalls-plants-us.json, {len(rows)} rows)" if rows else "",
                        f"PRASA's CSO layer (data/outfalls-pr.json, {len(cso_rows)} rows)" if cso_rows else "") if x)
                        or None),
                    "notification_channel": channel, "notification_feed_machine_readable": True,
                    "notification_signup_url": None, "towns": towns or (["island-wide"] if rid == PRASA[0] else []),
                    "notes": " ".join(parts).strip(), "verified": "fetched", "checked": CHECKED,
                    "aliases": [rid], "source_areas": ["pr"]})
    new.sort(key=lambda r: (r["id"] != PRASA[0], r["id"]))
    ids = Counter(r["id"] for r in keep + new)
    dup = [i for i, k in ids.items() if k > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup}")
    stats = {"rows": len(new), "permits": sum(len(r["npdes_permits"]) for r in new),
             "prasa_permits": len(by_row[PRASA[0]]), "permits_with_reports": sum(1 for p in permits if reports[p]),
             "legal_form": dict(Counter(r.get("legal_form") for r in new)), "kind": dict(Counter(r["kind"] for r in new))}
    first = next((i for i, d in enumerate(dis) if d.get("state") == "PR" and "pr" in (d.get("source_areas") or [])), None)
    if first is None:
        return keep + new, stats
    before = sum(1 for d in dis[:first] if not (d.get("state") == "PR" and "pr" in (d.get("source_areas") or [])))
    return keep[:before] + new + keep[before:], stats


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    out, stats = build(dis)
    print(json.dumps(stats, indent=1, ensure_ascii=False))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
