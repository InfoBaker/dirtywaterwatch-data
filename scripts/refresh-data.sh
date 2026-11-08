#!/bin/sh
# The data refresh: feeds -> provisional outfalls -> reaches -> status -> charts -> export -> tally -> R2 current/.
# Run from the repository root by the GitHub Actions workflow or by hand. A PAUSE file stops it (skipped=1); a lock directory
# keeps runs from overlapping (a lock older than two hours is treated as stale). The site is built elsewhere from
# the files uploaded to R2. Log: data/build/refresh.log (not in git).
# Exit 1 when the refresh or the export failed, or the export is blocked: the workflow then publishes no export
# (state/out.tar.gz) and saves no state, so a partial run never replaces the last good one.
set -u
cd "$(dirname "$0")/.." || exit 1
export FIXTURES=0   # research fixtures never reach the public files
# a run that stops at once (PAUSE, or another run's lock) did nothing: under GitHub Actions it says skipped=1, so the
# workflow publishes and saves nothing after it (SOL wave1 P2-9; the workflow checks R2 state/PAUSE before this)
skipped() { echo "$(date -u +%FT%TZ) $1"; [ -n "${GITHUB_OUTPUT:-}" ] && echo "skipped=1" >> "$GITHUB_OUTPUT"; exit 0; }
[ -f data/build/PAUSE ] && skipped paused
LOCK=data/build/refresh.lockdir
mkdir -p data/build
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +120 2>/dev/null)" ]; then rmdir "$LOCK"; mkdir "$LOCK" || skipped locked; else skipped locked; fi
fi
# every feed and stage prints "timing: NAME SECONDS s" (scripts/timed.sh); the longest are listed again at the end
TIMINGS_FILE="$(pwd)/data/build/refresh-timings.tsv"
export TIMINGS_FILE
: > "$TIMINGS_FILE"
summary() {
  [ -s "$TIMINGS_FILE" ] || return 0
  echo "timing summary, longest first (seconds; a stage includes the feeds and steps listed under it):"
  sort -t "$(printf '\t')" -k2,2nr "$TIMINGS_FILE" | head -n 20 | awk -F '\t' '{ printf "  %6d s  %s\n", $2, $1 }'
}
trap 'summary; rmdir "$LOCK" 2>/dev/null' EXIT
echo "===== $(date -u +%FT%TZ) refresh start"
make refresh || { echo "make refresh failed: nothing uploaded; the workflow publishes no export and saves no state"; exit 1; }
# the standing name review (build/name_review.py --standing) reads the events as the export publishes them: its details
# go to data/build only (saved with the private state, never to git or out/), this log gets counts only (Actions logs
# are public) and a ::warning:: when new candidate names to review appear; it never blocks the publish, and its
# failure leaves this script's exit status as it is
NR_PY="$(pwd)/pipeline/.venv/bin/python"
[ -x "$NR_PY" ] || NR_PY=python3
# on a daily pass (pipeline/cadence.py daily: exit 3 when it ran well in the last day; any other answer runs it): it
# rescans every record, about 3.5 minutes, for a review the owner reads, and nothing published or later reads it
nr_due=0; (cd pipeline && exec "$NR_PY" -m cadence daily name-review) || nr_due=$?
if [ "$nr_due" = 3 ]; then
  echo "name review: on its daily pass, not due this run (data/build/feed-cadence.json)"
elif sh scripts/timed.sh name-review sh -c 'cd pipeline && exec "$0" -m build.name_review --standing' "$NR_PY"; then
  (cd pipeline && exec "$NR_PY" -m cadence ran name-review) || true
else
  echo "name review failed: not blocking"
fi
sh scripts/timed.sh tally make tally || echo "source tally failed"
# the export's blocklist self-check (pipeline/export/build.py enforce_blocklist) found a private name in out/:
# nothing is uploaded until an export passes it (the mark lists the files)
[ -f data/build/export-blocked.json ] && { echo "export blocked: a blocklisted name is in out/ (data/build/export-blocked.json); not uploading"; exit 1; }
sh scripts/timed.sh upload sh scripts/upload-current.sh || { echo "upload failed: the live files in R2 current/ were not all replaced (the export itself is good)"; echo "::warning::R2 current/ upload failed; see the log"; }
echo "===== $(date -u +%FT%TZ) refresh end"
