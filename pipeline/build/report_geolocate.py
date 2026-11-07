"""Places for overflow reports that carry no usable point (step 4 of the provisional outfall pipeline; owner
2026-11-03 16:14: "Even if we don't have coordinates we can use address and description to geolocate").

Called by build/provisional_outfalls.py with --geolocate. Input: the reports build_places kept (an operator named,
no private-property or building-backup sign) that have no point or a point that failed its checks. A report whose
outfall id is a registry outfall of its permit is already placed by the registry and is skipped. The rest, the
operators with no official point and no place first, then by report count, are read in this order, and each place
records the step that placed it:

  (a) a street address (house number and street: CT Address, MDE overflow_address + ZIP, VA address + city + ZIP,
      NY geoaddress or street number + name + city) -> US Census geocoder (onelineaddress, Public_AR_Current). The
      Census geocoder only answers address-range matches (no town or ZIP centroid); a match in another state, or in
      another town and ZIP than the report gives, is rejected. Precision 50 m, confidence medium.
  (b) an intersection ("X and Y", "X & Y", "corner of X and Y", "X at Y") -> the shared node of the two named
      streets in the operator's town (OpenStreetMap via Overpass; the town's box from Nominatim, 1 request a second).
      Several junctions over 200 m apart: not placed. Precision 30 m, confidence medium.
  (c) a named facility: a pump or lift station (the station mapped by OSM man_made=pumping_station within 150 m of
      the street the text names, or whose name matches), the treatment plant (OSM man_made=wastewater_plant in the
      town, one only, else EPA FRS facility coordinates of the permit via ECHO). Precision 100 m (pump station) or
      250 m (plant), confidence medium.
  (d) a street name only -> the street in the operator's town (OSM), its middle; the radius is half its length
      (at most 1.5 km; a street found in pieces over 1 km apart is not placed). Confidence low.
  (e) a receiving water named and nothing else -> no point is invented; the reports stay on that water as today and
      the operator is listed (geolocation.water_only).
  With no usable location at all: the operator's plant point from EPA FRS (ECHO facility coordinates of its permit)
  stands in, confidence low, labelled "treatment plant location, not an overflow point".
Never a town or county centroid. Every result is checked: inside the state (1 km slack), not a point three or more
operators share, within 30 km of the operator's other places when it has some.

Language models (build/llm_judge.py, docs/llm-judges.md) only where rules cannot: Jev classifies the kind of a
location text the rules could not read (accepted at confidence 0.80 or more; below that the text goes to the review
list), luna writes the structured query (streets, facility, town) for a text Jev classed as an intersection,
facility or street when the rules could not split it; Jev gives a second privacy opinion on the location texts of
every place (noul 0.70 or more excludes; it can only exclude more); Jev judges a disagreement between the traced
water and the reports' water (report / traced / unsure, accepted at 0.80). The model never supplies coordinates.
Places a model touched say so in method.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from build import provisional_outfalls as P
from build import status as S
from common import BUILD_DIR, now_iso, read_json

GEO_CACHE = BUILD_DIR / "provisional-outfalls-geocache.json"
CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
CENSUS_BATCH = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
ECHO = "https://echodata.epa.gov/echo/cwa_rest_services.get_facility_info"

STATE_NAMES = {"CT": "Connecticut", "MA": "Massachusetts", "RI": "Rhode Island", "NH": "New Hampshire", "VT": "Vermont",
               "ME": "Maine", "NY": "New York", "NJ": "New Jersey", "PA": "Pennsylvania", "MD": "Maryland",
               "VA": "Virginia", "DC": "District of Columbia", "DE": "Delaware", "WV": "West Virginia",
               "NC": "North Carolina", "GA": "Georgia", "FL": "Florida", "MI": "Michigan", "WA": "Washington", "CA": "California", "IL": "Illinois", "AZ": "Arizona",
               "SD": "South Dakota",
               "MS": "Mississippi", "NE": "Nebraska", "AK": "Alaska",
               "NM": "New Mexico", "HI": "Hawaii"}
PRECISION = {"address": 50, "intersection": 30, "pump_station": 100, "plant": 250, "frs_plant": 250}
NEAR_OPERATOR_KM = 30
TOWN_MISMATCH_NEAR_KM = 10
TOWN_BOX_MAX_DEG = 0.6
JEV_MIN = 0.80
PRIVATE_NOUL = 0.70
KIND_VERSION = "location-kind-v1"
QUERY_VERSION = "location-query-v1"
PRIVACY_VERSION = "privacy-v1"
WATER_VERSION = "water-disagree-v1"

STREET_WORDS = (r"st|street|rd|road|ave|avenue|av|dr|drive|ln|lane|blvd|boulevard|ct|court|pl|place|way|ter|terrace|"
                r"cir|circle|pkwy|parkway|hwy|highway|tpke|turnpike|route|rte|rt|sq|square|trl|trail|pike|row|xing|"
                r"crossing|ext|extension|alley|aly|walk")
SUFFIX = {"st": "street", "rd": "road", "ave": "avenue", "av": "avenue", "dr": "drive", "ln": "lane", "blvd": "boulevard",
          "ct": "court", "pl": "place", "ter": "terrace", "cir": "circle", "pkwy": "parkway", "hwy": "highway",
          "tpke": "turnpike", "rte": "route", "rt": "route", "sq": "square", "trl": "trail", "xing": "crossing",
          "ext": "extension", "aly": "alley", "n": "north", "s": "south", "e": "east", "w": "west", "mt": "mount",
          "ft": "fort"}
ADDRESS_START = re.compile(r"^\s*\d+[A-Za-z]?(?:-\d+)?\s+(?:[NSEW]\.?\s+)?[A-Za-z0-9]", re.I)
PLACEHOLDER = re.compile(r"please see|see dep|website|unknown|^n/?a$|^none$|various|multiple|^other$|^select|"
                         r"^(?:address|municipality|location|town|city|street)$", re.I)
INTERSECTION = re.compile(
    rf"(?:corner\s+of|intersection\s+of|junction\s+of)?\s*(?P<a>[A-Za-z0-9.'\- ]{{2,40}}?\b(?:{STREET_WORDS})\b\.?)"
    rf"\s*(?:and|&|/|@|at)\s+(?P<b>[A-Za-z0-9.'\- ]{{2,40}}?\b(?:{STREET_WORDS})\b\.?)", re.I)
INTERSECTION_PHRASE = re.compile(r"(?:corner|intersection|junction)\s+of\s+(?P<a>[A-Za-z0-9.'\- ]{2,40}?)\s+(?:and|&)\s+"
                                 r"(?P<b>[A-Za-z0-9.'\- ]{2,40}?)(?:[,.;(]|$)", re.I)
PUMP = re.compile(r"\b(?:pump(?:ing)?\s*station|lift\s*station|p\.?s\.?(?=\s|$|,)|pumping\s+plant|ejector\s+station)\b", re.I)
PLANT = re.compile(r"\b(?:treatment\s+(?:plant|facility|works)|wastewater\s+(?:treatment|facility|plant)|wwtp|wwtf|wpcf|wpcp|"
                   r"wrrf|wrf|water\s+reclamation|pollution\s+control|main\s+plant|headworks|sewer\s+plant|"
                   r"sewage\s+plant|plant\s+(?:outfall|influent|effluent|bypass)|^\s*plant\s*$)\b", re.I)
STREET_ONLY = re.compile(rf"^\s*(?:[NSEW]\.?\s+)?[A-Za-z][A-Za-z0-9.'\- ]{{1,40}}?\b(?:{STREET_WORDS})\b\.?\s*$", re.I)
CATEGORY = re.compile(r"^\s*(?:manhole|sewer\s+main|treatment\s+plant|pump\s+station|lateral\s*-\s*public|other|pipe|"
                      r"force\s+main|cleanout|pipe\s+failure|regulator|cso\s+outfall)\s*-?\s*$", re.I)


# ---------------------------------------------------------------- reading a report's location

def clean_town(t) -> str | None:
    """A town name fit for a lookup ("Town Of Woodstock" -> "Woodstock", "Springfield V.T." -> "Springfield"), or None
    for a text that is not one ("Lfd #2", "Brattleboro Wwtp" -> "Brattleboro")."""
    if not isinstance(t, str):
        return None
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"^\s*(?:town|city|village|borough|township)(?:\s+of)?\s+", "", t, flags=re.I)
    t = re.sub(r"\b(?:v\.?t\.?|wwtp|wwtf|wpcf|wpca|potw|sewer\s+district|fire\s+district)\s*$", "", t.strip(), flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" .,")
    if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,29}", t) or len(t) < 3:
        return None
    return t.title()


def town_of(ev: dict, oprow: dict) -> str | None:
    t = P.location_texts(ev)
    for k in ("Municipality", "Muncipality", "municipality", "REPORTING_TOWN", "CSO_TOWN", "Town", "town", "city",
              "report.city", "City/Town"):
        v = t.get(k)
        if v and not PLACEHOLDER.search(v) and len(v) < 40 and clean_town(v):
            return clean_town(v)
    towns = [clean_town(x) for x in (oprow.get("towns") or []) if clean_town(x)]
    return towns[0] if towns else None


def clean_street(s: str) -> str:
    s = re.sub(r"\s+", " ", re.sub(r"[.,;]+$", "", s.strip()))
    return re.sub(r"^(?:the|in|on|at|of)\s+", "", s, flags=re.I)


def address_query(ev: dict, state: str) -> str | None:
    """A one-line street address the report gives (house number first), or None."""
    t = P.location_texts(ev)
    raw_row = (ev.get("raw") or {}).get("row") or {}
    cands = []
    if t.get("Address"):
        cands.append(t["Address"])
    if t.get("STREET_ADDRESS"):
        cands.append(f"{t['STREET_ADDRESS']}, {t.get('REPORTING_TOWN') or ''}")
    if t.get("overflow_address"):
        cands.append(f"{t['overflow_address']}, {state} {t.get('zip') or ''}")
    if t.get("report.address"):
        cands.append(f"{t['report.address']}, {t.get('report.city') or ''}, {state} {t.get('report.zip') or ''}")
    if t.get("geoaddress"):
        cands.append(t["geoaddress"])
    if raw_row.get("streetNumber") and raw_row.get("streetName"):
        cands.append(f"{raw_row['streetNumber']} {raw_row['streetName']}, {raw_row.get('city') or ''}")
    for c in cands:
        c = re.sub(r"\s+", " ", re.sub(r",\s*,", ",", c)).strip(" ,")
        if PLACEHOLDER.search(c):
            continue
        if ADDRESS_START.match(c):
            if state not in c.upper().split(", ")[-1] and not re.search(rf"\b{state}\b", c):
                c = f"{c}, {state}"
            return c
    return None


def location_text(ev: dict) -> str | None:
    """The report's free location text (the one a geocoder query is made from), or None."""
    t = P.location_texts(ev)
    for k in ("STREET_ADDRESS", "Address", "overflow_address", "report.address", "addressDescription",
              "text.location_comment", "outfall_name", "LOCATION", "Location", "location", "componentDescription",
              "report.site_name"):
        v = t.get(k)
        if v and not PLACEHOLDER.search(v) and not CATEGORY.match(v) and not re.fullmatch(r"[\d\sA-Z#-]{1,8}", v):
            return v[:200]
    return None


