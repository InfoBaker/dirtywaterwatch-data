"""Springfield Water and Sewer Commission's monthly CSO reports, 2019 to 2023 (ingest/ma_springfield_archive.py).

The fixture months are small and inline (a few outfalls, figures of the kind the reports print, partly invented for the
edge cases); one test reads the committed transcript. No network, no PDFs.

Run from pipeline/:  python -m pytest tests/test_ingest_ma_springfield_archive.py -q
"""
from __future__ import annotations

import json

import pytest

from build import charts
from build import status as ST
from common import read_json
from ingest import ma_springfield_archive as S

URL = "https://springfieldalerts.com/Suez/wp-content/uploads/2022/06/CSO-{}.pdf"


def capture(name, ts="20220928054028"):
    return {"name": f"CSO-{name}.pdf", "url": URL.format(name), "bytes": 1000,
            "capture": {"service": "Internet Archive", "timestamp": ts, "sha1_base32": "A" * 32,
                        "date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "url": f"https://web.archive.org/web/{ts}/{URL.format(name)}"}}


def month(name, rows, label="Hours", total=None):
    rows = [{"outfall": o, "watershed": w, "events": e, "volume_gal": g, "hours": h} for o, w, e, g, h in rows]
    total = total or {"events": sum(r["events"] for r in rows), "volume_gal": sum(r["volume_gal"] for r in rows),
                      "hours": round(sum(r["hours"] for r in rows), 1)}
    return {"file": capture(name), "rows": rows, "total_row": total, "duration_label": label}


def doc():
    return {
        "watersheds": {"CSO010": "Connecticut River", "CSO036A": "Chicopee River", "CSO046": "Mill River"},
        "months": {
            "2019-02": month("Feb-2019", [("CSO 010", None, 3, 16830000, 22.5), ("CSO 036", None, 1, 506000, 1.0),
                                          ("CSO 046", None, 0, 0, 0.0)], label="H.M"),
            "2022-08": month("Aug-2022", [("CSO 010", "Connecticut River", 2, 5677000, 15.3),
                                          ("CSO-042", "Connecticut River", 1, 512424, 1.0),
                                          ("CSO 046", "Mill River", 0, 0, 0.0)]),
        },
    }


def build(d=None):
    d = d or doc()
    S.validate(d)
    recs, counts = S.build(d, {}, "2026-11-28T12:00:00Z")
    return {r["event_id"]: r for r in recs}, counts


# ---------------------------------------------------------------- records

def test_record_shape_and_month_precision():
    recs, _ = build()
    r = recs["ma-springfield-archive:MA0101613:SPR010:2019-02"]
    assert (r["event_type"], r["status"], r["time_precision"]) == ("cso", "ended", "month")
    assert (r["started_at"], r["ended_at"]) == ("2019-02-01", "2019-02-28")
    assert r["npdes_permit"] == "MA0101613" and r["discharger_id"] == "ma-springfield-wsc"
    assert r["volume_gal"] == 16830000 and r["estimate_flag"] == "unknown"
    assert r["reported_at"] is None and r["published_at"] is None          # never invented
    assert r["source_url"] == URL.format("Feb-2019")
    raw = r["raw"]
    assert raw["events"] == 3 and raw["hours"] == 22.5 and raw["duration_label"] == "H.M"
    assert raw["available_no_later_than"] == "2022-09-28" and raw["capture"]["service"] == "Internet Archive"
    assert "24 hours of dry weather" in raw["event_definition"]
    assert r["volume_text"].startswith("3 discharge events; 22.5 (printed under \"Overflow Duration (H.M)\")")
    assert r["waterbody_text"] == "Connecticut River" and raw["_water_basis"]       # 2019 reports print no water
    hours = recs["ma-springfield-archive:MA0101613:SPR010:2022-08"]
    assert hours["raw"]["duration_text"] == "15.3 hours" and hours["waterbody_text"] == "Connecticut River"


def test_monthly_mark_never_red_or_yellow():
    recs, _ = build()
    r = recs["ma-springfield-archive:MA0101613:SPR010:2019-02"]
    mark = ST.monthly_mark(r)
    assert mark and mark["month"] == "2019-02" and mark["events"] == 3 and mark["discharged"]
    assert mark["label"].startswith("3 discharge events reported for February 2019; dates not given (monthly report, "
                                    "receipt date not given)")
    assert ST.end_assumed(r, ST.parse_time("2026-11-28T00:00:00Z"), {}) is None       # no window, no unresolved
    assert charts.is_total(r)                                                       # a total, never an event


def test_crosswalk_aliases():
    assert S.outfall_of("CSO 010")[0] == "SPR010"
    assert S.outfall_of("CSO-042")[0] == "SPR042"
    assert S.outfall_of("CSO 036")[0] == "SPR036A"          # the monthly reports' 036 is the map's 036A
    assert S.outfall_of("CSO 036A")[0] == "SPR036A"
    assert S.outfall_of("CSO 037A")[0] == "SPR037"          # the annual sheets' 037A is the map's 037
    assert S.outfall_of("CSO 015B")[0] == "SPR015B"
    assert not hasattr(S, "CROSSWALK")                      # one table, the map collector's
    recs, _ = build()
    r = recs["ma-springfield-archive:MA0101613:SPR036A:2019-02"]
    assert r["raw"]["outfall_as_printed"] == "CSO 036"
    assert r["raw"]["_outfall_note"] == ("the report prints CSO 036; the commission's annual sheets and map name this "
                                         "outfall CSO 036A")


def test_zero_rows_are_not_records():
    recs, counts = build()
    assert not [k for k in recs if ":SPR046:" in k]
    assert counts["zero_rows"] == 2
    assert len(recs) == 4
    # the latest month is kept for each outfall, a zero month included (clears an older mark; build/status.py)
    assert counts["latest_month_by_outfall"]["MA0101613|SPR046"] == {"month": "2022-08", "discharged": False,
                                                                     "events": 0, "received_at": None}


# ---------------------------------------------------------------- totals

def test_rows_must_add_up_to_the_total_row():
    m = month("Mar-2019", [("CSO 010", None, 2, 100, 1.0), ("CSO 012", None, 1, 50, 0.5)])
    assert S.check_month(m["rows"], m["total_row"])["ok"]
    with pytest.raises(S.TranscriptError):
        S.check_month(m["rows"], {**m["total_row"], "volume_gal": 151})
    with pytest.raises(S.TranscriptError):
        S.check_month(m["rows"], {**m["total_row"], "events": 4})
    with pytest.raises(S.TranscriptError):            # hours beyond the rounding of two rows (0.15)
        S.check_month(m["rows"], {**m["total_row"], "hours": 1.8})
    assert S.check_month(m["rows"], {**m["total_row"], "hours": 1.6})["ok"]
    # a difference printed in the source passes only when it is exactly the listed one
    known = {"volume_gal": 1, "why": "rounding"}
    out = S.check_month(m["rows"], {**m["total_row"], "volume_gal": 151}, known)
    assert out["source_difference"] == {"volume_gal": 1, "why": "rounding"}
    with pytest.raises(S.TranscriptError):
        S.check_month(m["rows"], {**m["total_row"], "volume_gal": 152}, known)
    with pytest.raises(S.TranscriptError):            # a listed difference that is no longer there is a change too
        S.check_month(m["rows"], m["total_row"], known)


def test_a_month_that_does_not_add_up_fails_the_run(tmp_path):
    d = doc()
    d["months"]["2022-08"]["total_row"]["volume_gal"] += 1000
    ref, out = tmp_path / "ref.json", tmp_path / "events.json"
    ref.write_text(json.dumps(d))
    assert S.run(ref, out=out, ctx={}) == 1
    f = read_json(out)
    assert f["ok"] is False and "2022-08" in f["error"] and not f["records"]


def test_run_writes_the_feed(tmp_path):
    ref, out = tmp_path / "ref.json", tmp_path / "events.json"
    ref.write_text(json.dumps(doc()))
    assert S.run(ref, out=out, ctx={}) == 0
    f = read_json(out)
    assert f["ok"] and f["count"] == 4
    meta = f["meta"]
    assert meta["months"] == ["2019-02", "2022-08"] and meta["zero_event_rows"] == 2
    assert meta["covers_permits"] == ["MA0101613"] and meta["registry_ids"] == ["ma-springfield-archive"]


def test_parse_month_text():
    text = ("OVERFLOW REPORT - Springfield Water and Sewer Commission\nSEPTEMBER 2019\n(H.M)\n"
            "CSO 007 1 64,000 0.5 RG01 3.56\nCSO 036 1 506,000 1.0\nCSO-042 Connecticut River 2 2,323,133 2.1\n"
            "Total 38.75 2,893,133 3.6\n*A storm event is any period of precipitation which is preceded and "
            "followed\nby 24 hours of dry weather:")
    m = S.parse_month(text.replace(" ", " "), "2019-09")
    assert [r["outfall"] for r in m["rows"]] == ["CSO 007", "CSO 036", "CSO 042"]
    assert m["rows"][2] == {"outfall": "CSO 042", "watershed": "Connecticut River", "events": 2,
                            "volume_gal": 2323133, "hours": 2.1}
    assert m["total_row"] == {"events": 38.75, "volume_gal": 2893133, "hours": 3.6}
    assert m["duration_label"] == "H.M"
    with pytest.raises(S.TranscriptError):
        S.parse_month(text, "2019-10")                 # the title names another month
    with pytest.raises(S.TranscriptError):
        S.check_month(m["rows"], m["total_row"])       # 38.75 events printed, 4 in the rows


# ---------------------------------------------------------------- October 2021

ANNUAL_URL = "https://springfieldalerts.com/Suez/wp-content/uploads/2022/03/CSO-Overflow-Volumes-2021.pdf"


def with_october(oct_line=31039264, entry=None):
    """The fixture plus an annual 2021 sheet (two outfalls; month lines adding up to the System Total) and the October
    entry the extraction writes."""
    d = doc()
    lines = {f"2021-{i:02d}": 1000 for i in range(1, 13)}
    lines["2021-10"] = oct_line
    total = sum(lines.values())
    d["annual"] = {"2021": {"file": {**capture("Overflow-Volumes-2021"), "name": "CSO-Overflow-Volumes-2021.pdf",
                                     "url": ANNUAL_URL},
                            "rows": [{"outfall": "CSO 010", "watershed": "Connecticut River", "events": 30,
                                      "volume_gal": total - 500},
                                     {"outfall": "CSO 046", "watershed": "Mill River", "events": 5, "volume_gal": 500}],
                            "system_total": {"events": 35, "volume_gal": total}, "monthly_volume_gal": lines}}
    d["months"]["2021-10"] = entry or S.sheet_month(d["annual"]["2021"], "2021-10")
    return d


def test_october_2021_is_one_record_of_the_sheets_printed_line():
    """Astra review 2026-11-28 P2: no per-outfall October records; one record, no outfall, the gallons the annual
    sheet prints for October (not computed), citing the sheet and its capture, saying the report is not online."""
    recs, counts = build(with_october())
    octs = [r for r in recs.values() if r["started_at"].startswith("2021-10")]
    [r] = octs
    assert r["event_id"] == "ma-springfield-archive:MA0101613:all-outfalls:2021-10"
    assert r["outfall_id"] is None and r["waterbody_text"] is None and r["lat"] is None
    assert r["npdes_permit"] == "MA0101613" and r["event_type"] == "cso" and r["time_precision"] == "month"
    assert (r["started_at"], r["ended_at"]) == ("2021-10-01", "2021-10-31")
    assert r["reported_at"] is None and r["published_at"] is None
    # the permit-wide figure is text and raw only: the record sits on five waters and must not sum on each
    assert r["volume_gal"] is None and r["raw"]["volume_gal"] == 31039264 and r["source_url"] == ANNUAL_URL
    assert r["volume_text"] == "31,039,264 gallons, all outfalls combined, from the commission's 2021 annual sheet"
    raw = r["raw"]
    assert raw["permit_level"] is True and "computed" not in raw and "events" not in raw and "hours" not in raw
    assert raw["available_no_later_than"] == "2022-09-28" and raw["capture"]["service"] == "Internet Archive"
    assert raw["volume_basis"].startswith("Printed by the commission: the October line of the \"Discharge Summary By "
                                          "Month\" table on its 2021 annual sheet") and "Not computed" in raw["volume_basis"]
    assert raw["public_note"] == (
        "October 2021 total for all outfalls combined, as printed on the commission's 2021 annual sheet (not "
        "computed). The commission's monthly report for October 2021 is not on its CSO Data Archive page (the page's "
        "link to it is broken), so no per-outfall figures are published for the month. The sheet gives no event count "
        "or hours for the month.")
    mark = ST.monthly_mark(r)
    assert mark["discharged"] and mark["events"] is None and mark["month"] == "2021-10"
    assert not [k for k in counts["latest_month_by_outfall"] if "all-outfalls" in k]
    assert len(recs) == 5


def test_october_2021_must_be_the_sheets_line():
    """Astra review 2026-11-28 P3: the October entry is checked against the annual sheet's printed line."""
    d = with_october()
    d["months"]["2021-10"]["volume_gal"] += 1
    with pytest.raises(S.TranscriptError, match="annual sheet's line"):
        S.validate(d)
    d = with_october()
    d["annual"]["2021"]["monthly_volume_gal"]["2021-03"] += 5        # the month lines no longer meet the System Total
    with pytest.raises(S.TranscriptError, match="System Total"):
        S.validate(d)
    d = with_october()
    d["months"]["2021-10"]["rows"] = [{"outfall": "CSO 010", "events": 1, "volume_gal": 5, "hours": None}]
    with pytest.raises(S.TranscriptError):
        S.validate(d)
    d = with_october()
    del d["annual"]
    with pytest.raises(S.TranscriptError):
        S.validate(d)


def test_no_month_skips_reconciliation_for_a_method():
    """Astra review 2026-11-28 P3: a month carrying a method (or marked computed) fails; it is never exempt."""
    d = doc()
    d["months"]["2022-08"]["method"] = {"volume": "computed"}
    with pytest.raises(S.TranscriptError, match="computed"):
        S.validate(d)
    d = doc()
    d["months"]["2022-08"]["computed"] = True
    d["months"]["2022-08"]["rows"][0]["volume_gal"] = 999_999_999
    with pytest.raises(S.TranscriptError):
        S.validate(d)
    assert not hasattr(S, "compute_october") and not hasattr(S, "COMPUTED_MONTH")


def test_known_difference_must_be_the_codes():
    """Astra review 2026-11-28 P3: a transcript allowance the code does not list fails, and the check uses the
    code's value, never the transcript's."""
    d = doc()
    d["months"]["2019-02"]["rows"][0]["volume_gal"] += 1_000_000
    d["months"]["2019-02"]["known_difference"] = {"volume_gal": -1_000_000, "why": "invented"}
    with pytest.raises(S.TranscriptError, match="KNOWN_DIFFERENCES"):
        S.validate(d)
    # a listed month: the transcript must carry the code's entry; an altered one fails
    rows = [("CSO 010", None, 2, 100, 1.0)]
    m = month("Mar-2019", rows, total={"events": 2, "volume_gal": 101, "hours": 1.0})
    d = {"watersheds": {}, "months": {"2019-03": {**m, "known_difference": S.KNOWN_DIFFERENCES["2019-03"]}}}
    S.validate(d)
    d["months"]["2019-03"]["known_difference"] = {"volume_gal": 1, "why": "something else"}
    with pytest.raises(S.TranscriptError, match="KNOWN_DIFFERENCES"):
        S.validate(d)
    del d["months"]["2019-03"]["known_difference"]
    with pytest.raises(S.TranscriptError, match="KNOWN_DIFFERENCES"):
        S.validate(d)


def _chart(recs, kind="discharger"):
    import types
    from datetime import UTC, datetime
    b = charts.Bucket(kind, "example")
    b.state = "MA"
    b.totals = list(recs)
    waters = {"example": {"slug": "example", "name": "Example River", "kind": "river", "state": "MA"}}
    data = types.SimpleNamespace(history={}, status={}, waters=waters, by_id={}, dropped={}, effective={},
                                 placements={}, now=datetime(2026, 11, 28, tzinfo=UTC), rules={}, events=[],
                                 dischargers={})
    doc_ = charts.build_entity(b, data, {}, {}, "Example")
    [tot] = doc_["charts"]["reported_totals"]
    return tot["x"], {s["key"]: s["values"] for s in tot["series"]}


def test_chart_totals_never_turn_a_missing_volume_into_zero():
    """Astra review 2026-11-28 P2: a record of this source with no volume is null in the totals, never 0.0; a month
    with no record stays 0 (the source lists every month); on a water's chart the all-outfalls October figure is
    unknown (it is for every water of the permit combined); the record carries no summable volume at all, so the
    operator's chart is unknown too and no export or CSV can add it to a water (pass 2)."""
    recs, _ = build(with_october())
    by = {r["started_at"][:7]: r for r in recs.values() if r["outfall_id"] in (None, "SPR010")}
    sep = {**by["2021-10"], "event_id": "x:2021-09", "started_at": "2021-09-01", "ended_at": "2021-09-30",
           "volume_gal": None}
    x, s = _chart([by["2021-10"], sep, by["2022-08"]])
    assert x[:2] == ["2021-09", "2021-10"]
    assert s["gallons"][0] is None and s["gallons"][1] is None     # October: printed in the text, not summed
    assert s["gallons"][2] == 0.0 and s["gallons"][-1] == 5677000.0          # November 2021: no record, no events
    x, s = _chart([by["2021-10"], by["2022-08"]], kind="water")
    assert s["gallons"][0] is None and s["gallons"][-1] == 5677000.0
    other = {**sep, "source_id": "xx-example-monthly"}
    assert _chart([other, {**by["2021-10"], "source_id": "xx-example-monthly", "volume_gal": 31039264}])[1]["gallons"][0] == 0.0


# ---------------------------------------------------------------- overlap and the committed transcript

def test_overlap_rule_months_stand_beside_event_records():
    ov = S.overlap(["2019-01", "2022-02", "2022-03", "2022-07", "2023-04"])
    by = {s["source_id"]: s for s in ov["event_level_sources"]}
    assert by["ma-springfield-aquasight"]["months"] == ["2022-03", "2023-04"]
    assert by["ma-massdep"]["months"] == ["2022-07", "2023-04"] and by["ma-massdep"]["count"] == 2
    recs, _ = build()
    r = recs["ma-springfield-archive:MA0101613:SPR010:2022-08"]
    assert r["duplicate_of"] is None                       # emitted, a total beside the events
    assert ST.RANK["monthly"] < min(ST.RANK["yellow"], ST.RANK["red"], ST.RANK["unresolved"])
    assert charts.is_total(r)


def test_committed_transcript():
    d = json.loads(S.REFERENCE.read_text())
    months = S.validate(d)
    assert months[0] == "2019-01" and months[-1] == "2023-04" and len(months) == 52
    assert d["hand_corrections"] == []
    oc = d["months"]["2021-10"]
    assert oc == {"report_online": False, "why": S.SHEET_MONTHS["2021-10"], "from_annual_sheet": "2021",
                  "volume_gal": 31039264, "events": None, "hours": None}
    assert d["annual"]["2021"]["monthly_volume_gal"]["2021-10"] == 31039264     # the sheet's own October line
    for ym, m in d["months"].items():
        assert "computed" not in m and "method" not in m
        if ym not in S.SHEET_MONTHS:
            assert m["check"]["ok"] and m["file"]["url"].startswith("https://springfieldalerts.com/Suez/")
            assert ("capture" in m["file"]) != ("sha256" in m["file"])
    recs, counts = S.build(d, {}, "2026-11-28T12:00:00Z")
    assert len(recs) == 736 and counts["zero_rows"] == 458
    assert all(r["time_precision"] == "month" for r in recs)
    [oct_] = [r for r in recs if r["started_at"].startswith("2021-10")]
    assert oct_["outfall_id"] is None and oct_["volume_gal"] is None and oct_["raw"]["volume_gal"] == 31039264
    assert oct_["raw"]["available_no_later_than"] == "2022-09-28" and oct_["source_url"].endswith("Volumes-2021.pdf")
    assert all(r["outfall_id"].startswith("SPR") for r in recs if r is not oct_)


def test_export_detail_and_chart_label():
    from export import detail
    recs, _ = build()
    d = detail.detail_of(recs["ma-springfield-archive:MA0101613:SPR010:2022-08"])
    assert d["report_kind"] == "Monthly overflow report" and d["duration_text"] == "15.3 hours"
    assert "volume_method" not in d and "notes" not in d    # a reported figure: no method of ours
    recs, _ = build(with_october())
    d = detail.detail_of(recs["ma-springfield-archive:MA0101613:all-outfalls:2021-10"])
    assert d["report_kind"] == "Annual summary, month line" and "volume_method" not in d
    assert d["notes"].startswith("October 2021 total for all outfalls combined, as printed on the commission's 2021 "
                                 "annual sheet (not computed).")
    assert charts.SOURCE_LABEL["ma-springfield-archive"].startswith("Springfield Water and Sewer Commission monthly")
