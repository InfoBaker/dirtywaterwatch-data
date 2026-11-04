"""Operator rows (data/dischargers.json) for the live-state permits of the outfall registry that have none.

Usage: pipeline/.venv/bin/python -I scripts/add_federal_operators.py [--dry-run]

Owner, 2026-11-03: outfall rows with no operator page (out/outfalls.json discharger_id null). The export links an
outfall to its operator by permit (export/outfalls.py permit_index: npdes_permit, npdes_permits), so a permit with no row
in data/dischargers.json has no page. This reads every live-state row of data/outfalls-plants-us.json,
data/outfalls-mid-atlantic.json and data/outfalls-ne.json (the permits only; the outfall rows are not touched), finds the
permits no registry row holds (as npdes_permit, in npdes_permits, or as an alias) and, for each:

  - skips a private permit (the owner has not decided on private utilities): a plant row whose basis is a permit
    component POTW but whose owner type is Privately Owned Facility, Corporation or NON-POTW; a sewerage SIC/NAICS permit
    whose owner type is blank or unknown (research/federal/plant-outfalls.md section 2.8 lists the bases); and the
    CSO-inventory permits in SKIP_PRIVATE (a hydro dam, a paint plant, a power plant, a fuel terminal, a college).
    The skipped are counted per state, never added;
  - attaches the permit to an existing operator when the name says it is that operator: the permittee's name, with
    the generic words dropped (town, WWTP, WPCF, authority, ...; key()), equals the name of exactly one registry row of
    the same state, or ATTACH_BY_HAND says so (a permit the CSO inventory lists under a collection-system or
    co-permittee name). The permit goes into the row's npdes_permits (and npdes_permit when it had none) and its notes
    say so. A name that equals several rows (Groton: the town's WPCA and the city) or that is inside a name of a row
    with no permit (Ocean Pines inside Ocean City) is HELD: no row is added and no permit attached, the case is listed in
    docs/reviews/2026-11-03-federal-operators.md for a person to settle;
  - otherwise adds a row, in the registry's row shape: id "<state>-<permit>" lower case (as pa-pa0023736), name as EPA
    spells the permittee, kind "plant" (or "cso" when the permit has outfalls in a CSO file), npdes_permit(s) (several
    permits of one permittee in one town become one operator), receiving_waters as the permit names them, towns from
    EPA's city, outfall_count and outfalls_source from the registry, notification_channel "None found online (not
    searched individually)", verified "fetched", checked today, source_areas ["federal"] and notes naming the source.

Then TERMINATED_FIX: the 8 operators whose permit research/federal/plant-outfalls.md listed as terminated. EPA's
ICIS_PERMITS (data/raw/icis-npdes/2026-11-03/npdes_downloads.zip) holds one row per permit VERSION: version 0 of each is
terminated and a later version is expired (administratively continued) or effective, so the number is current; the plant
build read version 0. The row keeps its permit and gains the facility's other current permits (same FRS id) and a
sentence in its notes.

Idempotent: a permit a row holds is not added again. Writes data/dischargers.json in the registry's layout
(scripts/align-discharger-ids.py dump) and docs/reviews/2026-11-03-federal-operators.md.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from common import load_outfall_registry  # noqa: E402

TODAY = date.today().isoformat()
DIS = ROOT / "data" / "dischargers.json"
REVIEW = ROOT / "docs" / "reviews" / "2026-11-03-federal-operators.md"
LIVE = {"CT", "MA", "ME", "NH", "RI", "VT", "NJ", "NY", "PA", "MD", "VA", "DC"}
FILES = {"plants": "data/outfalls-plants-us.json", "mid-atlantic": "data/outfalls-mid-atlantic.json",
         "ne": "data/outfalls-ne.json"}
PRIVATE_TYPES = {"Privately Owned Facility", "Corporation", "NON-POTW"}
# CSO-inventory permits that are no sewer operator's (ICIS_PERMITS: facility type POF, a college)
SKIP_PRIVATE = {"MAG250958": "Rust-Oleum paint plant", "ME0001678": "Milford hydro dam", "MEU250309":
                "Southern Maine Technical College", "NY0001333": "Cayuga Operating Company power plant",
                "NY0231924": "Sunoco Syracuse terminal"}
# permit -> (operator id, why): the inventory lists the permit under a name the key() test cannot match
ATTACH_BY_HAND = {
    "RISS00024": ("ri-nbc-bucklin-point", "NBC - Bucklin Point WWCS is the Narragansett Bay Commission's collection-system permit (RI state sewer-system number)"),
    "RISS00032": ("ri-nbc-fields-point", "NBC - Field's Point WWCS is the Narragansett Bay Commission's collection-system permit (RI state sewer-system number)"),
    "RISS00031": ("ri-newport-wpcf", "City of Newport WWCS is the City of Newport Utilities' collection-system permit (RI state sewer-system number)"),
    "NY0024406": ("ny-binghamton", "Binghamton (C) CSO's is the City of Binghamton's CSO permit (the row holds its plant permit NY0024414)"),
    "NJG108740": ("nj-jmeuc", "Joint Meeting of Essex and Union Counties, listed in the CSO inventory under a general-permit number"),
    "ME0101010": ("me-gaud", "Hallowell Water District CSO: ICIS names the Greater Augusta Utility District as its owner"),
    # names the key() test held (a registry row with no permit whose name holds, or is held by, EPA's): settled by hand
    "VA0025020": ("va-wvwa", "EPA's permittee is the Western Virginia Water Authority, the row's operator (Roanoke regional plant)"),
    "VA0025143": ("va-arlington-des", "Arlington County Water Pollution Control Facility is the plant of the row's operator, Arlington County DES"),
    "VAN010021": ("va-arlington-des", "Arlington County Water Pollution Control Facility is the plant of the row's operator, Arlington County DES"),
    "PA0026271": ("pa-meadville-area-sewer-authority", "Meadville Area Sewer Authority WWTP: the row's operator (MASA)"),
    "CT0100374": ("ct-bristol-water-reclamation-fac", "Bristol Water Reclamation Facility, the row's plant"),
    "CT0100480": ("ct-rocky-hill-mdc", "Rocky Hill WPCF (MDC), the row's plant"),
    "CT0100994": ("ct-poquonock-mdc-windsor", "Poquonock WPCF (MDC Windsor), the row's plant"),
    "CT0100544": ("ct-stonington-mystic", "Mystic WPCF is the Town of Stonington's Mystic plant, the row's"),
    "CT0100749": ("ct-milford-beaverbrook", "Milford Beaverbrook WPCF; the other row of that name is its collection system"),
    "CT0101656": ("ct-milford-housatonic", "Housatonic WPCF (Milford); the other row of that name is its collection system"),
    "CT0101184": ("ct-groton-city-of", "Groton WPCA, City of: the City of Groton, not the Town of Groton's WPCF (ct-groton-town-wpca)"),
    "NY0022551": ("ny-lyons-t-poss", "Lyons (T) WWTP: the Town of Lyons, the row's operator (its publicly owned sewage system)"),
    "MD0024767": ("md-commissioners-of-leonardtown", "Leonardtown WWTP: the Commissioners of Leonardtown are the town"),
    "MD0059463": ("md-talbot-county-dpw", "Talbot County Region V WWTP: Talbot County's public works department"),
}
# held on purpose: a New Jersey CSO operator needs a row in data/notice-channels.json first (tests/test_notice_channels.py
# lists the 25 NJ CSO permits that have one); research the channel, then rerun
HOLD_BY_HAND = {"NJ0108804": "NJ CSO permit (Cliffside Park): no row in data/notice-channels.json yet",
                "NJG156582": "NJ CSO permit (Edgewater MUA): no row in data/notice-channels.json yet"}
# the name overlaps a permit-less operator's but it is another operator: a row is added (not held)
NEW_DESPITE_OVERLAP = {"MA0102253", "MAG580036", "PA0026468"}   # MCI Norfolk-Walpole (state prison); Lower Bucks County JMA
# operator id -> (permits to add, note): the 8 operators of research/federal/plant-outfalls.md section 4
TERMINATED_FIX = {
    "ct-middletown-wpcf": ([], "CT0100323"),
    "ma-greenfield-wpcf": (["MAG590014"], "MA0101214"),
    "ma-upton-wastewater-treatment-facility": (["MAG580034"], "MA0100196"),
    "ma-maynard-wastewater-treatment-facility": ([], "MA0101001"),
    "ma-medfield-wastewater-treatment-facility": (["MAG590008"], "MA0100978"),
    "ny-mayfield-v-wwtp": ([], "NY0252042"),
    "ny-heuvelton-v-wpcp": ([], "NY0027146"),
    "ny-walworth-t-sd-1-wwtp": ([], "NY0025704"),
}
ICIS_VERSIONS = {   # (permit: versions as ICIS_PERMITS lists them, checked 2026-11-03 in npdes_downloads.zip)
    "CT0100323": "version 0 terminated 2020-03-04, version 1 expired",
    "MA0101214": "version 0 terminated 2023-04-01, versions 1 and 2 expired",
    "MA0100196": "version 0 terminated 2023-09-01, versions 1 and 2 expired",
    "MA0101001": "version 0 terminated 2023-04-01, version 1 expired, version 2 administratively continued",
    "MA0100978": "version 0 terminated 2023-04-01, versions 1 and 2 expired",
    "NY0252042": "version 0 terminated 2026-09-30, versions 1 to 5 expired, effective or administratively continued",
    "NY0027146": "version 0 terminated 2025-11-19, versions 1 to 4 expired or administratively continued",
    "NY0025704": "version 0 terminated 2026-05-26, versions 1 to 3 expired or administratively continued",
}
GENERIC = set("""town city village of the and wwtp wwtf wpcf wpca wpcp wrrf wrf stp sewer sewage
authority auth municipal muni mun water pollution control facility plant treatment works department dept public
sanitary district dist commission regional joint sa ma mua mud board county co wastewater waste disposal system systems
utility utilities service services pw dpw wpc wwt tp sd collection wwcs potw reclamation""".split())


def toks(s):
    """The distinctive words of a permittee's name. Township and borough stay (as twp, boro: 'Mt Pleasant Twp' and 'Mt
    Pleasant Boro', 'Harrison Township' and the Town of Harrison are different operators); a drinking-water plant keeps
    its mark ('Bethlehem Water Treatment Plant' is not the city's wastewater plant)."""
    t = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower().replace("'", ""))
    out = [{"township": "twp", "borough": "boro"}.get(w, w) for w in t.split() if w not in GENERIC]
    if re.search(r"water (treatment|filtration|filter)|filter plant|\bwtp\b|\bwtf\b", t):
        out.append("drinkingwater")
    return out


