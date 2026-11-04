"""Candidate names of private individuals in quoted source text, for the owner to review.

    cd pipeline && .venv/bin/python -m build.name_review
    cd pipeline && .venv/bin/python -m build.name_review --standing      (the hourly refresh, after the export)

Reads data/build/events/*.json and takes each record as the export publishes it (export.build.
public_event: personal keys, emails, phones and staff names already scrubbed). Every string in raw and
in the free-text top-level fields (waterbody_text, outfall_name, volume_text, advice_text, parse_error,
material) is scanned for candidate names (build/redact.py: two or three capitalised words that are not
place, water, organisation, street or header words, or one after Mr / Mrs / Ms / Mx / Dr). Writes

  data/build/name-review.json  {built, totals, by_source, candidates: [{candidate, count, sources,
                               fields, example_event_ids, example, contexts, first_name, auto_redact,
                               verdict}]}. auto_redact: the export removes it (marked as a person by
                               an honorific, a role word, a name cue or an address, or blocklisted).
                               verdict: null for the owner to decide; "allow" / "block" when the name
                               is already on data/name-allowlist.json / data/build/name-blocklist.json.
  data/build/name-review.md    counts by source, the names removed, the candidates to review.

--standing (scripts/refresh-data.sh, right after the export; 2026-11-04 Florida name-review review, point (e)): the same
files, and on standard output counts only, never a name (the Actions log of a public repository is public): the
candidates still to review (not removed by the export, no verdict) and how many of them the previous run's saved
data/build/name-review.json did not hold, with a GitHub ::warning:: line when there are new ones. It never blocks the
publish: the refresh goes on whatever it finds or however it fails, and a failure prints the exception's type only.

The owner acts through the lists: a false positive goes into data/name-allowlist.json, a name to
remove everywhere into data/build/name-blocklist.json; the export applies both. These files are internal
(data/build is never published) because they quote the names.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import redact as R  # noqa: E402
from common import BUILD_DIR, DATA_DIR, EVENTS_DIR, now_iso, write_json  # noqa: E402

OUT_JSON = BUILD_DIR / "name-review.json"
OUT_MD = BUILD_DIR / "name-review.md"
EXAMPLES = 5


def load(events_dir: Path) -> list[tuple[str, dict]]:
    """(source_id, public record) for every record of every events file, fixtures included."""
    from export.build import public_event
    out = []
    for p in sorted(events_dir.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        sid = d.get("source_id") or p.stem
        for r in d.get("records") or []:
            if isinstance(r, dict) and r.get("event_id"):
                out.append((sid, public_event(r)))
    return out


def _key(h: R.Hit, s: str) -> str:
    if len(h.phrase.split()) == 1:                     # "Mr. Sacks": a surname after an honorific
        return re.sub(r"\s+", " ", s[h.cut:h.end])
    return h.phrase


def _snippet(s: str, a: int, b: int, width: int = 70) -> str:
    lo, hi = max(0, a - width), min(len(s), b + width)
    return ("…" if lo else "") + re.sub(r"\s+", " ", s[lo:hi]) + ("…" if hi < len(s) else "")


def review(rows: list[tuple[str, dict]], data_dir: Path = DATA_DIR) -> dict:
    records = [r for _, r in rows]
    lex = R.build_lexicon(records, data_dir)
    marked = R.marked_names(records, lex)
    redactor = R.Redactor(lex, marked)
    blocked = {R._norm(b) for b in lex.block}

    cands = {}
    by_source = defaultdict(Counter)
    for sid, rec in rows:
        src = by_source[sid]
        src["records"] += 1
        changed = False
        for path, s in R.iter_texts(rec):
            src["strings"] += 1
            field = re.sub(r"\[\]", "", path)
            hits = R.find_names(s, lex)
            for h in hits:
                k = _key(h, s)
                c = cands.setdefault(k.lower(), {"forms": Counter(), "count": 0, "sources": Counter(), "fields": Counter(),
                                                 "ids": [], "example": None, "example_ctx": False,
                                                 "contexts": Counter(), "first_name": h.first_name, "removed": 0})
                c["forms"][k] += 1
                c["count"] += 1
                c["sources"][sid] += 1
                c["fields"][field] += 1
                if rec["event_id"] not in c["ids"] and len(c["ids"]) < EXAMPLES:
                    c["ids"].append(rec["event_id"])
                c["contexts"].update(h.contexts)
                if h.auto and not R.allowed(h, R.shadow(s), lex):
                    c["removed"] += 1
                if c["example"] is None or (h.contexts and not c["example_ctx"]):
                    c["example"], c["example_ctx"] = _snippet(s, h.start, h.end), bool(h.contexts)
                src["occurrences"] += 1
            red = redactor.text(s)
            if red != s:
                src["redactions"] += red.count(R.REDACTED) - s.count(R.REDACTED)
                changed = True
        src["records_changed"] += changed

    out = []
    for low, c in cands.items():
        words = R._norm(low)
        auto = words in blocked or (words not in lex.allow and (c["removed"] > 0 or low in marked))
        verdict = "block" if words in blocked else "allow" if words in lex.allow else None
        out.append({"candidate": c["forms"].most_common(1)[0][0], "count": c["count"], "sources": dict(c["sources"].most_common()),
                    "fields": dict(c["fields"].most_common(5)), "example_event_ids": c["ids"], "example": c["example"],
                    "contexts": dict(c["contexts"]), "first_name": c["first_name"], "auto_redact": auto, "verdict": verdict})
    for b in lex.block:                                 # blocklisted names not seen as candidates
        if R._norm(b) not in {R._norm(o["candidate"]) for o in out}:
            out.append({"candidate": b, "count": 0, "sources": {}, "fields": {}, "example_event_ids": [], "example": None,
                        "contexts": {}, "first_name": None, "auto_redact": True, "verdict": "block"})
    out.sort(key=rank, reverse=True)
    for sid in by_source:
        by_source[sid]["candidates"] = sum(1 for o in out if sid in o["sources"])
        by_source[sid]["auto_redacted_candidates"] = sum(1 for o in out if sid in o["sources"] and o["auto_redact"])
    totals = {"records": len(rows), "candidates": len(out), "occurrences": sum(o["count"] for o in out),
              "auto_redacted_candidates": sum(1 for o in out if o["auto_redact"]),
              "redactions": sum(c["redactions"] for c in by_source.values()),
              "records_changed": sum(c["records_changed"] for c in by_source.values()),
              "with_first_name": sum(1 for o in out if o["first_name"] and not o["auto_redact"]),
              "allowlist": len(lex.allow), "blocklist": len(lex.block)}
    return {"built": now_iso(), "totals": totals,
            "by_source": {k: dict(v) for k, v in sorted(by_source.items())}, "candidates": out}


def rank(o: dict):
    """Most person-like first: removed, then any person context, then a first name, then count."""
    ctx = o["contexts"] or {}
    return (o["auto_redact"], sum(ctx.values()) > 0, bool(o["first_name"]), o["count"])


def markdown(rep: dict, top: int = 150) -> str:
    t = rep["totals"]
    lines = [f"# Name review ({rep['built']})", "",
             "Candidate names of private individuals in quoted source text (build/name_review.py). "
             "Internal file: it quotes the names. A false positive goes into `data/name-allowlist.json`, "
             "a name to remove everywhere into `data/build/name-blocklist.json`; the export applies both.", "",
             f"- records scanned: {t['records']:,}",
             f"- candidates: {t['candidates']:,} ({t['occurrences']:,} occurrences); "
             f"{t['with_first_name']:,} of those not removed start with a common first name",
             f"- removed by the export: {t['auto_redacted_candidates']:,} candidates; "
             f"{t['redactions']:,} redactions in {t['records_changed']:,} records",
             f"- allowlist {t['allowlist']}, blocklist {t['blocklist']}", "",
             "## By source", "",
             "| source | records | strings | candidates | occurrences | removed (names) | redactions | records changed |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for sid, c in rep["by_source"].items():
        lines.append(f"| {sid} | {c.get('records', 0):,} | {c.get('strings', 0):,} | {c.get('candidates', 0):,} | "
                     f"{c.get('occurrences', 0):,} | {c.get('auto_redacted_candidates', 0):,} | {c.get('redactions', 0):,} | "
                     f"{c.get('records_changed', 0):,} |")

    def table(rows):
        out = ["| candidate | count | sources | contexts | first name | example |", "|---|---:|---|---|---|---|"]
        for o in rows:
            ex = (o["example"] or "").replace("|", "/")
            out.append(f"| {o['candidate']} | {o['count']} | {', '.join(o['sources'])} | "
                       f"{', '.join(f'{k} {v}' for k, v in o['contexts'].items())} | {'yes' if o['first_name'] else ''} | {ex} |")
        return out

    auto = [o for o in rep["candidates"] if o["auto_redact"]]
    rest = [o for o in rep["candidates"] if not o["auto_redact"] and o["verdict"] is None]
    lines += ["", f"## Removed by the export ({len(auto)})", ""] + table(auto)
    lines += ["", f"## To review (top {min(top, len(rest))} of {len(rest)}, most person-like first)", ""] + table(rest[:top])
    return "\n".join(lines) + "\n"


def to_review(rep: dict | None) -> set[str]:
    """The candidates of a review still to review (not removed by the export, no verdict), normalised."""
    return {R._norm(o["candidate"]) for o in (rep or {}).get("candidates") or []
            if isinstance(o, dict) and o.get("candidate") and not o.get("auto_redact") and o.get("verdict") is None}


def standing_lines(previous: dict | None, rep: dict) -> list[str]:
    """The log lines of a standing review: counts only, and a ::warning:: when candidates to review are new against the
    previous run's saved review (all of them when none was saved)."""
    t, now = rep["totals"], to_review(rep)
    lines = [f"name review: {t['candidates']} candidates in {t['records']} records; {t['auto_redacted_candidates']} "
             f"removed by the export; {len(now)} to review"]
    if previous is None:
        lines[0] += "; no earlier review in the saved state"
        if now:
            lines.append(f"::warning::name review: {len(now)} candidate names to review and no earlier review saved; "
                         f"details in the private state (data/build/name-review.json)")
        return lines
    new = now - to_review(previous)
    lines[0] += f", {len(new)} new since the last run"
    if new:
        lines.append(f"::warning::name review: {len(new)} new candidate names to review since the last run "
                     f"({len(now)} in all); details in the private state (data/build/name-review.json)")
    return lines


