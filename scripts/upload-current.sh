#!/bin/sh
# The small live files the site's Worker serves from R2 (current/<name>): meta, statuses, active list, rules,
# overlays, reaches, points, history and the event index. Run from the repository root after `make export`;
# needs wrangler on the PATH and CLOUDFLARE_API_TOKEN (R2 object read and write on the bucket) with
# CLOUDFLARE_ACCOUNT_ID set. Nothing else on Cloudflare is touched: no Worker deploy, no D1.
set -eu
cd "$(dirname "$0")/.."
python3 -I scripts/export-outfalls.py || echo "outfalls export failed"
for f in outfalls.json meta.json waters.json active.json rules.json overlays.geojson reaches.geojson advisory-points.geojson launches.geojson history.json events-index.json sources.json dischargers.json; do
  if [ -f "out/$f" ]; then
    n=0
    until wrangler r2 object put "dirtywaterwatch-data/current/$f" --file "out/$f" --remote >/dev/null; do
      n=$((n + 1)); [ "$n" -ge 4 ] && { echo "upload failed: current/$f"; break; }
      sleep $((2 ** n))   # back off on 429 and transient errors
    done
    [ "$n" -lt 4 ] && echo "uploaded current/$f"
  fi
done
