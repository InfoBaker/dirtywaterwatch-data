#!/bin/sh
# The data refresh: feeds -> provisional outfalls -> reaches -> status -> charts -> export -> tally -> R2 current/.
# Run from the repository root by the GitHub Actions workflow or by hand. A PAUSE file stops it; a lock directory
# keeps runs from overlapping (a lock older than two hours is treated as stale). The site is built elsewhere from
# the files uploaded to R2. Log: data/build/refresh.log (not in git).
# Exit 1 when the refresh or the export failed, or the export is blocked: the workflow then publishes no export
# (state/out.tar.gz) and saves no state, so a partial run never replaces the last good one.
set -u
cd "$(dirname "$0")/.." || exit 1
export FIXTURES=0   # research fixtures never reach the public files
[ -f data/build/PAUSE ] && { echo "$(date -u +%FT%TZ) paused"; exit 0; }
LOCK=data/build/refresh.lockdir
mkdir -p data/build
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +120 2>/dev/null)" ]; then rmdir "$LOCK"; mkdir "$LOCK" || exit 0; else echo "$(date -u +%FT%TZ) locked"; exit 0; fi
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
sh scripts/timed.sh tally make tally || echo "source tally failed"
# the export's blocklist self-check (pipeline/export/build.py enforce_blocklist) found a private name in out/:
# nothing is uploaded until an export passes it (the mark lists the files)
[ -f data/build/export-blocked.json ] && { echo "export blocked: a blocklisted name is in out/ (data/build/export-blocked.json); not uploading"; exit 1; }
sh scripts/timed.sh upload sh scripts/upload-current.sh || { echo "upload failed: the live files in R2 current/ were not all replaced (the export itself is good)"; echo "::warning::R2 current/ upload failed; see the log"; }
echo "===== $(date -u +%FT%TZ) refresh end"