STREET_PHRASE = re.compile(rf"(?:^|\b(?:on|along|of|at|near)\s+|^[A-Za-z ]*?,\s*)"
                           rf"(?P<s>(?:[NSEW]\.?\s+)?[A-Za-z][A-Za-z0-9.'\-]*(?:\s+[A-Za-z0-9][A-Za-z0-9.'\-]*){{0,3}}?"
                           rf"\s+(?:{STREET_WORDS})\b\.?)", re.I)
LEAD_WORDS = re.compile(r"^(?:manhole|mh|sewer\s+main|main|pipe|force\s+main|cleanout|regulator|outfall|sso|cso)\b"
                        r"[\s#\d,:-]*", re.I)
JOIN = re.compile(r"^(?P<a>[A-Za-z0-9.' -]{2,40}?)\s+(?:and|&|@|at)\s+(?P<b>[A-Za-z0-9.' -]{2,40}?)$", re.I)
HAS_STREET_WORD = re.compile(rf"\b(?:{STREET_WORDS})\b\.?$", re.I)


def split_town(text: str, state: str) -> tuple[str, str | None]:
    """("first part", town) of "Iranistan Ave, Bridgeport, CT" style texts."""
    parts = [x.strip() for x in text.split(",") if x.strip()]
    if len(parts) >= 2 and parts[-1].upper() in (state, STATE_NAMES.get(state, "").upper()):
        parts = parts[:-1]
    town = None
    if len(parts) >= 2 and re.fullmatch(r"[A-Za-z .'-]{2,30}", parts[-1]) and not HAS_STREET_WORD.search(parts[-1]) \
            and not re.search(r"\b(?:and|at)\b|&", parts[-1], re.I):
        town = parts[-1].title()
        parts = parts[:-1]
    return ", ".join(parts), town


