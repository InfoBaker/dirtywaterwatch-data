"""Michigan's history from 2001 (pipeline/ingest/mi_egle_mienviro.py --backfill): spans a year at a time, each saved
to the archive as it arrives, a time budget that a later --backfill resumes from, a 4xx answer that stops the backfill
against transient failures that are named and asked again, meta.backfill, and the privacy of the archived rows.
The service is faked from the name-free fixture tests/fixtures/mi_mienviro_list.json (its placeholders must never
reach a record or the archive).
Run from pipeline/: python -m pytest tests/test_ingest_mi_backfill.py -q
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import requests

import common
from ingest import mi_egle_mienviro as M

FIX = Path(__file__).resolve().parent / "fixtures"
TODAY = date(2026, 11, 4)
PERMITS = {"MI0099001": "mi-sampleton", "3112A-0999": "mi-sample-charter-township", "MI0099004": "mi-sample-bay"}
PLACEHOLDERS = ["Pat Example", "517-555-0123", "pat.example@example.com", "Inspector Sample", "Robin Placeholder",
                "Lee Placeholder", "448 Example St", "Behind the house", "6517", "cleaned the manhole",
                "1234567890123456789"]


def fixture_rows():
    return json.loads((FIX / "mi_mienviro_list.json").read_text())["queryResults"]


def year_rows(year: int, n: int = 3) -> list[dict]:
    """Completed reports of an older year, shaped as the list gives them (the fixture's completed rows, the year
    moved, new submission ids); the first keeps the fixture's personal placeholders."""
    done = [r for r in fixture_rows() if r["reportStatusId"] == "COMPLETE" and r["eventStartDate"].startswith("2026")]
    out = []
    for i, r in enumerate((done * 3)[:n]):
        r = dict(r)
        for k in ("eventStartDate", "eventEndDate", "submissionReceivedDate"):
            if r.get(k):
                r[k] = f"{year}{r[k][4:]}"
        r["submissionId"] = f"-7{year}{i:04d}"
        out.append(r)
    return out


def old_shape_row(year: int) -> dict:
    """An older report with the fields the list leaves empty in early years, a permit typed another way, and a field
    the service sent that was not asked for (a contact): only the asked fields are kept."""
    return {"submissionId": f"-8{year}", "sectionNumber": 1, "submissionReceivedDate": f"{year}-03-02T00:00:00",
            "responsiblePartyName": "Village of Sample", "siteName": None, "permitNumber": "MI-0099001",
            "countyDescription": "Sample", "reportStatusId": "COMPLETE", "reportStatusDescription": "Complete",
            "dischargeType": None, "dischargeQuality": "Raw Sewage", "dischargeVolume": None,
            "dischargeVolumeNumeric": None, "eventStartDate": f"{year}-03-01T00:00:00", "eventEndDate": None,
            "featureNumber": None, "featureDescription": None, "receivingWater": "Sample River",
            "landImpacted": None, "contactName": "Pat Example", "contactPhone": "517-555-0123"}


class Resp:
    def __init__(self, rows, code=200):
        self.rows, self.status_code = rows, code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return {"queryResults": self.rows, "hasResultsRemaining": False}


