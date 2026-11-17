"""The separate sewer rain caution's first real run (refresh 43970387446, 2026-11-16): "28 operators with reports, 28 read,
0 qualify", for two reasons not true of them. These tests use the shapes of the real inputs, not the seed's:

  events   each of the three sources' records made by its own ingester code (ingest/al_adem_sso.build on its fixture,
           ingest/fl_dep_pnp.build on its fixture, ingest/ct_deep.normalise on a dashboard row of the real raw shape),
           written with common.write_events and read back by the stage's own reader. None carries a top-level "state":
           Alabama's is raw.state, Connecticut's the permit's and source's prefix, Florida's the source's prefix.
  grades   data/build/coverage-grades.json as export/build.py writes it (rain_sso.write_grades from a coverage block),
           or absent, as on the first switched-on run (the export writes it after this stage).
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402
from build import rain_sso as SS  # noqa: E402
from build.rain_thresholds import ServiceRefused  # noqa: E402
from ingest import al_adem_sso as AL  # noqa: E402
from ingest import ct_deep as CT  # noqa: E402
from ingest import fl_dep_pnp as FL  # noqa: E402

from tests.test_rain_sso import DAILY, NOW, RULES, STORM_DAYS, TODAY  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
OPS = ["al-wet", "ct-wet", "fl-wet"]
SIDS = {"al-wet": "al-adem-sso-history", "ct-wet": "ct-deep", "fl-wet": "fl-dep-pnp"}
UNTIL = TODAY - timedelta(days=3)       # each source's newest report: three days ago, as on the first run


def rules_on(approved=OPS) -> dict:
    r = copy.deepcopy({"rain_likely": RULES["rain_likely"]})
    r["rain_likely"]["separate_sewers"].update(enabled=True, approved=list(approved))
    return r


# ---------------------------------------------------------------- one template record per source, by its own ingester

def al_template() -> dict:
    hist = AL.rows_of(json.loads((FIX / "al_adem" / "history.json").read_text()))
    live = AL.rows_of(json.loads((FIX / "al_adem" / "live.json").read_text()))
    recs, _ = AL.build(hist, live, "2026-11-07T14:00:00Z", [], True,
                       ops={"AL0042234": ("al-baldwin-county-sewer-service", "Baldwin County Sewer Service, LLC")})
    return next(r for r in recs if r["event_type"] == "sso" and r["time_precision"] == "minute"
                and r.get("npdes_permit") == "AL0042234")


def fl_template() -> dict:
    feats = [f["attributes"] for f in json.loads((FIX / "fl_dep_pnp_layer.json").read_text())["features"]]
    recs, _ = FL.build(feats, "2026-11-04T00:00:00Z", [], permits={"FL0031771": ("fl-test", "Test")})
    return next(r for r in recs if r["event_type"] == "sso" and r["time_precision"] == "day"
                and r["raw"].get("_pnp_kind") == "untreated")


CT_ROW = {"Reporting Utility": "WATERBURY WPCA", "Status": "Closed", "Incident Type": "Sewage Bypass",
          "Weather Conditions": "Rain", "Date Bypass Began or was Discovered": "11/13/2026", "Event Start Time": "05:45 PM",
          "Location of Bypass": "Manhole", "Type of Bypass": "Raw Sewage", "Cause of Bypass": "Rain",
          "Estimated Quantity or Rate of Discharge": "1,000 gallons", "Reach Waterbody": "No", "Request ID": "11674",
          "Waterbody Name": None, "Date Bypass Ended": "11/14/2026", "Event End Time": "01:00 AM",
          "Final Quantity": "1,000 gallons", "Municipality": "Waterbury"}


def ct_template() -> dict:
    r = CT.normalise("sso", dict(CT_ROW), "2026-11-16T12:00:00Z", NOW)
    r.pop("_key", None)         # the ingester's merge key, dropped before write_events (ct_deep.main)
    return r


def clones(tpl: dict, op: str, days, lat: float, lon: float) -> list[dict]:
    """The template's exact shape with only its values moved: one report per day given, at a point."""
    out = []
    for i, d in enumerate(days):
        r = copy.deepcopy(tpl)
        rid = f"{op}-{i}"
        r.update(source_record_id=rid, event_id=f"{r['source_id']}:{rid}", discharger_id=op, lat=lat, lon=lon,
                 started_at=f"{d.isoformat()}T08:00:00-05:00", ended_at=f"{d.isoformat()}T09:00:00-05:00",
                 reported_at=f"{(d + timedelta(days=1)).isoformat()}T08:00:00-05:00", duplicate_of=None,
                 water_slugs=[])
        out.append(r)
    return out


