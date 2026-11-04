"""Michigan operator rows for data/dischargers.json: one row per operator, every permit in exactly one row.

Usage (after pipeline/ingest/mi_egle_mienviro.py has written its events file):
    pipeline/.venv/bin/python -I scripts/add_mi_operators.py [--dry-run]

Inputs
  - research/mi/dischargers.json: the CSO permittees of EPA's inventory and the SSO reporters the research saw on
    EGLE's list (71 rows). Each becomes a row under its research id, its name the permittee's (EPA ICIS-NPDES
    permit_name, else the responsible party EGLE's list names most often for the permit) with the facility in
    brackets. Two research rows carry a mistyped permit (MI10025585, MI10021083: an extra digit of MI0025585 and
    MI0021083) and are folded into the rows of the real permits. Four permits EPA's CSO inventory lists are general
    permits for petroleum or remediation sites, not sewer systems (NOT_SEWER): kind "cso_closed_or_none".
  - data/outfalls-plants-us.json: EPA ICIS-NPDES treatment-plant permits for Michigan (440). permit_name is the owner;
    permits of one owner are one row. A plant add_federal_operators.private_reason flags is kept when its owner reads
    as a public body by name, else it waits for the private-utilities pass below.
  - data/build/events/mi-egle-mienviro-cso-sso-list.json: every permit EGLE's list names (Part 31 sewer-system numbers
    3112a-nnnn, general permits MIG..., groundwater permits GW..., NPDES permits), each with the responsible party the
    list names most often for it (a party the ingester removed as a person's name is never used). A permit no row
    holds joins the row whose owner key it shares, else gets its own row.
  - research/mi/private-utilities-candidates.json (EPA's private sewage permits): PRIVATE below files each with the
    permittee as EPA ICIS-NPDES records it (EGLE's permit documents sit behind the MiEnviro login and were not read),
    legal_form from the controlled list, and never an individual's name.

Rules
  - Owner key (key()): lower case, punctuation dropped, "city of" / ", city of" dropped, "twp" and "charter township"
    read as "township", "co" as "county", trailing works words (WWTP, WRRF, wastewater treatment plant, DPW ...)
    dropped. A township and the city of the same name are two operators.
  - legal_form (form()) from the name, on the controlled list (docs/legal-forms.md); null when the name does not say
    (a bare place name).
  - notification_channel: the statutory notice and EGLE's posting (MCL 324.3112a(1)-(2)); CSO rows add the 4-hour
    Great Lakes notice (40 CFR 122.38). notification_signup_url null: EGLE offers no overflow e-mail list.
  - Idempotent: a permit already in any row is not added again; rows already written are left as they are. New rows go
    after the last Michigan row (the state's block stays together).
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "pipeline"))
from add_federal_operators import private_reason, title  # noqa: E402

TODAY = date.today().isoformat()
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "mi" / "dischargers.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
EVENTS = ROOT / "data" / "build" / "events" / "mi-egle-mienviro-cso-sso-list.json"
LIST_URL = "https://mienviro.michigan.gov/ncore/external/overflow/list"
LAW = ("Notice to EGLE, the local health departments and a daily newspaper immediately and not more than 24 hours "
       "after the discharge begins, and a report at its end (MCL 324.3112a(1)); EGLE posts each notice on the MiEnviro "
       f"CSO/SSO List (MCL 324.3112a(2)): {LIST_URL}. The operator's own pages were not searched individually.")
LAW_CSO = ("Notice to EGLE, the local health departments and a daily newspaper within 24 hours (MCL 324.3112a(1)); "
           f"EGLE posts each notice on the MiEnviro CSO/SSO List (MCL 324.3112a(2)): {LIST_URL}. As a Great Lakes CSO "
           "permittee it also owes public notice within 4 hours of becoming aware of a discharge under its public "
           "notification plan (40 CFR 122.38); the plan read (GLWA's) gives that notice through the same list. The "
           "operator's own pages were not searched individually.")
SHORT = {"mi-glwa-wrrf-mi0022802": "Great Lakes Water Authority (GLWA)"}
TYPO_PERMITS = {"MI10025585": "MI0025585", "MI10021083": "MI0021083"}
NOT_SEWER = {"MIG081156": "Enbridge Line 6B (Marshall): a general permit for petroleum and remediation discharges",
             "MIG081159": "Enbridge Energy (St. Ignace): a general permit for petroleum and remediation discharges",
             "MIG081161": "MRP Properties (Mt. Pleasant): a general permit for petroleum and remediation discharges",
             "MIG081165": "Speedway 8860 (Sterling Heights): a general permit for petroleum and remediation discharges"}
# EPA's private sewage permits for Michigan (research/mi/private-utilities-candidates.json): permit -> (name, legal_form,
# towns, note). The permittee is as EPA ICIS-NPDES records it; no individual is named.
PRIVATE = {
    "MI0029360": ("Holy Cross Children's Services (The Hive Project WWTP)", "institution", ["Clinton"],
                  "A children's services agency's treatment plant (EPA SIC 8211)."),
    "MI0056723": ("West Michigan Development Company (Saddle Ridge Condominium, Algoma)", "business or industrial",
                  ["Algoma Township"], "EPA records a development company as permittee for the condominium's plant."),
    "MI0060249": ("Orchard View of Saline Water and Wastewater Treatment Authority LLC (Faust Acres)",
                  "investor-owned utility", ["Saline"],
                  "A limited liability company despite the word Authority in its name: a private utility."),
    "MI0043974": ("Private sewage system near Saline (permit MI0043974)", "facility (permittee not named)", ["Saline"],
                  "EPA's permittee and facility names read as an individual's: not named here."),
}
HELD = {"MI0060329": "RACER Trust Coldwater Road Facility: an environmental response trust's site; whether the permit "
                     "has a sanitary outfall to public water was not checked (EGLE's documents need a login)"}
PUBLIC_WORDS = re.compile(r"\b(city|village|township|twp|county|authority|district|commission|commissioner|board of "
                          r"public|department|state|university|tribe|band|indian|public works|dpw|bpw|bpu|sda|"
                          r"s&wa|swa|utilities authority)\b", re.I)
WORKS = (r"(wastewater treatment plant|waste water treatment plant|wastewater treatment facility|water resource "
         r"recovery facility|wastewater plant|wwtp|wwtf|wrrf|wrf|wwsl|stp|potw|dpw|cm|wastewater division|"
         r"wastewater|collection system)")


def key(name) -> str | None:
    s = re.sub(r"\([^)]*\)", " ", (name or "").lower()).replace("&", " and ")
    s = re.sub(r"water resources? commission(er)?('?s)?( office)?|water resource commissioner('?s)?( office)?", " wrc ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(the|of|mi|michigan|office)\b", " ", s)
    s = re.sub(r"\bcharter township\b|\bcharter twp\b|\btwp\b|\btownhip\b|\btownship\b", " township ", s)
    s = re.sub(r"\bc o\b.*$", " ", s)                       # "c/o <someone>"
    s = re.sub(r"\b(inc|incorporated|llc|l l c|ltd|lp|limited partnership|operating|corp|corporation)\b", " ", s)
    s = re.sub(r"\bco\b", " county ", s)
    s = re.sub(r"\bcity\b", " ", s)
    s = " ".join(s.split())
    for _ in range(3):
        s = re.sub(rf"\s+{WORKS}$", "", s).strip()
    s = re.sub(r"^township (.+)$", r"\1 township", s)
    return s or None


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def form(name: str) -> str | None:
    n = (name or "").lower()
    if re.search(r"\b(band|indians?|tribe|tribal|reservation|hannahville|odanaang)\b", n):
        return "tribal"
    if re.search(r"\b(national park|forest service|u\.?s\.? |united states|veterans affairs|air force|coast guard)\b", n):
        return "federal facility"
    if re.search(r"\b(state park|correctional|mdoc|department of (transportation|corrections|natural resources)|mdot|"
                 r"dnr|national guard|miarng|university of michigan|michigan state university|western michigan "
                 r"university|wayne state university)\b", n):
        return "state facility"
    if re.search(r"\b(drainage district|drain drainage|sanitary district|metropolitan district|improvement district|"
                 r"school district|public schools|community schools|area schools|schools)\b", n):
        return "special district"
    if re.search(r"\b(authority|sda|s&wa|swa|wsa|sewer and water|sewage disposal)\b", n) and not re.search(r"\bllc\b", n):
        return "authority"
    if re.search(r"\bcounty\b|\bdrain commission|\bwater resources? commission|\bwrc\b", n):
        return "county"
    if re.search(r"\b(township|twp|village of|, village of|village$)\b", n) and not re.search(r"\b(llc|inc|mhc|mhp)\b", n):
        return "town"
    if re.search(r"\bcity\b|\bboard of public (works|utilities)\b|\bbpw\b|\bbpu\b|water and sewerage department", n):
        return "city"
    if re.search(r"\b(condominium|condo|owners'? association|homeowners)\b", n):
        return "homeowners' association"
    if re.search(r"\b(mhp|mhc|mobile home|manufactured|sun communities|havenpark|rhp properties|kingsley)\b", n):
        return "mobile-home park"
    if re.search(r"\b(campground|resort|rv park|outdoor adventures)\b", n):
        return "campground or resort"
    if re.search(r"\b(country club|golf)\b", n):
        return "private club"
    if re.search(r"\b(llc|l\.l\.c|inc|ltd|corp|corporation|company|companies|co\.|associates|partnership|motors|"
                 r"steel|chemical|energy|gypsum)\b", n):
        return "business or industrial"
    return None


def clean_name(name: str | None) -> str | None:
    """A party name without a care-of line ("Sun Communities, Inc., c/o <officer>") or EPA's "(Unknown Permittee)"."""
    if not name:
        return name
    s = re.sub(r",?\s*c/o\b.*$", "", name, flags=re.I).strip(" ,")
    return None if re.fullmatch(r"\(?unknown permittee\)?", s, re.I) else s


