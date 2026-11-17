"""Texas: Austin Water's and El Paso Water's spill news releases (ingest/tx_utility_spill_news.py).

Fixtures in tx_utility_news/, read 2026-11-17: list pages trimmed to their release links (Austin pages 0 and 3; El Paso's
?show=all list cut to seven links, the 2023 update among them) and six release pages trimmed to the date and the text,
with telephone numbers, quoted officials and the named contacts removed.
"""
import json
from pathlib import Path

import pytest

from ingest import tx_spill_notice_form as F
from ingest import tx_utility_spill_news as X

FX = Path(__file__).parent / "fixtures" / "tx_utility_news"
AT = "2026-11-17T10:00:00Z"


@pytest.fixture(autouse=True)
def no_tceq(monkeypatch):
    monkeypatch.setattr(F, "tceq_rows", lambda path=None: [])


def get_release(name):
    def g(url):
        p = FX / f"{name}-{url.rstrip('/').rsplit('/', 1)[-1]}.html"
        return p.read_text() if p.exists() else None
    return g


def run(name):
    pages = [p.read_text() for p in sorted(FX.glob(f"{name}-list*.html"))]
    return X.run_site(name, pages, [], AT, get_release(name))


def by_slug(recs):
    return {r["source_record_id"]: r for r in recs}


def test_austin_records():
    recs, stats = run("austin")
    d = by_slug(recs)
    assert stats["notices"] == 3 and [u.rsplit("/", 1)[-1][:40] for u in stats["unread"]] == [
        "austin-water-responds-wastewater-sludge-"]                      # the one release not in the fixtures
    cb = d["austin-water-reports-sanitary-sewer-overflow-near-5000-block-creek-bend-drive"]
    assert cb["started_at"] == "2024-12-10T11:53:00-06:00" and cb["raw"]["start_is_upper_bound"] is True
    assert cb["ended_at"] == "2024-12-10T13:47:00-06:00" and cb["status"] == "ended"
    assert cb["waterbody_text"] is None                    # "the spill did not reach Williamson Creek"
    assert cb["volume_gal"] is None and cb["volume_text"] == "over 100,000 gallons"
    assert cb["published_at"] == "2024-12-10"
    ne = d["austin-water-reports-sanitary-sewer-overflow-northeast-austin"]
    assert ne["waterbody_text"] == "Gilliland Creek" and ne["volume_gal"] == 198000 and ne["estimate_flag"] == "estimated"
    assert ne["started_at"] == "2025-12-22T09:50:00-06:00" and ne["ended_at"] is None
    eh = d["austin-water-responds-sanitary-sewer-overflow-near-e-howard-and-old-gregg-lane"]
    assert eh["started_at"] == "2026-09-14" and eh["time_precision"] == "day"
    assert eh["waterbody_text"] is None and eh["outfall_name"] == "E. Howard and Old Gregg Lane"
    assert eh["advice_text"].startswith("The public should avoid contact")
    assert eh["raw"]["county"] == "Travis" and eh["raw"]["_placement"] == "named_water_only"


def test_el_paso_records():
    recs, stats = run("elpaso")
    d = by_slug(recs)
    assert stats["not_notices"] == {"follow-up of an earlier release": 1}
    assert set(d) == {"wastewater-spill-at-bustamante-treatment-plant",
                      "wastewater-spill-contained-at-john-t-hickerson-treatment-facility", "wastewater-overflow-in-west-el-paso"}
    b = d["wastewater-spill-at-bustamante-treatment-plant"]
    assert b["started_at"] == "2026-05-31" and b["published_at"] == "2026-06-02"
    assert b["volume_gal"] == 560000 and b["raw"]["reached_water"] is False and b["waterbody_text"] is None
    assert b["raw"]["time_zone"] == "America/Denver"
    h = d["wastewater-spill-contained-at-john-t-hickerson-treatment-facility"]
    assert h["started_at"] == "2026-03-24T00:10:00-06:00"        # "first reported on Tuesday at 12:10 am", Mountain time
    assert h["waterbody_text"] == "Rio Grande" and h["raw"]["start_is_upper_bound"] is True
    w = d["wastewater-overflow-in-west-el-paso"]
    assert w["started_at"] == "2023-03-21"                         # "On Tuesday evening" in a Wednesday release
    assert w["volume_gal"] is None and "24,000" in w["volume_text"] and "100,000" in w["volume_text"]


def test_nothing_personal_or_reassuring_kept():
    s = json.dumps(run("austin")[0] + run("elpaso")[0])
    for bad in ("[phone removed]", "Media Line", "said", "remains safe", "not at risk", "Coomer Path", "13625", "10001"):
        assert bad not in s, bad


def test_list_failure_and_quiet_list(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(X, "list_pages", lambda name, backfill, src: ["<html>maintenance</html>"])
    assert X.main(["--site", "austin"]) == 1
    assert common.read_json(tmp_path / "tx-austin-water-spill-news.json")["ok"] is False
    quiet = '<a href="/water/news/prescribed-burn" hreflang="und">Prescribed Burn Planned</a>'
    monkeypatch.setattr(X, "list_pages", lambda name, backfill, src: [quiet])
    monkeypatch.setattr(X, "save_raw", lambda *a: None)
    assert X.main(["--site", "austin"]) == 0
    d = common.read_json(tmp_path / "tx-austin-water-spill-news.json")
    assert d["ok"] is True and d["count"] == 0


def test_link_to_tceq_by_any_entity(monkeypatch):
    rows = [{"event_id": "tx-tceq-sso-opendata:455203", "source_record_id": "455203", "started_at": "2026-03-24",
             "volume_gal": 670000, "discharger_id": "tx-rn104403209", "raw": {}},
            {"event_id": "tx-tceq-sso-opendata:458958", "source_record_id": "458958", "started_at": "2026-05-31",
             "volume_gal": None, "discharger_id": "tx-el-paso-water-utilities-public-service-board", "raw": {}}]
    monkeypatch.setattr(F, "tceq_rows", lambda path=None: rows)
    recs, stats = run("elpaso")
    d = by_slug(recs)
    assert d["wastewater-spill-contained-at-john-t-hickerson-treatment-facility"]["duplicate_of"] == "tx-tceq-sso-opendata:455203"
    assert d["wastewater-spill-at-bustamante-treatment-plant"]["duplicate_of"] == "tx-tceq-sso-opendata:458958"
    assert stats["duplicates_of_tceq"] == 2
