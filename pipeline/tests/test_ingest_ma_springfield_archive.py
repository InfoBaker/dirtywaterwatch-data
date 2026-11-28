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

def year_2021(oct_line, revisions=None, annual_extra=None):
    """Eleven months of two outfalls (CSO 010: 1 event, 100 gal a month; CSO 024: none), and an annual sheet whose
    October line is oct_line and whose month lines carry the given revisions."""
    months = {}
    for i in range(1, 13):
        if i == 10:
            continue
        ym = f"2021-{i:02d}"
        months[ym] = month(ym, [("CSO 010", "Connecticut River", 1, 100, 1.0), ("CSO 024", "Mill River", 0, 0, 0.0)])
        months[ym]["file"]["url"] = f"https://example.org/{ym}.pdf"
    lines = {f"2021-{i:02d}": 100 + (revisions or {}).get(f"2021-{i:02d}", 0) for i in range(1, 13)}
    lines["2021-10"] = oct_line
    extra = annual_extra or {}
    annual = {"file": {"url": "https://example.org/annual-2021.pdf"},
              "rows": [{"outfall": "CSO 010", "watershed": "Connecticut River", "events": 11 + extra.get("ev010", 0),
                        "volume_gal": 1100 + extra.get("gal010", 0)},
                       {"outfall": "CSO 024", "watershed": "Mill River", "events": extra.get("ev024", 0),
                        "volume_gal": extra.get("gal024", 0)}],
              "monthly_volume_gal": lines, "system_total": {"events": 11 + sum(v for k, v in extra.items() if k[:2] == "ev")}}
    return months, annual


def test_october_2021_computed_and_worded():
    months, annual = year_2021(500, annual_extra={"ev010": 2, "gal010": 500})
    oc = S.compute_october(months, annual)
    assert oc["computed"] and oc["unplaced_gal"] == 0 and not oc["not_published"]
    [row] = oc["rows"]
    assert (row["outfall"], row["events"], row["volume_gal"], row["hours"]) == ("CSO 010", 2, 500, None)
    assert row["figures_published"] is True
    d = {"watersheds": {}, "months": {**months, "2021-10": oc}}
    recs, _ = build(d)
    r = recs["ma-springfield-archive:MA0101613:SPR010:2021-10"]
    assert r["volume_gal"] == 500 and r["volume_text"] == "2 discharge events (computed); 500 gallons (computed)"
    assert r["raw"]["computed"] is True and r["raw"]["report_kind"] == "Computed from the annual sheet"
    assert r["raw"]["volume_method"].startswith("Computed by us: the outfall's 2021 total on the commission's annual "
                                                "sheet minus the sum of its other eleven monthly reports")
    assert r["raw"]["volume_basis"] == ("2021 annual sheet 1,600 gallons minus 1,100 gallons in the other eleven "
                                        "monthly reports")
    assert r["source_url"] == "https://example.org/annual-2021.pdf" and r["raw"]["hours"] is None   # the sheet has none
    assert ST.monthly_mark(r)["events"] == 2


def test_october_2021_revision_of_another_month_is_not_october():
    # May's line exceeds May's report by 7,000 gallons, CSO 024's whole difference: that is May's, not October's
    months, annual = year_2021(500, revisions={"2021-05": 7000},
                               annual_extra={"ev010": 2, "gal010": 500, "ev024": 1, "gal024": 7000})
    oc = S.compute_october(months, annual)
    assert [r["outfall"] for r in oc["rows"]] == ["CSO 010"] and oc["rows"][0]["figures_published"]
    [skip] = oc["not_published"]
    assert skip["outfall"] == "CSO 024" and "revision of 2021-05" in skip["why"]
    assert oc["revisions"] == {"2021-05": {"gallons": 7000, "outfall": "CSO 024"}}


