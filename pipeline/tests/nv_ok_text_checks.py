"""Checks shared by the Nevada and Oklahoma text tests (Astra P2-12, P3-13): public texts state dated observations and
search limits, never confirmed absence the saved evidence does not support, cite no file this repository lacks, and
give the operator and permit counts the registry computes."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OVERCLAIMS = re.compile(r"\bno API\b|as a picture|picture with no data|no data endpoint|publishes none of these|"
                        r"No sewage discharge report is published|posts no list|shows the public nothing|only statewide", re.I)


def public_texts(st: str) -> dict:
    low = st.lower()
    out = {"state-text": (ROOT / "research" / low / "state-text.md").read_text(),
           "rules": json.dumps(json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"][st])}
    for y in (ROOT / "data" / "sources").glob(f"{low}-*.yaml"):
        out[y.name] = y.read_text()
    for c in json.loads((ROOT / "data" / "notice-channels" / f"{low}.json").read_text())["channels"]:
        out[c["id"]] = json.dumps(c)
    for r in json.loads((ROOT / "data" / "dischargers.json").read_text()):
        if r.get("state") == st:
            out[r["id"]] = json.dumps(r)
    return out


def bad_citations(texts: dict) -> list:
    """research/... file references that this repository does not hold and that are not marked as the site
    repository's."""
    bad = []
    for k, t in texts.items():
        for m in re.finditer(r"(?<![\w/])(research/[\w./-]+\.(?:md|json))", t):
            if not (ROOT / m.group(1)).exists() and "site repository" not in t[max(0, m.start() - 40):m.start()]:
                bad.append((k, m.group(1)))
    return bad


def counts(st: str) -> dict:
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == st} - {"AZ0025160"}
    rows = [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == st]
    ops = [r for r in rows if not r.get("permit_only") and set(r["npdes_permits"]) & plants]
    po = [r for r in rows if r.get("permit_only")]
    return {"plant_permits": len(plants), "operators": len(ops),
            "operator_permits": sum(len(set(r["npdes_permits"]) & plants) for r in ops),
            "permit_only_rows": len(po), "permit_only_permits": sum(len(r["npdes_permits"]) for r in po),
            "points": sum(r["outfall_count"] or 0 for r in rows),
            "other_permits": sum(len(set(r["npdes_permits"]) - plants) for r in rows)}
