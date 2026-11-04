"""Pennsylvania ingesters: ALCOSAN's hand-typed log, its news posts, Erie's report, the CSOcast state
machine, PA DOH HAB episodes and Erie County beach rows (no network)."""
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from ingest import pa_alcosan as A
from ingest import pa_erie as E
from ingest import pa_habs_beaches as H
from ingest import pa_phila_csocast as C

RAW = Path(__file__).resolve().parents[2] / "research" / "pa" / "raw"


def _t(s, alert):
    dt, fixes, prob = A.parse_log_time(s, date.fromisoformat(alert))
    return (dt.isoformat() if dt else None), fixes, prob


def test_alcosan_lenient_times():
    assert _t("10/14/2026 - 09:09 AM", "2026-10-14")[0] == "2026-10-14T09:09:00-04:00"
    assert _t("08/20/205 - 03:40 AM", "2025-08-20")[0] == "2025-08-20T03:40:00-04:00"
    assert _t("06/22/2016 - 10:29 AM", "2026-06-22")[0] == "2026-06-22T10:29:00-04:00"
    assert _t("04.29/2026 - 04:45 PM", "2026-04-29")[0] == "2026-04-29T16:45:00-04:00"
    assert _t("08/17:2025 - 12:56 PM", "2025-08-17")[0] == "2025-08-17T12:56:00-04:00"
    assert _t("09/25/2025 - 12: 15 PM", "2025-09-25")[0] == "2025-09-25T12:15:00-04:00"
    assert _t("04/02/2026 - 01:18AM", "2026-04-02")[0] == "2026-04-02T01:18:00-04:00"
    v, fixes, _ = _t("05/27/2026 - 07:33 AN", "2026-05-29")
    assert v == "2026-05-27T07:33:00-04:00" and any("AM" in f for f in fixes)
    assert _t("9/3/26 - 6:30", "2026-09-03")[0] is None                      # no AM/PM
    assert "AM/PM" in _t("09/27/2025 - 12:15 Apm", "2025-09-27")[2]
    assert "30 days before" in _t("06/18/2026 - 03:10 PM", "2026-07-18")[2]  # month typo: not used


def test_alcosan_page_parse():
    p = RAW / "alcosan-soak.html"
    if not p.exists():
        pytest.skip("research copy missing")
    rows = A.parse_log_page(p.read_text(errors="replace"))
    assert len(rows) == 5
    assert rows[0]["status"].startswith("System is in dry weather operation")
    assert (rows[0]["in"], rows[0]["out"], rows[0]["dry"]) == ("10/14/2026 - 09:09 AM", "10/14/2026 - 09:32 AM",
                                                              "10/16/2026 - 09:32 AM")
    assert rows[2]["out"] is None and A.stage_of(rows[2]["status"]) == "effect"


def test_alcosan_periods_from_research_log():
    p = RAW / "alcosan-soak-log-parsed.json"
    if not p.exists():
        pytest.skip("research copy missing")
    rows = json.loads(p.read_text())
    for k, r in enumerate(rows):
        r["_pos"] = -k
    w = {"slugs": ["allegheny-river-pa", "monongahela-river-pa", "ohio-river-pa"], "missing": []}
    recs = [A.period_record(items, w) for items in A.group_periods(rows)]
    by = {r["source_record_id"]: r for r in recs}
    assert len(recs) == 82 and len(by) == 82
    r = by["soak-20260718T1510"]   # the "06/18" typo joins its period, the period keeps 07/18
    assert len(r["raw"]["entries"]) == 3 and r["ended_at"] == "2026-07-18T16:40:00-04:00" and not r["parse_error"]
    r = by["soak-20260903T1830"]   # "9/3/26 - 6:30" (no AM/PM) joins by clock time
    assert len(r["raw"]["entries"]) == 3 and r["status"] == "ended"
    assert "disagree" in by["soak-20260622T0918"]["parse_error"]
    assert all(r["water_match"] == "inferred" and r["advice_window_hours"] == 48 for r in recs)
    assert A.bound_unclosed(recs) == 3
    r = by["soak-20260418T1821"]   # "in effect" never followed by its own "ceased"
    assert r["status"] == "ended" and r["ended_at"] is None and r["time_precision"] == "bound"
    assert r["raw"]["_ended_before"] == "2026-04-19T06:21:00-04:00"