def key(s):
    return " ".join(sorted(toks(s)))


def town_ok(row, city):
    """False when the registry row names towns and EPA's city is none of them (the same name in another town)."""
    towns = {re.sub(r"[^a-z]", "", t.lower()) for t in row.get("towns") or [] if t}
    c = re.sub(r"[^a-z]", "", title(city).lower())
    return not towns or not c or any(c in t or t in c for t in towns)


def add_note(d, text):
    """Append a sentence to a row's notes; a row made from a feed's facility name (tests/test_align_review.py fixes its
    shape) keeps its closing 'Not verified.'."""
    old = (d.get("notes") or "").rstrip()
    if old.startswith("Row made from the feed's own facility name") and old.endswith("Not verified."):
        d["notes"] = old[:-len("Not verified.")].rstrip() + " " + text + " Not verified."
    else:
        d["notes"] = old + (" " if old else "") + text


def title(s):
    """EPA's upper-case city as a place name ('ST. MARYS' -> 'St. Marys'); ', TOWN OF' style suffixes dropped."""
    s = re.sub(r",?\s*(TOWN|VILLAGE|CITY|BOROUGH|TOWNSHIP)\s+OF\s*$", "", (s or "").strip(), flags=re.I)
    return re.sub(r"(?<=\w)'S\b", "'s", s.title()) if s else ""