def parse_location(ev: dict, state: str) -> dict:
    """{kind, ...}: address (query), intersection (a, b), pump_station (name, street), plant, street (street),
    water_only, unknown (text), none. Rules only."""
    q = address_query(ev, state)
    if q:
        return {"kind": "address", "query": q}
    text = location_text(ev)
    t = P.location_texts(ev)
    cat = t.get("BYPASS_LOCATION") or t.get("Location of Bypass") or ""
    if text and len(re.findall(r"\b(?:CSO|SSO|outfall)\s*(?:#|no\.?|[-\u2013])?\s*\d", text, re.I)) >= 2:
        return {"kind": "multiple", "text": text}           # several outfalls in one report: no single place
    if text:
        body, town = split_town(text, state)
        extra = {"town": town} if town else {}
        body = re.sub(r"[()]", " ", re.sub(r"[\u2013\u2014]", "-", body))
        for part in [x.strip() for x in re.split(r",|\s-\s|:", body)]:
            part = LEAD_WORDS.sub("", part).strip().lstrip("#").strip()
            if ADDRESS_START.match(part) and (HAS_STREET_WORD.search(part) or len(part.split()) <= 4):
                return {"kind": "address", "street_address": part, "query": f"{part}, {town + ', ' if town else ''}{state}",
                        **extra}
        m = INTERSECTION_PHRASE.search(body) or INTERSECTION.search(body)
        if not m:
            for part in [LEAD_WORDS.sub("", x.strip()) for x in body.split(",")]:
                j = JOIN.match(part.strip())
                if j and (HAS_STREET_WORD.search(j.group("a")) or HAS_STREET_WORD.search(j.group("b"))):
                    m = j
                    break
        if m:
            return {"kind": "intersection", "a": clean_street(m.group("a")), "b": clean_street(m.group("b")),
                    "text": text, **extra}
        if PUMP.search(body):
            rest = PUMP.sub(" ", body)
            st = STREET_PHRASE.search(rest.strip(" ,"))
            name = re.sub(r"[,#()-]+", " ", rest).strip()
            return {"kind": "pump_station", "street": clean_street(st.group("s")) if st else None,
                    "name": re.sub(r"\s+", " ", name)[:60] or None, "text": text, **extra}
        if PLANT.search(body):
            return {"kind": "plant", "text": text, **extra}
        stripped = re.sub(r"\s+", " ", LEAD_WORDS.sub("", body)).strip(" ,:-")
        if STREET_ONLY.match(stripped):
            return {"kind": "street", "street": clean_street(stripped), "text": text, **extra}
        st = STREET_PHRASE.search(stripped)
        if st and len(stripped) <= 60:
            return {"kind": "street", "street": clean_street(st.group("s")), "text": text, **extra}
        return {"kind": "unknown", "text": text, **extra}
    if re.search(r"treatment\s+plant", cat, re.I) or ev.get("event_type") == "plant_bypass":
        return {"kind": "plant", "text": cat or "plant bypass"}
    if re.search(r"pump\s+station", cat, re.I):
        return {"kind": "pump_station", "street": None, "name": None, "text": cat}
    if ev.get("waterbody_text"):
        return {"kind": "water_only"}
    return {"kind": "none"}


# ---------------------------------------------------------------- lookups (cached, polite)