def test_alcosan_news():
    text = ("The Allegheny County Sanitary Authority (ALCOSAN) is advising the public to stay out of area waterways "
            "for 48 hours, following a full power outage at the wastewater treatment plant that occurred between "
            "6 – 8 p.m. this evening. ALCOSAN was unable to process wastewater, causing the plant’s wet well "
            "filled to capacity. As with other overflow events, this resulted in a discharge into the river.")
    a, b, _ = A.post_times(text, datetime(2026, 3, 6, 23, 0, tzinfo=A.TZ))
    assert (a.isoformat(), b.isoformat()) == ("2026-03-06T18:00:00-05:00", "2026-03-06T20:00:00-05:00")
    assert A.classify(text)[0] == "bypass"
    assert A.classify("A CSO event caused a structure near the 10th Street Bypass to stick open.")[0] == "unknown"
    assert A.classify("A sanitary sewer overflow occurred on Main St.")[0] == "sso"
    u1 = "https://www.alcosan.org/news-and-events/featured-news/news/2026/03/07/advisory"
    posts = {u1: {"url": u1, "title": "Advisory Issued", "posted_at": "2026-03-06T23:00:00-05:00", "links": [], "text": text},
             "u2": {"url": "u2", "title": "Advisory Lifted;", "posted_at": "2026-03-10T07:18:00-04:00", "links": [u1],
                    "text": "The advisory has been lifted. It resulted in an estimated 20-million-gallon discharge in the river."},
             "u3": {"url": "u3", "title": "Update on March 6th Power Outage", "posted_at": "2026-03-12T16:53:00-04:00",
                    "links": [], "text": "We continue to review."}}
    incs = A.group_incidents(posts)
    assert len(incs) == 1 and len(incs[0]) == 3
    r = A.incident_record(incs[0], {"slugs": ["ohio-river-pa"], "missing": []})
    assert r["event_type"] == "bypass" and r["status"] == "ended" and r["volume_gal"] == 20_000_000
    assert r["advice_window_hours"] == 48 and r["estimate_flag"] == "estimated"


def test_erie_report_and_map():
    rp, mp = RAW / "erie-telog-report-2025.html", RAW / "erie-telog-map.html"
    if not (rp.exists() and mp.exists()):
        pytest.skip("research copy missing")
    markers = E.parse_map(mp.read_text())
    assert set(markers) == {"294142", "295559", "294143", "292962"}
    rows = E.parse_report(rp.read_text())
    assert len(rows) == 22
    r = E.to_record(rows[0], markers, "u")
    assert r["event_type"] == "cso" and r["status"] == "ended" and r["outfall_id"] == "014"
    assert r["started_at"] == "2025-04-02T13:55:00-04:00" and r["volume_gal"] is None
    assert r["volume_text"].startswith("0.00069 ") and "unconfirmed" in r["volume_text"]
    assert r["water_slugs"] == ["lake-erie-pa"] and r["raw"]["water_placement"]["without_water_record"] == ["Mill Creek"]
    assert r["advice_window_hours"] is None


def _snap(msg, ms, name="D_02"):
    return [{"Name": name, "Status": 1, "Status_Message": msg, "LastPoll": ms, "Latitude": 39.97, "Longitude": -75.13,
             "Interceptor": "X", "Waterbody": "D", "Street": "Somewhere St"}]


def test_csocast_last_poll_is_local_time():
    assert C.last_poll(1793606250000).isoformat() == "2026-11-02T07:57:30-05:00"


def _rec(st, key, name="D_02", t0=1_790_000_000_000):
    return C.to_record(key, st["events"][key], {"attributes": _snap("x", t0, name)[0], "place": {}})


