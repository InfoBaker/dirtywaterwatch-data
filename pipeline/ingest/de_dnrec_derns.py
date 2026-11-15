"""Delaware DNREC's Environmental Release Notification System (DERNS): the sewage and sanitary-wastewater releases of
its public Recent Releases list, as dated sewage reports -> data/build/events/de-dnrec-derns-recent-releases.json

Source
  https://derns.dnrec.delaware.gov/Pub/RecentReleases.aspx (registry de-dnrec-derns-recent-releases): an ASP.NET page
  with no login listing every environmental release reported to DNREC under 7 Del. C. 6028, ten rows a page, newest
  first (columns Notification Issued, Release ID, Location, Substance Released, Extremely Hazardous, Release Time,
  Facility, Status), a search by facility, substance, city or zip (a substring match, paged by postback), and a
  detail page per release reached by an ordinary GET (Pub/ReleaseDetail.aspx?ReleaseID=2026-2671: the query key
  differs from the displayed release number 17751; both are kept and the detail address is the one the list links,
  never built from the number). 7,480 releases of every substance listed on 2026-11-14, from 2002.
  The law: anyone causing an environmental release, which for sewage means 10,000 gallons or more (7 Del. C.
  6002(20)), reports it to DNREC as soon as known, and DNREC posts it on its website no later than one business day
  after the report (6028(a)); discharges in compliance with a permit are exempt, so Wilmington's permitted combined
  sewer overflows are not in it. Smaller sewage releases are posted when they are reported, which the law does not
  require: the list is not every spill.

Which rows are read (rules only; no model)
  - The list holds every substance (fuel oil at homes, gasoline, chemicals). Only rows whose Substance Released names
    sewage or sanitary wastewater (CANDIDATE) are kept at all; every other row is counted and dropped before anything
    is saved.
  - SEWAGE: the substance names sewage, sewer, septic, sanitary waste, grey or gray water, or a plant's mixed liquor:
    a sewage report.
  - WASTEWATER ("WASTEWATER", "WASTE WATER") is DNREC's word for municipal and industrial wastewater alike. It is a
    sewage report when the substance says untreated, raw or partially treated, or when the facility, location or the
    release's own text names a sewer system (a pump or lift station, a manhole, a sewer or force main, a wastewater or
    sewage treatment plant, a county, city or town public works, NOT_INDUSTRIAL aside). It is dropped as industrial
    (reason industrial) when the substance or facility names a process, a poultry or food plant, a chemical or brine
    (INDUSTRIAL), and as unattributed (reason wastewater_unattributed) when nothing ties it to a sewer system: kept in
    meta, never shown. Treated effluent (reason treated_effluent) and grease-trap or oily waste are not sewage reports.
  - meta.counts gives the kept and dropped rows by reason.

Record rules
  - Key: the detail page's query key (2026-2671); raw.release_number is the displayed number (17751).
  - Type: plant_bypass when the facility or location is a treatment plant (TREATMENT_PLANT), cso when the text says
    combined sewer, else sso. raw._type_basis says which.
  - Times, all America/New_York (raw.time_zone): started_at is the Release Date/Time (minute precision; a time of
    exactly midnight is read as the day only, precision day); reported_at the detail's Report Date/Time (when DNREC
    received the report); published_at stays null (DERNS shows no posting time; the law's one business day is the
    latest it may be posted). No end: Release Duration ("Continuous", "2 hours", "Unknown") and DERNS's Status
    ("Final": DNREC's processing state, never an end) are kept in raw only; an end is never derived from them. With no
    end the status build gives the site's caution from the release time, then "end not confirmed".
  - Water: the detail's Released To boxes (Ground, Water, Air) are kept as raw.released_to. A water named in the
    release's own text or location ("into the Christina River", "Calf Run") is waterbody_text (WATER_NAME, never a
    road such as "Creek Road"). When the form marks the release to ground or air only and the text names no water,
    raw.reached_water is false with the reason (kept, listed, placed on no water); a water the text names while the
    form says ground only is placed by the text (raw.reached_water "text": the site's caution only, err on safety).
    No point: DERNS gives none, and a street is never geocoded.
  - County: from the location's ZIP code or town (DE_ZIPS, DE_TOWNS), else null; raw.county is used by the name
    placement and the state page's list.
  - Operator: the facility's or location's words matched against the operators of the registry (OPERATORS); "SPILL
    LOCATION", "ROADWAY" and the like name no operator. A release at a private home (RESIDENCE) names none and keeps
    only its county and town (raw.private_source).
  - Volume: Estimated Quantity when it gives gallons (volume_gal, estimate_flag estimated); a figure in the text when
    the field is empty is kept as volume_text, not as a measurement.
  - advice_text: DNREC's "Precautions" field when it gives one; "None" is not advice.

Lifecycle
  - Each run reads the first PAGES pages of the unfiltered list (the newest releases of every substance) and, when no
    state is kept or with --backfill, every page of each substance search (SEARCH_TERMS). Candidate rows are kept in
    data/build/de-dnrec-derns-state.json (safe fields only) and carried, so a release that leaves the first pages is
    never dropped. Details are read for at most DETAILS_PER_RUN releases a run, newest first, and read again while a
    release is under RECHECK_DAYS old; a changed detail is kept with its earlier version's hash (raw._revisions).
  - A list, a search or a detail page that cannot be read is ok=False: the previous records stay and nothing is
    dropped; a detail page that fails MAX_DETAIL_FAILURES reads is no longer asked for.
  - raw._placement "named_water_only": a release is never geolocated from its street, plant or pump station
    (build/provisional_outfalls.py); only a water its notes name places it.

Privacy: the detail page's Contact Name, Contact Phone, Contact Email and Facility Address are never read; the
Location and the release's text lose every house number (common.strip_house_numbers) and go through common.scrub_text
(emails, telephone numbers, names after a title) before anything is saved; a facility that reads as a person's name
becomes "[name removed]" (common.scrub_discharger); a release at a private home keeps its county and town only.
data/raw keeps only the safe rows of the candidate releases. tests/test_ingest_de.py proves a contact name, an e-mail,
a telephone number and a house number never reach a record.

Cadence: hourly (the list is posted within a business day). Run from pipeline/:
  python -m ingest.de_dnrec_derns [--backfill] [--file saved.json] [--pages N]
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, scrub_text, strip_house_numbers,
                    write_events, write_json)

SOURCE_ID = "de-dnrec-derns-recent-releases"
LIST_URL = "https://derns.dnrec.delaware.gov/Pub/RecentReleases.aspx"
DETAIL_URL = "https://derns.dnrec.delaware.gov/Pub/ReleaseDetail.aspx?ReleaseID={}"
TZ = ZoneInfo("America/New_York")
STATE_PATH = BUILD_DIR / "de-dnrec-derns-state.json"
SAFE_FORMAT = "dww-de-derns-safe/1"
AUTHORITY = "Delaware DNREC, Environmental Release Notification System"
TIMEOUT = (60, 300)
PAUSE_S = 1.5
PAGES = 3
DETAILS_PER_RUN = 40
RECHECK_DAYS = 14
MAX_DETAIL_FAILURES = 3   # a detail page that failed this many reads is no longer asked for (meta counts it)
P = "ctl00$ctl00$ContentPlaceHolderBody$ContentPlaceHolder1$ucReleaseSearch$"
SEARCH_TERMS = ["SEWAGE", "SEWER", "SANITARY", "SEPTIC", "WASTEWATER", "WASTE WATER", "GREY WATER", "GRAY WATER",
                "EFFLUENT", "MIXED LIQUOR"]

# a substance worth keeping at all (everything else is dropped before anything is saved)
CANDIDATE = re.compile(r"sewage|sewer|sanitary|septic|waste\s*-?\s*water|gr[ae]y\s*water|effluent|mixed\s+liquor|MLSS",
                       re.I)
SEWAGE = re.compile(r"(?<!non-)(?<!non )\b(?:sewage|sewer|sanitary|septic|gr[ae]y\s*water|mixed\s+liquor|MLSS)\b", re.I)
WASTEWATER = re.compile(r"waste\s*-?\s*water", re.I)
UNTREATED = re.compile(r"\b(?:un-?\s*treated|raw|partially\s+treated|partly\s+treated)\b", re.I)
TREATED_EFFLUENT = re.compile(r"\b(?:treated|final|chlorinated|unchlorinated|dechlorinated)\s+(?:effluent|waste\s*water)\b|"
                              r"^\W*effluent\W*$|but\s+unchlorinated", re.I)
INDUSTRIAL = re.compile(r"\b(?:process|poultry|chicken|turkey|cheese|dairy|brine|salt|vinyl|polyvinyl|chloride|leachate|"
                        r"refinery|petroleum|oil|grease\s+trap|grease|hazardous|chemical|brewery|cannery|food|DAF|"
                        r"cooling|boiler|scrubber|landfill|plating|acid|caustic|perdue|mountaire|allen\s+harim|"
                        r"formosa|croda|dupont|chemours|valero|pbf|evraz|amtrak|n\.o\.s)\b", re.I)
SEWER_SYSTEM = re.compile(r"\b(?:pump(?:ing)?\s*station|lift\s*station|PS\s*#?\d|manhole|man\s*hole|sewer|sewage|force\s*main|"
                          r"sanitary|wastewater\s+(?:treatment|facility|plant|division)|waste\s+water\s+(?:treatment|"
                          r"facility|plant)|treatment\s+(?:plant|facility|works)|WWTP|WWTF|STP|water\s+reclamation|"
                          r"public\s+works|special\s+services|county|city\s+of|town\s+of|utilities|artesian|tidewater|"
                          r"collection\s+system|cleanout|clean-out|lateral)\b", re.I)
TREATMENT_PLANT = re.compile(r"\b(?:treatment\s+(?:plant|facility|works)|WWTP|WWTF|water\s+reclamation|regional\s+"
                             r"(?:wastewater|resource)|resource\s+recovery|sewage\s+treatment)\b", re.I)
CSO_WORDS = re.compile(r"\bcombined\s+sewer\b|\bCSO\b", re.I)
RESIDENCE = re.compile(r"\b(?:residen(?:ce|tial)|home\s*owner|homeowner|private\s+(?:home|property|residence|septic)|"
                       r"(?:his|her|their|the)\s+(?:home|house|yard|basement)|in\s+(?:the\s+)?basement|"
                       r"septic\s+(?:tank|system)\s+(?:at|of|behind)|trailer|mobile\s+home)\b", re.I)
NO_OPERATOR = re.compile(r"^\W*(?:spill\s+location|discharge\s+location|roadway|roaway|road\s*way|parking\s+(?:lot|area)|"
                         r"n/?a|unknown|wooded\s+area|storm\s+drain|sewage\s+(?:spill|overflow|discharge)|"
                         r"release\s+location|location|residence|private\s+residence)\W*$", re.I)
_WATER_WORD = r"(?:River|Creek|Run|Branch|Pond|Lake|Bay|Canal|Ditch|Gut|Prong|Marsh|Inlet|Tax\s+Ditch|Millpond|Mill\s+Pond)"
_NOT_ROAD = (r"(?![ \t]+(?:Rd|Road|Dr|Drive|Ln|Lane|Blvd|Boulevard|Ave|Avenue|St|Street|Pike|Way|Ct|Court|Cir|Circle|"
             r"Pkwy|Parkway|Hwy|Highway|Plaza|Apartments?|Apts|Village|Estates|Farms?|Park|Pump|Lift|PS|Station|"
             r"Interceptor|Sewer|Elementary|School|Shopping|Center|Golf|Crossing|Commons|Development)\b)")
_NOT_NAME_WORD = (r"(?!(?:and|or|the|into|in|to|from|near|nearby|of|at|on|by|onto|a|an|road|rd|street|drive|dr|lane|"
                  r"ln|avenue|ave|blvd|pike|way|court|ct|highway|hwy|route|rt|DE|Delaware|then|which|that|entered|"
                  r"reached|flowed|discharged|released|spilled|went|ran|traveled|travelled)\b)")
WATER_NAME = re.compile(rf"\b((?:{_NOT_NAME_WORD}(?:[A-Z][A-Za-z'’.]+|St\.?)[ \t]+){{1,3}}{_WATER_WORD})\b{_NOT_ROAD}",
                        re.I)
NOT_A_WATER = re.compile(r"^(?:the|a|an|into|to|from|near|nearby|of|and|in|at|on|storm|unnamed|small|local|tidal|"
                         r"drainage|retention|detention|stormwater|storm\s+water|farm|irrigation|fire|fish|sediment|"
                         r"holding|lagoon|sludge|equalization|aeration|include|includes|including|adjacent|adajcent|"
                         r"reaching|reached|reach|did|enter|entering|entered|is|was|discharge|wastewater|sewage|station|"
                         r"no|named|community's|water|artesian|existing|nearest|towards?|camden|possibly|then|"
                         r"flowing|flowed|went|caused|bridge|over|private|dupont\w*|wilmington|newark|dover)\b", re.I)
NO_WATER_FORM = "DNREC's release form marks the release to {} only, and the release's text names no water"

# the ZIP codes of Kent County (the rest of 199xx is Sussex; 197xx and 198xx are New Castle); 19963 (Milford) and
# 19977 (Smyrna) straddle a county line and give no county (US Census ZIP code tabulation areas)
KENT_ZIPS = {"19901", "19902", "19903", "19904", "19905", "19906", "19934", "19936", "19938", "19943", "19946",
             "19952", "19953", "19954", "19955", "19961", "19962", "19964", "19979", "19980"}
SPLIT_ZIPS = {"19963", "19977"}
DE_TOWNS = {
    "New Castle": ["wilmington", "newark", "new castle", "middletown", "bear", "glasgow", "claymont", "hockessin",
                   "townsend", "odessa", "delaware city", "elsmere", "newport", "pike creek", "edgemoor", "kirkwood",
                   "st. georges", "saint georges", "port penn", "talleyville", "greenville", "yorklyn", "montchanin",
                   "rockland", "christiana", "ardentown", "arden", "bellefonte", "minquadale", "brookside", "stanton",
                   "marshallton", "north star", "chapel hill", "boothwyn"],
    "Kent": ["dover", "smyrna", "camden", "wyoming", "clayton", "hartly", "marydel", "cheswold", "kenton", "leipsic",
             "little creek", "magnolia", "felton", "frederica", "harrington", "houston", "viola", "woodside",
             "bowers", "bowers beach", "rising sun", "kitts hummock", "farmington", "dover air force base"],
    "Sussex": ["georgetown", "lewes", "rehoboth", "rehoboth beach", "dewey beach", "milton", "millsboro", "seaford",
               "laurel", "delmar", "selbyville", "frankford", "dagsboro", "millville", "ocean view", "bethany beach",
               "south bethany", "fenwick island", "bridgeville", "greenwood", "ellendale", "lincoln", "harbeson",
               "nassau", "long neck", "angola", "bethel", "blades", "gumboro", "slaughter beach", "broadkill beach",
               "primehook", "prime hook", "oak orchard", "lewis", "selbyvile"],
}
_TOWN_COUNTY = {t: c for c, ts in DE_TOWNS.items() for t in ts}
_TOWN_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(t) for t in _TOWN_COUNTY), key=len, reverse=True)) + r")\b", re.I)

# operator rows of data/dischargers.json (scripts/add_de_operators.py): (rule on the facility or location words, id)
OPERATORS = [
    (r"new\s+castle\s+county|\bNCC\b|special\s+services", "de-new-castle-county"),
    (r"kent\s+county", "de-kent-county"),
    (r"sussex\s+county", "de-sussex-county"),
    (r"city\s+of\s+wilmington|wilmington\s+(?:sewage|waste\s*water|wwtp|regional|treatment)|"
     r"wilmington\s+(?:dept|department)\s+of\s+public\s+works", "de-de0020320"),
    (r"city\s+of\s+dover|dover\s+public\s+works", "de-city-of-dover"),
    (r"millsboro", "de-millsboro"),
    (r"city\s+of\s+newark|newark\s+public\s+works", "de-city-of-newark"),
    (r"town\s+of\s+middletown|middletown\s+(?:public\s+works|waste\s*water|wwtp|sewer)", "de-town-of-middletown"),
    (r"town\s+of\s+laurel|laurel\s+(?:waste\s*water|wwtp|sewer|treatment)", "de-de0020125"),
    (r"(?:city\s+of\s+)?seaford\s+(?:waste\s*water|wwtp|sewer|treatment)|city\s+of\s+seaford", "de-de0020265"),
    (r"howard\s+(?:h\.?\s+)?seymour|lewes\s+(?:waste\s*water|wwtp|treatment|board)|lewis\s+waste", "de-de0021512"),
    (r"rehoboth\s+(?:beach\s+)?(?:waste\s*water|wwtp|treatment)|city\s+of\s+rehoboth", "de-de0020028"),
    (r"selbyville", "de-de0020010"),
    (r"south\s+coastal", "de-sussex-county"),
    (r"town\s+of\s+milton|milton\s+(?:waste\s*water|wwtp)", "de-town-of-milton"),
    (r"town\s+of\s+smyrna|smyrna\s+(?:waste\s*water|public\s+works)", "de-town-of-smyrna"),
    (r"artesian", "de-artesian-wastewater"),
    (r"tidewater\s+(?:utilities|environmental)", "de-tidewater-environmental"),
]
_OPERATOR_RES = [(re.compile(p, re.I), i) for p, i in OPERATORS]


# ---------------------------------------------------------------- page parsing

def _text(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def hidden_fields(page: str) -> dict:
    return {m.group(1): htmllib.unescape(m.group(2))
            for m in re.finditer(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', page)}


def list_rows(page: str) -> list[dict]:
    """The grid's rows: {key, notify, release_number, location, substance, extremely_hazardous, release_time,
    facility, status} as the page shows them (unscrubbed: the caller keeps only candidates, scrubbed)."""
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        link = re.search(r"ReleaseDetail\.aspx\?ReleaseID=([0-9A-Za-z-]+)", r)
        if not link:
            continue
        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if len(cells) < 9:
            continue
        out.append({"key": link.group(1), "notify": cells[1], "release_number": cells[2], "location": cells[3],
                    "substance": cells[4], "extremely_hazardous": cells[5], "release_time": cells[6],
                    "facility": cells[7], "status": cells[8]})
    return out


def page_count(page: str) -> int:
    sel = re.search(r'<select[^>]*ddlPageSelector[^>]*>(.*?)</select>', page, re.S)
    return len(re.findall(r"<option", sel.group(1))) if sel else 1


DETAIL_SPANS = {"release_time": "lblReleaseDateTime", "report_time": "lblReportDateTime",
                "location": "lblReleaseLocation", "facility": "lblFacIDName", "substance": "lblSubstanceReleased",
                "duration": "lblReleaseDuration", "quantity": "lblEstQuantity", "text": "lblComments",
                "precautions": "lblPrecautions", "notify_public": "lblNotifyPublic", "status": "lblStatusDesc",
                "extremely_hazardous": "lblExtremelyHazardous"}
# never read: lblFacAddress, lblContactName, lblContactPhone, lblContactEmail, lblHealthRisks, lblMedicalAttention


def parse_detail(page: str) -> dict | None:
    """The safe fields of a detail page (DETAIL_SPANS) and the Released To boxes that are ticked; None when the page
    is not a release detail."""
    if "lblReleaseDateTime" not in page:
        return None
    d = {}
    for k, span in DETAIL_SPANS.items():
        m = re.search(rf'id="[^"]*_{span}"[^>]*>(.*?)</span>', page, re.S)
        d[k] = _text(m.group(1)) if m else None
    boxes = re.search(r'id="[^"]*cblReleasedTo"(.*?)</table>|id="[^"]*cblReleasedTo"(.*?)</td>', page, re.S)
    ticked = []
    if boxes:
        seg = boxes.group(1) or boxes.group(2) or ""
        for m in re.finditer(r'<input[^>]*id="([^"]*cblReleasedTo_\d+)"([^>]*)/?>\s*<label[^>]*>(.*?)</label>', seg, re.S):
            if "checked" in m.group(2):
                ticked.append(_text(m.group(3)))
    d["released_to"] = ticked
    fac = d.pop("facility") or ""
    m = re.match(r"(\d+)\s+(.*)", fac)
    d["facility_id"], d["facility"] = (m.group(1), m.group(2)) if m else (None, fac)
    return d


# ---------------------------------------------------------------- privacy

# a person named after a verb of contact or an honorific in DNREC's notes ("Call Pat Example at ...", "spoke with
# Ms. Example"): the name is cut (the blocklist and the export's redactor run again on every record)
_HON = r"(?:Mr|Mrs|Ms|Miss|Dr)\.?"
NAMED_PERSON = re.compile(rf"\b((?:[Cc]all(?:ed)?|[Cc]ontact(?:ed)?|[Ss]poke\s+(?:with|to)|[Tt]alked\s+(?:with|to)|"
                          rf"[Rr]eported\s+by|[Cc]aller|[Pp]er|[Ii]nspector|[Oo]fficer|[Oo]wner|[Rr]esident|[Hh]omeowner)"
                          rf"\s+)(?:{_HON}\s+)?[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z'-]+)?|\b{_HON}\s+[A-Z][a-z'-]+")
NOT_A_NAME = re.compile(r"^(?:the|a|an|DNREC|New|Kent|Sussex|City|Town|County|Public|Works|Special|Delaware|Artesian|"
                        r"Tidewater|DelDOT|Dover|Newark|Wilmington)\b", re.I)


def _cut_name(m: re.Match) -> str:
    lead = m.group(1) or ""
    rest = m.group(0)[len(lead):]
    return m.group(0) if (lead and NOT_A_NAME.match(rest)) else lead + "[name removed]"


def scrub(v: str | None) -> str | None:
    if not v:
        return v
    return NAMED_PERSON.sub(_cut_name, scrub_text(strip_house_numbers(v)))


def scrub_facility(v: str | None) -> str | None:
    if not v:
        return v
    from common import scrub_discharger
    return scrub_discharger({"discharger_name": scrub(v)})["discharger_name"]


def safe_list_row(r: dict) -> dict:
    return {"key": r["key"], "release_number": r["release_number"], "notify": r["notify"],
            "location": scrub(r["location"]), "substance": (r["substance"] or "")[:160],
            "extremely_hazardous": r["extremely_hazardous"], "release_time": r["release_time"],
            "facility": scrub_facility(r["facility"]), "status": r["status"]}


def safe_detail(d: dict) -> dict:
    out = dict(d)
    for k in ("location", "text", "precautions"):
        out[k] = scrub(d.get(k))
    out["facility"] = scrub_facility(d.get("facility"))
    out["substance"] = (d.get("substance") or "")[:160]
    return out


# ---------------------------------------------------------------- fetching

class Client:
    def __init__(self, session=None, pause=PAUSE_S):
        self.s = session or requests.Session()
        self.s.headers.update(HEADERS)
        self.pause = pause

    def get(self, url):
        time.sleep(self.pause)
        r = self.s.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text

    def post(self, data):
        time.sleep(self.pause)
        r = self.s.post(LIST_URL, data=data, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text

    def recent(self, pages: int) -> list[dict]:
        page = self.get(LIST_URL)
        rows = list_rows(page)
        if not rows:
            raise RuntimeError("the Recent Releases list showed no rows")
        for _ in range(1, min(pages, page_count(page))):
            page = self.post(self._next(page, None))
            rows += list_rows(page)
        return rows

    def search(self, term: str) -> list[dict]:
        page = self.get(LIST_URL)
        d = hidden_fields(page)
        d.update({P + "rblSearchField": "SubstanceReleased", P + "txtSearchValue": term, P + "btnSearch": "Search",
                  P + "txtSortExpression": "", P + "txtSortDirection": ""})
        page = self.post(d)
        n = page_count(page)
        rows = list_rows(page)
        for _ in range(1, n):
            page = self.post(self._next(page, term))
            got = list_rows(page)
            if not got:
                raise RuntimeError(f"search {term!r}: an empty page before the last")
            rows += got
        return rows

    @staticmethod
    def _next(page: str, term: str | None) -> dict:
        d = hidden_fields(page)
        if term is not None:
            d.update({P + "rblSearchField": "SubstanceReleased", P + "txtSearchValue": term})
        d.update({P + "txtSortExpression": "", P + "txtSortDirection": ""})
        btn = re.search(r'name="([^"]*btnNext)"', page)
        if not btn:
            raise RuntimeError("no Next button on the list page")
        d[btn.group(1)] = "   Next    "
        sel = re.search(r'name="([^"]*ddlPageSelector)"', page)
        cur = re.search(r'<option selected="selected" value="(\d+)"', page)
        if sel and cur:
            d[sel.group(1)] = cur.group(1)
        return d

    def detail(self, key: str) -> dict | None:
        return parse_detail(self.get(DETAIL_URL.format(key)))


# ---------------------------------------------------------------- classification

def classify(row: dict, detail: dict | None) -> tuple[str, str]:
    """(kind, basis): kind sewage | industrial | treated_effluent | wastewater_unattributed | pending (a wastewater row
    whose detail is not read yet and whose list fields do not decide it) | not_candidate."""
    sub = (detail or {}).get("substance") or row.get("substance") or ""
    if not CANDIDATE.search(sub):
        return "not_candidate", "the substance names no sewage or wastewater"
    where = " ".join(x or "" for x in (row.get("facility"), row.get("location"), (detail or {}).get("facility"),
                                       (detail or {}).get("location")))
    text = (detail or {}).get("text") or ""
    if TREATED_EFFLUENT.search(sub) and not UNTREATED.search(sub):
        return "treated_effluent", f"the substance is treated effluent ('{sub[:60]}')"
    if SEWAGE.search(sub) and not INDUSTRIAL.search(sub):
        return "sewage", f"the substance names sewage ('{sub[:60]}')"
    if INDUSTRIAL.search(sub) or (INDUSTRIAL.search(where) and not SEWAGE.search(sub)):
        return "industrial", f"industrial or commercial wastewater ('{sub[:60]}')"
    if SEWAGE.search(sub):
        return "sewage", f"the substance names sewage ('{sub[:60]}')"
    if WASTEWATER.search(sub) or re.search(r"effluent", sub, re.I):
        if UNTREATED.search(sub):
            return "sewage", f"untreated or partially treated wastewater ('{sub[:60]}')"
        m = SEWER_SYSTEM.search(where) or SEWER_SYSTEM.search(text)
        if m:
            return "sewage", f"wastewater from a sewer system ('{m.group(0)}' in the facility, location or text)"
        if detail is None:
            return "pending", "wastewater; the release's detail is not read yet"
        return "wastewater_unattributed", "wastewater that nothing ties to a sewer system"
    return "wastewater_unattributed", "no rule decides it"


def county_of(*texts: str | None) -> str | None:
    t = " ".join(x for x in texts if x)
    for z in re.findall(r"\b(19[7-9]\d\d)\b", t):
        if z in SPLIT_ZIPS:
            continue
        if z.startswith(("197", "198")):
            return "New Castle"
        return "Kent" if z in KENT_ZIPS else "Sussex"
    m = _TOWN_RE.search(t)
    return _TOWN_COUNTY[m.group(1).lower()] if m else None


def town_of(*texts: str | None) -> str | None:
    m = _TOWN_RE.search(" ".join(x for x in texts if x))
    return m.group(1).title() if m else None


def waters_named(*texts: str | None) -> list[str]:
    out = []
    for t in texts:
        for m in WATER_NAME.finditer(t or ""):
            name = re.sub(r"\s+", " ", m.group(1)).strip()
            words = name.split(" ")
            while words and NOT_A_WATER.match(words[0]):
                words = words[1:]
            if len(words) < 2:
                continue
            name = " ".join(w if w.isupper() is False else w.title() for w in words)
            name = " ".join(w[:1].upper() + w[1:] for w in name.split(" "))
            name = re.sub(r"^St\.?\s", "St. ", name)
            if name.lower() not in {o.lower() for o in out}:
                out.append(name)
    return out


def operator_of(*texts: str | None) -> str | None:
    t = " ".join(x for x in texts if x)
    for rx, did in _OPERATOR_RES:
        if rx.search(t):
            return did
    return None


def parse_time(s: str | None) -> tuple[str | None, str | None]:
    """(ISO time in America/New_York, precision) of a DERNS time ('10/23/2026 8:00:00 AM')."""
    if not s:
        return None, None
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
        if fmt == "%m/%d/%Y" or (dt.hour, dt.minute, dt.second) == (0, 0, 0):
            return dt.date().isoformat(), "day"
        return dt.replace(tzinfo=TZ).isoformat(), "minute"
    return None, None


GALLONS = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?:\+\s*)?(?:gal\b|gallons?\b|gals?\b)", re.I)


def volume(detail: dict | None) -> tuple[float | None, str | None, str]:
    q = (detail or {}).get("quantity") or ""
    m = GALLONS.search(q)
    if m:
        return float(m.group(1).replace(",", "")), q, "estimated"
    if q and q.upper() not in ("N/A", "NA", "UNKNOWN", "NONE", ""):
        return None, q, "unknown"
    m = GALLONS.search((detail or {}).get("text") or "")
    if m:
        return None, f"{m.group(0)} (in the release's text)", "unknown"
    return None, None, "unknown"


# ---------------------------------------------------------------- records

def build_record(entry: dict, fetched_at: str) -> dict | None:
    row, det = entry["list"], entry.get("detail")
    kind, basis = classify(row, det)
    if kind != "sewage":
        return None
    d = det or {}
    location = d.get("location") or row.get("location")
    facility = d.get("facility") or row.get("facility")
    text = d.get("text")
    started_at, prec = parse_time(d.get("release_time") or row.get("release_time"))
    reported_at, _ = parse_time(d.get("report_time"))
    county = county_of(location, facility)
    town = town_of(location)
    private = bool(RESIDENCE.search(" ".join(x or "" for x in (location, facility, text))))
    did = None if private else operator_of(facility, location, text if not NO_OPERATOR.match(facility or "") else None)
    where = " ".join(x or "" for x in (facility, location))
    if CSO_WORDS.search(where + " " + (text or "")):
        etype, tbasis = "cso", "the release's text says combined sewer"
    elif TREATMENT_PLANT.search(where):
        etype, tbasis = "plant_bypass", "the facility or location is a treatment plant"
    else:
        etype, tbasis = "sso", "a release from the sewer system (DERNS gives no type; the default)"
    names = waters_named(text, location, facility)
    released = d.get("released_to")
    raw = {"state": "DE", "time_zone": "America/New_York", "release_number": row.get("release_number"),
           "_placement": "named_water_only",
           "query_key": entry["key"], "substance": d.get("substance") or row.get("substance"),
           "_class_basis": basis, "_type_basis": tbasis, "derns_status": d.get("status") or row.get("status"),
           "notification_issued": row.get("notify"), "notify_public": d.get("notify_public"),
           "release_duration": d.get("duration"), "released_to": released, "county": county, "town": town,
           "facility_id": d.get("facility_id"), "detail_read": det is not None,
           "first_seen_at": entry.get("first_seen_at"), "_last_seen_in_list": entry.get("last_seen_at"),
           "start_basis": "the Release Date/Time DNREC's form gives (local time)",
           "end_basis": "DERNS gives no end; Release Duration and Status ('Final') are kept as given and never read as an end"}
    if entry.get("revisions"):
        raw["_revisions"] = entry["revisions"]
    if private:
        raw["private_source"] = True
        raw["location_basis"] = "a release at a private home: its county and town only"
    else:
        raw["location_text"] = location
        raw["facility_text"] = facility
        if text:
            raw["release_text"] = text
    if released is not None and released and "Water" not in released and not names:
        raw["reached_water"] = False
        raw["_no_water_reason"] = NO_WATER_FORM.format(" and ".join(x.lower() for x in released))
    elif released is not None and released and "Water" not in released and names:
        raw["reached_water"] = "text"
        raw["_reached_water_basis"] = ("the release's text names this water; DNREC's form marks the release to "
                                       + " and ".join(x.lower() for x in released) + " only")
    elif released and "Water" in released:
        raw["reached_water"] = True
    vol, vtext, flag = volume(det)
    precautions = d.get("precautions")
    advice = precautions if precautions and precautions.strip().lower() not in ("none", "n/a", "na", "unknown") else None
    rec = event(source_id=SOURCE_ID, source_record_id=entry["key"], event_type=etype, status="unknown",
                discharger_id=did, waterbody_text="; ".join(names) or None,
                started_at=started_at, time_precision=prec, reported_at=reported_at,
                fetched_at=entry.get("last_seen_at") or fetched_at,
                material="sewage", volume_gal=vol, volume_text=vtext, estimate_flag=flag,
                authority=AUTHORITY, advice_text=advice, source_url=DETAIL_URL.format(entry["key"]),
                outfall_name=None if private else (facility if facility and not NO_OPERATOR.match(facility) else None),
                raw=raw)
    return rec


def merge(state: dict, rows: list[dict], now: str) -> dict:
    """Candidate rows into the state (safe fields only); counts by reason in the returned dict."""
    n = {"rows_read": len(rows), "not_candidate": 0, "candidates": 0}
    seen = set()
    for r in rows:
        if r["key"] in seen:
            continue
        seen.add(r["key"])
        if not CANDIDATE.search(r.get("substance") or ""):
            n["not_candidate"] += 1
            continue
        n["candidates"] += 1
        e = state["rows"].setdefault(r["key"], {"key": r["key"], "first_seen_at": now, "detail": None})
        e["list"] = safe_list_row(r)
        e["last_seen_at"] = now
    return n


def due_for_detail(state: dict, now_dt: datetime, limit: int) -> list[str]:
    def started(e):
        t, _ = parse_time(e["list"].get("release_time"))
        return t or ""
    out = []
    for e in sorted(state["rows"].values(), key=started, reverse=True):
        kind, _ = classify(e["list"], e.get("detail"))
        if kind in ("not_candidate", "industrial", "treated_effluent") and e.get("detail") is not None:
            continue
        if e.get("detail") is None:
            if e.get("detail_failures", 0) < MAX_DETAIL_FAILURES:
                out.append(e["key"])
            continue
        t, _ = parse_time(e["list"].get("release_time"))
        try:
            d = datetime.fromisoformat(t)
            d = d if d.tzinfo else d.replace(tzinfo=TZ)
        except (TypeError, ValueError):
            continue
        if now_dt - d < timedelta(days=RECHECK_DAYS) and (e.get("detail_read_at") or "") < (now_dt - timedelta(hours=20)).isoformat():
            out.append(e["key"])
    return out[:limit]


def read_details(client: Client, state: dict, keys: list[str], now: str) -> dict:
    n = {"details_read": 0, "details_changed": 0, "details_failed": 0}
    for k in keys:
        try:
            d = client.detail(k)
        except requests.RequestException as e:
            n["details_failed"] += 1
            state["rows"][k]["detail_failures"] = state["rows"][k].get("detail_failures", 0) + 1
            print(f"{SOURCE_ID}: detail {k}: {e}", file=sys.stderr)
            continue
        if d is None:
            n["details_failed"] += 1
            e = state["rows"][k]
            e["detail_failures"] = e.get("detail_failures", 0) + 1
            continue
        d = safe_detail(d)
        h = hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]
        e = state["rows"][k]
        if e.get("detail_hash") and e["detail_hash"] != h:
            e.setdefault("revisions", []).append({"seen_at": now, "previous_hash": e["detail_hash"]})
            n["details_changed"] += 1
        e.update(detail=d, detail_hash=h, detail_read_at=now)
        n["details_read"] += 1
    return n


def rescrub(state: dict) -> dict:
    """The saved rows through today's scrub again (a rule added since they were saved applies to them too)."""
    for e in state.get("rows", {}).values():
        if e.get("list"):
            e["list"] = {**e["list"], "location": scrub(e["list"].get("location")),
                         "facility": scrub_facility(e["list"].get("facility"))}
        if e.get("detail"):
            e["detail"] = safe_detail(e["detail"])
    return state