class Geo:
    def __init__(self, net: P.Net, offline: bool = False):
        self.net, self.offline = net, offline
        try:
            self.cache = read_json(GEO_CACHE) or {}
        except Exception:
            self.cache = {}
        for k in ("census", "town", "overpass", "echo"):
            self.cache.setdefault(k, {})

    def save(self):
        if self.offline or not sum(self.net.counts.values()):
            return
        P.save_merged(GEO_CACHE, self.cache)

    def _get(self, table, key, kind, url, params, timeout=60):
        hit = self.cache[table].get(key)
        if hit is not None and not (isinstance(hit, dict) and hit.get("error") and not P.fresh_error(hit)):
            return hit
        d, why = self.net.get_json(kind, url, params, timeout=timeout)
        if d is None and (why in ("budget", "offline") or P.transient(why)):
            return None
        val = d if d is not None else {"error": why, "fetched_at": now_iso()}
        self.cache[table][key] = val
        return val

    def census_batch(self, queries: list[str], state_of: dict) -> None:
        """Ask the Census batch geocoder (addressbatch, up to 1,000 a request) for every query not cached; the answer
        of each is cached like a onelineaddress answer ({"result": {"addressMatches": [...]}})."""
        need = sorted({q for q in queries if q.upper() not in self.cache["census"]})
        if not need or self.offline:
            return
        import csv
        import io
        for i in range(0, len(need), 1000):
            chunk = need[i:i + 1000]
            buf = io.StringIO()
            w = csv.writer(buf)
            for n, q in enumerate(chunk):
                street, city, st, zipc = oneline_parts(q, state_of.get(q, ""))
                w.writerow([n, street, city, st, zipc])
            if not self.net.budget.take():
                return
            t0 = time.monotonic()
            try:
                r = self.net.session().post(CENSUS_BATCH, data={"benchmark": "Public_AR_Current"},
                                            files={"addressFile": ("addresses.csv", buf.getvalue(), "text/csv")},
                                            timeout=max(20.0, min(600.0, self.net.budget.left_s())))
                ok = r.status_code == 200
            except Exception:
                ok = False
            self.net._count("census-batch", t0, failed=not ok)
            if not ok:
                return
            got = {}
            for row in csv.reader(io.StringIO(r.text)):
                if len(row) < 3 or not row[0].isdigit():
                    continue
                n = int(row[0])
                if row[2] == "Match" and len(row) >= 6 and "," in row[5]:
                    lon, lat = map(float, row[5].split(","))
                    matched = row[4]
                    mparts = [x.strip() for x in matched.split(",")]
                    got[n] = {"result": {"addressMatches": [{
                        "coordinates": {"x": lon, "y": lat}, "matchedAddress": matched, "match_type": row[3],
                        "addressComponents": {"city": mparts[1] if len(mparts) > 2 else "",
                                              "state": mparts[2] if len(mparts) > 3 else "",
                                              "zip": mparts[3] if len(mparts) > 3 else ""}}]}, "via": "batch"}
                else:
                    got[n] = {"result": {"addressMatches": []}, "via": "batch", "match": row[2] if len(row) > 2 else ""}
            for n, q in enumerate(chunk):
                self.cache["census"][q.upper()] = got.get(n) or {"result": {"addressMatches": []}, "via": "batch"}
            self.save()

    def census(self, query: str):
        d = self._get("census", query.upper(), "census-geocoder", CENSUS,
                      {"address": query, "benchmark": "Public_AR_Current", "format": "json"})
        if d is None:
            return None
        return ((d.get("result") or {}).get("addressMatches") or []) if isinstance(d, dict) else []

    def town_box(self, town: str, state: str):
        key = f"{town.upper()}|{state}"
        hit = self.cache["town"].get(key)
        if hit is None:
            d, why = self.net.get_json("nominatim", NOMINATIM, {"city": town, "state": STATE_NAMES.get(state, state),
                                                               "country": "USA", "format": "jsonv2", "limit": "1"})
            if d is None and (why in ("budget", "offline") or P.transient(why)):
                return None
            box = None
            if isinstance(d, list) and d:
                bb = d[0].get("boundingbox")
                if bb:
                    s_, n_, w_, e_ = map(float, bb)
                    if (n_ - s_) <= TOWN_BOX_MAX_DEG and (e_ - w_) <= TOWN_BOX_MAX_DEG:
                        box = [s_, w_, n_, e_]
            hit = self.cache["town"][key] = {"box": box, "fetched_at": now_iso()}
        return hit.get("box") or False

    def overpass(self, box, names: list[str], facilities: bool):
        s_, w_, n_, e_ = box
        bb = f"{s_:.4f},{w_:.4f},{n_:.4f},{e_:.4f}"
        rx = "|".join(re.escape(n) for n in sorted(set(names)) if n)
        parts = []
        if rx:
            parts.append(f'way["highway"]["name"~"(^| )({rx})( |$)",i]({bb});')
        if facilities:
            parts.append(f'nwr["man_made"~"^(pumping_station|wastewater_plant)$"]({bb});')
            parts.append(f'nwr["name"~"(pump|pumping|lift) station|treatment plant|wastewater|pollution control|'
                         f'water reclamation",i]({bb});')
        if not parts:
            return {"elements": []}
        q = f"[out:json][timeout:60];({''.join(parts)});out geom tags;"
        key = hashlib.sha1(q.encode()).hexdigest()[:20]
        hit = self.cache["overpass"].get(key)
        if hit is not None and not (isinstance(hit, dict) and hit.get("error") and not P.fresh_error(hit)):
            return hit
        for url in OVERPASS:
            d, why = self.net.get_json("overpass", url, {"data": q}, timeout=45, attempts=1)
            if d is None and why in ("budget", "offline"):
                return None
            if isinstance(d, dict) and "elements" in d:
                slim = {"elements": [{k: e.get(k) for k in ("type", "id", "tags", "geometry", "nodes", "lat", "lon",
                                                            "center", "bounds")} for e in d["elements"]]}
                self.cache["overpass"][key] = slim
                return slim
        return None                      # every mirror failed: asked again next run, never cached as an answer

    def echo_facility(self, permit: str):
        hit = self._get("echo", permit, "echo-facility", ECHO, {"p_pid": permit, "output": "JSON",
                                                                "qcolumns": "1,2,4,5,9,26,27"})
        if hit is None:
            return None
        for f in ((hit.get("Results") or {}).get("Facilities") or []) if isinstance(hit, dict) else []:
            try:
                return {"lat": float(f["FacLat"]), "lon": float(f["FacLong"]), "name": f.get("CWPName"),
                        "registry_id": f.get("RegistryID")}
            except (KeyError, TypeError, ValueError):
                continue
        return False


def oneline_parts(q: str, state: str) -> tuple[str, str, str, str]:
    """(street, city, state, zip) of a one-line address "12 Main St, Town, CT 06401"."""
    zm = re.search(r"\b(\d{5})(?:-\d{4})?\b(?!.*\d{5})", q)
    zipc = zm.group(1) if zm else ""
    parts = [x.strip() for x in re.sub(r"\b\d{5}(?:-\d{4})?\b", "", q).split(",") if x.strip()]
    parts = [x for x in parts if x.upper() not in ("USA", "US", "UNITED STATES")]
    st = state
    if parts and re.fullmatch(r"[A-Z]{2}", parts[-1].upper().strip()):
        st = parts[-1].upper().strip()
        parts = parts[:-1]
    street = parts[0] if parts else q
    city = parts[1] if len(parts) > 1 else ""
    return street, city, st, zipc


# ---------------------------------------------------------------- resolving

def norm_street(s: str) -> str:
    ws = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()
    return " ".join(SUFFIX.get(w, w) for w in ws)


def street_core(s: str) -> str:
    """The distinctive word(s) of a street name for the Overpass pattern: 'Glen Drive' -> 'Glen'."""
    ws = [w for w in re.sub(r"[^A-Za-z0-9 ]", " ", s or "").split()
          if w.lower() not in SUFFIX and w.lower() not in set(SUFFIX.values())]
    return " ".join(ws[:3])


def ways_named(elements, street: str) -> list:
    want = norm_street(street)
    out = []
    for e in elements:
        if e.get("type") == "way" and (e.get("tags") or {}).get("highway") and e.get("geometry"):
            if norm_street((e.get("tags") or {}).get("name") or "") == want:
                out.append(e)
    return out


def line_of(way):
    from shapely.geometry import LineString
    return LineString([(g["lon"], g["lat"]) for g in way["geometry"]])


