"""Washington DC: the ECHO receiving-water alias table and the out-of-District rule, the DC Water news list
parser and notice reader, the ECHO duplicate link, and the DC water builder (no network)."""
import json
from datetime import date
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from common import ROOT
from ingest import dc_water_news as N
from ingest import dc_waters as W
from ingest import echo_sewer_overflow_events as E

FIX = Path(__file__).parent / "fixtures"
RESEARCH_WATERS = ROOT / "research" / "dc" / "waters-dc.json"


# ---------------------------------------------------------------- ECHO: names and state

def test_alias_table_normalises_free_text():
    n = E.normalise_dc_water
    assert n("Rock Creek ") == "Rock Creek"            # trailing space
    assert n("ROCK CREEK") == "Rock Creek"
    assert n("Anacostia river") == "Anacostia River"
    assert n("Hickory Run") == "Hickey Run" and n("Hickory RUN") == "Hickey Run"
    assert n("Watts Branch Creek") == "Watts Branch"
    assert n("soapstone") == "Soapstone Valley stream" and n("Soapstone Stream") == "Soapstone Valley stream"
    assert n("@PARK RD @PINEY BRANCH PKY NW") == "Piney Branch"
    assert n("Potomac River, East Side") == "Potomac River"
    assert n("C&O Canal") == "Chesapeake and Ohio Canal"
    assert n(" Some Unnamed Ditch ") == "Some Unnamed Ditch"   # not in the table: kept as typed, stripped


@pytest.mark.skipif(not RESEARCH_WATERS.exists(), reason="research/dc/waters-dc.json not present")
def test_alias_table_covers_the_research_file():
    specs = json.loads(RESEARCH_WATERS.read_text())["waters"]
    for s in specs:
        assert E.normalise_dc_water(s["name"]) == s["name"], s["name"]
        for alias in W.clean_aliases(s):
            assert E.normalise_dc_water(alias) == s["name"], (s["name"], alias)


def test_out_of_district_rule():
    assert E.dc_row_state(38.813611, -77.0275) == (None, None)     # Blue Plains, in the District
    assert E.dc_row_state(38.904724, -77.076385) == (None, None)   # CSO 029, Canal Road
    assert E.dc_row_state(38.9022, -77.0707) == (None, None)       # Key Bridge: the District takes in the river
    assert E.dc_row_state(None, None) == (None, None)
    state, basis = E.dc_row_state(38.949607, -77.127348)           # Interceptor collapse, Montgomery County
    assert state == "MD" and "operator unchanged" in basis
    assert E.dc_row_state(39.037901, -77.282721)[0] == "MD"        # Interceptor overflow near Seneca, 2024


def _row(**kw):
    base = {"permit_identifier": "DC0021199", "program_report_form_set_id": "1", "program_report_form_id": "1",
            "sewer_overflow_bypass_event_key": "1", "sewer_overflow_bypass_event_id_ext": "1",
            "sewer_overflow_bypass_description_text": "", "sewer_overflow_structure_type_code": "",
            "sewer_overflow_structure_type_desc": "", "sewer_overflow_structure_type_code_other_text": "",
            "collection_system_identifier": "", "permitted_feature_identifier": "", "latitude_measure": "",
            "longitude_measure": "", "sewer_overflow_bypass_start_datetime": "2026-01-19 17:03:00",
            "sewer_overflow_bypass_end_datetime": "", "discharge_quantification_method_desc": "Best Professional Judgement",
            "sewer_overflow_bypass_discharge_volume_gallons": "", "program_report_received_date": "2026-01-20",
            "program_report_npdes_data_group_number_code": "", "program_report_start_date": "", "program_report_end_date": ""}
    base.update(kw)
    return base


