"""Puerto Rico's water names with and without accents, in Spanish and English (2026-11-15): status.norm_name_in and
name_forms_in, the resolver, names_disagree, the NHD builder's name_score, SQL names and slugs, the OSM fallback's
regex, and the ties step. Every other state reads its names exactly as before (the invariance tests below run over
every accented name on file). Run from pipeline/: python -m pytest tests/test_pr_accent_names.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from build import status as S  # noqa: E402
from ingest import outfall_waters as O  # noqa: E402
from ingest import waters_extra as WX  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "data"


def _state_of(o: dict) -> str:
    return str(o.get("state") or str(o.get("npdes_permit") or "")[:2]).upper()


def _names_on_file() -> list[tuple[str, str]]:
    """(state, text) for every water record name and alias and every registry receiving-water text on file."""
    out = []
    for p in sorted(DATA.glob("waters-*.json")) + sorted(DATA.glob("outfalls-*.json")):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        rows = (d.get("waters") or d.get("outfalls") or []) if isinstance(d, dict) else d
        for r in rows:
            if not isinstance(r, dict):
                continue
            st = _state_of(r)
            for k in ("name", "receiving_water_echo", "reach_gnis_name", "water_name", "receiving_water"):
                if isinstance(r.get(k), str) and r[k].strip():
                    out.append((st, r[k]))
            out += [(st, a) for a in r.get("aliases") or [] if isinstance(a, str)]
    return out


NAMES = _names_on_file()
ACCENTED = sorted({(st, t) for st, t in NAMES if not t.isascii() and st != "PR"})
# a sample of plain names as well, from every state
PLAIN = sorted({(st, t) for st, t in NAMES if t.isascii() and st != "PR"})[::97]


# ------------------------------------------------------------------ every other state as before

def test_other_states_hold_accented_names():
    """The invariance below is tested on real names: AZ, CA, NM, TX, VT, HI and others hold accented ones."""
    states = {st for st, _ in ACCENTED}
    assert {"AZ", "CA", "NM", "TX", "VT", "HI"} <= states


@pytest.mark.parametrize("st,text", ACCENTED + PLAIN[:400])
def test_other_states_normalise_byte_for_byte(st, text):
    assert S.state_text(text, st) is text
    assert S.state_split_text(text, st) is text
    assert S.norm_name_in(text, st) == S.norm_name(text)
    assert S.name_forms_in(text, st) == [S.norm_name(text)]
    assert S.spanish_spellings(text, st) == []
    assert N.slugify(text, st) == WX.slugify(text)
    ws = N.words(text)
    for other in ("Río Grande", "Rio Grande", "Peña Blanca Lake", "Lac Memphrémagog", text):
        assert N.name_score(ws, other, st) == N.name_score(ws, other)
        assert S.names_disagree(text, other, st) == S.names_disagree(text, other)


def test_known_accented_slugs_unchanged():
    assert N.slugify("Cañada de Buey", "NM") == "ca-ada-de-buey"          # NM's live slug ca-ada-de-buey-nm
    assert N.slugify("Cañada de Buey") == "ca-ada-de-buey"
    assert N.slugify("Río Cibuco", "PR") == "rio-cibuco"
    assert N.slugify("Bayamón", "PR") == "bayamon"


def test_other_states_resolver_index_unchanged():
    """The resolver's index for every accented record outside Puerto Rico is the one it was without the fold."""
    waters = {}
    for i, (st, t) in enumerate(ACCENTED + PLAIN[:300]):
        waters[f"w{i}"] = {"slug": f"w{i}", "name": t, "state": st, "aliases": [t.upper(), S.fold_accents(t)]}
    on = S.Resolver(waters, [], placement_rules={})
    keep = S.ACCENT_FOLD_STATES
    S.ACCENT_FOLD_STATES = frozenset()
    try:
        off = S.Resolver(waters, [], placement_rules={})
    finally:
        S.ACCENT_FOLD_STATES = keep
    assert dict(on.names) == dict(off.names)
    assert dict(on.stems) == dict(off.stems)
    assert dict(on.exact) == dict(off.exact)
    for st, t in ACCENTED[:200]:
        assert on.by_name(S.fold_accents(t), st, None, None, {}) == off.by_name(S.fold_accents(t), st, None, None, {})


def _old_where(names):
    return "UPPER(gnis_name) IN (" + ",".join(f"'{n}'" for n in names) + ")"


