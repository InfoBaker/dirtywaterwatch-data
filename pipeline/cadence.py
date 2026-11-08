"""How often the hourly refresh runs a feed: every hour for a live state, once a day for a state not yet live.

    python -m cadence due ingest.al_adem_sso generic.tx-glo-beach-watch ...   the names due this run, one line,
                                                                            space-separated; a feed of a state not
                                                                            yet live carries ":daily"
    python -m cadence ran ingest.al_adem_sso                                 that daily feed ran well now

The rule (docs/refresh-time-brief-2026-11-07.md; data/rules.json `live_states` is the only switch): a feed belongs to
a state when its name starts with a two-letter state code and an underscore or hyphen (`al_adem_sso`,
`tx-tceq-sso-opendata`); a feed of no one state (`echo_sewer_overflow_events`, `notification_pages`, `nyc_...`) or of a
live state runs every hour, as before. A feed of a state not in live_states is not exported (export.build
live_jurisdiction_events) nor coloured (build.status --live-only), so it runs on a daily pass: when its last good run,
kept in data/build/feed-cadence.json (saved with the state), is NOT_LIVE_EVERY_H hours old or more, or has never been.
Its history stays in the saved state and the ingesters backfill their windows, so the records are there, at most a
day old, the hour the state goes live, and from that hour the feed runs hourly with no other edit. FEEDS_ALL=1 in the
environment runs every feed (a dispatch, a hand run). A daily feed that fails is tried again the next hour.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from common import BUILD_DIR, DATA_DIR, rules_live_states

CADENCE_FILE = BUILD_DIR / "feed-cadence.json"
NOT_LIVE_EVERY_H = 24
SLACK = timedelta(minutes=30)   # an hourly run starting a few minutes earlier than yesterday's still counts as a day

US_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK "
    "OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR VI GU AS MP".split())


def feed_state(name: str) -> str | None:
    """The state a feed belongs to by its name ("ingest.al_adem_sso", "generic.tx-glo-beach-watch", or bare), else
    None (a national or multi-state feed, or a name with no state prefix)."""
    base = name.split(".", 1)[1] if "." in name else name
    if len(base) > 3 and base[2] in "_-":
        code = base[:2].upper()
        if code in US_CODES:
            return code
    return None


def read_stamps(path: Path = CADENCE_FILE) -> dict:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _parse(s) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def due(names: list[str], live: set[str] | None, stamps: dict, now: datetime, every_h: float = NOT_LIVE_EVERY_H,
        run_all: bool = False) -> list[str]:
    """The names to run now, in their order; a not-live feed's name gets ":daily". live None (no live_states list):
    every feed is hourly."""
    out = []
    for n in names:
        st = feed_state(n)
        if live is None or st is None or st in live:
            out.append(n)
            continue
        last = _parse(stamps.get(n))
        if run_all or last is None or now - last >= timedelta(hours=every_h) - SLACK or last > now + SLACK:
            out.append(f"{n}:daily")
    return out


def load_live(data_dir: Path = DATA_DIR) -> set[str] | None:
    try:
        return rules_live_states(json.loads((data_dir / "rules.json").read_text()))
    except (OSError, ValueError):
        return None     # no readable rules: every feed hourly (never skip a feed by accident)


def mark_ran(name: str, now: datetime, path: Path = CADENCE_FILE) -> None:
    d = read_stamps(path)
    d[name] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(d.items())), indent=1) + "\n")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("due", "ran"):
        print(__doc__, file=sys.stderr)
        return 2
    now = datetime.now(UTC)
    if argv[0] == "ran":
        for n in argv[1:]:
            mark_ran(n, now)
        return 0
    names = argv[1:]
    every = float(os.environ.get("NOT_LIVE_EVERY_H") or NOT_LIVE_EVERY_H)
    run_all = os.environ.get("FEEDS_ALL", "") in ("1", "yes", "true")
    out = due(names, load_live(), read_stamps(), now, every, run_all)
    print(" ".join(out))
    chosen = {o.split(":")[0] for o in out}
    skipped = [n for n in names if n not in chosen]
    if skipped:
        print(f"cadence: {len(skipped)} feed(s) of states not yet live wait for their daily pass: {' '.join(skipped)}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
