"""South Carolina operator rows for data/dischargers.json: one row per operator, every South Carolina permit of the
outfall registry, the research's operators and EPA's private sewage permits in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_sc_operators.py [--dry-run]

Inputs
  - research/sc/dischargers.json (9 rows): Charleston Water System, North Charleston Sewer District, Florence, Columbia,
    ReWa, Spartanburg Water's Sanitary Sewer District, Mount Pleasant Waterworks, Beaufort-Jasper Water and Sewer
    Authority, Grand Strand Water and Sewer Authority. Each keeps its research id.
  - data/outfalls-plants-us.json: every South Carolina permit EPA lists (213 plant permits; South Carolina has no
    combined sewers and EPA's CSO inventory no South Carolina row). The permits of one owner are one row: EPA's owner
    spelling (permit_name) is normalised (owner_key) and OWNERS joins the spellings of one owner and names the owner
    where EPA records "(Unknown Permittee)" or none, from the facility's own name (FACILITY_OWNERS).
  - research/sc/private-utilities-candidates.json (26 privately owned sewage permits, most not in the plant registry,
    and one public body EPA types private): a row each, grouped by company where the facility names one (Blue Granite
    Water Company, Synergy Utilities), legal_form from the controlled list, never an individual's name (a permittee the
    candidate file removed stays removed; the row names the facility).
Rules
  - legal_form from the controlled list (docs/legal-forms.md): OWNERS by hand, else form() from the name.
  - notification_channel: S.C. Code 48-1-95(E) (public notice of a spill of 5,000 gallons or more within 24 hours of
    discovery; the law names no channel; DES gives notice when the utility does not), the operator's own page where
    the research found one; the rest not searched individually.
  - Idempotent: every row with state SC is rebuilt; other states' rows are left as they are; the South Carolina rows
    are written after the last row of the file in id order.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "sc" / "dischargers.json"
CANDIDATES = ROOT / "research" / "sc" / "private-utilities-candidates.json"
CHECKED = "2026-11-14"
LAW = ("S.C. Code 48-1-95(E): the utility must give public notice of a significant spill (5,000 gallons or more of "
       "untreated or partially treated sewage) within 24 hours of discovery, through a channel the law does not name; "
       "DES gives the notice when the utility does not. DES publishes no list of the reports it receives. The "
       "operator's own pages were not searched individually.")
CHANNEL = {
    "sc-florence": ("S.C. Code 48-1-95(E). The City posts a 'Notification of Sanitary Sewer Overflow' news release for "
                    "each overflow of 5,000 gallons or more (https://www.cityofflorencesc.gov/city-news), read by this "
                    "site."),
    "sc-charleston-water-system": ("S.C. Code 48-1-95(E). Charleston Water System posts overflow news on its site "
                                   "(https://www.charlestonwater.com/m/newsflash) and offers 'Notify Me' alerts; its "
                                   "host did not answer this site's client on 2026-11-14."),
}
# research id -> (extra permits, kind, legal_form, short name, name)
RESEARCH_ROWS = {
    "sc-charleston-water-system": (["SC0021229", "SC0047074"], "sso", "authority", "Charleston Water System",
                                   "Charleston Water System (Commissioners of Public Works of the City of Charleston)"),
    "sc-north-charleston-sewer": (["SC0024783"], "sso", "special district", "North Charleston Sewer District", None),
    "sc-florence": (["SC0045462", "SC0025356"], "sso", "city", "City of Florence", "City of Florence (Utilities)"),
    "sc-columbia": (["SC0020940"], "sso", "city", "City of Columbia", None),
    "sc-rewa": ([], "sso", "special district", "ReWa", "Renewable Water Resources (ReWa)"),
    "sc-spartanburg-water": ([], "sso", "special district", "Spartanburg Sanitary Sewer District",
                             "Spartanburg Sanitary Sewer District (Spartanburg Water)"),
    "sc-mount-pleasant-waterworks": ([], "sso", "authority", "Mount Pleasant Waterworks", None),
    "sc-bjwsa": ([], "sso", "authority", "BJWSA", "Beaufort-Jasper Water and Sewer Authority"),
    "sc-grand-strand": ([], "sso", "authority", "Grand Strand Water and Sewer Authority", None),
}
DISCHARGER_ALIAS = {"sc-florence": "sc-city-of-florence"}   # the ingester's id for Florence's row
# owner key -> (row id, name, legal_form): one owner's spellings joined
OWNERS = {
    "renewablewaterresources": ("sc-rewa", None, None),
    "rewa": ("sc-rewa", None, None),
    "spartanburgsanitarysewerdistrict": ("sc-spartanburg-water", None, None),
    "sssd": ("sc-spartanburg-water", None, None),
    "mountpleasantwaterworks": ("sc-mount-pleasant-waterworks", None, None),
    "beaufortjasperwatersewerauthority": ("sc-bjwsa", None, None),
    "bjwsa": ("sc-bjwsa", None, None),
    "grandstrandwatersewerauthority": ("sc-grand-strand", None, None),
    "gswsa": ("sc-grand-strand", None, None),
    "charlestonwatersystem": ("sc-charleston-water-system", None, None),
    "northcharlestonsewerdistrict": ("sc-north-charleston-sewer", None, None),
    "pickenscountypublicservicecommission": ("sc-pickens-county-psc", "Pickens County Public Service Commission",
                                             "special district"),
    "pickenscopsc": ("sc-pickens-county-psc", None, None),
    "pickenscopsc18milecreekupperwwtp": ("sc-pickens-county-psc", None, None),
    "easleycombinedutilities": ("sc-easley-combined-utilities", "Easley Combined Utilities", "city"),
    "edgefieldcountywatersewerauthority": ("sc-edgefield-cwsa", "Edgefield County Water and Sewer Authority", "authority"),
    "ecwsa": ("sc-edgefield-cwsa", None, None),
    "gaffneyboardofpublicworks": ("sc-gaffney-bpw", "Gaffney Board of Public Works", "city"),
    "berkeleycountywatersanitationauthority": ("sc-berkeley-county-wsa", "Berkeley County Water and Sanitation", "county"),
    "isleofpalmswatersewercommission": ("sc-isle-of-palms-wsc", "Isle of Palms Water and Sewer Commission", "city"),
    "lowcountryregionalwatersystem": ("sc-lowcountry-regional-water", "Lowcountry Regional Water System", "authority"),
    "georgetowncountywatersewerdistrict": ("sc-georgetown-county-wsd", "Georgetown County Water and Sewer District",
                                           "special district"),
    "chestersewerdistrict": ("sc-chester-sewer-district", "Chester Sewer District", "special district"),
    "greenwoodmetropolitandistrict": ("sc-greenwood-metro", "Greenwood Metropolitan District", "special district"),
    "southislandpublicservicedistrict": ("sc-south-island-psd", "South Island Public Service District",
                                         "special district"),
    "ninetysixcommissionofpublicworks": ("sc-ninety-six-cpw", "Ninety Six Commission of Public Works", "town"),
    "richlandcountyutilitiesservices": ("sc-richland-county", "Richland County Utilities", "county"),
    "northmyrtlebeachcityof": ("sc-north-myrtle-beach", "City of North Myrtle Beach", "city"),
    "andersoncityof": ("sc-city-of-anderson", "City of Anderson", "city"),
    "tegacaycityof": ("sc-tega-cay", "City of Tega Cay", "city"),
    "springfieldtownof": ("sc-springfield", "Town of Springfield", "town"),
    "springfieldwwtp1": ("sc-springfield", None, None),
    "springfieldwwtp2": ("sc-springfield", None, None),
    "kingstreetownof": ("sc-kingstree", "Town of Kingstree", "town"),
    "scdeptofcorrections": ("sc-dept-of-corrections", "South Carolina Department of Corrections", "state facility"),
    "scdeptofparksrecreationtourism": ("sc-state-parks", "South Carolina Department of Parks, Recreation and Tourism",
                                       "state facility"),
    "pagelandtownof": ("sc-pageland", "Town of Pageland", "town"),
    "pagelandnorthwestwwtf": ("sc-pageland", None, None),
    "dorchestercounty": ("sc-dorchester-county", "Dorchester County Water and Sewer", "county"),
    "dorchestercountywatersewerdepartment": ("sc-dorchester-county", None, None),
    "beaufortcountyschooldistrict": ("sc-beaufort-county-schools", "Beaufort County School District",
                                     "special district"),
    "bcsdjamesjdaviselemschool": ("sc-beaufort-county-schools", None, None),
    "hiltonheadpublicservicedistrict": ("sc-hilton-head-psd", "Hilton Head Public Service District", "special district"),
    "hiltonheadreverseosmosis": ("sc-hilton-head-psd", None, None),
    "lancastercounty": ("sc-lancaster-county", "Lancaster County", "county"),
    "lancastercountywatersewerdistrict": ("sc-lancaster-county-wsd", "Lancaster County Water and Sewer District",
                                          "special district"),
    "laurenscommissionofpublicworks": ("sc-laurens-cpw", "Laurens Commission of Public Works", "city"),
    "laurenscountywatersewercommission": ("sc-laurens-county-wsc", "Laurens County Water and Sewer Commission",
                                          "special district"),
    "saludacommissionofpublicworks": ("sc-saluda-cpw", "Saluda Commission of Public Works", "town"),
    "saludacountywatersewerauthority": ("sc-saluda-county-wsa", "Saluda County Water and Sewer Authority", "authority"),
    "summervillecommissionersofpublicworks": ("sc-summerville-cpw", "Summerville Commissioners of Public Works", "town"),
    "aikencountypublicserviceauthority": ("sc-aiken-county-psa", "Aiken County Public Service Authority", "authority"),
    "mccormickcommissionofpublicworks": ("sc-mccormick-cpw", "McCormick Commission of Public Works", "town"),
    "greercommissionofpublicworks": ("sc-greer-cpw", "Greer Commission of Public Works", "city"),
    "oconeejointregionalsewerauthority": ("sc-ojrsa", "Oconee Joint Regional Sewer Authority", "authority"),
    "eastrichlandcountypsd": ("sc-east-richland-psd", "East Richland County Public Service District", "special district"),
    "williamsburgcountywatersewerauthoritysouth": ("sc-williamsburg-county-wsa",
                                                   "Williamsburg County Water and Sewer Authority", "authority"),
    "woodruffroebuckwaterdistrict": ("sc-woodruff-roebuck-water", "Woodruff-Roebuck Water District", "special district"),
    "santeecooper": ("sc-santee-cooper", "South Carolina Public Service Authority (Santee Cooper)", "authority"),
    "georgetowncountyschooldistrict": ("sc-georgetown-county-schools", "Georgetown County School District",
                                       "special district"),
    "berkeleycountyschooldistrict": ("sc-berkeley-county-schools", "Berkeley County School District",
                                     "special district"),
    "departmentofairforce": ("sc-joint-base-charleston", "U.S. Air Force, Joint Base Charleston", "federal facility"),
    "usafwatereerecreationfacility": ("sc-usaf-wateree", "U.S. Air Force, Wateree Recreation Area", "federal facility"),
    "orangeburgdepartmentofpublicutilities": ("sc-orangeburg-dpu", "Orangeburg Department of Public Utilities", "city"),
    "clemsonuniversitywwtf": ("sc-clemson-university", "Clemson University", "state facility"),
    "mayortownofwhitmire": ("sc-whitmire", "Town of Whitmire", "town"),
    "kershawcounty": ("sc-kershaw-county", "Kershaw County", "county"),
    "andersoncounty": ("sc-anderson-county", "Anderson County", "county"),
    "sumtercounty": ("sc-sumter-county", "Sumter County", "county"),
    "calhouncounty": ("sc-calhoun-county", "Calhoun County", "county"),
    "pickenscityof": ("sc-city-of-pickens", "City of Pickens", "city"),
    "mhccarolinalcinc": ("sc-mhc-carolina-landing", "MHC Carolina LC, Inc. (Carolina Landing campground)",
                         "campground or resort"),
    "alicemanufacturingcoinc": ("sc-alice-manufacturing", "Alice Manufacturing Co., Inc.", "business or industrial"),
    "cogsdilltoolproductsinc": ("sc-cogsdill-tool", "Cogsdill Tool Products, Inc.", "business or industrial"),
    "sswasherette": ("sc-ss-washerette", "S&S Washerette", "business or industrial"),
    "chesneecityof": ("sc-spartanburg-water", None, None),
    "ecwsatrentonwwtf": ("sc-edgefield-cwsa", None, None),
    "sssdpacoletmillswwtp": ("sc-spartanburg-water", None, None),
    "rewapiedmontwwtp": ("sc-rewa", None, None),
    "rewagrovecreekwwtp": ("sc-rewa", None, None),
    "lexingtoncoventrywoodswwtp": ("sc-lexington", "Town of Lexington", "town"),
    "stmatthewssouthplant": ("sc-st-matthews", "Town of St. Matthews", "town"),
    "westpelzerwwtf": ("sc-west-pelzer", "Town of West Pelzer", "town"),
    "bcsdjamesjdaviselemschool2": ("sc-beaufort-county-schools", None, None),
}
# facility words -> owner key, where EPA records "(Unknown Permittee)" or no permittee
FACILITY_OWNERS = [
    (r"^GSW&SA\b", "gswsa"), (r"^DORCHESTER CO\b", "dorchestercounty"),
    (r"^ORANGEBURG COUNTY WATER AND SEWER AUTHORITY", "orangeburgcountywsa"),
    (r"^TOWN OF HOLLY HILL", "hollyhilltownof"), (r"^SSSD\b", "sssd"), (r"^BLUE GRANITE WATER COMPANY", "bluegranite"),
    (r"^LANCASTER CATAWBA RIVER", "lancastercityof"), (r"^NCW&SA\b", "newberrycountywsa"),
    (r"^PENDLETON-CLEMSON", "pendletonclemson"), (r"^NORWAY TOWN OF", "norwaytownof"),
    (r"^YC HOLDINGS", "ycholdings"), (r"^AMERICAN HOUSE SPINNING", "americanhousespinning"),
    (r"FAMILY CHILDREN'S TRUST", "privatetrustwalterboro"),
]
OWNERS.update({
    "orangeburgcountywsa": ("sc-orangeburg-county-wsa", "Orangeburg County Water and Sewer Authority", "authority"),
    "hollyhilltownof": ("sc-holly-hill", "Town of Holly Hill", "town"),
    "bluegranite": ("sc-blue-granite-water", "Blue Granite Water Company", "investor-owned utility"),
    "lancastercityof": ("sc-city-of-lancaster", "City of Lancaster", "city"),
    "newberrycountywsa": ("sc-newberry-county-wsa", "Newberry County Water and Sewer Authority", "authority"),
    "pendletonclemson": ("sc-pendleton-clemson-regional", "Pendleton-Clemson Regional Wastewater Treatment Facility "
                         "(owner not recorded by EPA)", None),
    "norwaytownof": ("sc-norway", "Town of Norway", "town"),
    "ycholdings": ("sc-yc-holdings", "YC Holdings, Inc.", "business or industrial"),
    "americanhousespinning": ("sc-american-house-spinning", "American House Spinning, Inc.", "business or industrial"),
    "privatetrustwalterboro": ("sc-scg570037", "Privately owned plant at Walterboro (permittee not named)",
                               "facility (permittee not named)"),
})
# EPA's private sewage permits (the candidates file): permit -> (row id, name, legal_form)
PRIVATE = {
    "SC0022357": ("sc-cswr-south-carolina", "CSWR South Carolina (Foxwood Hills subdivision plant)", "investor-owned utility"),
    "SC0023141": ("sc-king-real-estate-holdings", "King Real Estate Holdings LP", "business or industrial"),
    "SC0026565": ("sc-rewa", None, None),
    "SC0027146": ("sc-blue-granite-water", None, None),
    "SC0027189": ("sc-blue-granite-water", None, None),
    "SC0028673": ("sc-blue-granite-water", None, None),
    "SC0029475": ("sc-sc0029475", "Woodland Hills West subdivision plant (permittee not named)",
                  "facility (permittee not named)"),
    "SC0029483": ("sc-alpine-utilities", "Alpine Utilities (Stoop Creek plant)", "investor-owned utility"),
    "SC0030112": ("sc-cws-lamplighter", "CWS Inc. of NC (Lamplighter Village South plant)", "investor-owned utility"),
    "SC0030571": ("sc-sc0030571", "Wellford Estates Trailer Park", "mobile-home park"),
    "SC0030678": ("sc-blue-granite-water", None, None),
    "SC0030724": ("sc-blue-granite-water", None, None),
    "SC0031801": ("sc-south-of-the-border", "South of the Border Motel", "business or industrial"),
    "SC0032018": ("sc-sc0032018", "Cedar Creek Mobile Home Park", "mobile-home park"),
    "SC0032212": ("sc-sc0032212", "Carolina Mobile Court", "mobile-home park"),
    "SC0032743": ("sc-synergy-utilities", "Synergy Utilities LP (South Carolina Water Utilities)", "investor-owned utility"),
    "SC0035980": ("sc-vision-center", "Vision Center (Winnsboro)", "institution"),
    "SC0037605": ("sc-lake-wylie-mhp-utilities", "Lake Wylie MHP Utilities LLC", "mobile-home park"),
    "SC0037788": ("sc-bolen-point-poa", "Bolen Point Plantation Property Owners Association, Inc.",
                  "homeowners' association"),
    "SC0039055": ("sc-synergy-utilities", None, None),
    "SC0039217": ("sc-blue-granite-water", None, None),
    "SC0042684": ("sc-jacabb-utilities", "JACABB Utilities LLC (Links of Tryon plant)", "investor-owned utility"),
    "SC0043451": ("sc-palmetto-utilities", "Palmetto Utilities, Inc. (South Carolina Water Utilities; Spears Creek plant)",
                  "investor-owned utility"),
    "SC0046817": ("sc-dewees-utility", "Dewees Utility Corporation", "investor-owned utility"),
    "SC0047813": ("sc-federal-pacific-electric", "Federal Pacific Electric Company", "business or industrial"),
    "SC0049374": ("sc-sc0049374", "Privately owned plant at Holly Hill (permittee not named)",
                  "facility (permittee not named)"),
}
PUBLIC_BY_NAME = {"SC0027162": ("sc-lexington", "Town of Lexington", "town")}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}


def key(s: str | None) -> str:
    s = (s or "").lower().replace("&", "").replace("utilities, ", "")
    s = re.sub(r"\b(the|and)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def title(s: str) -> str:
    s = (s or "").strip()
    if s.isupper() or s.islower():
        s = s.title()
    s = re.sub(r"\b(Wwtp|Wwtf|Psd|Cpw|Wrf)\b", lambda m: m.group(1).upper(), s)
    s = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), s)
    return re.sub(r"(?<=\w )\b(Of|And|The)\b", lambda m: m.group(1).lower(), s)


def pretty(owner: str) -> str:
    """"ROCK HILL CITY OF" -> "City of Rock Hill"; "City of Cayce" stays."""
    s = re.sub(r"\s+", " ", owner or "").strip()
    m = re.match(r"^(.*?),?\s+(CITY|TOWN)(?:\s+OF)?$", s, re.I)
    if m and not re.match(r"(?i)^(city|town) of\b", s):
        return f"{m.group(2).title()} of {title(m.group(1))}"
    t = title(s)
    return re.sub(r"^(City|Town) Of\b", lambda m: f"{m.group(1)} of", t)


def form(name: str) -> str | None:
    n = (name or "").lower()
    if re.search(r"\b(air force|army|navy|national park|u\.?s\.? )\b", n):
        return "federal facility"
    if re.search(r"\b(public service district|psd|sewer district|water district|school district|metropolitan district)\b", n):
        return "special district"
    if re.search(r"\b(authority|commission)\b", n):
        return "authority"
    if re.search(r"\bcounty\b", n):
        return "county"
    if re.search(r"\btown of\b|\btown$", n):
        return "town"
    if re.search(r"\bcity of\b|\bcity$", n):
        return "city"
    return None


def load_epa() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in ("outfalls-plants-us.json", "outfalls-us.json"):
        doc = json.loads((ROOT / "data" / f).read_text())
        for r in doc["outfalls"]:
            p = str(r.get("npdes_permit") or "").upper()
            if not p.startswith("SC") or r.get("state") not in (None, "SC"):
                continue
            o = out.setdefault(p, {"owner": r.get("permit_name"), "facility": r.get("permittee"), "city": r.get("city"),
                                   "waters": [], "outfalls": 0})
            w = (r.get("receiving_water_echo") or "").strip()
            if w and w.title() not in o["waters"]:
                o["waters"].append(w.title())
            o["outfalls"] += 1
    return out


def owner_key(o: dict) -> str:
    own = o.get("owner")
    if own and own not in ("(Unknown Permittee)",) and key(own) in OWNERS:
        return key(own)
    fac = o.get("facility") or ""
    for rx, k in FACILITY_OWNERS:
        if re.search(rx, fac, re.I):
            return k
    if own and own != "(Unknown Permittee)":
        return key(own)
    return key(fac)


def base_row(rid, name, permits, kind, lf, towns, waters, outfalls, notes, short=None, research=False) -> dict:
    r = {"id": rid, "name": name, "state": "SC", "kind": kind, "npdes_permit": permits[0] if permits else None,
         "npdes_permits": permits, "receiving_waters": waters, "water_slugs": [], "outfall_count": outfalls or None,
         "outfalls_source": ("EPA ECHO ICIS-NPDES discharge points (data/outfalls-plants-us.json: "
                             f"{outfalls} rows for these permits)" if outfalls else None),
         "notification_channel": CHANNEL.get(rid, LAW), "notification_feed_machine_readable": rid in CHANNEL and rid == "sc-florence",
         "notification_signup_url": None, "towns": towns, "notes": notes, "verified": "fetched", "checked": CHECKED,
         "aliases": [rid] + ([DISCHARGER_ALIAS[rid]] if rid in DISCHARGER_ALIAS else []),
         "source_areas": ["sc"] + ([] if research else ["federal"])}
    if short:
        r["short_name"] = short
    if lf:
        r["legal_form"] = lf
    return r


# rows of data/outfalls-sc.json that are kind other (a drinking-water plant's concentrate, a land-application site):
# not counted as outfalls
OTHER = Counter(r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-sc.json").read_text())["outfalls"]
                if r.get("outfall_kind") == "other")


def build(epa: dict, research: list[dict], cand: dict) -> list[dict]:
    rows: dict[str, dict] = {}
    held: dict[str, str] = {}
    for r in research:
        extra, kind, lf, short, name = RESEARCH_ROWS[r["id"]]
        permits = list(dict.fromkeys(p for p in [r.get("npdes_permit"), *extra] if p))
        note = ((r.get("notes") or "").strip() + f" Research row (research/sc/dischargers.json, checked "
                f"{r.get('checked')}).").strip()
        rows[r["id"]] = base_row(r["id"], name or r["name"], permits, kind, lf, r.get("towns") or [],
                                 list(dict.fromkeys(r.get("receiving_waters") or [])), 0, note, short, True)
        for p in permits:
            held[p] = r["id"]
    groups: dict[str, list[str]] = defaultdict(list)
    meta: dict[str, tuple] = {}
    for p, o in sorted(epa.items()):
        if p in held:
            continue
        if p in PRIVATE or p in PUBLIC_BY_NAME:
            rid, name, lf = {**PRIVATE, **PUBLIC_BY_NAME}[p]
        else:
            k = owner_key(o)
            if k in OWNERS:
                rid, name, lf = OWNERS[k]
            else:
                name = pretty(o["owner"] if o.get("owner") and o["owner"] != "(Unknown Permittee)" else o["facility"])
                rid, lf = f"sc-{p.lower()}", form(name)
                prior = next((g for g, m in meta.items() if m[0] and key(m[0]) == key(name)), None)
                rid = prior or rid
        if rid in rows:
            rows[rid]["npdes_permits"].append(p)
            held[p] = rid
            continue
        groups[rid].append(p)
        if rid not in meta or (name and not meta[rid][0]):
            meta[rid] = (name, lf)
    for p, (rid, name, lf) in {**PRIVATE, **PUBLIC_BY_NAME}.items():      # the candidates EPA's plant file lacks
        if p in epa or p in held:
            continue
        c = next((x for x in cand["candidates"] + cand.get("public_by_name", []) if x["npdes_permit"] == p), {})
        if rid in rows:
            rows[rid]["npdes_permits"].append(p)
        else:
            groups[rid].append(p)
            if rid not in meta or (name and not meta[rid][0]):
                meta[rid] = (name, lf)
        epa.setdefault(p, {"owner": None, "facility": c.get("facility"), "city": c.get("city"),
                           "waters": [w.title() for w in c.get("receiving_waters_echo") or []], "outfalls": 0,
                           "candidate": True})
        held[p] = rid
    named = {v[0]: (v[1], v[2]) for v in OWNERS.values() if v[1]}
    for rid, permits in groups.items():
        name, lf = meta[rid]
        if not name and rid in named:
            name, lf = named[rid]
        name = name or pretty(epa[permits[0]].get("owner") or epa[permits[0]]["facility"])
        lf = lf or form(name)
        towns = sorted({title(epa[p]["city"]) for p in permits if epa[p].get("city")})
        waters = list(dict.fromkeys(w for p in permits for w in epa[p]["waters"]))
        facs = "; ".join(f"{p} {epa[p]['facility']}" for p in permits if epa[p].get("facility") not in (None, "[name removed]"))
        note = f"EPA ECHO ICIS-NPDES: {facs}." if facs else "EPA ECHO ICIS-NPDES."
        if any(epa[p].get("candidate") for p in permits):
            note += (" Privately owned sewage permit(s) from EPA's discharge points (research/sc/private-utilities-"
                     "candidates.json); not in the plant registry.")
        if lf in PRIVATE_FORMS and not note.startswith("Privately"):
            note = "Privately owned. " + note
        rows[rid] = base_row(rid, name, permits, "plant", lf, towns, waters, 0, note)
        for p in permits:
            held[p] = rid
    for r in rows.values():
        r["npdes_permits"] = list(dict.fromkeys(r["npdes_permits"]))
        r["npdes_permit"] = r["npdes_permits"][0] if r["npdes_permits"] else None
        n = sum(epa.get(p, {}).get("outfalls", 0) - OTHER.get(p, 0) for p in r["npdes_permits"])
        r["outfall_count"] = n or None
        r["outfalls_source"] = ("EPA ECHO ICIS-NPDES discharge points (data/outfalls-plants-us.json: "
                                f"{n} rows for these permits)") if n else None
        extra_towns = sorted({title(epa[p]["city"]) for p in r["npdes_permits"] if epa.get(p, {}).get("city")})
        r["towns"] = list(dict.fromkeys(r["towns"] + extra_towns))
        if r["source_areas"] == ["sc"] and r["npdes_permits"]:
            r["source_areas"].append("federal")
    return sorted(rows.values(), key=lambda r: r["id"])


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    new = build(load_epa(), json.loads(RESEARCH.read_text()), json.loads(CANDIDATES.read_text()))
    others = [r for r in dis if r.get("state") != "SC"]
    taken = {p for r in others for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])] if p}
    clash = sorted(p for r in new for p in r["npdes_permits"] if p in taken)
    if clash:
        raise SystemExit(f"permits already held by another state's row: {clash}")
    ids = Counter(r["id"] for r in others + new)
    if [i for i, n in ids.items() if n > 1]:
        raise SystemExit(f"duplicate ids: {[i for i, n in ids.items() if n > 1]}")
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(others + new, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(new), "permits": sum(len(r["npdes_permits"]) for r in new),
                      "no_form": [r["id"] for r in new if not r.get("legal_form")],
                      "by_form": dict(Counter(r.get("legal_form") for r in new))}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