def test_october_2021_unplaced_revision_withholds_figures():
    # August's line exceeds August's report by 60 gallons that match no outfall: CSO 010 (530 left) still discharged
    # in October, but its count and gallons are not given; an outfall whose difference is under 60 is not shown
    months, annual = year_2021(500, revisions={"2021-08": 60},
                               annual_extra={"ev010": 2, "gal010": 530, "ev024": 1, "gal024": 30})
    oc = S.compute_october(months, annual)
    [row] = oc["rows"]
    assert row["outfall"] == "CSO 010" and row["figures_published"] is False
    [skip] = oc["not_published"]
    assert skip["outfall"] == "CSO 024" and "not more than the 60 gallons" in skip["why"]
    assert oc["method"]["withheld"].startswith("The annual sheet's figures for August 2021 are higher than those "
                                               "months' reports by 60 gallons")
    recs, _ = build({"watersheds": {}, "months": {**months, "2021-10": oc}})
    r = recs["ma-springfield-archive:MA0101613:SPR010:2021-10"]
    assert r["volume_gal"] is None and "events" not in r["raw"]
    assert r["volume_text"] == "computed from the commission's 2021 annual sheet; count and gallons not given"
    assert "We show only outfalls whose difference is larger than that" in r["raw"]["volume_method"]
    mark = ST.monthly_mark(r)
    assert mark["discharged"] and mark["events"] is None


def test_october_2021_negative_difference_not_published():
    months, annual = year_2021(498, annual_extra={"ev010": 2, "gal010": 499})
    months["2021-03"]["rows"][1].update(events=0, volume_gal=1)     # CSO 024: 1 gallon in March, 0 on the sheet
    months["2021-03"]["total_row"]["volume_gal"] += 1
    annual["monthly_volume_gal"]["2021-03"] += 1
    oc = S.compute_october(months, annual)
    assert [r["outfall"] for r in oc["not_published"]] == ["CSO 024"]
    assert "negative" in oc["not_published"][0]["why"]


def test_october_2021_must_meet_the_sheet():
    months, annual = year_2021(900, annual_extra={"ev010": 2, "gal010": 500})       # 500 left, the sheet says 900
    with pytest.raises(S.TranscriptError):
        S.compute_october(months, annual)


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
    assert oc["computed"] and oc["unplaced_gal"] == 149000
    assert {r["outfall"] for r in oc["rows"]} == {"CSO 010", "CSO 012", "CSO 013", "CSO 014", "CSO 016", "CSO 045",
                                                  "CSO 049"}
    assert not any(r["figures_published"] for r in oc["rows"])
    assert oc["revisions"]["2021-05"] == {"gallons": 11554000, "outfall": "CSO 024"}
    assert oc["revisions"]["2021-07"] == {"gallons": 6944000, "outfall": "CSO 042"}
    for ym, m in d["months"].items():
        if not m.get("computed"):
            assert m["check"]["ok"] and m["file"]["url"].startswith("https://springfieldalerts.com/Suez/")
            assert ("capture" in m["file"]) != ("sha256" in m["file"])
    recs, counts = S.build(d, {}, "2026-11-28T12:00:00Z")
    assert len(recs) == 742 and counts["zero_rows"] == 458
    assert all(r["time_precision"] == "month" and r["outfall_id"].startswith("SPR") for r in recs)


def test_export_detail_and_chart_label():
    from export import detail
    recs, _ = build()
    d = detail.detail_of(recs["ma-springfield-archive:MA0101613:SPR010:2022-08"])
    assert d["report_kind"] == "Monthly overflow report" and d["duration_text"] == "15.3 hours"
    assert "volume_method" not in d                       # a reported figure: no method of ours
    months, annual = year_2021(500, revisions={"2021-08": 60},
                               annual_extra={"ev010": 2, "gal010": 530, "ev024": 1, "gal024": 30})
    recs, _ = build({"watersheds": {}, "months": {**months, "2021-10": S.compute_october(months, annual)}})
    d = detail.detail_of(recs["ma-springfield-archive:MA0101613:SPR010:2021-10"])
    assert d["report_kind"] == "Computed from the annual sheet" and d["volume_method"].startswith("Computed by us")
    assert charts.SOURCE_LABEL["ma-springfield-archive"].startswith("Springfield Water and Sewer Commission monthly")