def resolve(parsed: dict, town: str | None, state: str, geo: Geo, permit: str | None) -> dict:
    """{status: placed, lat, lon, step, precision_m, confidence, detail} | {status: not_placed, why} |
    {status: pending}."""
    kind = parsed["kind"]
    if kind == "address":
        ms = geo.census(parsed["query"])
        if ms is None:
            return {"status": "pending"}
        if isinstance(ms, dict) or not ms:
            return {"status": "not_placed", "why": "the Census geocoder found no address match"}
        m = ms[0]
        comp = m.get("addressComponents") or {}
        if comp.get("state") and comp["state"] != state:
            return {"status": "not_placed", "why": f"the Census match is in {comp['state']}"}
        q = parsed["query"].upper()
        city, zipc = (comp.get("city") or "").upper(), comp.get("zip") or ""
        nt, nc = S.norm_town(town or ""), S.norm_town(city)
        same = not town or not city or nt == nc or nt in nc or nc in nt or (zipc and zipc in q) or city in q \
            or "county" in (town or "").lower()
        qzip = re.search(r"\b(\d{5})\b", q)
        if qzip and zipc and qzip.group(1) != zipc:
            return {"status": "not_placed", "why": f"the Census match is in ZIP {zipc}, not {qzip.group(1)}"}
        mismatch = None if same else f"the Census match is in {city.title()}, not {town}"
        c = m.get("coordinates") or {}
        return {"status": "placed", "lat": float(c["y"]), "lon": float(c["x"]), "step": "a",
                "precision_m": PRECISION["address"], "confidence": "medium",
                "detail": "US Census geocoder, address-range match", "town_mismatch": mismatch}
    if kind == "plant":
        box = geo.town_box(town, state) if town else False
        if box is None:
            return {"status": "pending"}
        if box:
            d = geo.overpass(box, [], facilities=True)
            if d is None:
                return {"status": "pending"}
            plants = [e for e in d.get("elements") or [] if (e.get("tags") or {}).get("man_made") == "wastewater_plant"]
            if len(plants) == 1:
                lat, lon = element_point(plants[0])
                if lat is not None:
                    return {"status": "placed", "lat": lat, "lon": lon, "step": "c", "precision_m": PRECISION["plant"],
                            "confidence": "medium", "detail": f"the treatment plant mapped in OpenStreetMap in {town}"}
        if permit:
            f = geo.echo_facility(permit)
            if f is None:
                return {"status": "pending"}
            if f:
                return {"status": "placed", "lat": f["lat"], "lon": f["lon"], "step": "c",
                        "precision_m": PRECISION["frs_plant"], "confidence": "medium",
                        "detail": f"EPA FRS facility coordinates of {permit} (the treatment plant the reports name)"}
        return {"status": "not_placed", "why": "no single treatment plant mapped in the town and no EPA facility point"}
    if kind in ("intersection", "pump_station", "street"):
        if not town:
            return {"status": "not_placed", "why": "no town to look the streets up in"}
        box = geo.town_box(town, state)
        if box is None:
            return {"status": "pending"}
        if not box:
            return {"status": "not_placed", "why": f"no town box for {town}, {state}"}
        names = [street_core(parsed.get(k)) for k in ("a", "b", "street") if parsed.get(k)]
        d = geo.overpass(box, names, facilities=kind == "pump_station")
        if d is None:
            return {"status": "pending"}
        els = d.get("elements") or []
        if kind == "intersection":
            return junction(els, parsed["a"], parsed["b"], town)
        if kind == "pump_station":
            r = pump_station(els, parsed, town)
            if r["status"] == "placed" or not parsed.get("street"):
                return r
            r2 = street_middle(els, parsed["street"], town)
            if r2["status"] == "placed":
                r2["detail"] += " (the pump station the report names is not mapped; its street stands in)"
            return r2
        return street_middle(els, parsed["street"], town)
    return {"status": "not_placed", "why": kind}


