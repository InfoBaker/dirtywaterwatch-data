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
  A fit statement counts only when affirmed: a negation anywhere before it in its sentence ("no se encuentran aptas",
  "ninguna ... se encuentra apta", "aún no están aptas"), a condition ("si", "cuando", "una vez", "hasta que") or an
  exception ("excepto", "salvo") makes the notice unread, never a lift; the future ("se encontrarán") is not read.
  The lift's subject must be the programme's beaches ("las playas que son parte del Programa de Playas", "todas las
  playas incluidas en el Programa de Playas"): one beach that "se encuentra apta", or named beaches, lifts nothing
  (unread). A plan, an expectation or a possibility ("se espera", "podrían", "pendiente") is a condition. The "no son
  aptas" list is read only when it is not conditional or planned ("Si los resultados se confirman, ...": unread)
  (Astra verify P1-3).
  The sampling date(s) are read from the text as DRNA writes them ("del 2 y 3 de noviembre de 2026"): sampled_at is
  the first day, raw.sample_dates the words. A sample date is never an advisory's start.
  Versions (merge_notice; Astra review P1-2): a post re-read with a different listing keeps every version read. A
  revision of the newest notice applies at its modified_gmt: a beach it adds starts then (raw.start_basis says so, id
  <station>:<post>r<n>), a beach it drops ends then with poll precision; nothing first read is erased. A version's time
  is its modified_gmt when first read: a later re-read with the same listing and a newer modified_gmt keeps that time
  (the newer one is kept apart in modified_latest), so a re-read never moves a start or turns a revision late. A revision
  dated after a newer notice was published is kept and listed in meta.late_revisions, not applied.

Records (the accuracy-first pattern, docs/generic-ingesters.md: sampled_at apart, no sample date as a start)
  One record per run of consecutive readable notices that list a station: event_type beach_advisory, DRNA's own
  advisory ("no son aptas para bañistas"), quoted in Spanish as written (advice_text; never translated inside the
  quotation). started_at and published_at are the publication time of the first notice of the run (date_gmt, given by
  DRNA; time_precision minute); sampled_at its first sampling day. Ends (Astra review P1-1):
  - an explicit statement (an "all_fit" notice, or a "fit_list" naming the beach): ended_at its publication,
    raw.ended_at_precision "minute", DRNA's own lift;
  - a later list without the beach (an omission): ended_at that notice's publication with raw.ended_at_precision
    "poll" and raw._last_seen_in_source the last notice that listed it; DRNA states no lift, so the status build stops
    the colour 14 days after that notice (status.POLL_END_HORIZON_SOURCES) however long DRNA waits between notices;
  - a list with a row no station is matched to, a row with fewer than three cells, or a table or row opened and not
    closed ends nothing (the unread part may be the beach) and reconfirms nothing; when it is the newest notice the feed
    is written with ok false (partial, meta.incomplete_blocking) until a complete notice is read (Astra verify P1-2).
    A post with no id or no date_gmt is never skipped silently: meta.malformed_posts lists it and the feed is not ok.
  raw.end_basis, raw.ended_by_notice and raw.end_url cite the notice. A run the newest notice lists is
  advisory_active with no end and raw._last_seen_in_source this poll's time; when the newest notice cannot be read the
  confirmation stays where the last run left it (state file "confirmed"), and the feed is written with ok false
  (partial) until it is read (P1-3). Unread posts older than the first readable notice (the 2019 PDF-only posts) are
  listed and do not fail the feed. event id: pr-drna-beach-notices:<station>:<first post id> (stable).
  The notices list only the beaches over the value: a beach not listed, a notice that the beaches are fit for bathers,
  and a green flag at a beach are never records here, and never a clean or passing status (grey: no report).

Stations (STATIONS, station_of; Astra review P2-2): DRNA's station table (Identificaciones de las Playas,
  wp-content/uploads/2020/06/Tabla-playas.pdf: 36 stations RW-1 to RW-39) with one public point each, the station's
  own monitoring location in the Water Quality Portal (organization PR_BEACH_WQX, Puerto Rico Environmental Quality
  Board (Beach), whose beach program DRNA continues; read 2026-11-14), cited in raw.point_basis and raw.point_url
  (coord_source "station_point"; rounded to three decimals). The notice's station number is normalised (RW-06 -> RW-6,
  RWW-28 -> RW-28, RW14A -> RW-14, RW-25 -> RW-25A). The beach's name is matched whole against the station's own
  names (the table's and the forms DRNA's notices give it), never as a part of a longer name: number and name agree
  (a municipality typed otherwise is kept in raw.station_note); a name with no number of the table only in the
  station's municipality; a name against another station's number only for the two evidenced corrections
  (CODE_CORRECTIONS: Playa Cabullón, Ponce, listed as RW-30; Muelle de Arecibo as RW-28). Anything else is a record
  with no point, a parse_error and raw.place_unknown saying its place on the map is not known and why; never dropped.
  waterbody_text is the beach and municipality in DRNA's table's words; placement by the point only (a marker),
  never a whole-water colour.

Privacy (Astra review P1-5): only the parsed notices are saved (data/raw/pr-drna-beach-notices/<stamp>.json and the
  state file), cut before the first save: a matched row keeps the station's name as DRNA wrote it (one of its names);
  an unmatched row keeps a code of the station form, a name that reads as a place (a beach word first, letters only)
  and a municipality of Puerto Rico, else "[withheld]"; the advice is DRNA's standard wording or "no son aptas para
  bañistas"; undated sampling words only when they are digits and month words; the link only DRNA's. Notices carried
  from an earlier state file are cut the same way (sanitize_notice).

