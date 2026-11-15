"""Puerto Rico's weekly beach notices (Departamento de Recursos Naturales y Ambientales, Programa de Monitoría de
Playas y Notificación Pública) -> data/build/events/pr-drna-beach-notices.json.

Source
  https://www.drna.pr.gov/wp-json/wp/v2/posts?categories=1424 (registry pr-drna-beach-notices; research/pr/
  sources.json): the WordPress REST list of DRNA's "Notificación Monitoria de Playas" posts, about one a week since
  October 2019 (280 posts on 2026-11-14). No key; no terms of use are stated. Each post's content is DRNA's notice in
  Spanish: "A base de los resultados de los muestreos del <day(s)> de <month> de <year>, realizados en las playas que
  son parte del Programa de Playas, la(s) siguiente(s) playa(s) no son aptas para bañistas por exceder el “Beach Action
  Value” (BAV) para el parámetro de Enterococos (70 colonias/100 mL):" followed by a table Estación | Nombre de la Playa
  | Municipio. A week with no beach over the value says instead that "las playas que son parte del Programa de Playas
  se encuentran aptas para bañistas". The fields read are id, date_gmt (the time DRNA published the notice, UTC),
  modified_gmt, link and content; nothing else is saved.

Notices (parse_notice): kind "exceed" (the "no son aptas" list, its stations), "all_fit" (no beach listed: the
  program's beaches "se encuentran aptas"), "fit_list" (one notice of 2020-06-30 that lists the stations that are fit,
  "están aptas ... por NO exceder"), "unread" (three posts of October 2019 that only link a PDF report, and any post
  whose words no rule recognises: it neither opens nor closes an advisory, and is counted in meta.unread_notices).
  The sampling date(s) are read from the text as DRNA writes them ("del 2 y 3 de noviembre de 2026"): sampled_at is
  the first day, raw.sample_dates the words. A sample date is never an advisory's start.

Records (the accuracy-first pattern, docs/generic-ingesters.md: sampled_at apart, no sample date as a start)
  One record per run of consecutive readable notices that list a station: event_type beach_advisory, DRNA's own
  advisory ("no son aptas para bañistas"), quoted in Spanish as written (advice_text; never translated inside the
  quotation). started_at and published_at are the publication time of the first notice of the run (date_gmt, given by
  DRNA; time_precision minute); sampled_at its first sampling day. The run ends at the publication time of the first
  later readable notice that does not list the station (an "exceed" list without it, an "all_fit" notice, or a
  "fit_list" naming it): ended_at with raw.ended_at_precision "minute" and raw.end_basis naming that notice, status
  advisory_lifted. A run the newest notice still lists is advisory_active with no end, and raw._last_seen_in_source
  is this poll's time (the status build keeps it red while DRNA's newest notice lists it, and ages it out 14 days after
  the last poll that saw it). event id: pr-drna-beach-notices:<station>:<first post id> (stable).
  The notices list only the beaches over the value: a beach not listed, a notice that the beaches are fit for bathers,
  and a green flag at a beach are never records here, and never a clean or passing status (grey: no report).

Stations (STATIONS): DRNA's station table (Identificaciones de las Playas, wp-content/uploads/2020/06/Tabla-playas.pdf:
  36 stations RW-1 to RW-39) with one public point each, the station's own monitoring location in the Water Quality
  Portal (organization PR_BEACH_WQX, Puerto Rico Environmental Quality Board (Beach), whose beach program DRNA
  continues; read 2026-11-14), cited in raw.point_basis and raw.point_url (coord_source "station_point"; rounded to
  three decimals). The notice's station number is normalised (RW-06 -> RW-6, RWW-28 -> RW-28, RW14A -> RW-14, RW-1A ->
  RW-1, RW-12B -> RW-12, RW-20A -> RW-20, RW-21C -> RW-21, RW-25 -> RW-25A); the beach's name decides when the number
  disagrees with it (2026-10-16 lists Playa Cabullón, Ponce, as RW-30, which is Playa Guayanés, Yabucoa; one notice
  lists Muelle de Arecibo as RW-28), with raw.station_note. A station no rule knows is kept as a record with no point
  and a parse_error, never dropped. waterbody_text is the beach and municipality in DRNA's table's words; placement by
  the point only (a marker), never a whole-water colour.

Privacy: the notices carry no person (the contact line is the program's general one); only the parsed notices are
  saved (data/raw/pr-drna-beach-notices/<stamp>.json).

Cadence: weekly posts; read with the refresh (page 1, the newest 100, merged with the notices already read; every page
  on a first run or with --all). Run from pipeline/:
  python -m ingest.pr_drna_beaches [--file posts.json ...] [--all] [--at 2026-11-14T12:00:00Z]
"""
from __future__ import annotations

