"""EPA BEACON's beach actions linked again to the state feeds' records, after the state feeds (not a feed).

The Makefile runs this in INGEST_SNAPSHOTS, after every feed: ingest/fed_beacon_beach_actions.py runs before most state
beach feeds (the modules run in name order), so a state record that appears or goes in this hour's run is linked here
before the status build, and a BEACON row is never shown twice nor hidden behind a record that has gone. It reads the
saved rows and the events files and writes the BEACON events file again (its header, the last pull's, kept); it
fetches nothing.
Run from pipeline/: python -m ingest.fed_beacon_beach_link
"""
from __future__ import annotations

import sys

from ingest.fed_beacon_beach_actions import relink_only

if __name__ == "__main__":
    sys.exit(relink_only())