def permits_of(row):
    out = set()
    for f in ("npdes_permit", "npdes_permits"):
        v = row.get(f)
        for p in (v if isinstance(v, list) else [v]):
            if p:
                out.add(str(p).strip().upper())
    return out


def load_candidates(registry_permits):
    """permit -> {rows, files, state}: every live-state permit of the three outfall files no registry row holds."""
    cand = defaultdict(lambda: {"rows": [], "files": set(), "state": None})
    for name, path in FILES.items():
        for r in json.loads((ROOT / path).read_text())["outfalls"]:
            p = str(r.get("npdes_permit") or "").strip().upper()
            if p and r.get("state") in LIVE and p not in registry_permits:
                c = cand[p]
                c["rows"].append(r)
                c["files"].add(name)
                c["state"] = r["state"]
    return cand


def public_permit_name(v):
    """ICIS's permit name, or None when the whole name is a person's (EPA often fills the field with a contact person):
    no body's word and a person's name by scripts/private_utilities.person_like."""
    s = str(v or "").strip()
    if not s:
        return None
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    import private_utilities as pu
    return None if not pu.has_org_word(s) and pu.person_like(pu.clean(s).strip(" .,")) else s


def private_reason(p, c):
    """Why a permit is not added now (None when it is): the owner has not decided on private utilities."""
    if p in SKIP_PRIVATE:
        return f"CSO inventory, not a sewer operator ({SKIP_PRIVATE[p]})"
    pr = [r for r in c["rows"] if "plants" in c["files"] and r.get("plant_basis")]
    if not pr:
        return None                     # CSO files only: municipal by the inventory
    r = pr[0]
    basis, owner = r.get("plant_basis"), r.get("facility_type")
    if basis in ("potw_component", "potw_indicator"):
        return f"POTW permit, owner type {owner}" if owner in PRIVATE_TYPES else None
    if basis == "sewerage_code_public_owner":
        return None
    return f"sewerage SIC/NAICS permit, owner type {owner or 'blank'} (basis {basis})"


