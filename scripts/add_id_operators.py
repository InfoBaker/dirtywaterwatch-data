"""Idaho operator rows for data/dischargers.json: one row per operator, every Idaho permit of the outfall registry and
every private sewage permit of the research candidates in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_id_operators.py [--dry-run]

Inputs
  - data/outfalls-plants-us.json: every Idaho sewage plant permit EPA lists (121; no Idaho combined sewer permit in
    EPA's CSO inventory). permit_name is the owner as EPA records it; one owner's permits are one row.
  - research/id/dischargers.json (12 rows): each research id stays as an alias of the row that holds its permit.
  - research/id/private-utilities-candidates.json (5 private permits; three are not in the plant list): PRIVATE gives
    each its body and legal_form (docs/legal-forms.md), never an individual's name.
  - data/reference/id-permit-authority.json (scripts/id_permit_authority.py): who issues each permit. Idaho DEQ (IPDES)
    for the 104 on its issued-permits list; EPA Region 10 for the 13 whose plants lie on the Nez Perce or Coeur d'Alene
    Reservation; 4 not confirmed.
Rules
  - legal_form: "City of X" -> city; a sewer, water and sewer, or recreational district, or a regional sewer board ->
    special district (Idaho Code Title 42 chapter 32 and Title 50; read from the name); the state's correctional
    institution -> state facility; the Nez Perce Tribe -> tribal; PRIVATE by hand.
  - notification_channel: the permit's 24-hour and five-day noncompliance reports go to its issuer (DEQ under the
    IPDES permit conditions, IDAPA 58.01.25; EPA Region 10 in Indian country); DEQ publishes no list of them and EPA's
    overflow tables hold one Idaho report (2023), so no Idaho sewage report is public; no duty to tell the public was
    found. notification_signup_url null.
  - kind plant (no Idaho combined sewer permit).
  - Idempotent: every row with state ID is rebuilt; Idaho's rows go after the other states'.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_sd_operators import municipal, slug, tidy, title, town  # noqa: E402

DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "id" / "dischargers.json"
CANDIDATES = ROOT / "research" / "id" / "private-utilities-candidates.json"
AUTH = ROOT / "data" / "reference" / "id-permit-authority.json"
CHECKED = "2026-11-14"
DEQ_LAW = ("Idaho DEQ issues this permit (IPDES). Its conditions require noncompliance that may endanger health, "
           "collection-system overflows included, to be reported to DEQ by telephone within 24 hours and in writing "
           "within five days; DEQ publishes no list of these reports, and EPA's overflow tables hold one Idaho report "
           "(December 2023), so the reports are not public. No duty to tell the public was found.")
EPA_LAW = ("EPA Region 10 issues this permit: the plant lies on the {where}, in Indian country, where EPA keeps "
           "permitting. The 24-hour and five-day noncompliance reports go to EPA; none is public in EPA's overflow "
           "tables. No duty to tell the public was found.")
UNCONFIRMED = ("The permit is not on Idaho DEQ's list of issued IPDES permits and its plant lies outside a reservation "
               "(an expired or administratively continued permit DEQ has not listed): its issuer was not confirmed. "
               "Either way the 24-hour and five-day noncompliance reports go to the permitting authority and are not "
               "public. No duty to tell the public was found.")
OWNERS = {
    "NORTH IDAHO CORRECTIONAL INSTITUTION": ("id-north-idaho-correctional-institution",
                                             "Idaho Department of Correction, North Idaho Correctional Institution",
                                             "state facility"),
    "NEZ PERCE TRIBE WATER RESOURCES DIVISION": ("id-nez-perce-tribe", "Nez Perce Tribe (Water Resources Division)",
                                                 "tribal"),
    "HAYDEN AREA REGIONAL SEWER BOARD": ("id-hayden-harsb", "Hayden Area Regional Sewer Board", "authority"),
}
# permit -> (row id, name, legal_form, note): the private candidates
PRIVATE = {
    "ID0024422": ("id-mid-valley-sewer-company", "Mid-Valley Sewer Company LLC", "investor-owned utility",
                  "EPA records the permittee as Mid-Valley Sewer Company LLC; Idaho DEQ's list names the plant The "
                  "Meadows LLC Wastewater Treatment Plant: one system, the permittee not confirmed from the permit."),
    "ID0027979": ("id-elk-valley-subdivision", "Elk Valley Subdivision wastewater plant", None,
                  "EPA types it privately owned; who holds the permit (a homeowners' association or the developer) "
                  "was not read."),
    "ID0028029": ("id-jug-mountain-ranch", "Jug Mountain Ranch LLC", "business or industrial",
                  "A resort community's plant; EPA types it mixed ownership."),
    "ID0030015": ("id-edge-resort", "Edge Resort (Downhill, LLC)", "campground or resort", None),
    "ID0030091": ("id-avimor-water-reclamation", "Avimor Water Reclamation Facility (Puttman Infrastructure, Inc.)",
                  "business or industrial", "A planned community's plant, owned by its developer's company."),
}


def form(owner: str) -> str | None:
    n = owner.lower()
    if re.search(r"\bassociation\b", n):
        return "member-owned utility"
    if re.search(r"\bsewer\b.*\bdistrict\b|\bwater (and|&) sewer\b|\bregional sewer\b", n):
        return "special district"
    return None


def load_epa() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]:
        p = str(r.get("npdes_permit") or "").upper()
        if not p.startswith("ID"):
            continue
        o = out.setdefault(p, {"owner": r.get("permit_name") or r.get("permittee"), "facility": r.get("permittee"),
                               "city": r.get("city"), "type": r.get("facility_type"), "waters": [], "outfalls": 0})
        w = (r.get("receiving_water_echo") or "").strip()
        if w and w not in o["waters"]:
            o["waters"].append(w)
        o["outfalls"] += 1
    return out


def channel(permits: list[str], auth: dict) -> str:
    a = [auth.get(p, {"authority": "unconfirmed"}) for p in permits]
    if all(x["authority"] == "IDEQ" for x in a):
        return DEQ_LAW
    if all(x["authority"] == "EPA" for x in a):
        return EPA_LAW.format(where=a[0].get("reservation") or "a tribal government's land")
    if any(x["authority"] == "IDEQ" for x in a):
        return DEQ_LAW + " One of its permits' issuers was not confirmed."
    return UNCONFIRMED


def build(epa: dict, research: list[dict], cand: list[dict], auth: dict) -> tuple[list[dict], dict]:
    alias = {r["npdes_permit"]: r["id"] for r in research if r.get("npdes_permit")}
    cmap = {c["npdes_permit"]: c for c in cand}
    groups: dict[str, list[str]] = defaultdict(list)
    meta: dict[str, tuple] = {}
    for p in sorted(set(epa) | set(PRIVATE)):
        o = epa.get(p) or {"owner": cmap[p]["permittee_as_recorded"], "facility": cmap[p]["facility"],
                           "city": cmap[p]["city"], "type": cmap[p]["ownership"]["facility_type"], "waters": [],
                           "outfalls": 0}
        epa.setdefault(p, o)
        owner = o["owner"] or o["facility"] or p
        if p in PRIVATE:
            rid, name, lf, note = PRIVATE[p]
        elif owner.upper() in OWNERS:
            (rid, name, lf), note = OWNERS[owner.upper()], None
        else:
            mm = municipal(re.sub(r"\s+-\s+.*$", "", owner))
            if mm:
                rid, name, lf = f"id-{slug(tidy(mm[1]))}", tidy(f"{mm[0]} of {mm[1]}"), mm[0].lower()
            else:
                base = re.sub(r"\s*\(.*?\)|\s+-\s+.*$", "", owner)
                rid, name, lf = f"id-{slug(base)}", tidy(title(base)).replace("Coeur D Alene", "Coeur d'Alene"), form(owner)
            note = None
        groups[rid].append(p)
        meta.setdefault(rid, (name, lf, note))
    rows = []
    for rid, permits in sorted(groups.items()):
        name, lf, why = meta[rid]
        e = [epa[p] for p in permits]
        n_out = sum(x["outfalls"] for x in e)
        a = [auth.get(p, {"authority": "unconfirmed", "basis": "not in the plant list"}) for p in permits]
        note = (f"EPA ECHO ICIS-NPDES: {'; '.join(f'{p} {epa[p]['facility']}' for p in permits)}. Owner as EPA records "
                f"it: {'; '.join(sorted({str(x['owner']) for x in e}))}; facility type "
                f"{'; '.join(sorted({str(x['type']) for x in e}))}. Permitting authority: "
                + "; ".join(f"{p} {x['authority']} ({x['basis']})" for p, x in zip(permits, a)) + "."
                + (f" {why}" if why else "") + (" Legal form read from the name." if lf not in (None, "city") else ""))
        if lf in ("investor-owned utility", "business or industrial", "campground or resort") or rid in (
                "id-elk-valley-subdivision",):
            note = "Privately owned. " + note
        aliases = [rid] + [alias[p] for p in permits if p in alias and alias[p] != rid]
        row = {"id": rid, "name": name, "state": "ID", "kind": "plant", "npdes_permit": permits[0],
               "npdes_permits": permits, "receiving_waters": list(dict.fromkeys(w for x in e for w in x["waters"])),
               "water_slugs": [], "outfall_count": n_out or None,
               "outfalls_source": ("EPA ECHO ICIS-NPDES discharge points (data/outfalls-plants-us.json: "
                                   f"{n_out} rows for these permits)") if n_out else None,
               "notification_channel": channel(permits, auth), "notification_feed_machine_readable": False,
               "notification_signup_url": None, "towns": sorted({t for x in e if (t := town(x["city"]))}),
               "notes": note, "verified": "fetched", "checked": CHECKED, "aliases": aliases,
               "source_areas": ["id", "federal"], "permitting_authority": sorted({x["authority"] for x in a})}
        if lf:
            row["legal_form"] = lf
        rows.append(row)
    stats = {"rows": len(rows), "permits": sum(len(r["npdes_permits"]) for r in rows),
             "by_form": dict(Counter(r.get("legal_form") for r in rows)),
             "by_authority": dict(Counter("/".join(r["permitting_authority"]) for r in rows))}
    return rows, stats


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    epa = load_epa()
    cand = json.loads(CANDIDATES.read_text())["candidates"]
    missing = sorted(c["npdes_permit"] for c in cand if c["npdes_permit"] not in PRIVATE)
    if missing:
        raise SystemExit(f"private candidates without a PRIVATE row: {missing}")
    new, stats = build(epa, json.loads(RESEARCH.read_text()), cand, json.loads(AUTH.read_text())["permits"])
    others = [r for r in dis if r.get("state") != "ID"]
    taken = {p for r in others for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])] if p}
    clash = sorted(p for r in new for p in r["npdes_permits"] if p in taken)
    if clash:
        raise SystemExit(f"permits already held by another state's row: {clash}")
    ids = Counter(r["id"] for r in others + new)
    if [i for i, n in ids.items() if n > 1]:
        raise SystemExit(f"duplicate ids: {[i for i, n in ids.items() if n > 1]}")
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(others + new, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
