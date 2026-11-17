#!/bin/sh
# Put the redacting guard in front of wrangler for the rest of a GitHub Actions job: run right after
# `npm install -g wrangler@4`, in the same step (`npm install -g wrangler@4 && sh scripts/wrangler-guard.sh`).
# It writes a `wrangler` that runs the real one through scripts/wrangler_redact.py (no e-mail address or Cloudflare
# account name in the public log; exit code and --json/--pipe data unchanged) into a folder named wrangler-guard,
# and adds that folder to the front of the job's PATH ($GITHUB_PATH; later steps). Every later bare `wrangler`, in a
# workflow step, a script or a Python subprocess, goes through it. Outside Actions, set GITHUB_PATH to a scratch file
# and WRANGLER_GUARD_DIR to where the shim goes.
set -eu
repo="$(cd "$(dirname "$0")/.." && pwd)"
real="$(command -v wrangler || true)"
case "$real" in
  "") echo "::error::wrangler-guard: wrangler is not installed"; exit 1 ;;
  *wrangler-guard*) echo "wrangler-guard: already in place"; exit 0 ;;
esac
dir="${WRANGLER_GUARD_DIR:-${RUNNER_TEMP:?RUNNER_TEMP or WRANGLER_GUARD_DIR is needed}/wrangler-guard}"
case "$dir" in *wrangler-guard*) ;; *) echo "::error::wrangler-guard: the folder must be named wrangler-guard"; exit 1 ;; esac
case "$real$repo" in *"'"*) echo "::error::wrangler-guard: a quote in a path"; exit 1 ;; esac
mkdir -p "$dir"
cat > "$dir/wrangler" <<EOF
#!/bin/sh
WRANGLER_REAL='$real' exec python3 -I '$repo/scripts/wrangler_redact.py' "\$@"
EOF
chmod 755 "$dir/wrangler"
echo "$dir" >> "${GITHUB_PATH:?GITHUB_PATH is needed}"
echo "wrangler-guard: wrangler's output is filtered from the next step on"