def rain_days_until(d):
    return [x for x in STORM_DAYS[::2] if x <= d]


def write_sources(folder: Path, until=UNTIL) -> dict[str, list[dict]]:
    """The three events files as the ingesters write them: rain-driven reports of each operator from 2023, and the
    source's newest report (another operator's, dry day) on `until`."""
    tpls = {"al-wet": al_template(), "ct-wet": ct_template(), "fl-wet": fl_template()}
    pts = {"al-wet": (33.84, -87.28), "ct-wet": (41.55, -73.04), "fl-wet": (27.95, -82.46)}
    files = {}
    for op, tpl in tpls.items():
        recs = clones(tpl, op, rain_days_until(until - timedelta(days=10)), *pts[op])
        recs += clones(tpl, f"{op[:2]}-someone-else", [until], *pts[op])
        files[SIDS[op]] = recs
        common.write_events(SIDS[op], recs, ok=True, meta={"registry_ids": []}, path=folder / f"{SIDS[op]}.json")
    return files


@pytest.fixture
def world(tmp_path, monkeypatch):
    ev = tmp_path / "events"
    ev.mkdir()
    monkeypatch.setattr(common, "EVENTS_DIR", ev)
    monkeypatch.setattr(SS, "GRADES_FILE", tmp_path / "coverage-grades.json")
    monkeypatch.setattr(SS, "LEVELS_BUILD", tmp_path / "rain-levels-sso.json")
    write_sources(ev)
    return tmp_path


def run(rules=None, **kw):
    kw.setdefault("prev", {})
    return SS.build(offline=kw.pop("offline", True), today=TODAY, now=NOW, rules=rules or rules_on(),
                    operator_of=lambda r: r.get("discharger_id"), placements={},
                    reader=kw.pop("reader", lambda *a: dict(DAILY)), have=kw.pop("have", lambda *a: True),
                    write=kw.pop("write", False), **kw)


# ---------------------------------------------------------------- fault 2: the state a source's records are from

def test_real_records_carry_no_top_level_state():
    for tpl in (al_template(), ct_template(), fl_template()):
        assert "state" not in tpl            # the shape the first run met: "newest_published_by_state" keyed by ""
    assert al_template()["raw"]["state"] == "AL" and "state" not in ct_template()["raw"]
    assert "state" not in fl_template()["raw"] and fl_template()["npdes_permit"] is None


def test_each_source_newest_report_is_keyed_by_the_records_own_state(world):
    d = run()
    for op, sid, st in (("al-wet", "al-adem-sso-history", "AL"), ("ct-wet", "ct-deep", "CT"),
                        ("fl-wet", "fl-dep-pnp", "FL")):
        src = d["sources"][sid]
        assert src["newest_published_by_state"] == {st: UNTIL.isoformat()}, sid
        e = d["operators"][op]
        assert e["state"] == st
        rc = e["recency"]
        assert rc["source"] == sid and rc["source_newest"] == UNTIL.isoformat() and rc["silent"] is False, op
        assert rc["in"] is True and not any("published no report" in w for w in e["why_not"]), op


# ---------------------------------------------------------------- fault 1: the grades on a first run and after