import html as htmllib
import json
import re
import sys
import unicodedata
from pathlib import Path

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "pr-drna-beach-notices"
URL = "https://www.drna.pr.gov/wp-json/wp/v2/posts"
PARAMS = {"categories": "1424", "per_page": "100", "_fields": "id,date_gmt,modified_gmt,link,content"}
STATE_PATH = BUILD_DIR / "pr-drna-beach-notices-state.json"
AUTHORITY = ("Departamento de Recursos Naturales y Ambientales (DRNA), Programa de Monitoría de Playas y "
             "Notificación Pública")
TABLE_URL = "https://www.drna.pr.gov/wp-content/uploads/2020/06/Tabla-playas.pdf"
WQP = "https://www.waterqualitydata.us/provider/STORET/PR_BEACH_WQX/PR_BEACH_WQX-{}/"
POINT_BASIS = ("the station's monitoring location in the Water Quality Portal (PR_BEACH_WQX-{}, Puerto Rico "
               "Environmental Quality Board beach program, which DRNA continues), read 2026-11-14")
TIME_ZONE = "America/Puerto_Rico"

# station: (DRNA's table name, municipality, WQX station, lat, lon, name rule); points from the WQP station list
STATIONS = {
    "RW-1": ("Balneario de Luquillo (La Monserrate)", "Luquillo", "RW-1A", 18.386, -65.729, r"luquillo|monserrate"),
    "RW-2": ("Balneario Seven Seas", "Fajardo", "RW-2", 18.369, -65.636, r"seven seas"),
    "RW-4": ("Balneario Punta Santiago", "Humacao", "RW-4", 18.158, -65.755, r"punta santiago"),
    "RW-5": ("Balneario de Rincón", "Rincón", "RW-5", 18.341, -67.256, r"balneario (de )?rincon"),
    "RW-6": ("Balneario de Patillas", "Patillas", "RW-6", 17.974, -65.989, r"patilla"),
    "RW-7": ("Balneario Punta Guilarte", "Arroyo", "RW-7", 17.962, -66.040, r"guilarte"),
    "RW-8": ("Playa Buyé", "Cabo Rojo", "RW-8", 18.049, -67.199, r"buye"),
    "RW-9": ("Balneario Caña Gorda", "Guánica", "RW-9", 17.953, -66.885, r"cana gorda"),
    "RW-10": ("Playa Santa", "Guánica", "RW-10", 17.938, -66.955, r"playa santa"),
    "RW-12": ("Playa Combate", "Cabo Rojo", "RW-12B", 17.975, -67.213, r"combate"),
    "RW-13": ("Balneario Boquerón", "Cabo Rojo", "RW-13", 18.019, -67.172, r"boqueron"),
    "RW-14": ("Playa Mojacasabe", "Cabo Rojo", "RW-14A", 17.986, -67.215, r"moja ?casabe"),
    "RW-15": ("Balneario de Añasco (Tres Hermanos)", "Añasco", "RW-15", 18.288, -67.194, r"anasco|tres hermanos"),
    "RW-16": ("Playa Crash Boat", "Aguadilla", "RW-16", 18.458, -67.164, r"crash boat"),
    "RW-17": ("Balneario Cerro Gordo", "Vega Alta", "RW-17", 18.481, -66.341, r"cerro gordo"),
    "RW-18": ("Balneario Sardinera (Manuel “Nolo” Morales)", "Dorado", "RW-18", 18.475, -66.281, r"sardinera|nolo"),
    "RW-19": ("Balneario Punta Salinas", "Toa Baja", "RW-19", 18.472, -66.186, r"punta salinas"),
    "RW-20": ("Balneario El Escambrón", "San Juan", "RW-20A", 18.467, -66.090, r"escambron"),
    "RW-21": ("Balneario de Carolina", "Carolina", "RW-21C", 18.446, -66.004, r"balneario de carolina"),
    "RW-22": ("Balneario de Aguada (Pico de Piedra)", "Aguada", "RW-22", 18.384, -67.213, r"pico de piedra|balneario de aguada"),
    "RW-23": ("Balneario Puerto Nuevo", "Vega Baja", "RW-23", 18.491, -66.399, r"puerto nuevo"),
    "RW-25A": ("Playa Sixto Escobar", "San Juan", "RW-25A", 18.467, -66.087, r"sixto escobar"),
    "RW-26": ("Playita del Condado", "San Juan", "RW-26", 18.461, -66.082, r"condado"),
    "RW-27": ("Playa Ocean Park", "San Juan", "RW-27", 18.453, -66.049, r"ocean park"),
    "RW-28": ("Playa El Alambique", "Carolina", "RW-28", 18.444, -66.022, r"alambique"),
    "RW-29": ("Playa Vacía Talega", "Loíza", "RW-29", 18.448, -65.906, r"talega"),
    "RW-30": ("Playa Guayanés", "Yabucoa", "RW-30", 18.063, -65.819, r"guayanes"),
    "RW-31": ("Tropical Beach", "Naguabo", "RW-31", 18.187, -65.726, r"tropic ?al beach"),
    "RW-32": ("Playa Azul", "Luquillo", "RW-32", 18.382, -65.718, r"playa azul"),
    "RW-33": ("Playita Rosada", "Lajas", "RW-33", 17.972, -67.032, r"rosada"),
    "RW-34": ("Playa Cabullón", "Ponce", "RW-34", 17.969, -66.603, r"cabullon"),
    "RW-35": ("Playa Jauca", "Santa Isabel", "RW-35", 17.960, -66.370, r"jauca"),
    "RW-36": ("Balneario de Salinas", "Salinas", "RW-36", 17.978, -66.332, r"balneario de salinas"),
    "RW-37": ("Playa Villa Lamela", "Cabo Rojo", "RW-37", 18.065, -67.198, r"lamela"),
    "RW-38": ("Playa Muelle de Arecibo", "Arecibo", "RW-38", 18.480, -66.700, r"muelle de arecibo"),
    "RW-39": ("Playa Mar Chiquita", "Manatí", "RW-39", 18.473, -66.486, r"mar chiquita"),
}
ALIASES = {"RW-1A": "RW-1", "RW-12B": "RW-12", "RW-14A": "RW-14", "RW-20A": "RW-20", "RW-21C": "RW-21",
           "RW-25": "RW-25A"}