def element_point(e):
    if e.get("lat") is not None:
        return float(e["lat"]), float(e["lon"])
    if e.get("center"):
        return float(e["center"]["lat"]), float(e["center"]["lon"])
    g = e.get("geometry")
    if g:
        lats = [p["lat"] for p in g if p]
        lons = [p["lon"] for p in g if p]
        return sum(lats) / len(lats), sum(lons) / len(lons)
    b = e.get("bounds")
    if b:
        return (b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2
    return None, None


def junction(els, a, b, town) -> dict:
    wa, wb = ways_named(els, a), ways_named(els, b)
    if not wa or not wb:
        miss = a if not wa else b
        return {"status": "not_placed", "why": f"no street named {miss!r} mapped in {town}"}
    na = {n: (g["lat"], g["lon"]) for w in wa for n, g in zip(w.get("nodes") or [], w["geometry"]) if g}
    common = [na[n] for w in wb for n in (w.get("nodes") or []) if n in na]
    if not common:
        from shapely.ops import unary_union
        inter = unary_union([line_of(w) for w in wa]).intersection(unary_union([line_of(w) for w in wb]))
        common = [(p.y, p.x) for p in getattr(inter, "geoms", [inter]) if p.geom_type == "Point"]
    if not common:
        return {"status": "not_placed", "why": f"{a} and {b} do not meet in {town} (OpenStreetMap)"}
    lat0, lon0 = common[0]
    if any(P.dist_m(lat0, lon0, la, lo) > 200 for la, lo in common):
        return {"status": "not_placed", "why": f"{a} and {b} meet at several places in {town}"}
    lat = sum(c[0] for c in common) / len(common)
    lon = sum(c[1] for c in common) / len(common)
    return {"status": "placed", "lat": lat, "lon": lon, "step": "b", "precision_m": PRECISION["intersection"],
            "confidence": "medium", "detail": f"the junction of {a} and {b} in {town} (OpenStreetMap)"}


def pump_station(els, parsed, town) -> dict:
    stations = [e for e in els if (e.get("tags") or {}).get("man_made") == "pumping_station"
                or re.search(r"(pump|pumping|lift) station", (e.get("tags") or {}).get("name") or "", re.I)]
    stations = [e for e in stations if "water" not in ((e.get("tags") or {}).get("substance") or "sewage")
                or (e.get("tags") or {}).get("substance") in ("sewage", "wastewater")]
    hits = []
    if parsed.get("street"):
        ways = ways_named(els, parsed["street"])
        if ways:
            from shapely.geometry import Point
            from shapely.ops import unary_union
            line = unary_union([line_of(w) for w in ways])
            for e in stations:
                lat, lon = element_point(e)
                if lat is not None and line.distance(Point(lon, lat)) * 111_320 <= 150:
                    hits.append((lat, lon, e))
    name_ws = [w for w in re.sub(r"[^a-z0-9 ]", " ", (parsed.get("name") or "").lower()).split()
               if w not in {"pump", "station", "ps", "lift", "pumping", "the", "at", "on", "sewer"} and len(w) > 2]
    if not hits and name_ws:
        for e in stations:
            nm = ((e.get("tags") or {}).get("name") or "").lower()
            if nm and all(w in nm for w in name_ws):
                lat, lon = element_point(e)
                if lat is not None:
                    hits.append((lat, lon, e))
    if not hits:
        return {"status": "not_placed", "why": f"the pump station is not mapped in {town} (OpenStreetMap)"}
    lat0, lon0, _ = hits[0]
    if any(P.dist_m(lat0, lon0, la, lo) > 150 for la, lo, _ in hits):
        return {"status": "not_placed", "why": f"several pump stations match in {town}"}
    return {"status": "placed", "lat": lat0, "lon": lon0, "step": "c", "precision_m": PRECISION["pump_station"],
            "confidence": "medium", "detail": f"the pump station mapped in OpenStreetMap in {town}"}


def street_middle(els, street, town) -> dict:
    ways = ways_named(els, street)
    if not ways:
        return {"status": "not_placed", "why": f"no street named {street!r} mapped in {town}"}
    from shapely.ops import linemerge, unary_union
    u = unary_union([line_of(w) for w in ways])
    merged = linemerge(u) if u.geom_type == "MultiLineString" else u
    parts = list(getattr(merged, "geoms", [merged]))
    if len(parts) > 1:
        far = max(parts[0].distance(p) for p in parts[1:]) * 111_320
        if far > 1000:
            return {"status": "not_placed", "why": f"{street} is mapped in pieces {far / 1000:.1f} km apart in {town}"}
    main = max(parts, key=lambda p: p.length)
    mid = main.interpolate(0.5, normalized=True)
    import math
    length_m = sum(p.length for p in parts) * 111_320 * math.cos(math.radians(mid.y))
    radius = min(1500, max(50, round(length_m / 2)))
    if length_m / 2 > 1500:
        return {"status": "not_placed", "why": f"{street} is {length_m / 1000:.1f} km long in {town}: too long to stand"
                                                f" for a place"}
    return {"status": "placed", "lat": mid.y, "lon": mid.x, "step": "d", "precision_m": radius, "confidence": "low",
            "detail": f"the middle of {street} in {town} (OpenStreetMap; the overflow lies within {radius} m)"}


# ---------------------------------------------------------------- language models (only where rules cannot)

KIND_Q = {"kind": {"type": "choice",
                   "instructions": "A sewer overflow report gives this location text. What kind of place does it name, "
                                   "for finding it on a map?",
                   "criteria": {"address": "a street address with a house number",
                                "intersection": "two streets that meet (a corner, 'X at Y', 'X and Y')",
                                "named_facility": "a named facility: pump station, treatment plant, regulator, a named "
                                                  "park, school, bridge or building",
                                "street": "one street name, with no house number and no cross street",
                                "water_only": "only a river, creek or other water body",
                                "none": "no usable place: a category word, an outfall number, a placeholder"}}}
QUERY_SCHEMA = {"type": "object", "additionalProperties": False,
                "properties": {"kind": {"type": "string", "enum": ["address", "intersection", "named_facility", "street",
                                                                   "none"]},
                               "street1": {"type": ["string", "null"]}, "street2": {"type": ["string", "null"]},
                               "facility": {"type": ["string", "null"]}, "address": {"type": ["string", "null"]},
                               "town": {"type": ["string", "null"]}},
                "required": ["kind", "street1", "street2", "facility", "address", "town"]}
QUERY_SYSTEM = ("You read the location text of a sewer overflow report and return the parts a geocoder needs. Use only "
                "words that are in the text (or the town given); never invent a place, a house number or coordinates. "
                "kind address: 'address' is the house number and street. intersection: street1 and street2 are the two "
                "street names. named_facility: 'facility' is its name and street1 the street it is on, if the text says. "
                "street: street1. none: nothing usable. town: the town the text names, else the town given.")


def model_parse(judge, text: str, town: str | None, state: str) -> tuple[dict | None, str]:
    """(parsed, note): Jev's kind of a text the rules could not read, then luna's structured query when Jev classed it
    as a place to look up. None when the model is unsure (review list) or says there is nothing to look up."""
    a = judge.decide(KIND_VERSION, {"location_text": text, "town": town, "state": state}, KIND_Q)
    k = ((a or {}).get("answers") or {}).get("kind") or {}
    if not k:
        return None, "model gave no answer"
    if float(k.get("confidence") or 0) < JEV_MIN:
        return None, f"Jev unsure ({k.get('choice')} at {k.get('confidence')})"
    kind = k.get("choice")
    if kind in ("water_only", "none"):
        return {"kind": kind}, f"Jev: {kind} ({k.get('confidence')})"
    w = judge.write(QUERY_VERSION, QUERY_SYSTEM, json.dumps({"text": text, "town": town, "state": state}), QUERY_SCHEMA,
                    name="location_query")
    if not w or w.get("kind") in (None, "none"):
        return None, "luna found nothing to look up"
    for k in ("street1", "street2", "facility", "address"):
        if w.get(k) and not grounded(w[k], text):
            return None, f"luna's {k} {w[k]!r} is not in the text (review)"
    t = w.get("town") if w.get("town") and (grounded(w["town"], text) or (town and grounded(w["town"], town))) \
        else town
    if kind == "address" and w.get("address") and ADDRESS_START.match(w["address"]):
        return {"kind": "address", "query": f"{w['address']}, {t or ''}, {state}".replace(", ,", ","),
                "town": t}, "Jev: address; luna wrote the query"
    if kind == "intersection" and w.get("street1") and w.get("street2"):
        return {"kind": "intersection", "a": w["street1"], "b": w["street2"], "town": t}, \
            "Jev: intersection; luna named the streets"
    if kind == "named_facility" and (w.get("facility") or w.get("street1")):
        fac = w.get("facility") or ""
        if PLANT.search(fac):
            return {"kind": "plant", "town": t}, "Jev: named facility; luna: the treatment plant"
        if PUMP.search(fac):
            return {"kind": "pump_station", "name": fac, "street": w.get("street1"), "town": t}, \
                "Jev: named facility; luna: a pump station"
        if w.get("street1"):
            return {"kind": "street", "street": w["street1"], "town": t}, \
                "Jev: named facility not mapped by name; luna gave its street"
        return None, f"Jev: named facility ({fac}); not a kind this step can look up"
    if kind == "street" and w.get("street1"):
        return {"kind": "street", "street": w["street1"], "town": t}, "Jev: street; luna named it"
    return None, f"Jev: {kind}; luna's answer did not fit"


def grounded(value: str, text: str) -> bool:
    """Whether a value the model extracted is in the text (street abbreviations normalised, case and punctuation
    ignored)."""
    v = norm_street(value).replace(" ", "")
    t = norm_street(text).replace(" ", "")
    return bool(v) and v in t


PRIVACY_Q = {"private": {"type": "noul",
                         "instructions": "Does this sewer overflow location text say the overflow happened on private "
                                         "property or was sewage backing up into a building (a home, a basement, a "
                                         "private service lateral)?"}}


def model_private(judge, text: str) -> float | None:
    a = judge.decide(PRIVACY_VERSION, {"location_text": text}, PRIVACY_Q)
    v = ((a or {}).get("answers") or {}).get("private") or {}
    return float(v["noul"]) if v.get("noul") is not None else None


WATER_Q = {"which": {"type": "choice",
                     "instructions": "A sewer overflow place has two candidate receiving waters: the water the "
                                     "operator's reports name, and the water a downhill trace from the place's point "
                                     "reaches on the national stream network. Which is the water the overflow reaches?",
                     "criteria": {"report_water": "the water the reports name",
                                  "traced_water": "the water the downhill trace reaches",
                                  "both": "both: the traced stream flows into the named water, or they are one water "
                                          "under two names",
                                  "unsure": "cannot tell"}}}


# ---------------------------------------------------------------- the step

def registry_placed(ev: dict, reg_keys: set) -> bool:
    permit = str(ev.get("npdes_permit") or "").upper()
    if not permit:
        return False
    return any((permit, S.oid_key(i) if hasattr(S, "oid_key") else i) in reg_keys for i in P.outfall_ids(ev))


def geolocate(unlocated: list[dict], args, key=None, by_id=None, anchors=None) -> tuple[list[dict], dict]:
    """(places, stats) for the reports without a usable point. anchors: the places the reports' own points gave
    ({operator: [(lat, lon), ...]}): a lookup more than NEAR_OPERATOR_KM from all of its operator's is rejected."""
    t0 = time.monotonic()
    anchors = anchors or {}
    by_id = by_id or {}
    reg = P.registry_rows()
    reg_keys = {(str(o["npdes_permit"]).upper(), S.oid_key(o.get("outfall")) if hasattr(S, "oid_key") else
                 str(o.get("outfall"))) for o in reg}
    reg_permits = {str(o["npdes_permit"]).upper() for o in reg}
    stats = Counter()
    groups = defaultdict(list)
    parsed_of = {}
    for ev in unlocated:
        if registry_placed(ev, reg_keys):
            stats["placed by its registry outfall already"] += 1
            continue
        op = ev["_op"]
        oprow = by_id.get(op) or {}
        state = ev.get("_state") or oprow.get("state")
        if not state:
            stats["no state"] += 1
            continue
        parsed = parse_location(ev, state)
        town = town_of(ev, oprow) or clean_town(parsed.get("town"))
        if parsed["kind"] == "address" and parsed.get("street_address") and not parsed.get("town"):
            if not town:
                stats["address with no town"] += 1
                continue
            parsed = {**parsed, "query": f"{parsed['street_address']}, {town}, {state}"}
        k = (op, state, json.dumps({x: v for x, v in parsed.items()
                                    if x != "text" or parsed["kind"] in ("unknown", "multiple")}, sort_keys=True),
             town if parsed["kind"] != "address" else "")
        groups[k].append(ev)
        parsed_of[k] = (parsed, town)
    # operators with no official point and no place first, then by report count
    def has_official(op):
        r = by_id.get(op) or {}
        perms = {p.upper() for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])] if p}
        return bool(perms & reg_permits)
    order = sorted(groups, key=lambda k: (has_official(k[0]), -len(groups[k]), tuple(str(x or "") for x in k)))
    budget = P.Budget(args.geo_budget_s, getattr(args, "geo_max_requests", 2000))
    net = P.Net(budget, offline=args.offline, pause=1.0)          # Nominatim: one request a second
    geo = Geo(net, offline=args.offline)
    addr = {parsed_of[k][0]["query"]: k[1] for k in order if parsed_of[k][0]["kind"] == "address"}
    geo.census_batch(list(addr), addr)
    judge = getattr(args, "judge", None)
    placed = []          # (lat, lon, ev, info)
    review, water_only = [], defaultdict(int)
    plant_fallback = defaultdict(list)
    model_notes = Counter()
    for k in order:
        op, state, _, _ = k
        parsed, town = parsed_of[k]
        evs = groups[k]
        note = None
        if parsed["kind"] == "unknown" and judge is not None:
            try:
                mp, note = model_parse(judge, parsed["text"], town, state)
            except Exception as ex:          # SpendCap or anything else: rules only from here
                mp, note = None, f"model stopped ({type(ex).__name__})"
            model_notes[note.split(" (")[0] if note else "none"] += 1
            if mp is None:
                review.append({"operator": op, "state": state, "text": parsed["text"][:200], "town": town,
                               "reports": len(evs), "why": note})
                parsed = {"kind": "none"}
            else:
                parsed = {**mp, "model": note}
                town = town or clean_town(mp.get("town"))
        kind = parsed["kind"]
        stats[f"kind {kind}"] += len(evs)
        if kind == "water_only":
            water_only[(op, state)] += len(evs)
            continue
        if kind == "multiple":
            review.append({"operator": op, "state": state, "text": parsed["text"][:200], "town": town,
                           "reports": len(evs), "why": "the report names several outfalls: no single place"})
            continue
        if kind in ("none", "unknown"):
            plant_fallback[(op, state)].extend(evs)
            if kind == "unknown":
                review.append({"operator": op, "state": state, "text": parsed["text"][:200], "town": town,
                               "reports": len(evs), "why": "rules could not read it (no model this run)"})
            continue
        permit = next((e.get("npdes_permit") for e in evs if e.get("npdes_permit")), None) or \
            (by_id.get(op) or {}).get("npdes_permit")
        try:
            r = resolve(parsed, town, state, geo, permit)
        except Exception as ex:                  # one odd geometry never stops the step
            r = {"status": "not_placed", "why": f"error {type(ex).__name__}"}
        if r["status"] == "pending":
            stats["pending (request budget)"] += len(evs)
            continue
        if r["status"] != "placed":
            stats[f"not placed: {r['why'][:60]}"] += len(evs)
            continue
        prob = P.coord_problem(r["lat"], r["lon"], state, P.state_outlines())
        if prob:
            stats[f"rejected: {prob}"] += len(evs)
            continue
        near = [P.dist_m(r["lat"], r["lon"], a, b) for a, b in anchors.get(op, [])]
        if near and min(near) > NEAR_OPERATOR_KM * 1000:
            stats[f"rejected: over {NEAR_OPERATOR_KM} km from the operator's other places"] += len(evs)
            continue
        if r.get("town_mismatch") and not (near and min(near) <= TOWN_MISMATCH_NEAR_KM * 1000):
            # the Census postal city differs from the report's town: kept only beside the operator's other places
            stats[f"not placed: {r['town_mismatch'][:60]}"] += len(evs)
            continue
        info = {**r, "kind": kind, "model": parsed.get("model")}
        for e in evs:
            placed.append((r["lat"], r["lon"], {**e, "coord_source": "geocode"}, info))
    # a point three or more operators share (a town hall, a county office, one plant for several systems) is a
    # centroid-like stand-in, never a place: the same rule as for the reports' own points
    ops_at = defaultdict(set)
    for lat, lon, e, _ in placed:
        ops_at[(round(lat, P.CENTROID_ROUND), round(lon, P.CENTROID_ROUND))].add(e["_op"])
    shared = {p for p, ops in ops_at.items() if len(ops) >= P.CENTROID_OPERATORS}
    if shared:
        n0 = len(placed)
        placed = [x for x in placed if (round(x[0], P.CENTROID_ROUND), round(x[1], P.CENTROID_ROUND)) not in shared]
        stats[f"rejected: a point {P.CENTROID_OPERATORS} or more operators share"] += n0 - len(placed)
    # the plant stands in for an operator with no usable location and no other place this step found
    stand_ins = []
    placed_ops = {e["_op"] for _, _, e, _ in placed}
    for (op, state), evs in plant_fallback.items():
        if op in placed_ops:
            continue
        permit = next((e.get("npdes_permit") for e in evs if e.get("npdes_permit")), None) or \
            (by_id.get(op) or {}).get("npdes_permit")
        if not permit or has_official(op):
            stats["no location, no stand-in (an official point exists or no permit)"] += len(evs)
            continue
        f = geo.echo_facility(permit)
        if not f:
            stats["no location, no EPA facility point"] += len(evs)
            continue
        if P.coord_problem(f["lat"], f["lon"], state, P.state_outlines()):
            continue
        info = {"status": "placed", "lat": f["lat"], "lon": f["lon"], "step": "frs", "precision_m": None,
                "confidence": "low", "detail": f"EPA FRS facility coordinates of {permit}: {P.PLANT_LABEL}",
                "kind": "frs_stand_in", "stand_in": True}
        for e in evs:
            stand_ins.append((f["lat"], f["lon"], {**e, "coord_source": "geocode"}, info))
    geo.save()
    if judge is not None:
        judge.save()
    places = build_geo_places(placed, by_id) + build_geo_places(stand_ins, by_id)
    out_stats = {
        "reports_in": len(unlocated), "by_outcome": dict(stats.most_common()),
        "places": len(places), "reports_placed": sum(p["report_count"] for p in places),
        "operators_placed": len({p["discharger_id"] for p in places}),
        "by_step": dict(Counter(p["geolocation"]["step"] for p in places)),
        "water_only_operators": [{"operator": o, "state": s, "reports": n}
                                 for (o, s), n in sorted(water_only.items(), key=lambda x: -x[1])],
        "review": review[:300], "review_count": len(review),
        "model": judge.stats() if judge is not None else None, "model_outcomes": dict(model_notes),
        "requests": dict(net.counts), "request_failures": dict(net.failures), "budget_spent": budget.spent,
        "seconds": round(time.monotonic() - t0, 1),
    }
    return places, out_stats


