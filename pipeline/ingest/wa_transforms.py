"""Washington hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

kc_cso_outfall: the King County / Seattle CSO status CSV (data/sources/wa-kc-cso-status-csv.yaml). Each row names its
operator in Name ("King County CSO: Ballard" for King County's outfalls under NPDES WA0029181, "Seattle CSO" for
Seattle Public Utilities' under WA0031682) and its discharge serial number in DSN, which is the permit's outfall
number (DSN 3 is King County's outfall 003, Ballard Siphon Regulator; DSN 124 is Seattle's outfall 124, Lake Union
Park, in EPA ICIS-NPDES). The hook sets the operator, the permit and the outfall, so the status build places each
event on the registry's outfall (data/outfalls-wa.json) and its water.
"""
from __future__ import annotations

import re

from ingest.generic import fieldmap as F

KC_OPERATORS = {
    "king county": ("wa-king-county-west-point", "WA0029181", "King County Wastewater Treatment Division"),
    "seattle": ("wa-seattle-spu", "WA0031682", "Seattle Public Utilities"),
}


def kc_operator(name: str) -> tuple[str, str, str] | None:
    n = F.clean(name).lower()
    for prefix, op in KC_OPERATORS.items():
        if n.startswith(prefix):
            return op
    return None


def dsn(v) -> str | None:
    s = F.clean(v)
    return s.zfill(3) if re.fullmatch(r"\d{1,3}[A-Za-z]?", s) and s[0].isdigit() else None


@F.hook
def kc_cso_outfall(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    name = F.clean(row.get("Name"))
    op = kc_operator(name)
    out = dsn(row.get("DSN"))
    if op is None:
        notes.setdefault("_problems", []).append(f"Name {name!r} names neither King County nor Seattle")
        return
    rec["discharger_id"], rec["npdes_permit"], rec["discharger_name"] = op
    rec["outfall_id"] = out
    label = name.split(":", 1)[1].strip() if ":" in name else None
    rec["outfall_name"] = label or (f"{name} outfall {out}" if out else name)
    notes["_operator_basis"] = (f"Name {name!r}: {op[2]}, NPDES {op[1]}; DSN {F.clean(row.get('DSN'))!r} is the "
                                f"permit's outfall {out}")
