"""The state assessments beside a water's status (build/attains.py, docs/attains.md): name normalisation, the geometry
gate, each organization's latest cycle, the sewage-source kinds, the summary counts, the export's block (a missing or
stale cache shows nothing and never fails), no key needed, no address or service text in a saved error, and the
weekly workflow's state objects. Synthetic zips and geometry only; no network. Run from pipeline/:
python -m pytest tests -q
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import attains as A  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
KEY = "test-key-value-not-real"
MAIL = "pat" + "@" + "example.org"           # an e-mail address made up for the privacy fixtures
PHONE = "901-555-0123"

# ---------------------------------------------------------------- names


@pytest.mark.parametrize("water,au", [
    ("Allatoona Lake", "Lake Allatoona"),
    ("Black Bayou", "BLACK BAYOU"),
    ("Allen's Creek", "Allens Cr."),
    ("Mississippi River", "Upper Mississippi River"),
    ("Anacostia River", "Tidal Anacostia River"),
    ("Cumberland River", "Cumberland River Embayment"),
    ("Cumberland River", "Cumberland River - Old Hickory Lake to Cheatham Dam"),
    ("Cheatham Reservoir", "Cumberland River (Cheatham Reservoir)"),
    ("Mount Hope Bay", "Mt. Hope Bay"),
    ("Saint Croix River", "St. Croix River"),
    ("Larrys Creek", "Larrys Creek-66911819"),
    ("Charles River", "Charles River (MA72-36)"),
    ("Kentucky Lake", "Kentucky Reservoir"),
    ("Lake Barkley", "Barkley Reservoir"),
    ("Caney Fork", "Caney Fork River"),
    ("South Fork Roanoke River", "S.F. Roanoke River"),
    ("East Fork Lewis River", "LEWIS RIVER, E.F."),
    ("East Passage", "DALCO PASSAGE AND EAST PASSAGE"),
    ("Drayton Passage", "NISQUALLY REACH/DRAYTON PASSAGE"),
    ("Staunton River / Roanoke River", "Roanoke (Staunton) River"),
    ("Kerr Lake;Buggs Island Lake", "Kerr Reservoir"),
    ("Lake Cochituate (Middle Pond)", "Lake Cochituate"),
    ("Blackwater River", "Smith Mtn. Lake (Blackwater River)"),
    ("Watts Bar Lake", "Emory River Embayment of Watts Bar Reservoir"),
    ("Black River", "Black River from Mill Creek to the state line"),
    ("Ten Mile River", "Ten Mile River"),
    ("Ohio River", "Ohio River Mile 0 to 40"),
    ("South Fork of Wildcat Creek", "WILDCAT CREEK, SOUTH FORK (OSRW)"),
    ("Lake George", "GEORGE, LAKE"),
    ("Río Portugués", "RIO PORTUGUES"),
    ("Six Mile Run", "Sixmile Run (above Middlebush Rd)"),
    ("Middle Tyger River", "MIDDLE TYGER RIVER AT HAMPTON RD"),
    ("A M Puett Reservoir", "Puett Reservoir."),                   # initials added; trailing punctuation
    ("Woods Lake", "Lake of the Woods"),
    ("West Fork White River", "White River (West Fork)"),          # a fork in parentheses is the fork
    ("North Branch Mill Creek", "Mill Creek (North Branch)"),
    ("East Fork Lewis River", "Lewis River (E.F.)"),
    ("White River (West Fork)", "West Fork White River"),          # the record's name with the fork in parentheses
    ("White River (West Fork)", "WHITE RIVER - WEST FORK"),
    ("Mill Creek (North Branch)", "Mill Creek, North Branch"),
])
def test_names_agree_after_normalisation(water, au):
    assert A.names_agree([water], au)


@pytest.mark.parametrize("water,au", [
    ("Mill Creek", "Mill Creek Tributary"),
    ("Mill Creek", "Little Mill Creek"),
    ("Larrys Creek", "Second Fork Larrys Creek-66911819"),
    ("Shenandoah River", "Shenandoah River North Fork"),
    ("Platte River", "South Platte River"),
    ("Black Bayou", "Unnamed Tributary to Black Bayou"),
    ("Black Bayou", "Misc tribs to Black Bayou"),
    ("Nonconnah Creek", "Johns Creek"),
    ("Lewis River", "LEWIS RIVER, E.F."),
    ("White River", "WHITE RIVER - WEST FORK"),
    ("South Holston Lake", "South Holston Reservoir Misc. Tribs."),
    ("Smith River", "Smith River Tributaries"),
    ("Kerr Lake", "Unsegmented Portion of Watershed L75R"),
    ("Mill Creek", "Black River from Mill Creek to the state line"),
    ("Tennessee River", "Kentucky Reservoir"),
    ("Clifty Creek", "CLIFTY CREEK, NORTH BRANCH"),
    ("Raccoon Creek", "BIG RACCOON CREEK"),
    ("Red River", "East Fork Red River (Red River to headwaters)"),
    ("Bear Creek", "Lakes and reservoirs in the Plum Creek system and the Bear Creek drainage."),
    ("Johns Lake", "JOHNS LAKE OUTLET"),
    ("Mermentau River", "Mermentau River Basin Coastal Bays and Gulf Waters to the State 3 mile limit"),
    ("Cuyahoga River", "Sawyer Brook-Cuyahoga River"),             # a watershed named for a brook and the river
    ("Puett Reservoir", "Puett Creek"),
    ("Lanier Lake", "Lake Sidney Lanier"),
    ("White River", "White River (West Fork)"),                    # a fork in parentheses is not the main stem
    ("Mill Creek", "Mill Creek (North Branch)"),
    ("Mill Creek", "MILL CREEK (N. BR.)"),
    ("Lewis River", "Lewis River (E.F.)"),
    ("White River (West Fork)", "White River"),                    # nor is the main stem the fork's record
    ("Mill Creek (North Branch)", "Mill Creek"),
    ("Mill Creek (North Branch)", "North Branch"),
])
def test_names_that_name_another_water_do_not_agree(water, au):
    assert not A.names_agree([water], au)


def test_an_alias_lets_a_reservoir_unit_match_the_river_record():
    assert not A.names_agree(["Cumberland River"], "Cheatham Reservoir")
    assert A.names_agree(["Cumberland River", "Cheatham Reservoir"], "Cheatham Reservoir")


def test_unnamed_units_are_recognised():
    for n in ("Unnamed Tributary to Wolf River", "UT to Mill Creek", "Misc tribs to Duck River", "Tributaries to X", "",
              "Kentucky Reservoir misc. tribs.", "Unsegmented rivers in E26", "Smith River Tributaries"):
        assert A.is_unnamed(n), n
    assert not A.is_unnamed("Unity Lake") and not A.is_unnamed("Black Bayou")


# ---------------------------------------------------------------- sewage sources


@pytest.mark.parametrize("name,kind", [
    ("COMBINED SEWER OVERFLOWS", "cso"),
    ("SANITARY SEWER OVERFLOWS (COLLECTION SYSTEM FAILURES)", "sso"),
    ("MUNICIPAL POINT SOURCE DISCHARGES", "municipal"),
    ("PACKAGE PLANT OR OTHER PERMITTED SMALL FLOWS DISCHARGES", "municipal"),
    ("INDUSTRIAL/COMMERCIAL SITE STORMWATER DISCHARGE (PERMITTED)", None),
    ("WET WEATHER DISCHARGES (POINT SOURCE AND COMBINATION OF STORMWATER, SSO OR CSO)", "wet_weather"),
    ("ON-SITE TREATMENT SYSTEMS (SEPTIC SYSTEMS AND SIMILAR DECENTRALIZED SYSTEMS)", "septic"),
    ("UNSEWERED AREA", "septic"),
    ("ILLICIT CONNECTIONS/HOOK-UPS TO STORM SEWERS", "septic"),
    ("MARINA/BOATING SANITARY ON-VESSEL DISCHARGES", "boat"),
    ("URBAN RUNOFF/STORM SEWERS", None),
    ("MUNICIPAL (URBANIZED HIGH DENSITY AREA)", None),
    ("MUNICIPAL SEPARATE STORM SEWER SYSTEMS (MS4)", None),
    ("LIVESTOCK (GRAZING OR FEEDING OPERATIONS)", None),
    ("SOURCE UNKNOWN", None),
])
def test_sewage_kinds_follow_the_rules_and_stormwater_is_not_sewage(name, kind):
    assert A.sewage_kind(name) == kind


# ---------------------------------------------------------------- the geometry gate

LAT0, LON0 = 35.0, -90.0
KX = math.cos(math.radians(LAT0)) * A.M_PER_DEG


def east(m):
    return m / KX


def north(m):
    return m / A.M_PER_DEG


def river():
    from shapely.geometry import LineString
    return LineString([(LON0, LAT0), (LON0, LAT0 + north(2200))])


def lake():
    from shapely.geometry import box
    return box(LON0 + east(5000), LAT0, LON0 + east(6000), LAT0 + north(1000))


def test_a_line_along_the_water_within_100_m_matches_with_its_distance():
    from shapely.geometry import LineString
    au = LineString([(LON0 + east(30), LAT0 + north(100)), (LON0 + east(30), LAT0 + north(2100))])
    m = A.measure(au, "line", river())
    assert m and m["method"] == "geometry+name" and 28 <= m["distance_m"] <= 32


def test_a_unit_that_covers_part_of_the_water_matches():
    from shapely.geometry import LineString
    au = LineString([(LON0 + east(30), LAT0 + north(100)), (LON0 + east(30), LAT0 + north(500))])   # 400 m of 2.2 km
    assert A.measure(au, "line", river())["method"] == "geometry+name"


def test_a_line_farther_than_100_m_does_not_match():
    from shapely.geometry import LineString
    au = LineString([(LON0 + east(150), LAT0 + north(100)), (LON0 + east(150), LAT0 + north(2100))])
    assert A.measure(au, "line", river()) is None


def test_a_line_that_only_touches_the_water_at_a_confluence_does_not_match():
    from shapely.geometry import LineString
    au = LineString([(LON0, LAT0 + north(1000)), (LON0 + east(2000), LAT0 + north(1000))])
    assert A.measure(au, "line", river()) is None


def test_an_area_that_meets_the_lake_matches_and_an_unnamed_one_inside_matches_by_geometry_only():
    from shapely.geometry import box
    au = box(LON0 + east(5900), LAT0 + north(100), LON0 + east(6500), LAT0 + north(900))
    assert A.measure(au, "area", lake())["method"] == "geometry+name"
    inner = box(LON0 + east(5200), LAT0 + north(200), LON0 + east(5400), LAT0 + north(400))
    assert A.measure(inner, "area", lake(), inside_only=True)["method"] == "geometry_inside"
    assert A.measure(au, "area", lake(), inside_only=True) is None          # half outside the lake


# ---------------------------------------------------------------- a small world: layers, files, a fake EPA


def ring(x0, y0, x1, y1):
    """An ArcGIS outer ring (clockwise) of a box given in metres from the origin."""
    a, b, c, d = LON0 + east(x0), LAT0 + north(y0), LON0 + east(x1), LAT0 + north(y1)
    return [[a, b], [a, d], [c, d], [c, b], [a, b]]


def path(*pts):
    return [[LON0 + east(x), LAT0 + north(y)] for x, y in pts]


LAYER_ROWS = {   # layer -> features: (objectid, au_id, name, recreation_use, pathogens, geometry)
    0: [(10, "TN020", "RL-0001", "Not Supporting", "Cause", {"points": [path((40, 1200))[0]]}),     # a station code
        (11, "TN021", "RL-0002", None, None, {"points": [path((40, 1300))[0]]})],                  # no location text
    1: [(1, "TN001", "Black Bayou", "Not Supporting", "Cause", {"paths": [path((30, 100), (30, 1000))]}),
        (2, "TN001", "Black Bayou", "Not Supporting", "Cause", {"paths": [path((30, 1000), (30, 2100))]}),
        (3, "TN002", "Black Bayou Tributary", None, None, {"paths": [path((0, 500), (40, 900))]}),
        (4, "TN003", "Black Bayou", None, None, {"paths": [path((500, 100), (500, 2100))]}),
        (5, "TN004", "Little Black Bayou", None, None, {"paths": [path((0, 700), (1500, 700))]}),
        (6, "TN005", "Unnamed Tributary to Black Bayou", None, None, {"paths": [path((20, 100), (20, 2000))]}),
        (7, "TN006", "Black Bayou", None, None, {"paths": [path((0, 1500), (2000, 1500))]}),
        (12, "TN007", "Nonconnah Creek", None, None, {"paths": [path((50, 200), (50, 1000))]})],    # another name
    2: [(8, "TN010", "Mill Lake", "Fully Supporting", "Meeting Criteria", {"rings": [ring(5900, 100, 6500, 900)]}),
        (9, "TN011", "Unnamed Pond", None, None, {"rings": [ring(5200, 200, 5400, 400)]})],
}
WATERS = {"black-bayou-tn": {"slug": "black-bayou-tn", "name": "Black Bayou", "kind": "stream", "state": "TN"},
          "mill-lake-tn": {"slug": "mill-lake-tn", "name": "Mill Lake", "kind": "lake", "state": "TN"},
          "far-creek-tn": {"slug": "far-creek-tn", "name": "Far Creek", "kind": "stream", "state": "TN"},
          # a second record over the upper half of the same bayou: a unit along both is kept on both, and flagged
          "upper-black-bayou-tn": {"slug": "upper-black-bayou-tn", "name": "Black Bayou", "kind": "stream", "state": "TN"},
          # the same bayou's record in the next state: Tennessee's units stay off it (audit: other_state)
          "black-bayou-ms": {"slug": "black-bayou-ms", "name": "Black Bayou", "kind": "stream", "state": "MS"}}


def geometry_of(slug):
    from shapely.geometry import LineString
    return {"black-bayou-tn": river(), "mill-lake-tn": lake(),
            "far-creek-tn": LineString([(LON0 + 1, LAT0), (LON0 + 1, LAT0 + 0.02)]),
            "upper-black-bayou-tn": LineString([(LON0, LAT0 + north(1100)), (LON0, LAT0 + north(2200))]),
            "black-bayou-ms": LineString([(LON0, LAT0), (LON0, LAT0 + north(1000))])}[slug]


A_HEADER = ["OBJECTID", "STATE", "ORGANIZATIONID", "ORGANIZATIONNAME", "REPORTINGCYCLE", "ASSESSMENTUNITID",
            "ASSESSMENTUNITNAME", "OVERALLSTATUS", "EPAIRCATEGORY", "PARAMETERGROUP", "PARAMETERNAME", "PARAMETERSTATUS",
            "USEGROUP", "USENAME", "USESUPPORT", "PARAMETERIRCATEGORY", "CYCLEFIRSTLISTED", "ASSOCIATEDACTIONTYPE",
            "LOCATIONDESCRIPTION", "WATERTYPE", "WATERSIZE", "WATERSIZEUNITS", "ASSESSMENTDATE", "MONITORINGSTARTDATE",
            "MONITORINGENDDATE", "DELISTED", "CYCLESTATUS"]


def arow(cycle, au, name, group, param, status, use_group, use, support, ircat="", first="", action="", mstart="",
         mend="", adate="", org="TDECWR"):
    return {"OBJECTID": "1", "STATE": "TN", "ORGANIZATIONID": org, "ORGANIZATIONNAME": "Tennessee",
            "REPORTINGCYCLE": str(cycle), "ASSESSMENTUNITID": au, "ASSESSMENTUNITNAME": name,
            "OVERALLSTATUS": "Not Supporting", "EPAIRCATEGORY": "5", "PARAMETERGROUP": group, "PARAMETERNAME": param,
            "PARAMETERSTATUS": status, "USEGROUP": use_group, "USENAME": use, "USESUPPORT": support,
            "PARAMETERIRCATEGORY": ircat, "CYCLEFIRSTLISTED": first, "ASSOCIATEDACTIONTYPE": action,
            "LOCATIONDESCRIPTION": "Black Bayou from Nonconnah Creek to headwaters", "WATERTYPE": "RIVER",
            "WATERSIZE": "7.9000", "WATERSIZEUNITS": "Miles", "ASSESSMENTDATE": adate, "MONITORINGSTARTDATE": mstart,
            "MONITORINGENDDATE": mend, "DELISTED": "N", "CYCLESTATUS": "EPA Final Action"}


ASSESSMENT_ROWS = [
    # the older cycle says something else: never shown
    arow(2024, "TN001", "Black Bayou", "PATHOGENS", "FECAL COLIFORM", "Cause", "RECREATION_USE", "Recreation", "N"),
    arow(2026, "TN001", "Black Bayou", "PATHOGENS", "ESCHERICHIA COLI (E. COLI)", "Cause", "RECREATION_USE",
         "Recreation", "N", "4A", "2008", "TMDL", "2021/08/01", "2021/08/31", "2023/05/12"),
    arow(2026, "TN001", "Black Bayou", "PATHOGENS", "ESCHERICHIA COLI (E. COLI)", "Cause", "RECREATION_USE",
         "Primary Contact Recreation", "I", "4A", "2008", "", "2019/06/01", "2020/07/01"),
    arow(2026, "TN001", "Black Bayou", "NUTRIENTS", "NITRATE", "Cause", "ECOLOGICAL_USE", "Fish and Aquatic Life", "N"),
    arow(2026, "TN010", "Mill Lake", "PATHOGENS", "ESCHERICHIA COLI (E. COLI)", "Meeting Criteria", "RECREATION_USE",
         "Recreation", "F"),
    arow(2026, "TN999", "Elsewhere", "PATHOGENS", "ENTEROCOCCUS BACTERIA", "Cause", "RECREATION_USE", "Recreation", "N"),
]
S_HEADER = ["OBJECTID", "STATE", "ORGANIZATIONID", "ASSESSMENTUNITID", "REPORTINGCYCLE", "PARAMETERGROUP", "CAUSENAME",
            "SOURCENAME", "CONFIRMED"]


def srow(cycle, au, group, cause, source, confirmed="N"):
    return {"OBJECTID": "1", "STATE": "TN", "ORGANIZATIONID": "TDECWR", "ASSESSMENTUNITID": au,
            "REPORTINGCYCLE": str(cycle), "PARAMETERGROUP": group, "CAUSENAME": cause, "SOURCENAME": source,
            "CONFIRMED": confirmed}


SOURCE_ROWS = [   # the organization's newest source rows are 2018 (as Illinois's and Delaware's are)
    srow(2016, "TN001", "PATHOGENS", "ESCHERICHIA COLI (E. COLI)", "COMBINED SEWER OVERFLOWS"),
    srow(2018, "TN001", "PATHOGENS", "ESCHERICHIA COLI (E. COLI)",
         "SANITARY SEWER OVERFLOWS (COLLECTION SYSTEM FAILURES)"),
    srow(2018, "TN001", "PATHOGENS", "ESCHERICHIA COLI (E. COLI)", "MUNICIPAL (URBANIZED HIGH DENSITY AREA)"),
    srow(2018, "TN001", "PATHOGENS", "ESCHERICHIA COLI (E. COLI)", "URBAN RUNOFF/STORM SEWERS"),
    srow(2018, "TN001", "NUTRIENTS", "NITRATE", "MUNICIPAL POINT SOURCE DISCHARGES"),
    srow(2018, "TN999", "PATHOGENS", "ENTEROCOCCUS BACTERIA", "SEPTIC SYSTEMS"),
]
U_HEADER = ["OBJECTID", "STATE", "ORGANIZATIONID", "ORGANIZATIONNAME", "WATERTYPE", "ASSESSMENTUNITID",
            "ASSESSMENTUNITNAME", "ASSESSMENTUNITSTATUS", "REPORTINGCYCLE", "LOCATIONDESCRIPTION", "WATERSIZE",
            "WATERSIZEUNITS"]
UNIT_ROWS = [{"OBJECTID": "2", "STATE": "TN", "ORGANIZATIONID": "TDECWR", "ORGANIZATIONNAME": "Tennessee",
              "WATERTYPE": "STREAM", "ASSESSMENTUNITID": "TN020", "ASSESSMENTUNITNAME": "RL-0001",
              "ASSESSMENTUNITSTATUS": "A", "REPORTINGCYCLE": "2026", "LOCATIONDESCRIPTION": "BLACK BAYOU AT MAIN ST",
              "WATERSIZE": "", "WATERSIZEUNITS": ""},
             {"OBJECTID": "1", "STATE": "TN", "ORGANIZATIONID": "TDECWR", "ORGANIZATIONNAME": "Tennessee",
              "WATERTYPE": "LAKE, FRESHWATER", "ASSESSMENTUNITID": "TN011", "ASSESSMENTUNITNAME": "Unnamed Pond",
              "ASSESSMENTUNITSTATUS": "A", "REPORTINGCYCLE": "2026", "LOCATIONDESCRIPTION": "Shelby County",
              "WATERSIZE": "4.2", "WATERSIZEUNITS": "Acres"}]


def zipped(name: str, header: list[str], rows: list[dict]) -> bytes:
    text = io.StringIO()
    w = csv.DictWriter(text, fieldnames=header)
    w.writeheader()
    w.writerows(rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name.replace(".zip", ""), text.getvalue())
    return buf.getvalue()


class Resp:
    def __init__(self, status=200, obj=None, content=b"", headers=None):
        self.status_code, self._obj, self.content, self.headers = status, obj, content, headers or {}

    def json(self):
        if self._obj is None:
            raise ValueError("not JSON")
        return self._obj

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]


CONTROL = {"features": [{"attributes": {"state": "TN", "organizationid": "TDECWR", "organizationname": "Tennessee",
                                        "reportingcycle": 2026, "createdon": 1787576054000}}]}


class FakeEPA:
    """The lookup, the map layers, the national files and the web services, from the world above. Options for the
    failures: a layer answering 503, a control table answer, a page of a layer without its features list (page_fault
    {layer: (page, "no_features" | "interrupted")}), a layer count off by some (count_off), the web services' answer
    (api_answer, else api_status), the national files (files) and their timestamp."""

    BUCKET = "https://cg-example.s3-us-gov-west-1.amazonaws.com/national-downloads/1794790801/"

    def __init__(self, fail_layer=None, api_status=500, api_answer=None, control=None, page_fault=None, count_off=0,
                 layer_rows=None, files=None, timestamp="2026-11-14T01:30:17.000Z"):
        self.calls = []
        self.fail_layer = fail_layer
        self.api_status, self.api_answer = api_status, api_answer
        self.control = CONTROL if control is None else control
        self.page_fault = page_fault or {}
        self.count_off = count_off
        self.layer_rows = LAYER_ROWS if layer_rows is None else layer_rows
        self.timestamp = timestamp
        self.files = files or {"assessments": zipped("assessments.csv.zip", A_HEADER, ASSESSMENT_ROWS),
                               "sources": zipped("sources.csv.zip", S_HEADER, SOURCE_ROWS),
                               "assessmentUnits": zipped("assessment_units.csv.zip", U_HEADER, UNIT_ROWS)}
        self.pages = {}

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {})})
        if url == A.LOOKUP_URL:
            return Resp(obj={"metadata": {k: {"url": self.BUCKET + A.FILES[k], "timestamp": self.timestamp,
                                              "zipSize": len(b), "numRows": 5, "csvSize": 1}
                                          for k, b in self.files.items()}})
        for k, b in self.files.items():
            if url == self.BUCKET + A.FILES[k]:
                return Resp(content=b)
        if url.startswith(A.API_URL):
            return Resp(obj=self.api_answer) if self.api_answer is not None else Resp(status=self.api_status)
        m = re.fullmatch(re.escape(A.FS_URL) + r"/(\d+)(/query)?", url)
        assert m, url
        layer = int(m.group(1))
        if layer == A.CONTROL_TABLE:
            return Resp(obj=self.control)
        if not m.group(2):
            return Resp(obj={"editingInfo": {"dataLastEditDate": 1788329282245}})
        if layer == self.fail_layer:
            return Resp(status=503)
        rows = self.layer_rows.get(layer, [])
        if params.get("returnCountOnly") == "true":
            return Resp(obj={"count": len(rows) + self.count_off})
        last = int(re.search(r"OBJECTID>(\d+)", params["where"]).group(1))
        page = self.pages[layer] = self.pages.get(layer, 0) + 1
        fault = self.page_fault.get(layer)
        if fault and fault[0] == page:
            return Resp(obj={"exceededTransferLimit": True} if fault[1] == "no_features"
                        else {"features": [], "exceededTransferLimit": True})
        feats = [{"attributes": {"OBJECTID": oid, "organizationid": "TDECWR", "assessmentunitidentifier": au,
                                 "assessmentunitname": name, "reportingcycle": 2026, "recreation_use": rec,
                                 "pathogens": pat, "cyclestatus": "EPA Final Action",
                                 "waterbodyreportlink": f"https://mywaterway.epa.gov/waterbody-report/TDECWR/{au}/2026"},
                  "geometry": g}
                 for oid, au, name, rec, pat, g in sorted(rows) if oid > last][:2]   # pages of two
        return Resp(obj={"features": feats, "exceededTransferLimit": len(feats) == 2})


def run_world(tmp_path, monkeypatch, epa=None, key=None, log=None, states=("TN",), refresh_geometry=False,
              now=None):
    if key:
        monkeypatch.setenv("ATTAINS_API_KEY", key)
    else:
        monkeypatch.delenv("ATTAINS_API_KEY", raising=False)
    epa = epa or FakeEPA()
    lines = log if log is not None else []
    client = A.Client(session=epa, pause=0, tries=2, sleep=lambda s: None, log=lines.append)
    out = tmp_path / "build" / "attains" / "attains-waters.json"
    obj = A.build(list(states) if states else None, out, raw_dir=tmp_path / "raw", client=client, waters=WATERS,
                  geometry_of=geometry_of, log=lines.append, refresh_geometry=refresh_geometry, now=now)
    return obj, epa, lines, out


def test_the_join_keeps_the_latest_cycle_the_pathogen_listing_and_the_sewage_sources(tmp_path, monkeypatch):
    obj, epa, lines, out = run_world(tmp_path, monkeypatch)
    assert json.loads(out.read_text()) == obj
    w = obj["waters"]
    assert set(w) == {"black-bayou-tn", "mill-lake-tn", "upper-black-bayou-tn"}   # far-creek-tn: nothing near
    units = w["black-bayou-tn"]["units"]
    # out: the tributary, the far copy, Little ..., the unnamed one, the confluence, a code with no location text
    assert [u["au_id"] for u in units] == ["TN001", "TN020"]
    coded = units[1]
    assert coded["au_name"] == "RL-0001" and coded["location"] == "BLACK BAYOU AT MAIN ST"
    assert coded["match"] == {"method": "geometry+name", "distance_m": 40, "geometry": "point", "name_from": "location"}
    assert coded["from"] == "layer" and coded["pathogens"][0]["status"] == "Cause"
    u = units[0]
    assert u["cycle"] == 2026 and u["org_id"] == "TDECWR" and u["org_name"] == "Tennessee" and u["state"] == "TN"
    assert u["pathogens"] == [{"parameter": "ESCHERICHIA COLI (E. COLI)", "status": "Cause", "ir_category": "4A",
                               "first_listed": 2008, "uses": ["Primary Contact Recreation", "Recreation"],
                               "use_groups": ["RECREATION_USE"]}]
    # two recreation uses: the earliest start, the latest end, both named; the worst support
    assert u["recreation"] == {"support": "Not Supporting", "uses": ["Primary Contact Recreation", "Recreation"],
                               "monitoring_start": "2019-06-01", "monitoring_end": "2021-08-31",
                               "assessment_date": "2023-05-12"}
    # sources: the organization's newest source cycle (2018), pathogen causes, sewage only (stormwater left out)
    assert u["sewage_sources"] == [{"name": "SANITARY SEWER OVERFLOWS (COLLECTION SYSTEM FAILURES)", "kind": "sso",
                                    "confirmed": False, "cause": "ESCHERICHIA COLI (E. COLI)", "cycle": 2018}]
    assert u["has_tmdl"] is True and u["water_type"] == "RIVER" and u["size"] == 7.9 and u["size_units"] == "Miles"
    assert u["report_url"] == "https://mywaterway.epa.gov/waterbody-report/TDECWR/TN001/2026"
    assert u["latest_url"] == "https://mywaterway.epa.gov/waterbody-report/TDECWR/TN001"
    # keyed by organization, unit and cycle: the 2026 assessment, its sources from the 2018 cycle only, never mixed
    assert u["sources_cycle"] == 2018 and {s_["cycle"] for s_ in u["sewage_sources"]} == {2018}
    assert u["match"]["method"] == "geometry+name" and 28 <= u["match"]["distance_m"] <= 32
    assert u["match"]["geometry"] == "line"
    assert w["black-bayou-tn"]["summary"] == {"units": 2, "pathogen_listed": 2, "sewage_named": 1,
                                              "latest_cycle": 2026, "states": ["TN"]}
    lake_units = w["mill-lake-tn"]["units"]
    assert [(x["au_id"], x["match"]["method"]) for x in lake_units] == [("TN010", "geometry+name"),
                                                                       ("TN011", "geometry_inside")]
    assert lake_units[0]["recreation"]["support"] == "Fully Supporting" and not A.pathogen_listed(lake_units[0])
    assert lake_units[1]["from"] == "layer" and lake_units[1]["water_type"] == "LAKE, FRESHWATER"
    assert w["mill-lake-tn"]["summary"] == {"units": 2, "pathogen_listed": 0, "sewage_named": 0, "latest_cycle": 2026,
                                            "states": ["TN"]}
    assert obj["states"]["TN"] == {"units": 11, "waters": 4, "waters_with_units": 3, "waters_pathogen_listed": 2,
                                   "waters_sewage_named": 2}
    # the audit list (cache only): the candidates not taken, with their reasons, and the unit on two records
    got = {(x["au_id"], x["reason"]) for x in obj["audit"]["black-bayou-tn"]}
    assert got == {("TN002", "unnamed_on_river"), ("TN005", "unnamed_on_river"), ("TN006", "not_along"),
                   ("TN007", "name_mismatch"), ("TN021", "no_name"), ("TN001", "ambiguous_multi_water"),
                   ("TN020", "ambiguous_multi_water")}
    amb = next(x for x in obj["audit"]["black-bayou-tn"] if x["au_id"] == "TN001")
    assert amb["kept"] is True and amb["others"] == ["upper-black-bayou-tn"]
    assert [x["au_id"] for x in w["upper-black-bayou-tn"]["units"]] == ["TN001", "TN020"]
    assert "black-bayou-ms" not in w                                        # another state's units only
    other = [x for x in obj["audit"]["black-bayou-ms"] if x["reason"] == "other_state"]
    assert [(x["au_id"], x["state"]) for x in other] == [("TN001", "TN")]
    assert obj["source"]["latest_cycles"] == {"assessments": {"TDECWR": 2026}, "sources": {"TDECWR": 2018}}
    assert [f["name"] for f in obj["source"]["files"]] == ["assessments", "sources", "assessmentUnits"]
    assert obj["source"]["layers"]["data_last_edited"] == "2026-09-02T06:08:02Z"


def test_no_key_is_needed_and_none_is_sent(tmp_path, monkeypatch):
    obj, epa, lines, out = run_world(tmp_path, monkeypatch)
    assert not any(c["url"].startswith(A.API_URL) for c in epa.calls)
    assert not any("X-Api-Key" in c["headers"] or "api_key" in c["params"] for c in epa.calls)
    assert obj["waters"]["mill-lake-tn"]["units"][1]["from"] == "layer"


def test_a_key_goes_in_the_header_only_and_is_never_logged_or_saved(tmp_path, monkeypatch):
    obj, epa, lines, out = run_world(tmp_path, monkeypatch, key=KEY)
    api = [c for c in epa.calls if c["url"].startswith(A.API_URL)]
    assert api and all(c["headers"].get("X-Api-Key") == KEY for c in api)       # TN011 is in no national file
    assert all(KEY not in c["url"] and KEY not in json.dumps(c["params"]) for c in epa.calls)
    assert KEY not in "\n".join(lines) and KEY not in out.read_text()
    assert obj["waters"]["mill-lake-tn"]["units"][1]["from"] == "layer"         # the service answered 500


def test_the_web_services_answer_fills_a_unit_the_files_lack():
    d = {"items": [{"organizationIdentifier": "TDECWR", "organizationName": "Tennessee", "reportingCycleText": "2026",
                    "assessments": [{"assessmentUnitIdentifier": "TN011", "useAttainments": [
                        {"useName": "Recreation", "useAttainmentCode": "N",
                         "assessmentMetadata": {"assessmentActivity": {"assessmentDate": "2023-05-12"},
                                                "monitoringActivity": {"monitoringStartDate": "2021-08-01",
                                                                       "monitoringEndDate": "2021-08-31"}}}],
                        "parameters": [{"parameterName": "ESCHERICHIA COLI (E. COLI)", "parameterStatusName": "Cause",
                                        "associatedUses": [{"associatedUseName": "Recreation"}],
                                        "impairedWatersInformation": {"listingInformation": {"cycleFirstListedText": "2008"}}},
                                       {"parameterName": "NITRATE", "parameterStatusName": "Cause"}],
                        "probableSources": [{"sourceName": "SEPTIC SYSTEMS", "sourceConfirmedIndicator": "Y",
                                             "associatedCauseNames": [{"causeName": "ESCHERICHIA COLI (E. COLI)"}]},
                                            {"sourceName": "AGRICULTURE",
                                             "associatedCauseNames": [{"causeName": "NITRATE"}]}]}]}]}
    u = A.parse_api(d, "TN011", {"ESCHERICHIA COLI (E. COLI)"})
    assert u["_cycle"] == 2026 and list(u["pathogens"]) == ["ESCHERICHIA COLI (E. COLI)"]
    older = {"organizationIdentifier": "TDECWR", "organizationName": "Tennessee", "reportingCycleText": "2024",
             "assessments": [{"assessmentUnitIdentifier": "TN011", "parameters": []}]}
    both = {"items": [d["items"][0], older]}
    assert A.parse_api(both, "TN011", set())["_cycle"] == 2026                 # the newest cycle, whatever the order
    assert A.parse_api({"items": [older, d["items"][0]]}, "TN011", set())["_cycle"] == 2026
    assert A.public_pathogen(u["pathogens"]["ESCHERICHIA COLI (E. COLI)"]) == {
        "parameter": "ESCHERICHIA COLI (E. COLI)", "status": "Cause", "ir_category": None, "first_listed": 2008,
        "uses": ["Recreation"]}                                                  # no use group given: none written
    assert u["uses"]["Recreation"]["support"] == "Not Supporting"
    assert u["uses"]["Recreation"]["assessment_date"] == "2023-05-12"          # the services' nesting (2026-11-21)
    assert u["_sources"] == [{"name": "SEPTIC SYSTEMS", "cause": "ESCHERICHIA COLI (E. COLI)", "confirmed": True}]


def api_sources(probable):
    d = {"items": [{"organizationName": "Tennessee", "reportingCycleText": "2026",
                    "assessments": [{"assessmentUnitIdentifier": "TN011", "probableSources": probable}]}]}
    return A.parse_api(d, "TN011", {"ESCHERICHIA COLI (E. COLI)"})["_sources"]


@pytest.mark.parametrize("probable", [
    [{"sourceName": "SEPTIC SYSTEMS"}],                                          # no association
    [{"sourceName": "SEPTIC SYSTEMS", "associatedCauseNames": []}],             # an empty one
    [{"sourceName": "SEPTIC SYSTEMS", "associatedCauseNames": [{}]}],           # a cause without a name
    [{"sourceName": "SEPTIC SYSTEMS", "associatedCauseNames": [{"causeName": " "}]}],
    [{"sourceName": "SEPTIC SYSTEMS", "associatedCauseNames": [{"causeName": "NITRATE"}]}],   # another cause
    [{"sourceName": "SEPTIC SYSTEMS", "associatedCauseNames": "ESCHERICHIA COLI (E. COLI)"}],  # not a list
    ["SEPTIC SYSTEMS"],
])
def test_a_web_services_source_without_a_pathogen_cause_is_not_kept(probable):
    assert api_sources(probable) == []


def test_a_web_services_source_with_a_pathogen_cause_is_kept_and_counts_as_sewage():
    got = api_sources([{"sourceName": "SEPTIC SYSTEMS", "associatedCauseNames": [{"causeName": "NITRATE"},
                                                                                {"causeName": "Escherichia coli (E. coli)"}]}])
    assert got == [{"name": "SEPTIC SYSTEMS", "cause": "ESCHERICHIA COLI (E. COLI)", "confirmed": None}]
    rec = A.unit_record(("TDECWR", "TN011"), {"au_name": "Unnamed Pond", "cycle": 2026, "kind": "area"},
                        {"method": "geometry_inside", "distance_m": 0}, {"_cycle": 2026, "pathogens": {}}, got, 2026, None)
    assert [x["kind"] for x in rec["sewage_sources"]] == ["septic"] and A.summary([rec])["sewage_named"] == 1
    none = A.unit_record(("TDECWR", "TN011"), {"au_name": "Unnamed Pond", "cycle": 2026, "kind": "area"},
                         {"method": "geometry_inside", "distance_m": 0}, {"_cycle": 2026, "pathogens": {}},
                         api_sources([{"sourceName": "SEPTIC SYSTEMS", "associatedCauseNames": []}]), 2026, None)
    assert none["sewage_sources"] == [] and A.summary([none])["sewage_named"] == 0


def test_a_failed_geometry_fetch_writes_nothing_and_its_error_names_no_address(tmp_path, monkeypatch):
    out = tmp_path / "build" / "attains" / "attains-waters.json"
    out.parent.mkdir(parents=True)
    out.write_text('{"built": "earlier"}')
    with pytest.raises(A.AttainsError) as ex:
        run_world(tmp_path, monkeypatch, epa=FakeEPA(fail_layer=1))
    msg = str(ex.value)
    assert "TN" in msg and "https://" not in msg and "where" not in msg
    assert out.read_text() == '{"built": "earlier"}'                            # the last good file stands


def test_logged_failures_carry_a_host_at_most(tmp_path, monkeypatch):
    lines = []
    with pytest.raises(A.AttainsError):
        run_world(tmp_path, monkeypatch, epa=FakeEPA(fail_layer=1), log=lines)
    text = "\n".join(lines)
    assert "HTTP 503" in text and "services.arcgis.com" in text
    assert "https://" not in text and "OBJECTID>" not in text and "outFields" not in text


def test_the_client_backs_off_on_429_and_honours_retry_after():
    class S:
        def __init__(self):
            self.n = 0

        def get(self, url, **kw):
            self.n += 1
            return Resp(429, headers={"Retry-After": "7"}) if self.n == 1 else Resp(obj={"ok": 1})
    waits = []
    c = A.Client(session=S(), pause=0, tries=3, sleep=waits.append, log=lambda m: None)
    assert c.get_json("https://example.gov/x") == {"ok": 1} and waits == [7.0]


def test_a_cached_download_is_reused_while_the_lookup_timestamp_is_unchanged(tmp_path, monkeypatch):
    run_world(tmp_path, monkeypatch)
    epa = FakeEPA()
    run_world(tmp_path, monkeypatch, epa=epa)
    assert not any(c["url"].startswith(FakeEPA.BUCKET) for c in epa.calls)         # nothing downloaded again
    assert not any("/query" in c["url"] and "OBJECTID" in c["params"].get("where", "") for c in epa.calls)


def test_offline_runs_from_the_caches_alone(tmp_path, monkeypatch):
    first, *_ = run_world(tmp_path, monkeypatch)
    out = tmp_path / "offline.json"
    obj = A.build(["TN"], out, raw_dir=tmp_path / "raw", client=A.Client(session=None, log=lambda m: None),
                  offline=True, waters=WATERS, geometry_of=geometry_of, log=lambda m: None)
    assert obj["waters"] == first["waters"]


def test_a_parameter_the_file_ties_to_no_use_carries_no_uses(tmp_path):
    rows = [arow(2026, "TN020", "Dry Creek", "PATHOGENS", "FECAL COLIFORM", "Cause", "", "", "")]
    p = tmp_path / "assessments.csv.zip"
    p.write_bytes(zipped("assessments.csv.zip", A_HEADER, rows))
    units, org_max, names = A.read_assessments(p, {("TDECWR", "TN020")})
    rec = A.public_pathogen(units[("TDECWR", "TN020", 2026)]["pathogens"]["FECAL COLIFORM"])
    assert rec == {"parameter": "FECAL COLIFORM", "status": "Cause", "ir_category": None, "first_listed": None}
    assert org_max == {"TDECWR": 2026} and names == {"FECAL COLIFORM"}


def test_a_state_is_fetched_again_only_when_epa_reloaded_it_or_the_copy_is_old():
    from datetime import UTC, datetime
    now = datetime(2026, 11, 21, tzinfo=UTC)
    control = {"TN": [{"created_on": 1787576054000}]}
    have = {"TN": {"fetched_at": "2026-11-01T00:00:00Z", "loads": ["1787576054000"], "layer_edits": {"1": "old"}}}
    assert A.geometry_due("TN", control, {"1": "new"}, have, now) is None       # another state's reload: kept
    assert A.geometry_due("TN", {"TN": [{"created_on": 1}]}, {}, have, now) == "the state's load date changed"
    assert A.geometry_due("MA", control, {}, have, now) == "no copy"
    assert "older than" in A.geometry_due("TN", control, {}, have, datetime(2027, 3, 1, tzinfo=UTC))
    assert A.geometry_due("TN", control, {}, have, now, force=True) == "asked"


def test_summary_counts():
    units = [{"cycle": 2024, "state": "TN", "pathogens": [{"status": "Cause"}], "sewage_sources": [{"kind": "sso"}]},
             {"cycle": 2026, "state": "MS", "pathogens": [{"status": "Meeting Criteria"}], "sewage_sources": []},
             {"cycle": None, "state": "TN", "pathogens": [], "sewage_sources": []}]
    assert A.summary(units) == {"units": 3, "pathogen_listed": 1, "sewage_named": 1, "latest_cycle": 2026,
                                "states": ["MS", "TN"]}


# ---------------------------------------------------------------- review fixes (Astra, 2026-11-21): the build


def world_files(assessments=None, sources=None, units=None, stored=False):
    """The three national files as FakeEPA serves them, from rows (the world's rows by default)."""
    kind = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED

    def z(name, header, rows):
        text = io.StringIO()
        w = csv.DictWriter(text, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", kind) as f:
            f.writestr(name.replace(".zip", ""), text.getvalue())
        return buf.getvalue()
    return {"assessments": z("assessments.csv.zip", A_HEADER, ASSESSMENT_ROWS if assessments is None else assessments),
            "sources": z("sources.csv.zip", S_HEADER, SOURCE_ROWS if sources is None else sources),
            "assessmentUnits": z("assessment_units.csv.zip", U_HEADER, UNIT_ROWS if units is None else units)}


def test_free_text_with_contact_details_is_scrubbed_in_the_cache_the_water_block_and_the_download(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from export import assessments as XA
    loc = f"Black Bayou from Nonconnah Creek to headwaters; questions to {MAIL} or {PHONE}"
    rows = [{**r, "LOCATIONDESCRIPTION": loc, "ORGANIZATIONNAME": f"Tennessee ({MAIL})"} for r in ASSESSMENT_ROWS]
    srcs = [{**r, "SOURCENAME": f"{r['SOURCENAME']} (call {PHONE})"} for r in SOURCE_ROWS]
    layers = {**LAYER_ROWS, 1: [(o, au, f"{n} {MAIL}" if au == "TN007" else n, rec, pat, g)
                                for o, au, n, rec, pat, g in LAYER_ROWS[1]]}       # an audit entry's name
    obj, epa, lines, out = run_world(tmp_path, monkeypatch, epa=FakeEPA(files=world_files(rows, srcs), layer_rows=layers))
    text = out.read_text()
    assert MAIL in text and PHONE in text
    u = obj["waters"]["black-bayou-tn"]["units"][0]
    assert u["location"] == loc
    assert u["org_name"] == f"Tennessee ({MAIL})"
    assert u["sewage_sources"][0]["kind"] == "sso" and PHONE in u["sewage_sources"][0]["name"]
    audit = next(x for x in obj["audit"]["black-bayou-tn"] if x["au_id"] == "TN007")
    assert audit["au_name"] == f"Nonconnah Creek {MAIL}"
    # the export scrubs again (a cache written before this fix, or by hand): the water block and the download
    raw = json.loads(text)
    raw["waters"]["black-bayou-tn"]["units"][0]["location"] = loc
    raw["waters"]["black-bayou-tn"]["units"][0]["au_name"] = f"Black Bayou {MAIL}"
    raw["built"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    a = XA.public(raw, {"black-bayou-tn"})
    block = json.dumps(XA.water_block(a, "black-bayou-tn"))
    assert MAIL in block and PHONE in block
    path = tmp_path / "out" / "csv" / "assessments.csv"
    assert XA.write_csv(path, a, names={"black-bayou-tn": "Black Bayou"}) == 2
    csv_text = path.read_text()
    assert MAIL in csv_text and PHONE in csv_text
    row = next(csv.DictReader(io.StringIO(csv_text)))
    assert row["au_name"] == f"Black Bayou {MAIL}" and row["location"] == loc
    assert PHONE in row["sewage_sources"]


def test_a_malformed_key_is_never_sent_logged_or_saved_and_the_build_runs_without_it(tmp_path, monkeypatch):
    bad = "part-one-not-real\npart-two-not-real"
    obj, epa, lines, out = run_world(tmp_path, monkeypatch, key=bad)
    assert not any(c["url"].startswith(A.API_URL) for c in epa.calls)
    text = "\n".join(lines) + out.read_text()
    assert "part-one" not in text and "part-two" not in text
    assert any("not a usable key" in x for x in lines)
    assert obj["waters"]["mill-lake-tn"]["units"][1]["from"] == "layer"


def test_a_key_with_surrounding_whitespace_is_stripped_before_it_is_sent(tmp_path, monkeypatch):
    obj, epa, lines, out = run_world(tmp_path, monkeypatch, key=f"  {KEY}\n")
    api = [c for c in epa.calls if c["url"].startswith(A.API_URL)]
    assert api and all(c["headers"]["X-Api-Key"] == KEY for c in api)


def test_a_request_requests_refuses_never_quotes_the_header_value():
    import requests

    class NoSend(requests.adapters.BaseAdapter):
        def send(self, *a, **k):
            raise AssertionError("nothing may be sent")

        def close(self):
            pass
    session = requests.Session()
    session.mount("https://", NoSend())
    c = A.Client(session=session, pause=0, tries=2, sleep=lambda s: None, log=lambda m: None)
    for value in ("part-one-not-real\npart-two-not-real", " part-one-not-real"):
        with pytest.raises(A.AttainsError) as ex:
            c.get_json(A.API_URL + "assessments", headers={"X-Api-Key": value})
        assert "part-one" not in str(ex.value) and "InvalidHeader" in str(ex.value)
        assert "api.epa.gov" in str(ex.value) and "https://" not in str(ex.value)
    # and the optional fill falls back to the layers
    assert A.api_fill(c, ("TDECWR", "TN011"), set(), api_key="part-one-not-real\nx", log=lambda m: None,
                      api_dir=Path("/nonexistent")) is None


SECRET = "a-sec" + "ret-value\nb"       # built here, so no traceback line quotes it


def test_the_command_line_prints_any_failure_through_error_text(tmp_path, monkeypatch, capsys):
    import requests
    hidden = tmp_path / ("private-" + "folder-name")
    hidden.mkdir()
    (hidden / "junk.zip").write_bytes(b"not a zip at all")

    def invalid_header(*a, **k):        # raised by requests itself, its words quoting the header value
        requests.Session().prepare_request(requests.Request("GET", A.API_URL, headers={"X-Api-Key": SECRET}))

    def bad_zip(*a, **k):               # zipfile's own failure
        zipfile.ZipFile(hidden / "junk.zip")

    def missing(*a, **k):               # the disk's, quoting the path
        (hidden / "none" / "x.csv.zip").read_bytes()
    seen = []
    for fail in (invalid_header, bad_zip, missing):
        monkeypatch.setattr(A, "build", fail)
        assert A.main(["--states", "TN"]) == 1
        got = capsys.readouterr()
        text = got.out + got.err
        assert "a-secret" not in text and "private-folder" not in text and got.out.startswith("::error::attains: ")
        seen.append(got.out)
    assert "InvalidHeader" in seen[0] and "BadZipFile" in seen[1] and "missing file" in seen[2]


def _previous_cache(tmp_path):
    out = tmp_path / "build" / "attains" / "attains-waters.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('{"built": "earlier"}')
    return out


@pytest.mark.parametrize("epa,why", [
    (lambda: FakeEPA(control={}), "no features list"),                                   # an empty answer
    (lambda: FakeEPA(control={"features": []}), "no state organization"),
    (lambda: FakeEPA(control={"features": [{"no": "attributes"}]}), "no attributes"),
    (lambda: FakeEPA(page_fault={1: (2, "no_features")}), "page 2: the answer has no features list"),
    (lambda: FakeEPA(page_fault={1: (2, "interrupted")}), "interrupted"),
    (lambda: FakeEPA(count_off=1), "the layer counts"),
])
def test_an_incomplete_answer_stops_the_run_and_keeps_the_previous_cache(tmp_path, monkeypatch, epa, why):
    out = _previous_cache(tmp_path)
    lines = []
    with pytest.raises(A.AttainsError) as ex:
        run_world(tmp_path, monkeypatch, epa=epa(), log=lines)
    assert why in str(ex.value) + "\n".join(lines)
    assert "page" not in why or "no geometry for TN" in str(ex.value)
    assert out.read_text() == '{"built": "earlier"}'
    assert not (tmp_path / "raw" / "geom" / "TN.json.gz").exists()           # no partial geometry cached either


def test_a_failed_refetch_keeps_the_cached_geometry_of_the_state(tmp_path, monkeypatch):
    run_world(tmp_path, monkeypatch)
    geom = tmp_path / "raw" / "geom" / "TN.json.gz"
    before = geom.read_bytes()
    with pytest.raises(A.AttainsError):
        run_world(tmp_path, monkeypatch, epa=FakeEPA(page_fault={1: (2, "no_features")}), refresh_geometry=True)
    assert geom.read_bytes() == before


def test_a_control_table_that_lost_a_state_covered_before_stops_the_run(tmp_path, monkeypatch):
    first, *_ = run_world(tmp_path, monkeypatch)
    out = tmp_path / "build" / "attains" / "attains-waters.json"
    before = out.read_text()
    m = json.loads((tmp_path / "raw" / "geom" / "manifest.json").read_text())
    m["MS"] = {**m["TN"]}                                                      # a live state the last run covered
    (tmp_path / "raw" / "geom" / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(A.AttainsError) as ex:
        run_world(tmp_path, monkeypatch, states=None)                          # the control table names TN only
    assert "lacks MS" in str(ex.value) and out.read_text() == before
    with pytest.raises(A.AttainsError) as ex:
        run_world(tmp_path, monkeypatch, states=("TN", "AL"))                  # asked for, and not in the table
    assert "lacks AL" in str(ex.value)


def test_unit_metadata_comes_from_the_assessments_cycle_only(tmp_path, monkeypatch):
    blank = {"LOCATIONDESCRIPTION": "", "WATERTYPE": "", "WATERSIZE": "", "WATERSIZEUNITS": ""}
    rows = [{**arow(2024, "TN001", "Black Bayou", "PATHOGENS", "FECAL COLIFORM", "Cause", "RECREATION_USE",
                    "Recreation", "N"), **blank}]
    new_lake = {"OBJECTID": "3", "STATE": "TN", "ORGANIZATIONID": "TDECWR", "ORGANIZATIONNAME": "Tennessee",
                "WATERTYPE": "LAKE, FRESHWATER", "ASSESSMENTUNITID": "TN001", "ASSESSMENTUNITNAME": "Black Bayou",
                "ASSESSMENTUNITSTATUS": "A", "REPORTINGCYCLE": "2026", "LOCATIONDESCRIPTION": "A new lake",
                "WATERSIZE": "100", "WATERSIZEUNITS": "Acres"}
    obj, *_ = run_world(tmp_path, monkeypatch, epa=FakeEPA(files=world_files(rows, [], [new_lake])))
    u = next(x for x in obj["waters"]["black-bayou-tn"]["units"] if x["au_id"] == "TN001")
    assert u["cycle"] == 2024 and u["report_url"].endswith("/TN001/2024")
    assert (u["water_type"], u["size"], u["size_units"], u["location"]) == (None, None, None, None)   # not 2026's
    same = {**new_lake, "REPORTINGCYCLE": "2024", "LOCATIONDESCRIPTION": "Black Bayou, 2024 segment",
            "WATERTYPE": "RIVER", "WATERSIZE": "7.9", "WATERSIZEUNITS": "Miles"}
    obj, *_ = run_world(tmp_path / "b", monkeypatch, epa=FakeEPA(files=world_files(rows, [], [new_lake, same])))
    u = next(x for x in obj["waters"]["black-bayou-tn"]["units"] if x["au_id"] == "TN001")
    assert (u["water_type"], u["size"], u["size_units"], u["location"]) == ("RIVER", 7.9, "Miles",
                                                                            "Black Bayou, 2024 segment")


def test_a_corrupt_download_of_the_same_size_keeps_the_previous_file(tmp_path, monkeypatch):
    good = world_files(stored=True)
    run_world(tmp_path, monkeypatch, epa=FakeEPA(files=good))
    cached = tmp_path / "raw" / "assessments.csv.zip"
    side = tmp_path / "raw" / "assessments.csv.zip.meta.json"
    assert cached.read_bytes() == good["assessments"]
    side_before = side.read_text()
    i = good["assessments"].index(b"Elsewhere")
    bad = good["assessments"][:i] + b"Elsewhera" + good["assessments"][i + 9:]     # same size, wrong CRC
    assert len(bad) == len(good["assessments"])
    epa = FakeEPA(files={**good, "assessments": bad}, timestamp="2026-11-21T01:30:17.000Z")
    with pytest.raises(A.AttainsError) as ex:
        run_world(tmp_path, monkeypatch, epa=epa)
    assert "CRC" in str(ex.value) or "not a readable zip" in str(ex.value)
    assert cached.read_bytes() == good["assessments"] and side.read_text() == side_before
    assert not (tmp_path / "raw" / "assessments.csv.zip.part").exists()
    # a file without the columns the readers use is refused the same way
    headless = world_files([], stored=True)
    headless["sources"] = zipped("sources.csv.zip", ["OBJECTID", "STATE"], [{"OBJECTID": "1", "STATE": "TN"}])
    with pytest.raises(A.AttainsError) as ex:
        run_world(tmp_path, monkeypatch, epa=FakeEPA(files=headless, timestamp="2026-11-22T01:30:17.000Z"))
    assert "columns missing" in str(ex.value)
    assert (tmp_path / "raw" / "sources.csv.zip").read_bytes() == good["sources"]     # the bad one never replaced it


def api_answer(cycle, org_name="Tennessee"):
    return {"items": [{"organizationIdentifier": "TDECWR", "organizationName": org_name,
                       "reportingCycleText": str(cycle),
                       "assessments": [{"assessmentUnitIdentifier": "TN011", "useAttainments": [
                           {"useName": "Recreation", "useAttainmentCode": "N"}],
                           "parameters": [{"parameterName": "ESCHERICHIA COLI (E. COLI)",
                                           "parameterStatusName": "Cause"}],
                           "probableSources": [{"sourceName": "SEPTIC SYSTEMS",
                                                "associatedCauseNames": [{"causeName": "ESCHERICHIA COLI (E. COLI)"}]}]}]}]}


def test_a_cached_web_services_answer_advances_when_a_newer_cycle_shows(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    now = datetime(2026, 11, 21, 12, tzinfo=UTC)
    api = tmp_path / "raw" / "api"
    api.mkdir(parents=True)
    entry = api / "TDECWR__TN011.json"
    old = {"fetched_at": "2026-11-16T00:00:00Z", "cycle": 2024, "newest_known": 2024,
           "unit": A.api_unit(api_answer(2024), "TN011", set())}
    entry.write_text(json.dumps(old))
    # the layers show TN011 in 2026: the 2024 entry is asked again, and the 2026 answer replaces it
    obj, epa, lines, out = run_world(tmp_path, monkeypatch, key=KEY, now=now,
                                     epa=FakeEPA(api_answer=api_answer(2026, org_name=f"Tennessee {MAIL}")))
    assert any(c["url"].startswith(A.API_URL) and c["params"].get("assessmentUnitIdentifier") == "TN011"
               for c in epa.calls)
    u = next(x for x in obj["waters"]["mill-lake-tn"]["units"] if x["au_id"] == "TN011")
    assert u["cycle"] == 2026 and u["from"] == "web services" and u["report_url"].endswith("/TN011/2026")
    assert u["sewage_sources"][0]["kind"] == "septic"
    saved = json.loads(entry.read_text())
    assert saved["cycle"] == 2026 and saved["fetched_at"] == "2026-11-21T12:00:00Z" and MAIL in entry.read_text()
    assert KEY not in entry.read_text() and "items" not in saved                 # the parsed fields only
    # a fresh entry of the newest cycle is used as it is; one older than 30 days is asked again
    epa2 = FakeEPA(api_answer=api_answer(2026))
    run_world(tmp_path, monkeypatch, key=KEY, now=now, epa=epa2)
    assert not any(c["params"].get("assessmentUnitIdentifier") == "TN011" for c in epa2.calls)
    epa3 = FakeEPA(api_answer=api_answer(2026))
    run_world(tmp_path, monkeypatch, key=KEY, now=datetime(2027, 1, 5, tzinfo=UTC), epa=epa3)
    assert any(c["params"].get("assessmentUnitIdentifier") == "TN011" for c in epa3.calls)


def test_an_old_raw_web_services_answer_in_the_cache_is_not_used(tmp_path):
    from datetime import UTC, datetime
    p = tmp_path / "TDECWR__TN011.json"
    p.write_text(json.dumps(api_answer(2024)))                                 # the format before entries had a time
    assert A.api_cached(p, 2024, datetime(2026, 11, 21, tzinfo=UTC)) == (False, None)


# ---------------------------------------------------------------- the export's block


def cache(built="2026-11-20T00:00:00Z"):
    unit = {"org_id": "TDECWR", "au_id": "TN001", "pathogens": [{"status": "Cause"}], "sewage_sources": []}
    return {"built": built, "source": {"name": A.SOURCE_NAME},
            "waters": {"black-bayou-tn": {"units": [unit], "summary": {"units": 1, "pathogen_listed": 1}},
                       "old-name-tn": {"units": [unit], "summary": {"units": 1, "pathogen_listed": 1}},
                       "untracked-tn": {"units": [unit], "summary": {"units": 1}}}}


def test_the_export_keeps_tracked_waters_under_their_own_slug():
    from datetime import UTC, datetime

    from export import assessments as XA
    from export import build as X
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    a = XA.public(cache(now), {"black-bayou-tn", "new-name-tn"}, canon=lambda s: {"old-name-tn": "new-name-tn"}.get(s, s))
    assert set(a["waters"]) == {"black-bayou-tn", "new-name-tn"} and a["unavailable"] is None
    assert XA.meta(a) == {"built": now, "waters_with_units": 2, "waters_pathogen_listed": 2, "waters_sewage_named": 0,
                          "waters_capped": 0, "unavailable": None}
    assert not X.internal_wording(a)
    assert XA.water_block(a, "untracked-tn") is None and XA.water_block(a, "black-bayou-tn")["units"]
    assert "audit" not in json.dumps(XA.index(a))


def test_a_missing_unreadable_or_stale_cache_shows_nothing_and_never_fails(tmp_path):
    from export import assessments as XA
    a = XA.load({"black-bayou-tn"}, path=tmp_path / "none.json")
    assert a["waters"] == {} and "no assessment file" in a["unavailable"]
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert XA.load({"black-bayou-tn"}, path=bad)["waters"] == {}
    old = XA.public(cache("2026-09-01T00:00:00Z"), {"black-bayou-tn"}, now="2026-11-21T00:00:00Z")
    assert old["waters"] == {} and "more than 30 days" in old["unavailable"]
    fresh = XA.public(cache("2026-11-01T00:00:00Z"), {"black-bayou-tn"}, now="2026-11-21T00:00:00Z")
    assert set(fresh["waters"]) == {"black-bayou-tn"}
    assert XA.write_csv(tmp_path / "csv" / "assessments.csv", old) == 0 and not (tmp_path / "csv").exists()


def test_a_waters_block_carries_at_most_25_units_and_the_totals(tmp_path):
    from datetime import UTC, datetime

    from export import assessments as XA
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def unit(i, listed=False, sewage=False):
        return {"au_id": f"U{i:02d}", "org_id": "X", "state": "TN", "cycle": 2026, "match": {"distance_m": i},
                "pathogens": [{"parameter": "ESCHERICHIA COLI (E. COLI)", "status": "Cause" if listed else "Meeting Criteria"}],
                "sewage_sources": [{"name": "COMBINED SEWER OVERFLOWS", "kind": "cso"}] if sewage else []}
    units = [unit(i) for i in range(27)] + [unit(90, listed=True), unit(91, sewage=True), unit(92, True, True)]
    c = {"built": now, "source": {"name": A.SOURCE_NAME}, "waters": {"long-river-tn": {"units": units, "summary": {}}}}
    a = XA.public(c, {"long-river-tn"})
    b = XA.water_block(a, "long-river-tn")
    assert [u["au_id"] for u in b["units"][:4]] == ["U92", "U90", "U91", "U00"] and len(b["units"]) == 25
    assert b["summary"] == {"units": 25, "pathogen_listed": 2, "sewage_named": 2, "latest_cycle": 2026, "states": ["TN"],
                            "units_total": 30, "pathogen_listed_total": 2, "sewage_named_total": 2}
    assert XA.meta(a)["waters_capped"] == 1 and "all_units" not in b
    assert XA.write_csv(tmp_path / "a.csv", a) == 30                         # the download keeps every unit
    # 25 pathogen listings without a sewage source, then a sewage source on an unlisted unit (26th): the block
    # carries no sewage source, its totals and meta.json count the water
    many = [unit(i, listed=True) for i in range(25)] + [unit(40, sewage=True)] + [unit(i) for i in range(50, 53)]
    c = {"built": now, "source": {"name": A.SOURCE_NAME}, "waters": {"long-river-tn": {"units": many, "summary": {}},
                                                                     "short-creek-tn": {"units": [unit(1)]}}}
    a = XA.public(c, {"long-river-tn", "short-creek-tn"})
    s = XA.water_block(a, "long-river-tn")["summary"]
    assert (s["units"], s["sewage_named"], s["sewage_named_total"], s["pathogen_listed_total"]) == (25, 0, 1, 25)
    assert [u["au_id"] for u in XA.water_block(a, "long-river-tn")["units"]][-1] == "U24"
    assert XA.meta(a) == {"built": now, "waters_with_units": 2, "waters_pathogen_listed": 1, "waters_sewage_named": 1,
                          "waters_capped": 1, "unavailable": None}
    assert XA.write_csv(tmp_path / "b.csv", a) == 30 and "COMBINED SEWER" in (tmp_path / "b.csv").read_text()


def test_a_waters_block_cites_the_source_without_the_per_organization_tables():
    from export import assessments as XA
    full = {"name": A.SOURCE_NAME, "files": [{"name": "assessments", "url": "https://x.example.gov/a.csv.zip"}],
            "layers": {"url": A.FS_URL, "data_last_edited": "2026-09-02T06:08:02Z"}, "fetched_at": "2026-11-21T14:08:29Z",
            "geometry_fetched": {"TN": "2026-11-21T13:30:00Z"}, "latest_cycles": {"assessments": {"TDECWR": 2026}}}
    assert XA.assessment_source(full) == {k: full[k] for k in ("name", "files", "layers", "fetched_at")}
    assert XA.assessment_source(None) is None


def test_the_assessment_download_has_one_row_per_water_and_unit(tmp_path, monkeypatch):
    from export import assessments as XA
    obj, *_ = run_world(tmp_path, monkeypatch)
    obj["built"] = "2026-11-21T00:00:00Z"
    a = XA.public(obj, {"black-bayou-tn", "mill-lake-tn"}, now="2026-11-21T01:00:00Z")
    p = tmp_path / "out" / "csv" / "assessments.csv"
    assert XA.write_csv(p, a, names={"black-bayou-tn": "Black Bayou"}) == 4
    raw = p.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    assert list(rows[0]) == XA.CSV_COLUMNS
    first = rows[0]
    assert (first["water_slug"], first["water"], first["au_id"], first["cycle"]) == ("black-bayou-tn", "Black Bayou",
                                                                                     "TN001", "2026")
    assert first["pathogen_parameters"] == "ESCHERICHIA COLI (E. COLI)" and first["pathogen_listed"] == "true"
    assert (first["sewage_sources"], first["sewage_kinds"], first["sources_cycle"]) == (
        "SANITARY SEWER OVERFLOWS (COLLECTION SYSTEM FAILURES)", "sso", "2018")
    assert first["report_url"].endswith("/TN001/2026") and first["latest_url"].endswith("/TDECWR/TN001")
    assert first["match_method"] == "geometry+name" and first["recreation_support"] == "Not Supporting"
    assert [r["au_id"] for r in rows] == ["TN001", "TN020", "TN010", "TN011"]


# ---------------------------------------------------------------- the R2 objects and the workflows


def tarball(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as tf:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return path


def unpack(tmp_path, tb, *extra):
    """The command line on a copy of the script in tmp_path/repo (it writes under its own checkout), with the
    pipeline's common.py beside it as in the checkout (its error_text formats the failures)."""
    import shutil
    (tmp_path / "repo" / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "repo" / "pipeline").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "scripts" / "state_paths.py", tmp_path / "repo" / "scripts" / "state_paths.py")
    shutil.copy(ROOT / "pipeline" / "common.py", tmp_path / "repo" / "pipeline" / "common.py")
    return subprocess.run([sys.executable, "-I", str(tmp_path / "repo" / "scripts" / "state_paths.py"), "unpack-attains",
                           str(tb), *extra], capture_output=True, text=True, cwd=tmp_path)


def test_unpack_attains_restores_the_cache_and_refuses_anything_else(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import state_paths as SP
    good = tarball(tmp_path / "a.tar.gz", {"data/build/attains/attains-waters.json": b'{"waters": {}}'})
    SP.unpack_attains(good, root=tmp_path / "repo", only="cache")
    assert (tmp_path / "repo/data/build/attains/attains-waters.json").read_text() == '{"waters": {}}'
    geom = tarball(tmp_path / "g.tar.gz", {"data/raw/attains/geom/TN.json.gz": b"x",
                                           "data/raw/attains/geom/manifest.json": b"{}"})
    SP.unpack_attains(geom, root=tmp_path / "repo", only="geom")
    assert (tmp_path / "repo/data/raw/attains/geom/TN.json.gz").is_file()
    with pytest.raises(SP.Unreadable):
        SP.unpack_attains(geom, root=tmp_path / "other", only="cache")         # geometry in the refresh's restore
    for bad in ({"data/build/attains/attains-waters.json": b"{}", "data/build/history.json": b"{}"},
                {"scripts/state_paths.py": b"print(1)"},
                {"data/raw/attains/geom/../../../x.json": b"{}"},
                {"data/raw/attains/geom/tn.json.gz": b"x"},
                {"data/build/attains/._attains-waters.json": b"x"}):                # nothing left once skipped
        tb = tarball(tmp_path / "bad.tar.gz", bad)
        with pytest.raises(SP.Unreadable):
            SP.unpack_attains(tb, root=tmp_path / "bad")
        assert not (tmp_path / "bad").exists() or not any((tmp_path / "bad").rglob("*.json"))
    p = unpack(tmp_path, tarball(tmp_path / "c.tar.gz", {"data/build/attains/attains-waters.json": b"{}"}), "--only",
               "cache")
    assert p.returncode == 0 and "restored 1 file" in p.stdout
    assert (tmp_path / "repo/data/build/attains/attains-waters.json").read_text() == "{}"


def test_a_refused_archive_is_reported_by_category_and_count_never_by_member_name(tmp_path):
    names = {"/home/" + "example/private.txt": b"x",                               # an absolute path
             f"data/build/attains/{MAIL}.json": b"x",                              # an address as a file name
             "data/build/attains/::error::injected.json": b"x",                    # a workflow command
             "data/raw/attains/geom/../../../../etc/x.json": b"x"}                 # a way out
    tb = tarball(tmp_path / "bad.tar.gz", {"data/build/attains/attains-waters.json": b"{}", **names})
    p = unpack(tmp_path, tb, "--only", "cache")
    out = p.stdout + p.stderr
    assert p.returncode == 1 and not (tmp_path / "repo" / "data").exists()
    for n in names:
        assert n not in out
    assert "example" not in out and MAIL not in out and "injected" not in out and "etc/" not in out
    assert ("4 member(s) that may not be restored (a file that is not the cache's: 2; an absolute or odd path: 1; "
            "an odd path: 1)") in out and "nothing was restored" in out
    # a damaged object: the failure's category, not its words
    junk = tmp_path / "junk.tar.gz"
    junk.write_bytes(b"\x1f\x8b" + b"not really gzip " * 10)
    p = unpack(tmp_path, junk, "--only", "cache")
    assert p.returncode == 1 and "could not be read" in p.stdout and "junk.tar.gz" not in p.stdout + p.stderr
    assert "Traceback" not in p.stdout + p.stderr


def load_workflow(name):
    import yaml
    d = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())
    d["on"] = d.pop(True, d.get("on"))
    return d


def test_the_weekly_workflow_is_keyless_guarded_and_saves_only_its_own_objects():
    w = load_workflow("attains.yml")
    text = (ROOT / ".github" / "workflows" / "attains.yml").read_text()
    assert "schedule" in w["on"] and "workflow_dispatch" in w["on"]
    cron = w["on"]["schedule"][0]["cron"].split()
    assert cron[2] == "*" and cron[3] == "*" and cron[4] != "*"                  # weekly
    assert w["concurrency"] == {"group": "attains", "cancel-in-progress": False}
    assert w["permissions"] == {"contents": "read"}
    assert "ATTAINS" not in "".join(str(v) for v in w["jobs"]["attains"]["env"].values())
    assert "secrets.ATTAINS" not in text and "ATTAINS_API" not in text and "X-Api-Key" not in text
    assert "object put dirtywaterwatch-data/state/attains.tar.gz" in text
    assert "object put dirtywaterwatch-data/state/attains-geom.tar.gz" in text
    runs = "\n".join(str(s.get("run") or "") for s in w["jobs"]["attains"]["steps"])
    assert "state/build.tar.gz" not in runs and "current/" not in runs
    puts = re.findall(r"object put (\S+)", runs)
    assert all(p.startswith("dirtywaterwatch-data/state/attains") for p in puts)
    for s in w["jobs"]["attains"]["steps"]:
        if "uses" in s:
            assert re.fullmatch(r"actions/(checkout|setup-python|setup-node)@[0-9a-f]{40}", s["uses"]), s["uses"]
        assert "github.event.inputs" not in s.get("run", "")                    # inputs reach the shell through env
    assert "scripts/attains_context.py" in text and "unpack-attains attains-geom.tar.gz --only geom" in text
    build = next(s for s in w["jobs"]["attains"]["steps"] if s.get("name", "").startswith("Build the state assessments"))
    assert "| python3 -I scripts/log_redact.py" in build["run"] and "set -o pipefail" in build["run"]
    assert build["env"].get("AWS_ACCESS_KEY_ID") == "" and "CLOUDFLARE_API_TOKEN" not in build["env"]


def test_the_refresh_restores_the_assessments_read_only_after_its_build_state():
    w = load_workflow("refresh.yml")
    steps = w["jobs"]["refresh"]["steps"]
    names = [s.get("name", "") for s in steps]
    rb = names.index("Restore pipeline state from R2")
    ra = next(i for i, n in enumerate(names) if n.startswith("Restore the state assessments"))
    assert rb < ra < next(i for i, n in enumerate(names) if n.startswith("Refresh ("))
    assert "unpack-attains attains.tar.gz --only cache" in steps[ra]["run"]
    assert "exit 1" not in steps[ra]["run"]                                     # never stops the refresh
    assert "object put dirtywaterwatch-data/state/attains" not in (ROOT / ".github/workflows/refresh.yml").read_text()


def _simulate(tmp_path, monkeypatch, env=None, build_fails=False, paused=False):
    import test_state_workflows as TSW
    monkeypatch.setitem(TSW.STANDINS, "openboatlaunch's water records", "true")
    monkeypatch.setitem(TSW.STANDINS, "Build the state assessments",
                        "[ -z \"$BUILD_FAILS\" ] || exit 1\nmkdir -p data/build/attains data/raw/attains/geom\n"
                        "echo '{\"waters\": {}}' > data/build/attains/attains-waters.json\n"
                        "echo '{}' > data/raw/attains/geom/manifest.json\necho x > data/raw/attains/geom/TN.json.gz")
    TSW.checkout(tmp_path)
    if paused:
        (tmp_path / "r2" / "state" / "PAUSE").write_text("paused")
    return TSW, TSW.simulate("attains.yml", tmp_path, env={**(env or {}), **({"BUILD_FAILS": "1"} if build_fails else {})})


def test_the_weekly_run_saves_the_assessments_and_the_geometry(tmp_path, monkeypatch):
    TSW, r = _simulate(tmp_path, monkeypatch)
    assert not r["failed"], r["log"]
    assert TSW.puts(tmp_path) == ["put state/attains.tar.gz", "put state/attains-geom.tar.gz"]
    got = [m for m in TSW.members(tmp_path, "state/attains.tar.gz") if "/._" not in m]   # a Mac's tar adds '._' files
    assert got == ["data/build/attains/attains-waters.json"]


def test_a_failed_weekly_build_saves_nothing(tmp_path, monkeypatch):
    TSW, r = _simulate(tmp_path, monkeypatch, build_fails=True)
    assert r["failed"] and TSW.puts(tmp_path) == []


def test_a_geometry_cache_that_could_not_be_fetched_is_kept(tmp_path, monkeypatch):
    TSW, r = _simulate(tmp_path, monkeypatch, env={"FAKE_R2_FAIL_GET": "state/attains-geom.tar.gz"})
    assert not r["failed"], r["log"]
    assert TSW.puts(tmp_path) == ["put state/attains.tar.gz"]


def test_the_weekly_run_honours_the_pause_switch(tmp_path, monkeypatch):
    TSW, r = _simulate(tmp_path, monkeypatch, paused=True)
    assert not r["failed"] and TSW.puts(tmp_path) == []