def status_of(c):
    for r in c["rows"]:
        if r.get("permit_status"):
            return r["permit_status"]
    return None


def build_row(group, counts):
    """One new operator row for a group of (permit, candidate) pairs of one permittee in one town."""
    def rank(pc):
        p, c = pc
        r = c["rows"][0]
        return (r.get("permit_type") not in ("NPD", "SIN"), status_of(c) not in ("EFF", "ADC", "EXP"), -counts[p], p)
    group = sorted(group, key=rank)
    p0, c0 = group[0]
    r0 = c0["rows"][0]
    st = c0["state"]
    pids = [p for p, _ in group]
    waters = []
    for _, c in group:
        for r in c["rows"]:
            w = (r.get("receiving_water_echo") or "").strip()
            if w and w not in waters:
                waters.append(w)
    towns = []
    for _, c in group:
        for r in c["rows"]:
            t = title(r.get("city"))
            if t and t not in towns:
                towns.append(t)
    n_out = sum(counts[p] for p in pids)
    from_cso = any(c["files"] & {"mid-atlantic", "ne"} for _, c in group)
    files = sorted({f for _, c in group for f in c["files"]})
    if from_cso:
        src = (f"EPA National CSO Inventory (ECHO ALL_CSO_DOWNLOADS, {n_out} {st} rows for this permit, joined in "
               f"data/outfalls-{'ne' if st in ('CT', 'MA', 'ME', 'NH', 'RI', 'VT') else 'mid-atlantic'}.json)")
        if "plants" in files:
            src += f"; treatment-plant outfalls from EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json)"
    else:
        src = f"EPA ECHO ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, {n_out} rows for this permit)" if n_out else \
            "EPA ECHO ICIS-NPDES (data/outfalls-plants-us.json: the plant's point only, no outfall coordinates)"
    bits = []
    for p, c in group:
        r = c["rows"][0]
        b = [p]
        if r.get("permit_type"):
            b.append(f"{r['permit_type']} permit")
        if status_of(c):
            b.append(f"status {status_of(c)}")
        if r.get("facility_type"):
            b.append(str(r["facility_type"]))
        if r.get("major_minor"):
            b.append(str(r["major_minor"]))
        if r.get("design_flow_mgd") is not None:
            b.append(f"design flow {r['design_flow_mgd']} MGD")
        bits.append(", ".join(b))
    notes = ("EPA ECHO ICIS-NPDES: " + "; ".join(bits) + ". Added 2026-11-03 so the permit's outfalls have an operator page "
             "(scripts/add_federal_operators.py; data/outfalls-plants-us.json, research/federal/plant-outfalls.md): "
             "name, city and receiving water as EPA spells them; no contact, notification channel or overflow history "
             "has been researched.")
    perm_name = public_permit_name(r0.get("permit_name"))
    if perm_name and perm_name.strip().upper() != str(r0.get("permittee") or "").strip().upper():
        notes += f" ICIS permit name: {perm_name}."
    rid = f"{st.lower()}-{p0.lower()}"
    return {"id": rid, "name": r0.get("permittee") or perm_name or p0, "state": st, "kind": "cso" if from_cso else "plant",
            "npdes_permit": p0, "npdes_permits": pids, "receiving_waters": waters[:8], "water_slugs": [],
            "outfall_count": n_out or None, "outfalls_source": src,
            "notification_channel": "None found online (not searched individually)",
            "notification_feed_machine_readable": False, "notification_signup_url": None, "towns": towns, "notes": notes,
            "verified": "fetched", "checked": TODAY, "aliases": [rid], "source_areas": ["federal"]}