class Service:
    """The list service: open reports from the fixture, completed ones by start year; fail[span] = an exception or an
    HTTP code to answer for that span's request (once, or always when sticky)."""

    def __init__(self, by_year: dict[int, list[dict]], fail: dict | None = None, sticky: bool = False):
        self.by_year, self.fail, self.sticky, self.asked = by_year, dict(fail or {}), sticky, []

    def get(self, url, params=None, timeout=None):
        flt = json.loads(params["queryParams"])["filter"][0]
        if flt.get("reportStatusId") == "IN_PROCESS":
            return Resp([r for r in fixture_rows() if r["reportStatusId"] == "IN_PROCESS"])
        if "submissionId" in flt:
            return Resp([])
        lo, hi = flt.get("eventStartDateMin"), flt.get("eventStartDateMax")
        if lo and hi and (date.fromisoformat(hi) - date.fromisoformat(lo)).days < 100:   # the hourly 60-day read
            return Resp([])
        span = (lo[:4] if lo and hi else "later" if lo else "before")
        self.asked.append(span)
        if span in self.fail:
            f = self.fail[span] if self.sticky else self.fail.pop(span)
            if isinstance(f, int):
                return Resp([], f)
            raise f
        if span in ("later", "before"):
            return Resp([])
        return Resp(list(self.by_year.get(int(span), [])))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(M, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(M, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(M, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(M, "permit_index", lambda rows=None: dict(PERMITS))
    monkeypatch.setattr(M, "save_raw", lambda sid, content, ext: _raw(tmp_path, content))
    monkeypatch.setattr(M, "ROOT", tmp_path)
    monkeypatch.setattr(M, "BACKFILL_PAUSE_S", 0)
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    return tmp_path


def _raw(tmp_path, content):
    p = tmp_path / "raw" / f"{len(list((tmp_path / 'raw').glob('*'))) if (tmp_path / 'raw').exists() else 0}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def run(env, monkeypatch, service, *args) -> dict:
    monkeypatch.setattr(M.requests, "Session", lambda: _Sess(service))
    monkeypatch.setattr(M, "datetime", _Clock)
    assert M.main(list(args)) == 0
    return json.loads((env / "events" / f"{M.SOURCE_ID}.json").read_text())


class _Sess:
    def __init__(self, service):
        self.service, self.headers = service, {}

    def get(self, *a, **k):
        return self.service.get(*a, **k)


class _Clock(M.datetime):
    @classmethod
    def now(cls, tz=None):
        return M.datetime(2026, 11, 4, 12, 0, tzinfo=tz)


def strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield str(k)
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


def leaks(obj):
    text = "\n".join(strings(obj))
    return [p for p in PLACEHOLDERS if p in text]


HISTORY = {y: year_rows(y, 2) for y in range(2001, 2027)}


def test_the_backfill_starts_in_2001_and_asks_for_the_typed_years_before_and_after():
    assert M.BACKFILL_FROM == 2001
    spans = M.backfill_spans(M.BACKFILL_FROM, TODAY)
    names = [n for n, _, _ in spans]
    assert names[0] == "2001" and names[-2] == "2026" and names[-1] == "later" and len(names) == 27
    assert spans[-1][2] is None
    spans = M.backfill_spans(1999, TODAY)
    assert [n for n, _, _ in spans][:3] == ["before-1999", "1999", "2000"] and spans[0][1] is None
    assert [n for n, _, _ in M.backfill_spans(2024, TODAY)] == ["2024", "2025", "2026", "later"]


def test_a_backfill_from_2001_reads_every_year_saves_each_and_names_its_range_in_meta(env, monkeypatch):
    svc = Service(HISTORY)
    d = run(env, monkeypatch, svc, "--backfill")
    b = d["meta"]["backfill"]
    assert b["from"] == 2001 and b["complete"] and b["covered_from"] == 2001 and b["failed"] == []
    assert len(b["read_now"]) == 27 and b["rows"] == 52 and b["rows_by_span"]["2003"] == 2
    assert b["records_by_start_year"]["2001"] == 2 and b["records_by_start_year"]["2014"] == 2
    assert (env / "archive" / "2001.json").exists() and (env / "archive" / "later.json").exists()
    assert "every report read since January 2001" in d["meta"]["left_out_note"]
    years = {r["started_at"][:4] for r in d["records"] if r.get("started_at")}
    assert {"2001", "2013", "2026"} <= years
    # the raw page of the run holds the current answer only; the history is in the archive
    raw = json.loads((env / M.ROOT / d["meta"]["raw_path"]).read_text())
    assert all(not r["eventStartDate"].startswith("2001") for r in raw["rows"])


def test_a_second_backfill_asks_only_for_this_year_and_the_last_and_keeps_the_rest_from_the_archive(env, monkeypatch):
    run(env, monkeypatch, Service(HISTORY), "--backfill")
    svc = Service(HISTORY)
    d = run(env, monkeypatch, svc, "--backfill")
    assert svc.asked == ["2025", "2026", "later"]
    b = d["meta"]["backfill"]
    assert len(b["from_archive"]) == 24 and b["rows"] == 52 and b["complete"]
    svc = Service(HISTORY)
    run(env, monkeypatch, svc, "--backfill", "--refetch")
    assert len(svc.asked) == 27


def test_from_narrows_the_backfill(env, monkeypatch):
    svc = Service(HISTORY)
    d = run(env, monkeypatch, svc, "--backfill", "--from", "2024")
    assert svc.asked == ["2024", "2025", "2026", "later"]
    assert d["meta"]["backfill"]["covered_from"] == 2024
    assert "since January 2024" in d["meta"]["left_out_note"]


def test_a_backfill_out_of_time_stops_asking_names_the_rest_and_the_next_one_resumes(env, monkeypatch):
    ticks = iter([0] + [0] * 6 + [M.BACKFILL_BUDGET_S + 1] * 200)
    monkeypatch.setattr(M, "clock", lambda: next(ticks))
    svc = Service(HISTORY)
    d = run(env, monkeypatch, svc, "--backfill")
    b = d["meta"]["backfill"]
    assert b["read_now"] == ["2001", "2002", "2003", "2004", "2005", "2006"] and not b["complete"]
    assert b["not_requested"][0] == "2007" and b["covered_from"] is None
    assert any("not requested; run --backfill again" in e for e in d["meta"]["lookup_errors"])
    assert "since January" not in d["meta"]["left_out_note"]
    assert {r["started_at"][:4] for r in d["records"] if r.get("started_at")} >= {"2001", "2005"}
    monkeypatch.setattr(M, "clock", lambda: 0)
    svc = Service(HISTORY)
    d = run(env, monkeypatch, svc, "--backfill")
    assert svc.asked[0] == "2007" and "2001" not in svc.asked and d["meta"]["backfill"]["complete"]
    assert d["meta"]["backfill"]["covered_from"] == 2001


def test_a_timeout_or_5xx_is_named_and_asked_again_and_the_next_year_is_still_read(env, monkeypatch):
    svc = Service(HISTORY, {"2004": requests.ReadTimeout("read timed out"), "2010": 503})
    d = run(env, monkeypatch, svc, "--backfill")
    b = d["meta"]["backfill"]
    assert b["failed"] == ["2004", "2010"] and "2005" in b["read_now"] and "2011" in b["read_now"]
    assert not b["complete"] and b["covered_from"] == 2011
    errs = d["meta"]["lookup_errors"]
    assert any("2004 not read: ReadTimeout" in e for e in errs) and any("2010 not read: HTTPError" in e for e in errs)
    assert not (env / "archive" / "2004.json").exists()
    svc = Service(HISTORY)
    d = run(env, monkeypatch, svc, "--backfill")
    assert svc.asked == ["2004", "2010", "2025", "2026", "later"] and d["meta"]["backfill"]["complete"]


def test_a_4xx_answer_stops_the_backfill_and_three_transient_failures_in_a_row_stop_it_too(env, monkeypatch):
    svc = Service(HISTORY, {"2003": 404})
    d = run(env, monkeypatch, svc, "--backfill")
    assert svc.asked == ["2001", "2002", "2003"]
    assert any("HTTP 404" in e for e in d["meta"]["lookup_errors"]) and d["meta"]["backfill"]["failed"] == ["2003"]
    assert d["ok"] and {r["started_at"][:4] for r in d["records"] if r.get("started_at")} >= {"2001", "2002"}
    svc = Service(HISTORY, {y: requests.ConnectionError("reset") for y in ("2003", "2004", "2005", "2006")})
    d = run(env, monkeypatch, svc, "--backfill")
    assert svc.asked == ["2003", "2004", "2005"]
    assert any("3 failures in a row" in e for e in d["meta"]["lookup_errors"])


def test_an_hourly_run_after_the_backfill_keeps_the_history_and_meta_and_never_reads_the_archive(env, monkeypatch):
    run(env, monkeypatch, Service(HISTORY), "--backfill")
    monkeypatch.setattr(M, "read_archive", lambda name: pytest.fail("the hourly run read the archive"))
    svc = Service(HISTORY)
    d = run(env, monkeypatch, svc)
    assert svc.asked == []
    assert d["meta"]["backfill"]["complete"] and d["meta"]["backfill"]["covered_from"] == 2001
    assert sum(1 for r in d["records"] if (r.get("started_at") or "").startswith("2001")) == 2


def test_older_shapes_and_personal_details_never_reach_the_archive_or_a_record(env, monkeypatch):
    by_year = {**HISTORY, 2002: HISTORY[2002] + [old_shape_row(2002)]}
    by_year[2003] = [{**r, "responsiblePartyName": "Pat Example", "siteName": "Pat Example"} for r in year_rows(2003, 1)]
    d = run(env, monkeypatch, Service(by_year), "--backfill")
    assert leaks(d) == []
    for p in (env / "archive").glob("*.json"):
        a = json.loads(p.read_text())
        assert leaks(a) == [] and all(set(r) <= set(M.FIELDS) for r in a["rows"]), p.name
    old = next(r for r in d["records"] if r["source_record_id"] == "-82002-1")
    assert old["npdes_permit"] == "MI0099001" and old["event_type"] == "sso" and old["status"] == "ended"
    assert old["ended_at"] is None and old["started_at"].startswith("2002-03-01")
    assert "contactName" not in old["raw"]


def test_the_hourly_run_keeps_completed_history_as_saved_and_rebuilds_it_when_the_rules_change(env, monkeypatch):
    """With the history on file the hourly run rebuilds only what it read (and open reports); a completed report it
    did not read is kept as saved, unless the module, the permit index or the name lists changed (build_stamp)."""
    run(env, monkeypatch, Service(HISTORY), "--backfill")
    before = json.loads((env / "events" / f"{M.SOURCE_ID}.json").read_text())["records"]
    built = []
    real = M.build_record
    monkeypatch.setattr(M, "build_record", lambda row, *a, **k: built.append(M.row_key(row)) or real(row, *a, **k))
    d = run(env, monkeypatch, Service(HISTORY))
    assert d["meta"]["kept_as_saved"] == 52 and len(built) == d["meta"]["rows_read"] < 10
    after = {r["event_id"]: r for r in d["records"]}
    for r in before:
        if r["raw"]["reportStatusId"] == "COMPLETE" and r["started_at"] and r["started_at"] < "2026-01-01":
            assert after[r["event_id"]] == r
    built.clear()
    monkeypatch.setattr(M, "permit_index", lambda rows=None: {**PERMITS, "MI0099009": "mi-another"})
    d = run(env, monkeypatch, Service(HISTORY))
    assert d["meta"]["kept_as_saved"] == 0 and len(built) >= d["count"]
    built.clear()
    d = run(env, monkeypatch, Service(HISTORY))
    assert d["meta"]["kept_as_saved"] == 52 and leaks(d) == []


def test_an_answer_of_exactly_top_rows_is_read_as_cut_short_and_the_year_halved(monkeypatch):
    """2006 answered exactly 5,000 rows, February to May, with hasResultsRemaining false: the year is halved."""
    asked = []

    class Sess:
        def get(self, url, params=None, timeout=None):
            flt = json.loads(params["queryParams"])["filter"][0]
            asked.append(flt)
            a, b = date.fromisoformat(flt["eventStartDateMin"]), date.fromisoformat(flt["eventStartDateMax"])
            n = 4 if (b - a).days > 200 else 2
            return Resp([{"submissionId": f"-6{len(asked)}{i}", "sectionNumber": 1} for i in range(n)])

    monkeypatch.setattr(M, "TOP", 4)
    monkeypatch.setattr(M.query, "__defaults__", (4, 300))
    got = M.query_window(Sess(), "COMPLETE", date(2006, 1, 1), date(2007, 1, 1))
    assert len(asked) == 3 and len(got) == 4


@pytest.mark.parametrize("given,gone,kept", [
    ("Robin Placeholder`s back yard", "Robin Placeholder", "back yard"),
    ("rear of Lee Placeholder's property near the ditch", "Lee Placeholder", "property near the ditch"),
    ("Mr. Placeholder’s lawn", "Placeholder", "lawn"),
    ("Sample Township's park lot", None, "Sample Township's park lot"),
    ("Resident's basement", None, "Resident's basement"),
    ("Homeowner's lawn", None, "Homeowner's lawn"),
])
def test_a_landowners_name_in_the_possessive_is_cut(given, gone, kept):
    """An older report names the land as "<given> <surname>`s back yard" (a backtick for the apostrophe)."""
    out = M.free_text(given)
    assert kept in out
    if gone:
        assert gone not in out and M.NAME_REMOVED in out
    else:
        assert out == given


# ---------------------------------------------------------------- review 2026-11-04: what rebuilds the kept records

def _kept(env, monkeypatch) -> int:
    return run(env, monkeypatch, Service(HISTORY))["meta"]["kept_as_saved"]


def test_a_changed_privacy_rule_file_or_name_list_rebuilds_every_kept_record(env, monkeypatch, tmp_path):
    """The records kept as saved get a new privacy rule: a change to redact.py, common.py, this module or a name list
    (data/build/name-blocklist.json, data/name-allowlist.json and the public data/name-blocklist.json the redaction
    also reads) rebuilds and redacts every record once."""
    from build import redact
    data, build_dir = tmp_path / "data", tmp_path / "build"
    data.mkdir()
    build_dir.mkdir()
    monkeypatch.setattr(M, "DATA_DIR", data)
    monkeypatch.setattr(M, "BUILD_DIR", build_dir)
    run(env, monkeypatch, Service(HISTORY), "--backfill")
    assert _kept(env, monkeypatch) == 52
    for f in (Path(redact.__file__), Path(common.__file__), Path(M.__file__)):
        copy = tmp_path / f"changed_{f.name}"
        copy.write_text(f.read_text() + "\n# a new rule\n")
        mod = {"redact.py": redact, "common.py": common, "mi_egle_mienviro.py": M}[f.name]
        monkeypatch.setattr(mod, "__file__", str(copy))
        assert _kept(env, monkeypatch) == 0, f.name
        assert _kept(env, monkeypatch) == 52, f.name
    for p in (build_dir / "name-blocklist.json", data / "name-allowlist.json", data / "name-blocklist.json"):
        p.write_text(json.dumps({"names": ["Robin Placeholder"]}))
        assert _kept(env, monkeypatch) == 0, p
        assert _kept(env, monkeypatch) == 52, p


def test_the_rules_stamp_is_saved_only_with_the_records_it_built(env, monkeypatch):
    """A run that changes the rules and stops before its records are written must not leave the new stamp: the next run
    would keep the old records as saved under rules they were not built with."""
    run(env, monkeypatch, Service(HISTORY), "--backfill")
    stamp = json.loads((env / "state.json").read_text())["build_stamp"]
    monkeypatch.setattr(M, "permit_index", lambda rows=None: {**PERMITS, "MI0099009": "mi-another"})

    def stop(*a, **k):
        raise KeyboardInterrupt("the runner stopped the job")
    monkeypatch.setattr(M, "write_events", stop)
    monkeypatch.setattr(M.requests, "Session", lambda: _Sess(Service(HISTORY)))
    monkeypatch.setattr(M, "datetime", _Clock)
    with pytest.raises(KeyboardInterrupt):
        M.main([])
    assert json.loads((env / "state.json").read_text())["build_stamp"] == stamp


def test_a_year_halved_after_the_budget_is_spent_is_not_asked_further_and_the_next_backfill_reads_it(env, monkeypatch):
    """The budget bounds the halves of a full year too: 2003 answers TOP rows when the time is nearly spent, so its
    halves are not asked for; it is named as not requested (not failed), and the next --backfill reads it."""
    monkeypatch.setattr(M, "TOP", 6)                          # over the fixture's three open reports
    monkeypatch.setattr(M.query, "__defaults__", (6, 300))
    t = {"now": 0}
    monkeypatch.setattr(M, "clock", lambda: t["now"])
    by_year = {**HISTORY, 2003: year_rows(2003, 6)}

    class Full(Service):
        def get(self, url, params=None, timeout=None):
            flt = json.loads(params["queryParams"])["filter"][0]
            lo, hi = flt.get("eventStartDateMin"), flt.get("eventStartDateMax")
            if lo and hi and lo.startswith("2003") and (date.fromisoformat(hi) - date.fromisoformat(lo)).days > 300:
                t["now"] = M.BACKFILL_BUDGET_S + 1             # the full answer comes back after the budget
            return super().get(url, params, timeout)
    svc = Full(by_year)
    d = run(env, monkeypatch, svc, "--backfill")
    b = d["meta"]["backfill"]
    assert svc.asked == ["2001", "2002", "2003"]               # no half of 2003, and no later year
    assert b["not_requested"][0] == "2003" and "2003" not in b["failed"] and not b["complete"]
    assert not (env / "archive" / "2003.json").exists()
    t["now"] = 0
    svc = Service(by_year)
    monkeypatch.setattr(M, "TOP", 5000)
    monkeypatch.setattr(M.query, "__defaults__", (5000, 300))
    d = run(env, monkeypatch, svc, "--backfill")
    assert svc.asked[0] == "2003" and d["meta"]["backfill"]["complete"]
    assert d["meta"]["backfill"]["rows_by_span"]["2003"] == 6
