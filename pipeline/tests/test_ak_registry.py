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
    assert by["ak-steelhead-barge"]["towns"] == ["Ketchikan"] and "Anchorage" not in by["ak-steelhead-barge"]["name"]
    assert "not searched" not in by["ak-juneau-douglas"]["notification_channel"]


BODY = re.compile(r"\b(?:City|Borough|District|Council|Village|Community|Corporation|Corp|LLC|Inc|Utilities|Utility|"
                  r"Services|Service|Dept|Department|NPS|Park|Interior|Defense|Navy|Army|Force|School|Municipality|"
                  r"Health|Systems|Tribe|Tribal|Native|Traditional|Highway|AWWU|Facility|Lagoon|WWTF|WWTP)\b", re.I)


def _person_parts():
    """Person-shaped parts of EPA's Alaska permit names: every field that is not all capitals is split at '-' and ','
    and each part without a body word that reads as two or more capitalised words (an inner capital and Jr/Sr allowed)
    is kept, the whole field included when it holds no body word at all."""
    parts = set()
    for f in ("outfalls-plants-us.json", "outfalls-us.json"):
        doc = json.loads((ROOT / "data" / f).read_text())
        for r in doc["outfalls"] if isinstance(doc, dict) else doc:
            pn = str(r.get("permit_name") or "").strip()
            if not str(r.get("npdes_permit") or "").startswith("AK") or not pn or pn.isupper():
                continue
            for part in re.split(r"\s*[-,]\s*", pn):
                part = re.sub(r"\s+(?:Jr|Sr)\.?$", "", part.strip(" ,."))
                if part and not BODY.search(part) and re.fullmatch(r"[A-Z][A-Za-z']+(?: [A-Z][A-Za-z']+)+", part):
                    parts.add(part)
    return parts


def test_no_name_from_epas_permit_name_field_reaches_a_row():
    """EPA's permit_name often reads '<person> - <body>', and sometimes is a person's name alone: no such name, and no
    two-word start of one, appears in the operator rows or the register (the names are read here, never listed)."""
    people = _person_parts()
    # scripts/permit_names.py cut them from the registry (2026-11-07): none is left, and none reached a row
    assert not people, f"{len(people)} person-shaped parts left in EPA's Alaska permit names"
    blob = json.dumps(_ak_rows())
    reg = (ROOT / "data" / "notice-channels" / "ak.json").read_text()
    text = (ROOT / "research" / "ak" / "state-text.md").read_text()
    for p in people:
        two = " ".join(p.split()[:2])
        for t in (blob, reg, text):
            assert p not in t and two not in t, "a contact's name reached a row"


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
    sso = ids["ak-juneau-douglas-sso-public-notification"]
    assert sso["barrier"] == "not_verified" and "Part II.H.2.a" in sso["legal_basis"] and "III.H" not in sso["legal_basis"]
    assert "Part II.H.2.a" in next(r for r in _ak_rows() if r["id"] == "ak-juneau-douglas")["notification_channel"]
    for pmt, part in (("AK0023213", "Part I.C.7"), ("AK0022951", "Part 2.5")):
        sign = ids[f"ak-juneau-douglas-outfall-signs-{pmt.lower()}"]
        assert sign["permit"] == pmt and part in sign["legal_basis"] and sign["urls"] == []
        assert sign["barrier"] == "signs_only"
    assert cso["urls"] == ["https://juneau.org/engineering-public-works/utilities-division/wastewater-utility-division"]
    assert ids["ak-ahab-network"]["urls"] == ["https://ahab.aoos.org/"]
    assert ids["ak-epa-echo-overflow-events"]["feed_source_id"] == "echo-sewer-overflow"
    assert ids["ak-dec-spill-database"]["barrier"] == "bot_wall"
    assert "ak-apsc-taps-dec-emergency-notice" not in ids
