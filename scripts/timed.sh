#!/bin/sh
# timed.sh [--cap SECONDS] NAME COMMAND [ARG...]: run COMMAND, then print one line "timing: NAME <seconds> s" (with the
# exit code when it is not 0) and, when TIMINGS_FILE is set, append "NAME<TAB><seconds>" to it; exit with COMMAND's code.
# The Makefile times every feed and every refresh stage with it, so the hourly log shows where the time goes;
# scripts/refresh-data.sh prints the longest at the end.
#
# --cap SECONDS (the Makefile's ingest loops: FEED_CAP_S, 600 by default): a command still running after SECONDS is
# stopped (TERM, then KILL 10 s later), logged "timing: NAME SECONDS s (exit 124, stopped at the cap)" and exits 124,
# so the loop counts the feed as failed and the refresh goes on (run 42440292355: EPA's DMR service did not answer and
# ingest.echo_cso_dmr_monthly held the ingest stage for 3,219 s, past the workflow's 100 minutes). One feed's own cap:
# FEED_CAP_<NAME with every character other than a letter or digit as _> in the environment, e.g.
# FEED_CAP_ingest_fl_doh_beaches=900; 0 is no cap. No cap either when the command carries --backfill (a one-time
# history load runs as long as it needs). A stopped feed loses nothing it kept before: every ingester writes its events
# file once, through common.write_events -> write_json (a temporary file, then an atomic rename), so a stop leaves the
# previous run's file whole, or this run's whole.
cap=0
if [ "${1:-}" = "--cap" ]; then
  cap=$2
  shift 2
fi
name=$1
shift
over=$(printf '%s' "FEED_CAP_$name" | tr -c 'A-Za-z0-9_' '_')
eval "own=\${$over:-}"
[ -n "$own" ] && cap=$own
for a in "$@"; do [ "$a" = "--backfill" ] && cap=0; done
case "$cap" in ''|*[!0-9]*) cap=0 ;; esac
start=$(date +%s)
if [ "$cap" -gt 0 ]; then
  mark=$(mktemp "${TMPDIR:-/tmp}/timed-cap.XXXXXX")
  rm -f "$mark"
  "$@" &
  pid=$!
  (
    trap 'kill "$s" 2>/dev/null; exit 0' TERM
    sleep "$cap" & s=$!
    wait "$s"
    if kill -0 "$pid" 2>/dev/null; then
      : > "$mark"
      kids=$(pgrep -P "$pid" 2>/dev/null)   # its own children too (a shell's, a pdftotext): the feed first
      kill -TERM "$pid" 2>/dev/null
      [ -n "$kids" ] && kill -TERM $kids 2>/dev/null
      sleep 10 & s=$!
      wait "$s"
      kill -KILL "$pid" 2>/dev/null
    fi
  ) &
  dog=$!
  wait "$pid"
  rc=$?
  kill -TERM "$dog" 2>/dev/null
  wait "$dog" 2>/dev/null
  if [ -f "$mark" ]; then
    rm -f "$mark"
    echo "timing: $name $cap s (exit 124, stopped at the cap)"
    if [ -n "${TIMINGS_FILE:-}" ]; then
      printf '%s\t%s\n' "$name" "$cap" >> "$TIMINGS_FILE" 2>/dev/null || true
    fi
    exit 124
  fi
else
  "$@"
  rc=$?
fi
secs=$(( $(date +%s) - start ))
if [ "$rc" -eq 0 ]; then
  echo "timing: $name $secs s"
else
  echo "timing: $name $secs s (exit $rc)"
fi
if [ -n "${TIMINGS_FILE:-}" ]; then
  printf '%s\t%s\n' "$name" "$secs" >> "$TIMINGS_FILE" 2>/dev/null || true
fi
exit "$rc"
