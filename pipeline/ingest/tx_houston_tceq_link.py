"""Houston's monthly SSO rows linked to TCEQ's records again, after the generic readers (not a feed).

The Makefile runs this in INGEST_SNAPSHOTS, after `ingest.generic tx-tceq-sso-opendata`: when TCEQ publishes a new
batch, the generic reader writes its records afresh, without the duplicate_of marks ingest/tx_houston_sso_monthly.py
set in the hour's first loop; this puts them back before the status build, so the same overflow is never counted twice
for an hour (review 2026-11-17 P1-9). It reads the two events files and writes them; it fetches nothing.
Run from pipeline/: python -m ingest.tx_houston_tceq_link
"""
from __future__ import annotations

import sys

from common import now_iso
from ingest.tx_houston_sso_monthly import link_only

if __name__ == "__main__":
    sys.exit(link_only(now_iso()))
