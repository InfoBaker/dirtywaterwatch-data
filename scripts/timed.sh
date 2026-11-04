#!/bin/sh
# timed.sh NAME COMMAND [ARG...]: run COMMAND, then print one line "timing: NAME <seconds> s" (with the exit code
# when it is not 0) and, when TIMINGS_FILE is set, append "NAME<TAB><seconds>" to it; exit with COMMAND's code.
# The Makefile times every feed and every refresh stage with it, so the hourly log shows where the time goes;
# scripts/refresh-data.sh prints the longest at the end.
name=$1
shift
start=$(date +%s)
"$@"
rc=$?
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
