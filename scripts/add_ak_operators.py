"""Alaska operator rows for data/dischargers.json: one row per operator, every Alaska permit of the outfall registry in
exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_ak_operators.py [--dry-run]

Inputs
  - data/outfalls-plants-us.json and data/outfalls-us.json: every Alaska permit EPA lists (100 plant permits, 2 CSO
    inventory permits, 101 permits in all). EPA's permit name often reads '<a person> - <the body>' (a contact's name
    put before the permittee): the name is never read from it. Each permit is filed by hand in PERMITS below with the
    body that holds it, taken from the body half of EPA's permit name, the facility name or EPA's facility type.
  - research/ak/dischargers.json (6 rows): the CSO permittees of EPA's inventory and the operators the research named
    (Anchorage, Juneau, Ketchikan, Denali, Fairbanks). Each keeps its research id. The Alyeska pipeline permit, which
    EPA's CSO inventory lists, is kind "cso_closed_or_none" (a general permit for pipeline facilities, not a sewer).
  - research/ak/private-utilities-candidates.json: the one private sewage permit EPA lists outside the plant table
    (AK0053384, the Ward Cove industrial site plant, permittee as DEC's permit notice names it) and Fairbanks
    (AK0023451), which EPA types mixed ownership: the permit is held with Golden Heart Utilities, Inc., the private
    utility that runs the city's sewer service.
Rules
  - legal_form from the controlled list (docs/legal-forms.md). Alaska's unified home-rule municipalities (Anchorage,
    Juneau, Sitka, Skagway, Haines, Wrangell, Petersburg) are "city" (a consolidated city-county); the other boroughs
    (North Slope, Ketchikan Gateway, Bristol Bay, Matanuska-Susitna) are "county", the county equivalent; school
    districts are "special district"; tribal councils and the Metlakatla Indian Community are "tribal". A facility
    whose owner EPA's record does not name keeps legal_form null.
  - kind: "cso" for Juneau (three open CSO outfalls), "cso_closed_or_none" for the pipeline permit, "sso" for the
    operators with reports in EPA's overflow tables, "plant" for the rest.
  - notification_channel: the law (18 AAC 72.940, read on akleg.gov 2026-11-07) and the APDES permits' standard
    conditions (Appendix A, Part 3.4, read in permit AK0022951 on the City and Borough of Juneau's site) put the duty
    to report on the operator and the recipient is DEC; nothing requires the public to be told, and DEC does not post
    the reports. The three operators that file through EPA's NeT-SewerOverflow reach EPA's tables. Juneau's own CSO
    notice page and its permit's public-notice clauses are added to its row.
  - Idempotent: every row with state AK is rebuilt; other states' rows are left as they are; the Alaska rows are
    written after the last row of the file in id order.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "ak" / "dischargers.json"
CHECKED = "2026-11-07"
SOBE_FILERS = {"AK0022551": 43, "AK0021440": 2, "AK0053775": 1}   # current reports in the 2026-11-04 extract
LAW = ("No Alaska statute or rule requires public notice of a sewer overflow or bypass. 18 AAC 72.940 requires the "
       "owner or operator of a wastewater system to report to the Department of Environmental Conservation (DEC) "
       "within 24 hours when a spill or other event threatens public health or water quality, when a sludge "
       "carry-over, washout or overflow occurs, or when part of the treatment works is bypassed, and to send a "
       "written report within seven days; the APDES permits' standard conditions (Appendix A, Part 3.4) require an "
       "oral report within 24 hours and a written report within five days. DEC does not post the reports.")
SOBE = (" This operator files its reports through EPA's NeT-SewerOverflow, so they are published in EPA's sewer "
        "overflow tables (ECHO), a median one day after the start for Alaska's reports.")
NO_SOBE = " Its reports were not found in EPA's sewer overflow tables; the operator's own pages were not searched."
JUNEAU_PAGE = "https://juneau.org/engineering-public-works/wastewater-utility"
JUNEAU = (" Permit AK0023213 (EPA-issued 2001, administratively continued) Part I.D.1.g: \"The permittee must ensure "
          "that the public receives adequate notification of CSO occurrences and CSO impacts\"; Part III.H.2.a: "
          "notification of the public of sewer overflows that may imminently and substantially endanger human health, "
          "under its overflow emergency response plan. The City and Borough's wastewater utility page lists its CSO "
          f"public notices as PDFs (the last from November 2005; the page says no CSO has occurred since 2005): "
          f"{JUNEAU_PAGE}.")

# permit -> row id. Rows: id -> (name, short_name, legal_form, kind, note)
PERMITS = {
    "AK0022551": "ak-awwu-anchorage", "AK0022543": "ak-awwu-anchorage", "AK0047856": "ak-awwu-anchorage",
    "AKG002440": "ak-awwu-anchorage",
    "AK0023213": "ak-juneau-douglas", "AK0022951": "ak-juneau-douglas", "AKG572004": "ak-juneau-douglas",
    "AK0021440": "ak-ketchikan", "AK0053775": "ak-denali-np", "AK0023451": "ak-fairbanks-ghu",
    "AKG320002": "ak-apsc-taps",
    "AK0020010": "ak-skagway", "AK0020036": "ak-soldotna", "AK0020648": "ak-uscg-kodiak", "AK0021245": "ak-homer",
    "AK0021377": "ak-kenai", "AK0021385": "ak-haines", "AK0021393": "ak-north-pole", "AK0021431": "ak-valdez",
    "AK0021458": "ak-petersburg", "AK0021466": "ak-wrangell", "AK0021474": "ak-sitka", "AK0021547": "ak-cordova",
    "AK0021555": "ak-kodiak", "AK0021890": "ak-seward", "AK0053724": "ak-seward", "AK0022497": "ak-palmer",
    "AK0025402": "ak-whittier", "AK0043451": "ak-unalaska", "AK0043532": "ak-pelican", "AK0053813": "ak-metlakatla",
    "AK0053384": "ak-ward-cove-full-cycle",
    "AKG527721": "ak-saint-paul", "AKG570023": "ak-koyuk", "AKG571012": "ak-bia-annette-bay",
    "AKG571038": "ak-ketchikan-gateway-borough", "AKG572028": "ak-ketchikan-gateway-borough",
    "AKG571051": "ak-deering",
    "AKG571056": "ak-north-slope-borough", "AKG572001": "ak-north-slope-borough", "AKG572006": "ak-north-slope-borough",
    "AKG572024": "ak-north-slope-borough", "AKG572032": "ak-north-slope-borough", "AKG572033": "ak-north-slope-borough",
    "AKG572036": "ak-north-slope-borough", "AKG572048": "ak-north-slope-borough", "AKG572071": "ak-north-slope-borough",
    "AKG573038": "ak-north-slope-borough",
    "AKG572005": "ak-lower-kuskokwim-sd", "AKG572023": "ak-lower-kuskokwim-sd", "AKG572026": "ak-lower-kuskokwim-sd",
    "AKG572098": "ak-lower-kuskokwim-sd", "AKG572141": "ak-lower-kuskokwim-sd",
    "AKG572007": "ak-nps-glacier-bay", "AKG572019": "ak-forest-park-ketchikan", "AKG572020": "ak-usfs-kake",
    "AKG572022": "ak-hoonah", "AKG572025": "ak-northwest-arctic-borough-sd", "AKG572130": "ak-northwest-arctic-borough-sd",
    "AKG572027": "ak-kenai-peninsula-borough-sd", "AKG572031": "ak-nenana", "AKG572043": "ak-dot-marine-highway",
    "AKG572045": "ak-thorne-bay",
    "AKG572056": "ak-bering-strait-sd", "AKG573024": "ak-bering-strait-sd", "AKG573034": "ak-bering-strait-sd",
    "AKG572072": "ak-schlumberger-east-camp", "AKG572077": "ak-ljdjh-yellowjacket", "AKG572085": "ak-usaf-cape-newenham",
    "AKG572088": "ak-unalakleet-river-lodge", "AKG572111": "ak-steelhead-barge", "AKG572115": "ak-newtok-village-council",
    "AKG572116": "ak-norton-sound-health-corporation",
    "AKG573001": "ak-alakanuk", "AKG573002": "ak-chuathbaluk", "AKG573003": "ak-cold-bay", "AKG573004": "ak-dillingham",
    "AKG573005": "ak-usaf-eareckson", "AKG573006": "ak-emmonak", "AKG573007": "ak-doyon-utilities",
    "AKG573008": "ak-kongiganak-traditional-council",
    "AKG573010": "ak-bristol-bay-borough", "AKG573029": "ak-bristol-bay-borough",
    "AKG573011": "ak-napaskiak", "AKG573012": "ak-noatak", "AKG573013": "ak-nightmute", "AKG573014": "ak-pilot-station",
    "AKG573016": "ak-st-marys", "AKG573019": "ak-selawik", "AKG573020": "ak-shishmaref", "AKG573025": "ak-togiak",
    "AKG573027": "ak-white-mountain", "AKG573028": "ak-buckland", "AKG573030": "ak-kipnuk",
    "AKG573031": "ak-mountain-village", "AKG573033": "ak-mat-su-borough",
    "AKG573037": "ak-galena", "AKG573039": "ak-kasigluk-traditional-council", "AKG573041": "ak-kasigluk-traditional-council",
    "AKG573040": "ak-shageluk", "AKG573043": "ak-tetlin", "AKG573044": "ak-rampart",
}
ROWS = {
    "ak-awwu-anchorage": ("Anchorage Water and Wastewater Utility (Municipality of Anchorage: Asplund, Eagle River and "
                          "Girdwood plants and the collection system)", "Anchorage Water and Wastewater Utility", "city",
                          "sso", "AKG002440 (a sewer service repair in Anchorage, EPA type municipal) is the "
                          "utility's: it is Anchorage's only public sewer utility."),
    "ak-juneau-douglas": ("City and Borough of Juneau (Juneau-Douglas, Mendenhall and Auke Bay plants)",
                          "City and Borough of Juneau", "city", "cso", None),
    "ak-ketchikan": ("City of Ketchikan", "City of Ketchikan", "city", "sso", None),
    "ak-denali-np": ("National Park Service, Denali National Park and Preserve (front country lagoon)",
                     "Denali National Park and Preserve", "federal facility", "sso", None),
    "ak-fairbanks-ghu": ("Golden Heart Utilities, Inc. (Fairbanks; permit held with the City of Fairbanks)",
                         "Golden Heart Utilities", "investor-owned utility", "plant",
                         "EPA types the permit mixed ownership and names the City of Fairbanks and Golden Heart "
                         "Utilities, Inc.; the company is the private utility that runs Fairbanks's sewer service."),
    "ak-apsc-taps": ("Alyeska Pipeline Service Company: Trans-Alaska Pipeline System (inventory record)",
                     "Alyeska Pipeline Service Company", "business or industrial", "cso_closed_or_none",
                     "A general permit for pipeline facilities that EPA's CSO inventory lists with one outfall; not a "
                     "sewer system. No notice channel is claimed for it."),
    "ak-skagway": ("Municipality of Skagway", None, "city", "plant", None),
    "ak-soldotna": ("City of Soldotna", None, "city", "plant", None),
    "ak-uscg-kodiak": ("U.S. Coast Guard, Base Kodiak", None, "federal facility", "plant", None),
    "ak-homer": ("City of Homer", None, "city", "plant", None),
    "ak-kenai": ("City of Kenai", None, "city", "plant", None),
    "ak-haines": ("Municipality of Haines", None, "city", "plant", None),
    "ak-north-pole": ("City of North Pole", None, "city", "plant", None),
    "ak-valdez": ("City of Valdez", None, "city", "plant", None),
    "ak-petersburg": ("City of Petersburg", None, "city", "plant", None),
    "ak-wrangell": ("City of Wrangell", None, "city", "plant", None),
    "ak-sitka": ("City and Borough of Sitka", None, "city", "plant", None),
    "ak-cordova": ("City of Cordova", None, "city", "plant", None),
    "ak-kodiak": ("City of Kodiak", None, "city", "plant", None),
    "ak-seward": ("City of Seward (Lowell Point and Spring Creek plants)", "City of Seward", "city", "plant", None),
    "ak-palmer": ("City of Palmer", None, "city", "plant", None),
    "ak-whittier": ("City of Whittier", None, "city", "plant", None),
    "ak-unalaska": ("City of Unalaska", None, "city", "plant", None),
    "ak-pelican": ("City of Pelican", None, "city", "plant", None),
    "ak-metlakatla": ("Metlakatla Indian Community", None, "tribal", "plant", None),
    "ak-ward-cove-full-cycle": ("Full Cycle - Power Systems and Supplies of Alaska, LLC (Ward Cove Industrial Site "
                                "plant)", "Full Cycle - Power Systems and Supplies of Alaska", "business or industrial",
                                "plant", "Privately owned: a company's plant serving an industrial site (EPA facility "
                                "type Corporation; SIC 4952); the permittee as DEC's permit notice names it. Not in "
                                "the plant outfall table."),
    "ak-saint-paul": ("City of Saint Paul", None, "city", "plant", None),
    "ak-koyuk": ("City of Koyuk", None, "city", "plant", None),
    "ak-bia-annette-bay": ("U.S. Bureau of Indian Affairs (Annette Bay plant, Metlakatla)", None, "federal facility",
                           "plant", None),
    "ak-ketchikan-gateway-borough": ("Ketchikan Gateway Borough (Mountain Point and Waterfall Creek plants)",
                                     "Ketchikan Gateway Borough", "county", "plant", None),
    "ak-deering": ("City of Deering", None, "city", "plant", None),
    "ak-north-slope-borough": ("North Slope Borough", None, "county", "plant", None),
    "ak-lower-kuskokwim-sd": ("Lower Kuskokwim School District (school plants)", "Lower Kuskokwim School District",
                              "special district", "plant",
                              "AKG572141 (the Napakiak school, EPA type school district) is joined here: Napakiak's "
                              "school is in this district."),
    "ak-nps-glacier-bay": ("National Park Service, Glacier Bay National Park and Preserve (Bartlett Cove)", None,
                           "federal facility", "plant", None),
    "ak-forest-park-ketchikan": ("Forest Park plant (Ketchikan)", None, None, "plant",
                                 "EPA's record names the facility only (type NON-POTW); the permittee is not stated."),
    "ak-usfs-kake": ("U.S. Forest Service, Kake administrative site", None, "federal facility", "plant", None),
    "ak-hoonah": ("City of Hoonah", None, "city", "plant", None),
    "ak-northwest-arctic-borough-sd": ("Northwest Arctic Borough School District (school plants)",
                                       "Northwest Arctic Borough School District", "special district", "plant",
                                       "AKG572130 (the Kivalina school, EPA type school district) is joined here: the "
                                       "district runs the borough's schools."),
    "ak-kenai-peninsula-borough-sd": ("Kenai Peninsula Borough School District (McNeil Canyon school)",
                                      "Kenai Peninsula Borough School District", "special district", "plant", None),
    "ak-nenana": ("City of Nenana", None, "city", "plant", None),
    "ak-dot-marine-highway": ("Alaska Department of Transportation and Public Facilities, Alaska Marine Highway System "
                              "(Sitka ferry terminal)", "Alaska Marine Highway System", "state facility", "plant", None),
    "ak-thorne-bay": ("City of Thorne Bay", None, "city", "plant", None),
    "ak-bering-strait-sd": ("Bering Strait School District (school plants)", "Bering Strait School District",
                            "special district", "plant", None),
    "ak-schlumberger-east-camp": ("Schlumberger Oilfield Services (East Camp, Prudhoe Bay)", "Schlumberger",
                                  "business or industrial", "plant", "Privately owned: a work camp's plant."),
    "ak-ljdjh-yellowjacket": ("LJDJH, LLC (Yellowjacket Oilfield Services camp, Prudhoe Bay)", "LJDJH, LLC",
                              "business or industrial", "plant", "Privately owned: a work camp's plant."),
    "ak-usaf-cape-newenham": ("U.S. Air Force, Cape Newenham Long Range Radar Site", None, "federal facility", "plant",
                              None),
    "ak-unalakleet-river-lodge": ("Unalakleet River Lodge", None, "campground or resort", "plant",
                                  "Privately owned: a lodge's plant (EPA facility type Corporation)."),
    "ak-steelhead-barge": ("Steelhead Barge plant (federal facility, Anchorage)", None, "federal facility", "plant",
                           "EPA types it a federal facility and names the barge, not the agency."),
    "ak-newtok-village-council": ("Newtok Village Council (Mertarvik)", None, "tribal", "plant", None),
    "ak-norton-sound-health-corporation": ("Norton Sound Health Corporation (Diomede clinic)", None, "institution",
                                           "plant", "A regional tribal health organization's clinic plant (EPA "
                                           "facility type Corporation)."),
    "ak-alakanuk": ("City of Alakanuk", None, "city", "plant", None),
    "ak-chuathbaluk": ("City of Chuathbaluk", None, "city", "plant", None),
    "ak-cold-bay": ("City of Cold Bay", None, "city", "plant", None),
    "ak-dillingham": ("City of Dillingham", None, "city", "plant", None),
    "ak-usaf-eareckson": ("U.S. Air Force, Eareckson Air Station (Shemya Island)", None, "federal facility", "plant",
                          None),
    "ak-emmonak": ("City of Emmonak", None, "city", "plant", None),
    "ak-doyon-utilities": ("Doyon Utilities, LLC (Fort Greely)", "Doyon Utilities", "investor-owned utility", "plant",
                           "Privately owned: the company that runs the post's utilities."),
    "ak-kongiganak-traditional-council": ("Kongiganak Traditional Council", None, "tribal", "plant", None),
    "ak-bristol-bay-borough": ("Bristol Bay Borough (Naknek and King Salmon lagoons)", "Bristol Bay Borough", "county",
                               "plant", None),
    "ak-napaskiak": ("Native Village of Napaskiak", None, "tribal", "plant", None),
    "ak-noatak": ("Native Village of Noatak", None, "tribal", "plant", None),
    "ak-nightmute": ("City of Nightmute", None, "city", "plant", None),
    "ak-pilot-station": ("City of Pilot Station", None, "city", "plant", None),
    "ak-st-marys": ("City of St. Mary's", None, "city", "plant", None),
    "ak-selawik": ("City of Selawik", None, "city", "plant", None),
    "ak-shishmaref": ("City of Shishmaref", None, "city", "plant", None),
    "ak-togiak": ("City of Togiak", None, "city", "plant", None),
    "ak-white-mountain": ("City of White Mountain", None, "city", "plant", None),
    "ak-buckland": ("City of Buckland", None, "city", "plant", None),
    "ak-kipnuk": ("Native Village of Kipnuk", None, "tribal", "plant", None),
    "ak-mountain-village": ("City of Mountain Village", None, "city", "plant", None),
    "ak-mat-su-borough": ("Matanuska-Susitna Borough (Talkeetna lagoon)", "Matanuska-Susitna Borough", "county", "plant",
                          "EPA types the permit county government; Talkeetna lies in the borough."),
    "ak-galena": ("City of Galena", None, "city", "plant", None),
    "ak-kasigluk-traditional-council": ("Kasigluk Traditional Council", None, "tribal", "plant", None),
    "ak-shageluk": ("City of Shageluk", None, "city", "plant", None),
    "ak-tetlin": ("Tetlin tribal government (Tetlin lagoon)", None, "tribal", "plant",
                  "EPA types the permit tribal government; its permit name is a person's and is not used."),
    "ak-rampart": ("Rampart tribal government (Rampart plant)", None, "tribal", "plant",
                   "EPA types the permit tribal government and names the facility only."),
}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}
EXTRA = {   # permits held by a row that are in neither EPA table: permit -> (facility, city, waters)
    "AK0053384": ("WARD COVE INDUSTRIAL SITE WW TREATMENT FACILITY", "KETCHIKAN", ["Ward Cove"]),
}


def title(s: str) -> str:
    s = (s or "").strip()
    return s.title() if s.isupper() or s.islower() else s


def load_epa() -> dict[str, dict]:
    """permit -> {facility, city, waters, outfalls, open_cso}; EPA's permit name is not kept (it may be a person)."""
    out: dict[str, dict] = {}
    for f in ("outfalls-plants-us.json", "outfalls-us.json"):
        doc = json.loads((ROOT / "data" / f).read_text())
        for r in doc["outfalls"] if isinstance(doc, dict) else doc:
            p = str(r.get("npdes_permit") or "").upper()
            if not p.startswith("AK") or r.get("state") not in (None, "AK"):
                continue
            o = out.setdefault(p, {"facility": None, "city": None, "waters": [], "outfalls": 0, "open_cso": 0,
                                   "files": set()})
            o["facility"] = o["facility"] or r.get("permittee")
            o["city"] = o["city"] or r.get("city")
            w = (r.get("receiving_water_echo") or "").strip()
            if w and w not in o["waters"]:
                o["waters"].append(w)
            o["outfalls"] += 1
            o["files"].add(f)
            if f == "outfalls-us.json" and not str(r.get("outfall_status") or "").upper().startswith("CLS"):
                o["open_cso"] += 1
    for p, (fac, city, waters) in EXTRA.items():
        out.setdefault(p, {"facility": fac, "city": city, "waters": waters, "outfalls": 0, "open_cso": 0,
                           "files": set()})
    return out