def main(argv):
    dry = "--dry-run" in argv
    dis = json.loads(DIS.read_text())
    before = len(dis)
    registry_permits = set()
    for d in dis:
        registry_permits |= permits_of(d)
        registry_permits |= {str(a).strip().upper() for a in d.get("aliases") or []}
    ids = {d["id"] for d in dis} | {a for d in dis for a in d.get("aliases") or []}
    by_key = defaultdict(list)
    for d in dis:
        for n in [d.get("name"), d.get("short_name")] + list(d.get("alt_names") or []):
            k = key(n)
            if k and d["id"] not in [x["id"] for x in by_key[(d["state"], k)]]:
                by_key[(d["state"], k)].append(d)
    by_id = {d["id"]: d for d in dis}
    reg = load_outfall_registry(provisional=False)
    counts = Counter()
    for o in reg:
        if o.get("npdes_permit") and str(o.get("outfall") or "").strip():
            counts[str(o["npdes_permit"]).strip().upper()] += 1

    cand = load_candidates(registry_permits)
    skipped = defaultdict(Counter)
    held, attached, groups = [], [], defaultdict(list)
    for p, c in sorted(cand.items()):
        st = c["state"]
        why = private_reason(p, c)
        if why:
            skipped[st][why] += 1
            continue
        r0 = c["rows"][0]
        if p in HOLD_BY_HAND:
            held.append((p, r0, HOLD_BY_HAND[p]))
            continue
        if p in ATTACH_BY_HAND:
            attached.append((p, ATTACH_BY_HAND[p][0], ATTACH_BY_HAND[p][1], r0))
            continue
        k = key(r0.get("permittee"))
        rows = [d for d in by_key.get((st, k)) or [] if town_ok(d, r0.get("city"))] if k else None
        if rows and len(rows) == 1:
            attached.append((p, rows[0]["id"], f"same operator by name ('{r0.get('permittee')}' = '{rows[0]['name']}')", r0))
            continue
        if rows:
            held.append((p, r0, "the name equals " + ", ".join(f"{d['name']} ({d['id']})" for d in rows)))
            continue
        # inside the name of a row that has no permit (and so no way to tell it apart by permit): Ocean Pines in Ocean City
        ct = set(toks(r0.get("permittee")))
        near = [] if p in NEW_DESPITE_OVERLAP else [d for d in dis if d["state"] == st and not permits_of(d) and ct and any(
            t and (ct <= set(t) or set(t) <= ct) for t in [toks(d.get("name"))])]
        if near:
            held.append((p, r0, "its name overlaps the permit-less operator " + ", ".join(f"{d['name']} ({d['id']})" for d in near[:3])))
            continue
        gk = (st, k or p, key(title(r0.get("city"))) if k else p)
        groups[gk].append((p, c))

    new_rows = []
    for gk, group in sorted(groups.items()):
        row = build_row(group, counts)
        n = 2
        base = row["id"]
        while row["id"] in ids:
            row["id"] = f"{base}-{n}"
            n += 1
        row["aliases"] = [row["id"]]
        ids.add(row["id"])
        new_rows.append(row)

    # attach
    note_tag = f" Permit added {TODAY} from EPA ECHO ICIS-NPDES (scripts/add_federal_operators.py)"
    for p, did, why, r0 in attached:
        d = by_id[did]
        if p in permits_of(d):
            continue
        d["npdes_permits"] = list(d.get("npdes_permits") or ([d["npdes_permit"]] if d.get("npdes_permit") else [])) + [p]
        if not d.get("npdes_permit"):
            d["npdes_permit"] = p
        text = f"{note_tag.strip()}: {p} ({r0.get('permittee')}, {r0.get('city') or 'city not given'}); {why}."
        add_note(d, text)
        # the registry row's `checked` is about its own research and stays

    # the 8 operators
    fixed = []
    for did, (add, old) in TERMINATED_FIX.items():
        d = by_id.get(did)
        if d is None:
            continue
        have = permits_of(d)
        for p in add:
            if p not in have:
                d["npdes_permits"] = list(d.get("npdes_permits") or []) + [p]
        note = (f"EPA ICIS-NPDES lists {old} with {ICIS_VERSIONS[old]}; the permit number is current, and EPA's facility record "
                f"(same FRS registry id) also holds {', '.join(add)}" if add else
                f"EPA ICIS-NPDES lists {old} with {ICIS_VERSIONS[old]}; the permit number is current")
        note += (" (ICIS_PERMITS, npdes_downloads.zip dated 2026-11-01, read 2026-11-03; the plant-outfall build read version 0, "
                 "so research/federal/plant-outfalls.md listed it as terminated).")
        if note not in str(d.get("notes")):
            add_note(d, note)
        fixed.append((did, old, add))

    dis_out = dis + new_rows
    # the review file
    n_att = Counter(by_id[did]["state"] for _, did, _, _ in attached)
    n_new = Counter(r["state"] for r in new_rows)
    L = [f"# Operator rows added from the outfall registry ({TODAY})", "",
         "Written by `scripts/add_federal_operators.py` (see its docstring for the rules). Outfalls whose permit had no row in "
         "`data/dischargers.json` had no operator page. Nothing here is a judgement about the operators; the rows carry EPA's "
         "names, cities and receiving waters, and say no channel was searched.", "",
         f"- New operator rows: {len(new_rows)} ({sum(len(r['npdes_permits']) for r in new_rows)} permits). "
         f"Permits attached to an existing operator: {len(attached)}. Held for a person: {len(held)}. "
         f"Skipped (private): {sum(sum(v.values()) for v in skipped.values())}.", "",
         "| State | New rows | Attached | Held | Skipped |", "|---|---|---|---|---|"]
    n_held = Counter(r0["state"] for _, r0, _ in held)
    for st in sorted(LIVE):
        L.append(f"| {st} | {n_new[st]} | {n_att[st]} | {n_held[st]} | {sum(skipped[st].values())} |")
    L += ["", "## Skipped: private or not a sewer operator's", "",
          "The owner has not decided on private utilities. A permit is added only when EPA marks it POTW with an owner that is "
          "not private, or it has the sewerage SIC/NAICS code and a public owner.", "", "| State | Permits | Why |", "|---|---|---|"]
    for st in sorted(skipped):
        L.append(f"| {st} | {sum(skipped[st].values())} | " + "; ".join(f"{n} x {w}" for w, n in skipped[st].most_common()) + " |")
    L += ["", "## Attached to an existing operator", "", "| Permit | Operator | Basis |", "|---|---|---|"]
    for p, did, why, r0 in attached:
        L.append(f"| {p} | {did} | {why} |")
    L += ["", "## Held: could be an existing operator (no row added, no permit attached)", "",
          "| Permit | EPA's name (city) | Why held |", "|---|---|---|"]
    for p, r0, why in held:
        L.append(f"| {p} | {r0.get('permittee')} ({r0.get('city')}) | {why} |")
    L += ["", "## The 8 operators whose permit the plant-outfall research listed as terminated", ""]
    for did, old, add in fixed:
        L.append(f"- {did}: {old} stays; " + (f"added {', '.join(add)}; " if add else "no other current permit; ") + ICIS_VERSIONS[old] + ".")
    if not dry:
        sys.path.insert(0, str(ROOT / "scripts"))
        tmp = DIS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(dis_out, indent=1, ensure_ascii=False) + "\n")
        tmp.replace(DIS)
        REVIEW.write_text("\n".join(L) + "\n")
    print(f"operators {before} -> {len(dis_out)}: new {len(new_rows)} rows ({sum(len(r['npdes_permits']) for r in new_rows)} permits), "
          f"attached {len(attached)}, held {len(held)}, skipped {sum(sum(v.values()) for v in skipped.values())}, "
          f"fixed {len(fixed)}" + (" (dry run)" if dry else ""))
    print("new by state", dict(sorted(n_new.items())))
    print("skipped by state", {s: sum(v.values()) for s, v in sorted(skipped.items())})


if __name__ == "__main__":
    main(sys.argv[1:])