def test_first_run_with_no_grades_file_the_source_rule_decides_and_all_three_qualify(world):
    assert not (world / "coverage-grades.json").exists()
    d = run()
    for op in OPS:
        e = d["operators"][op]
        assert e["qualifies"] is True and e["why_not"] == [], (op, e["why_not"])
    assert d["state_grades_on_file"] is False
    assert d["counts"]["qualify"] == 3 and d["counts"]["qualify_by_state"] == {"AL": 1, "CT": 1, "FL": 1}
    assert all(src["excluded"] is None for src in d["sources"].values())


def test_grades_as_the_export_writes_them_are_read_by_state(world):
    cov = {"states": {"AL": {"grade": "Dated reports", "records_12m": 9}, "CT": {"grade": "Dated reports, delayed"},
                      "FL": {"grade": "Dated reports"}}}
    SS.write_grades(cov)                                    # export/build.py's own call
    assert SS.load_grades() == {"AL": "Dated reports", "CT": "Dated reports, delayed", "FL": "Dated reports"}
    d = run()
    assert d["state_grades_on_file"] is True and d["state_grades"] == {"AL": "Dated reports",
                                                                      "CT": "Dated reports, delayed",
                                                                      "FL": "Dated reports"}
    assert d["operators"]["al-wet"]["qualifies"] and d["operators"]["fl-wet"]["qualifies"]
    assert d["operators"]["ct-wet"]["why_not"] == ['its state\'s reports grade "Dated reports, delayed", not "Dated reports"']


def test_a_source_that_dates_few_reports_or_reports_late_is_left_out_in_true_words(world):
    cfg = SS.settings(rules_on())
    assert SS.source_timely({"records": 10, "dated_share": 0.6, "lag_days": 1}, cfg) == (
        "gives a date for 60 percent of its sewage reports of the last 12 months (more than 80 percent needed)")
    assert SS.source_timely({"records": 10, "dated_share": 0.8, "lag_days": 1}, cfg)          # 80 is not more than 80
    assert SS.source_timely({"records": 10, "dated_share": 1.0, "lag_days": 9.5}, cfg) == (
        "publishes its reports a median 9.5 days after the discharge (at most 7 days needed)")
    assert SS.source_timely({"records": 10, "dated_share": 1.0, "lag_days": None}, cfg) is None  # as the grade
    assert SS.source_timely({"records": 10, "dated_share": 1.0, "lag_days": 7}, cfg) is None
    assert SS.source_timely({"records": 0, "dated_share": None, "lag_days": None}, cfg) is None  # the silence rule's
    ev = common.EVENTS_DIR
    doc = json.loads((ev / "fl-dep-pnp.json").read_text())
    for r in doc["records"]:
        r["reported_at"] = (datetime.fromisoformat(r["started_at"]) + timedelta(days=30)).isoformat()
    (ev / "fl-dep-pnp.json").write_text(json.dumps(doc))
    d = run()
    e = d["operators"]["fl-wet"]
    assert e["qualifies"] is False and e["why_not"] == [
        "its source fl-dep-pnp publishes its reports a median 30 days after the discharge (at most 7 days needed)"]
    assert d["operators"]["al-wet"]["qualifies"] is True


# ---------------------------------------------------------------- a missing input stops the stage

def test_no_events_stops_the_stage_and_writes_nothing(tmp_path, monkeypatch, capsys):
    ev = tmp_path / "events"
    ev.mkdir()
    monkeypatch.setattr(common, "EVENTS_DIR", ev)
    monkeypatch.setattr(SS, "LEVELS_BUILD", tmp_path / "rain-levels-sso.json")
    with pytest.raises(SS.MissingInput, match="no events file"):
        run(write=True)
    monkeypatch.setattr(SS, "read_json", lambda p, d=None: rules_on() if p.name == "rules.json" else common.read_json(p, d))
    assert SS.main(["--offline"]) == 1
    assert "rain_sso: stopped: no events file with records; nothing written" in capsys.readouterr().out
    assert not (tmp_path / "rain-levels-sso.json").exists()


