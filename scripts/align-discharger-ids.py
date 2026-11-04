#!/usr/bin/env python3
"""Align the discharger ids on events with the consolidated registry (docs/plan.md section 4).

    pipeline/.venv/bin/python scripts/align-discharger-ids.py [--dry-run]

The ingesters stamp each event with a discharger_id taken from research/<area>/dischargers.json; the
consolidated registry data/dischargers.json merged those files one row per permit and kept a different
id for many operators, so some events point at an id with no registry row. For every discharger_id in
out/events.json that is neither a registry id nor a registry alias this script looks for the registry
row the id belongs to:

  (a) through the research row that defines the id (research/*/dischargers.json): its permit, then its
      exact name, then its name lowercased with punctuation removed, within the same state;
  (b) failing that, through the events themselves: their npdes_permit, then discharger_name (exact,
      then normalised), against registry rows of the same state.

Exactly one row  -> the orphan id is added to that row's `aliases` (existing aliases kept, the row's
                    own id dropped from the list).
No row           -> a new registry row is created from the research row (verified: false, notes naming
                    the research file), using the event id as the row id.
More than one    -> nothing is changed; the case is written to docs/reviews/2026-11-02-discharger-id-review.md.
No row and no research row (the ingesters build an id from the source's own facility name when the
                    research files do not know it, so most ids are of this kind) -> nothing is changed
                    and nothing is invented from the event text (feeds carry junk labels such as test
                    records); the id is listed under "unmatched" in the same review file, with the
                    registry rows whose names look close, as hints only.
In LEFT_ON_PURPOSE -> an id whose text is no organisation (a placeholder, a test label, a street
                    address, a route, a person): never matched and never given a row; the review file
                    lists it under "Left on purpose" with the one-word reason.

The "## Settled ..." sections of the review file are the record of what was decided by hand (ids
aliased, rows created); a rewrite keeps them as they are and regenerates only the counts, "Left on
purpose", "Ambiguous" and "Unmatched".

The registry keeps its format (json.dumps indent=1, ensure_ascii=False, trailing newline) and the
order of its rows; new rows are appended. The export (pipeline/export/build.py) rewrites an event's
alias id to the row id, so the registry, not the events files, is where the mapping lives.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS_FILE = ROOT / "out" / "events.json"
REGISTRY_FILE = ROOT / "data" / "dischargers.json"
REVIEW_FILE = ROOT / "docs" / "reviews" / "2026-11-02-discharger-id-review.md"
PERMIT_RE = re.compile(r"\b([A-Z]{2}\d{7})\b")
STATE_RE = re.compile(r"^([a-z]{2})-")
# Ids whose events carry no operator: id -> a one-word reason. Not matched, not given a row.
LEFT_ON_PURPOSE = {
    "ct-reporting-utility": "placeholder",        # the feed's own label for "utility not named"
    "ct-zzz-test-scotland": "test",               # a test record in the CT DEEP dashboard
    "vt-privately-owned": "placeholder",
    "ny-cicero-to-oak-orchard": "label",          # a route between two places; outfall "Private sewer"
    "md-paramount": "unclear",                    # one word and a street address; no operator can be told
}
ROW_KEYS = ["id", "name", "state", "kind", "npdes_permit", "npdes_permits", "receiving_waters", "water_slugs",
            "outfall_count", "outfalls_source", "notification_channel", "notification_feed_machine_readable",
            "notification_signup_url", "towns", "notes", "verified", "checked", "aliases", "source_areas"]


# ---------------------------------------------------------------- matching

def permits_of(*texts) -> list[str]:
    """NPDES permit numbers in the texts, upper-cased, in order, without repeats."""
    out: list[str] = []
    for t in texts:
        for p in PERMIT_RE.findall(str(t or "").upper()):
            if p not in out:
                out.append(p)
    return out


def norm_name(s) -> str:
    """Lowercased, punctuation turned to spaces, spaces collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(s or "").lower())).strip()


def row_permits(row: dict) -> list[str]:
    return permits_of(row.get("npdes_permit"), *(row.get("npdes_permits") or []))


def row_names(row: dict) -> list[str]:
    return [n for n in [row.get("name"), *(row.get("alt_names") or [])] if isinstance(n, str) and n.strip()]


def event_states(ev: dict, fallback: str | None = None) -> set[str]:
    st = str(ev.get("state") or "").upper()
    if len(st) == 2:
        return {st}
    m = re.match(r"([A-Z]{2})\d", str(ev.get("npdes_permit") or "").upper())
    if m:
        return {m.group(1)}
    m = STATE_RE.match(str(ev.get("discharger_id") or ""))
    if m:
        return {m.group(1).upper()}
    return {fallback.upper()} if fallback else set()


