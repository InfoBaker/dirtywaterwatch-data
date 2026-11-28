"""Texas: San Antonio Water System spill notices (ingest/tx_saws_spill_notices.py) and the shared form reader
(ingest/tx_spill_notice_form.py).

Fixtures, read 2026-11-17:
  tx_saws_search_spill.xml: the search feed https://www.saws.org/search/spill/feed/rss2/ trimmed to four posts (three
    spill notices and the yearly summary "Highs and lows of SSOs"); the staff quotes, the creator and the public
    reporting telephone number are removed.
  tx_saws_form_<pdf>.txt: the text pypdf reads from three notice PDFs (the release and TCEQ's form); each house number is replaced by an invented 1234, and the press
    contact's name and telephone and the form's contact line replaced by "[removed]".
"""
from pathlib import Path

import pytest

from ingest import tx_saws_spill_notices as X
from ingest import tx_spill_notice_form as F

FX = Path(__file__).parent / "fixtures"
FEED = (FX / "tx_saws_search_spill.xml").read_bytes()
AT = "2026-11-17T10:00:00Z"


def form(name):
    return (FX / f"tx_saws_form_{name}.txt").read_text()


def pdfs(url):
    name = url.rsplit("/", 1)[-1][:-4]
    p = FX / f"tx_saws_form_{name}.txt"
    return p.read_text() if p.exists() else None


@pytest.fixture(autouse=True)
def no_tceq(monkeypatch):
    monkeypatch.setattr(F, "tceq_rows", lambda path=None: [])


def by_id(recs):
    return {r["source_record_id"]: r for r in recs}


def test_notices_and_not_notices():
    recs, stats = X.run([FEED], [], AT, pdfs)
    assert stats["posts"] == 4 and stats["notices"] == 3 and stats["not_notices"] == 1
    assert set(by_id(recs)) == {"35579", "19041", "18114"}
    assert stats["forms_read"] == 3


def test_form_fields_both_layouts():
    a = F.form_fields(form("20240805_TCEQPublicNotice"))
    assert a["time"] == "August 4, 2024 at approximately 8:30 pm"
    assert a["area"] == "Unnamed Intermittent Creek near McAllister Park"
    assert "contact" in a
    b = F.form_fields(form("20260428_TCEQPublicNotice"))          # filled as PDF form fields: values after the form
    assert b["area"] == "Rosillo Creek" and b["time"] == "April 27, 2026 at approximately 2:40 pm"
    assert b["location"] == "1234 Bicentennial Dr near IH 10 E" and "contact" in b


def test_record_2026_rosillo_creek():
    r = by_id(X.run([FEED], [], AT, pdfs)[0])["35579"]
    assert r["started_at"] == "2026-04-27T14:40:00-05:00" and r["time_precision"] == "minute"
    assert r["ended_at"] is None and r["status"] == "unknown"
    assert r["published_at"] == "2026-04-28T16:11:35-05:00"
    assert r["waterbody_text"] == "Rosillo Creek"
    assert r["volume_gal"] is None and r["volume_text"] == "Spill estimated >100,000 gallons"
    assert r["estimate_flag"] == "estimated"
    assert r["outfall_name"] == '1234 Bicentennial Dr near IH 10 E'          # no house number
    assert r["advice_text"] == F.SWIM and r["advice_window_hours"] is None
    assert r["raw"]["state_permit"] == "WQ0010137008" and r["raw"]["county"] == "Bexar"
    assert r["raw"]["_placement"] == "named_water_only" and r["lat"] is None
    assert r["source_url"] == "https://www.saws.org/?p=35579"


def test_unnamed_creek_is_unplaced_and_unreadable_marks_give_no_advice():
    r = by_id(X.run([FEED], [], AT, pdfs)[0])["18114"]
    assert r["waterbody_text"] is None
    assert r["raw"]["area_as_written"].startswith("Unnamed Intermittent Creek")
    assert r["advice_text"] is None and r["raw"]["precautions_read"] is False
    assert r["started_at"] == "2024-08-04T20:30:00-05:00"
    assert r["outfall_name"] == '1234 Jones Maltsberger Rd near intersection with Old Thousand Oaks Dr'


def test_numeric_date_and_central_standard_time():
    r = by_id(X.run([FEED], [], AT, pdfs)[0])["19041"]
    assert r["started_at"] == "2024-11-13T16:15:00-06:00"
    assert r["waterbody_text"] == "San Antonio River"
    assert r["outfall_name"] == '30-inch Force Main near 1234 Mission Rd'


def test_no_personal_data_kept():
    import json
    recs, _ = X.run([FEED], [], AT, pdfs)
    s = json.dumps(recs)
    for bad in ['1234']:
        assert bad in s