def norm_permit(p):
    from ingest.mi_egle_mienviro import norm_permit as n
    return n(p) or (str(p).strip().upper() if p else None)


def permit_set(row) -> set[str]:
    return {str(p).strip().upper() for p in [row.get("npdes_permit"), *(row.get("npdes_permits") or [])] if p}


def feed_permits() -> tuple[dict[str, Counter], dict[str, Counter], dict[str, Counter], dict[str, Counter]]:
    """permit -> Counter of responsible parties, of site names, of receiving waters, of counties (EGLE's list)."""
    party, site, water, county = (defaultdict(Counter) for _ in range(4))
    if not EVENTS.exists():
        return party, site, water, county
    for r in json.loads(EVENTS.read_text()).get("records", []):
        p = r.get("npdes_permit")
        raw = r.get("raw") or {}
        if not p:
            continue
        name = r.get("discharger_name")
        if name and name != "[name removed]":
            party[p][name] += 1
        else:
            party[p]["[name removed]"] += 1
        if raw.get("siteName") and raw["siteName"] != "[name removed]":
            site[p][raw["siteName"]] += 1
        if r.get("waterbody_text") and raw.get("reached_water"):
            water[p][r["waterbody_text"]] += 1
        if raw.get("countyDescription"):
            county[p][raw["countyDescription"]] += 1
    return party, site, water, county


