"""North Dakota operator rows for data/dischargers.json: one row per operator, every North Dakota permit in exactly one
row.

Usage: pipeline/.venv/bin/python -I scripts/add_nd_operators.py [--dry-run]

Built by scripts/icis_operators.py (the rules are in its docstring) from EPA ICIS-NPDES's 399 North Dakota sewage-plant
permits (data/outfalls-plants-us.json: 75 individual permits ND0..., 324 general-permit coverages NDG...; EPA writes
the permits in Indian country, the Three Affiliated Tribes' ND0000005 among them), research/nd/dischargers.json (the
nine largest cities) and research/nd/private-utilities-candidates.json (21 permits). North Dakota has no combined sewer
outfall in EPA's inventory.
notification_channel: what North Dakota requires (below), then the operator's own channel as the research found it.
The public-notification clause in Fargo's 2023 permit was read in the draft put out for comment; whether the final
permit kept it was not confirmed, so it is quoted as the draft's for Fargo only.
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from icis_operators import ROOT, run  # noqa: E402

LAW = ("No North Dakota statute or rule requires the public to be told of a sewage discharge. N.D. Admin. Code "
       "33.1-16-02.1-11(4) requires a spill or discharge that causes or is likely to cause water pollution to be "
       "reported to the Department of Environmental Quality immediately (by telephone or through spill.nd.gov); the "
       "permits' standard conditions (the domestic-treatment general permit NDG420000, Part IV(F), and the individual "
       "permits) add an oral report within 24 hours and a written one within five days. Reports since 2021 go into the "
       "state's unified spill system, whose public incident list refuses automated readers; reports from 1975 to 2020 "
       "are in the Department's public archive. Electronic reports through EPA's NeT-SewerOverflow: none from a North "
       "Dakota permit in EPA's 2026-11-12 tables.")
FARGO = (" Fargo's draft permit of 2023 (public notice ND-2023-021) would require it to notify the public, public health "
         "agencies and affected entities immediately of an overflow its plan identifies, the channel set by the plan; "
         "the final permit and plan were not read.")
NOT_SEARCHED = " Its own public channel was not searched individually."


def channel(rs: list[dict], private: bool, is_cso: bool) -> str:
    s = LAW
    if any(r["id"] == "nd-fargo" for r in rs):
        s += FARGO
    else:
        listed = [r["notification_channel"] for r in rs if r.get("verified") == "fetched"]
        s += (" Its channel: " + " ".join(listed)) if listed else NOT_SEARCHED
    if private:
        s += " The rule and the permit bind a private permittee as they bind a public one."
    return s


CFG = {
    "state": "ND", "area": "nd", "checked": "2026-11-14",
    "research": ROOT / "research" / "nd" / "dischargers.json",
    "candidates": ROOT / "research" / "nd" / "private-utilities-candidates.json",
    "research_name": {"ND0023434": "City of Bismarck"},
    "form_by_name": {},
    "state_words": ("North Dakota", "ND"),
    "channel": channel,
}


if __name__ == "__main__":
    sys.exit(run(CFG, sys.argv[1:]))
