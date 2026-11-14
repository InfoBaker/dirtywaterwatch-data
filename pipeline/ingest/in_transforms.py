"""Indiana hooks for the generic ingesters (docs/generic-ingesters.md).

IDEM's cyanobacteria layer (data/sources/in-idem-cyanobacteria.yaml): every sample IDEM's beach project took at
Indiana state-park and reservoir beaches since 2010, each with the advisory level IDEM gave that sample
(advisory_level: 'Advisory', 'Caution', 'No Swimming', 'Low Risk', and at Fort Harrison's dog-park lakes 'Dog Park
Closed', 'Dog Park Caution', 'Dog Park Low Risk'), the toxin results and the beach's point. The levels are IDEM's own
statements and are quoted, never re-derived from the toxin numbers.

in_cyano_record (transform): a sample whose level is one of ADVISORY_LEVELS is IDEM's bloom advisory for that beach as
of that sample: event_type hab_advisory (the bloom category), status unknown, sampled_at the sample date (a date-only
field, read as the date it is), started_at and ended_at empty, advice_text IDEM's level in IDEM's words. A 'Low Risk'
sample is not an advisory and not a record (raw._sample_only: grey, 'no report', never clean); it is kept through the
run only to show that a later sample changed the level. raw.time_zone is the beach's county's zone (zones.indiana_zone:
every sampled beach is in Eastern time today, but the rule is the point's). The beach's point is rounded to three
decimals; a bloom on a named lake is placed on that lake only (named_water_only).

in_cyano_sequence (after_history): the accuracy-first rule of the Nebraska layer (ingest.ne_transforms,
ne_beachwatch_sequence): a sample date is not an advisory's issue or lift date. Historical samples keep sampled_at and
no advisory timestamps, so they sit in their sample year's history without an invented red interval. Only the latest
sample at a station, when it is at an advisory level and at most RECENT_SAMPLE_DAYS old when first observed, opens an
observed advisory interval: its start is that poll (time_precision poll), not the sample date. A later sample at the
station, or a corrected level, ends the observed interval at the poll that first shows the change (raw.ended_at_precision
poll: an upper bound, not IDEM's lift time). The sample-only rows are then removed from the run's records.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import zones
from ingest.generic import fieldmap as F

ADVISORY_LEVELS = {"advisory", "caution", "no swimming", "dog park closed", "dog park caution"}
LOW_LEVELS = {"low risk", "dog park low risk"}
RECENT_SAMPLE_DAYS = 14
CLOCK_VERSION = 1
CLOCK_NOTE = ("IDEM gives the sample date and the advisory level for that sample, not an advisory's issue or lift "
              "date. Any advisory times here are the polls that first showed a recent advisory-level sample or its "
              "change, not times published by IDEM.")
LEVEL_BASIS = ("IDEM's advisory level for the sample, as the layer gives it; the toxin results are kept with it and "
               "not re-read into a level")


def _level(row: dict) -> str:
    return F.clean(row.get("advisory_level"))


@F.hook
def in_cyano_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    level = _level(row)
    station = F.clean(row.get("location_id")).upper() or F.clean(row.get("beach_name"))
    notes["_station"] = station
    notes["_level"] = level
    sample = rec.get("started_at")
    if sample:
        sample = str(sample)[:10]
    notes["_sample_date"] = sample
    tz = zones.indiana_zone(lat=rec.get("lat"), lon=rec.get("lon"))
    notes["time_zone"] = tz
    notes["_placement"] = "named_water_only"
    toxins = {k: row.get(k) for k in ("microcystin", "anatoxin_a", "cylindrospermopsin", "saxitoxin")
              if isinstance(row.get(k), (int, float)) and row.get(k) >= 0}
    if toxins:
        notes["_toxins_ug_per_l"] = toxins
    if level.lower() in ADVISORY_LEVELS:
        rec["sampled_at"] = sample
        rec.update(started_at=None, ended_at=None, time_precision=None, source_updated_at=None,
                   event_type="hab_advisory", status="unknown")
        beach = F.clean(row.get("beach_name")) or F.clean(row.get("waterbody"))
        rec["advice_text"] = (f"IDEM's advisory level for {beach}: {level} (sample dated {sample})")
        notes["_level_basis"] = LEVEL_BASIS
    else:
        notes["_sample_only"] = True
        if level.lower() not in LOW_LEVELS:
            notes["_unknown_level"] = level


def _sample(rec: dict) -> str:
    return str((rec.get("raw") or {}).get("_sample_date") or rec.get("sampled_at") or "")


@F.hook
def in_cyano_sequence(records: list[dict], ctx: F.Ctx) -> dict:
    """Observed advisory intervals only; never a sample date as an advisory date (module docstring)."""
    prev = {r["event_id"]: r for r in ctx.previous_records}
    stations: dict[str, list[dict]] = {}
    n = {"alerts_open": 0, "alerts_lifted": 0, "alerts_continued": 0, "samples_dropped": 0, "historical": 0}
    for r in records:
        raw = r["raw"]
        if raw.get("_station") and _sample(r):
            stations.setdefault(raw["_station"], []).append(r)
        p = prev.get(r["event_id"]) or {}
        if r["event_type"] != "hab_advisory" and p.get("event_type") != "hab_advisory":
            continue
        if r["event_type"] != "hab_advisory":
            # a level IDEM corrected below the advisory levels: the earlier observation is kept and closed below
            r["event_type"] = "hab_advisory"
            raw.pop("_sample_only", None)
            raw["_level_corrected"] = True
            r["advice_text"] = "The advisory level previously listed for this sample is no longer present."
        praw = p.get("raw") or {}
        observed = deepcopy(praw.get("_advisory_observed") or {}) if praw.get("_advisory_clock_version") == CLOCK_VERSION else {}
        r.update(sampled_at=_sample(r) or None, started_at=None, ended_at=None, time_precision=None,
                 reported_at=None, published_at=None, source_updated_at=None, status="unknown")
        raw.update(_advisory_clock_version=CLOCK_VERSION, _advisory_observed=observed, time_basis=CLOCK_NOTE)
        for key in ("_unlisted_since", "_last_seen_in_source", "ended_at_precision"):
            raw.pop(key, None)

    for rows in stations.values():
        rows.sort(key=lambda r: (_sample(r), r["event_id"]))
        current = [r for r in rows if not r["raw"].get("_missing_from_source_since") and not r.get("duplicate_of")]
        latest = current[-1] if current else None
        for r in rows:
            if r["event_type"] != "hab_advisory":
                continue
            raw = r["raw"]
            observed = raw["_advisory_observed"]
            positive = str(raw.get("_level") or "").lower() in ADVISORY_LEVELS and not raw.get("_level_corrected")
            sample = _sample(r)
            newer = next((x for x in current if _sample(x) > sample), None)
            if observed.get("start") and not observed.get("end") and (newer or (r in current and not positive)):
                observed.update(end=ctx.fetched_at, end_sample=(newer or r)["source_record_id"],
                                end_reason="a newer sample was observed" if newer else "the source corrected the level")
                observed["continued"] = bool(newer and str(newer["raw"].get("_level") or "").lower() in ADVISORY_LEVELS)
            try:
                age = (ctx.fetched_dt.astimezone(ctx.tz).date() - datetime.fromisoformat(sample).date()).days
            except ValueError:
                age = None
            if r is latest and positive and age is not None and 0 <= age <= RECENT_SAMPLE_DAYS and not observed.get("start"):
                observed["start"] = ctx.fetched_at
            if observed.get("start"):
                r.update(started_at=observed["start"], time_precision="poll", ended_at=observed.get("end"),
                         status=("ended" if observed.get("continued") else "advisory_lifted") if observed.get("end")
                         else "advisory_active")
                raw["_last_seen_in_source"] = observed["start"]
                raw["start_basis"] = "the first poll that showed this recent advisory-level sample; IDEM's issue time is not published"
                if observed.get("end"):
                    raw["ended_at_precision"] = "poll"
                    raw["end_basis"] = "the first poll showing the next sample or a corrected level, not IDEM's lift time"
                    n["alerts_continued" if observed.get("continued") else "alerts_lifted"] += 1
                else:
                    n["alerts_open"] += 1
            else:
                raw["start_basis"] = "historical sample; the advisory's issue and lift dates are not published"
                n["historical"] += 1
    n["samples_dropped"] = sum(bool(r["raw"].get("_sample_only")) for r in records)
    records[:] = [r for r in records if not r["raw"].get("_sample_only")]
    return n
