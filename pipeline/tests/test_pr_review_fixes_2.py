"""Puerto Rico: the fixes of Astra's verification pass on fix/pr-review (2026-11-15), each on invented data in DRNA's
and EPA's forms; no real notice or report is changed."""
import json

import pytest

import common
from ingest import pr_drna_beaches as P
from tests.test_pr_review_fixes import AT, AZUL, FIT, INTRO, SANTA, TROP, _main_env, post, recs_of


def _doc(tmp_path):
    return json.loads((tmp_path / "pr-drna-beach-notices.json").read_text())


# ----------------------------------------------------------------- P1-1: a re-read never moves a revision's time

def test_an_unchanged_reread_with_a_newer_modified_time_keeps_the_revisions_start():
    v1 = post(10, "2026-11-01T12:00:00", [TROP])
    v2 = post(10, "2026-11-01T12:00:00", [TROP, AZUL], modified="2026-11-08T12:00:00")
    v3 = post(10, "2026-11-01T12:00:00", [TROP, AZUL], modified="2026-11-15T12:00:00")
    recs, _ = recs_of([v1, v2])
    assert recs["RW-32:10r1"]["started_at"] == "2026-11-08T12:00:00Z"
    recs, meta = recs_of([v1, v2, v3], at="2026-11-16T00:00:00Z")
    assert recs["RW-32:10r1"]["started_at"] == "2026-11-08T12:00:00Z"
    assert recs["RW-32:10r1"]["status"] == "advisory_active" and meta["late_revisions"] == []
    # with a newer notice published between the revision and the later re-read, the revision is not made late
    n11 = post(11, "2026-11-10T12:00:00", [TROP, AZUL])
    recs, meta = recs_of([v1, v2, n11, v3], at="2026-11-16T00:00:00Z")
    azul = recs["RW-32:10r1"]
    assert azul["started_at"] == "2026-11-08T12:00:00Z" and azul["status"] == "advisory_active"
    assert [n["id"] for n in azul["raw"]["notices"]] == [10, 11] and meta["late_revisions"] == []
    # the later modification time is kept apart, not lost
    ns = {}
    for p in (v1, v2, v3):
        ns[p["id"]] = P.merge_notice(ns.get(p["id"]), P.parse_notice(p))
    v = ns[10]["versions"][-1]
    assert v["modified"] == "2026-11-08T12:00:00Z" and v["modified_latest"] == "2026-11-15T12:00:00Z"
    assert P.sanitize_notice(ns[10])["versions"][-1]["modified_latest"] == "2026-11-15T12:00:00Z"


# ----------------------------------------------------------------- P1-2: an incomplete read ends nothing

def _rows_html(rows, extra="", close=True):
    t = "".join(f"<tr><td>{c}</td><td>{n}</td><td>{m}</td></tr>" for c, n, m in rows)
    return (f"<p>{INTRO}</p><table><tr><th>Estación</th><th>Nombre</th><th>Municipio</th></tr>{t}{extra}"
            + ("</table>" if close else ""))


@pytest.mark.parametrize("extra,close", [("<tr><td>Tropical</td></tr>", True),        # a one-cell row
                                         ("<tr><td>RW-</td><td>Tropi</td></tr>", True),  # a two-cell row
                                         ("", False)])                                   # a table cut off
def test_a_truncated_row_or_table_ends_no_advisory_and_fails_health(extra, close):
    a = post(1, "2026-11-01T12:00:00", [TROP, SANTA])
    b = post(2, "2026-11-08T12:00:00", [SANTA])
    b["content"]["rendered"] = _rows_html([SANTA], extra, close)
    recs, meta = recs_of([a, b])
    trop = recs["RW-31:1"]
    assert trop["status"] == "advisory_active" and trop["ended_at"] is None
    assert trop["raw"]["_last_seen_in_source"] == "2026-11-01T12:00:00Z"          # not reconfirmed by notice 2
    assert meta["incomplete_blocking"] == [2]


def test_an_unmatched_row_in_the_newest_notice_fails_health_and_an_older_one_does_not():
    a = post(1, "2026-11-01T12:00:00", [TROP, ("RW-77", "Playa Ejemplo", "Naguabo")])
    recs, meta = recs_of([a])
    assert meta["incomplete_blocking"] == [1]
    recs, meta = recs_of([a, post(2, "2026-11-08T12:00:00", [TROP])])
    assert meta["incomplete_blocking"] == []