def test_csocast_open_continue_close_reappear():
    st = {}
    h = 3_600_000
    t0 = 1_790_000_000_000
    lp = lambda k: C.iso(C.last_poll(t0 + k * h))
    C.poll(st, _snap("No overflow in the past 72 hours.", t0), "2026-09-21T16:00:00Z")
    assert st["events"] == {}
    # open: the first poll that says overflowing; started_at is that poll's LastPoll
    C.poll(st, _snap("Currently overflowing.", t0 + h), "2026-09-21T17:00:00Z")
    (key, ev), = st["events"].items()
    assert ev["state"] == "ongoing" and ev["started_at"] == lp(1) and ev["started_after"] == lp(0)
    r = _rec(st, key)
    assert r["status"] == "ongoing" and r["started_at"] == lp(1) and r["ended_at"] is None
    assert r["time_precision"] == "poll" and "not a measured or reported discharge" in r["raw"]["status_basis"]
    assert "model" in r["raw"]["status_basis"] and r["raw"]["time_basis"]["precision"].startswith("poll")
    # continue
    C.poll(st, _snap("Currently overflowing.", t0 + 2 * h), "2026-09-21T18:00:00Z")
    assert len(st["events"]) == 1 and ev["state"] == "ongoing" and ev["last_overflowing_at"] == lp(2)
    # close: the first poll that no longer says overflowing; ended_at is its LastPoll
    C.poll(st, _snap("Overflow in the past 72 hours.", t0 + 3 * h), "2026-09-21T19:00:00Z")
    assert ev["state"] == "ended" and ev["ended_at"] == lp(3) and ev["ended_after"] == lp(2)
    assert "D_02" not in st["open"]
    r = _rec(st, key)
    assert r["status"] == "ended" and r["started_at"] == lp(1) and r["ended_at"] == lp(3)
    assert r["time_precision"] == "poll" and r["raw"]["ended_after"] == lp(2) and r["advice_window_hours"] is None
    assert r["source_updated_at"] == lp(3) and r["fetched_at"] == "2026-09-21T19:00:00Z"
    # the same past overflow, still listed: nothing new
    C.poll(st, _snap("Overflow in the past 72 hours.", t0 + 4 * h), "2026-09-21T20:00:00Z")
    C.poll(st, _snap("Data is not currently available.", t0 + 5 * h), "2026-09-21T21:00:00Z")
    C.poll(st, _snap("Overflow in the past 72 hours.", t0 + 6 * h), "2026-09-21T22:00:00Z")
    assert len(st["events"]) == 1 and ev["ended_at"] == lp(3)
    # reappear: overflowing again after a close is a new event
    C.poll(st, _snap("Currently overflowing.", t0 + 7 * h), "2026-09-21T23:00:00Z")
    assert len(st["events"]) == 2 and st["open"]["D_02"] != key
    new = st["events"][st["open"]["D_02"]]
    assert new["state"] == "ongoing" and new["started_at"] == lp(7) and new["started_after"] == lp(6)
    C.poll(st, _snap("No overflow in the past 72 hours.", t0 + 80 * h), "2026-09-25T04:00:00Z")
    assert new["state"] == "ended" and new["ended_at"] == lp(80) and "D_02" not in st["open"]
    assert ev["ended_at"] == lp(3)                                   # the first event is unchanged


def test_csocast_no_data_and_vanished():
    st = {}
    h = 3_600_000
    t0 = 1_790_000_000_000
    lp = lambda k: C.iso(C.last_poll(t0 + k * h))
    # no data is a per-outfall state, never an event
    C.poll(st, _snap("Data is not currently available.", t0), "2026-09-21T16:00:00Z")
    assert st["events"] == {} and st["outfalls"]["D_02"]["state"] == "no_data"
    # an ongoing overflow that loses data is unknown, and continues when it reports again
    C.poll(st, _snap("Currently overflowing.", t0 + h), "2026-09-21T17:00:00Z")
    (key, ev), = st["events"].items()
    assert ev["started_after"] is None                               # never seen clear before
    C.poll(st, _snap("Data is not currently available.", t0 + 2 * h), "2026-09-21T18:00:00Z")
    assert ev["state"] == "unknown" and _rec(st, key)["status"] == "unknown"
    C.poll(st, _snap("Currently overflowing.", t0 + 3 * h), "2026-09-21T19:00:00Z")
    assert len(st["events"]) == 1 and ev["state"] == "ongoing" and ev["resumed"][0]["after"] == "unknown"
    C.poll(st, _snap("Data is not currently available.", t0 + 4 * h), "2026-09-21T20:00:00Z")
    C.poll(st, _snap("No overflow in the past 72 hours.", t0 + 5 * h), "2026-09-21T21:00:00Z")
    assert ev["state"] == "ended" and ev["ended_at"] == lp(5) and ev["ended_after"] == lp(3)
    # an outfall that leaves the layer while overflowing is unknown
    C.poll(st, _snap("Currently overflowing.", t0 + 6 * h), "2026-09-21T22:00:00Z")
    C.poll(st, _snap("No overflow in the past 72 hours.", t0 + 7 * h, "S_09"), "2026-09-21T23:00:00Z")
    gone = st["events"][st["open"]["D_02"]]
    assert gone["state"] == "unknown" and gone["vanished"]["missing_at"] == "2026-09-21T23:00:00Z"


