"""Washington operator rows for data/dischargers.json: one row per operator, every Washington permit of the outfall
registry in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_wa_operators.py [--dry-run]

Inputs
  - research/wa/dischargers.json (14 rows): the CSO permittees of EPA's inventory and the operators the research named
    (King County, Seattle, Spokane, JBLM, Puyallup, Tacoma ...). Each keeps its research id. Port Angeles' second
    inventory permit (WAG994562) joins its row; Sound Transit's construction stormwater permit, which EPA's CSO inventory
    lists, is kind "cso_closed_or_none" (not a sewer system).
  - data/outfalls-plants-us.json and data/outfalls-us.json: every Washington permit EPA lists (262 plant permits, 12 CSO
    inventory permits). permit_name is the owner as EPA records it; the permits of one owner are one row (OWNERS joins
    the spellings of one owner and names the owner when EPA records a contractor or a plant).
  - research/wa/private-utilities-candidates.json (EPA's private sewage permits, 10, and 6 public bodies EPA types
    private): PRIVATE files each with the facility as Ecology's PARIS permit search names it (read 2026-11-04 with the
    project user agent), legal_form from the controlled list, and never an individual's name. The six public bodies
    are cities.
Rules
  - legal_form from the controlled list (docs/legal-forms.md): OWNERS by hand, else form() from the owner's name, else
    null (a plant name that does not say who owns it).
  - name: OWNERS, else the owner as EPA spells it, put in order ("BURLINGTON CITY" -> "City of Burlington").
  - notification_channel: Ecology's sewage spill list (RCW 90.48.636), which posts every spill reported under an
    individual permit; the operator's own channels where the research found them (King County and Seattle's CSO status
    map, Spokane's CSO page). notification_signup_url null: Washington has no overflow e-mail list (the bill's
    notification system was cut). An EPA-issued permit (JBLM) reports to EPA, not Ecology: its row says so.
  - Idempotent: every row with state WA is rebuilt; other states' rows are left as they are; the Washington rows are
    written after the last row of the file in id order.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "wa" / "dischargers.json"
CANDIDATES = ROOT / "research" / "wa" / "private-utilities-candidates.json"
CHECKED = "2026-11-04"
SPILLS = "https://ecology.wa.gov/water-shorelines/water-quality/wastewater/sewage-spills"
LAW = (f"Ecology's sewage spill list (RCW 90.48.636): Ecology posts each sewage spill reported under the operator's "
       f"individual permit, with its volume, treatment level, start, end once known and the area potentially "
       f"affected, aiming at five working days after the report: {SPILLS}.")
OWN_PAGES = " The operator's own pages were not searched individually."
KC_MAP = ("King County's CSO status map and file, updated every 10 minutes for King County's and Seattle's CSO "
          "outfalls (https://kingcounty.gov/en/dept/dnrp/waste-services/wastewater-treatment/sewer-system-services/"
          "cso-status); signs at the outfalls.")
CHANNEL = {
    "wa-king-county-west-point": LAW + " " + KC_MAP,
    "wa-seattle-spu": LAW + " " + KC_MAP,
    "wa-spokane": LAW + (" Spokane's real-time CSO page (https://sewerfinder.spokanecity.org/CSOUpdate) shows each "
                         "overflow's start for 48 hours; it refused the project user agent (403) on 2026-11-04."),
    "wa-jblm": ("EPA's eRule overflow reports (WA0021954 is an EPA-issued federal-facility permit: its reports go to EPA "
                "Region 10, so Ecology's list need not carry them). No public channel of the operator was found."),
}
# research id -> extra permits, kind, legal_form, short_name, name override
RESEARCH_ROWS = {
    "wa-king-county-west-point": (["WA0029581", "WA0032247", "WA0022527", "WA0032182", "WAR002511", "WAR125522"],
                                  "cso", "county", "King County Wastewater Treatment Division",
                                  "King County Wastewater Treatment Division (West Point, South, Brightwater, Vashon "
                                  "and Carnation plants and King County's CSOs)"),
    "wa-seattle-spu": ([], "cso", "city", "Seattle Public Utilities", "Seattle Public Utilities (combined sewer system)"),
    "wa-spokane": ([], "cso", "city", "City of Spokane", None),
    "wa-bremerton": (["WAR310854"], "cso", "city", "City of Bremerton", None),
    "wa-snohomish": ([], "cso", "city", "City of Snohomish", None),
    "wa-lott": ([], "cso", "authority", "LOTT Clean Water Alliance",
                "LOTT Clean Water Alliance (Budd Inlet Water Reclamation Facility; Lacey, Olympia, Tumwater and "
                "Thurston County)"),
    "wa-everett": ([], "cso", "city", "City of Everett", None),
    "wa-port-angeles": (["WAG994562"], "cso", "city", "City of Port Angeles", None),
    "wa-mount-vernon": ([], "cso", "city", "City of Mount Vernon", None),
    "wa-anacortes": ([], "cso", "city", "City of Anacortes", None),
    "wa-sound-transit-east-link": ([], "cso_closed_or_none", "authority", "Sound Transit",
                                   "Sound Transit (East Link construction stormwater permit in EPA's CSO inventory)"),
    "wa-jblm": ([], "sso", "federal facility", "Joint Base Lewis-McChord",
                "Joint Base Lewis-McChord sewer system (American Water Military Services, the permittee)"),
    "wa-puyallup": ([], "sso", "city", "City of Puyallup", None),
    "wa-tacoma": (["WA0037214", "WAR000711"], "sso", "city", "City of Tacoma Environmental Services", None),
}
# EPA permit_name -> (row id, name, legal_form): one owner's spellings joined, a contractor or plant named for its owner
OWNERS = {
    "Jacobs": ("wa-walla-walla", "City of Walla Walla (Walla Walla Water Reclamation Facility)", "city",
               "EPA records the plant's contract operator as permit name; Ecology lists the City's plant"),
    "Water & Wastewater Services": ("wa-skagit-county-sewer-district-2", "Skagit County Sewer District No. 2 (Big Lake)",
                                    "special district", "EPA records a services name; the plant is the district's"),
    "SEATTLE CITY LIGHT DIABLO WWTP": ("wa-seattle-city-light", "Seattle City Light (Skagit project camps)", "city", None),
    "Seattle City Light": ("wa-seattle-city-light", "Seattle City Light (Skagit project camps)", "city", None),
    "Kitsap Co Dept of Public Works": ("wa-kitsap-county", "Kitsap County Public Works (Sewer Utility)", "county", None),
    "Kitsap County Dept Public Works": ("wa-kitsap-county", "Kitsap County Public Works (Sewer Utility)", "county", None),
    "Kitsap County Dept of Public Works": ("wa-kitsap-county", "Kitsap County Public Works (Sewer Utility)", "county", None),
    "Kitsap County Public Works": ("wa-kitsap-county", "Kitsap County Public Works (Sewer Utility)", "county", None),
    "Public Utility District #1 of Kitsap County": ("wa-kitsap-pud", "Public Utility District No. 1 of Kitsap County "
                                                    "(Kitsap County Sewer District No. 7 plant)", "special district", None),
    "King County Wastewater Treatment Division": ("wa-king-county-west-point", None, "county", None),
    "King County Dept of Natural Resources and Parks": ("wa-king-county-west-point", None, "county", None),
    "Clallam County Public Works": ("wa-clallam-county", "Clallam County Public Works", "county", None),
    "Clallam County Public Works Department": ("wa-clallam-county", "Clallam County Public Works", "county", None),
    "Cowlitz County Public Works": ("wa-cowlitz-county", "Cowlitz County Public Works", "county", None),
    "Cowlitz County Public Works--Ryderwood": ("wa-cowlitz-county", "Cowlitz County Public Works", "county", None),
    "Department of Corrections": ("wa-doc", "Washington State Department of Corrections", "state facility", None),
    "Washington State Department of Corrections": ("wa-doc", "Washington State Department of Corrections",
                                                   "state facility", None),
    "McNeil Island Stewardship WA Dept of Corrections": ("wa-doc", "Washington State Department of Corrections",
                                                         "state facility", None),
    "Department of Social and Health Services": ("wa-dshs", "Washington State Department of Social and Health Services",
                                                 "state facility", None),
    "Wa State Parks & Recreation Commission": ("wa-state-parks", "Washington State Parks and Recreation Commission",
                                               "state facility", None),
    "Washington State Parks & Recreation Commission": ("wa-state-parks", "Washington State Parks and Recreation "
                                                       "Commission", "state facility", None),
    "Chelan Co PUD #1 Lake Wenatchee": ("wa-chelan-county-pud", "Chelan County Public Utility District No. 1",
                                        "special district", None),
    "Chelan County PUD No. 1": ("wa-chelan-county-pud", "Chelan County Public Utility District No. 1",
                                "special district", None),
    "LUMMI INDIAN BUSINESS COUNCIL": ("wa-lummi-nation", "Lummi Nation (Lummi Indian Business Council; Lummi Tribal "
                                      "Sewer and Water District)", "tribal", None),
    "LUMMI TRIBAL SEWER AND WATER": ("wa-lummi-nation", "Lummi Nation (Lummi Indian Business Council; Lummi Tribal "
                                     "Sewer and Water District)", "tribal", None),
    "MOCLIPS RIVER ESTATES WWTP": ("wa-quinault-indian-nation", "Quinault Indian Nation", "tribal", None),
    "QUEETS VILLAGE WWTP": ("wa-quinault-indian-nation", "Quinault Indian Nation", "tribal", None),
    "TAHOLAH VILLAGE WWTP": ("wa-quinault-indian-nation", "Quinault Indian Nation", "tribal", None),
    "SWINOMISH INDIAN TRIBAL COMMUN": ("wa-swinomish", "Swinomish Indian Tribal Community", "tribal", None),
    "SWINOMISH RESERVATION SWR DIST": ("wa-swinomish", "Swinomish Indian Tribal Community", "tribal", None),
    "TULALIP TRIBES OF WASHINGTON": ("wa-tulalip-tribes", "Tulalip Tribes of Washington (Tulalip Utilities)", "tribal", None),
    "YAKAMA NATION LEGENDS CASINO": ("wa-yakama-nation", "Yakama Nation (Legends Casino plant)", "tribal", None),
    "Cowlitz Tribal Member Services": ("wa-cowlitz-indian-tribe", "Cowlitz Indian Tribe (tribal housing plant)", "tribal",
                                       None),
    "SCRWRF": ("wa-spokane-county", "Spokane County (Spokane County Regional Water Reclamation Facility)", "county", None),
    "Medical Lake WRF": ("wa-medical-lake", "City of Medical Lake", "city", None),
    "College Place Stp": ("wa-college-place", "City of College Place", "city", None),
    "Snoqualmie Wastewater & Water Reclamation Facility": ("wa-snoqualmie", "City of Snoqualmie", "city", None),
    "Yakima Regional POTW": ("wa-yakima", "City of Yakima (Yakima Regional Wastewater Treatment Plant)", "city", None),
    "PUYALLUP STP": ("wa-puyallup", None, "city", None),
    "City of Tacoma": ("wa-tacoma", None, "city", None),
    "LOTT Clean Water Alliance": ("wa-lott", None, "authority", None),
    "City of Bremerton WWTP": ("wa-bremerton", None, "city", None),
    "AMERICAN WATER MILITARY SERVICES - JBLM": ("wa-jblm", None, "federal facility", None),
    "Grant PUD": ("wa-grant-pud", "Public Utility District No. 1 of Grant County", "special district", None),
    "DEFENSE, NAVY": ("wa-navy-indian-island", "U.S. Navy, Naval Magazine Indian Island", "federal facility", None),
    "NAVAL AIR STATION WHIDBEY ISLAND": ("wa-nas-whidbey-island", "U.S. Navy, Naval Air Station Whidbey Island",
                                         "federal facility", None),
    "NATIONAL PARK SERVICE": ("wa-mount-rainier-np", "National Park Service, Mount Rainier National Park (Paradise)",
                              "federal facility", None),
    "INTERIOR, RECLAMATION": ("wa-usbr-grand-coulee", "U.S. Bureau of Reclamation, Grand Coulee Dam", "federal facility",
                              None),
    "US ARMY YAKIMA TRAINING CENTER": ("wa-yakima-training-center", "U.S. Army Yakima Training Center",
                                       "federal facility", None),
    "Port of Kalama": ("wa-port-of-kalama", "Port of Kalama", "special district", None),
    "Port of Sunnyside": ("wa-port-of-sunnyside", "Port of Sunnyside (industrial wastewater plant)", "special district",
                          None),
    "Olympic Property Group": ("wa-port-gamble", "Olympic Property Group (Port Gamble plant)", "business or industrial",
                               "EPA types the permit NON-POTW and the owner a company; Ecology's PARIS was not read for it"),
}
# permit -> (row id, name, legal_form, towns, note): EPA's private sewage permits, the facility as PARIS names it
PRIVATE = {
    "WA0021202": ("wa-olympic-water-and-sewer", "Olympic Water & Sewer, Inc. (Port Ludlow plant)", "investor-owned utility",
                  ["Port Ludlow"], "PARIS: OLYMPIC WATER & SEWER INC; a company whose business is water and sewer service."),
    "WA0021822": ("wa-roche-harbor-utilities", "Roche Harbor Utilities (Roche Harbor Resort plant)", "investor-owned utility",
                  ["Friday Harbor"], "PARIS: ROCHE HARBOR RESORT; EPA records Roche Harbor Utilities as permittee."),
    "WA0023469": ("wa-messenger-house", "Cascadia Holding Bainbridge LLC (Messenger House Care Center plant)",
                  "institution", ["Bainbridge Island"],
                  "PARIS: MESSENGER HOUSE CARE CTR; a care center's own plant, held by a company."),
    "WA0029891": ("wa-washington-water-service-rosario", "Washington Water Service Company (Rosario plant)",
                  "investor-owned utility", ["Eastsound"], "PARIS: ROSARIO WWTP; a water utility company."),
    "WA0029904": ("wa-warm-beach-camp", "Warm Beach Christian Camp and Conference Center", "institution", ["Stanwood"],
                  "PARIS: WARM BEACH CHR CAMP & CONFER CTR (now a reclaimed-water permit in PARIS); a camp."),
    "WA0037079": ("wa-cherrywood-mhp", "Cherrywood Mobile Home Manor", "mobile-home park", ["Puyallup"],
                  "PARIS: CHERRYWOOD MOBILE HOME MANOR."),
    "WA0037273": ("wa-seashore-villa", "Seashore Villa Mobile Home Park (Emerald Properties)", "mobile-home park",
                  ["Olympia"], "PARIS: SEASHORE VILLA STP; EPA records the park and its company."),
    "WA0037656": ("wa-taylor-bay-beach-club", "Taylor Bay Beach Club, Inc.", "private club", ["Longbranch"],
                  "PARIS: TAYLOR BAY STP, at the beach club."),
    "WA0037753": ("wa-alderbrook-resort", "Alderbrook Resort & Spa (North Forty Lodging LLC)", "campground or resort",
                  ["Union"], "PARIS: ALDERBROOK RESORT & SPA."),
    "WA0037915": ("wa-carlyon-beach-hoa", "Carlyon Beach Homeowners Association", "homeowners' association", ["Olympia"],
                  "PARIS: CARLYON BEACH STP; EPA records the homeowners association."),
}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


WORKS = re.compile(r"\s+(POTW|WWTP|STP|WRF)$", re.I)


def title(s: str) -> str:
    s = (s or "").strip()
    if s.isupper() or s.islower():
        s = s.title()
    s = re.sub(r"\b(Wwtp|Stp|Potw|Wrf|Pud)\b", lambda m: m.group(1).upper(), s)
    return re.sub(r"(?<=\w )\b(Of|And|The)\b", lambda m: m.group(1).lower(), s).replace("'S ", "'s ")


def pretty(owner: str) -> str:
    """EPA's owner spelling, put in order: "BURLINGTON CITY" -> "City of Burlington", "COULEE DAM, TOWN OF" -> "Town of
    Coulee Dam", "Waitsburg City of" -> "City of Waitsburg"."""
    s = re.sub(r"\s+", " ", owner or "").strip()
    s = re.sub(r"(?i)^the\s+", "", s)
    if re.match(r"(?i)^(city|town) of\b", s):
        s = WORKS.sub("", s)
    m = re.match(r"^(.*?),?\s+(CITY|TOWN)(?:\s+OF)?$", s, re.I)
    if m and not re.match(r"(?i)^(city|town) of\b", s):
        return f"{m.group(2).title()} of {title(m.group(1))}"
    t = title(s)
    return re.sub(r"^(City|Town) Of\b", lambda m: f"{m.group(1)} of", t)