def test_build_dc_rows():
    tables = {
        "events": [
            _row(sewer_overflow_bypass_event_key="1", latitude_measure="38.949607", longitude_measure="-77.127348",
                 sewer_overflow_bypass_discharge_volume_gallons="242000000.00"),
            _row(sewer_overflow_bypass_event_key="2", program_report_form_set_id="2", latitude_measure="38.9150",
                 longitude_measure="-76.9650", sewer_overflow_bypass_start_datetime="2025-05-04 10:00:00"),
            _row(sewer_overflow_bypass_event_key="3", program_report_form_set_id="3", latitude_measure="38.9300",
                 longitude_measure="-77.0400", sewer_overflow_bypass_start_datetime="2025-06-01 10:00:00"),
        ],
        "types": [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": "SSO",
                   "sewer_overflow_bypass_type_desc": "Sanitary Sewer Overflow", "sewer_overflow_bypass_type_code_sequence": "1"}
                  for k in "123"],
        "waters": [{"sewer_overflow_bypass_event_key": "1", "name_receiving_water": "Potomac River"},
                   {"sewer_overflow_bypass_event_key": "2", "name_receiving_water": "Hickory Run"},
                   {"sewer_overflow_bypass_event_key": "3", "name_receiving_water": "Rock Creek "}],
    }
    kept, dropped, _ = E.build(tables, {"extract_date": "2026-11-02", "last_modified": None})
    by = {r["source_record_id"]: r for r in kept}
    assert len(kept) == 3 and not dropped
    pi = by["DC0021199:1:1"]
    # out of the District: state MD for placement; permit, operator and the text as reported are unchanged
    assert pi["raw"]["state"] == "MD" and pi["npdes_permit"] == "DC0021199"
    assert pi["discharger_id"] == "dc-dc0021199" and pi["waterbody_text"] == "Potomac River"
    assert pi["volume_gal"] == 242_000_000
    hr = by["DC0021199:2:1"]
    assert "state" not in hr["raw"]
    assert hr["waterbody_text"] == "Hickey Run" and hr["raw"]["receiving_waters"] == ["Hickory Run"]
    assert hr["raw"]["receiving_water_aliases"] == {"Hickory Run": "Hickey Run"}
    rc = by["DC0021199:3:1"]
    assert rc["waterbody_text"] == "Rock Creek" and rc["raw"]["receiving_waters"] == ["Rock Creek "]   # trailing space kept in raw
    assert "DC" in E.STATES


# ---------------------------------------------------------------- DC Water news

def _items(*names):
    out = []
    for i, n in enumerate(names):
        out += [(i, it) for it in N.parse_list((FIX / n).read_text())]
    return out


def test_parse_list_pages():
    p0 = N.parse_list((FIX / "dc_news_page0.html").read_text())
    assert [i["date_text"] for i in p0] == ["19 January, 2026", "14 January, 2026", "9 January, 2026", "8 January, 2026"]
    assert p0[0]["title"].startswith("DC Water Investigating Sanitary Sewer Overflow")
    assert p0[0]["url"] == "https://www.dcwater.com/about-dc-water/media/news/dc-water-investigating-sanitary-sewer-overflow-potomac-interceptor"
    assert "Drinking water is not impacted" in p0[0]["summary"]
    assert all("Board of Directors" not in i["title"] for i in p0)        # the sidebar's event row has no news date
    p1 = N.parse_list((FIX / "dc_news_page1.html").read_text())
    assert len(p1) == 4 and p1[2]["summary"].count("overflow") >= 2
    assert N.parse_item_date("16  August,  2025") == date(2025, 8, 16)


def test_notice_text():
    t = N.parse_notice((FIX / "dc_news_notice_force_main.html").read_text())
    assert t.startswith("DC Water is advising the public of a Sanitary Sewer Overflow")
    assert "EMERGENCY WATER OUTAGE" not in t                       # only the news body field
    assert "Leave the area immediately." in t.split("\n")
    assert N.advice_of(t).startswith("If people come in contact with the untreated overflow")


