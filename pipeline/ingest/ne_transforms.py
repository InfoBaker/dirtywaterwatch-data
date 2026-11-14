"""Nebraska hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

ne_beachwatch_record: DWEE's Beach Watch layer (data/sources/ne-dwee-beachwatch.yaml), one row per weekly sample at a
public beach, mid-May to mid-September. The block reads every row of the layer; each row carries two separate
statements of the agency, and a row is a record only when one of them is made (ne_beachwatch_sequence drops the
others after reading them for the next week's statement):
  - HealthAlert 'YES' ("This beach is under health alert"): the sample's microcystin was above DWEE's and the
    Department of Health and Human Services' 8 micrograms per litre, which puts the lake on health alert and closes its
    designated beach. event_type hab_advisory: the authority's own alert flag for that sample. Advisory dates are
    unknown unless polling supplies observation bounds (ne_beachwatch_sequence).
  - EColiRisk 'Elevated health risk for E. coli' (E. coli above 235 per 100 mL): the layer's label, but DWEE issues no
    advisory for E. coli. event_type beach_advisory (the beach category), status unknown, raw._agency_label_only and
    raw._agency_label (the agency's words): the status build gives it the site's caution for 72 hours from the sample
    (data/rules.json unresolved.sample_caution), never the authority's advisory rule (review 2026-11-07 P2-2).
  A row with both is the health alert (hab_advisory), with the E. coli label in raw._ecoli_risk. A station on a lake in
another state (OUT_OF_STATE_STATIONS: Lake Yankton, South Dakota) names that lake, with raw.state, raw.county and
raw.state_basis: the status build places it only in that state (status.Resolver, place_elsewhere). A row with neither is
  marked raw._sample_only and is not a record.

ne_beachwatch_sequence (after_history): sample dates are not advisory issue or lift dates. Historical
samples keep sampled_at but no advisory timestamps, so they remain in their sample year's history without creating
an invented red interval. Only the latest positive sample at a station, at most 14 days old when first observed,
can open an observed advisory interval. Its start is that poll, not the sample date. A later sample or a corrected
flag ends the observed interval at the poll that first shows the change (an upper bound, not an agency lift time).
Unchanged historical rows never reconfirm an advisory; the usual 14-day aging applies from its last new observation.
Legacy sample-derived intervals are removed on the next successful read, including rows carried from prior seasons.
The safe source-field revisions are kept; sample-only rows are used for transitions and then removed.
The sample date (ActivityStartDate) is stored as an epoch at midnight Central time (05:00 UTC in summer), a date with
no time of day; the reader's midnight: date knows only UTC midnight, so the hook writes a Central-midnight value as the
date, precision day (raw._date_basis). A value at any other time stays the time it is.
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime

from ingest.generic import fieldmap as F

# Beach Watch stations whose lake lies outside Nebraska (DWEE samples them too): the record names the lake as its own
# state's records name it, with that state and county in raw.state / raw.county and the evidence in raw.state_basis, so
# the status build places it on that state's lake when that state is shown, and never on a Nebraska water near the
# point (review of the final audit 2026-11-07, P2-2). Lake Yankton (DWEE: "Lake Yankton (Cottonwood Lake) at Beach") is
# the lake below Gavins Point Dam on the South Dakota side; the station's point (42.853031, -97.468522) lies inside the
# bounding box of data/waters-sd.json lake-yankton-sd, 319 m from the Missouri River.
OUT_OF_STATE_STATIONS = {
    "YAKLKBACT1": {"state": "SD", "county": "Yankton County", "water": "Lake Yankton",
                   "basis": ("Lake Yankton lies in Yankton County, South Dakota, below Gavins Point Dam; the station's "
                             "point lies inside the South Dakota lake's outline box (lake-yankton-sd)")},
}

ALERT_RULE = ("DWEE and DHHS: a microcystin result above 8 micrograms per litre puts the lake on health alert and "
              "closes its designated beach")
ECOLI_RULE = "DWEE: E. coli above 235 per 100 mL is an elevated health risk; no advisory is issued for E. coli"


@F.hook
def ne_beachwatch_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    st = rec.get("started_at") or ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00[+-]0[56]:00", st):
        rec["started_at"], rec["time_precision"] = st[:10], "day"
        notes["_date_basis"] = "ActivityStartDate is stored as midnight Central time: read as the sample date"
    notes["_station"] = F.clean(row.get("StationID")).upper()
    away = OUT_OF_STATE_STATIONS.get(notes["_station"])
    if away:
        notes["waterbody_as_named"] = rec.get("waterbody_text")
        rec["waterbody_text"] = away["water"]
        notes["state"], notes["county"], notes["state_basis"] = away["state"], away["county"], away["basis"]
    alert = F.clean(row.get("HealthAlert")).upper() == "YES"
    ecoli = F.clean(row.get("EColiRisk"))
    micro, ec = F.clean(row.get("Microcystin")), F.clean(row.get("EColi"))
    if ecoli:
        notes["_ecoli_risk"] = ecoli
    if alert:
        # The sample date stays in started_at until ne_beachwatch_sequence (after_history) clears it: the block's
        # dedupe orders repeated record keys by started_at, and a start cleared here would hand a saved event id to
        # another source row (review 2026-11-14, Astra data P1-1).
        rec["sampled_at"] = rec.get("started_at")
        rec["event_type"], rec["status"] = "hab_advisory", "unknown"
        rec["advice_text"] = (F.clean(row.get("HealthDescription")) or "This beach is under health alert") + \
            (f" (microcystin {micro} micrograms per litre in the sample dated {rec['sampled_at']})" if micro else "")
        notes["_alert_basis"] = ALERT_RULE
    elif ecoli:
        rec["event_type"], rec["status"] = "beach_advisory", "unknown"
        rec["advice_text"] = (f"DWEE's label: \u201c{ecoli}\u201d (E. coli {ec} per 100 mL in the week's sample); the "
                              "agency issues no advisory for E. coli")
        notes["_alert_basis"] = ECOLI_RULE
        notes["_agency_label_only"] = True
        notes["_agency_label"] = ecoli
    else:
        rec["event_type"], rec["status"] = "unknown", "unknown"
        notes["_sample_only"] = True


CLOCK_VERSION = 1
RECENT_SAMPLE_DAYS = 14
CLOCK_NOTE = ("DWEE gives the sample date, not the advisory's issue or lift date. Any advisory times here are "
              "the polls that first showed a recent alert or its change, not times published by DWEE.")


def _sample_date(rec: dict, ctx: F.Ctx) -> str | None:
    if rec.get("sampled_at"):
        try:
            datetime.fromisoformat(rec["sampled_at"])
            return rec["sampled_at"]
        except (TypeError, ValueError):
            pass
    raw = rec.get("raw") or {}
    value = (raw.get("row") or {}).get("ActivityStartDate")
    try:
        return datetime.fromtimestamp(float(value) / 1000, ctx.tz).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        # Before the clock migration, a date-only start came directly from the sample date.
        # Retain that known date if the old snapshot no longer has the safe source field.
        old = rec.get("started_at")
        if not raw.get("_advisory_clock_version") and isinstance(old, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", old):
            try:
                return datetime.fromisoformat(old).date().isoformat()
            except ValueError:
                pass
        return None


def _legacy_observation(p: dict, sample: str | None, saved_by_station: dict, ctx: F.Ctx) -> dict:
    """The observation a record saved by the code before the clock (no _advisory_clock_version) can prove: the poll
    that first listed the health alert (raw._first_seen_at), when the sample was then at most RECENT_SAMPLE_DAYS old
    and no newer sample of the station had been seen by then. The end is the first sighting of the station's next
    saved sample, else the record's last saved poll (an upper bound). A sample first read late stays undated
    (review 2026-11-14, Astra data P1-2)."""
    praw = p.get("raw") or {}
    first = praw.get("_first_seen_at")
    if p.get("event_type") != "hab_advisory" or not sample or not isinstance(first, str) \
            or F.clean((praw.get("row") or {}).get("HealthAlert")).upper() != "YES":
        return {}
    try:
        seen = datetime.fromisoformat(first.replace("Z", "+00:00"))
    except ValueError:
        return {}
    if not 0 <= (seen.astimezone(ctx.tz).date() - datetime.fromisoformat(sample).date()).days <= RECENT_SAMPLE_DAYS:
        return {}
    newer = sorted(fs for s, fs in saved_by_station.get(praw.get("_station"), []) if s > sample and fs)
    if newer and newer[0] <= first:
        return {}                            # a newer sample was already listed: never the station's latest
    obs = {"start": first, "start_basis": "the first saved poll that listed this health alert (before the clock change)"}
    if p.get("ended_at") or p.get("status") in ("ended", "advisory_lifted"):
        later = [fs for fs in newer if fs > first]
        end = later[0] if later else p.get("fetched_at")
        if not end or end <= first:
            return obs
        obs.update(end=end, continued=p.get("status") == "ended", end_reason="a newer sample was observed",
                   end_basis=("the first saved poll that listed the station's next sample" if later else
                              "the last saved poll before the clock change, an upper bound; the first poll that showed "
                              "the change was not saved"))
    return obs


@F.hook
def ne_beachwatch_sequence(records: list[dict], ctx: F.Ctx) -> dict:
    """Use observations after history is joined; never infer an advisory date from a sample date."""
    prev = {r["event_id"]: r for r in ctx.previous_records}
    saved_by_station: dict[str, list[tuple[str, str | None]]] = {}
    for q in ctx.previous_records:
        qs = _sample_date(q, ctx)
        if qs and (q.get("raw") or {}).get("_station"):
            saved_by_station.setdefault(q["raw"]["_station"], []).append((qs, (q.get("raw") or {}).get("_first_seen_at")))
    stations: dict[str, list[dict]] = {}
    ecoli_corrections: dict[str, dict] = {}
    n = {"alerts_open": 0, "alerts_lifted": 0, "alerts_continued": 0, "samples_dropped": 0,
         "legacy_clocks_removed": 0, "legacy_observations_kept": 0}
    for r in records:
        raw = r["raw"]
        if raw.get("_ecoli_record_for"):
            continue                         # separate caution; not another weekly sample
        p = prev.get(r["event_id"]) or {}
        sample = _sample_date(r, ctx)
        if not sample and p:
            sample = _sample_date(p, ctx)
        station = raw.get("_station")
        if sample and station:
            stations.setdefault(station, []).append(r)
        if r["event_type"] != "hab_advisory" and p.get("event_type") != "hab_advisory":
            continue
        # A corrected YES -> NO row retains the earlier observed advisory and its safe revision history.
        # It is not mistaken for a vanished row and resurrected by keep_missing.
        if r["event_type"] != "hab_advisory":
            if r["event_type"] == "beach_advisory" and raw.get("_agency_label_only"):
                # Retaining the HAB observation must not swallow the independent E. coli caution.
                # The stable derived id lets later polls retain it without duplicating the source sample.
                caution = deepcopy(r)
                caution["event_id"] += ":ecoli"
                caution["source_record_id"] += ":ecoli"
                craw = caution["raw"]
                craw["_ecoli_record_for"] = r["event_id"]
                cprev = (prev.get(caution["event_id"]) or {}).get("raw") or {}
                craw["_first_seen_at"] = cprev.get("_first_seen_at") or ctx.fetched_at
                ecoli_corrections[caution["event_id"]] = caution
            r["event_type"] = "hab_advisory"
            raw.pop("_sample_only", None)
            raw.pop("_agency_label_only", None)
            raw.pop("_agency_label", None)
            raw["_alert_basis"] = ALERT_RULE
            r["advice_text"] = "The health-alert flag previously listed for this sample is no longer present."
        praw = p.get("raw") or {}
        observed = deepcopy(praw.get("_advisory_observed") or {}) if praw.get("_advisory_clock_version") == CLOCK_VERSION else {}
        if praw and praw.get("_advisory_clock_version") != CLOCK_VERSION:
            n["legacy_clocks_removed"] += 1
            observed = _legacy_observation(p, sample, saved_by_station, ctx)
            n["legacy_observations_kept"] += bool(observed)
            raw["_legacy_sample_clock_removed"] = {"started_at": p.get("started_at"), "ended_at": p.get("ended_at"),
                                                    "reason": "These were sample dates, not advisory issue or lift dates."}
        elif praw.get("_legacy_sample_clock_removed"):
            raw["_legacy_sample_clock_removed"] = deepcopy(praw["_legacy_sample_clock_removed"])
        r.update(sampled_at=sample, started_at=None, ended_at=None, time_precision=None,
                 reported_at=None, published_at=None, source_updated_at=None, status="unknown")
        raw.update(_advisory_clock_version=CLOCK_VERSION, _advisory_observed=observed, time_basis=CLOCK_NOTE)
        for key in ("_lifted_by", "_continued_by", "_unlisted_since", "_last_seen_in_source", "ended_at_precision"):
            raw.pop(key, None)

    for rows in stations.values():
        rows.sort(key=lambda r: (_sample_date(r, ctx), r["event_id"]))
        current = [r for r in rows if not r["raw"].get("_missing_from_source_since") and not r.get("duplicate_of")]
        latest = current[-1] if current else None
        for r in rows:
            if r["event_type"] != "hab_advisory":
                continue
            raw = r["raw"]
            observed = raw["_advisory_observed"]
            positive = F.clean(raw.get("row", {}).get("HealthAlert")).upper() == "YES"
            sample = _sample_date(r, ctx)
            newer = next((x for x in current if _sample_date(x, ctx) > sample), None)
            if observed.get("start") and not observed.get("end") and (newer or (r in current and not positive)):
                observed.update(end=ctx.fetched_at, end_sample=(newer or r)["source_record_id"],
                                end_reason="a newer sample was observed" if newer else "the source corrected the alert flag")
                observed["continued"] = bool(newer and F.clean(newer["raw"].get("row", {}).get("HealthAlert")).upper() == "YES")
            # A late first load of a historical season must not manufacture a current advisory. The freshness
            # limit is the same 14-day horizon as the status build's unconfirmed-advisory aging.
            age = (ctx.fetched_dt.astimezone(ctx.tz).date() - datetime.fromisoformat(sample).date()).days
            prior = (prev.get(r["event_id"]) or {}).get("raw") or {}
            corrected_to_yes = (positive and F.clean(prior.get("row", {}).get("HealthAlert")).upper() == "NO")
            if r is latest and positive and 0 <= age <= RECENT_SAMPLE_DAYS and (not observed.get("start") or corrected_to_yes):
                if observed.get("start"):
                    periods = observed.get("earlier_periods", []) + [{k: v for k, v in observed.items() if k != "earlier_periods"}]
                    observed.clear()
                    observed["earlier_periods"] = periods
                observed["start"] = ctx.fetched_at
            if observed.get("start"):
                r.update(started_at=observed["start"], time_precision="poll", ended_at=observed.get("end"),
                         status=("ended" if observed.get("continued") else "advisory_lifted") if observed.get("end") else "advisory_active")
                raw["_last_seen_in_source"] = observed["start"]
                raw["start_basis"] = observed.get("start_basis") or \
                    "the first poll that showed this recent health alert; its issue time is not published"
                if observed.get("end"):
                    raw["ended_at_precision"] = "poll"
                    raw["end_basis"] = observed.get("end_basis") or \
                        "the first poll showing the next sample or corrected flag, not an agency lift time"
                    n["alerts_continued" if observed.get("continued") else "alerts_lifted"] += 1
                else:
                    n["alerts_open"] += 1
            else:
                raw["start_basis"] = "historical sample; the advisory's issue and lift dates are not published"
    n["samples_dropped"] = sum(bool(r["raw"].get("_sample_only")) for r in records)
    keep = [r for r in records if not r["raw"].get("_sample_only") and r["event_id"] not in ecoli_corrections]
    keep.extend(ecoli_corrections.values())
    records[:] = keep
    return n