def form(name: str) -> str | None:
    n = (name or "").lower()
    if re.search(r"\b(tribe|tribal|nation|indian|reservation)\b", n):
        return "tribal"
    if re.search(r"\b(navy|army|air force|national park|reclamation|u\.?s\.? )\b", n):
        return "federal facility"
    if re.search(r"\b(school district|sewer district|water district|utility district|pud\b|public utility district|"
                 r"sewer & water|water & sewer|water-sewer|wastewater district|port of)\b", n):
        return "special district"
    if re.search(r"\bauthority\b", n):
        return "authority"
    if re.search(r"\bcounty\b", n):
        return "county"
    if re.search(r"^town of\b|\btown$|\btown of\b", n):
        return "town"
    if re.search(r"^city of\b|\bcity$|\bcity of\b", n):
        return "city"
    return None


def load_epa() -> dict[str, dict]:
    """permit -> {owner, facility, city, waters, outfalls, files}."""
    out: dict[str, dict] = {}
    for f in ("outfalls-plants-us.json", "outfalls-us.json"):
        doc = json.loads((ROOT / "data" / f).read_text())
        for r in doc["outfalls"] if isinstance(doc, dict) else doc:
            p = str(r.get("npdes_permit") or "").upper()
            if not p.startswith("WA") or (r.get("state") not in (None, "WA")):
                continue
            o = out.setdefault(p, {"owner": None, "facility": None, "city": None, "waters": [], "outfalls": 0,
                                   "files": set(), "open_cso": 0})
            o["owner"] = o["owner"] or r.get("permit_name") or r.get("permittee")
            o["facility"] = o["facility"] or r.get("permittee")
            o["city"] = o["city"] or r.get("city")
            w = (r.get("receiving_water_echo") or "").strip()
            if w and w not in o["waters"]:
                o["waters"].append(w)
            o["outfalls"] += 1
            o["files"].add(f)
            if f == "outfalls-us.json" and not str(r.get("outfall_status") or "").upper().startswith("CLS"):
                o["open_cso"] += 1
    return out


