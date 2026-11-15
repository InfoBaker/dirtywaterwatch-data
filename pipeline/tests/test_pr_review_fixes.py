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
    assert S.POLL_END_HORIZON_SOURCES == {"de-dnrec-recreational-water", "sc-des-beach-monitoring", "sc-des-hab",
                                          "pr-drna-beach-notices"}
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
    assert P.main(["--at", AT]) == 0
    assert len(saved) == 3
    for blob in saved:
        for x in SENT:
            assert x not in blob, x
    # a state file written before this fix is cut down the same way when it is carried
    old = P.parse_notice(post(2, "2026-11-01T12:00:00", [TROP]))
    old["unknown"] = [{"station": None, "code": "RW-77", "name": "Robin Ejemplo 787-555-0142",
                       "municipio": "123-A Calle Sol", "note": None}]
    old["advice"] = "no son aptas para bañistas, dice Robin Ejemplo"
    clean = json.dumps(P.sanitize_notice(old), ensure_ascii=False)
    for x in SENT:
        assert x not in clean


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
