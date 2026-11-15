"""West Virginia outfall rows that improve on EPA's (data/outfalls-wv.json): the DEP NPDES Outlets layer, CSO rows.

Usage: pipeline/.venv/bin/python -I scripts/build_wv_outfalls.py [--fetch | ROWS.json]
  --fetch asks the layer once for the safe fields below and saves the answer to data/raw/wv-dep-npdes-outlets/
  cso-rows.json (git-ignored); otherwise that saved answer (or the file named) is read.

Source: West Virginia Department of Environmental Protection, NPDES Outlets layer of the WVDEP_enterprise
water_resources map service (https://tagis.dep.wv.gov/arcgis/rest/services/WVDEP_enterprise/water_resources/MapServer/24),
read 2026-11-14: 792 rows of outlet type CSO ('Combined Sewer Overflow') on 62 permits, all permit type 'Sewage';
519 with no end date (iu_edate 'NA') on 61 permits, 273 with an end date. The layer states no licence; it is DEP's
public map service, credited.

Safe fields: only rows where iut_code = 'CSO' are asked for, and only objectid, permit_id, fac_name, issuedate,
expiredate, sub_desc, t_c_desc, statusflag, perm_type, iu_code, iut_code, iut_desc, iu_bdate, iu_edate, latitude,
longitude, huc, rstream, rs_code, cnty_code, major_flag. The layer's other outlet types include home aeration units
permitted to individuals, and its rp_name and rp_id fields name responsible parties: none of that is ever requested
(outFields is never '*').

Why: EPA's national CSO inventory (data/outfalls-us.json) lists 792 West Virginia rows (509 open, 2 'TCS', 281 closed)
with EPA's points. DEP's layer is the permitting authority's own: each outlet's point, receiving stream with the water
it joins ("Buffalo Creek/Monongahela River"), 8-digit HUC, county and the outlet's begin and end dates.
  - outfall: DEP's iu_code as written ('C001', 'C002A'). EPA writes most the same; DEP's five-character codes appear in
    EPA's inventory as 'XXX2', 'XX1N' and the like: such an EPA row is paired with the DEP outlet of the same permit
    whose point lies within PAIR_M (150 m) of EPA's, when exactly one does.
  - outfall_status: 'active (DEP layer)' when iu_edate is 'NA'; else 'CLS (ended <date> in DEP's layer)', read as
    closed by the registry (common._closed), so no rain caution is drawn there.
  - receiving_water_echo: DEP's rstream; county: cnty_code (a county name).
  - The water record is tied by the cloud batch; until it runs EPA's tie for the same outfall is carried when DEP's
    point lies within CARRY_TIE_M (500 m) of EPA's and DEP names the same water or none ("carried from EPA's row");
    a different name, a qualified name ("Little Wheeling Creek" against "Wheeling Creek") or an unnamed tributary
    ("UNT/...") is not carried (carry_refused): the batch ties DEP's own point and stream. Where DEP names no stream,
    EPA's receiving water is kept, marked receiving_water_from.
  - An EPA row under a different code for a paired outlet ('XXX2' for 'C002A') is written here under EPA's code, kind
    other and closed (alias_of): one physical outlet, loaded once. A sewage permit EPA lists with no outfall number
    (a collection system or a facility with no discharge point) is written kind other (state builder rule 6).
  - permittee: EPA's permittee for the permit (ICIS), else DEP's fac_name (an organisation for every CSO permit).
EPA's open rows that DEP's layer lacks keep EPA's rows (epa_not_in_state_layer); the regional file outranks the national
one (common.outfall_file_rank), so a paired EPA row is replaced and named in `supersedes`.
"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "outfalls-wv.json"
RAW = ROOT / "data" / "raw" / "wv-dep-npdes-outlets" / "cso-rows.json"
SOURCE_ID = "wv-dep-npdes-outlets"
LAYER = "https://tagis.dep.wv.gov/arcgis/rest/services/WVDEP_enterprise/water_resources/MapServer/24"
SAFE_FIELDS = ("objectid", "permit_id", "fac_name", "issuedate", "expiredate", "sub_desc", "t_c_desc", "statusflag",
               "perm_type", "iu_code", "iut_code", "iut_desc", "iu_bdate", "iu_edate", "latitude", "longitude", "huc",
               "rstream", "rs_code", "cnty_code", "major_flag")
PAIR_M = 150
CARRY_TIE_M = 500


def _metres(lat1, lon1, lat2, lon2) -> float | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    k = math.cos(math.radians((float(lat1) + float(lat2)) / 2))
    return math.hypot((float(lat1) - float(lat2)) * 111_195, (float(lon1) - float(lon2)) * 111_195 * k)


def _clean(v):
    s = " ".join(str(v or "").split())
    return s or None


def _num_key(o) -> str:
    """'C001' and '001' and 'c1' -> '1'; 'C002A' -> '2A'."""
    s = re.sub(r"\s+", "", str(o or "")).upper()
    s = s[1:] if s.startswith("C") else s
    return s.lstrip("0") or ("0" if s else "")


def _date(v) -> str | None:
    m = re.fullmatch(r"(\d{4})/(\d{2})/(\d{2})", str(v or "").strip())
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _first_name(text) -> str | None:
    """DEP's chain 'Little Wheeling Creek/Wheeling Creek/Ohio River' -> 'Little Wheeling Creek'; an unnamed
    tributary ('UNT/...') -> None."""
    first = " ".join(str(text or "").split("/")[0].split())
    return None if not first or re.match(r"(?i)^(unt|ut|unnamed)\b", first) else first


def _name_key(name) -> str:
    """Case, punctuation and 'River'/'Creek' abbreviations aside; a qualified name ('Little X') stays its own."""
    s = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower())
    s = re.sub(r"\bcr\b|\bck\b", "creek", re.sub(r"\bfk\b", "fork", s))
    # 'Ohio' and 'Ohio River', 'North Branch of Potomac River' and 'North Branch Potomac River', 'Tygart River Valley'
    # and 'Tygart Valley River' are one name; a qualifier ('Little', 'Middle', 'Big') stays and keeps names apart
    return " ".join(sorted(w for w in s.split() if w not in ("river", "r", "of", "the")))


# the one word a source may drop from a name without naming another water ('Tygart River' for 'Tygart Valley River');
# any other extra word ('Little', 'North Fork', 'Krout Creek of') makes it another water
SPELLING_WORDS = {"valley"}


def _same_water(name, tie) -> bool:
    """A receiving-water name agrees with a tie's water: the same key, or the same but for SPELLING_WORDS. 'Little
    Coal River' never ties to 'Coal River' nor the reverse, and an empty or unnamed name ties to nothing."""
    a, b = set(_name_key(name).split()), set(_name_key(tie).split())
    return bool(a and b) and (a == b or (a ^ b) <= SPELLING_WORDS and bool(a & b))