def find_rows(registry: list[dict], states: set[str], permits=(), names=()) -> tuple[list[dict], str]:
    """(rows, how): the registry rows of the states that match by permit, else by exact name, else by
    normalised name; the first stage with any match decides (more than one row = ambiguous). A row
    that matches by name but holds permits of its own, none of them the given permits, is not a match
    (the same name for another permittee)."""
    rows = [r for r in registry if not states or str(r.get("state") or "").upper() in states]
    permits = [p for p in permits if p]
    if permits:
        hit = [r for r in rows if set(permits) & set(row_permits(r))]
        if hit:
            return hit, "permit"

    def agree(r: dict) -> bool:
        return not (permits and row_permits(r) and not set(permits) & set(row_permits(r)))
    names = [n for n in names if isinstance(n, str) and n.strip()]
    if names:
        want = {n.strip() for n in names}
        hit = [r for r in rows if agree(r) and want & {n.strip() for n in row_names(r)}]
        if hit:
            return hit, "name"
        want = {norm_name(n) for n in names} - {""}
        hit = [r for r in rows if agree(r) and want & {norm_name(n) for n in row_names(r)}]
        if hit:
            return hit, "normalised name"
    return [], ""


NAME_STOP = {"city", "town", "of", "the", "village", "department", "public", "works", "dpw", "wpcf", "wwtp", "wpca",
             "sewer", "sewers", "district", "authority", "wwtf", "pcf", "sd", "c", "t", "v", "poss", "co", "and", "water",
             "pollution", "control", "facility", "plant", "treatment", "stp", "potw", "wpc"}


def name_tokens(s) -> set[str]:
    return {t for t in norm_name(s).split() if t not in NAME_STOP}


def possible_rows(registry: list[dict], states: set[str], names) -> list[str]:
    """Hints only: ids of registry rows of the states whose name or id holds every distinctive word of
    one of the names (not applied: "Groton, City of" also fits the Town of Groton's row)."""
    out = []
    for r in registry:
        if states and str(r.get("state") or "").upper() not in states:
            continue
        have = set().union(*(name_tokens(n) for n in row_names(r)), name_tokens(str(r["id"]).split("-", 1)[-1]))
        if any(w and w <= have for w in (name_tokens(n) for n in names)):
            out.append(r["id"])
    return out


def load_research(root: Path = ROOT) -> dict[str, dict]:
    """id -> {"row": research row, "file": relative path, "area": directory}; the first definition wins."""
    out: dict[str, dict] = {}
    for p in sorted(root.glob("research/*/dischargers.json")):
        try:
            rows = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and r.get("id") and r["id"] not in out:
                out[r["id"]] = {"row": r, "file": str(p.relative_to(root)), "area": p.parent.name}
    return out


def known_ids(registry: list[dict]) -> set[str]:
    ids = {r["id"] for r in registry}
    for r in registry:
        ids.update(a for a in r.get("aliases") or [] if isinstance(a, str))
    return ids


def new_row(orphan: str, research: dict, today: str) -> dict:
    """A registry row (the shape of the others in data/dischargers.json) from a research row."""
    r, permits = research["row"], row_permits(research["row"])
    note = f"Added from {research['file']} (research id {orphan}); not merged into another row; not yet verified."
    if r.get("notes"):
        note = f"{r['notes']} {note}"
    src = {"id": orphan, "npdes_permit": permits[0] if permits else None, "npdes_permits": permits,
           "notification_signup_url": r.get("notification_signup_url"), "notes": note, "verified": False,
           "checked": r.get("checked") or today, "aliases": [], "source_areas": [research["area"]]}
    row = {k: src[k] if k in src else r.get(k) for k in ROW_KEYS}
    if r.get("npdes_permit") and not permits:
        row["permit_note"] = r["npdes_permit"]
    for k, v in r.items():                      # keys the registry rows carry beyond ROW_KEYS (short_name ...)
        if k not in row and k not in ("aliases",):
            row[k] = v
    return row