def test_approved_operators_absent_from_the_events_stop_the_stage(world):
    with pytest.raises(SS.MissingInput, match="none of the 2 approved operators"):
        run(rules=rules_on(["al-nobody", "ct-nobody"]))


def test_the_hourly_check_with_no_grades_file_keeps_the_daily_verdict_and_says_so(world):
    from tests.test_rain_sso import WATERS, rain_for, storm
    d = run()
    rain = rain_for(storm(range(0, 6), 1.2), key="sso:al-wet")
    _, _, blk = SS.compute(rain, rules_on(), [], NOW, NOW - timedelta(days=30), WATERS, {}, lambda r, w: [], {}, d, None)
    assert set(blk["operators"]) == set(OPS)
    assert any("no state grades file" in p for p in blk["problems"])
    _, _, blk2 = SS.compute(rain, rules_on(), [], NOW, NOW - timedelta(days=30), WATERS, {}, lambda r, w: [], {}, d,
                            {"AL": "Dated reports, delayed", "CT": "Dated reports", "FL": "Dated reports"})
    assert set(blk2["operators"]) == {"ct-wet", "fl-wet"} and not blk2["problems"]
    assert blk2["not_covered"]["al-wet"]["why_not"][-1].startswith("its state's reports grade")


# ---------------------------------------------------------------- the part-way refusal

def test_a_refusal_part_way_keeps_the_unread_operators_previous_entries(world):
    full = run()
    calls = []

    def reader(lat, lon, years, offline, budget):
        calls.append((lat, lon))
        if len(calls) > 1:
            raise ServiceRefused("429")
        return dict(DAILY)
    d = run(reader=reader, have=lambda *a: False, prev=full, offline=False)
    assert d["run"]["stopped"].startswith("ServiceRefused at ct-wet")
    assert d["operators"]["al-wet"].get("carried") is None and d["operators"]["al-wet"]["qualifies"] is True
    for op in ("ct-wet", "fl-wet"):
        e = d["operators"][op]
        assert e["carried"]["from"] == full["built"] and e["qualifies"] is True
        assert {k: v for k, v in e.items() if k != "carried"} == full["operators"][op]
    assert d["counts"]["carried"] == 2 and d["counts"]["qualify"] == 3 and d["counts"]["read"] == 1
    # with no previous entry it says so, and never qualifies
    calls.append("again")
    d2 = run(reader=reader, have=lambda *a: False, prev={}, offline=False)
    assert d2["operators"]["fl-wet"]["why_not"] == ["the rain record for this operator has not been read yet"]


def test_a_pass_that_stopped_runs_again_the_next_hour(world, monkeypatch, capsys):
    rules = rules_on()
    monkeypatch.setattr(SS, "read_json", lambda p, d=None: rules if p.name == "rules.json" else common.read_json(p, d))
    path = world / "rain-levels-sso.json"
    built = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps({"method_version": SS.METHOD_VERSION, "built": built, "operators": {},
                                "run": {"stopped": "ServiceRefused at ct-wet: 429"}, "counts": {"carried": 2}}))
    calls = []
    monkeypatch.setattr(SS, "build", lambda **kw: calls.append(kw) or {
        "counts": {"operators": 3, "read": 3, "qualify": 3, "qualify_by_state": {}, "carried": 0},
        "run": {"requests": 0, "stopped": None}, "state_grades_on_file": True})
    assert SS.main(["--if-older-h", "20"]) == 0 and len(calls) == 1
    # the first run's file (no revision, nobody qualified), built an hour ago: rebuilt at once, not kept 20 hours
    path.write_text(json.dumps({"method_version": SS.METHOD_VERSION, "built": built, "operators": {},
                                "run": {"stopped": None}, "counts": {"carried": 0, "qualify": 0}}))
    assert SS.main(["--if-older-h", "20"]) == 0 and len(calls) == 2
    path.write_text(json.dumps({"method_version": SS.METHOD_VERSION, "revision": SS.FILE_REVISION, "built": built,
                                "operators": {}, "run": {"stopped": None}, "counts": {"carried": 0}}))
    assert SS.main(["--if-older-h", "20"]) == 0 and len(calls) == 2          # a complete pass: left alone 20 hours
    assert "younger than 20 hours" in capsys.readouterr().out


