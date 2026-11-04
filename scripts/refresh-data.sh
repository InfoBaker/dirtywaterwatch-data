#!/bin/sh
# The data refresh: feeds -> provisional outfalls -> reaches -> status -> charts -> export -> tally -> R2 current/.
# Run from the repository root by the GitHub Actions workflow or by hand. A PAUSE file stops it; a lock directory
# keeps runs from overlapping (a lock older than two hours is treated as stale). The site is built elsewhere from
# the files uploaded to R2. Log: data/build/refresh.log (not in git).
set -u
cd "$(dirname "$0")/.." || exit 1
export FIXTURES=0   # research fixtures never reach the public files
[ -f data/build/PAUSE ] && { echo "$(date -u +%FT%TZ) paused"; exit 0; }
LOCK=data/build/refresh.lockdir
mkdir -p data/build
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +120 2>/dev/null)" ]; then rmdir "$LOCK"; mkdir "$LOCK" || exit 0; else echo "$(date -u +%FT%TZ) locked"; exit 0; fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
echo "===== $(date -u +%FT%TZ) refresh start"
make refresh || echo "make refresh failed"
make tally || echo "source tally failed"
# the export's blocklist self-check (pipeline/export/build.py enforce_blocklist) found a private name in out/:
# nothing is uploaded until an export passes it (the mark lists the files)
[ -f data/build/export-blocked.json ] && { echo "export blocked: a blocklisted name is in out/ (data/build/export-blocked.json); not uploading"; exit 1; }
sh scripts/upload-current.sh || echo "upload failed"
echo "===== $(date -u +%FT%TZ) refresh end"