def test_news_events(tmp_path):
    (tmp_path / "notices").mkdir()
    slug = "dc-water-advises-public-unexpected-sewer-overflow-anacostia-force-main"
    (tmp_path / "notices" / f"{slug}.html").write_text((FIX / "dc_news_notice_force_main.html").read_text())
    items = _items("dc_news_page0.html", "dc_news_page1.html")
    recs, _, why = N.build(items, tmp_path, {})
    assert len(recs) == 3
    # the force-main SSO: hour and water from the notice, volume from its estimate, the advice sentence
    fm = next(r for r in recs if r["source_record_id"] == slug)
    assert fm["event_id"] == f"dc-water-news:{slug}" and fm["source_id"] == "dc-water-news"
    assert fm["event_type"] == "sso" and fm["npdes_permit"] == "DC0021199" and fm["discharger_id"] == "dc-dc0021199"
    assert fm["started_at"] == "2025-08-16T01:40:00" and fm["time_precision"] == "minute"
    assert fm["published_at"] == "2025-08-16" and fm["waterbody_text"] == "Anacostia River"
    assert fm["volume_gal"] == 6200 and fm["raw"]["notice_fetched"] is True
    assert fm["advice_text"].startswith("If people come in contact") and fm["source_url"].endswith(slug)
    assert fm["lat"] is None and fm["duplicate_of"] is None and fm["raw"].get("state") is None
    # the first public notice of the 2025 force-main SSO: ongoing, 'approximately' makes the figure an estimate, day precision
    nb = next(r for r in recs if r["source_record_id"].startswith("public-notice"))
    assert nb["status"] == "ongoing" and nb["time_precision"] == "day" and nb["started_at"] == "2025-07-21"
    assert nb["volume_gal"] == 6200 and nb["estimate_flag"] == "estimated" and nb["waterbody_text"] is None
    # the Potomac Interceptor notice is placed in Maryland, operator DC Water
    pi = next(r for r in recs if "potomac-interceptor" in r["source_record_id"])
    assert pi["raw"]["state"] == "MD" and pi["npdes_permit"] == "DC0021199" and pi["started_at"] == "2026-01-19"
    # kept but not events, with the reason; unrelated items are not kept at all
    assert "precautionary notice of a possible overflow" in why and "reports no overflow" in why
    assert sum(len(v) for v in why.values()) == 2


def test_notice_reading_rules():
    def one(title, summary, published):
        it = {"title": title, "summary": summary, "date_text": published, "url": N.BASE + N.NEWS_PATH + "x"}
        return N.classify(it, None)
    # the weekday is read from the notice's date: a Tuesday notice, an overflow 'late Monday night'
    f, _ = one("UPDATE: Repairs, February 10", "An overflow occurred late Monday night, when two pumps were taken out of service.",
               "10 February, 2026")
    assert f["started_at"] == "2026-02-09" and f["precision"] == "day"
    # an update about an overflow dated more than two days earlier is a follow-up, not a new discharge
    f, why = one("UPDATE: Overflow, January 31", "Crews continue work on the sanitary sewer overflow that occurred on January 19.",
                 "31 January, 2026")
    assert f is None and "follow-up" in why
    # no overflow, a plan, a possible overflow, a history sentence: not events
    assert one("UPDATE: Repairs", "No overflows reached the river for 19 days.", "27 February, 2026")[0] is None
    assert one("Testing", "Testing began after the collapse caused wastewater to overflow into the river.", "7 October, 2026")[0] is None
    assert one("Notice", "An overflow may occur this evening if heavy rain arrives.", "7 October, 2026")[0] is None
    # a flow rate is not a volume
    f, _ = one("DC Water Advises Public of Sewer Overflow", "A sewer overflow occurred today near a pumping station. The line carries about 60 million gallons daily.",
               "7 October, 2026")
    assert f["volume"] is None
    # combined sewer overflow -> cso
    f, _ = one("DC Water Advises Public of Combined Sewer Overflow", "A combined sewer overflow occurred this morning into Rock Creek.", "7 October, 2026")
    assert f["cso"] is True and f["waters"] == ["Rock Creek"]
    # street names are not waters
    assert N.water_names("The overflow reached Anacostia Avenue and the Rock Creek and Potomac Parkway.") == []
    # an advice sentence never keeps a staff name or a phone number
    adv = N.advice_of("If people come in contact with the untreated overflow, they should contact Jane Doe at (202) 555-0100.")
    assert "Jane Doe" not in adv and "555-0100" not in adv