@pytest.mark.parametrize("st", ["NM", "TX", "AZ", "CA", "VT", "HI", None])
def test_other_states_queries_unchanged(st):
    names = ["RIO GRANDE", "PEÑA BLANCA LAKE", "O''BRIEN CREEK"]
    assert N.name_queries(names, st) == [_old_where(names)]
    t = N.Target(state=st or "NM", name="Peña Blanca Lake", report_name=True, define_by="reach")
    t["words"] = N.words(S.state_text(t["name"], t["state"]))
    t2 = N.Target(state="XX", name="Peña Blanca Lake", report_name=True, define_by="reach")
    t2["words"] = N.words(t2["name"])
    assert N.sql_names(t) == N.sql_names(t2)                  # as for a state with no fold
    assert "PEÑA BLANCA LAKE" in N.sql_names(t)
    assert N.gnis_in("Peña Blanca Lake", {"PENA BLANCA LAKE"}, st) is False


# frozen from origin/main (2026-11-15) before this branch: every other state's OSM regex and queries, byte for byte
BASE_REGEX = '^(Peña Blanca Lake|St\\. John\'s River \\(x\\)|A\\|B\\.c\\*|Say \\"Hi\\")$'
BASE_STATE_QUERY = (
    '[out:json][timeout:90];\n(\n'
    '  way["waterway"~"^(river|stream|canal)$"]["name"~"^(Peña Blanca Lake|O\'Brien Creek)$",i](31.4,-111.1,31.5,-111.0);\n'
    '  relation["waterway"~"^(river|stream|canal)$"]["name"~"^(Peña Blanca Lake|O\'Brien Creek)$",i](31.4,-111.1,31.5,-111.0);\n'
    '  way["natural"~"^(water|bay|strait)$"]["name"~"^(Peña Blanca Lake|O\'Brien Creek)$",i](31.4,-111.1,31.5,-111.0);\n'
    '  relation["natural"~"^(water|bay|strait)$"]["name"~"^(Peña Blanca Lake|O\'Brien Creek)$",i](31.4,-111.1,31.5,-111.0);\n'
    ');\nout tags geom;\n')
BASE_BUILD_QUERY_HEAD = ('[out:json][timeout:300];\n(\n  way["waterway"]["name"~"^(Peña Blanca Lake|Pena Blanca Lake)$",i]'
                         '(31.4,-111.1,31.5,-111.0);\n')


def test_other_states_osm_unchanged():
    assert WX.name_regex(["Peña Blanca Lake", "St. John's River (x)", "A|B.c*", 'Say "Hi"']) == BASE_REGEX
    box = (31.4, -111.1, 31.5, -111.0)
    for st in (None, "AZ", "NM", "TX", "HI"):
        assert N.state_query(["Peña Blanca Lake", "O'Brien Creek"], box, st) == BASE_STATE_QUERY
    q = WX.build_query({"name": "Peña Blanca Lake", "osm_names": ["Pena Blanca Lake"], "box": box})
    assert q.startswith(BASE_BUILD_QUERY_HEAD) and "[aáAÁ]" not in q
    spec = {"name": "Peña Blanca Lake", "osm_names": [], "box": (0, 0, 10, 10)}
    resp = {"elements": [{"type": "way", "id": 1, "tags": {"name": "Pena Blanca Lake"},
                          "bounds": {"minlat": 1, "minlon": 1, "maxlat": 2, "maxlon": 2}}]}
    assert N.for_spec(resp, spec)["elements"] == []           # no fold outside Puerto Rico


# ------------------------------------------------------------------ Puerto Rico

def test_fold_accents():
    assert S.fold_accents("Río Grande de Loíza") == "Rio Grande de Loiza"
    assert S.fold_accents("Caño Martín Peña") == "Cano Martin Pena"
    assert S.fold_accents("Mayagüez") == "Mayaguez"
    assert S.fold_accents("Keʻanae") == "Keʻanae"            # no base letter: left as it is
    assert S.norm_name("Río Unibón") == "river o unib n"        # norm_name itself unchanged
    assert S.norm_name_in("Río Unibón", "PR") == "rio unibon"
    assert S.norm_name_in("Río Unibón", "pr") == "rio unibon"