Cadence: weekly posts; read with the refresh (page 1, the newest 100, merged with the notices already read; every page
  on a first run or with --all). Run from pipeline/:
  python -m ingest.pr_drna_beaches [--file posts.json ...] [--all] [--at 2026-11-14T12:00:00Z]
"""
from __future__ import annotations

import hashlib
import html as htmllib
import json
import re
import sys
import unicodedata
from pathlib import Path

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, scrub_text, write_events, write_json

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

# station: (DRNA's table name, municipality, WQX station, lat, lon, the other names DRNA's notices give it); points from
# the WQP station list. A name is matched whole after norm(), never as a part of a longer name (Astra P2-2).
STATIONS = {
    "RW-1": ("Balneario de Luquillo (La Monserrate)", "Luquillo", "RW-1A", 18.386, -65.729,
             ("balneario de luquillo monserrate", "balneario la monserrate", "balneario de luquillo")),
    "RW-2": ("Balneario Seven Seas", "Fajardo", "RW-2", 18.369, -65.636, ()),
    "RW-4": ("Balneario Punta Santiago", "Humacao", "RW-4", 18.158, -65.755, ()),
    "RW-5": ("Balneario de Rincón", "Rincón", "RW-5", 18.341, -67.256, ("balneario rincon",)),
    "RW-6": ("Balneario de Patillas", "Patillas", "RW-6", 17.974, -65.989,
             ("balneario de patilla", "balneariode patillas")),
    "RW-7": ("Balneario Punta Guilarte", "Arroyo", "RW-7", 17.962, -66.040, ()),
    "RW-8": ("Playa Buyé", "Cabo Rojo", "RW-8", 18.049, -67.199, ()),
    "RW-9": ("Balneario Caña Gorda", "Guánica", "RW-9", 17.953, -66.885, ("cana gorda",)),
    "RW-10": ("Playa Santa", "Guánica", "RW-10", 17.938, -66.955, ()),
    "RW-12": ("Playa Combate", "Cabo Rojo", "RW-12B", 17.975, -67.213, ("playa el combate",)),
    "RW-13": ("Balneario Boquerón", "Cabo Rojo", "RW-13", 18.019, -67.172, ("balneario de boqueron",)),
    "RW-14": ("Playa Mojacasabe", "Cabo Rojo", "RW-14A", 17.986, -67.215, ("playa moja casabe",)),
    "RW-15": ("Balneario de Añasco (Tres Hermanos)", "Añasco", "RW-15", 18.288, -67.194,
              ("balneario de anasco", "balneario de anasco balneario tres hermanos",
               "balneario de anasco o balneario tres hermanos", "balneario tres hermanos")),
    "RW-16": ("Playa Crash Boat", "Aguadilla", "RW-16", 18.458, -67.164, ("balneario crash boat",)),
    "RW-17": ("Balneario Cerro Gordo", "Vega Alta", "RW-17", 18.481, -66.341,
              ("balneario cerro gordo or javier calderon nieves",)),
    "RW-18": ("Balneario Sardinera (Manuel “Nolo” Morales)", "Dorado", "RW-18", 18.475, -66.281,
              ("balneario manuel nolo morales sardinera", "balneario manuel nolo morales",
               "balneario nolo morales sardinera", "balneario manuel nolo morales or sardinera",
               "balneario sardinera o manuel nolo morales", "manuel nolo morales sardinera", "balneario sardinera")),
    "RW-19": ("Balneario Punta Salinas", "Toa Baja", "RW-19", 18.472, -66.186, ()),
    "RW-20": ("Balneario El Escambrón", "San Juan", "RW-20A", 18.467, -66.090, ("balneario de escambron",)),
    "RW-21": ("Balneario de Carolina", "Carolina", "RW-21C", 18.446, -66.004, ()),
    "RW-22": ("Balneario de Aguada (Pico de Piedra)", "Aguada", "RW-22", 18.384, -67.213,
              ("balneario de pico de piedra", "balneario pico de piedra", "pico de piedra", "balneario de aguada")),
    "RW-23": ("Balneario Puerto Nuevo", "Vega Baja", "RW-23", 18.491, -66.399, ("balneario de puerto nuevo",)),
    "RW-25A": ("Playa Sixto Escobar", "San Juan", "RW-25A", 18.467, -66.087, ()),
    "RW-26": ("Playita del Condado", "San Juan", "RW-26", 18.461, -66.082, ()),
    "RW-27": ("Playa Ocean Park", "San Juan", "RW-27", 18.453, -66.049, ("ocean park",)),
    "RW-28": ("Playa El Alambique", "Carolina", "RW-28", 18.444, -66.022, ()),
    "RW-29": ("Playa Vacía Talega", "Loíza", "RW-29", 18.448, -65.906, ("vacia talega",)),
    "RW-30": ("Playa Guayanés", "Yabucoa", "RW-30", 18.063, -65.819, ()),
    "RW-31": ("Tropical Beach", "Naguabo", "RW-31", 18.187, -65.726, ("playa tropical beach", "playa tropic al beach")),
    "RW-32": ("Playa Azul", "Luquillo", "RW-32", 18.382, -65.718, ()),
    "RW-33": ("Playita Rosada", "Lajas", "RW-33", 17.972, -67.032, ()),
    "RW-34": ("Playa Cabullón", "Ponce", "RW-34", 17.969, -66.603, ()),
    "RW-35": ("Playa Jauca", "Santa Isabel", "RW-35", 17.960, -66.370, ()),
    "RW-36": ("Balneario de Salinas", "Salinas", "RW-36", 17.978, -66.332, ()),
    "RW-37": ("Playa Villa Lamela", "Cabo Rojo", "RW-37", 18.065, -67.198, ("villa lamela",)),
    "RW-38": ("Playa Muelle de Arecibo", "Arecibo", "RW-38", 18.480, -66.700, ("muelle de arecibo",)),
    "RW-39": ("Playa Mar Chiquita", "Manatí", "RW-39", 18.473, -66.486, ("mar chiquita",)),
}
ALIASES = {"RW-1A": "RW-1", "RW-12B": "RW-12", "RW-14A": "RW-14", "RW-20A": "RW-20", "RW-21C": "RW-21",
           "RW-25": "RW-25A"}
# the only station numbers the beach's name may override: each seen in a saved notice, the beach and its municipality
# those of the other station in DRNA's table (2026-10-16: Playa Cabullón, Ponce, as RW-30; Muelle de Arecibo as RW-28)
CODE_CORRECTIONS = {("RW-30", "RW-34"), ("RW-28", "RW-38")}
# Puerto Rico's 78 municipalities (for a row whose station is unknown: a municipality is kept only when it is one)
MUNICIPIOS = (
    "Adjuntas Aguada Aguadilla|Aguas Buenas|Aibonito|Añasco|Arecibo|Arroyo|Barceloneta|Barranquitas|Bayamón|Cabo Rojo|"
    "Caguas|Camuy|Canóvanas|Carolina|Cataño|Cayey|Ceiba|Ciales|Cidra|Coamo|Comerío|Corozal|Culebra|Dorado|Fajardo|"
    "Florida|Guánica|Guayama|Guayanilla|Guaynabo|Gurabo|Hatillo|Hormigueros|Humacao|Isabela|Jayuya|Juana Díaz|Juncos|"
    "Lajas|Lares|Las Marías|Las Piedras|Loíza|Luquillo|Manatí|Maricao|Maunabo|Mayagüez|Moca|Morovis|Naguabo|Naranjito|"
    "Orocovis|Patillas|Peñuelas|Ponce|Quebradillas|Rincón|Río Grande|Sabana Grande|Salinas|San Germán|San Juan|"
    "San Lorenzo|San Sebastián|Santa Isabel|Toa Alta|Toa Baja|Trujillo Alto|Utuado|Vega Alta|Vega Baja|Vieques|"
    "Villalba|Yabucoa|Yauco").replace("Adjuntas Aguada Aguadilla", "Adjuntas|Aguada|Aguadilla").split("|")
MONTHS = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                      "septiembre", "octubre", "noviembre", "diciembre"), 1)}
MONTHS["setiembre"] = 9
SAMPLE = re.compile(r"muestreos?\s+(?:realizados?\s+)?(?:del?|el|los)\s+((\d{1,2})(?:\s*(?:,|y|al|-)\s*\d{1,2})*"
                    r"\s+(?:de\s+)?(" + "|".join(MONTHS) + r")(?:\s+(?:de|del)\s+(\d{4}))?)", re.I)
SAMPLE_WORDS = re.compile(r"muestreos?\s+(?:realizados?\s+)?(?:del?|el|los)\s+(.{1,40}?),?\s+realizad", re.I)
# the words kept from an undated sampling phrase: digits, separators and month words only (privacy, Astra P1-5)
SAFE_SAMPLE_WORDS = re.compile(r"^[\d\s,y\-]*(?:(?:de\s+)?(?:" + "|".join(MONTHS) + r"))?[\d\s,de]*$", re.I)
EXCEED = re.compile(r"(no\s+son\s+aptas?\s+para\s+bañistas[^:]*)", re.I)
# DRNA's standard wording, the only advice kept beyond "no son aptas para bañistas" (privacy, Astra P1-5)
ADVICE_FULL = re.compile(r"no\s+son\s+aptas?\s+para\s+bañistas\s+por\s+exceder\s+el\s+[“\"]\s*Beach\s+Action\s+Value\s*"
                         r"[”\"]\s*\(BAV\)\s+para\s+el\s+parámetro\s+de\s+Enterococos\s*\(\s*70\s+colonias\s*/\s*100\s*mL\s*\)",
                         re.I)
# the programme's own statement, its subject the programme's beaches (Astra verify P1-3): "las playas que son parte del
# Programa de Playas" or "todas las playas incluidas en el Programa de Playas" (every form in the 280 posts read
# 2026-11-14); one beach that "se encuentra apta", or named beaches, is not every beach and lifts nothing
ALL_FIT = re.compile(r"(?:todas\s+)?las\s+playas\s+(?:que\s+son\s+parte\s+del|incluidas\s+en\s+el)\s+Programa\s+de\s+"
                     r"Playas\s*,?\s*se\s+encuentran\s+aptas\s+para\s+bañistas", re.I)
FIT_LIST = re.compile(r"\b(?:están|estan)\s+aptas?\s+para\s+bañistas\s+por\s+no\s+exceder", re.I)
# Spanish negation, condition and exception around a statement that beaches are fit (lessons 1 and 11): "no se
# encuentran aptas", "ninguna ... se encuentra apta", "aún no están aptas", "se encuentran aptas, excepto ...", "una
# vez ... se encuentran aptas", "si los resultados ... se encuentran aptas" are not a lift
NEGATED = re.compile(r"\b(?:no|ni|nunca|ninguna?s?|ningún|ningun|tampoco)\b", re.I)
CONDITION = re.compile(r"\b(?:si|cuando|una\s+vez|hasta\s+que|en\s+cuanto|siempre\s+que|de\s+ser|en\s+caso\s+de|"
                       r"tan\s+pronto|"
                       # planned, expected or possible, not done (Astra verify P1-3)
                       r"se\s+espera|se\s+anticipa|se\s+proyecta|se\s+prev[eé]|se\s+estima|podr[ií]an?|deber[ií]an?|"
                       r"probablemente|posiblemente|pendiente)\b", re.I)
EXCEPTION = re.compile(r"\b(?:excepto|salvo|con\s+excepci[oó]n|a\s+excepci[oó]n|menos\s+(?:la|las|el|los)|"
                       r"except[ou]ando)\b", re.I)
STATION = re.compile(r"^\W*R\s*W+\s*-?\s*0*(\d{1,2})\s*([A-Z])?\s*$", re.I)
BEACH_WORD = re.compile(r"^(?:playa|playita|balneario|bah[ií]a|muelle|laguna|r[ií]o|punta|cayo|isla|caño|cano)\b", re.I)
LINK_PREFIX = "https://www.drna.pr.gov/"


def fold(s: str) -> str:
    """Lower case, accents off, spaces folded (for the name rules only; text is kept as DRNA writes it)."""
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip().lower()


def norm(s: str) -> str:
    """fold() with every mark other than a letter or a digit read as a space: the form a station's names are matched in."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", fold(s))).strip()