def base_row(rid: str, name: str, permits: list[str], kind: str, legal_form: str | None, towns: list[str],
             waters: list[str], outfalls: int, notes: str, short: str | None = None, research: bool = False) -> dict:
    row = {"id": rid, "name": name, "state": "WA", "kind": kind, "npdes_permit": permits[0] if permits else None,
           "npdes_permits": permits, "receiving_waters": waters, "water_slugs": [], "outfall_count": outfalls or None,
           "outfalls_source": ("EPA ECHO ICIS-NPDES discharge points and the national CSO inventory "
                               f"(data/outfalls-plants-us.json, data/outfalls-us.json: {outfalls} rows for these permits)"
                               if outfalls else None),
           "notification_channel": CHANNEL.get(rid, LAW + OWN_PAGES),
           "notification_feed_machine_readable": True,
           "notification_signup_url": None, "towns": towns, "notes": notes,
           "verified": "fetched", "checked": CHECKED, "aliases": [rid],
           "source_areas": ["wa"] + ([] if research else ["federal"])}
    if short:
        row["short_name"] = short
    if legal_form:
        row["legal_form"] = legal_form
    return row


def build(epa: dict[str, dict], research: list[dict], candidates: dict) -> tuple[list[dict], dict]:
    rows: dict[str, dict] = {}
    held: dict[str, str] = {}
    # 1. the research rows
    for r in research:
        extra, kind, lf, short, name = RESEARCH_ROWS[r["id"]]
        permits = [r["npdes_permit"]] + [p for p in extra if p != r["npdes_permit"]]
        waters = list(dict.fromkeys(r.get("receiving_waters") or []))
        n_out = sum(epa.get(p, {}).get("outfalls", 0) for p in permits)
        note = (r.get("notes") or "").strip()
        note = (note + " " if note else "") + ("Research row (research/wa/dischargers.json, checked "
                                                f"{r.get('checked')}); permits joined from EPA's lists by owner.")
        if r["id"] == "wa-sound-transit-east-link":
            note += " Not a sewer system: no notice channel is claimed for it."
        rows[r["id"]] = base_row(r["id"], name or r["name"], permits, kind, lf, r.get("towns") or [], waters, n_out,
                                 note, short, research=True)
        for p in permits:
            held[p] = r["id"]
    # 2. EPA's permits by owner
    groups: dict[str, list[str]] = defaultdict(list)
    meta: dict[str, tuple] = {}
    for p, o in sorted(epa.items()):
        if p in held:
            continue
        if p in PRIVATE:
            rid, name, lf, towns, note = PRIVATE[p]
            groups[rid].append(p)
            meta[rid] = (name, lf, towns, note + " Permittee checked against Ecology's PARIS permit search (2026-11-04).")
            continue
        owner = o["owner"] or o["facility"] or p
        if owner in OWNERS:
            rid, name, lf, why = OWNERS[owner]
            if rid in rows:                          # joins a research row
                rows[rid]["npdes_permits"].append(p)
                rows[rid]["outfall_count"] = (rows[rid]["outfall_count"] or 0) + o["outfalls"]
                held[p] = rid
                continue
            groups[rid].append(p)
            meta.setdefault(rid, (name, lf, None, why))
            continue
        name = pretty(owner)
        rid = f"wa-{p.lower()}"
        key = slug(name)
        prior = next((k for k, v in meta.items() if v[0] and slug(v[0]) == key), None)
        if prior:
            rid = prior
        groups[rid].append(p)
        pub = candidates.get(p)
        meta.setdefault(rid, (name, form(name), None, "EPA types the permit privately owned; the name is the city's: "
                              "filed as a public body." if pub else None))
    for rid, permits in groups.items():
        name, lf, towns, why = meta[rid]
        towns = towns or sorted({title(epa[p]["city"]) for p in permits if epa[p].get("city")})
        waters = list(dict.fromkeys(w for p in permits for w in epa[p]["waters"]))
        n_out = sum(epa[p]["outfalls"] for p in permits)
        kind = "cso" if any(epa[p]["open_cso"] for p in permits) else "plant"
        facs = "; ".join(f"{p} {epa[p]['facility']}" for p in permits)
        note = (f"EPA ECHO ICIS-NPDES: {facs}. Owner as EPA records it: "
                f"{'; '.join(sorted({str(epa[p]['owner']) for p in permits}))}.")
        if lf in PRIVATE_FORMS:
            note = "Privately owned. " + note
        if why:
            note += " " + why
        rows[rid] = base_row(rid, name, permits, kind, lf, towns, waters, n_out, note)
        for p in permits:
            held[p] = rid
    for r in rows.values():
        r["npdes_permits"] = list(dict.fromkeys(r["npdes_permits"]))
    stats = {"rows": len(rows), "permits": len(held), "by_form": dict(Counter(r.get("legal_form") for r in rows.values())),
             "private": sorted(r["id"] for r in rows.values() if r.get("legal_form") in PRIVATE_FORMS)}
    return sorted(rows.values(), key=lambda r: r["id"]), stats


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    research = json.loads(RESEARCH.read_text())
    cand = json.loads(CANDIDATES.read_text())
    public_by_name = {c["npdes_permit"]: c for c in cand.get("public_by_name") or []}
    new, stats = build(load_epa(), research, public_by_name)
    others = [r for r in dis if r.get("state") != "WA"]
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