ALIAS_NOTE = ("EPA's inventory code for DEP's outlet {dep} of the same permit (paired by point, {d:.0f} m apart): one "
              "physical outlet, shown once, as DEP's row; this row only retires EPA's code")
NO_OUTFALL_NOTE = ("EPA lists this sewage permit with no discharge point (no outfall number): a collection system or a "
                   "facility with no outfall to a water in EPA's records; kept off the map and out of the outfall count")


def build(rows: list[dict], epa_rows: list[dict], fetched_at: str, plant_rows: list[dict] | None = None) -> dict:
    epa_wv = [r for r in epa_rows if r.get("state") == "WV"]
    epa = {(r["npdes_permit"], _num_key(r["outfall"])): r for r in epa_wv}
    permittee = {}
    for r in epa_wv:
        permittee.setdefault(r["npdes_permit"], r.get("permittee"))
    dep = [{k: v for k, v in a.items() if k in SAFE_FIELDS} for a in rows if (a.get("iut_code") or "").upper() == "CSO"]
    # EPA's 'XXX?' rows: pair by point within the permit
    taken: set = set()
    pair: dict = {}
    for a in dep:
        key = (a["permit_id"], _num_key(a["iu_code"]))
        if key in epa:
            pair[id(a)] = epa[key]
            taken.add(key)
    for a in dep:
        if id(a) in pair:
            continue
        cands = [(k, e) for k, e in epa.items() if k[0] == a["permit_id"] and k not in taken and "X" in str(e["outfall"])
                 and (d := _metres(a.get("latitude"), a.get("longitude"), e.get("lat"), e.get("lon"))) is not None
                 and d <= PAIR_M]
        if len(cands) == 1:
            pair[id(a)] = cands[0][1]
            taken.add(cands[0][0])
    out, unpaired, no_point = [], [], []
    for a in dep:
        permit = _clean(a.get("permit_id"))
        num = _clean(a.get("iu_code"))
        if not permit or not num:
            continue
        lat, lon = a.get("latitude"), a.get("longitude")
        if not lat or not lon:
            no_point.append({"npdes_permit": permit, "outfall": num})
            continue
        ended = _date(a.get("iu_edate"))
        e = pair.get(id(a))
        row = {"npdes_permit": permit,
               "permittee": permittee.get(permit) or _clean(a.get("fac_name")),
               "state": "WV", "city": (e or {}).get("city"), "outfall": num, "outfall_name": None,
               "outfall_status": f"CLS (ended {ended} in DEP's layer)" if ended else "active (DEP layer)",
               "dep_outlet_begin": _date(a.get("iu_bdate")), "dep_outlet_end": ended,
               "feature_type": "EXO",
               "receiving_water_echo": _clean(a.get("rstream")),
               "dep_stream_code": _clean(a.get("rs_code")), "huc": _clean(a.get("huc")),
               "county": _clean(a.get("cnty_code")),
               "lat": round(float(lat), 6), "lon": round(float(lon), 6),
               "coords_from": "state outfall layer", "outfall_kind": "cso", "country": "US",
               "source": SOURCE_ID, "source_url": LAYER, "source_record_id": a.get("objectid"),
               "fetched_at": fetched_at}
        if e:
            row.update(echo_url=e.get("echo_url"), permit_status=e.get("permit_status"), in_icis=e.get("in_icis"),
                       supersedes={"file": "data/outfalls-us.json", "npdes_permit": permit, "outfall": e["outfall"],
                                   "outfall_status": e.get("outfall_status"), "coords_from": e.get("coords_from"),
                                   "note": "EPA's national CSO inventory row; DEP's layer gives the outlet's own point, "
                                           "receiving stream, county and the outlet's begin and end dates"})
            if e["outfall"] != num:
                row["epa_outfall"] = e["outfall"]
            d = _metres(row["lat"], row["lon"], e.get("lat"), e.get("lon"))
            dep_blank = not (row["receiving_water_echo"] or "").strip()
            if dep_blank and (e.get("receiving_water_echo") or "").strip():
                row["receiving_water_echo"] = e["receiving_water_echo"]
                row["receiving_water_from"] = "EPA's inventory row (DEP's layer names no stream for this outlet)"
            # the tie is EPA's water record: the row's effective receiving water (DEP's stream, or EPA's text where DEP
            # names none) must name that water ('Little Wheeling Creek' rows tied to Big Wheeling Creek are refused).
            # Only a row with no receiving-water text at all takes the tie unchecked: nothing contradicts it.
            text = (row["receiving_water_echo"] or "").strip()
            eff = _first_name(text)
            same_name = _same_water(eff, e.get("water_name")) if eff else not text
            if not same_name and e.get("water_slug"):
                whose = "EPA's row (DEP names none)" if row.get("receiving_water_from") else "DEP"
                row["carry_refused"] = (f"EPA's tie ({e.get('water_name')}) not carried: {whose} names the receiving "
                                        f"stream {eff or ('an unnamed tributary' if text else 'not at all')}; the "
                                        "water batch ties the outlet's own point and stream")
            if e.get("water_slug") and d is not None and d <= CARRY_TIE_M and same_name:
                row.update(water_slug=e["water_slug"], water_name=e.get("water_name"), water_kind=e.get("water_kind"),
                           match="carried from EPA's row",
                           water_match=(f"EPA's tie for this outfall (data/outfalls-us.json, {e.get('match')}), carried: "
                                        f"DEP's point lies {d:.0f} m from EPA's; the water batch ties DEP's point"))
        else:
            unpaired.append({"npdes_permit": permit, "outfall": num, "dep_outlet_end": ended})
        out.append(row)
    out.sort(key=lambda r: (r["npdes_permit"], r["outfall"]))
    used = {(r["npdes_permit"], _num_key(r.get("epa_outfall") or r["outfall"])) for r in out if r.get("supersedes")}
    epa_missing = [{"npdes_permit": p, "outfall": e["outfall"], "outfall_status": e.get("outfall_status"),
                    "reason": "open in EPA's CSO inventory but not paired with an outlet of DEP's layer; EPA's row is kept"}
                   for (p, n), e in sorted(epa.items())
                   if (p, n) not in used and not str(e.get("outfall_status") or "").upper().startswith("CLS")]
    opened = [r for r in out if not r["dep_outlet_end"]]
    # EPA's differently coded row for a paired outlet ('XXX2' for DEP's 'C002A'): the registry keys rows by permit and
    # outfall number, so EPA's code would load as a second outlet; a row here under EPA's code, kind other and closed,
    # retires it (one physical outlet, DEP's row) and keeps the provenance
    aliases = []
    for r in out:
        if r.get("epa_outfall"):
            e = epa[(r["npdes_permit"], _num_key(r["epa_outfall"]))]
            d = _metres(r["lat"], r["lon"], e.get("lat"), e.get("lon")) or 0
            aliases.append({**{k: e.get(k) for k in ("npdes_permit", "permittee", "state", "city", "outfall",
                                                     "receiving_water_echo", "echo_url")},
                            "lat": r["lat"], "lon": r["lon"], "outfall_kind": "other",
                            "outfall_status": f"CLS (EPA's code for DEP outlet {r['outfall']})",
                            "kind_note": ALIAS_NOTE.format(dep=r["outfall"], d=d), "alias_of": r["outfall"],
                            "supersedes": f"data/outfalls-us.json {e['npdes_permit']} {e['outfall']}",
                            "source": SOURCE_ID})
    # sewage permits EPA lists with no discharge point: no outfall (state builder rule 6)
    no_outfall = [{**{k: p.get(k) for k in ("npdes_permit", "permittee", "permit_name", "state", "city", "outfall",
                                            "feature_type", "receiving_water_echo", "echo_url", "permit_status")},
                   "outfall_kind": "other", "kind_note": NO_OUTFALL_NOTE, "lat": None, "lon": None,
                   "supersedes": f"data/outfalls-plants-us.json {p['npdes_permit']} (no outfall number)"}
                  for p in sorted(plant_rows or [], key=lambda x: x["npdes_permit"])
                  if p.get("state") == "WV" and not str(p.get("outfall") or "").strip()]
    # where DEP and EPA disagree on open or closed, DEP (the permitting authority) is followed; listed for review
    differs = [{"npdes_permit": r["npdes_permit"], "outfall": r["outfall"], "dep": r["outfall_status"],
                "epa": r["supersedes"]["outfall_status"]} for r in out if r.get("supersedes")
               and (str(r["supersedes"]["outfall_status"] or "").upper().startswith("CLS")) != bool(r["dep_outlet_end"])]
    return {"source": (f"West Virginia DEP NPDES Outlets layer (outlet type CSO), {LAYER}, fetched {fetched_at}; EPA's "
                       "rows for the same permit and outfall (data/outfalls-us.json) are kept and named in supersedes"),
            "rule": ("one row per CSO outlet of DEP's layer: DEP's point, receiving stream, county and outlet dates; an "
                     "outlet with an end date written CLS (closed), one with none open"),
            "generated": datetime.now(UTC).date().isoformat(), "count": len(out),
            "permits": len({r["npdes_permit"] for r in out}),
            "open": len(opened), "open_permits": len({r["npdes_permit"] for r in opened}),
            "paired_with_epa": len(out) - len(unpaired), "unpaired": unpaired, "no_point": no_point,
            "epa_not_in_state_layer": epa_missing, "status_differs_from_epa": differs,
            "epa_code_aliases": len(aliases), "plant_permits_without_outfall": len(no_outfall),
            "outfalls": out + aliases + no_outfall}