def plants() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "MI" and r.get("npdes_permit"):
            out[r["npdes_permit"].upper()].append(r)
    return out


def best(c: Counter) -> str | None:
    """The most common name, preferring one that says what body it is ("City of Lansing" over "Lansing")."""
    if not c:
        return None
    names = [clean_name(n) for n, _ in c.most_common() if n != "[name removed]" and clean_name(n)]
    c = Counter({clean_name(n): v for n, v in c.items() if n != "[name removed]" and clean_name(n)})
    if not names:
        return None
    top = c[names[0]]
    bodies = [n for n in names if PUBLIC_WORDS.search(n) and c[n] * 4 >= top]
    return bodies[0] if bodies else names[0]


def base_row(rid, name, kind, permits, towns, waters, notes, legal_form=None, short=None, outfalls_source=None,
             outfall_count=None, verified="inferred"):
    return {"id": rid, "name": name, "short_name": short or name, "legal_form": legal_form, "state": "MI",
            "kind": kind, "npdes_permit": permits[0] if permits else None, "npdes_permits": list(permits),
            "receiving_waters": waters, "water_slugs": [], "outfall_count": outfall_count,
            "outfalls_source": outfalls_source,
            "notification_channel": LAW_CSO if kind == "cso" else LAW,
            "notification_feed_machine_readable": True, "notification_signup_url": None,
            "towns": towns, "notes": notes, "verified": verified, "checked": TODAY, "aliases": [rid],
            "source_areas": ["mi"]}


