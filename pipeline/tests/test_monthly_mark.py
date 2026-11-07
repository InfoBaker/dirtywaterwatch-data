"""docs/plan.md §2.x: the "monthly" mark for month-precision reports (EPA's monthly DMR totals) and the rain-likely
caution in the 90-day history. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from export import build as X  # noqa: E402
from tests.test_status import TEST_RULES, ev, iso, tmp_events, world  # noqa: E402

H = timedelta(hours=1)
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _rules(monkeypatch):
    monkeypatch.setattr(S, "_RULES", TEST_RULES)


def month_rec(rid, month, days=4, outfall="002", **kw):
    y, m = (int(x) for x in month.split("-"))
    last = (datetime(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    kw.setdefault("source_id", "nj-echo-monthly")
    kw.setdefault("volume_text", f"{days} day{'' if days == 1 else 's'} with discharge in {month} (MO TOTAL)")
    return ev(rid, status="ended", npdes_permit="MA0025321", outfall_id=outfall, started_at=f"{month}-01",
              ended_at=f"{month}-{last:02d}", time_precision="month", reported_at=kw.pop("reported_at", f"{month}-26"),
              fetched_at="2026-11-03T10:00:00Z", **kw)


def hour_index(hist, t):
    return int((t - S.parse_time(hist["start"])).total_seconds() // 3600)


def test_the_mark_reads_days_events_and_volumes_and_says_when_the_report_was_received():
    m = S.monthly_mark(month_rec("a", "2026-09", days=4, reported_at="2026-10-26"))
    assert (m["month"], m["days"], m["discharged"]) == ("2026-09", 4, True)
    assert m["label"] == ("4 days with discharge reported for September 2026; dates not given (monthly report to EPA, "
                          "received Oct 26, 2026)")
    assert m["received_at"] == "2026-10-26T04:00:00Z" and m["retrieved_at"] == "2026-11-03T10:00:00Z"
    assert m["start"] == datetime(2026, 9, 1, 4, tzinfo=UTC) and m["end"] == datetime(2026, 10, 1, 4, tzinfo=UTC)
    one = S.monthly_mark(month_rec("b", "2026-09", days=1))
    assert one["label"].startswith("1 day with discharge reported for September 2026")
    dmr = S.monthly_mark(month_rec("c", "2026-09", source_id="echo-cso-dmr-monthly",
                                   volume_text="2 discharge event(s); 5.75 hr/mo of discharge; 357,680 gallons",
                                   volume_gal=357680))
    assert dmr["days"] is None and dmr["events"] == 2 and dmr["label"].startswith("2 discharge events reported for")
    assert not S.monthly_mark(month_rec("d", "2026-09", days=0))["discharged"]
    assert not S.monthly_mark(month_rec("e", "2026-09", volume_text="0 discharge event(s); NODI duration")) ["discharged"]
    nh = S.monthly_mark(month_rec("f", "2010-01", source_id="nh-permittees", volume_text="0.5490 MG", volume_gal=549000,
                                  reported_at=None))
    # no receipt date in the source: the label says so, and the fetch time stays apart (review SOL P1-5)
    assert nh["discharged"] and nh["label"].endswith("(0.5490 MG); dates not given (monthly report, receipt date not given)")
    assert nh["received_at"] is None and nh["retrieved_at"] == "2026-11-03T10:00:00Z" and nh["published_at"] is None
    assert S.monthly_mark(ev("g", status="ended", started_at="2026-09-01")) is None           # not month precision
    assert S.monthly_mark(month_rec("h", "2025-01", event_type="annual_total")) is None


def test_a_monthly_report_marks_its_month_in_the_history_and_the_water_while_it_is_the_latest():
    sep = month_rec("sep", "2026-09", days=4)
    aug = month_rec("aug", "2026-08", days=2)
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([sep, aug])))
    w = st["waters"]["test-river-ma"]
    assert w["status"] == "monthly" and w["since"] == "2026-09-01T04:00:00Z"
    r = w["reasons"][0]
    assert r["event_id"] == sep["event_id"] and r["status"] == "monthly" and r["rule"] == "monthly"
    assert (r["days"], r["month"], r["received_at"]) == (4, "2026-09", "2026-09-26T04:00:00Z")
    assert r["short"].startswith("4 days with discharge reported for September 2026")
    assert [m["event_id"] for m in st["monthly_outfalls"]] == [sep["event_id"]]
    assert st["monthly_outfalls"][0]["outfall_id"] == "002" and st["counts"]["monthly_outfalls"] == 1
    strip = hist["waters"]["test-river-ma"]
    assert strip[hour_index(hist, datetime(2026, 9, 15, tzinfo=UTC))] == "m"
    assert strip[hour_index(hist, datetime(2026, 8, 20, tzinfo=UTC))] == "m"
    assert strip[hour_index(hist, datetime(2026, 10, 15, tzinfo=UTC))] == "g"            # no October report
    assert strip[hour_index(hist, datetime(2026, 9, 1, 3, tzinfo=UTC))] == "m"            # Aug 31, 23:00 local
    assert strip[hour_index(hist, datetime(2026, 10, 1, 4, tzinfo=UTC))] == "g"           # Oct 1, 00:00 local
    assert st["legend"]["m"].startswith("monthly report") and S.RANK["unresolved"] > S.RANK["monthly"] > S.RANK["grey"]
    assert "reach" not in st["placements"][sep["event_id"]] and st["needs_reach"] == []   # never a reach


def test_a_newer_report_of_no_discharge_ends_the_current_mark_and_red_wins():
    sep = month_rec("sep", "2026-09", days=4)
    octo = month_rec("oct", "2026-10", days=0)
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([sep, octo])))
    assert st["waters"]["test-river-ma"]["status"] == "grey" and st["monthly_outfalls"] == []
    assert hist["waters"]["test-river-ma"][hour_index(hist, datetime(2026, 9, 15, tzinfo=UTC))] == "m"
    # another outfall's report keeps its own mark; an old report (its month ended over 90 days ago) none
    other = month_rec("other", "2026-09", days=3, outfall="003")
    old = month_rec("old", "2026-06", days=5, outfall="004")
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([sep, octo, other, old])))
    assert [m["event_id"] for m in st["monthly_outfalls"]] == [other["event_id"]]
    # a discharge with a red window outranks the mark, now and in the history
    red = ev("red", status="ongoing", started_at=iso(datetime(2026, 9, 14, tzinfo=UTC)))
    live = ev("live", status="ongoing", started_at=iso(NOW - 2 * H))
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([sep, red, live])))
    assert st["waters"]["test-river-ma"]["status"] == "red"
    assert all(r["status"] != "monthly" for r in st["waters"]["test-river-ma"]["reasons"])
    strip = hist["waters"]["test-river-ma"]
    assert strip[hour_index(hist, datetime(2026, 9, 15, tzinfo=UTC))] == "r"
    assert strip[hour_index(hist, datetime(2026, 9, 5, tzinfo=UTC))] == "m"


def test_the_export_writes_the_mark_on_the_outline_and_the_outfall_points(tmp_path):
    w = {"status": "monthly", "reasons": [
        {"rule": "monthly", "month": "2026-08", "days": 2, "received_at": "a", "monthly_label": "2 days ..."},
        {"rule": "monthly", "month": "2026-09", "days": 4, "received_at": "b", "monthly_label": "4 days ..."}]}
    assert X.monthly_props(w) == {"days": 4, "month": "2026-09", "received_at": "b", "label": "4 days ...",
                                  "monthly_reports": 2}
    assert X.monthly_props({"status": "grey", "reasons": []}) == {}
    assert X.STATUS_ORDER["unresolved"] < X.STATUS_ORDER["monthly"] < X.STATUS_ORDER["grey"]
    src = Path(X.__file__).read_text()
    assert '"status": w["status"] if w.get("fill", True) or w["status"] == "monthly" else "grey"' in src
    assert 'OUT_DIR / "monthly-outfalls.json"' in src
    # the export (export/outfalls.py; scripts/export-outfalls.py rewrites it from disk) merges the marks into
    # out/outfalls.json, adding an outfall the registries lack
    from export import outfalls as XO
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "outfalls-new-england.json").write_text(json.dumps({"outfalls": [
        {"npdes_permit": "MA0101613", "outfall": "013", "water_slug": "test-river-ma", "lat": 42.0, "lon": -72.0}]}))
    from common import load_outfall_registry
    marks = [{"npdes_permit": "MA0101613", "outfall_id": "13", "status": "monthly", "days": 4, "month": "2026-09",
              "received_at": "x", "label": "4 days with discharge reported for September 2026", "event_id": "e1"},
             {"npdes_permit": "NJ0025321", "outfall_id": "002", "status": "monthly", "days": 1, "month": "2026-09",
              "received_at": "y", "label": "1 day ...", "event_id": "e2", "water_slugs": ["hudson-river-nj"],
              "lat": 40.78, "lon": -73.99, "source_id": "nj-echo-monthly"}]
    out = XO.outfall_rows(load_outfall_registry(tmp_path / "data"), {"MA", "NJ"}, marks=marks)
    XO.write(out, tmp_path / "out", "t")
    rows = {(r["npdes_permit"], r["outfall_id"]): r for r in json.loads((tmp_path / "out" / "outfalls.json").read_text())["outfalls"]}
    assert rows[("MA0101613", "013")]["status"] == "monthly" and rows[("MA0101613", "013")]["days"] == 4
    nj = rows[("NJ0025321", "002")]
    assert nj["status"] == "monthly" and nj["water_slugs"] == ["hudson-river-nj"] and nj["lat"] == 40.78
    # the script the upload runs is a shim over the same module
    assert "from export import outfalls" in (Path(X.ROOT) / "scripts" / "export-outfalls.py").read_text()


# ---------------------------------------------------------------- the rain-likely caution in the replay

def test_a_past_rain_likely_episode_is_in_the_90_day_history_of_the_waters_and_the_reach():
    from tests import test_rain_likely as T
    vals = {b: 0.0 for b in range(0, 2000)}
    for b in range(960, 970):                     # a storm 40 days back, the 24-hour total over the threshold
        vals[b] = 1.2
    st, hist = S.build(now=T.NOW, write=False, **T.rain_world(values=vals))
    assert st["waters"]["other-pond-ma"]["status"] == "grey"                       # long over now
    i0 = hour_index(hist, T.NOW - 969 * H)
    strip = hist["waters"]["other-pond-ma"]
    assert strip[i0 - 1] == "g" and strip[i0:i0 + 10 + 48] == "y" * 58 and strip[i0 + 58] == "g"   # 48 h tail
    ivs = [iv for iv in hist["intervals"]["other-pond-ma"] if iv[3] == "rain_likely"]
    assert len(ivs) == 1 and ivs[0][4].startswith(f"rain_likely:{T.PERMIT}:")
    assert any(iv[3] == "rain_likely" for iv in hist["reach_intervals"]["MA0101613-13"])
    assert "y" in hist["reaches"]["MA0101613-13"]