MONTHS = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                      "septiembre", "octubre", "noviembre", "diciembre"), 1)}
MONTHS["setiembre"] = 9
SAMPLE = re.compile(r"muestreos?\s+(?:realizados?\s+)?(?:del?|el|los)\s+((\d{1,2})(?:\s*(?:,|y|al|-)\s*\d{1,2})*"
                    r"\s+(?:de\s+)?(" + "|".join(MONTHS) + r")(?:\s+(?:de|del)\s+(\d{4}))?)", re.I)
SAMPLE_WORDS = re.compile(r"muestreos?\s+(?:realizados?\s+)?(?:del?|el|los)\s+(.{1,40}?),?\s+realizad", re.I)
EXCEED = re.compile(r"(no\s+son\s+aptas?\s+para\s+bañistas[^:]*)", re.I)
ALL_FIT = re.compile(r"se\s+encuentran?\s+aptas?\s+para\s+bañistas", re.I)
FIT_LIST = re.compile(r"(?<!no )\b(?:están|estan)\s+aptas?\s+para\s+bañistas\s+por\s+no\s+exceder", re.I)
STATION = re.compile(r"^\W*R\s*W+\s*-?\s*0*(\d{1,2})\s*([A-Z])?\s*$", re.I)


def fold(s: str) -> str:
    """Lower case, accents off, spaces folded (for the name rules only; text is kept as DRNA writes it)."""
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip().lower()