def build_geo_places(placed, by_id) -> list[dict]:
    """Places from geolocated reports: per operator, the 50 m clustering of build_places; each place keeps how it
    was found (the most reported lookup)."""
    by_op = defaultdict(list)
    for lat, lon, ev, info in placed:
        by_op[ev["_op"]].append((lat, lon, {**ev, "_geo": info}))
    out = []
    for op in sorted(by_op):
        evs = [e for _, _, e in by_op[op]]
        permits = P.operator_permits(op, evs, by_id)
        for group in P.cluster_points(by_op[op]):
            p = P.place_row(op, by_id.get(op) or {}, permits, group)
            infos = Counter(json.dumps({k: v for k, v in it["_geo"].items() if k not in ("lat", "lon", "status")},
                                       sort_keys=True) for _, _, it in group)
            info = json.loads(infos.most_common(1)[0][0])
            model = info.get("model")
            p["coord_source"] = "geocode"
            p["geolocation"] = {
                "step": info["step"], "kind": info["kind"], "precision_m": info.get("precision_m"),
                "confidence": info["confidence"], "detail": info["detail"], "model": model,
                "method": ("location text read by a language model, then " if model else "location text read by rules, then ")
                + info["detail"],
            }
            if info.get("stand_in"):
                p["stand_in"] = True
                p["geolocation"]["method"] = info["detail"]
            out.append(p)
    return out


