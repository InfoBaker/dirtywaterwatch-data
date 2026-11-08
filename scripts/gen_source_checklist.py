#!/usr/bin/env python3
"""Regenerate docs/source-checklist.md from docs/source-checklist.json, and append new research areas.

    python3 scripts/gen_source_checklist.py --check            # md must equal what the json generates
    python3 scripts/gen_source_checklist.py --add md va dc     # append research/<area>/sources.json rows, rewrite both files
    python3 scripts/gen_source_checklist.py --refresh ga nc    # replace an area's rows with its research rows, in place

The json is a list of the research rows in research order (area by area), each with an `area` field
added last. The md has a counts table and, per area, a table sorted by status (used, candidate, watch,
rejected, unreachable) then by id. An id that is already in the json is not added twice (the research
rows of one area are never edited here; a clash with another area needs a hand decision). --refresh takes an area
already in the checklist back to what research/<area>/sources.json says now (a status that changed, a row added),
keeping the area's place in the list; an id another area holds is refused the same way.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry_rows_from_research import scrub_row  # noqa: E402  (personal data out of every row we add)

ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "docs" / "source-checklist.json"
MD_PATH = ROOT / "docs" / "source-checklist.md"

STATUSES = ["used", "candidate", "watch", "rejected", "unreachable"]
AREA_TITLES = {
    "science": "Science (criteria, studies, advisory wording)",
    "federal": "Federal (EPA, USGS, NOAA, law)",
    "ma": "Massachusetts",
    "ct": "Connecticut",
    "ri": "Rhode Island",
    "nh-vt": "New Hampshire and Vermont",
    "me": "Maine",
    "community": "Community and prior art",
    "hydrography": "Hydrography (flow, downstream)",
    "ny": "New York",
    "nj": "New Jersey",
    "pa": "Pennsylvania",
    "md": "Maryland",
    "va": "Virginia",
    "fl": "Florida",
    "dc": "District of Columbia",
    "nc": "North Carolina",
    "ga": "Georgia",
    "mi": "Michigan",
    "wa": "Washington",
    "ca": "California",
    "il": "Illinois",
    "az": "Arizona",
    "sd": "South Dakota",
    "ms": "Mississippi",
    "ne": "Nebraska",
    "ak": "Alaska",
    "nm": "New Mexico",
    "ky": "Kentucky",
    "hi": "Hawaii",
    "or": "Oregon",
    "al": "Alabama",
    "ut": "Utah",
    "tx": "Texas",
}

HEADER = """# Source checklist

Every source considered by the wave-1 research, used or not, with its status and why. Generated 2026-11-02 from `research/*/sources.json` ({n} rows; the full rows with every field are in `docs/source-checklist.json`, each with an `area` field naming the research folder). The owner's rule: consider all of them, not just the top candidates. The "why" column is the research's status_reason; the JSON keeps the exact text (this table only swaps an em-dash for a hyphen).

Statuses as the research agents set them: **used** (read and relied on, or chosen as a feed to build against), **candidate** (usable, not yet built or decided), **watch** (context, or check again later), **rejected** (looked at and not usable; reason given), **unreachable** (could not be fetched from the research machine; reason given). `verified`: fetched (the page or endpoint was read), search_only (found by search, not read), inferred.

One id appears in two areas: `crwa-flagging` (hydrography: candidate; science: used). Both rows are kept with the area as a suffix: `crwa-flagging-hydrography`, `crwa-flagging-science`.

## Counts by area and status

"""


def cell(s) -> str:
    return str(s if s is not None else "").replace("—", "-").replace("|", "\\|").replace("\n", " ").strip()


def render(rows: list[dict]) -> str:
    areas: list[str] = []
    for r in rows:
        if r["area"] not in areas:
            areas.append(r["area"])
    by_area = {a: [r for r in rows if r["area"] == a] for a in areas}
    out = [HEADER.format(n=len(rows))]
    out.append("| area | " + " | ".join(STATUSES) + " | total |\n")
    out.append("|---|" + "---:|" * (len(STATUSES) + 1) + "\n")
    tot = Counter()
    for a in areas:
        c = Counter(r["status"] for r in by_area[a])
        tot.update(c)
        out.append(f"| {a} | " + " | ".join(str(c[s]) for s in STATUSES) + f" | {len(by_area[a])} |\n")
    out.append("| **all** | " + " | ".join(f"**{tot[s]}**" for s in STATUSES) + f" | **{len(rows)}** |\n")
    for a in areas:
        out.append(f"\n## {a}: {AREA_TITLES[a]} ({len(by_area[a])})\n\n")
        out.append("| id | name | status | verified | role | why |\n|---|---|---|---|---|---|\n")
        for r in sorted(by_area[a], key=lambda r: (STATUSES.index(r["status"]), r["id"])):
            out.append(f"| `{r['id']}` | {cell(r['name'])} | {r['status']} | {r.get('verified')} | {r.get('role')} | "
                       f"{cell(r.get('status_reason'))} |\n")
    return "".join(out)


def load() -> list[dict]:
    return json.loads(JSON_PATH.read_text())


def refresh(rows: list[dict], area: str, research: list[dict]) -> list[dict]:
    """The checklist with the area's rows replaced by its research rows (scrubbed, in research order) where the area's
    first row stood."""
    at = next((i for i, r in enumerate(rows) if r["area"] == area), None)
    if at is None:
        raise SystemExit(f"{area}: not in the checklist (use --add)")
    others = {r["id"] for r in rows if r["area"] != area}
    clash = [r["id"] for r in research if r["id"] in others]
    if clash:
        raise SystemExit(f"{area}: ids another area holds: {clash}")
    keep = [r for r in rows if r["area"] != area]
    new = [{**scrub_row(r), "area": area} for r in research]
    before = sum(1 for r in rows[:at] if r["area"] != area)
    return keep[:before] + new + keep[before:]


def main(argv: list[str]) -> int:
    rows = load()
    if argv[:1] == ["--check"]:
        same = render(rows) == MD_PATH.read_text()
        print("md matches json" if same else "md DIFFERS from what the json generates")
        return 0 if same else 1
    if argv[:1] == ["--add"]:
        have = {r["id"] for r in rows}
        for area in argv[1:]:
            new = json.loads((ROOT / "research" / area / "sources.json").read_text())
            clash = [r["id"] for r in new if r["id"] in have]
            if clash:
                raise SystemExit(f"{area}: ids already in the checklist: {clash}")
            if any(r["area"] == area for r in rows):
                raise SystemExit(f"{area}: already in the checklist")
            for r in new:
                rows.append({**scrub_row(r), "area": area})
                have.add(r["id"])
        JSON_PATH.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    if argv[:1] == ["--refresh"]:
        for area in argv[1:]:
            rows = refresh(rows, area, json.loads((ROOT / "research" / area / "sources.json").read_text()))
        JSON_PATH.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    MD_PATH.write_text(render(rows))
    print(f"{len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