def text_of(html: str) -> str:
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", html or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def table_rows(html: str) -> list[tuple[str, str, str]]:
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S | re.I):
        cells = [text_of(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        if len(cells) < 2 or not any(cells) or fold(cells[0]).startswith("estaci"):
            continue
        out.append(tuple((cells + ["", "", ""])[:3]))
    return out


def station_of(code: str, name: str) -> tuple[str | None, str | None]:
    """(station, note): the beach's name decides when it is one station's (module docstring), else the number."""
    m = STATION.match(code or "")
    by_code = None
    if m:
        key = f"RW-{int(m.group(1))}{(m.group(2) or '').upper()}"
        by_code = ALIASES.get(key, key) if ALIASES.get(key, key) in STATIONS else (
            f"RW-{int(m.group(1))}" if f"RW-{int(m.group(1))}" in STATIONS else None)
    f = fold(name)
    by_name = [k for k, v in STATIONS.items() if re.search(v[5], f)]
    if len(by_name) == 1:
        if by_code and by_code != by_name[0]:
            return by_name[0], (f"listed as {code.strip()}; the beach's name ({name.strip()}) is that of "
                                f"{by_name[0]} in DRNA's station table")
        return by_name[0], None
    return by_code, None


def sample_date(text: str, published: str) -> tuple[str | None, str | None]:
    """(first sampling day as ISO, the words) from the notice; a year left out is the publication's (or the year
    before, for a December sample in a January notice)."""
    m = SAMPLE.search(text)
    if not m:
        w = SAMPLE_WORDS.search(text)     # words DRNA wrote that give no date ('del 6, 8 y 9 2020'): kept, no date
        return None, w.group(1) if w else None
    day, month = int(m.group(2)), MONTHS[m.group(3).lower()]
    year = int(m.group(4)) if m.group(4) else int(published[:4]) - (1 if month > int(published[5:7]) else 0)
    try:
        from datetime import date
        return date(year, month, day).isoformat(), m.group(1)
    except ValueError:
        return None, m.group(1)


def parse_notice(post: dict) -> dict:
    """The parsed notice (the only thing saved): kind, stations, sampling date, DRNA's words."""
    html = (post.get("content") or {}).get("rendered") or ""
    text = text_of(html)
    pub = (post.get("date_gmt") or "")[:19] + "Z" if post.get("date_gmt") else None
    mod = (post.get("modified_gmt") or "")[:19] + "Z" if post.get("modified_gmt") else None
    sampled, words = sample_date(text, pub or "2000-01")
    rows = table_rows(html)
    listed, unknown = [], []
    for code, name, town in rows:
        st, note = station_of(code, name)
        if not (code or name):
            continue
        (listed if st else unknown).append({"station": st, "code": code.strip(), "name": name.strip(),
                                            "municipio": town.strip(), "note": note})
    ex = EXCEED.search(text)
    if ex and (listed or unknown):
        kind = "exceed"
    elif FIT_LIST.search(text) and (listed or unknown):
        kind = "fit_list"
    elif ALL_FIT.search(text) and not rows:
        kind = "all_fit"
    else:
        kind = "unread"
    return {"id": post.get("id"), "published": pub, "modified": mod, "link": post.get("link"), "kind": kind,
            "sampled": sampled, "sample_words": words, "advice": ex.group(1).strip() if ex else None,
            "listed": listed, "unknown": unknown}


def records(notices: list[dict], at: str) -> tuple[list[dict], dict]:
    """The advisory runs (module docstring) from the notices, oldest first."""
    ns = sorted([n for n in notices if n.get("published")], key=lambda n: (n["published"], n["id"]))
    readable = [n for n in ns if n["kind"] != "unread"]
    newest = readable[-1]["id"] if readable else None
    open_runs: dict[str, dict] = {}
    runs: list[dict] = []
    for n in readable:
        listed = {x["station"]: x for x in n["listed"]} if n["kind"] == "exceed" else {}
        ends = set(open_runs) if n["kind"] in ("exceed", "all_fit") else {x["station"] for x in n["listed"]}
        for st in sorted(ends - set(listed)):
            if st in open_runs:
                run = open_runs.pop(st)
                run["end"] = n
        for st, x in listed.items():
            if st in open_runs:
                open_runs[st]["notices"].append((n, x))
            else:
                open_runs[st] = {"station": st, "notices": [(n, x)], "end": None}
                runs.append(open_runs[st])
        for x in n["unknown"] if n["kind"] == "exceed" else []:
            runs.append({"station": None, "notices": [(n, x)], "end": None, "unknown": True})
    out = [_record(r, at, newest) for r in runs]
    meta = {"notices": len(ns), "by_kind": {k: sum(1 for n in ns if n["kind"] == k)
                                             for k in ("exceed", "all_fit", "fit_list", "unread")},
            "unread_notices": [n["id"] for n in ns if n["kind"] == "unread"],
            "newest_notice": readable[-1]["published"] if readable else None,
            "station_notes": sorted({x["note"] for n in ns for x in n["listed"] if x.get("note")})}
    return out, meta


def _record(run: dict, at: str, newest) -> dict:
    first, x0 = run["notices"][0]
    last, _ = run["notices"][-1]
    st = run["station"]
    end = run["end"]
    unknown = run.get("unknown")
    info = STATIONS.get(st) if st else None
    name, town = (info[0], info[1]) if info else (x0["name"], x0["municipio"])
    raw = {
        "station": st, "listed_as": sorted({x["code"] for _, x in run["notices"]}),
        "names_as_listed": sorted({x["name"] for _, x in run["notices"]}),
        "municipio": town, "time_zone": TIME_ZONE,
        "notices": [{"id": n["id"], "published": n["published"], "sampled": n["sampled"],
                     "sample_dates": n["sample_words"], "link": n["link"]} for n, _ in run["notices"]],
        "sample_dates": first["sample_words"],
        "start_basis": "the publication of DRNA's notice that first listed the beach (its date_gmt); the sampling "
                       "date is kept apart in sampled_at",
        "bav_rule": "Beach Action Value for enterococci, 70 colonies per 100 mL (DRNA's notice)",
    }
    notes = sorted({x["note"] for _, x in run["notices"] if x.get("note")})
    if notes:
        raw["station_note"] = "; ".join(notes)
    if info:
        raw["point_basis"] = POINT_BASIS.format(info[2])
        raw["point_url"] = WQP.format(info[2])
        raw["station_table"] = TABLE_URL
    status = "advisory_active"
    ended_at = None
    if end is not None:
        status, ended_at = "advisory_lifted", end["published"]
        raw["ended_at_precision"] = "minute"
        raw["end_basis"] = (f"DRNA's notice published {end['published']} (post {end['id']}) "
                            + ("says the program's beaches are fit for bathers" if end["kind"] == "all_fit" else
                               "lists the beach among those fit for bathers" if end["kind"] == "fit_list" else
                               "does not list this beach")
                            + "; DRNA publishes no other lift time")
        raw["ended_by_notice"] = end["id"]
    elif last["id"] == newest:
        raw["_last_seen_in_source"] = at
    advice = first.get("advice") or "no son aptas para bañistas"
    return event(
        source_id=SOURCE_ID, source_record_id=f"{st or 'unknown-' + fold(x0['code'] or x0['name'])}:{first['id']}",
        event_type="beach_advisory", status=status,
        waterbody_text=f"{name} ({town})" if town else name,
        lat=info[3] if info else None, lon=info[4] if info else None,
        coord_source="station_point" if info else None,
        started_at=first["published"], ended_at=ended_at, time_precision="minute", sampled_at=first["sampled"],
        published_at=first["published"], source_updated_at=last.get("modified") or last["published"],
        material="enterococci bacteria above the Beach Action Value",
        authority=AUTHORITY,
        advice_text=f"DRNA: la(s) siguiente(s) playa(s) “{advice}”",
        advice_window_basis="in effect until a later DRNA notice no longer lists the beach",
        source_url=first.get("link"), raw=raw,
        parse_error=(f"station {x0['code']!r} ({x0['name']}) is not in DRNA's station table: no point"
                     if unknown else None),
    )


def fetch(all_pages: bool) -> tuple[list[dict], str | None]:
    posts, page, pages = [], 1, 1
    while page <= pages:
        r = requests.get(URL, params={**PARAMS, "page": str(page)}, headers=HEADERS, timeout=120)
        r.raise_for_status()
        posts += r.json()
        pages = int(r.headers.get("X-WP-TotalPages") or 1) if all_pages else 1
        page += 1
    return posts, None


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = argv[argv.index("--at") + 1] if "--at" in argv else now_iso()
    files = []
    if "--file" in argv:
        i = argv.index("--file") + 1
        while i < len(argv) and not argv[i].startswith("--"):
            files.append(Path(argv[i]))
            i += 1
    state = read_json(STATE_PATH, {}) or {}
    known = {n["id"]: n for n in state.get("notices", [])}
    try:
        if files:
            posts = [p for f in files for p in json.loads(f.read_text())]
        else:
            posts, _ = fetch("--all" in argv or not known)
    except (requests.RequestException, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    parsed = [parse_notice(p) for p in posts if isinstance(p, dict) and p.get("id")]
    if not parsed:
        write_events(SOURCE_ID, [], ok=False, error="no notices in the response")
        return 1
    for n in parsed:
        known[n["id"]] = n
    notices = sorted(known.values(), key=lambda n: (n.get("published") or "", n["id"]))
    if not files:
        save_raw(SOURCE_ID, json.dumps(parsed, ensure_ascii=False), "json")
        write_json(STATE_PATH, {"source_id": SOURCE_ID, "updated": at, "notices": notices})
    recs, meta = records(notices, at)
    meta.update(registry_ids=[SOURCE_ID], url=URL, station_table=TABLE_URL,
                cadence="weekly notices; read with the refresh")
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} records from {len(notices)} notices "
          f"({sum(r['status'] == 'advisory_active' for r in recs)} in effect) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