def standing(events_dir: Path, out_json: Path = OUT_JSON, out_md: Path = OUT_MD, top: int = 150) -> int:
    """--standing: the review written under data/build, counts printed, never a name; 1 on a failure (the type of the
    exception only: its text could quote a record)."""
    try:
        try:
            previous = json.loads(out_json.read_text())
        except (OSError, ValueError):
            previous = None
        rep = review(load(events_dir))
        write_json(out_json, rep)
        out_md.write_text(markdown(rep, top))
        lines = standing_lines(previous if isinstance(previous, dict) else None, rep)
    except Exception as ex:             # never a traceback in a public log
        print(f"name review failed ({type(ex).__name__}); the publish is not affected")
        print(f"::warning::name review failed ({type(ex).__name__}); the publish is not affected")
        return 1
    print("\n".join(lines))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--events-dir", type=Path, default=EVENTS_DIR)
    ap.add_argument("--top", type=int, default=150, help="candidates to list in the markdown summary")
    ap.add_argument("--standing", action="store_true",
                    help="the hourly refresh's review: counts only on standard output, a ::warning:: for new candidates "
                         "to review against the previous saved review, never a name or a traceback")
    a = ap.parse_args(argv)
    if a.standing:
        return standing(a.events_dir, top=a.top)
    rep = review(load(a.events_dir))
    write_json(OUT_JSON, rep)
    OUT_MD.write_text(markdown(rep, a.top))
    t = rep["totals"]
    print(f"{t['candidates']} candidates ({t['occurrences']} occurrences) in {t['records']} records; "
          f"{t['auto_redacted_candidates']} removed by the export ({t['redactions']} redactions in "
          f"{t['records_changed']} records) -> {OUT_JSON.relative_to(DATA_DIR.parent)}, {OUT_MD.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
