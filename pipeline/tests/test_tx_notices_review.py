"""Texas local spill notices: the independent review's findings of 2026-11-17 (inputs are invented and marked so)."""
from pathlib import Path

from ingest import tx_saws_spill_notices as S
from ingest import tx_spill_notice_form as F
from ingest import tx_utility_spill_news as U

AUSTIN = U.SITES["austin"]


def _row(i, day, vol, water=None, permits=None):
    return {"event_id": f"tx-tceq-sso-opendata:{i}", "source_record_id": str(i), "started_at": day, "volume_gal": vol,
            "discharger_id": "tx-san-antonio-water-system", "waterbody_text": water, "raw": {"state_permits": permits or []}}


def test_p1_link_prefers_same_water_and_never_reuses_a_row():
    recs = [{"started_at": "2026-04-27T14:40:00-05:00", "volume_gal": None, "volume_text": "Spill estimated >100,000 gallons",
             "discharger_id": "tx-san-antonio-water-system", "waterbody_text": "Rosillo Creek", "raw": {}},
            {"started_at": "2026-04-27T09:00:00-05:00", "volume_gal": None, "volume_text": "Spill estimated >100,000 gallons",
             "discharger_id": "tx-san-antonio-water-system", "waterbody_text": None, "raw": {}}]
    rows = [_row(1, "2026-04-27", 200000, "LEON CREEK"), _row(2, "2026-04-27", 400000, "Rosillo Creek")]
    assert F.link_tceq(recs, rows) == 2
    assert recs[0]["duplicate_of"] == "tx-tceq-sso-opendata:2"
    assert recs[1]["duplicate_of"] == "tx-tceq-sso-opendata:1"
    lone = [dict(recs[0], raw={})]
    assert F.link_tceq(lone, [_row(1, "2026-04-27", 200000, "LEON CREEK")]) == 0    # another named water


def test_p1_waters_not_read_from_negations_streets_or_plants():
    ss = ["The wastewater did not flow into Salado Creek",
          "It spilled into a ditch on Salado Creek Road",
          "The Salado Creek Water Recycling Center overflowed into an unnamed ditch"]
    assert U.waters_of(ss)[0] == []
    assert F.water_of("Salado Creek Road ditch") is None


def test_p1_advice_drops_addresses_names_and_verdicts():
    assert U.advice_of(["Avoid contact with wastewater near 123 Main Street, said Jane Example"]) is None
    assert U.advice_of(["The water is clean, but avoid contact with sediment"]) is None
    assert U.advice_of(["Avoid contact with water near 123 Main Street"]) == "Avoid contact with water near Main Street."


def test_p1_saws_free_text_drops_house_numbers():
    feed = (Path(__file__).parent / "fixtures" / "tx_saws_search_spill.xml").read_bytes()
    form = (Path(__file__).parent / "fixtures" / "tx_saws_form_TCEQ-11.13.24-public-notice.txt").read_text()
    form = form.replace("San Antonio River", "San Antonio River near 123 Main Street")   # invented
    recs, _ = S.run([feed], [], "2026-11-17T10:00:00Z", lambda u: form if "11.13.24" in u else None)
    r = [x for x in recs if x["source_record_id"] == "19041"][0]
    assert "123" not in str(r["raw"]) and r["raw"]["area_as_written"] == "San Antonio River near Main Street"


def test_p1_saws_non_rss_page_is_a_failure(tmp_path, monkeypatch):
    import common
    import pytest
    with pytest.raises(ValueError):
        S.items(b"<html><body>Maintenance</body></html>")
    assert S.items(b"<rss><channel><title>x</title></channel></rss>") == []


def test_p1_saved_list_keeps_notice_titles_without_house_numbers():
    page = '<a href="/water/news/wastewater-spill-near-main" hreflang="und">Wastewater spill near 123 Main Street</a>'
    saved = U.safe_list([page], AUSTIN)
    assert "123" not in saved and "Main Street" in saved


def test_p2_clock_from_another_dated_sentence_is_not_used():
    ss = U.sentences("A sewer spill occurred on December 10. The spill was discovered on December 11 at 9:50 a.m. "
                     "On December 11, crews stopped the overflow at 1:47 p.m.")
    t = U.spill_times(ss, __import__("datetime").date(2026, 12, 12), F.CENTRAL)
    assert t["start"] == "2026-12-10" and t["precision"] == "day" and t["end"] is None


def test_p2_responding_is_an_upper_bound():
    ss = U.sentences("Crews began responding to the spill on December 10 at 9:50 a.m.")
    t = U.spill_times(ss, __import__("datetime").date(2026, 12, 12), F.CENTRAL)
    assert t["kind"] == "found"


def test_p2_bounds_and_ranges_have_no_figure():
    for s in ("less than 100,000 gallons", "up to 100,000 gallons", "at least 100,000 gallons",
              "between 100,000 and 200,000 gallons", "100,000 to 200,000 gallons"):
        assert F.volume(s)[0] is None, s


def test_p2_unread_release_is_retried_after_it_leaves_the_list(tmp_path):
    item = '<a href="/water/news/austin-water-reports-sanitary-sewer-overflow-x" hreflang="und">Austin Water Reports Sanitary Sewer Overflow</a>'
    recs, stats = U.run_site("austin", [item], [], "T1", lambda u: None)
    assert recs == [] and stats["unread"]
    page = ('<p>Release Date:</p><p>December 10, 2024</p> For Immediate Release <p>Crews responded to an overflow on '
            'Dec 10. Approximately 1,000 gallons spilled.</p>')
    recs2, stats2 = U.run_site("austin", ["<a href=\"/water/news/other\" hreflang=\"und\">Prescribed burn</a>"], [], "T2",
                               lambda u: page, retry=stats["unread_items"])
    assert len(recs2) == 1 and stats2["unread"] == []