@pytest.mark.parametrize("text,form", [
    ("CIBUCO RIVER", "rio cibuco"),
    ("Río Cibuco", "cibuco river"),
    ("LA PLATA RIVER", "rio la plata"),
    ("Río de la Plata", "de la plata river"),
    ("RIO GRANDE DE LOIZA RIVER", "rio grande de loiza"),
    ("Bahía de San Juan", "de san juan bay"),
    ("BAHIA SAN JUAN", "san juan bay"),
    ("Martin Pena Channel", "cano martin pena"),
    ("OCEANO ATLANTICO", "atlantic ocean"),
    ("Caribe Ocean", "caribbean sea"),
    ("QB AGUAS CLARAS", "quebrada aguas claras"),
    ("RIO GRANDE MANATI", "rio grande de manati"),
    ("Manatí River", "rio grande de manati"),
    ("Jayuya River", "rio grande de jayuya"),
    ("RIO LOISA", "rio grande de loiza"),
    ("RIO GUARDIANA", "rio guadiana"),
])
def test_pr_forms(text, form):
    assert form in S.name_forms_in(text, "PR")


@pytest.mark.parametrize("text,not_form", [
    ("RIO LA PLATA", "rio de la plata"), ("Río de la Plata", "rio la plata"), ("Río de la Plata", "la plata river"),
    ("Bahía de San Juan", "bahia san juan"), ("Bahía de San Juan", "san juan bay"),
    ("Caño de Martín Peña", "cano martin pena"), ("Caño de Martín Peña", "martin pena channel"),
    ("Río de Apeadero", "rio apeadero"), ("Río Grande de Arecibo", "rio grande arecibo"),
])
def test_pr_de_is_part_of_the_name(text, not_form):
    """'Río La Plata' and 'Río de la Plata' are different names: only the kind word is translated."""
    assert not_form not in S.name_forms_in(text, "PR")
    assert not any(" DE " in x for x in S.spanish_spellings("RIO LA PLATA", "PR"))


# the whole approved table (review 2026-11-15, item 6): (as filed, the water's name) and the evidence in the report
APPROVED_PAIRS = {
    ("oceano atlantico", "atlantic ocean"), ("mar caribe", "caribbean sea"), ("caribe ocean", "caribbean sea"),
    ("jayuya river", "rio grande de jayuya"), ("manati river", "rio grande de manati"),
    ("rio grande manati", "rio grande de manati"), ("rio loisa", "rio grande de loiza"), ("rio guardiana", "rio guadiana"),
}


def test_pr_name_pairs_pinned():
    assert set(S.STATE_NAME_PAIRS["PR"]) == APPROVED_PAIRS and len(S.STATE_NAME_PAIRS["PR"]) == len(APPROVED_PAIRS)
    assert set(S.STATE_NAME_PAIRS) == {"PR"}


def test_pr_two_waters_are_not_one_name():
    assert S.spanish_forms("quebrada and rio chico") == []
    assert S.state_split_text("QUEBRADA Y RIO CHICO", "PR") == "Creek and RIO CHICO"
    assert S.state_split_text("Quebrada y el Río Apeadero", "PR") == "Creek and Río Apeadero"
    assert N.report_name_parts(S.state_split_text("QUEBRADA Y RIO CHICO", "PR"))[0] == ["RIO CHICO"]
    assert N.report_name_parts(S.state_split_text("CAÑO (UNKNOWN THE NAME)", "PR"))[0] == []
    assert S.state_split_text("Río Grande", "PR") == "Río Grande"          # a name after the water word: kept


@pytest.mark.parametrize("text", ["OCEANO ATLANTICO", "Oceano Atlántico", "MAR CARIBE", "Mar Caribe", "CARIBBEAN SEA"])
def test_pr_spanish_open_sea(text):
    assert N.report_name_parts(text, "PR")[1] == N.OPEN_SEA
    assert N.report_name_parts("ATLANTIC OCEAN", "PR")[1] == N.OPEN_SEA


def test_open_sea_elsewhere_unchanged():
    for st in (None, "FL", "TX"):
        assert N.report_name_parts("MAR CARIBE", st) == N.report_name_parts("MAR CARIBE")
        assert N.report_name_parts("CARIBBEAN SEA", st) == N.report_name_parts("CARIBBEAN SEA")


