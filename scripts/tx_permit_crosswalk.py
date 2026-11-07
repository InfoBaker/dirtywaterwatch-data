"""data/reference/tx-tceq-permits.json: TCEQ's ids of a Texas wastewater operator (the regulated entity number RN... and
the state permit WQ...) to the federal NPDES id (TX0......) the outfall registry and data/dischargers.json use.

Usage (after the TCEQ table and EPA's Facility Registry file for Texas are saved under data/raw/):
    pipeline/.venv/bin/python -I scripts/tx_permit_crosswalk.py

Inputs (git-ignored raw files; the output is public data only: ids and counts)
  1. TCEQ's Sanitary Sewer Overflows table (data.texas.gov 8kc5-95uk; data/raw/tx-tceq-sso-opendata/, the newest saved
     response): list_of_permits gives the federal id beside the WQ permit on some rows ("WASTEWATER-EPA ID-TX0125288;
     WASTEWATER-PERMIT-WQ0014377001"); such a row pairs its WQ permits and its regulated entity with that federal id.
  2. EPA's Facility Registry Service state file for Texas (https://ordsext.epa.gov/FLA/www3/state_files/
     state_single_tx.zip; data/raw/epa-frs-tx/): a facility's PGM_SYS_ACRNMS lists its program ids, TCEQ's
     ("TX-TCEQ ACR:RN100217603") beside EPA's ("NPDES:TX0096172"). Only the program ids are read, no address.
Rules
  - Only individual federal permits (TX followed by seven digits) are kept; stormwater and general authorisations
    (TXR..., TXG...) are not sewage permits of the operator.
  - Only the entities and WQ permits the TCEQ table names are written.
  - A key with several federal ids keeps them all; the ingester (ingest/tx_transforms.py) uses a key only when it gives
    exactly one.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "tx-tceq-sso-opendata"
FRS = ROOT / "data" / "raw" / "epa-frs-tx" / "state_single_tx.zip"
OUT = ROOT / "data" / "reference" / "tx-tceq-permits.json"
FRS_URL = "https://ordsext.epa.gov/FLA/www3/state_files/state_single_tx.zip"
EPA_ID = re.compile(r"WASTEWATER-EPA ID-(TX\d{7})")
WQ_ID = re.compile(r"WASTEWATER-PERMIT-(WQ\d{10})")
NPDES = re.compile(r"\bNPDES:(TX\d{7})\b")
RN = re.compile(r"\bTX-TCEQ ACR:(RN\d{9})\b")


def tceq_rows() -> list[dict]:
    saved = sorted(p for p in RAW.glob("*.json") if not p.name.endswith(".meta.json") and p.name != "meta.json")
    if not saved:
        raise SystemExit(f"no saved TCEQ table under {RAW.relative_to(ROOT)}")
    doc = json.loads(saved[-1].read_text())
    return [r for pg in (doc.get("pages") if isinstance(doc, dict) else [doc]) for r in pg]


def frs_links() -> dict[str, set[str]]:
    """RN -> the individual federal ids EPA's registry links to it."""
    if not FRS.exists():
        raise SystemExit(f"save {FRS_URL} as {FRS.relative_to(ROOT)} first")
    out: dict[str, set[str]] = defaultdict(set)
    with zipfile.ZipFile(FRS) as z:
        name = next(n for n in z.namelist() if n.upper().endswith(".CSV"))
        with z.open(name) as fh:
            for row in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace")):
                p = row.get("PGM_SYS_ACRNMS") or ""
                rns, ids = RN.findall(p), NPDES.findall(p)
                for rn in rns:
                    out[rn].update(ids)
    return out


def main() -> int:
    rows = tceq_rows()
    rn_tx, wq_tx = defaultdict(set), defaultdict(set)
    rns, wqs = set(), set()
    for r in rows:
        lst = r.get("list_of_permits") or ""
        rn = (r.get("regulated_entity_number") or "").strip().upper()
        ids, wq = set(EPA_ID.findall(lst)), set(WQ_ID.findall(lst))
        rns.add(rn)
        wqs |= wq
        if ids:
            rn_tx[rn] |= ids
            for q in wq:
                wq_tx[q] |= ids
    from_rows = {k: set(v) for k, v in rn_tx.items()}
    frs = frs_links()
    added = Counter()
    for rn in rns:
        got = frs.get(rn) or set()
        if got - rn_tx.get(rn, set()):
            added["entities given a federal id by the registry" if rn not in from_rows
                  else "entities given a further federal id by the registry"] += 1
        if got:
            rn_tx[rn] |= got
    doc = {
        "about": ("TCEQ's ids of Texas wastewater operators (regulated entity RN..., state permit WQ...) and the federal "
                  "NPDES ids (TX0......) they hold: from the TCEQ Sanitary Sewer Overflows table's rows that give both "
                  "(data.texas.gov 8kc5-95uk) and from EPA's Facility Registry Service, whose facilities list TCEQ's "
                  "entity number beside EPA's permit. Individual permits only; only the entities and permits the TCEQ "
                  "table names. Written by scripts/tx_permit_crosswalk.py."),
        "sources": [{"source": "tx-tceq-sso-opendata", "url": "https://data.texas.gov/dataset/8kc5-95uk"},
                    {"source": "EPA Facility Registry Service state file (Texas)", "url": FRS_URL}],
        "counts": {"entities_in_table": len(rns), "entities_with_federal_id": len(rn_tx),
                   "entities_with_one_federal_id": sum(1 for v in rn_tx.values() if len(v) == 1),
                   "wq_permits_in_table": len(wqs), "wq_permits_with_federal_id": len(wq_tx), **dict(added)},
        "rn_to_npdes": {k: sorted(v) for k, v in sorted(rn_tx.items())},
        "wq_to_npdes": {k: sorted(v) for k, v in sorted(wq_tx.items())},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print(json.dumps(doc["counts"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
