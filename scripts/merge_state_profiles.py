#!/usr/bin/env python3
"""Merge research/<st>/profile.json into data/state-profiles.json and write docs/national-readiness.md.

The profiles are the research agents' per-state records (shape: research/00-national-brief.md). This script
validates the enums, fills the federal counts from the outfall registries, merges live-state rows from the
existing research and rules, and writes:

  data/state-profiles.json   one row per state and territory, sorted by code (the national registry of readiness)
  docs/national-readiness.md the readiness table and the per-state one-liners (generated; do not edit by hand)

Run from the repository root:  python3 -I scripts/merge_state_profiles.py [--check]
--check validates only and exits non-zero on an invalid profile.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
OUT_JSON = ROOT / "data" / "state-profiles.json"
OUT_MD = ROOT / "docs" / "national-readiness.md"

ENUMS = {
    "region": {"northeast", "mid-atlantic", "southeast", "gulf", "great-lakes", "ohio-valley", "plains", "mountain",
               "southwest", "pacific", "alaska-hawaii", "territories"},
    "npdes_authority": {"state", "epa", "mixed", "unknown"},
    "great_lakes_basin": {"yes", "part", "no", "unknown"},
    "public_notice_duty": {"yes", "partial", "none", "unknown"},
    "precision": {"event", "daily", "monthly", "annual", "none", "unknown"},
    "format": {"socrata", "arcgis", "csv", "json", "rss", "html", "pdf", "email", "map_only", "none", "unknown"},
    "barrier_kind": {"print_only", "sign_only", "login", "bot_wall", "image_only", "email_only", "records_request",
                     "licence", "no_web", "phone_only", "app_only", "map_only", "unknown"},
    "fix_level": {"legislative", "agency", "operator", "engineering", "owner", "unknown"},
    "effort": {"small", "medium", "large", "unknown"},
    "tier": {"A", "B", "C", "D", "live", "unknown"},
}
GRADES = {"Dated reports", "Dated reports, delayed", "Monthly totals only", "Annual totals only",
          "No public reports", "unknown"}

NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico", "VI": "U.S. Virgin Islands",
    "GU": "Guam", "AS": "American Samoa", "MP": "Northern Mariana Islands",
}
LIVE_REGION = {"CT": "northeast", "MA": "northeast", "ME": "northeast", "NH": "northeast", "RI": "northeast",
               "VT": "northeast", "NJ": "mid-atlantic", "NY": "mid-atlantic", "PA": "mid-atlantic",
               "MD": "mid-atlantic", "VA": "mid-atlantic", "DC": "mid-atlantic"}


def load_rows(path: pathlib.Path) -> list:
    d = json.loads(path.read_text())
    if isinstance(d, list):
        return d
    for k in ("outfalls", "rows", "records"):
        if isinstance(d.get(k), list):
            return d[k]
    raise SystemExit(f"{path}: no row list")


def federal_counts() -> dict:
    counts: dict = collections.defaultdict(lambda: {"cso_permits": set(), "cso_open_outfalls": 0,
                                                    "plant_permits": set(), "plant_permits_major": set()})
    for f in ("data/outfalls-us.json", "data/outfalls-new-england.json", "data/outfalls-mid-atlantic.json"):
        p = ROOT / f
        if not p.exists():
            continue
        for r in load_rows(p):
            if r.get("outfall_kind", "cso") != "cso":
                continue
            c = counts[r["state"]]
            c["cso_permits"].add(r["npdes_permit"])
            if r.get("outfall_status") != "CLS":
                c["cso_open_outfalls"] += 1
    p = ROOT / "data" / "outfalls-plants-us.json"
    if p.exists():
        for r in load_rows(p):
            c = counts[r["state"]]
            c["plant_permits"].add(r["npdes_permit"])
            if r.get("major_minor") == "Major":
                c["plant_permits_major"].add(r["npdes_permit"])
    return {st: {"cso_permits": len(c["cso_permits"]), "cso_open_outfalls": c["cso_open_outfalls"],
                 "plant_permits": len(c["plant_permits"]), "plant_permits_major": len(c["plant_permits_major"])}
            for st, c in counts.items()}


def check_enum(errors: list, st: str, field: str, value, enum: str) -> None:
    if value is None:
        return
    if value not in ENUMS[enum]:
        errors.append(f"{st}: {field} = {value!r} not in {sorted(ENUMS[enum])}")


def validate(st: str, p: dict) -> list:
    errors: list = []
    if p.get("state") != st:
        errors.append(f"{st}: profile.state is {p.get('state')!r}")
    for key in ("law", "erule", "statewide_feed", "cso", "sso", "beaches", "habs", "outfalls", "waters",
                "barriers", "readiness"):
        if key not in p:
            errors.append(f"{st}: missing {key}")
    check_enum(errors, st, "region", p.get("region"), "region")
    check_enum(errors, st, "npdes_authority", p.get("npdes_authority"), "npdes_authority")
    check_enum(errors, st, "great_lakes_basin", p.get("great_lakes_basin"), "great_lakes_basin")
    law = p.get("law") or {}
    check_enum(errors, st, "law.public_notice_duty", law.get("public_notice_duty"), "public_notice_duty")
    feed = p.get("statewide_feed") or {}
    check_enum(errors, st, "statewide_feed.precision", feed.get("precision"), "precision")
    check_enum(errors, st, "statewide_feed.format", feed.get("format"), "format")
    for i, b in enumerate(p.get("barriers") or []):
        check_enum(errors, st, f"barriers[{i}].kind", b.get("kind"), "barrier_kind")
        check_enum(errors, st, f"barriers[{i}].fix_level", b.get("fix_level"), "fix_level")
    rd = p.get("readiness") or {}
    check_enum(errors, st, "readiness.tier", rd.get("tier"), "tier")
    check_enum(errors, st, "readiness.effort", rd.get("effort"), "effort")
    if rd.get("expected_grade") not in GRADES:
        errors.append(f"{st}: readiness.expected_grade = {rd.get('expected_grade')!r} not in {sorted(GRADES)}")
    return errors


def live_profile(st: str, rules: dict, fed: dict) -> dict:
    red = (rules.get("red") or {}).get("by_state", {}).get(st) or {}
    return {
        "state": st, "name": NAMES[st], "region": LIVE_REGION[st], "checked": rules.get("version", "")[:10],
        "live": True,
        "law": {"public_notice_duty": "see research", "summary": red.get("basis"), "citations": [
            {"cite": red.get("source"), "verified": "fetched"}] if red else []},
        "readiness": {"tier": "live", "expected_grade": "see docs/source-tally.md", "first_feed": None,
                      "effort": None, "rationale": "Live; docs/source-tally.md carries the current grade."},
        "federal": fed.get(st, {}),
        "research": f"research/{st.lower() if st != 'NH' and st != 'VT' else 'nh-vt'}/report.md",
    }


def main(check_only: bool = False) -> int:
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    live = set(rules.get("live_states", []))
    fed = federal_counts()
    rows: dict = {}
    errors: list = []
    for d in sorted(RESEARCH.iterdir()):
        pf = d / "profile.json"
        if not pf.exists():
            continue
        st = d.name.upper()
        if "-" in d.name or len(d.name) > 6:
            continue
        try:
            p = json.loads(pf.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"{st}: profile.json invalid JSON: {e}")
            continue
        if d.name == "border":
            st = "XB"
        p.setdefault("state", st)
        errs = validate(st, p)
        errors.extend(errs)
        p.setdefault("name", NAMES.get(st, st))
        p["live"] = st in live
        p["federal"] = fed.get(st, {"cso_permits": 0, "cso_open_outfalls": 0, "plant_permits": 0,
                                    "plant_permits_major": 0})
        p["research"] = f"research/{d.name}/report.md"
        p["profile_valid"] = not errs
        rows[st] = p
    for st in sorted(live):
        if st not in rows:
            rows[st] = live_profile(st, rules, fed)
    for st in NAMES:
        if st not in rows:
            rows[st] = {"state": st, "name": NAMES[st], "live": False, "federal": fed.get(st, {}),
                        "readiness": {"tier": None, "expected_grade": "unknown"},
                        "research": None, "note": "no profile yet (research pending)"}
    if errors:
        print("\n".join(errors), file=sys.stderr)
    if check_only:
        return 1 if errors else 0
    out = {"about": "National registry of readiness: one row per state and territory, merged from "
                    "research/<st>/profile.json by scripts/merge_state_profiles.py (shape: research/00-national-brief.md). "
                    "Read by docs/national-approach.md's work plan and, later, by the source tally and /reporting/.",
           "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "states": [rows[k] for k in sorted(rows)]}
    OUT_JSON.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    OUT_MD.write_text(readiness_md(out))
    print(f"wrote {OUT_JSON.relative_to(ROOT)} ({len(rows)} rows, {sum(1 for r in rows.values() if r.get('research'))} with research) "
          f"and {OUT_MD.relative_to(ROOT)}; {len(errors)} validation errors")
    return 0


def readiness_md(out: dict) -> str:
    lines = ["# National readiness (generated)", "",
             f"Generated by `scripts/merge_state_profiles.py` ({out['generated']}) from `research/<st>/profile.json`; "
             "do not edit by hand. The design that reads it is `docs/national-approach.md`. Tiers: A build now "
             "(statewide machine-readable dated feed), B dated but scattered, C federal fallback or annual only, "
             "D nothing public. Counts are from the EPA CSO inventory and ICIS-NPDES permitted features in `data/`.", "",
             "| State | Tier | Expected grade | Public-notice duty | Statewide feed | CSO permits / open outfalls | Plant permits (major) | First feed | Effort |",
             "|---|---|---|---|---|---:|---:|---|---|"]
    order = {"live": 0, "A": 1, "B": 2, "C": 3, "D": 4, "unknown": 5, None: 6}
    for r in sorted(out["states"], key=lambda r: (order.get((r.get("readiness") or {}).get("tier"), 5), r["state"])):
        rd = r.get("readiness") or {}
        law = r.get("law") or {}
        feed = r.get("statewide_feed") or {}
        f = r.get("federal") or {}
        feed_txt = "-" if not r.get("research") else (
            f"{feed.get('precision', '?')}, {feed.get('format', '?')}" if feed.get("exists") else "none")
        lines.append(f"| {r['state']} {r.get('name', '')} | {rd.get('tier') or '?'} | {rd.get('expected_grade') or '?'} | "
                     f"{law.get('public_notice_duty') or '?'} | {feed_txt} | "
                     f"{f.get('cso_permits', 0)} / {f.get('cso_open_outfalls', 0)} | "
                     f"{f.get('plant_permits', 0)} ({f.get('plant_permits_major', 0)}) | "
                     f"{rd.get('first_feed') or '-'} | {rd.get('effort') or '-'} |")
    lines += ["", "## Per state", ""]
    for r in sorted(out["states"], key=lambda r: r["state"]):
        if not r.get("research") or r.get("live"):
            continue
        rd = r.get("readiness") or {}
        law = r.get("law") or {}
        lines.append(f"### {r['state']} {r.get('name', '')}")
        lines.append("")
        lines.append(f"- Law: {law.get('summary') or 'unknown'}")
        lines.append(f"- Readiness: tier {rd.get('tier')}, {rd.get('expected_grade')}; {rd.get('rationale') or ''}")
        bars = r.get("barriers") or []
        if bars:
            lines.append("- Barriers: " + "; ".join(f"{b.get('kind')} ({b.get('fix_level')}): {b.get('what')}" for b in bars))
        if r.get("surprise"):
            lines.append(f"- Surprise: {r['surprise']}")
        qs = r.get("owner_questions") or []
        if qs:
            lines.append("- Owner: " + " | ".join(qs))
        lines.append(f"- Research: `{r['research']}`")
        lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main(check_only="--check" in sys.argv))