# (text as filed, the NHDPlus V2.1 GNIS name it must find): the PR registry's and reports' texts, dry run 2026-11-15
PR_GNIS = [
    ("RIO CIBUCO", "Río Cibuco"), ("CIBUCO RIVER", "Río Cibuco"), ("Cibuco River", "Río Cibuco"),
    ("UNIBON RIVER", "Río Unibón"), ("Río Unibón", "Río Unibón"),
    ("RIO GRANDE DE LOIZA RIVER", "Río Grande De Loiza"), ("RIO LOISA", "Río Grande De Loiza"),
    ("BAIROA RIVER", "Río Bairoa"), ("MOROVIS RIVER", "Río Morovis"), ("GURABO RIVER", "Río Gurabo"),
    ("OROCOVIS RIVER", "Río Orocovis"), ("GUADIANA RIVER", "Río Guadiana"), ("RIO GUARDIANA", "Río Guadiana"),
    ("Jayuya River", "Río Grande de Jayuya"), ("RIO GRANDE DE JAYUYA", "Río Grande de Jayuya"),
    ("Manatí River", "Río Grande de Manati"), ("RIO GRANDE MANATI", "Río Grande de Manati"),
    ("RIO GUAMANI", "Río Guamaní"), ("Cidra River", "Río Cidra"), ("ARENAS RIVER", "Río Arenas"),
    ("Caño de Martín Peña", "Caño de Martín Peña"), ("Río Coamo", "Río Coamo"), ("RIO CHICO", "Río Chico"),
]


@pytest.mark.parametrize("text,gnis", PR_GNIS)
def test_pr_builder_name_score(text, gnis):
    ws = N.words(S.state_text(text, "PR"))
    assert N.name_score(ws, gnis, "PR") == 1.0
    assert N.report_score(ws, gnis, "PR") == 1.0


@pytest.mark.parametrize("text,gnis", [
    ("RIO CIBUCO", "Río Unibón"), ("CIBUCO RIVER", "Río Coamo"), ("RIO GRANDE", "Río Grande De Loiza"),
    ("RIO GUAJATACA", "Río de Barranquitas"), ("RIO LOS NEGROS", "Río Corozal"), ("TURABO PARK", "Río Turabo"),
    ("RIO CIBUCO", "Río Cibaco"), ("RIO CIBUCO", "Río Cibucos"),          # no fuzzy spelling in Puerto Rico
    ("RIO LA PLATA", "Río de la Plata"), ("LA PLATA RIVER", "Río de la Plata"), ("RIO APEADERO", "Río de Apeadero"),
    ("Martin Pena Channel", "Caño de Martín Peña"), ("RIO GRANDE DE LOIZA", "Río Grande"),
])
def test_pr_builder_other_waters_still_differ(text, gnis):
    ws = N.words(S.state_text(text, "PR"))
    assert N.name_score(ws, gnis, "PR") == 0.0
    assert N.report_score(ws, gnis, "PR") == 0.0


def test_pr_sql_names_exact_accent_variants():
    t = N.Target(state="PR", name="RIO UNIBON", report_name=True)
    t["words"] = N.words(S.state_text(t["name"], "PR"))
    names = N.sql_names(t)
    assert "RIO UNIBON" in names and not any(" DE " in n for n in names)
    wheres = N.name_queries(names, "PR")
    joined = " ".join(wheres)
    assert "LIKE" not in joined and "'RÍO UNIBÓN'" in joined and "'RIO UNIBON'" in joined
    assert all(w.startswith("UPPER(gnis_name) IN (") for w in wheres)
    w = " ".join(N.name_queries(["RIO A%_"], "PR"))
    assert "LIKE" not in w and "'RIO A%_'" in w                         # % and _ are letters inside an IN list
    assert all(len(v) == len("RIO UNIBON") for v in N.accent_variants("RIO UNIBON"))
    assert "'O''BRIEN CREEK'" in N.name_queries(["O''BRIEN CREEK"], "PR")[0]
    assert N.gnis_in("Río Unibón", {"RIO UNIBON"}, "PR")
    assert not N.gnis_in("Río Cibaco", {"RIO CIBUCO"}, "PR")
    assert not N.gnis_in("Río Unibón", {"RIO UNIBON"}, "NM")


@pytest.mark.parametrize("st", ["NM", "TX", None])
def test_other_states_name_queries_unchanged(st):
    names = ["RIO GRANDE", "PEÑA BLANCA LAKE", "O''BRIEN CREEK"]
    assert N.name_queries(names, st) == [_old_where(names)]


