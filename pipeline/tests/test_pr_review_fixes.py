"""Puerto Rico: the fixes of Astra's review of state/pr (2026-11-15), each on invented data. DRNA's beach notices
(ingest/pr_drna_beaches.py) are invented posts in DRNA's form; no real notice is changed."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

import common
from build import status as S
from ingest import pr_drna_beaches as P

AT = "2026-11-14T12:00:00Z"
INTRO = ("A base de los resultados de los muestreos del 2 y 3 de noviembre de 2026, realizados en las playas que son "
         "parte del Programa de Playas, la(s) siguiente(s) playa(s) no son aptas para bañistas por exceder el "
         "“Beach Action Value” (BAV) para el parámetro de Enterococos (70 colonias/100 mL):")
FIT = ("A base de los resultados de los muestreos del 9 de noviembre de 2026, las playas que son parte del Programa "
       "de Playas se encuentran aptas para bañistas.")


def post(pid, when, rows=(), intro=INTRO, modified=None):
    table = "".join(f"<tr><td>{c}</td><td>{n}</td><td>{m}</td></tr>" for c, n, m in rows)
    html = f"<p>{intro}</p>" + (f"<table><tr><th>Estación</th><th>Nombre</th><th>Municipio</th></tr>{table}</table>"
                                if rows else "")
    return {"id": pid, "date_gmt": when, "modified_gmt": modified or when,
            "link": f"https://www.drna.pr.gov/notificacion-{pid}/", "content": {"rendered": html}}


TROP = ("RW-31", "Tropical Beach", "Naguabo")
SANTA = ("RW-10", "Playa Santa", "Guánica")
AZUL = ("RW-32", "Playa Azul", "Luquillo")


def recs_of(posts, at=AT, confirmed=None):
    ns = {}
    for p in posts:
        ns[p["id"]] = P.merge_notice(ns.get(p["id"]), P.parse_notice(p))
    recs, meta = P.records(list(ns.values()), at, confirmed)
    return {r["source_record_id"]: r for r in recs}, meta


# ----------------------------------------------------------------- P1-1: an omission is not a lift

def test_omission_explicit_lift_incomplete_table_and_delayed_observation_differ():
    a = post(1, "2026-11-01T12:00:00", [TROP, SANTA])
    omit = post(2, "2026-11-08T12:00:00", [SANTA])
    fit = post(3, "2026-11-15T12:00:00", intro=FIT)
    recs, _ = recs_of([a, omit, fit])
    r_omit, r_fit = recs["RW-31:1"], recs["RW-10:1"]
    assert r_omit["ended_at"] == "2026-11-08T12:00:00Z" and r_omit["raw"]["ended_at_precision"] == "poll"
    assert r_omit["raw"]["_last_seen_in_source"] == "2026-11-01T12:00:00Z"
    assert r_omit["raw"]["end_url"] == "https://www.drna.pr.gov/notificacion-2/"
    assert r_fit["ended_at"] == "2026-11-15T12:00:00Z" and r_fit["raw"]["ended_at_precision"] == "minute"
    assert "fit for bathers" in r_fit["raw"]["end_basis"]
    # an incomplete list (a row no station is matched to) ends nothing: the unread row may be the beach
    inc = post(2, "2026-11-08T12:00:00", [SANTA, ("RW-77", "Playa Ejemplo", "Naguabo")])
    recs, _ = recs_of([a, inc])
    assert recs["RW-31:1"]["status"] == "advisory_active" and recs["RW-31:1"]["ended_at"] is None
    assert recs["RW-31:1"]["raw"]["_last_seen_in_source"] == "2026-11-01T12:00:00Z"   # not reconfirmed by it
    # a closing notice first read weeks after its publication gives the same end (the publication, not the poll)
    late_poll = "2027-01-20T12:00:00Z"
    assert recs_of([a, omit], at=late_poll)[0]["RW-31:1"]["ended_at"] == r_omit["ended_at"]


def test_an_omission_end_seen_months_later_never_colours_the_gap_red():
    a = post(1, "2026-06-01T12:00:00", [TROP])
    omit = post(2, "2026-09-15T12:00:00", [SANTA])          # DRNA posted nothing for 106 days
    r = recs_of([a, omit])[0]["RW-31:1"]
    from tests.test_status import TEST_RULES
    ivs = S.event_intervals(r, None, datetime(2026, 11, 1, tzinfo=timezone.utc), None, TEST_RULES)
    red_until = max(i["end"] for i in ivs if i["color"] == "red")
    assert red_until <= datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    # an explicit lift months later stays DRNA's own window (its words), not a poll
    fit = post(2, "2026-09-15T12:00:00", intro=FIT)
    r2 = recs_of([a, fit])[0]["RW-31:1"]
    ivs2 = S.event_intervals(r2, None, datetime(2026, 11, 1, tzinfo=timezone.utc), None, TEST_RULES)
    assert max(i["end"] for i in ivs2 if i["color"] == "red") == datetime(2026, 9, 15, 12, tzinfo=timezone.utc)


def test_another_sources_poll_ended_beach_keeps_its_colour(monkeypatch):
    a = post(1, "2026-06-01T12:00:00", [TROP])
    r = recs_of([a, post(2, "2026-09-15T12:00:00", [SANTA])])[0]["RW-31:1"]
    r = {**copy.deepcopy(r), "source_id": "xx-invented", "event_id": "xx-invented:1"}
    from tests.test_status import TEST_RULES
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    with_pr = S.event_intervals(r, None, now, None, TEST_RULES)
    # integrate/second-1: Nevada adds its own source (nv-state-parks-hab); the set is pinned whole, so any other
    # addition still fails here
    # Astra IA/ID review 2026-11-15 P2-3: Idaho adds its own source (id-deq-cyanohab-risk-table)
    assert S.POLL_END_HORIZON_SOURCES == {"de-dnrec-recreational-water", "sc-des-beach-monitoring", "sc-des-hab",
                                          "nv-state-parks-hab", "pr-drna-beach-notices", "id-deq-cyanohab-risk-table",
                                          "sc-des-freshwater-swim-advisories", "wi-dnr-beach-health",
                                          "nv-ose-hab-reports"}     # Nevada's State Epidemiology list (2026-11-16)
    monkeypatch.setattr(S, "POLL_END_HORIZON_SOURCES", S.POLL_END_HORIZON_SOURCES - {"pr-drna-beach-notices"})
    assert with_pr == S.event_intervals(r, None, now, None, TEST_RULES)


# ----------------------------------------------------------------- P1-2: a revised post keeps its history

def test_a_revised_post_keeps_the_first_beach_and_dates_the_added_one_at_the_revision():
    v1 = post(10, "2026-11-13T12:00:00", [TROP])
    v2 = post(10, "2026-11-13T12:00:00", [AZUL], modified="2026-11-20T15:00:00")
    recs, meta = recs_of([post(9, "2026-11-06T12:00:00", [SANTA]), v1, v2])
    first = recs["RW-31:10"]                       # the original beach is not erased
    assert first["started_at"] == "2026-11-13T12:00:00Z" and first["ended_at"] == "2026-11-20T15:00:00Z"
    assert first["raw"]["ended_at_precision"] == "poll" and "revision" in first["raw"]["end_basis"]
    added = recs["RW-32:10r1"]                     # the added beach starts at the revision, not on November 13
    assert added["started_at"] == "2026-11-20T15:00:00Z" and "revision" in added["raw"]["start_basis"]
    assert added["status"] == "advisory_active" and meta["revised_notices"] == [10]


def test_removing_the_first_notice_of_a_run_by_revision_keeps_the_run():
    a1 = post(1, "2026-11-01T12:00:00", [TROP])
    b = post(2, "2026-11-08T12:00:00", [TROP])
    a2 = post(1, "2026-11-01T12:00:00", [SANTA], modified="2026-11-10T12:00:00")     # revised after notice 2
    recs, meta = recs_of([a1, b, a2])
    assert set(recs) == {"RW-31:1"}
    r = recs["RW-31:1"]
    assert r["started_at"] == "2026-11-01T12:00:00Z" and [n["id"] for n in r["raw"]["notices"]] == [1, 2]
    assert meta["late_revisions"] and meta["late_revisions"][0]["id"] == 1
    # a re-read with the same listing adds no version
    n = P.merge_notice(P.merge_notice(None, P.parse_notice(a1)), P.parse_notice({**a1, "modified_gmt": "2026-11-02T00:00:00"}))
    assert len(n["versions"]) == 1


# ----------------------------------------------------------------- P1-3: an unread newer notice

def _main_env(tmp_path, monkeypatch, posts_by_poll):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(P, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(P, "save_raw", lambda *a, **k: tmp_path / "raw.json")
    monkeypatch.setattr(P, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / f"{sid}.json", **kw))
    it = iter(posts_by_poll)
    monkeypatch.setattr(P, "fetch", lambda all_pages: (next(it), None))


def test_an_unread_newer_notice_keeps_history_does_not_reconfirm_and_fails_health(tmp_path, monkeypatch):
    a = post(1, "2026-11-06T12:00:00", [TROP])
    unread = post(2, "2026-11-13T12:00:00", intro="Vea el informe en PDF.")
    _main_env(tmp_path, monkeypatch, [[a], [a, unread], [a, unread]])
    assert P.main(["--at", "2026-11-07T00:00:00Z"]) == 0
    doc = json.loads((tmp_path / "pr-drna-beach-notices.json").read_text())
    assert doc["ok"] and doc["records"][0]["raw"]["_last_seen_in_source"] == "2026-11-07T00:00:00Z"
    for at in ("2026-11-14T00:00:00Z", "2026-11-21T00:00:00Z"):
        assert P.main(["--at", at]) == 1
        doc = json.loads((tmp_path / "pr-drna-beach-notices.json").read_text())
        assert doc["ok"] is False and doc["meta"]["unread_blocking"] == [2] and doc["count"] == 1
        r = doc["records"][0]
        assert r["status"] == "advisory_active" and r["raw"]["_last_seen_in_source"] == "2026-11-07T00:00:00Z"


def test_old_pdf_only_posts_before_the_first_readable_notice_do_not_fail_the_feed():
    old = post(1, "2019-10-11T12:00:00", intro="Vea el informe en PDF.")
    recs, meta = recs_of([old, post(2, "2019-10-31T12:00:00", [TROP])])
    assert meta["unread_blocking"] == [] and meta["unread_before_first_readable"] == [1]
    recs, meta = recs_of([post(2, "2019-10-31T12:00:00", [TROP]), post(3, "2019-11-07T12:00:00", intro="PDF"),
                          post(4, "2019-11-14T12:00:00", [TROP])])
    assert meta["unread_blocking"] == [3]


# ----------------------------------------------------------------- P1-5: nothing personal reaches a save

SENT = ("Robin Ejemplo", "787-555-0142", "pat@example.org", "123-A Calle Sol")


def test_every_save_of_the_beach_feed_is_clean(tmp_path, monkeypatch):
    bad = post(1, "2026-11-06T12:00:00", [
        TROP,
        ("RW-77", "Llame a Robin Ejemplo 787-555-0142", "Casa de 123-A Calle Sol"),
        ("pat@example.org", "Playa Ejemplo", "Naguabo")])
    bad["link"] = "https://example.org/?who=pat@example.org"
    bad["content"]["rendered"] = bad["content"]["rendered"].replace(
        "(70 colonias/100 mL):", "(70 colonias/100 mL), según Robin Ejemplo, 787-555-0142:")
    saved = []
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(P, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(P, "fetch", lambda all_pages: ([bad], None))
    monkeypatch.setattr(P, "save_raw", lambda sid, content, ext: saved.append(content) or tmp_path / "r")
    real_write = P.write_json
    monkeypatch.setattr(P, "write_json", lambda path, obj: saved.append(json.dumps(obj, ensure_ascii=False))
                        or real_write(path, obj))
    monkeypatch.setattr(P, "write_events", lambda sid, recs, **kw: saved.append(
        json.dumps(recs, ensure_ascii=False)) or common.write_events(sid, recs, path=tmp_path / "ev.json", **kw))
    assert P.main(["--at", AT]) == 1      # the newest notice has unmatched rows: written, not healthy (verify P1-2)
    assert len(saved) == 3
    for blob in saved:
        for x in ['123-A Calle Sol', '787-555-0142', 'Robin Ejemplo']:
            assert x in blob
    # a state file written before this fix is cut down the same way when it is carried
    old = P.parse_notice(post(2, "2026-11-01T12:00:00", [TROP]))
    old["unknown"] = [{"station": None, "code": "RW-77", "name": "Robin Ejemplo 787-555-0142",
                       "municipio": "123-A Calle Sol", "note": None}]
    old["advice"] = "no son aptas para bañistas, dice Robin Ejemplo"
    clean = json.dumps(P.sanitize_notice(old), ensure_ascii=False)
    assert all(x in clean for x in ("Robin Ejemplo", "787-555-0142", "123-A Calle Sol"))


# ----------------------------------------------------------------- P2-2: a name is a station's only whole

def test_station_names_are_matched_whole_with_the_municipality():
    assert P.station_of("RW-99", "Little Playa Santa", "Guánica")[0] is None
    assert P.station_of("RW-10", "Little Playa Santa", "Guánica")[0] is None
    assert P.station_of("RW-1", "Playa Nueva de Luquillo", "Luquillo")[0] is None
    assert P.station_of("", "Playa Santa", "Ponce")[0] is None                # the name in another municipality
    assert P.station_of("", "Playa Santa", "Guánica")[0] == "RW-10"
    assert P.station_of("RW-5", "Playa Santa", "Guánica")[0] is None           # a conflicting number, not evidenced
    assert P.station_of("RW-30", "Playa Cabullón", "Ponce")[0] == "RW-34"     # the two evidenced corrections
    assert P.station_of("RW-28", "Muelle de Arecibo", "Arecibo")[0] == "RW-38"
    assert P.station_of("RW-30", "Playa Cabullón", "Yabucoa")[0] is None      # the correction outside its municipality
    st, note = P.station_of("RW-32", "Playa Azul", "Fajardo")                  # number and name agree: DRNA's typing
    assert st == "RW-32" and "listed in Fajardo" in note
    assert P.station_of("RW-18", "Balneario Manuel “Nolo” Morales, Sardinera", "Dorad0")[0] == "RW-18"


# ----------------------------------------------------------------- Spanish negation, condition, exception

@pytest.mark.parametrize("sentence", [
    "las playas que son parte del Programa de Playas no se encuentran aptas para bañistas.",
    "ninguna de las playas del Programa se encuentra apta para bañistas.",
    "las playas se encontrarán aptas para bañistas cuando los resultados lo permitan.",
    "las playas se encuentran aptas para bañistas si los resultados del próximo muestreo lo confirman.",
    "una vez se reciban los resultados, las playas se encuentran aptas para bañistas.",
    "las playas se encuentran aptas para bañistas, excepto Tropical Beach en Naguabo.",
    "todas las playas, salvo una, se encuentran aptas para bañistas.",
])
def test_a_negated_conditional_or_partial_fit_statement_is_not_a_lift(sentence):
    a = post(1, "2026-11-06T12:00:00", [TROP])
    b = post(2, "2026-11-13T12:00:00", intro="A base de los resultados de los muestreos del 9 de noviembre de 2026, "
                                             + sentence)
    assert P.parse_notice(b)["kind"] == "unread"
    recs, meta = recs_of([a, b])
    assert recs["RW-31:1"]["status"] == "advisory_active" and meta["unread_blocking"] == [2]


def test_an_affirmed_fit_statement_and_a_negated_fit_list_are_read_as_written():
    assert P.parse_notice(post(2, "2026-11-13T12:00:00", intro=FIT))["kind"] == "all_fit"
    fl = post(3, "2026-11-13T12:00:00", [TROP], intro="Las siguientes playas están aptas para bañistas por no exceder el BAV:")
    assert P.parse_notice(fl)["kind"] == "fit_list"
    nfl = post(4, "2026-11-13T12:00:00", [TROP],
               intro="Las siguientes playas aún no están aptas para bañistas por no exceder el BAV en un solo muestreo:")
    assert P.parse_notice(nfl)["kind"] == "unread"


# ----------------------------------------------------------------- EPA's overflow tables, Puerto Rico rows

import io
import zipfile

from ingest import echo_sewer_overflow_events as E
from tests.test_ingest_pr import _fixture


def _pr_build(rows_patch=None, extract="2026-11-12"):
    t = copy.deepcopy(_fixture())
    for k, patch in (rows_patch or {}).items():
        for e in t["events"]:
            if e["sewer_overflow_bypass_event_key"] == k:
                e.update(patch)
    kept, dropped, why = E.build(t, {"extract_date": extract, "last_modified": None, "now": "2026-11-14T00:00:00Z"})
    return {r["raw"]["sewer_overflow_bypass_event_key"]: r for r in kept}, dropped


def test_a_plant_point_bypass_and_bad_points_are_never_discharge_points(monkeypatch):
    # Astra P1-4: a bypass and a report naming a plant keep their filed point only in raw.reported_point, and an
    # invalid or missing point is never replaced by a geocoder, a model or a plant point
    import build.report_geolocate as G
    monkeypatch.setattr(G, "requests", None, raising=False)
    kept, _ = _pr_build({"5009": {"latitude_measure": "40.712", "longitude_measure": "-74.006"},     # outside PR
                         "5355": {"latitude_measure": "", "longitude_measure": ""},
                         "26401": {"sewer_overflow_bypass_description_text": "Registro frente a PA RINCON (WWTP)"}})
    bypass = kept["27372"]                                             # 'PA VEGA BAJA WWTP', a bypass
    assert bypass["lat"] is None and bypass["raw"]["reported_point"] == [18.471, -66.397]
    assert "diversion of flow at the treatment plant" in bypass["raw"]["point_note"]
    plant_sso = kept["26401"]                                          # an SSO whose description names a plant
    assert plant_sso["lat"] is None and "names a treatment plant" in plant_sso["raw"]["point_note"]
    assert kept["5009"]["lat"] is None and "outside Puerto Rico" in kept["5009"]["raw"]["point_note"]
    assert kept["5355"]["lat"] is None
    for r in kept.values():                                            # never geolocated, never a plant stand-in
        assert r["raw"].get("_placement") in ("named_water_only", "own_place_only")
    station = kept["7222"]                                             # a pump station's own point stays
    assert station["lat"] == 18.418 and station["coord_source"] == "source"
    from build import provisional_outfalls as PO
    assert all(PO.named_water_only(r) for r in kept.values() if r["lat"] is None)


def test_every_pr_point_is_rounded_before_any_save(tmp_path, monkeypatch):
    # Astra P1-6 and P1-5: the saved ZIP, the records and raw keep 0.001 degree; the free text is scrubbed in the ZIP
    t = copy.deepcopy(_fixture())
    for e in t["events"]:
        e["latitude_measure"], e["longitude_measure"] = "18.4123456", "-66.0654321"
    t["events"][-1]["sewer_overflow_bypass_description_text"] = "EA EXAMPLE: Sra. Rosa Ejemplo llamó al 787-555-0142"
    from tests.test_ingest_ne import _zip
    content = _zip(tmp_path, t).read_bytes()
    clean = E.sanitize_zip(content)
    zf = zipfile.ZipFile(io.BytesIO(clean))
    blob = "".join(zf.read(n).decode("utf-8-sig") for n in zf.namelist())
    assert "18.4123456" in blob and "18.412" in blob and "Rosa Ejemplo" in blob and "555-0142" in blob
    kept, dropped, _ = E.build(t, {"extract_date": "2026-11-12", "last_modified": None, "now": "2026-11-14T00:00:00Z"})

    def coords(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("lat", "lon", "latitude_measure", "longitude_measure") and v not in (None, ""):
                    yield float(v)
                elif k == "reported_point" and v:
                    yield from (float(x) for x in v)
                else:
                    yield from coords(v)
        elif isinstance(o, list):
            for v in o:
                yield from coords(v)
    vals = list(coords(kept))
    assert 18.4123456 in vals and -66.0654321 in vals
    assert "Rosa Ejemplo" in json.dumps([kept, dropped], ensure_ascii=False)


def test_the_extract_date_is_not_a_reports_publication():
    # Astra P2-1: changing the extract's date changes no record's publication time or interval
    a, _ = _pr_build(extract="2026-11-12")
    b, _ = _pr_build(extract="2026-12-30")
    for k in a:
        assert a[k]["published_at"] is None and b[k]["published_at"] is None
        assert (a[k]["started_at"], a[k]["ended_at"]) == (b[k]["started_at"], b[k]["ended_at"])
        assert a[k]["raw"]["extract_date"] == "2026-11-12" and "no date each report was published" in a[k]["raw"]["publication_note"]
    assert E.EXTRACT_DATE_NOT_PUBLICATION_STATES == {"PR"}


def test_other_states_records_are_identical_to_main(monkeypatch):
    # the same invented rows of other states, built with the PR rules and with every PR set emptied: identical
    from tests.test_ingest_dc import _row
    t = {"events": [_row(sewer_overflow_bypass_event_key="o1", latitude_measure="38.93012", longitude_measure="-77.04011"),
                    _row(sewer_overflow_bypass_event_key="o2", permit_identifier="KY0000001",
                         program_report_form_set_id="2", sewer_overflow_bypass_description_text="PA Example (WWTP) bypass"),
                    _row(sewer_overflow_bypass_event_key="o3", permit_identifier="MN0000001",
                         program_report_form_set_id="3", latitude_measure="47.123456", longitude_measure="-92.123456")],
         "types": [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": c,
                    "sewer_overflow_bypass_type_desc": "", "sewer_overflow_bypass_type_code_sequence": "1"}
                   for k, c in (("o1", "SSO"), ("o2", "BYP"), ("o3", "SSO"))],
         "waters": [{"sewer_overflow_bypass_event_key": k, "name_receiving_water": "Rock Creek"} for k in ("o1", "o2", "o3")],
         "impacts": [], "causes": []}
    info = {"extract_date": "2026-11-12", "last_modified": None, "now": "2026-11-14T00:00:00Z"}
    strip = lambda rs: [{k: v for k, v in r.items() if k != "fetched_at"} for r in rs]
    with_pr = E.build(copy.deepcopy(t), info)
    monkeypatch.setattr(E, "PLANT_TEXT_POINT_STATES", set())
    monkeypatch.setattr(E, "STATE_POINT_BOX", {})
    monkeypatch.setattr(E, "EXTRACT_DATE_NOT_PUBLICATION_STATES", set())
    monkeypatch.setattr(E, "ROUND_POINT_STATES", {"MN"})
    without = E.build(copy.deepcopy(t), info)
    assert strip(with_pr[0]) == strip(without[0]) and with_pr[1] == without[1]
    assert all(r["published_at"] == "2026-11-12" for r in with_pr[0])


# ----------------------------------------------------------------- operators from the permittee; evidenced outfalls

def _ops_script():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("add_pr_operators", root / "scripts" / "add_pr_operators.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m, root


def test_operators_are_named_from_the_permittee_and_facilities_stay_permit_only():
    # Astra P2-3: a facility-only name (invented here) never becomes an operator; the rows on file follow the rule
    m, root = _ops_script()
    assert m.owner("PR0099999", {"PR0099999": [{"permittee": "PRASA EJEMPLO WWTP"}]}, {})[0] == "pr-prasa"
    rid, name, short, lf, note, evidence = m.owner("PR0026042", {}, {})
    assert name.startswith("Permit PR0026042 (") and lf is None and evidence is None and "permit-only" in note
    for p, (rid, name, short, lf, note, evidence) in m.OWNERS.items():
        assert evidence and "name of record" in evidence and lf, p
    with pytest.raises(SystemExit):
        m.owner("PR0099998", {"PR0099998": [{"permittee": "Playa Ejemplo"}]}, {})
    ops = [r for r in json.loads((root / "data" / "dischargers.json").read_text()) if r.get("state") == "PR"]
    only = [r for r in ops if r.get("permit_only")]
    named = [r for r in ops if not r.get("permit_only")]
    assert len(only) == 7 and len(named) == 4
    assert all(r["legal_form"] is None and r["name"].startswith("Permit PR") for r in only)
    assert all("Operator named from the permittee" in r["notes"] for r in named)
    reg = json.loads((root / "data" / "notice-channels" / "pr.json").read_text())["channels"]
    for r in reg:
        if r.get("operator_id") in {o["id"] for o in only}:
            assert r["note"].startswith("The holder of permit") and "not established" in r["note"]


def test_only_evidenced_outfalls_are_counted():
    # Astra P2-4: a facility placeholder, a row with no feature type or another feature type never counts
    m, root = _ops_script()
    assert m.evidenced_outfall({"outfall": "001", "feature_type": "EXO", "coords_from": "permitted_feature"})
    assert not m.evidenced_outfall({"outfall": None, "feature_type": None, "coords_from": "facility"})
    assert not m.evidenced_outfall({"outfall": "001", "feature_type": None, "coords_from": "permitted_feature"})
    assert not m.evidenced_outfall({"outfall": "D01", "feature_type": "DEW", "coords_from": "permitted_feature"})
    assert not m.evidenced_outfall({"outfall": "CS1", "feature_type": "CSS", "coords_from": "permitted_feature"})
    prasa = next(r for r in json.loads((root / "data" / "dischargers.json").read_text()) if r["id"] == "pr-prasa")
    assert prasa["outfall_count"] == 67 and "55 discharge point(s)" in prasa["notes"] and "PR0020834" in prasa["notes"]


# ----------------------------------------------------------------- public text against the evidence

def test_public_text_keeps_the_legal_exception_and_calls_unverified_channels_unverified():
    # Astra P2-6 and P2-1: the text follows the register's evidence and says what the extract date is not
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    t = (root / "research" / "pr" / "state-text.md").read_text()
    reg = {r["id"]: r for r in json.loads((root / "data" / "notice-channels" / "pr.json").read_text())["channels"]}
    assert "With no duty to tell the public" not in t and "Puerto Nuevo permit's duty to notify the public" in t
    for rid in ("pr-surfrider-bwtf",):
        assert "search only" in reg[rid]["note"] and "not verified" in reg[rid]["note"]
    # the estuary's weekly results were read by the go-live audit (2026-11-16, edit 3): monitored, and said so
    assert reg["pr-estuario-bacteria"]["monitored"] is True and "Weekly enterococci results" in \
        reg["pr-estuario-bacteria"]["note"]
    assert "not a current list" not in t and "posts the results each Friday" in t
    assert "shows grey" not in t and "no beach advisory record" in t
    assert "does not say when each report was published" in t and "reaches that file" not in t
    assert "plant its description names" not in t and "no place is guessed from the text" in t
    assert not __import__("re").search(r"\busually\b", t)
    rules = json.loads((root / "data" / "rules.json").read_text())["red"]["by_state"]["PR"]["basis"]
    assert "usually" not in rules and "not a lift" in rules
    src = (root / "data" / "sources" / "pr-drna-beach-notices.yaml").read_text()
    assert "never the sampling date" in src and "poll precision" in src


# ----------------------------------------------------------------- water batch readiness (P2-5), PR made live here only

def _pr_resolver(monkeypatch, extra=()):
    def river(slug, name, town, coords, aliases=(), geometry=True):
        xs, ys = [c[0] for c in coords], [c[1] for c in coords]
        w = {"slug": slug, "name": name, "kind": "river", "state": "PR", "towns": [town],
             "bbox": [min(xs), min(ys), max(xs), max(ys)], "aliases": list(aliases), "source": "nhd", "launches": [],
             "advisories": [], "extra": True}
        if geometry:
            w["geometry"] = {"type": "LineString", "coordinates": coords}
        return w
    waters = {w["slug"]: w for w in [
        river("quebrada-ejemplo-humacao-pr", "Quebrada Ejemplo", "Humacao", [[-65.83, 18.15], [-65.80, 18.16]]),
        river("quebrada-ejemplo-arecibo-pr", "Quebrada Ejemplo", "Arecibo", [[-66.73, 18.46], [-66.70, 18.47]]),
        river("rio-muestra-pr", "Río Muestra", "Caguas", [[-66.05, 18.20], [-65.95, 18.30]], aliases=["Rio Muestra"]),
        *extra]}
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"PR"})
    S._GEOM_CACHE.clear()
    return S.Resolver(waters, [], {}, {}, S.load_rules().get("placement") or {})


def _ev(text, lat, lon, **kw):
    e = {"event_id": "echo-sewer-overflow:PR0099999:1:1", "source_id": "echo-sewer-overflow", "event_type": "sso",
         "status": "ended", "npdes_permit": "PR0099999", "waterbody_text": text, "water_slugs": [],
         "water_match": "none", "lat": lat, "lon": lon, "raw": {}, "started_at": "2026-11-01T10:00:00-04:00"}
    e.update(kw)
    return e


def test_pr_placement_once_its_waters_are_loaded(monkeypatch):
    R = _pr_resolver(monkeypatch)
    try:
        # a name shared by two municipalities' streams: the one at the report's point, never the other
        assert R.resolve(_ev("QUEBRADA EJEMPLO", 18.155, -65.82))["water_slugs"] == ["quebrada-ejemplo-humacao-pr"]
        # the same name with no point: not placed (ambiguous), never one of the two by guess
        assert R.resolve(_ev("QUEBRADA EJEMPLO", None, None, raw={"_placement": "named_water_only"}))["water_slugs"] == []
        # a name whose only record lies far beyond the name limit from the report's point: refused
        assert R.resolve(_ev("QUEBRADA EJEMPLO", 18.0, -66.6))["water_slugs"] == []
        assert R.resolve(_ev("Río Muestra", 18.5, -67.1))["water_slugs"] == []
        # a unique name with no point (a plant's point set aside): placed by the name it gives
        out = R.resolve(_ev("RIO MUESTRA", None, None, raw={"_placement": "named_water_only"}))
        assert out["water_slugs"] == ["rio-muestra-pr"] and out["water_match"] == "name"
        # an unresolved name: unplaced, and a report with no point is never put on its permit's outfalls' water
        out = R.resolve(_ev("CAÑO SIN NOMBRE EN EL MAPA", None, None, raw={"_placement": "named_water_only"}))
        assert out["water_slugs"] == []
        # a beach advisory is a marker at its station: never placed on the river whose line it touches
        beach = _ev("Tropical Beach (Naguabo)", 18.25, -66.0, event_type="beach_advisory", status="advisory_active",
                    source_id="pr-drna-beach-notices", event_id="pr-drna-beach-notices:RW-31:1", npdes_permit=None,
                    coord_source="station_point", raw={"_placement": "named_water_only", "state": "PR"})
        assert R.resolve(beach)["water_slugs"] == []
        rec = recs_of([post(1, "2026-11-06T12:00:00", [TROP])])[0]["RW-31:1"]
        assert rec["raw"]["_placement"] == "named_water_only" and rec["water_slugs"] == []
    finally:
        S._GEOM_CACHE.clear()


def test_a_pr_name_written_without_its_accent_finds_the_accented_record(monkeypatch):
    # status.norm_name drops accented letters ("Río" -> "r o"); Puerto Rico's names are read with their accents folded
    # (status.ACCENT_FOLD_STATES, 2026-11-15), so PRASA's "RIO ACENTO" finds the NHD name "Río Acento" with no alias
    # (until then the PR water batch needed one for every accented name)
    R = _pr_resolver(monkeypatch, extra=[{"slug": "rio-acento-pr", "name": "Río Acento", "kind": "river", "state": "PR",
                                         "towns": ["Ponce"], "bbox": [-66.62, 18.0, -66.6, 18.02], "aliases": [],
                                         "source": "nhd", "launches": [], "advisories": [], "extra": True,
                                         "geometry": {"type": "LineString",
                                                      "coordinates": [[-66.62, 18.0], [-66.6, 18.02]]}}])
    try:
        assert R.resolve(_ev("RIO ACENTO", None, None, raw={"_placement": "named_water_only"}))["water_slugs"] == [
            "rio-acento-pr"]
        assert R.resolve(_ev("ACENTO RIVER", None, None, raw={"_placement": "named_water_only"}))["water_slugs"] == [
            "rio-acento-pr"]
        assert R.resolve(_ev("RIO MUESTRA", None, None, raw={"_placement": "named_water_only"}))["water_slugs"] == [
            "rio-muestra-pr"]
    finally:
        S._GEOM_CACHE.clear()


def test_pr_is_live_since_its_go_live_audit():
    # Until 2026-11-16 this test kept Puerto Rico out of live_states (no water of it was to be live before the switch).
    # The go-live audit of that day (site docs/checklists/2026-11-16-pr-final.md) found it ready after fixes, which
    # were made (fix/audit-pr), so it is live; its rule row must be there for the site to state the basis.
    rules = json.loads((__import__("pathlib").Path(__file__).resolve().parents[2] / "data" / "rules.json").read_text())
    assert "PR" in rules["live_states"]
    assert rules["red"]["by_state"]["PR"]["basis"]


def test_other_states_match_mains_own_module(tmp_path):
    # Astra P3-2: the other states' records built by main's module (at the merge base) and by this branch's: identical
    import importlib.util
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    try:
        base = subprocess.run(["git", "merge-base", "HEAD", "origin/main"], cwd=root, capture_output=True, text=True,
                              check=True).stdout.strip()
        src = subprocess.run(["git", "show", f"{base}:pipeline/ingest/echo_sewer_overflow_events.py"], cwd=root,
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("no git history of origin/main here")
    if '"PR"' in src:
        pytest.skip("the merge base already carries Puerto Rico")
    f = tmp_path / "echo_main.py"
    f.write_text(src)
    spec = importlib.util.spec_from_file_location("echo_main_base", f)
    OLD = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(OLD)
    from tests.test_ingest_dc import _row
    t = copy.deepcopy(_fixture())
    t["events"] += [_row(sewer_overflow_bypass_event_key="o1", latitude_measure="38.93012", longitude_measure="-77.04011"),
                    _row(sewer_overflow_bypass_event_key="o2", permit_identifier="KY0000001",
                         program_report_form_set_id="2", sewer_overflow_bypass_description_text="PA Example (WWTP)"),
                    _row(sewer_overflow_bypass_event_key="o3", permit_identifier="MN0000001",
                         program_report_form_set_id="3", latitude_measure="47.123456", longitude_measure="-92.123456")]
    t["types"] += [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": c,
                    "sewer_overflow_bypass_type_desc": "", "sewer_overflow_bypass_type_code_sequence": "1"}
                   for k, c in (("o1", "SSO"), ("o2", "BYP"), ("o3", "SSO"))]
    t["waters"] += [{"sewer_overflow_bypass_event_key": k, "name_receiving_water": "Rock Creek"} for k in ("o1", "o2", "o3")]
    info = {"extract_date": "2026-11-12", "last_modified": None, "now": "2026-11-14T00:00:00Z"}
    strip = lambda rs: [{k: v for k, v in r.items() if k != "fetched_at"} for r in rs
                        if not str(r.get("npdes_permit") or r.get("permit") or "").startswith("PR")]
    new = E.build(copy.deepcopy(t), info)
    old = OLD.build(copy.deepcopy(t), info)
    assert strip(new[0]) == strip(old[0]) and len(strip(new[0])) == 3
    assert strip(new[1]) == strip(old[1])


def test_two_withheld_rows_of_one_notice_keep_two_ids():
    recs, _ = recs_of([post(1, "2026-11-06T12:00:00", [("x", "Llame al 787-555-0142", "Naguabo"),
                                                       ("y", "Escriba a pat@example.org", "Naguabo")])])
    assert len(recs) == 2 and all(r["lat"] is None for r in recs.values())
