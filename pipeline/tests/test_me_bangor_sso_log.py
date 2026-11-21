"""ingest/me_bangor_sso_log.py: Bangor's SSO Event Log, 2016 to 2024, from the two-reading transcription.

Run from pipeline/:  python -m pytest tests/test_me_bangor_sso_log.py -q
"""
from __future__ import annotations

import json

import requests

import common
from build import charts
from ingest import me_bangor_sso_log as m


def recs() -> dict[str, dict]:
    out, _ = m.records_from(m.REFERENCE.read_text(), m.bangor_waters())
    return {r["event_id"].split(":", 1)[1]: r for r in out}


def test_every_row_once_placed_only_on_a_water_the_log_names():
    out, counts = m.records_from(m.REFERENCE.read_text(), m.bangor_waters())
    assert len(out) == 72 == len({r["event_id"] for r in out}) == counts["rows"]
    by_year = {}
    for r in out:
        by_year[r["raw"]["report_year"]] = by_year.get(r["raw"]["report_year"], 0) + 1
    assert by_year == {2016: 11, 2017: 4, 2018: 10, 2019: 5, 2020: 5, 2021: 11, 2022: 7, 2023: 9, 2024: 10}
    assert all(r["npdes_permit"] == "ME0100781" and r["discharger_id"] == "me-bangor" and r["event_type"] == "sso"
               for r in out)
    # nothing is geocoded and the location column is never carried
    assert all(r["lat"] is None and r["lon"] is None for r in out)
    assert not any(k.lower().startswith(("location", "address")) for r in out for k in r["raw"])
    assert {s for r in out for s in r["water_slugs"]} == {"penobscot-river-me", "kenduskeag-stream-me"}
    assert sorted(counts["water_without_record"]) == ["Birch Stream", "Penjajawoc Stream"]
    assert (counts["with_water"], counts["no_water"], counts["open"]) == (15, 49, 8)


def test_the_disposition_decides_the_water_and_whether_any_was_reached():
    r = recs()
    assert r["2022:22-05"]["water_slugs"] == ["kenduskeag-stream-me", "penobscot-river-me"]
    assert r["2024:24-9"]["water_slugs"] == ["penobscot-river-me"] and r["2024:24-9"]["water_match"] == "name"
    # "possibly reaching" still places it, and says so
    assert r["2018:18-03"]["water_slugs"] == ["penobscot-river-me"] and r["2018:18-03"]["raw"]["possibly"] is True
    # a water with no record is named but not placed
    assert r["2024:24-06"]["waterbody_text"] == "Birch Stream" and r["2024:24-06"]["water_slugs"] == []
    # the ground alone, a basement, back into the system: the log's words are the reason no water was reached
    for k in ("2024:24-01", "2024:24-03", "2020:20-01", "2017:17-01", "2020:20-03", "2020:20-04"):
        assert r[k]["raw"]["reached_water"] is False and r[k]["raw"]["final_disposition"] in r[k]["raw"]["_no_water_reason"]
    # a storm drain, a ditch or an unnamed stream stays open
    for k in ("2017:17-02", "2021:21-10", "2018:18-04", "2016:16-10"):
        assert "reached_water" not in r[k]["raw"] and r[k]["water_slugs"] == []


def test_dates_as_printed_and_the_two_that_cannot_be_read_as_printed():
    r = recs()
    a = r["2016:16-01"]
    assert (a["started_at"], a["time_precision"], a["ended_at"], a["status"]) == ("2016-01-10T22:30-05:00", "minute", None, "unknown")
    b = r["2016:16-10"]
    assert (b["started_at"], b["ended_at"]) == ("2016-11-28T16:03-05:00", "2016-11-29T02:30-05:00")
    c = r["2022:22-05"]
    assert (c["started_at"], c["ended_at"], c["raw"]["reported_or_discovered_through"]) == ("2022-10-14", "2022-10-19", "10/19/2022")
    # 4/6/2022 in the 2021 log (issued January 2022) is read in 2021
    d = r["2021:21-01"]
    assert (d["started_at"], d["ended_at"], d["raw"]["date_as_printed"]) == ("2021-03-30", "2021-04-06", {"stopped": "4/6/2022"})
    # 8/34/17 is not a date: dated by the time stopped, and the record says so
    e = r["2017:17-03"]
    assert (e["started_at"], e["ended_at"]) == ("2017-08-23", "2017-08-23")
    assert "8/34/17" in e["raw"]["not_a_date"]["reported_or_discovered"] and "dated by the time stopped" in e["raw"]["notes"][0]
    f = r["2023:23-07"]
    assert f["ended_at"] == "2023-10-08" and "17" in f["raw"]["duration_as_printed"]
    assert r["2024:24-06"]["ended_at"] == "2024-06-10" and r["2024:24-06"]["published_at"] == "2025-01-31"
    assert r["2020:20-02"]["published_at"] is None          # the 2020 report prints no date the text gives


def test_only_one_number_is_a_volume():
    assert m.gallons("1,200 Gallons") == (1200, "unknown")
    assert m.gallons("5,000 gallons/ visual estimate") == (5000, "estimated")
    assert m.gallons("3000 gal / visual evidence") == (3000, "estimated")
    for t in ("<99,970", "50 -100 gallons/ visual estimate", "Minimal", "Trace/ on site observation", "Unknown",
              "returned to system", "<150,000 Gallons measured at DB Regulator Structure.", ""):
        assert m.gallons(t)[0] is None, t


class Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def page(links: dict[int, int]) -> str:
    return "".join(f'<a href="/DocumentCenter/View/{i}/Annual-Report-on-Compliance-Calendar-Year-{y}">{y}</a>'
                   for y, i in links.items())


def test_a_new_or_moved_report_is_named_for_transcription(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    listed = {y: i for y, (i, _) in m.REPORTS.items()} | {2025: 4000}
    listed[2024] = 3999
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: Resp(page(listed)))
    assert m.main([]) == 0
    out = json.loads((tmp_path / "events" / f"{m.SOURCE_ID}.json").read_text())
    assert out["ok"] is True and out["count"] == 72
    assert [(u["year"], u["why"]) for u in out["meta"]["unread_reports"]] == [(2024, "its link changed"), (2025, "not transcribed")]


def test_an_unreadable_page_keeps_the_records_and_shows_the_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")

    def boom(*a, **k):
        raise requests.ConnectionError("simulated outage")
    monkeypatch.setattr(m.requests, "get", boom)
    assert m.main([]) == 1
    out = json.loads((tmp_path / "events" / f"{m.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and out["count"] == 72 and "report page" in out["error"]


def test_a_page_that_lists_no_report_is_a_failed_check(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: Resp("<html>Site maintenance in progress</html>"))
    assert m.main([]) == 1
    out = json.loads((tmp_path / "events" / f"{m.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and out["count"] == 72 and "lists no Annual Report" in out["error"]


def test_the_charts_name_the_source():
    assert "Bangor" in charts.SOURCE_LABEL[m.SOURCE_ID] and "{first}" in charts.SOURCE_NOTES[m.SOURCE_ID]["events"]