def test_pr_name_only_never_takes_a_fuzzy_feature(monkeypatch):
    """A feature whose folded name is not one of the spellings asked is never chosen ('Río Cibaco' for RIO CIBUCO)."""
    from shapely.geometry import LineString

    class States:
        shapes = {"PR": LineString([(-67, 18), (-65, 18.5)]).buffer(1)}

    class Towns:
        def outlines(self, *a):
            return []

    class Fake:
        states, towns = States(), Towns()

        def by_name(self, layer, state, names):
            if layer != 2:
                return []
            return [{"gnis_id": "1", "gnis_name": "Río Cibaco", "comid": 1, "_geom": LineString([(-66, 18.2), (-66.1, 18.3)])}]
    t = N.Target(state="PR", name="RIO CIBUCO", towns={}, points={})
    t["words"] = N.words(S.state_text(t["name"], "PR"))
    choice, why = N.resolve_name_only(Fake(), t)
    assert choice is None


def test_pr_osm_regex_and_filter():
    rx = WX.name_regex(["Bahia de San Juan"], True)
    import re
    assert re.match(rx, "Bahía de San Juan") and re.match(rx, "BAHIA DE SAN JUAN", re.I)   # Overpass asks with ,i
    assert not re.match(rx, "Bahia del San Juan", re.I) and "." not in rx.replace("\\.", "")
    assert "[aáAÁ]" in N.state_query(["Bahia"], (1, 2, 3, 4), "PR")
    spec = {"name": "Bahía de San Juan", "state": "PR", "accents_free": True, "box": (18.0, -67.0, 19.0, -65.0),
            "osm_names": sorted(S.spanish_spellings("Bahía de San Juan", "PR"))}
    resp = {"elements": [{"type": "relation", "id": 7, "tags": {"name": "Bahia de San Juan"},
                          "bounds": {"minlat": 18.4, "minlon": -66.2, "maxlat": 18.5, "maxlon": -66.0}}]}
    assert len(N.for_spec(resp, spec)["elements"]) == 1


def _pr_waters(names=None):
    names = names or ["Río Cibuco", "Río Unibón", "Río Grande De Loiza", "Río de la Plata", "Caño de Martín Peña",
                      "Bahía de San Juan", "Atlantic Ocean", "Río Grande de Manati", "Río Grande de Jayuya", "Río Grande",
                      "Río Chico", "Río de Apeadero"]
    return {N.slugify(n, "PR") + "-pr": {"slug": N.slugify(n, "PR") + "-pr", "name": n, "state": "PR", "aliases": [],
                                         "kind": "river"} for n in names}


@pytest.mark.parametrize("text,name", [
    ("RIO CIBUCO", "Río Cibuco"), ("CIBUCO RIVER", "Río Cibuco"), ("Cibuco", "Río Cibuco"),
    ("UNIBON RIVER", "Río Unibón"), ("RIO UNIBON", "Río Unibón"), ("Río Unibón", "Río Unibón"),
    ("RIO GRANDE DE LOIZA RIVER", "Río Grande De Loiza"), ("Río Grande de Loíza", "Río Grande De Loiza"),
    ("Río de la Plata", "Río de la Plata"), ("Caño de Martín Peña", "Caño de Martín Peña"),
    ("Bahía de San Juan", "Bahía de San Juan"),
    ("OCEANO ATLANTICO", "Atlantic Ocean"), ("Oceano Atlantico", "Atlantic Ocean"),
    ("RIO GRANDE MANATI", "Río Grande de Manati"), ("Manatí River", "Río Grande de Manati"),
    ("Jayuya River", "Río Grande de Jayuya"), ("QUEBRADA Y RIO CHICO", "Río Chico"), ("RIO GRANDE", "Río Grande"),
])
def test_pr_resolver_places_each_spelling(text, name):
    r = S.Resolver(_pr_waters(), [], placement_rules={})
    slugs, _, _ = r.by_name(text, "PR", None, None, {})
    assert [r.waters[s]["name"] for s in slugs] == [name]


@pytest.mark.parametrize("text", ["LA PLATA RIVER", "RIO LA PLATA", "Martin Pena Channel", "Caño Martín Peña",
                                  "San Juan Bay", "BAHIA SAN JUAN", "RIO APEADERO", "discharge to the Rio Cibuco",
                                  "Rio Cibuco at Vega Baja"])