def main(argv) -> int:
    dry = "--dry-run" in argv
    dis = json.loads(DIS.read_text())
    have_ids = {d["id"] for d in dis}
    held = set().union(*(permit_set(d) for d in dis))
    party, site, water, county = feed_permits()
    pl = plants()
    new: list[dict] = []
    by_key: dict[str, dict] = {}
    by_permit: dict[str, dict] = {}
    counts = Counter()

    def add(row):
        new.append(row)
        have_ids.add(row["id"])
        for p in row["npdes_permits"]:
            by_permit[p.upper()] = row
            held.add(p.upper())

    def owner_of(p) -> tuple[str | None, str]:
        rows = pl.get(p) or []
        if rows and rows[0].get("permit_name"):
            return clean_name(rows[0]["permit_name"]), "EPA ICIS-NPDES permit name"
        b = best(party.get(p) or Counter())
        return b, "the responsible party EGLE's CSO/SSO List names for the permit"

    # 1. research rows
    research_keys: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(RESEARCH.read_text()):
        p = (r.get("npdes_permit") or "").upper() or None
        p = norm_permit(p) if p and p.startswith("3112") else p
        if p in TYPO_PERMITS:
            counts["research typo permit folded"] += 1
            continue
        if r["id"] in have_ids or (p and p in held):
            counts["research row already held"] += 1
            continue
        perms = [p] + [t for t, real in TYPO_PERMITS.items() if real == p] if p else []
        owner, basis = owner_of(p) if p else (None, "")
        fac = r["name"]
        name = f"{owner} ({fac})" if owner and key(owner) != key(fac) and owner.lower() != fac.lower() else (owner or fac)
        kind = r.get("kind") or "cso"
        notes = []
        if p in NOT_SEWER:
            kind = "cso_closed_or_none"
            notes.append(f"EPA's CSO inventory lists this permit, but it is {NOT_SEWER[p]}, not a sewer system.")
        if owner:
            notes.append(f"Permittee from {basis}; facility as EPA's CSO inventory names it.")
        if len(perms) > 1:
            notes.append(f"The research also listed {', '.join(perms[1:])}, a mistyped copy of {p} (an extra digit).")
        if r.get("notes"):
            notes.append(r["notes"])
        rw = r.get("receiving_waters") or [w for w, _ in (water.get(p) or Counter()).most_common(6)]
        row = base_row(r["id"], name, kind, perms, r.get("towns") or [], rw, " ".join(notes),
                       legal_form=form(owner or fac), short=SHORT.get(r["id"]) or owner or fac,
                       outfalls_source=r.get("outfalls_source"), outfall_count=r.get("outfall_count"),
                       verified=r.get("verified") or "inferred")
        if p is None:
            row["npdes_permit"], row["npdes_permits"] = None, []
        add(row)
        k = key(owner or fac)
        if k and kind != "cso_closed_or_none":
            research_keys[k].append(row)
        counts["research"] += 1
    # an owner with several research rows: its one collection-system (SSO) row takes the owner's other permits
    # (Oakland County's), else none does (Wayne County's CSO permits)
    for k, rows_k in research_keys.items():
        sso = [x for x in rows_k if x["kind"] != "cso"]
        if len(rows_k) == 1 or len(sso) == 1:
            by_key[k] = rows_k[0] if len(rows_k) == 1 else sso[0]

    # 2. EPA plant permits, grouped by owner
    groups: dict[str, list[str]] = defaultdict(list)
    for p, rows in sorted(pl.items()):
        if p in held:
            continue
        owner = clean_name(rows[0].get("permit_name")) or rows[0].get("permittee")
        if p in PRIVATE or p in HELD:
            continue
        why = private_reason(p, {"rows": rows, "files": {"plants"}})
        if why and not PUBLIC_WORDS.search(owner or ""):
            counts["plant private, waits for the private pass"] += 1
            continue
        groups[key(owner) or p].append(p)
    for k, perms in groups.items():
        rows = [r for p in perms for r in pl[p]]
        owner = clean_name(rows[0].get("permit_name")) or rows[0].get("permittee")
        if k in by_key:
            row = by_key[k]
            row["npdes_permits"] += perms
            row["npdes_permit"] = row["npdes_permit"] or perms[0]
            for p in perms:
                by_permit[p] = row
                held.add(p)
            counts["plant permits joined to a row"] += len(perms)
            continue
        rid = f"mi-{slug(k)}"
        if rid in have_ids:
            rid = f"mi-{slug(k)}-{perms[0].lower()}"
        towns = sorted({title(r.get("city")) for r in rows if r.get("city")})
        waters = list(dict.fromkeys(r["receiving_water_echo"] for r in rows if r.get("receiving_water_echo")))[:8]
        facs = ", ".join(sorted({f"{r.get('permittee')} ({r['npdes_permit']})" for r in rows}))
        notes = (f"Permittee as EPA ICIS-NPDES names it ({owner}); plants: {facs}. Added from data/outfalls-plants-us.json "
                 "(scripts/add_mi_operators.py); no contact or notification channel researched beyond the statute.")
        row = base_row(rid, owner, "plant", perms, towns, waters, notes, legal_form=form(owner),
                       outfalls_source=f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, {len(rows)} rows)",
                       outfall_count=len(rows), verified="fetched")
        add(row)
        by_key[k] = row
        counts["plant rows"] += 1

    # 3. permits on EGLE's list no row holds
    for p in sorted(party):
        P = p.upper()
        if P in held or p in PRIVATE or P in HELD:
            continue
        owner = best(party[p])
        if owner is None:                      # the list names a person as the responsible party
            fac = best(site[p]) or f"Sewage system (permit {p})"
            rid = f"mi-{slug(p)}"
            row = base_row(rid, fac, "sso" if p.startswith("3112a") else "plant", [p],
                           [], [w for w, _ in water[p].most_common(4)],
                           "EGLE's list names an individual as the responsible party: not named here; the row names "
                           "the site. (scripts/add_mi_operators.py)", legal_form="facility (permittee not named)")
            add(row)
            counts["list permits, permittee not named"] += 1
            continue
        k = key(owner) or p
        if k in by_key:
            row = by_key[k]
            row["npdes_permits"].append(p)
            row["npdes_permit"] = row["npdes_permit"] or p
            by_permit[P] = row
            held.add(P)
            counts["list permits joined to a row"] += 1
            continue
        rid = f"mi-{slug(k)}"
        if rid in have_ids:
            rid = f"mi-{slug(k)}-{slug(p)}"
        kind = "sso" if p.startswith("3112a") else "plant"
        cty = county[p].most_common(1)[0][0] + " County" if county[p] else None
        sites = ", ".join(n for n, _ in site[p].most_common(3))
        notes = (f"From EGLE's MiEnviro CSO/SSO List: the responsible party it names for permit {p} ({owner})"
                 + (f", site {sites}" if sites else "") + (f", {cty}" if cty else "") +
                 ". Added by scripts/add_mi_operators.py; no contact or notification channel researched beyond the "
                 "statute.")
        towns = [title(re.sub(r"(?i)^(city|village|charter township|township) of ", "", owner))] \
            if form(owner) in ("city", "town") else []
        row = base_row(rid, owner, kind, [p], towns, [w for w, _ in water[p].most_common(6)], notes,
                       legal_form=form(owner), verified="fetched")
        add(row)
        by_key[k] = row
        counts["list rows"] += 1

    # 4. private sewage permits (candidates file)
    for p, (name, lf, towns, note) in PRIVATE.items():
        if p in held:
            continue
        rows = pl.get(p) or []
        rid = f"mi-{p.lower()}" if lf == "facility (permittee not named)" else f"mi-{slug(name.split(' (')[0])}"
        waters = [] if lf == "facility (permittee not named)" else \
            list(dict.fromkeys(r["receiving_water_echo"] for r in rows if r.get("receiving_water_echo")))
        row = base_row(rid, name, "plant", [p], towns, waters,
                       note + " Privately owned; covered like any other operator: MCL 324.3112a binds the person "
                       "responsible for any sewer system that discharges untreated or partially treated sewage. "
                       "Permittee as EPA ICIS-NPDES records it (research/mi/private-utilities-candidates.json); "
                       "EGLE's permit documents need a MiEnviro login and were not read.",
                       legal_form=lf, verified=False)
        add(row)
        counts["private rows"] += 1

    for r in new:
        r["npdes_permits"] = list(dict.fromkeys(r["npdes_permits"]))
        if not r["npdes_permit"] and r["npdes_permits"]:
            r["npdes_permit"] = r["npdes_permits"][0]
    last = max((i for i, d in enumerate(dis) if d.get("state") == "MI"), default=len(dis) - 1)
    out = dis[:last + 1] + new + dis[last + 1:]
    print(json.dumps(dict(counts), indent=1), f"\nnew rows {len(new)}; held for a person: {sorted(HELD)}")
    print("legal_form:", dict(Counter(r.get("legal_form") for r in new)))
    if not dry:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
