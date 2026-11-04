#!/bin/sh
# The small live files the site's Worker serves from R2 (current/<name>): meta, statuses, active list, rules,
# overlays, reaches, points, history and the event index. Run from the repository root after `make export`;
# needs wrangler on the PATH and CLOUDFLARE_API_TOKEN (R2 object read and write on the bucket) with
# CLOUDFLARE_ACCOUNT_ID set. Nothing else on Cloudflare is touched: no Worker deploy, no D1.
# The reaches per state (out/reaches/<st>.geojson, pipeline/export/build.py write_reach_state_files) go up after the
# national files: only the files out/reaches/index.json lists, each named reaches/<two lowercase letters>.geojson,
# at most REACH_STATE_MAX of them, then the index last, so the index never names a file that is not in R2. A bad
# or missing index puts no state file; a state file that fails to upload keeps the old index in place.
set -eu
cd "$(dirname "$0")/.."
REACH_STATE_MAX=64
put() {   # put <path under out/>: every file goes through this one check (present) and the same retries
  f="$1"
  [ -f "out/$f" ] || { echo "not in out/: $f"; return 1; }
  n=0; wait_s=1
  until wrangler r2 object put "dirtywaterwatch-data/current/$f" --file "out/$f" --remote >/dev/null; do
    n=$((n + 1)); [ "$n" -ge 4 ] && { echo "upload failed: current/$f"; return 1; }
    wait_s=$((wait_s * 2)); sleep "$wait_s"   # back off on 429 and transient errors: 2, 4, 8 s (POSIX sh has no **)
  done
  echo "uploaded current/$f"
}
python3 -I scripts/export-outfalls.py || echo "outfalls export failed"
for f in outfalls.json meta.json waters.json active.json rules.json overlays.geojson reaches.geojson advisory-points.geojson launches.geojson history.json events-index.json sources.json dischargers.json; do
  if [ -f "out/$f" ]; then
    put "$f" || true
  fi
done
# the reaches per state: the explicit list is the index's, checked and bounded before anything is put
if [ -f out/reaches/index.json ]; then
  if states=$(python3 -I - "$REACH_STATE_MAX" <<'PY'
import json, re, sys
cap = int(sys.argv[1])
try:
    with open("out/reaches/index.json", encoding="utf-8") as fh:
        files = [e["file"] for e in json.load(fh)["files"]]
except (OSError, ValueError, KeyError, TypeError) as e:
    sys.exit(f"out/reaches/index.json unreadable ({type(e).__name__})")
bad = [f for f in files if not (isinstance(f, str) and re.fullmatch(r"reaches/[a-z]{2}\.geojson", f))]
if bad:
    sys.exit(f"out/reaches/index.json names {len(bad)} file(s) outside reaches/<st>.geojson")
if len(files) > cap or len(set(files)) != len(files):
    sys.exit(f"out/reaches/index.json lists {len(files)} files (at most {cap}, each once)")
print(" ".join(files))
PY
  ); then
    failed=""
    for f in $states; do
      put "$f" || failed="$failed $f"
    done
    if [ -z "$failed" ]; then
      put reaches/index.json || true
    else
      echo "reaches per state: not uploaded:$failed; current/reaches/index.json left as it was"
    fi
  else
    echo "reaches per state: nothing uploaded (the index did not pass the check)"
  fi
fi