def test_pr_resolver_no_partial_or_conflated_name(text):
    r = S.Resolver(_pr_waters(), [], placement_rules={})
    assert r.by_name(text, "PR", None, None, {})[0] == []


@pytest.mark.parametrize("text", ["RIO GRANDE DE LOIZA", "RIO GRANDE DE LOIZA RIVER", "Grande", "GRANDE", "Río", "RIO",
                                  "Grande River", "RIO GRANDE DE MANATI"])
def test_pr_singleton_rio_grande_takes_no_longer_or_generic_name(text):
    r = S.Resolver(_pr_waters(["Río Grande"]), [], placement_rules={})
    assert r.by_name(text, "PR", None, None, {})[0] == []


def test_pr_singleton_rio_grande_row_water():
    r = S.Resolver(_pr_waters(["Río Grande"]), [], placement_rules={})
    for text in ("RIO GRANDE DE LOIZA", "Grande"):
        assert r.row_water({"state": "PR", "npdes_permit": "PR0000001", "outfall": "001",
                            "receiving_water_echo": text})[0] is None


def test_row_cache_keys_state_and_text():
    """A PR row's answer never reaches the same row read as another state's, nor a row with another text."""
    r = S.Resolver(_pr_waters(["Río Cibuco"]), [], placement_rules={})
    row = {"receiving_water_echo": "CIBUCO RIVER"}
    assert r.row_water({**row, "state": "PR"})[0] == "rio-cibuco-pr"
    assert r.row_water({**row, "state": "NM"})[0] is None
    assert r.row_water({"state": "PR", "receiving_water_echo": "RIO UNIBON"})[0] is None
    fresh = S.Resolver(_pr_waters(["Río Cibuco"]), [], placement_rules={})
    assert fresh.row_water({**row, "state": "NM"})[0] is None


def test_pr_names_disagree():
    assert S.names_disagree("UNIBON RIVER", "Río Unibón", "PR") is None
    assert S.names_disagree("OCEANO ATLANTICO", "Atlantic Ocean", "PR") is None
    assert S.names_disagree("RIO CIBUCO", "Río Unibón", "PR") == "no name word in common"
    assert S.names_disagree("UNIBON RIVER", "Río Unibón") == "no name word in common"     # unscoped: as before


def test_pr_ties_same_water():
    w = {"name": "Río Cibuco", "aliases": [], "state": "PR"}
    assert O.same_water({"state": "PR", "receiving_water_echo": "CIBUCO RIVER"}, w)
    assert O.same_water({"state": "PR", "receiving_water_echo": "", "reach_gnis_name": "Río Cibuco"}, w)
    assert not O.same_water({"state": "NM", "receiving_water_echo": "CIBUCO RIVER"}, {**w, "state": "NM"})
    lp = {"name": "Río de la Plata", "aliases": [], "state": "PR"}
    assert not O.same_water({"state": "PR", "receiving_water_echo": "RIO LA PLATA"}, lp)


def test_pr_holds_name_and_existing_forms():
    rec = {"name": "Río Cibuco", "aliases": [], "state": "PR"}
    assert N.holds_name(rec, "CIBUCO RIVER")
    assert N.holds_name(rec, "RIO CIBUCO")
    assert not N.holds_name({**rec, "name": "Río de la Plata"}, "RIO LA PLATA")
    existing = {"rio-cibuco-pr": {**rec, "slug": "rio-cibuco-pr"}}
    assert N.same_named_existing(existing, "PR", "Cibuco River") == ["rio-cibuco-pr"]


def test_pr_las_is_the_spanish_article():
    """'LAS ARENAS CREEK' (a PRASA report) is a creek; LAS with no word after it stays a land-application system, and
    every other state reads 'LAS' as before."""
    assert N.report_name_parts("LAS ARENAS CREEK", "PR")[0] == ["LAS ARENAS CREEK"]
    assert N.national_parts("PLANT LAS", "PR")[1] == "a land-application system, not a surface water"
    for st in (None, "GA", "NM", "TX"):
        assert N.report_name_parts("LAS ARENAS CREEK", st)[1] == "a land-application system, not a surface water"
        assert N.national_parts("CHATHAM COUNTY LAS", st) == N.national_parts("CHATHAM COUNTY LAS")