def channel(rid: str, permits: list[str], kind: str) -> str:
    if kind == "cso_closed_or_none":
        return "None: not a sewer system (a pipeline general permit in EPA's CSO inventory)."
    filers = [p for p in permits if p in SOBE_FILERS]
    text = LAW + (SOBE if filers else NO_SOBE)
    if rid == "ak-juneau-douglas":
        text += JUNEAU
    return text


def build(epa: dict[str, dict], research: list[dict]) -> tuple[list[dict], dict]:
    missing = sorted(set(epa) - set(PERMITS))
    if missing:
        raise SystemExit(f"Alaska permits with no row: {missing}")
    groups: dict[str, list[str]] = {}
    for p in sorted(epa):
        groups.setdefault(PERMITS[p], []).append(p)
    res = {r["id"]: r for r in research}
    rows = []
    for rid, permits in sorted(groups.items()):
        name, short, lf, kind, why = ROWS[rid]
        r0 = res.get(rid)
        if r0 and r0["npdes_permit"] in permits:   # the research's permit first
            permits = [r0["npdes_permit"]] + [p for p in permits if p != r0["npdes_permit"]]
        towns = sorted({title(epa[p]["city"]) for p in permits if epa[p].get("city")})
        if r0:
            towns = list(dict.fromkeys((r0.get("towns") or []) + towns))
        waters = list(dict.fromkeys(([] if not r0 else r0.get("receiving_waters") or [])
                                    + [w for p in permits for w in epa[p]["waters"]]))
        n_out = sum(epa[p]["outfalls"] for p in permits)
        n_cso = sum(epa[p]["open_cso"] for p in permits)
        facs = "; ".join(f"{p} {epa[p]['facility']}" for p in permits)
        note = f"EPA ECHO ICIS-NPDES: {facs}."
        if lf in PRIVATE_FORMS and not (why or "").startswith("Privately owned"):
            note = "Privately owned. " + note
        if why:
            note += " " + why
        if r0:
            note += f" Research row (research/ak/dischargers.json, checked {r0.get('checked')})."
        filed = sum(SOBE_FILERS.get(p, 0) for p in permits)
        if filed:
            note += f" EPA's sewer overflow tables: {filed} current reports (2026-11-04 extract)."
        row = {"id": rid, "name": name, "state": "AK", "kind": kind, "npdes_permit": permits[0],
               "npdes_permits": permits, "receiving_waters": waters, "water_slugs": [], "outfall_count": n_out or None,
               "outfalls_source": ("EPA ECHO ICIS-NPDES discharge points and the national CSO inventory "
                                   f"(data/outfalls-plants-us.json, data/outfalls-us.json: {n_out} rows for these "
                                   f"permits, {n_cso} open CSO outfalls)" if n_cso else
                                   "EPA ECHO ICIS-NPDES discharge points (data/outfalls-plants-us.json: "
                                   f"{n_out} rows for these permits)") if n_out else None,
               "notification_channel": channel(rid, permits, kind),
               "notification_feed_machine_readable": bool(filed),
               "notification_signup_url": None, "towns": towns, "notes": note,
               "verified": "fetched", "checked": CHECKED, "aliases": [rid],
               "source_areas": ["ak"] + ([] if r0 else ["federal"])}
        if short:
            row["short_name"] = short
        if lf:
            row["legal_form"] = lf
        rows.append(row)
    stats = {"rows": len(rows), "permits": sum(len(r["npdes_permits"]) for r in rows),
             "by_form": dict(Counter(r.get("legal_form") for r in rows)),
             "by_kind": dict(Counter(r["kind"] for r in rows)),
             "private": sorted(r["id"] for r in rows if r.get("legal_form") in PRIVATE_FORMS)}
    return rows, stats


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    research = json.loads(RESEARCH.read_text())
    new, stats = build(load_epa(), research)
    unused = sorted(set(ROWS) - {r["id"] for r in new})
    if unused:
        raise SystemExit(f"rows with no permit: {unused}")
    others = [r for r in dis if r.get("state") != "AK"]
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
