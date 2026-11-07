"""Alaska registry: the operator rows (scripts/add_ak_operators.py) and the register rows
(scripts/add_ak_register_rows.py) as committed: every Alaska permit of EPA's tables in exactly one row, no name read
from EPA's permit-name field (which often puts a contact person before the body), the per-operator DEC notice rows
and Juneau's permit rows."""
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _ak_rows():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "AK"]


def test_every_alaska_permit_is_in_exactly_one_operator_row():
    ops = _script("add_ak_operators")
    epa = ops.load_epa()
    rows = _ak_rows()
    held = [p for r in rows for p in r["npdes_permits"]]
    assert len(held) == len(set(held))
    assert set(held) == set(epa) == set(ops.PERMITS)
    assert all(r["npdes_permit"] == r["npdes_permits"][0] for r in rows)
    by = {r["id"]: r for r in rows}
    assert by["ak-juneau-douglas"]["kind"] == "cso" and "AK0023213" in by["ak-juneau-douglas"]["npdes_permits"]
    assert by["ak-apsc-taps"]["kind"] == "cso_closed_or_none"
    assert {"AK0022551", "AK0022543", "AK0047856"} <= set(by["ak-awwu-anchorage"]["npdes_permits"])
    assert by["ak-fairbanks-ghu"]["legal_form"] == "investor-owned utility"


def test_no_name_from_epas_permit_name_field_reaches_a_row():
    """EPA's permit_name reads '<person> - <body>' for many Alaska permits: the person half never appears."""
    people = set()
    for f in ("outfalls-plants-us.json", "outfalls-us.json"):
        doc = json.loads((ROOT / "data" / f).read_text())
        for r in doc["outfalls"] if isinstance(doc, dict) else doc:
            pn = str(r.get("permit_name") or "")
            m = re.match(r"^([A-Z][a-z]+(?: [A-Z][a-z]+)+(?:,? (?:Jr|Sr)\.?)?)\s*[-,]\s*\S", pn)
            if str(r.get("npdes_permit") or "").startswith("AK") and m:
                people.add(m.group(1).strip(" ,"))
    assert len(people) > 30                              # the field does carry them
    blob = json.dumps(_ak_rows())
    reg = (ROOT / "data" / "notice-channels" / "ak.json").read_text()
    for p in people:
        assert p not in blob and p not in reg, "a contact's name reached a row"


def test_register_rows_per_operator_and_juneau():
    reg = json.loads((ROOT / "data" / "notice-channels" / "ak.json").read_text())["channels"]
    ids = {r["id"]: r for r in reg}
    ops = [r for r in _ak_rows() if r["kind"] != "cso_closed_or_none"]
    for op in ops:
        row = ids[f"{op['id']}-dec-emergency-notice"]
        assert row["basis_kind"] == "permit" and "18 AAC 72.940" in row["legal_basis"] and row["urls"] == []
        assert row["barrier"] == "no_web_page"
    cso = ids["ak-juneau-douglas-cso-public-notification"]
    assert cso["monitored"] and cso["urls"] and "Part I.D.1.g" in cso["legal_basis"] and cso["entry"]["start"]
    assert ids["ak-juneau-douglas-sso-public-notification"]["barrier"] == "not_verified"
    assert ids["ak-epa-echo-overflow-events"]["feed_source_id"] == "echo-sewer-overflow"
    assert ids["ak-dec-spill-database"]["barrier"] == "bot_wall"
    assert "ak-apsc-taps-dec-emergency-notice" not in ids