def test_sentences_keep_times_together():
    assert N.sentences("At approximately 1:40 a.m. the line failed. It ended at 3 p.m. today.")[0] == "At approximately 1:40 a.m. the line failed."


def test_link_to_echo_rows():
    rows = [{"event_id": "echo:a", "started_at": "2025-07-20T20:02:00", "ended_at": "2025-07-21T15:00:00", "waterbody_text": "Anacostia River"},
            {"event_id": "echo:b", "started_at": "2026-01-19T17:03:00", "ended_at": "2026-01-27T10:10:00", "waterbody_text": "Potomac River"},
            {"event_id": "echo:c", "started_at": "2026-05-20T09:00:00", "ended_at": None, "waterbody_text": "Pope Branch"}]
    def rec(day, water):
        return {"started_at": day, "waterbody_text": water, "duplicate_of": "stale"}
    a, b, c, d, e = (rec("2025-07-21", None), rec("2026-01-24", "Potomac River"), rec("2026-01-24", "Rock Creek"),
                     rec("2025-08-16T01:40:00", "Anacostia River"), rec("2026-05-20", "Pope Branch"))
    assert N.link_duplicates([a, b, c, d, e], rows) == 3
    assert a["duplicate_of"] == "echo:a"      # no water named, one row that day
    assert b["duplicate_of"] == "echo:b"      # inside the row's start-to-end days, same water
    assert c["duplicate_of"] is None          # another water
    assert d["duplicate_of"] is None          # no ECHO row for 16 August 2025 (the research found none)
    assert e["duplicate_of"] == "echo:c"
    # two rows that day and no water named: ambiguous, left alone
    amb = rec("2026-01-19", None)
    N.link_duplicates([amb], [*rows, {"event_id": "echo:d", "started_at": "2026-01-19T01:00:00", "ended_at": None, "waterbody_text": "Rock Creek"}])
    assert amb["duplicate_of"] is None


# ---------------------------------------------------------------- DC water records

def test_clip_and_record_shape():
    box = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    g = W.clip_paths([[(-1, 0.5), (0.5, 0.5), (2, 0.5)], [(5, 5), (6, 6)]], box)
    assert g.geom_type == "MultiLineString" and g.bounds == (0.0, 0.5, 1.0, 0.5)
    assert W.clip_paths([[(5, 5), (6, 6)]], box) is None
    spec = {"proposed_slug": "x-run-dc", "name": "X Run", "kind": "channel", "nhd_gnis_name": "X Run", "gnis_id": "00000001",
            "wikidata": None, "source_aliases": ["X Run", "x run ", "X Creek", "WB-1, WB-2 (ARK)", "X Run Tributary (SOBE text)"], "note": "a note"}
    feats = [{"attributes": {"reachcode": "0207", "fcode": 46000}}]
    rec = W.build_record(spec, g, feats, "2026-11-03T00:00:00Z")
    assert rec["slug"] == "x-run-dc" and rec["state"] == "DC" and rec["towns"] == ["Washington"] and rec["source"] == "nhd"
    assert rec["kind"] == "bay" and rec["aliases"] == ["X Creek", "X Run Tributary"]   # the name, a case twin and a station code dropped
    assert rec["gnis_id"] == "00000001" and rec["reachcodes"] == ["0207"] and rec["bbox"] == [0.0, 0.5, 1.0, 0.5]
    assert rec["geometry"]["type"] == "MultiLineString" and rec["launches"] == [] and rec["length_km"] > 0


@pytest.mark.skipif(not (ROOT / "research" / "dc" / "raw" / "dcgis" / "dc-boundary.json").exists(), reason="research boundary copy not present")
def test_district_outline_is_the_dc_gis_polygon():
    poly = W.polygon_from_esri(json.loads((ROOT / "research" / "dc" / "raw" / "dcgis" / "dc-boundary.json").read_text()))
    assert poly.is_valid and 170 < poly.area * 111.32 * 86.5 < 182      # about 177 km2
    assert W.in_district(38.8899, -77.0091, poly) and not W.in_district(38.949607, -77.127348, poly)