def test_partial_polls_through_main_keep_history_and_fail_health(tmp_path, monkeypatch):
    a = post(1, "2026-11-01T12:00:00", [TROP, SANTA])
    trunc = post(2, "2026-11-08T12:00:00", [SANTA])
    trunc["content"]["rendered"] = _rows_html([SANTA], "<tr><td>Tropical</td></tr>")
    nodate = {**post(3, "2026-11-15T12:00:00", [SANTA]), "date_gmt": None}
    unmatched = post(4, "2026-11-15T12:00:00", [SANTA, ("RW-77", "Playa Ejemplo", "Naguabo")])
    _main_env(tmp_path, monkeypatch, [[a], [a, trunc], [a, trunc], [a, nodate], [a, unmatched]])
    assert P.main(["--at", "2026-11-02T00:00:00Z"]) == 0 and _doc(tmp_path)["ok"]
    for at in ("2026-11-09T00:00:00Z", "2026-11-10T00:00:00Z"):
        assert P.main(["--at", at]) == 1
        doc = _doc(tmp_path)
        trop = next(r for r in doc["records"] if r["source_record_id"] == "RW-31:1")
        assert doc["ok"] is False and trop["status"] == "advisory_active"
        assert trop["raw"]["_last_seen_in_source"] == "2026-11-02T00:00:00Z"
    assert P.main(["--at", "2026-11-16T00:00:00Z"]) == 1          # a post with no date: not skipped silently
    doc = _doc(tmp_path)
    assert doc["ok"] is False and doc["meta"]["malformed_posts"] == [{"id": 3, "why": "no date_gmt"}]
    assert next(r for r in doc["records"] if r["source_record_id"] == "RW-31:1")["status"] == "advisory_active"
    assert P.main(["--at", "2026-11-17T00:00:00Z"]) == 1          # an unmatched row in the newest notice
    doc = _doc(tmp_path)
    assert doc["ok"] is False and doc["meta"]["incomplete_blocking"] == [4]
    assert next(r for r in doc["records"] if r["source_record_id"] == "RW-31:1")["status"] == "advisory_active"


# ----------------------------------------------------------------- P1-3: the subject and mood of a Spanish statement

@pytest.mark.parametrize("sentence", [
    "A base de los resultados de los muestreos del 9 de noviembre de 2026, la Playa Santa se encuentra apta para "
    "bañistas.",
    "A base de los resultados de los muestreos del 9 de noviembre de 2026, las playas Santa y Azul se encuentran "
    "aptas para bañistas.",
    "Se espera que las playas que son parte del Programa de Playas se encuentran aptas para bañistas.",
    "Las playas que son parte del Programa de Playas podrían, si los resultados lo permiten, se encuentran aptas "
    "para bañistas.",
    "Las playas que son parte del Programa de Playas aún no se encuentran aptas para bañistas.",
])
def test_a_single_beach_or_a_conditional_fit_statement_lifts_nothing(sentence):
    a = post(1, "2026-11-01T12:00:00", [TROP, SANTA])
    recs, meta = recs_of([a, post(2, "2026-11-08T12:00:00", intro=sentence)])
    assert all(r["status"] == "advisory_active" for r in recs.values())
    assert P.parse_notice(post(2, "2026-11-08T12:00:00", intro=sentence))["kind"] == "unread"
    assert meta["unread_blocking"] == [2]


def test_the_programmes_fit_statement_still_lifts_every_beach():
    a = post(1, "2026-11-01T12:00:00", [TROP, SANTA])
    for intro in (FIT, FIT.replace("las playas que son parte del Programa de Playas",
                                   "todas las playas incluidas en el Programa de Playas,")):
        recs, _ = recs_of([a, post(2, "2026-11-08T12:00:00", intro=intro)])
        assert all(r["status"] == "advisory_lifted" for r in recs.values()), intro


@pytest.mark.parametrize("cond", ["Si los resultados se confirman, la(s) siguiente(s) playa(s)",
                                  "En caso de que se confirmen los resultados, la(s) siguiente(s) playa(s)",
                                  "Se espera que la(s) siguiente(s) playa(s)"])
def test_a_conditional_or_planned_exceedance_list_is_not_read_as_one(cond):
    intro = INTRO.replace("la(s) siguiente(s) playa(s)", cond, 1)
    n = P.parse_notice(post(1, "2026-11-01T12:00:00", [TROP], intro=intro))
    assert n["kind"] == "unread"


# ----------------------------------------------------------------- P1-3 (EPA): a water named only to deny it

from ingest import echo_sewer_overflow_events as E   # noqa: E402


def _reach(text):
    ev = {"sewer_overflow_structure_type_code": "MH"}
    imp = [{"sewer_overflow_bypass_impact_code": "OTH", "sewer_overflow_bypass_impact_other_text": text}]
    return E.reached_water(ev, ["SSO"], [], imp, "PR")


@pytest.mark.parametrize("text", ["El derrame no afectó la quebrada", "El derrame no llegó a la quebrada.",
                                  "No hubo impacto a la quebrada ni al río", "Sin llegar al caño",
                                  "The spill did not reach the creek", "no alcanzó ningún cuerpo de agua ni la playa"])
def test_a_denied_water_is_not_a_water_reached(text):
    assert _reach(text)[0] is False, _reach(text)


@pytest.mark.parametrize("text", ["El derrame no afectó la quebrada pero llegó al río",
                                  "Llegó a la quebrada", "No se pudo contener y discurrió a la quebrada"])
def test_an_affirmed_water_next_to_a_denied_one_is_kept(text):
    assert _reach(text)[0] is True, _reach(text)


def test_other_states_keep_their_reading_of_the_same_text():
    ev = {"sewer_overflow_structure_type_code": "MH"}
    imp = [{"sewer_overflow_bypass_impact_code": "OTH", "sewer_overflow_bypass_impact_other_text":
            "El derrame no afectó la quebrada"}]
    assert E.reached_water(ev, ["SSO"], [], imp, "IL") == E.reached_water(ev, ["SSO"], [], imp, "NE")