def fetch() -> Path:
    import requests
    sys.path.insert(0, str(ROOT / "pipeline"))
    from common import HEADERS
    params = {"where": "iut_code='CSO'", "outFields": ",".join(SAFE_FIELDS), "returnGeometry": "false",
              "orderByFields": "objectid", "f": "json"}
    r = requests.get(LAYER + "/query", params=params, headers=HEADERS, timeout=300)
    r.raise_for_status()
    doc = r.json()
    if doc.get("error") or doc.get("exceededTransferLimit"):
        raise SystemExit(f"DEP's layer answered {doc.get('error') or 'more than one page'}")
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps(doc))
    return RAW


def main(argv) -> int:
    path = fetch() if "--fetch" in argv else Path(argv[1]) if len(argv) > 1 else RAW
    doc = json.loads(Path(path).read_text())
    fetched = datetime.fromtimestamp(Path(path).stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    epa_rows = json.loads((ROOT / "data" / "outfalls-us.json").read_text())["outfalls"]
    plants = json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
    out = build([f.get("attributes") or {} for f in doc.get("features") or []], epa_rows, fetched, plants)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{out['count']} DEP outlets on {out['permits']} permits ({out['open']} open on {out['open_permits']} permits; "
          f"{out['paired_with_epa']} paired with EPA's rows; {len(out['epa_not_in_state_layer'])} open EPA rows "
          f"unpaired) -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