def align(events: list[dict], registry: list[dict], research: dict[str, dict], today: str = "2026-11-02") -> dict:
    """The decisions, without changing anything: {"aliased": [...], "created": [...], "ambiguous": [...],
    "already": n}. Each entry names the orphan id, its event count and how it was decided."""
    known = known_ids(registry)
    by_id: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        did = e.get("discharger_id")
        if did and did not in known:
            by_id[did].append(e)
    row_ids = {r["id"] for r in registry}
    plan = {"aliased": [], "created": [], "ambiguous": [], "unmatched": [], "left": [],
            "already": sum(1 for e in events if e.get("discharger_id") in known - row_ids)}
    for orphan in sorted(by_id, key=lambda i: (-len(by_id[i]), i)):
        evs = by_id[orphan]
        res = research.get(orphan)
        rr = res["row"] if res else {}
        ev_states = set().union(*(event_states(e) for e in evs))
        names = Counter(e.get("discharger_name") for e in evs if e.get("discharger_name"))
        ev_permits = permits_of(*(e.get("npdes_permit") for e in evs))
        found, how, via = [], "", ""
        if orphan in LEFT_ON_PURPOSE:
            plan["left"].append({"orphan": orphan, "events": len(evs), "state": ",".join(sorted(ev_states)) or None,
                                 "names": [n for n, _ in names.most_common(3)], "permits": ev_permits,
                                 "reason": LEFT_ON_PURPOSE[orphan]})
            continue
        if res:
            st = {str(rr["state"]).upper()} if rr.get("state") else ev_states
            found, how = find_rows(registry, st, row_permits(rr), [rr.get("name")])
            via = f"research row {res['file']}, {how}"
        if not found:
            found, how = find_rows(registry, ev_states, ev_permits, list(names))
            via = f"events, {how}"
        info = {"orphan": orphan, "events": len(evs), "state": ",".join(sorted(ev_states)) or None,
                "names": [n for n, _ in names.most_common(3)], "permits": ev_permits,
                "research_file": res["file"] if res else None, "research_name": rr.get("name"),
                "research_permit": rr.get("npdes_permit")}
        if len(found) == 1:
            plan["aliased"].append({**info, "row": found[0]["id"], "row_name": found[0].get("name"), "via": via})
        elif len(found) > 1:
            plan["ambiguous"].append({**info, "candidates": [(r["id"], r.get("name"), r.get("npdes_permit")) for r in found],
                                      "via": via})
        elif res:
            plan["created"].append({**info, "row": new_row(orphan, res, today)})
        else:
            plan["unmatched"].append({**info, "hints": possible_rows(registry, ev_states, list(names)),
                                      "via": "no research row and no registry match"})
    return plan


def apply(plan: dict, registry: list[dict]) -> list[dict]:
    """A new registry list: aliases added (a row's own id dropped from its aliases), created rows appended."""
    by_id = {r["id"]: i for i, r in enumerate(registry)}
    out = [dict(r) for r in registry]
    add: dict[str, list[str]] = defaultdict(list)
    for a in plan["aliased"]:
        add[a["row"]].append(a["orphan"])
    for rid, new in add.items():
        row = out[by_id[rid]]
        old = [x for x in row.get("aliases") or [] if x != rid]
        row["aliases"] = old + [x for x in new if x not in old and x != rid]
    return out + [dict(c["row"]) for c in plan["created"]]


# ---------------------------------------------------------------- output

def dump(rows: list[dict]) -> str:
    return json.dumps(rows, indent=1, ensure_ascii=False) + "\n"