# ---------------------------------------------------------------- the reasons printed on operator pages

def test_an_unusable_history_gives_its_reason_not_none():
    """The chain check on real-shaped inputs (2026-11-16) printed "no usable history: None" for two Connecticut
    operators: the reason was read after it had been moved to history_why_not."""
    tpl = al_template()
    recs = clones(tpl, "al-few", rain_days_until(UNTIL)[-5:], 33.84, -87.28)
    d = SS.build(offline=True, today=TODAY, now=NOW, sources=[("al-adem-sso-history", recs)], rules=rules_on(["al-few"]),
                 operator_of=lambda r: r.get("discharger_id"), placements={}, reader=lambda *a: dict(DAILY),
                 have=lambda *a: True, grades={}, prev={}, write=False)
    e = d["operators"]["al-few"]
    assert e["read"] is True and e["usable"] is False and e["history_why_not"]
    assert e["why_not"][0] == f"no usable history: {e['history_why_not']}"
    assert not any("None" in w for w in e["why_not"])


def test_a_late_annual_source_beside_a_prompt_one_stays_in_the_history(world):
    """Connecticut: the dashboard (ct-deep) is prompt, the annual workbook (ct-deep-annual, made by its own
    make_record) is published months later. Its dated reports count in the history; the prompt source carries the
    caution. Alone, the late source gives no caution, and says why."""
    from collections import Counter
    from ingest import ct_deep_annual as CA
    ann = CA.make_record("sso", dict(CT_ROW), dict(CT_ROW), 2, "2026-sso-bypass.xlsx", "SSO", 2025,
                         "2026-02-25T21:08:59Z", "2026-11-16T08:00:00Z", NOW, set(), Counter())
    assert ann["source_id"] == "ct-deep-annual" and "state" not in ann and ann["published_at"]
    days = rain_days_until(UNTIL - timedelta(days=10))
    recs = clones(ann, "ct-wet", days[len(days) // 2:], 41.55, -73.04)
    for r in recs:      # the workbook's publication date, months after each report (as in the real file: 86 days)
        r["reported_at"] = None
        r["published_at"] = (datetime.fromisoformat(r["started_at"]) + timedelta(days=90)).isoformat()
    common.write_events("ct-deep-annual", recs, ok=True, path=common.EVENTS_DIR / "ct-deep-annual.json")
    d = run()
    e = d["operators"]["ct-wet"]
    assert e["sources"] == ["ct-deep", "ct-deep-annual"] and e["qualifies"] is True
    assert set(e["late_sources"]) == {"ct-deep-annual"}
    assert e["reports"] == len(recs) + len(clones(ct_template(), "x", days, 0, 0))
    (common.EVENTS_DIR / "ct-deep.json").unlink()
    d2 = run()
    e2 = d2["operators"]["ct-wet"]
    assert e2["qualifies"] is False and e2["why_not"][0].startswith(
        "its source ct-deep-annual publishes its reports a median ")


def test_an_entry_with_no_source_date_is_not_said_to_have_a_silent_source():
    cfg = SS.settings(rules_on())
    e = {"recency": {"source": "ct-deep", "source_newest": None}}
    assert SS.too_old(e, cfg, TODAY) == "the date of its source's newest report is not on file"
    assert SS.too_old({"recency": {"source": "ct-deep", "source_newest": "2025-10-01"}}, cfg, TODAY).startswith(
        "its source ct-deep has published no report in the last 12 months (newest 2025-10-01)")