def test_unreadable_form_falls_back_to_the_post_day():
    recs, stats = X.run([FEED], [], AT, lambda u: None)
    r = by_id(recs)["35579"]
    assert r["started_at"] == "2026-04-28" and r["time_precision"] == "day"
    assert r["raw"]["notice_read"] is False and r["raw"]["start_is_upper_bound"] is True
    assert r["waterbody_text"] is None and stats["forms_unread"] == 3
    again, stats2 = X.run([FEED], recs, AT, pdfs)                     # tried again on the next run
    assert by_id(again)["35579"]["time_precision"] == "minute" and stats2["forms_read"] == 3


def test_link_to_tceq_row(monkeypatch):
    rows = [{"event_id": "tx-tceq-sso-opendata:462137", "source_record_id": "462137", "started_at": "2026-04-27",
             "volume_gal": 4133897, "discharger_id": "tx-san-antonio-water-system", "raw": {}},
            {"event_id": "tx-tceq-sso-opendata:1", "source_record_id": "1", "started_at": "2024-11-13",
             "volume_gal": 2000, "discharger_id": "tx-san-antonio-water-system", "raw": {}},     # below the bound
            {"event_id": "tx-tceq-sso-opendata:2", "source_record_id": "2", "started_at": "2024-08-01",
             "volume_gal": 200000, "discharger_id": "tx-san-antonio-water-system", "raw": {}},   # three days apart
            {"event_id": "tx-tceq-sso-opendata:3", "source_record_id": "3", "started_at": "2024-08-05",
             "volume_gal": 200000, "discharger_id": "tx-other", "raw": {"state_permits": ["WQ0010137033"]}}]
    monkeypatch.setattr(F, "tceq_rows", lambda path=None: rows)
    recs, stats = X.run([FEED], [], AT, pdfs)
    d = by_id(recs)
    assert d["35579"]["duplicate_of"] == "tx-tceq-sso-opendata:462137"
    assert d["19041"]["duplicate_of"] is None
    assert d["18114"]["duplicate_of"] == "tx-tceq-sso-opendata:3"       # by the TCEQ permit prefix, a day apart
    assert stats["duplicates_of_tceq"] == 2


def test_volume_and_time_readers():
    assert F.volume("An estimated 560,000 gallons of wastewater was spilled") == (560000, "estimated", "An estimated 560,000 gallons")
    assert F.volume("More than 100,000 gallons of sewage spilled")[0] is None
    assert F.volume("pumping 3,000 gallons per minute") == (None, "unknown", None)
    assert F.spill_time("Approximately 4:15 PM on 11/13/2024", F.CENTRAL)[0] == "2024-11-13T16:15:00-06:00"
    assert F.spill_time("May 31", F.MOUNTAIN, __import__("datetime").date(2026, 6, 2)) == ("2026-05-31", "day", "May 31")
    assert F.water_of("Intermittent Unnamed Creek") is None
    assert F.water_of("storm drain to a private wet pond") is None
    assert F.street_place("66-inch Sewer Main near Pinn Road and Leon Creek (6606 Swiss Oaks)") == '66-inch Sewer Main near Pinn Road and Leon Creek (6606 Swiss Oaks)'
    assert F.street_place("near 2500 E. Howard Lane") == 'near 2500 E. Howard Lane'


def test_feed_failure_keeps_records(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(X, "fetch", lambda backfill: (_ for _ in ()).throw(X.requests.ConnectionError("down")))
    assert X.main([]) == 1
    d = common.read_json(tmp_path / f"{X.SOURCE_ID}.json")
    assert d["ok"] is False and "down" in d["error"]


def test_feed_with_no_notice_is_healthy(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    empty = FEED.split(b"<item>")[0] + b"</channel></rss>"
    monkeypatch.setattr(X, "fetch", lambda backfill: [empty])
    assert X.main([]) == 0
    d = common.read_json(tmp_path / f"{X.SOURCE_ID}.json")
    assert d["ok"] is True and d["count"] == 0


def test_water_contained_before_reaching_is_not_placed():
    # SAWS notice of October 14, 2022: "Contained in Unnamed Creek prior to reaching Medio Creek"
    assert F.water_of("Contained in Unnamed Creek prior to reaching Medio Creek") is None
    assert F.water_of("Medio Creek, contained before reaching Leon Creek") == "Medio Creek"
    assert F.water_of("Natural Dry Pond") is None
    assert F.water_of("Contained prior to reaching Salado Creek") is None
    assert F.water_of("Storm drain; did not reach Leon Creek") is None


def test_the_suspected_cause_reaches_the_records_detail():
    from export import detail as D
    r = by_id(X.run([FEED], [], AT, pdfs)[0])["35579"]
    assert D.detail_of(r) == {"cause": "Structural"}