def build(state: dict, fetched_at: str) -> tuple[list[dict], dict]:
    recs, reasons = [], {}
    for e in state["rows"].values():
        kind, _ = classify(e["list"], e.get("detail"))
        reasons[kind] = reasons.get(kind, 0) + 1
        if kind == "sewage":
            r = build_record(e, fetched_at)
            if r:
                recs.append(r)
    recs.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    return recs, reasons


META = {"credit": "Delaware Department of Natural Resources and Environmental Control, DERNS Recent Releases",
        "license": "No licence statement on the site",
        "caveat": ("DNREC lists every environmental release reported under 7 Del. C. 6028; sewage must be reported from "
                   "10,000 gallons, permitted discharges (Wilmington's combined sewer overflows) are exempt, and smaller "
                   "releases appear only when reported. DERNS gives no end time."),
        "time_basis": "Release and report times are Eastern local times as DNREC's form gives them."}


def run(args) -> int:
    now = now_iso()
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if args.file:
        state = rescrub(json.loads(open(args.file).read()))
        recs, reasons = build(state, now)
        write_events(SOURCE_ID, recs, meta={**META, "counts": reasons}, path=args.out)
        print(f"{SOURCE_ID}: {len(recs)} records from {args.file}")
        return 0
    state = rescrub(read_json(STATE_PATH, None) or {"format": SAFE_FORMAT, "rows": {}})
    client = Client()
    counts = {}
    try:
        rows = client.recent(args.pages)
        if args.backfill or not state.get("backfilled_at"):
            for term in SEARCH_TERMS:
                rows += client.search(term)
            state["backfilled_at"] = now
        counts.update(merge(state, rows, now))
    except (requests.RequestException, RuntimeError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", meta=META)
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    counts.update(read_details(client, state, due_for_detail(state, now_dt, args.details), now))
    state["format"], state["updated_at"] = SAFE_FORMAT, now
    write_json(STATE_PATH, state)
    save_raw(SOURCE_ID, json.dumps(state, indent=1, sort_keys=True), "json")
    if counts.get("details_failed"):
        # a detail page that failed (an error, or a page that is not a release's detail): the published records stay
        # as they were (ok=False); what was read is kept in the state for the next run
        write_events(SOURCE_ID, [], ok=False, error=f"{counts['details_failed']} release detail page(s) not read",
                     meta=META)
        print(f"{SOURCE_ID}: FAILED {counts}", file=sys.stderr)
        return 1
    recs, reasons = build(state, now)
    write_events(SOURCE_ID, recs, meta={**META, "counts": {**counts, **reasons}})
    print(f"{SOURCE_ID}: {len(recs)} sewage records; {counts}; {reasons}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="a saved state (safe rows) to build from, no network")
    ap.add_argument("--out", help="write the events here instead of data/build/events")
    ap.add_argument("--backfill", action="store_true", help="read every page of each substance search")
    ap.add_argument("--pages", type=int, default=PAGES)
    ap.add_argument("--details", type=int, default=DETAILS_PER_RUN)
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
