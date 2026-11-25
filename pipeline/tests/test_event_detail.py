"""The source's detail on a public record (export/detail.py): named fields only, scrubbed, and a later record's
volume carried onto the earlier record of the same event only where the pipeline linked the two
(site docs/decisions.md item 31). Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as status_mod  # noqa: E402
from common import NAME_KEYS, PERSONAL_KEYS, event  # noqa: E402
from export import build as X  # noqa: E402
from export import csv as csv_export  # noqa: E402
from export import detail as D  # noqa: E402
from ingest import ma_massdep  # noqa: E402


def ma(rid, cls, start, *, kind=None, number=None, parent=None, volume="", rain="", hours="", minutes="",
       published="2026-09-28T09:00:00-04:00", end=None, status="ongoing"):
    """A MassDEP record as the ingester keeps it (the row's fields in raw), before linking."""
    raw = {"_report_class": cls, "reporterClass": cls, "incidentNumber": number or rid, "municipality": "SPRINGFIELD",
           "volumnOfEvent": volume, "rainfallData": rain, "hours": hours, "minutes": minutes}
    if kind:
        raw["reportingType"] = kind
    if parent:
        raw["parentIncidentId"] = parent
    vg, _ = (int(volume), None) if volume else (None, None)
    return {"event_id": f"ma-massdep:{rid}", "source_id": "ma-massdep", "source_record_id": rid, "event_type": "cso",
            "started_at": start, "ended_at": end, "outfall_id": "SPR010", "discharger_name": "SPRINGFIELD WSC",
            "status": status, "parent_event_id": None, "published_at": published, "volume_gal": vg,
            "volume_text": volume or None, "estimate_flag": "unknown", "raw": raw}


def springfield():
    """Springfield's September 27 overflow: the notice (no volume, as MassDEP's notices are), its Ceased update and
    the Verified Data Report a month later with 1,017,806 gallons."""
    notice = ma("n1", "Public Notification Report", "2026-09-27T05:10:00-04:00", kind="Initial-Ongoing",
                number="26017854", published="2026-09-27T09:00:00-04:00")
    ceased = ma("c1", "Public Notification Report", "2026-09-27T05:10:00-04:00", kind="Ceased", number="26017854-1", parent="n1",
                published="2026-09-27T15:00:00-04:00")
    vdr = ma("v1", "Verified Data Report", "2026-09-27T05:15:00-04:00", number="26019001", volume="1017806",
             rain="1.27", hours="6", minutes="35", published="2026-10-28T11:02:00-04:00",
             end="2026-09-27T11:50:00-04:00", status="ended")
    recs = [notice, ceased, vdr]
    ma_massdep.link(recs, {})
    return notice, ceased, vdr


def test_a_verified_volume_reaches_its_notice_with_its_qualifier_and_date():
    notice, ceased, vdr = springfield()
    assert vdr["parent_event_id"] == notice["event_id"] and ceased["parent_event_id"] == notice["event_id"]
    D.enrich([notice, ceased, vdr])
    assert notice["later_volume"] == {"event_id": "ma-massdep:v1", "volume_gal": 1017806, "volume_text": "1017806",
                                      "volume_qualifier": "verified by the operator", "report_kind": "Verified Data Report",
                                      "published_at": "2026-10-28T11:02:00-04:00"}
    assert ceased["later_volume"]["volume_gal"] == 1017806          # the Ceased update is the same event
    assert "later_volume" not in vdr                                 # nothing later than the verified report
    rel = {r["event_id"]: r["relation"] for r in notice["linked_records"]}
    assert rel == {"ma-massdep:c1": "later", "ma-massdep:v1": "later"}
    assert vdr["linked_records"] == [{"event_id": "ma-massdep:n1", "relation": "earlier", "source_id": "ma-massdep",
                                      "report_kind": "Public Notification Report, Initial-Ongoing",
                                      "published_at": "2026-09-27T09:00:00-04:00"}]
    assert notice["volume_gal"] is None                              # the notice's own figure is never filled in


def test_the_verified_reports_own_detail_is_read_as_the_source_gives_it():
    *_, vdr = springfield()
    assert D.detail_of(vdr) == {"report_kind": "Verified Data Report", "rainfall_in": "1.27", "rainfall_label": "Rainfall",
                                "duration_text": "6 hours, 35 minutes", "volume_qualifier": "verified by the operator",
                                "town": "SPRINGFIELD"}


def test_a_notice_with_a_volume_is_an_estimate_by_statute():
    n = ma("n9", "Public Notification Report", "2026-09-27T05:10:00-04:00", kind="Initial-Ongoing", volume="250000")
    assert D.detail_of(n)["volume_qualifier"] == "estimated"
    # a qualifier with no volume is not written
    assert "volume_qualifier" not in D.detail_of(ma("n8", "Public Notification Report", "2026-09-27T05:10:00-04:00"))


def test_two_overflows_the_pipeline_did_not_link_share_nothing():
    a = ma("a1", "Public Notification Report", "2026-09-27T05:10:00-04:00", kind="Initial-Ongoing")
    b = ma("b1", "Verified Data Report", "2026-09-29T20:00:00-04:00", volume="5000", hours="1", minutes="0",
           published="2026-10-28T11:00:00-04:00", end="2026-09-29T21:00:00-04:00", status="ended")
    ma_massdep.link([a, b], {})                                     # two days apart: not the same event
    D.enrich([a, b])
    assert b["parent_event_id"] is None and "later_volume" not in a and "linked_records" not in a


def test_the_same_figure_and_qualifier_later_adds_nothing_and_advisories_get_no_later_volume():
    first = {"event_id": "ny-dec-sprtk:1", "source_id": "ny-dec-sprtk", "event_type": "sso", "parent_event_id": None,
             "volume_gal": 2000, "published_at": "2026-07-01T00:47:00-04:00",
             "raw": {"row": {"quantity": "2000 Gallons Estimated", "notificationStatus": "New"}}}
    close = {**first, "event_id": "ny-dec-sprtk:2", "parent_event_id": "ny-dec-sprtk:1", "published_at": "2026-07-01T09:21:00-04:00",
             "raw": {"row": {"quantity": "2000 Gallons Estimated", "notificationStatus": "Close"}}}
    D.enrich([first, close])
    assert "later_volume" not in first and first["linked_records"][0]["report_kind"] == "Close"
    a1 = {"event_id": "vt-advisories:1", "source_id": "vt-advisories", "event_type": "hab_advisory", "parent_event_id": None,
          "published_at": "2026-07-01", "raw": {}}
    a2 = {**a1, "event_id": "vt-advisories:2", "parent_event_id": "vt-advisories:1", "published_at": "2026-07-02",
          "volume_gal": 5}
    D.enrich([a1, a2])
    assert "later_volume" not in a1


def test_a_later_notice_of_one_chain_gives_its_figure_to_the_earlier_one():
    new = {"event_id": "ny-dec-sprtk:1", "source_id": "ny-dec-sprtk", "event_type": "cso", "parent_event_id": None,
           "volume_gal": None, "volume_text": "65 Gallons per Minute Estimated", "published_at": "2026-07-01T00:47:00-04:00",
           "raw": {"row": {"quantity": "65 Gallons per Minute Estimated", "notificationStatus": "New"}}}
    close = {"event_id": "ny-dec-sprtk:2", "source_id": "ny-dec-sprtk", "event_type": "cso", "parent_event_id": "ny-dec-sprtk:1",
             "volume_gal": 2000, "volume_text": "2000 Gallons Estimated", "published_at": "2026-07-01T09:21:00-04:00",
             "raw": {"row": {"quantity": "2000 Gallons Estimated", "notificationStatus": "Close"}}}
    D.enrich([new, close])
    assert new["later_volume"]["volume_gal"] == 2000 and new["later_volume"]["volume_qualifier"] == "estimated"
    assert new["later_volume"]["report_kind"] == "Close"


def test_a_record_with_every_field_and_one_with_none():
    full = {"source_id": "ct-deep", "volume_gal": 3470000, "raw": {
        "Report Type": "CSO - Greater New Haven 5 Day Report", "Cause of Bypass": "Excessive Flows - Storm Event",
        "Weather Conditions": 'Rain 1-2" per hour', "Total Rainfall": "1.5",
        "Describe how final volume was determined": "flow meter", "Location of Bypass": "Treatment Plant",
        "Municipality": "Bridgeport"}}
    assert D.detail_of(full) == {"report_kind": "CSO - Greater New Haven 5 Day Report",
                                 "cause": "Excessive Flows - Storm Event", "weather": 'Rain 1-2" per hour',
                                 "rainfall_in": "1.5", "rainfall_label": "Total rainfall", "volume_method": "flow meter",
                                 "overflow_point": "Treatment Plant", "town": "Bridgeport"}
    assert D.detail_of({"source_id": "ct-deep", "raw": {"Cause of Bypass": "N/A", "Total Rainfall": "trace"}}) == {}
    assert D.detail_of({"source_id": "a-feed-nobody-mapped", "raw": {"cause": "Grease"}}) == {}
    assert D.detail_of({"source_id": "ct-deep"}) == {}
    fl = {"source_id": "fl-dep-pnp", "raw": {"FACILITY_CITY": "Tampa", "FACILITY_ADDRESS_LINE_1": "4113 Tartan Pl",
                                             "_template": {"cause": "Contractor", "volume_recovered": "300"}}}
    assert D.detail_of(fl) == {"cause": "Contractor", "town": "Tampa"}            # never the address


def test_named_detail_fields_preserve_public_record_text():
    rec = {"source_id": "md-mde-overflows", "raw": {"row": {
        "overflow_cause": "Grease at 12 Elm St, the resident's home; call Jane at 410-555-0100 or jane@example.org",
        "duration_day": "0", "duration_hour": "1", "duration_minute": "15",
        "reporter_name": "Jane Roe", "secret_new_field": "anything"}}}
    d = D.detail_of(rec)
    assert set(d) == {"cause", "duration_text"} and d["duration_text"] == "0 days, 1 hour, 15 minutes"
    assert d["cause"] == rec["raw"]["row"]["overflow_cause"]
    assert "Jane Roe" not in str(d) and "anything" not in str(d)
    assert not any(PERSONAL_KEYS.search(f) or NAME_KEYS.search(f) for f in D.FIELDS)
    long = {"source_id": "tx-tceq-sso-opendata", "raw": {"_cause": "word " * 200}}
    assert D.detail_of(long)["cause"] == long["raw"]["_cause"].strip()


def test_another_sources_record_of_the_same_event_is_linked_both_ways():
    ga = {"event_id": "ga-epd-spills:9", "source_id": "ga-epd-spills", "event_type": "sso", "parent_event_id": None,
          "raw": {"_epa_record": "echo-sewer-overflow:GA1:M-1:1", "row": {"cause": "Grease"}}}
    epa = {"event_id": "echo-sewer-overflow:GA1:M-1:1", "source_id": "echo-sewer-overflow", "event_type": "sso",
           "parent_event_id": None, "volume_gal": 120000, "published_at": "2026-08-24",
           "raw": {"causes": [{"code": "BPA", "desc": "Broken Pipe"}], "discharge_quantification_method_desc": "Best Professional Judgement"}}
    D.enrich([ga, epa])
    assert ga["linked_records"] == [{"event_id": epa["event_id"], "relation": "other_source", "source_id": "echo-sewer-overflow",
                                     "published_at": "2026-08-24"}]         # no bare figure without its qualifier
    assert epa["linked_records"][0]["event_id"] == ga["event_id"]
    assert "later_volume" not in ga                                 # another source's figure is linked, not carried
    assert epa["detail"] == {"cause": "Broken Pipe", "volume_method": "Best Professional Judgement"}


def test_slim_rows_carry_the_cells_detail_only():
    notice, ceased, vdr = springfield()
    D.enrich([notice, ceased, vdr])
    s = X.slim_event({**vdr, "file": "events/x.json", "fixture": False})
    assert s["detail"] == {"duration_text": "6 hours, 35 minutes", "volume_qualifier": "verified by the operator"}
    assert "linked_records" not in s and "raw" not in s
    n = X.slim_event({**notice, "file": "events/n.json", "fixture": False})
    assert n["later_volume"]["volume_gal"] == 1017806 and "detail" not in n
    for k in ("estimate_flag", "detail", "later_volume"):
        assert k in X.WATER_EVENT_EXTRA


@pytest.fixture
def covered(monkeypatch):
    monkeypatch.setattr(status_mod, "_STATES", {"MA"})


def test_csv_rows_carry_the_detail_and_the_later_record(tmp_path, covered):
    notice, ceased, vdr = springfield()
    D.enrich([notice, ceased, vdr])
    rows = []
    for r in (notice, vdr):
        e = event(**{k: v for k, v in r.items() if k in {"event_id", "source_id", "source_record_id", "event_type", "status",
                                                          "started_at", "ended_at", "outfall_id", "discharger_name",
                                                          "published_at", "volume_gal", "volume_text", "parent_event_id"}})
        e.update(fixture=False, water_slugs=[], detail=r.get("detail"), later_volume=r.get("later_volume"),
                 linked_records=r.get("linked_records"), raw={})
        rows.append(e)
    out = tmp_path / "csv"
    csv_export.write_csvs(rows, [], [], out, page_ids=set())
    import csv as _csv
    with (out / "state" / "ma.csv").open(newline="", encoding="utf-8") as f:
        got = {r["event_id"]: r for r in _csv.DictReader(f)}
    n, v = got["ma-massdep:n1"], got["ma-massdep:v1"]
    assert (n["later_volume_gal"], n["later_volume_qualifier"], n["later_record_id"]) == ("1017806", "verified by the operator", "ma-massdep:v1")
    assert n["later_record_kind"] == "Verified Data Report" and n["town_named"] == "SPRINGFIELD"
    assert n["linked_record_ids"] == "later:ma-massdep:c1;later:ma-massdep:v1"
    assert n["volume_gal"] == "" and n["report_kind"] == "Public Notification Report, Initial-Ongoing"
    assert (v["rainfall_in"], v["duration_text"], v["volume_qualifier"]) == ("1.27", "6 hours, 35 minutes", "verified by the operator")
    assert v["later_volume_gal"] == ""


def test_a_nested_container_never_becomes_text():
    rec = {"source_id": "md-mde-overflows", "raw": {"row": {"overflow_cause": {"desc": {"secret_new_field": "unmapped value"}}}}}
    assert D.detail_of(rec) == {}
    rec = {"source_id": "echo-sewer-overflow", "raw": {"causes": [{"code": "X", "desc": ["nested"]}, {"code": "B", "desc": "Blockage"}]}}
    assert D.detail_of(rec) == {"cause": "Blockage"}


def test_later_means_a_later_instant_across_offsets():
    """01:10 EST is after 01:50 EDT on the night the clocks go back: string order would swap them."""
    a = {"event_id": "ny-dec-sprtk:a", "source_id": "ny-dec-sprtk", "event_type": "cso", "parent_event_id": None,
         "volume_gal": 100, "published_at": "2026-11-01T01:50:00-04:00", "raw": {}}
    b = {"event_id": "ny-dec-sprtk:b", "source_id": "ny-dec-sprtk", "event_type": "cso", "parent_event_id": "ny-dec-sprtk:a",
         "volume_gal": 900, "published_at": "2026-11-01T01:10:00-05:00", "raw": {}}
    D.enrich([a, b])
    assert a["later_volume"]["volume_gal"] == 900 and "later_volume" not in b


def test_a_duplicate_from_the_status_build_neither_gives_nor_takes_a_later_volume():
    notice, ceased, vdr = springfield()
    D.enrich([notice, ceased, vdr], duplicates={vdr["event_id"]})
    assert "later_volume" not in notice
    notice, ceased, vdr = springfield()
    D.enrich([notice, ceased, vdr], duplicates={notice["event_id"]})
    assert "later_volume" not in notice and "linked_records" in notice      # still linked, just no figure carried


def test_ny_web_notices_join_their_workbook_chain_and_are_read_from_the_page():
    wb = {"event_id": "ny-dec-sprtk:1", "source_id": "ny-dec-sprtk", "event_type": "cso", "parent_event_id": None,
          "volume_gal": None, "volume_text": "65 Gallons per Minute Estimated", "published_at": "2026-11-12T20:00:00-05:00",
          "raw": {"row": {"notificationStatus": "New"}}}
    web = {"event_id": "ny-dec-sprtk-web:9", "source_id": "ny-dec-sprtk-web", "event_type": "cso", "parent_event_id": "ny-dec-sprtk:1",
           "volume_gal": 60000, "volume_text": "60,000 Gallons Estimated", "published_at": "2026-11-12T21:42:00-05:00",
           "raw": {"parsed": {"word": "UPDATE", "reason": "System Capacity", "duration": "unknown Hours",
                              "volume": "60,000 Gallons Estimated", "discharge_location": "50 State School Rd"}}}
    D.enrich([wb, web])
    assert web["detail"] == {"report_kind": "UPDATE", "cause": "System Capacity", "duration_text": "unknown Hours",
                             "volume_qualifier": "estimated"}
    assert wb["later_volume"]["event_id"] == web["event_id"] and wb["later_volume"]["volume_qualifier"] == "estimated"
    other = {**web, "event_id": "fl-dep-pnp:1", "source_id": "fl-dep-pnp"}         # an unrelated feed is never joined
    wb2 = {**wb}
    D.enrich([wb2, other])
    assert "later_volume" not in wb2 and "linked_records" not in wb2


def test_georgias_several_epa_reports_are_each_linked():
    ga = {"event_id": "ga-epd-spills:9", "source_id": "ga-epd-spills", "event_type": "sso", "parent_event_id": None,
          "raw": {"_epa_record": ["echo-sewer-overflow:a", "echo-sewer-overflow:b"]}}
    a = {"event_id": "echo-sewer-overflow:a", "source_id": "echo-sewer-overflow", "event_type": "sso", "parent_event_id": None, "raw": {}}
    b = {**a, "event_id": "echo-sewer-overflow:b"}
    D.enrich([ga, a, b])
    assert [r["event_id"] for r in ga["linked_records"]] == ["echo-sewer-overflow:a", "echo-sewer-overflow:b"]
    assert b["linked_records"][0]["event_id"] == ga["event_id"]


def test_ma_duration_reads_one_hour_in_the_singular():
    r = ma("v7", "Verified Data Report", "2026-09-27T05:15:00-04:00", volume="5", hours="1", minutes="1")
    assert D.detail_of(r)["duration_text"] == "1 hour, 1 minute"