def _town_key(s: str) -> str:
    return re.sub(r"[^a-z]", "", fold(s))


def _near(a: str, b: str) -> bool:
    """One letter's difference at most ('Dorad0', 'Sannjuan'): DRNA's typing, not another municipality."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1 or not a or not b:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:] or (len(a) == len(b) and a[i + 1:] == b[i + 1:])


def same_town(listed: str, station: str) -> bool:
    return _near(_town_key(listed), _town_key(STATIONS[station][1]))


STATION_NAMES = {k: {norm(v[0]), *(norm(a) for a in v[5])} for k, v in STATIONS.items()}
_TOWN_KEYS = {_town_key(m): m for m in MUNICIPIOS}


def text_of(html: str) -> str:
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", html or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def table_read(html: str) -> tuple[list[tuple[str, str, str]], dict]:
    """(rows, what was incomplete) of a notice's table (Astra verify P1-2). A row with fewer than three cells is kept
    (padded) and counted as short; a table or row opened and not closed is counted. A notice with either ends no
    advisory (the missing part may be any beach) and, when it is the newest, fails the feed's health."""
    out, short = [], 0
    h = html or ""
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S | re.I):
        cells = [text_of(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        if not any(cells) or fold(cells[0]).startswith("estaci"):
            continue
        if len(cells) < 3:
            short += 1
        out.append(tuple((cells + ["", "", ""])[:3]))
    unclosed = (len(re.findall(r"<table\b", h, re.I)) > len(re.findall(r"</table>", h, re.I))
                or len(re.findall(r"<tr\b", h, re.I)) > len(re.findall(r"</tr>", h, re.I)))
    inc = {}
    if short:
        inc["short_rows"] = short
    if unclosed:
        inc["table_not_closed"] = True
    return out, inc


def table_rows(html: str) -> list[tuple[str, str, str]]:
    return table_read(html)[0]


def code_station(code: str) -> str | None:
    """The station a notice's number names (normalised: RW-06 -> RW-6, RW-25 -> RW-25A), or None."""
    m = STATION.match(code or "")
    if not m:
        return None
    key = f"RW-{int(m.group(1))}{(m.group(2) or '').upper()}"
    if ALIASES.get(key, key) in STATIONS:
        return ALIASES.get(key, key)
    return f"RW-{int(m.group(1))}" if f"RW-{int(m.group(1))}" in STATIONS else None


def station_of(code: str, name: str, town: str | None = None) -> tuple[str | None, str | None]:
    """(station, note) of one row of a notice, or (None, why) (Astra P2-2). The beach's name is matched whole against
    the station's own names (STATIONS), never as a part of a longer or qualified name. A station is accepted when the
    number and the name agree; a name with no number of the table when the municipality is the station's; a name
    against another station's number only for an evidenced correction (CODE_CORRECTIONS) in the station's
    municipality; a number with no name. Anything else is refused: the record is kept with no point."""
    by_code = code_station(code)
    n = norm(name)
    by_name = [k for k, names in STATION_NAMES.items() if n in names] if n else []
    by_name = by_name[0] if len(by_name) == 1 else None
    town = town if town is not None else ""
    if by_code and (by_name == by_code or not n):
        if town and not same_town(town, by_code):
            return by_code, f"listed in {town.strip()}; DRNA's station table has {by_code} in {STATIONS[by_code][1]}"
        return by_code, None
    if by_name and not by_code:
        if town and same_town(town, by_name):
            return by_name, None
        return None, (f"the name is that of {by_name} in DRNA's station table, but the row gives no station number of "
                      f"the table and {'no municipality' if not town else 'another municipality'}")
    if by_name and by_code:
        cm = STATION.match(code or "")
        listed_code = f"RW-{int(cm.group(1))}" if cm else None
        if (listed_code, by_name) in CODE_CORRECTIONS and town and same_town(town, by_name):
            return by_name, (f"listed as {code.strip()}; the beach's name ({name.strip()}) is that of "
                             f"{by_name} in DRNA's station table")
        return None, f"the number is {by_code}'s and the name {by_name}'s in DRNA's station table"
    if by_code:
        return None, f"the number is {by_code}'s but the name is not one of its names in DRNA's station table"
    return None, "neither the number nor the name is in DRNA's station table"


def sample_date(text: str, published: str) -> tuple[str | None, str | None]:
    """(first sampling day as ISO, the words) from the notice; a year left out is the publication's (or the year
    before, for a December sample in a January notice). Undated words are kept only when they are digits, separators
    and month words."""
    m = SAMPLE.search(text)
    if not m:
        w = SAMPLE_WORDS.search(text)     # words DRNA wrote that give no date ('del 6, 8 y 9 2020'): kept, no date
        words = w.group(1).strip() if w else None
        return None, words if words and SAFE_SAMPLE_WORDS.match(words) else None
    day, month = int(m.group(2)), MONTHS[m.group(3).lower()]
    year = int(m.group(4)) if m.group(4) else int(published[:4]) - (1 if month > int(published[5:7]) else 0)
    try:
        from datetime import date
        return date(year, month, day).isoformat(), m.group(1)
    except ValueError:
        return None, m.group(1)


def affirmed(rx: re.Pattern, text: str) -> bool:
    """rx matches in an affirmative, unconditional sentence with no exception (Spanish negation, condition and
    exception rules: NEGATED, CONDITION, EXCEPTION)."""
    for m in rx.finditer(text):
        a = max(text.rfind(".", 0, m.start()), text.rfind(";", 0, m.start()), text.rfind(":", 0, m.start())) + 1
        b = [i for i in (text.find(".", m.end()), text.find(";", m.end())) if i >= 0]
        sentence_before, rest = text[a:m.start()], text[m.end():min(b) if b else len(text)]
        if NEGATED.search(sentence_before) or CONDITION.search(sentence_before) or CONDITION.search(rest):
            continue
        if EXCEPTION.search(sentence_before) or EXCEPTION.search(rest):
            continue
        return True
    return False


def exceed_affirmed(text: str) -> re.Match | None:
    """The "no son aptas para bañistas" statement when it is DRNA's finding, not a condition, a plan or an expectation
    ("Si los resultados se confirman, la(s) siguiente(s) playa(s) no son aptas ...": Astra verify P1-3)."""
    for m in EXCEED.finditer(text):
        a = max(text.rfind(".", 0, m.start()), text.rfind(";", 0, m.start()), text.rfind(":", 0, m.start())) + 1
        if not CONDITION.search(text[a:m.start()]):
            return m
    return None


def _safe_unknown_name(name: str) -> str:
    """An unmatched row's beach name, kept only when it reads as a place (a beach word first, letters only, six words
    at most), else withheld: a cell that cannot be told apart from a person's name or address is not saved."""
    t = re.sub(r"\s+", " ", name or "").strip()
    if t and BEACH_WORD.match(fold(t)) and len(t.split()) <= 6 and not re.search(r"[\d@/:]", t):
        return scrub_text(t)
    return "[withheld: not a name in DRNA's station table]" if t else ""


def _safe_town(town: str) -> str:
    t = _town_key(town)
    hit = _TOWN_KEYS.get(t) or next((m for k, m in _TOWN_KEYS.items() if _near(t, k)), None)
    return hit or ("[withheld]" if t else "")


def _safe_code(code: str) -> str:
    c = re.sub(r"\s+", " ", code or "").strip()
    return c if STATION.match(c) else ("[unreadable]" if c else "")


def parse_notice(post: dict) -> dict:
    """The parsed notice (the only thing saved): kind, stations, sampling date, DRNA's words. Every saved text is cut
    to what the site uses before any save (Astra P1-5): a matched station's row keeps the name only when it is one of
    the station's names; an unmatched row keeps a code of the station form, a place-like name and a municipality of
    Puerto Rico, else withholds them; the advice is DRNA's standard wording or its first words; the link only DRNA's."""
    html = (post.get("content") or {}).get("rendered") or ""
    text = text_of(html)
    pub = (post.get("date_gmt") or "")[:19] + "Z" if post.get("date_gmt") else None
    mod = (post.get("modified_gmt") or "")[:19] + "Z" if post.get("modified_gmt") else None
    sampled, words = sample_date(text, pub or "2000-01")
    rows, incomplete = table_read(html)
    listed, unknown = [], []
    for code, name, town in rows:
        if not (code or name):
            continue
        st, note = station_of(code, name, town)
        if st:
            listed.append({"station": st, "code": _safe_code(code), "name": re.sub(r"\s+", " ", name).strip(),
                           "municipio": _safe_town(town), "note": note})
        else:
            unknown.append({"station": None, "code": _safe_code(code), "name": _safe_unknown_name(name),
                            "municipio": _safe_town(town), "note": note})
    ex = exceed_affirmed(text)
    if ex and (listed or unknown):
        kind = "exceed"
    elif affirmed(FIT_LIST, text) and (listed or unknown):
        kind = "fit_list"
    elif affirmed(ALL_FIT, text) and not rows:
        kind = "all_fit"
    else:
        kind = "unread"
    advice = None
    if ex:
        full = ADVICE_FULL.match(ex.group(1).strip())
        advice = re.sub(r"\s+", " ", full.group(0)) if full else "no son aptas para bañistas"
    link = post.get("link") if isinstance(post.get("link"), str) and post["link"].startswith(LINK_PREFIX) else None
    return {"id": post.get("id"), "published": pub, "modified": mod, "link": link, "kind": kind,
            "sampled": sampled, "sample_words": words, "advice": advice, "listed": listed, "unknown": unknown,
            "incomplete": incomplete}


def sanitize_notice(n: dict) -> dict:
    """A notice carried from an earlier state file, cut to the same fields and forms parse_notice saves (lesson 6)."""
    keep = ("id", "published", "modified", "link", "kind", "sampled", "sample_words", "advice", "listed", "unknown")
    out = {k: n.get(k) for k in keep}
    inc = n.get("incomplete") if isinstance(n.get("incomplete"), dict) else {}
    out["incomplete"] = {k: v for k, v in inc.items() if (k == "short_rows" and isinstance(v, int)
                                                          and not isinstance(v, bool)) or (k == "table_not_closed"
                                                                                           and v is True)}
    for k in ("modified_latest",):
        if isinstance(n.get(k), str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", n[k]):
            out[k] = n[k]
    if not (isinstance(out["link"], str) and out["link"].startswith(LINK_PREFIX)):
        out["link"] = None
    if out["sample_words"] and not (SAMPLE.search("muestreos del " + out["sample_words"])
                                    or SAFE_SAMPLE_WORDS.match(out["sample_words"])):
        out["sample_words"] = None
    if out["advice"] and not ADVICE_FULL.fullmatch(out["advice"]):
        out["advice"] = "no son aptas para bañistas"
    rows = []
    for x in out.get("listed") or []:
        st = x.get("station")
        ok = st in STATIONS and norm(x.get("name") or "") in STATION_NAMES[st] | {""}
        rows.append({"station": st, "code": _safe_code(x.get("code") or ""),
                     "name": (x.get("name") or "") if ok else STATIONS[st][0] if st in STATIONS else "",
                     "municipio": _safe_town(x.get("municipio") or ""), "note": x.get("note") if ok else None})
    out["listed"] = [r for r in rows if r["station"] in STATIONS]
    out["unknown"] = [{"station": None, "code": _safe_code(x.get("code") or ""),
                       "name": _safe_unknown_name(x.get("name") or ""),
                       "municipio": _safe_town(x.get("municipio") or ""), "note": None}
                      for x in out.get("unknown") or []]
    if isinstance(n.get("versions"), list):
        out["versions"] = [sanitize_notice(v) for v in n["versions"]]
    return out


def _listing(n: dict) -> tuple:
    return (n.get("kind"), tuple(sorted(x["station"] for x in n.get("listed") or [])),
            tuple(sorted((x.get("code") or "", x.get("name") or "") for x in n.get("unknown") or [])))


def merge_notice(known: dict | None, new: dict) -> dict:
    """The notice kept for a post id, with every version read (Astra P1-2): a re-read whose listing (kind, stations,
    unmatched rows) differs from the last version kept adds a version; one that does not only refreshes the fields
    read. The first version is the one first read; nothing read is ever replaced."""
    if not known:
        return {**new, "versions": [dict(new)]}
    versions = list(known.get("versions") or [{k: v for k, v in known.items() if k != "versions"}])
    if _listing(versions[-1]) != _listing(new):
        versions.append(dict(new))
    else:
        # the version's own time (its modified_gmt when first read) is kept: a later re-read with the same listing and
        # a newer modified_gmt only records that time apart (modified_latest), never moves the version (Astra verify P1-1)
        seen = [x for x in (new.get("modified"), versions[-1].get("modified_latest"), versions[-1].get("modified")) if x]
        versions[-1] = {**versions[-1], "modified_latest": max(seen) if seen else None}
    return {**versions[0], "versions": versions}


def _versions(n: dict) -> list[dict]:
    vs = n.get("versions")
    return vs if isinstance(vs, list) and vs else [{k: v for k, v in n.items() if k != "versions"}]


def records(notices: list[dict], at: str, confirmed: dict | None = None) -> tuple[list[dict], dict]:
    """The advisory runs (module docstring) from the notices and their versions, oldest first. `confirmed`: the
    confirmation times of the previous run's advisories in effect (record id -> time), kept when the newest notice
    cannot be read (Astra P1-3)."""
    ns = sorted([n for n in notices if n.get("published")], key=lambda n: (n["published"], n["id"]))
    pubs = sorted(n["published"] for n in ns)
    steps = []
    late = []
    for n in ns:
        for i, v in enumerate(_versions(n)):
            t = n["published"] if i == 0 else (v.get("modified") or n["published"])
            if i and any(n["published"] < p <= t for p in pubs):
                late.append({"id": n["id"], "revised": t, "kind": v.get("kind"),
                             "why": "revised after a newer notice was published: kept, not applied to the runs"})
                continue
            steps.append((t, n["published"], n["id"], i, n, v))
    steps.sort(key=lambda s: s[:4])
    readable_steps = [s for s in steps if s[5].get("kind") != "unread"]
    first_readable = readable_steps[0][0] if readable_steps else None
    newest = steps[-1] if steps else None
    newest_unread = bool(newest) and newest[5].get("kind") == "unread"
    open_runs: dict[str, dict] = {}
    runs: list[dict] = []
    for t, pub, pid, i, n, v in steps:
        kind = v.get("kind")
        if kind == "unread":
            continue
        step = {"time": t, "id": pid, "published": pub, "revision": i, "link": v.get("link") or n.get("link"),
                "kind": kind, "sampled": v.get("sampled"), "sample_words": v.get("sample_words"),
                "advice": v.get("advice"), "modified": v.get("modified"),
                "modified_latest": v.get("modified_latest")}
        listed = {x["station"]: x for x in v["listed"]} if kind == "exceed" else {}
        if kind == "all_fit":
            ends, how = set(open_runs), "explicit"
        elif kind == "fit_list":
            ends, how = {x["station"] for x in v["listed"]} & set(open_runs), "explicit"
        elif v.get("unknown") or v.get("incomplete"):
            # an incomplete list (a row no station is matched to, a short row, a table cut off): the unread part may be
            # any beach, so none is ended (Astra verify P1-2)
            ends, how = set(), None
        else:
            ends, how = set(open_runs) - set(listed), "omission"
        if i and how:
            how = "revision" if how == "omission" else how
        for st in sorted(ends - set(listed)):
            run = open_runs.pop(st)
            run["end"] = {**step, "how": how}
        for st, x in listed.items():
            if st in open_runs:
                open_runs[st]["notices"].append((step, x))
            else:
                open_runs[st] = {"station": st, "notices": [(step, x)], "end": None}
                runs.append(open_runs[st])
        for x in v.get("unknown") or [] if kind == "exceed" else []:
            runs.append({"station": None, "notices": [(step, x)], "end": None, "unknown": True})
    newest_listing = newest if newest and not newest_unread else None
    out = [_record(r, at, newest_listing, confirmed or {}) for r in runs]
    seen: dict[str, int] = {}
    for r in out:      # two withheld unmatched rows of one notice would share an id: the second gets a suffix
        n = seen[r["event_id"]] = seen.get(r["event_id"], 0) + 1
        if n > 1:
            r["source_record_id"] += f"-{n}"
            r["event_id"] += f"-{n}"
    unread = [n for n in ns if _versions(n)[-1].get("kind") == "unread"]
    blocking = [n["id"] for n in unread if first_readable and n["published"] > first_readable]
    if newest_unread and newest[2] not in blocking:
        blocking.append(newest[2])
    # the newest readable notice read incompletely (an unmatched or short row, a table cut off): the records read are
    # kept, nothing is ended by it, and the feed is not healthy until a complete notice is read (Astra verify P1-2)
    newest_read = readable_steps[-1] if readable_steps else None
    incomplete_blocking = ([newest_read[2]] if newest_read and newest_read[5].get("kind") in ("exceed", "fit_list")
                           and (newest_read[5].get("unknown") or newest_read[5].get("incomplete")) else [])
    meta = {"notices": len(ns), "by_kind": {k: sum(1 for n in ns if _versions(n)[-1].get("kind") == k)
                                             for k in ("exceed", "all_fit", "fit_list", "unread")},
            "unread_notices": [n["id"] for n in unread],
            "unread_blocking": blocking,
            "unread_before_first_readable": [n["id"] for n in unread if n["id"] not in blocking],
            "incomplete_blocking": incomplete_blocking,
            "late_revisions": late,
            "revised_notices": sorted(n["id"] for n in ns if len(_versions(n)) > 1),
            "newest_notice": readable_steps[-1][1] if readable_steps else None,
            "station_notes": sorted({x["note"] for n in ns for v in _versions(n) for x in v["listed"] if x.get("note")}),
            "unplaced_rows": sorted({x.get("note") or "" for n in ns for v in _versions(n) for x in v["unknown"]})}
    return out, meta


def _record(run: dict, at: str, newest, confirmed: dict) -> dict:
    first, x0 = run["notices"][0]
    last, _ = run["notices"][-1]
    st = run["station"]
    end = run["end"]
    unknown = run.get("unknown")
    info = STATIONS.get(st) if st else None
    name, town = (info[0], info[1]) if info else (x0["name"], x0["municipio"])
    rid_key = st or "unknown-" + (norm(x0["code"]) if STATION.match(x0["code"] or "") else
                                  hashlib.sha1(norm(x0["name"] + "|" + x0["municipio"]).encode()).hexdigest()[:10])
    rid = f"{rid_key}:{first['id']}" + (f"r{first['revision']}" if first["revision"] else "")
    raw = {
        "station": st, "listed_as": sorted({x["code"] for _, x in run["notices"]}),
        "names_as_listed": sorted({x["name"] for _, x in run["notices"]}),
        "municipio": town, "time_zone": TIME_ZONE,
        "notices": [{"id": n["id"], "published": n["published"], "sampled": n["sampled"],
                     "sample_dates": n["sample_words"], "link": n["link"],
                     **({"revised_at": n["time"]} if n["revision"] else {})} for n, _ in run["notices"]],
        "sample_dates": first["sample_words"],
        "start_basis": ("the publication of DRNA's notice that first listed the beach (its date_gmt); the sampling "
                        "date is kept apart in sampled_at") if not first["revision"] else
                       (f"DRNA's revision of its notice published {first['published']} (post {first['id']}), dated "
                        f"{first['time']} (its modified_gmt), added the beach; the original notice did not list it"),
        "bav_rule": "Beach Action Value for enterococci, 70 colonies per 100 mL (DRNA's notice)",
        # a marker at the station only: never placed on a water by its point or a registry (a river mouth near a
        # beach is not the beach), so no water is coloured for it (status.named_water_only)
        "_placement": "named_water_only",
    }
    notes = sorted({x["note"] for _, x in run["notices"] if x.get("note")})
    if notes:
        raw["station_note"] = "; ".join(notes)
    if info:
        raw["point_basis"] = POINT_BASIS.format(info[2])
        raw["point_url"] = WQP.format(info[2])
        raw["station_table"] = TABLE_URL
    else:
        raw["place_unknown"] = ("the row's station could not be matched to DRNA's station table, so its place on the "
                                "map is not known: " + (x0.get("note") or "no station"))
    status = "advisory_active"
    ended_at = None
    if end is not None:
        status, ended_at = "advisory_lifted", end["time"]
        raw["ended_by_notice"] = end["id"]
        raw["end_url"] = end["link"]
        if end["how"] == "explicit":
            raw["ended_at_precision"] = "minute"
            raw["end_basis"] = (f"DRNA's notice published {end['time']} (post {end['id']}) "
                                + ("says the program's beaches are fit for bathers" if end["kind"] == "all_fit" else
                                   "lists the beach among those fit for bathers"))
        else:
            # an omission is not a lift (Astra P1-1): the end is the first notice seen without the beach, with poll
            # precision, and the time after the last notice that listed it is not confirmed (status: the 14-day horizon)
            raw["ended_at_precision"] = "poll"
            raw["_last_seen_in_source"] = last["time"]
            raw["end_basis"] = ((f"DRNA's notice published {end['time']} (post {end['id']}) no longer lists the beach"
                                 if end["how"] == "omission" else
                                 f"DRNA's revision dated {end['time']} of its notice published {end['published']} "
                                 f"(post {end['id']}) no longer lists the beach")
                                + "; DRNA states no lift, so this is the first notice seen without it, not a lift time")
    elif newest is not None and last["id"] == newest[2] and last["revision"] == newest[3]:
        raw["_last_seen_in_source"] = at
    else:
        # the newest notice could not be read, or does not reach this run: the confirmation stays where it was
        prev = confirmed.get(f"{SOURCE_ID}:{rid}")
        raw["_last_seen_in_source"] = prev if prev and prev >= last["time"] else last["time"]
    advice = first.get("advice") or "no son aptas para bañistas"
    return event(
        source_id=SOURCE_ID, source_record_id=rid,
        event_type="beach_advisory", status=status,
        waterbody_text=f"{name} ({town})" if town else name,
        lat=info[3] if info else None, lon=info[4] if info else None,
        coord_source="station_point" if info else None,
        started_at=first["time"], ended_at=ended_at, time_precision="minute", sampled_at=first["sampled"],
        published_at=first["time"],
        source_updated_at=last.get("modified_latest") or last.get("modified") or last["published"],
        material="enterococci bacteria above the Beach Action Value",
        authority=AUTHORITY,
        advice_text=f"DRNA: la(s) siguiente(s) playa(s) “{advice}”",
        advice_window_basis="in effect until a later DRNA notice no longer lists the beach",
        source_url=first.get("link"), raw=raw,
        parse_error=(f"row {x0['code']!r} ({x0['name']}) is not matched to DRNA's station table: no point "
                     f"({x0.get('note') or 'no station'})" if unknown else None),
    )


def fetch(all_pages: bool) -> tuple[list[dict], str | None]:
    posts, page, pages = [], 1, 1
    while page <= pages:
        r = requests.get(URL, params={**PARAMS, "page": str(page)}, headers=HEADERS, timeout=120)
        r.raise_for_status()
        body = r.json()
        if not isinstance(body, list):
            raise ValueError(f"page {page} is not a list of posts")
        posts += body
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
    known = {n["id"]: sanitize_notice(n) for n in state.get("notices", []) if isinstance(n, dict) and n.get("id")}
    try:
        if files:
            posts = [p for f in files for p in json.loads(f.read_text())]
        else:
            posts, _ = fetch("--all" in argv or not known)
    except (requests.RequestException, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")
        print(f"{SOURCE_ID}: {type(e).__name__}", file=sys.stderr)
        return 1
    parsed = [parse_notice(p) for p in posts if isinstance(p, dict) and p.get("id") and p.get("date_gmt")]
    # a post that cannot be placed in time or identified is never skipped silently: listed, and the feed not healthy
    # (Astra verify P1-2); its id only, nothing else of it is saved
    malformed = [{"id": p.get("id") if isinstance(p, dict) and isinstance(p.get("id"), int) else None,
                  "why": "not a post" if not isinstance(p, dict) else "no id" if not p.get("id") else "no date_gmt"}
                 for p in posts if not (isinstance(p, dict) and p.get("id") and p.get("date_gmt"))]
    if not parsed:
        write_events(SOURCE_ID, [], ok=False, error="no notices in the response")
        return 1
    for n in parsed:
        known[n["id"]] = merge_notice(known.get(n["id"]), n)
    notices = sorted(known.values(), key=lambda n: (n.get("published") or "", n["id"]))
    recs, meta = records(notices, at, state.get("confirmed") or {})
    meta.update(registry_ids=[SOURCE_ID], url=URL, station_table=TABLE_URL,
                cadence="weekly notices; read with the refresh", malformed_posts=malformed)
    if not files:
        save_raw(SOURCE_ID, json.dumps(parsed, ensure_ascii=False), "json")
        write_json(STATE_PATH, {"source_id": SOURCE_ID, "updated": at, "notices": notices,
                                "confirmed": {r["event_id"]: r["raw"]["_last_seen_in_source"] for r in recs
                                              if r["status"] == "advisory_active"
                                              and r["raw"].get("_last_seen_in_source")}})
    if meta["unread_blocking"] or meta["incomplete_blocking"] or malformed:
        # a notice that cannot be read after the first readable one (the newest above all), a newest notice read
        # incompletely, or a post with no id or date: the records read are kept and written, the confirmations stay
        # where they were, and the feed is not healthy until it is read (P1-3; Astra verify P1-2)
        why = "; ".join(x for x in (
            f"notices not read: {meta['unread_blocking']}" if meta["unread_blocking"] else "",
            f"newest notice read incompletely: {meta['incomplete_blocking']}" if meta["incomplete_blocking"] else "",
            f"posts with no id or date: {len(malformed)}" if malformed else "") if x)
        path = write_events(SOURCE_ID, recs, ok=False, partial=True, meta=meta, error=why)
        print(f"{SOURCE_ID}: {len(recs)} records; {why}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} records from {len(notices)} notices "
          f"({sum(r['status'] == 'advisory_active' for r in recs)} in effect) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