def settled_sections(text: str) -> str:
    """The hand-kept "## Settled ..." sections of an existing review file: from the first such heading up
    to the first heading this script writes itself (Left on purpose, Ambiguous, Unmatched)."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## Settled")), None)
    if start is None:
        return ""
    own = ("## Left on purpose", "## Ambiguous", "## Unmatched")
    end = next((i for i in range(start + 1, len(lines)) if lines[i] in own), len(lines))
    return "\n".join(lines[start:end]).strip()


def review_text(plan: dict, today: str, settled: str = "") -> str:
    amb, unm, left = plan["ambiguous"], plan["unmatched"], plan.get("left") or []
    lines = [f"# Discharger id review ({today})", "",
             "Written by `scripts/align-discharger-ids.py`. Discharger ids on events that have no row in",
             "`data/dischargers.json` (neither as a row id nor as an alias) and that the script did not place. Nothing",
             "was changed for them. To settle a case, add the id to the `aliases` of the right row (or add a row), then",
             "run the script again; it rewrites this file from what is still open.", "",
             f"- Ambiguous (more than one registry row fits): {len(amb)} ids, {sum(a['events'] for a in amb)} events.",
             f"- Unmatched (no research row, no registry row): {len(unm)} ids, {sum(a['events'] for a in unm)} events.",
             f"- Left on purpose (no operator in the text): {len(left)} ids, {sum(a['events'] for a in left)} events.", ""]
    if settled:
        lines += [settled, ""]
    if left:
        lines += ["## Left on purpose", "",
                  "The text is not an organisation, so no row is made and no alias added. The reason is one word: "
                  "placeholder, test, label, unclear, or person (a private individual; the name is not copied "
                  "here, only the feed's id).", "",
                  "| id | events | state | name in the events | reason |", "|---|---:|---|---|---|"]
        for a in left:
            nm = "withheld" if a["reason"] == "person" else "; ".join(a["names"]).replace("|", "/")
            lines.append(f"| `{a['orphan']}` | {a['events']} | {a['state'] or ''} | {nm} | {a['reason']} |")
        lines.append("")
    lines += ["## Ambiguous", ""]
    if not amb:
        lines += ["None.", ""]
    for a in amb:
        lines += [f"### `{a['orphan']}` ({a['events']} events)", "",
                  f"- State {a['state'] or 'unknown'}; event operator names: {'; '.join(a['names']) or 'none'}; "
                  f"event permits: {', '.join(a['permits']) or 'none'}",
                  f"- Research row: {a['research_file'] or 'none'}"
                  + (f" ({a['research_name']}; permit {a['research_permit']})" if a["research_file"] else ""),
                  f"- Matched by: {a['via']}", "- Candidate rows:"]
        lines += [f"  - `{i}`: {n} (permit {p})" for i, n, p in a["candidates"]]
        lines.append("")
    lines += ["## Unmatched", "",
              "The ingesters build an id from the source's own facility name when the research files do not know the",
              "operator, so these ids are in no research file. The event text is not enough to make a registry row",
              "(some feeds carry test records and placeholder labels), so none was created. \"Close rows\" are",
              "registry rows of the same state whose name holds the same distinctive words: hints, not matches.", ""]
    if not unm:
        lines += ["None.", ""]
    else:
        lines += ["| id | events | state | operator name in the events | permits in the events | close rows |",
                  "|---|---:|---|---|---|---|"]
    for a in unm:
        cell = lambda xs: ", ".join(f"`{x}`" for x in xs) if xs else ""      # noqa: E731
        lines.append(f"| `{a['orphan']}` | {a['events']} | {a['state'] or ''} | {'; '.join(a['names']).replace('|', '/')} | "
                     f"{', '.join(a['permits'])} | {cell(a['hints'])} |")
    return "\n".join(lines).rstrip() + "\n"


CATEGORIES = ("aliased", "created", "ambiguous", "unmatched")


def summary(plan: dict) -> str:
    out = [f"{'result':<12}{'ids':>6}{'events':>9}", "-" * 27]
    for name in CATEGORIES:
        out.append(f"{name:<12}{len(plan[name]):>6}{sum(i['events'] for i in plan[name]):>9}")
    left = plan.get("left") or []
    if left:
        out.append(f"{'left':<12}{len(left):>6}{sum(i['events'] for i in left):>9}")
    out.append(f"{'total':<12}{sum(len(plan[n]) for n in CATEGORIES) + len(left):>6}"
               f"{sum(x['events'] for n in CATEGORIES for x in plan[n]) + sum(x['events'] for x in left):>9}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the table and the decisions; write nothing")
    ap.add_argument("--verbose", "-v", action="store_true", help="print one line per decision")
    ap.add_argument("--today", default="2026-11-02")
    a = ap.parse_args(argv)
    doc = json.loads(EVENTS_FILE.read_text())
    events = doc["events"] if isinstance(doc, dict) else doc
    registry = json.loads(REGISTRY_FILE.read_text())
    plan = align(events, registry, load_research(), a.today)
    if a.verbose:
        for k in CATEGORIES:
            for x in plan[k]:
                tgt = x["row"]["id"] if k == "created" else x.get("row", "-")
                print(f"{k:<9} {x['orphan']:<46} {x['events']:>5} -> {tgt}   [{x['via']}]")
    print(summary(plan))
    if plan["already"]:
        print(f"({plan['already']} more events already carry an alias id; the export rewrites them)")
    if a.dry_run:
        return 0
    if plan["aliased"] or plan["created"]:
        REGISTRY_FILE.write_text(dump(apply(plan, registry)))
        print(f"wrote {REGISTRY_FILE.relative_to(ROOT)}")
    if plan["ambiguous"] or plan["unmatched"] or plan["left"] or REVIEW_FILE.exists():
        REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        old = REVIEW_FILE.read_text() if REVIEW_FILE.exists() else ""
        REVIEW_FILE.write_text(review_text(plan, a.today, settled_sections(old)))
        print(f"wrote {REVIEW_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