def after_water(places: list[dict], args, gstats: dict) -> None:
    """Model opinions after the water step: a second privacy check on every place's location texts (it can only
    exclude: such a place is marked excluded and leaves the output) and a judgement of each disagreement between the
    traced water and the reports' water (recorded, never overwriting the reports' water)."""
    judge = getattr(args, "judge", None)
    if judge is None:
        return
    judged = Counter()
    for p in sorted(places, key=lambda p: -p["report_count"]):
        w = p.get("water") or {}
        if w.get("check") in ("disagree", "unclear") and w.get("name"):
            state = {"reports_water": (p.get("reports_water_text") or [None])[0],
                     "reports_water_record": (p.get("reports_water_slugs") or [None])[0],
                     "traced_water": w.get("label"), "trace_distance_m": w.get("snap_m"),
                     "downstream_km": w.get("downstream_km"), "place_names": p.get("place_names"),
                     "event_types": p.get("event_types"), "state": p.get("state")}
            try:
                a = judge.decide(WATER_VERSION, state, WATER_Q)
            except Exception:
                judged["not asked (cap or time budget)"] += 1
                continue
            c = ((a or {}).get("answers") or {}).get("which") or {}
            if c:
                ok = float(c.get("confidence") or 0) >= JEV_MIN
                w["judge"] = {"choice": c.get("choice") if ok else "unsure", "confidence": c.get("confidence"),
                              "model": judge.jev, "version": WATER_VERSION,
                              "note": "language-model opinion, recorded only; the reports' water is kept"}
                judged[w["judge"]["choice"]] += 1
    gstats["water_judgements"] = dict(judged)
    judge.save()


def privacy_second_opinion(places: list[dict], events_by_id: dict, judge) -> tuple[list[dict], Counter]:
    """Jev's privacy opinion on the distinct free location texts of each place's reports; a place whose texts the
    model reads as private property or a building backup (noul >= PRIVATE_NOUL on any of its reports' texts) is left
    out. Rules ran first; this can only exclude more."""
    out, why = [], Counter()
    for p in places:
        texts = set()
        for eid in p.get("_all_event_ids") or p.get("event_ids") or []:
            ev = events_by_id.get(eid)
            if ev:
                t = location_text(ev)
                if t and len(t) > 12:
                    texts.add(t)
        bad = None
        for t in sorted(texts)[:5]:
            try:
                v = model_private(judge, t)       # a cached answer is used even after the cap or time budget
            except Exception:
                v = None                          # not asked this run: rules only for it
                why["model privacy opinion not asked (cap or time budget)"] += 1
            if v is not None and v >= PRIVATE_NOUL:
                bad = (t, v)
                break
        if bad:
            why["excluded by the model's privacy opinion"] += 1
            continue
        out.append(p)
    return out, why
