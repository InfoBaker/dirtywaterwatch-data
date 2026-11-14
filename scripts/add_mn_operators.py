"""Minnesota operator rows for data/dischargers.json: one row per operator, every Minnesota permit in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_mn_operators.py [--dry-run]

Built by scripts/icis_operators.py (the rules are in its docstring) from EPA ICIS-NPDES's 661 Minnesota sewage-plant
permits (data/outfalls-plants-us.json), EPA's CSO inventory (Minneapolis's joint permit MN0046744: seven outfalls, all
closed), research/mn/dischargers.json (five operators) and research/mn/private-utilities-candidates.json (19 permits).
Minnesota specifics:
  - The Metropolitan Council's nine plant permits are one row ("Metropolitan Council", its Environmental Services
    division runs the regional interceptors and plants); its research id mn-mces is an alias, so the spill-notice
    feed (mn-mces-spill-notices) resolves. WLSSD is its permit MN0049786 (research id mn-wlssd). The City of Duluth
    holds no plant permit of its own (its sewage goes to WLSSD): its row comes from the research, kind sso.
  - notification_channel: Minn. Stat. 115.061 (quoted below) and then the operator's own channel as the research found
    it. The duty in paragraph (c) binds a publicly owned treatment works and any public or private domestic sewer
    system owner alike.
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from icis_operators import ROOT, run  # noqa: E402

LAW = ("Minn. Stat. 115.061: (a) every person must notify the Minnesota Pollution Control Agency immediately (through "
       "the Minnesota Duty Officer) of a discharge that may pollute waters of the state; (c) promptly after that, a "
       "publicly owned treatment works or a publicly or privately owned domestic sewer system owner must notify "
       "potentially impacted downstream users, including the public, Tribal governments and drinking water facilities, "
       "by the most efficient means it has (in person, telephone, radio, social media, a web page or another expedited "
       "form), post signs at impacted public use areas or tell the body that runs them, and give the date and time of "
       "the discharge, the material, a warning of the health risk and its contact. The Duty Officer's reports are not "
       "published and no statewide list of the notices exists.")
NOT_SEARCHED = " Its own public channel was not searched individually."


def channel(rs: list[dict], private: bool, is_cso: bool) -> str:
    s = LAW
    found = [r["notification_channel"] for r in rs if r.get("verified") == "fetched"]
    listed = [r["notification_channel"] for r in rs if r.get("verified") != "fetched"
              and not str(r.get("notification_channel") or "").lower().startswith("not searched")]
    if found:
        s += " Its channel: " + " ".join(found)
    elif listed:
        s += " Listed for it (not read here): " + " ".join(listed)
    else:
        s += NOT_SEARCHED
    if private:
        s += " The statute binds a private sewer system owner as it binds a public one."
    return s


CFG = {
    "state": "MN", "area": "mn", "checked": "2026-11-14",
    "research": ROOT / "research" / "mn" / "dischargers.json",
    "candidates": ROOT / "research" / "mn" / "private-utilities-candidates.json",
    "research_permit": {"mn-wlssd": "MN0049786", "mn-mces": "MN0029815"},
    "research_name": {"MN0049786": "Western Lake Superior Sanitary District",
                      "MN0046744": "Minneapolis Public Works and Metropolitan Council (joint CSO permit)",
                      "MN0025488": "Metropolitan Council"},       # EPA: "METROPOLITAN COUNCIL-ROSEMOUNT", its plant
    "form_by_name": {"Metropolitan Council": "special district",
                     "Metropolitan Council-Rosemount": "special district",
                     "Western Lake Superior Sanitary District": "special district",
                     "Minneapolis Public Works and Metropolitan Council (joint CSO permit)": "city",
                     "City of Duluth (sanitary collection system)": "city"},
    "state_words": ("Minnesota", "MN"),
    "channel": channel,
}


if __name__ == "__main__":
    sys.exit(run(CFG, sys.argv[1:]))