def test_csocast_overflow_between_polls():
    h = 3_600_000
    t0 = 1_790_000_000_000
    # first seen as "Overflow in the past 72 hours.": no start, ended by that poll, at most 72 h before
    st2 = {}
    C.poll(st2, _snap("Overflow in the past 72 hours.", t0, "S_01"), "2026-09-21T16:00:00Z")
    (k2, e2), = st2["events"].items()
    r2 = _rec(st2, k2, "S_01")
    assert r2["started_at"] is None and r2["reported_at"] == C.iso(C.last_poll(t0)) and r2["status"] == "ended"
    assert r2["ended_at"] == C.iso(C.last_poll(t0)) and r2["time_precision"] == "poll"
    assert r2["raw"]["occurred_after"] == C.iso(C.last_poll(t0 - 72 * h))
    # after "No overflow ..." the overflow began after that poll
    st3 = {}
    C.poll(st3, _snap("No overflow in the past 72 hours.", t0, "S_02"), "2026-09-21T16:00:00Z")
    C.poll(st3, _snap("Overflow in the past 72 hours.", t0 + h, "S_02"), "2026-09-21T17:00:00Z")
    (k3, e3), = st3["events"].items()
    assert e3["occurred_after"] == C.iso(C.last_poll(t0)) and e3["ended_at"] == C.iso(C.last_poll(t0 + h))
    # a close whose LastPoll went backwards uses our fetch time
    st4 = {}
    C.poll(st4, _snap("Currently overflowing.", t0 + 2 * h, "S_03"), "2026-09-21T17:00:00Z")
    C.poll(st4, _snap("No overflow in the past 72 hours.", t0 + h, "S_03"), "2026-09-21T18:00:00Z")
    (k4, e4), = st4["events"].items()
    assert e4["end_basis"] == "fetch" and e4["ended_at"] == "2026-09-21T14:00:00-04:00"
    assert "fetch time" in _rec(st4, k4, "S_03")["raw"]["end_basis"]


def test_hab_episodes():
    def s(day, lvl, wb="Pinchot Lake"):
        return {"Waterbody": wb, "newdateobs": f"{day}:09:00:00", "Response_Level": lvl,
                "Latitude": 40.07, "Longitude": -76.89, "Collector_ID": "8307"}
    rows = [s("02JUN2026", "No HAB issue detected"), s("09JUN2026", "Advisory (Yellow)"),
            s("16JUN2026", "Avoid Contact (Red)"), s("23JUN2026", "No HAB issue detected"),
            s("30JUN2026", "Advisory (Yellow)"), s("30JUN2026", "No HAB issue detected")]
    eps, unused = H.hab_episodes(rows)
    assert len(eps) == 2 and not unused
    r1, r2 = (H.hab_record(e) for e in eps)
    assert r1["status"] == "advisory_lifted" and r1["started_at"] == "2026-06-09T09:00:00-04:00"
    assert r1["ended_at"] == "2026-06-23T09:00:00-04:00" and r1["advice_text"].startswith("Avoid Contact (Red)")
    assert r2["status"] == "advisory_active" and r2["ended_at"] is None   # a mixed day counts at its highest level
    assert "Collector_ID" not in json.dumps(r1["raw"])


def test_beach_rows():
    assert H.advisory_kind("Restriction")[0] == "beach_closure"
    assert H.advisory_kind("RESTRICTION")[0] == "beach_closure"
    assert H.advisory_kind("Advisory  ")[0] == "beach_advisory"
    assert H.advisory_kind("Adisory")[0] == "beach_advisory" and H.advisory_kind("Adisory")[1]
    for v in ("", "None", "GM 114.6", "Closed for Season", "Was not open to swimming this day "):
        assert H.advisory_kind(v)[0] is None
    assert H.advisory_kind("Boil water")[0] == "unknown"
    assert H.parse_day("6//30/2026") == date(2026, 6, 30) and H.parse_day("6/3/0206") is None
    beach = {"name": "Beach 8", "lat": 42.15, "lon": -80.13, "current_status": "Closed for the season", "date_updated": "9/28/2026"}

    def row(d, adv=""):
        return {"Beach ID": "PA995339", "Collection Date": d, "Advisory type": adv, "Result Value": "1"}
    rows = [row("8/30/2025", "Restriction"), row("6/1/2026"), row("7/1/2026", "Advisory"), row("7/2/2026", "Restriction"),
            row("7/3/2026"), row("9/21/2026", "Advisory"), row("Collection Date", "Advisory type")]
    recs, st = H.beach_records(beach, rows, ["lake-erie-pa"], "https://x/export?format=csv")
    by = {r["source_record_id"]: r for r in recs}
    assert len(recs) == 4
    assert by["PA995339-20250830"]["ended_at"] is None          # the next sample is next season
    assert by["PA995339-20260701"]["ended_at"] == "2026-07-02T00:00:00-04:00"
    assert by["PA995339-20260702"]["event_type"] == "beach_closure"
    assert by["PA995339-20260702"]["ended_at"] == "2026-07-03T00:00:00-04:00"
    last = by["PA995339-20260921"]
    assert last["status"] == "advisory_lifted" and last["source_updated_at"] == "2026-09-28T00:00:00-04:00"
