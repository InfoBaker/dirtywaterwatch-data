"""The state-name lists of the chart builder and the report geocoder name every state with operators in
data/dischargers.json (Florida was missing: chart labels read "FL" and the town geocoder was asked for state "FL")."""
import json

from build import charts, report_geolocate
from common import DATA_DIR
from export.coverage import STATE_NAMES as FULL

STATES = {r["state"] for r in json.loads((DATA_DIR / "dischargers.json").read_text())}


def test_florida_is_named():
    assert charts.STATE_NAMES["FL"] == report_geolocate.STATE_NAMES["FL"] == "Florida"


def test_every_state_with_operators_is_named_as_the_export_names_it():
    # DC stays "DC" in the charts: a live state whose chart wording ("in DC") is left as it is
    for names, exempt in ((report_geolocate.STATE_NAMES, set()), (charts.STATE_NAMES, {"DC"})):
        assert STATES - exempt <= set(names), sorted(STATES - exempt - set(names))
        assert all(FULL[k] == v for k, v in names.items())
