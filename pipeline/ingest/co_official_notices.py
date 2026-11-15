"""Colorado: selected official notices of sewage spills and water-contact or algae advisories (source id
co-official-notices), a reviewed notice set (ingest/notice_set.py: the records are transcribed from each page by a
reviewer, and every run confirms the page still carries the sentences they rest on).

Why a reviewed set of notices (Colorado publishes no spill list to read)
  Colorado publishes no list of sewage spills: operators report them to the Water Quality Control Division (C.R.S.
  25-8-601(2); the CDPS permits' 24-hour report), which publishes none of them; a large spill reaches the public only
  when an agency issues an advisory. CDPHE's own pages answered 403 to the build's client on 2026-11-14, and the City
  of Pueblo's news page did not answer (connection timed out), so its own account of the August 2026 spill could not be
  read. The pages read here, on 2026-11-14:

  1. Colorado Parks and Wildlife, "Water contact advisory at John Martin as Pueblo sewage spill moves downstream",
     published 2026-08-30 11:05 MDT: about 4.2 million gallons of untreated sewage entered the Arkansas River in Pueblo
     on August 26-27, 2026; CPW advised avoiding contact with the Arkansas River and John Martin Reservoir at the park
     from Monday, August 31. Two records: the spill (event_type sso, the City of Pueblo's permit CO0026646 as the
     operator: the notice says the spill was in Pueblo, and the research found the city's own follow-up; started
     2026-08-26, ended 2026-08-27, both to the day as the notice gives them; the volume as stated) and CPW's advisory
     (status advisory_active from 2026-08-31, no end: CPW said it would update the advisory and no update was found, so
     raw._ages_after_confirmation makes the status build's 14-day rule age it, as the type sso alone would
     not). The notice's mention of Lake Hasty's separate algae restriction is not a
     record here (the CDPHE sheet carries Lake Hasty, co-cdphe-toxic-algae).
  2. National Park Service, Curecanti National Recreation Area, "Toxic Algae detected in Blue Mesa Reservoir",
     2026-08-13: toxic algae at low levels in the Iola Basin, posted with yellow caution signs. A hab_advisory whose
     start is not given: started_at is the release day only as an upper bound (time_precision "bound",
     raw.start_bound "on_or_before"; the signs were up by then, their posting date is not given), Blue Mesa Reservoir,
     the Iola Basin in raw.place; never confirmed by a later read.
  3. Colorado Parks and Wildlife, Barr Lake State Park's activities page: "As of August 3 at 7pm ... the reservoir is
     now on red alert due to high concentrations of toxic algae". A standing hab_advisory from 2026-08-03 19:00 MDT,
     confirmed at every read that shows the line and ended at the first read that shows neither its sentences nor the
     words "red alert" (a poll bound); a read that shows only part of the wording, or the words without the sentences,
     is unresolved: the record stays as it was and the run's health is false. Shown again later: a new record. The same
     line's boating closure for low water is not a water-quality record.

Health: every notice must validate at every read (meta.unvalidated lists each that did not, with its reason); while
any does not, the readable notices are still updated, the run is written with health false (write_events partial) and
the exit is non-zero.

Each record keeps raw.time_zone America/Denver; a date-only start or end is a Colorado day.

Run from pipeline/:  python -m ingest.co_official_notices
"""
from __future__ import annotations

import sys

from common import EVENTS_DIR, now_iso, read_json, write_events
from ingest import notice_set as NS

SOURCE_ID = "co-official-notices"
TZ = "America/Denver"
CPW_JM = ("https://cpw.state.co.us/news/08302026/water-contact-advisory-john-martin-pueblo-sewage-spill-moves-"
          "downstream")
NPS_BM = "https://www.nps.gov/cure/learn/news/toxic-algae-detected-in-blue-mesa-reservoir.htm"
CPW_BARR = "https://cpw.state.co.us/state-parks/barr-lake-state-park/barr-lake-state-park-activities-trails"
CPW = "Colorado Parks and Wildlife"

NOTICES = [
    {"id": "cpw-john-martin-2026-08-30", "kind": "dated", "url": CPW_JM, "reviewed": "2026-11-14",
     "published_at": "2026-08-30T17:05:04Z",
     "records": [
         {"source_record_id": "pueblo-arkansas-river-2026-08-26", "event_type": "sso", "status": "ended",
          "discharger_id": "co-co0026646", "discharger_name": "City of Pueblo", "npdes_permit": "CO0026646",
          "waterbody_text": "Arkansas River", "started_at": "2026-08-26", "ended_at": "2026-08-27",
          "time_precision": "day", "material": "untreated sewage", "volume_gal": 4200000,
          "volume_text": "4.2-million-gallon untreated sewage spill", "estimate_flag": "unknown",
          "authority": f"{CPW} (news release)",
          "advice_text": ("Colorado Parks and Wildlife advised avoiding contact with the Arkansas River and John Martin "
                          "Reservoir at John Martin Reservoir State Park from August 31, 2026, as the water affected by "
                          "the spill moved downstream."),
          "quotes": ["Colorado Parks and Wildlife advises visitors to John Martin Reservoir State Park to avoid contact "
                     "with the Arkansas River and John Martin Reservoir beginning Monday, Aug. 31, as water affected by "
                     "a 4.2-million-gallon untreated sewage spill in Pueblo moves downstream.",
                     "The sewage entered the Arkansas River in Pueblo Aug. 26-27 and is expected to reach the reservoir "
                     "by Monday morning."],
          "raw": {"time_zone": TZ, "ended_at_precision": "day",
                  "start_basis": "the notice: the sewage entered the Arkansas River in Pueblo on August 26-27",
                  "end_basis": ("the notice: the sewage entered the river on August 26-27; the last day it gives, "
                                "not a stated end of the discharge time"),
                  "operator_basis": ("the notice places the spill in Pueblo; the City of Pueblo's own follow-up (its "
                                     "news page, not readable on 2026-11-14) is the operator's account the research "
                                     "found; permit CO0026646 is the city's plant permit"),
                  "county": "Pueblo",
                  "placement_hint": {"name": "Arkansas River", "county": "Pueblo", "state": "CO",
                                     "basis": "the notice: the sewage entered the Arkansas River in Pueblo"},
                  "volume_basis": "the figure the notice gives; how it was estimated is not stated"}},
         {"source_record_id": "john-martin-water-contact-advisory-2026-08-31", "event_type": "sso",
          "status": "advisory_active", "parent_event_id": f"{SOURCE_ID}:pueblo-arkansas-river-2026-08-26",
          "discharger_id": "co-co0026646", "discharger_name": "City of Pueblo", "npdes_permit": "CO0026646",
          "waterbody_text": "John Martin Reservoir", "started_at": "2026-08-31", "time_precision": "day",
          "authority": CPW,
          "advice_text": ("Avoid swimming, wading, tubing, paddleboarding, fishing and other activities involving direct "
                          "contact with water in the Arkansas River and John Martin Reservoir at the park; keep pets "
                          "away from the water (CPW, from August 31, 2026)."),
          "quotes": ["The park remains open and the advisory applies to activities involving direct contact with water "
                     "in the Arkansas River and John Martin Reservoir.",
                     "CDPHE will collect water-quality samples at the park, and CPW will update the advisory as "
                     "sampling results become available."],
          "raw": {"time_zone": TZ, "advisory_extent": "named_water", "_ages_after_confirmation": True,
                  "also_named": "the Arkansas River at John Martin Reservoir State Park",
                  "start_basis": "the notice: the advisory begins Monday, August 31, 2026",
                  "end_basis": ("no end given: CPW said it would update the advisory as sampling results became "
                                "available; no update was found. Aged 14 days from its start (raw._ages_after_confirmation: "
                                "the type sso has no aging of its own)"),
                  "county": "Bent",
                  "placement_hint": {"name": "John Martin Reservoir", "county": "Bent", "state": "CO",
                                     "basis": "the reservoir the advisory names (John Martin Reservoir State Park)"}}},
     ]},
    {"id": "nps-blue-mesa-2026-08-13", "kind": "dated", "url": NPS_BM, "reviewed": "2026-11-14",
     "published_at": "2026-08-13",
     "records": [
         {"source_record_id": "blue-mesa-iola-basin-2026-08-13", "event_type": "hab_advisory",
          "status": "advisory_active", "waterbody_text": "Blue Mesa Reservoir", "started_at": "2026-08-13",
          "time_precision": "bound",
          "authority": "National Park Service, Curecanti National Recreation Area",
          "advice_text": ("Toxic algae detected at low levels in the Iola Basin, posted with yellow caution signs; avoid "
                          "areas with observed or suspected blue-green algal mats throughout the reservoir."),
          "quotes": ["At this time, toxic algae have been detected at low levels in the Iola Basin.",
                     "The Iola Basin has been posted with yellow caution signs",
                     "Park staff advise avoiding areas with observed or suspected blue-green algal mats throughout the "
                     "reservoir."],
          "raw": {"time_zone": TZ, "place": "Iola Basin", "start_bound": "on_or_before",
                  "release_published": "2026-08-13",
                  "start_basis": ("not given: the release of August 13, 2026 says the basin had been posted; the "
                                  "posting date is not given, so started_at is only the latest day the advisory can "
                                  "have begun (time_precision bound), the release's publication day, not an issue "
                                  "date"),
                  "end_basis": "no end given and no later release found",
                  "county": "Gunnison",
                  "placement_hint": {"name": "Blue Mesa Reservoir", "county": "Gunnison", "state": "CO",
                                     "basis": "the reservoir the release names"}}},
     ]},
    {"id": "cpw-barr-lake-red-alert", "kind": "standing", "url": CPW_BARR, "reviewed": "2026-11-14",
     "anchor": "Barr Lake", "alert_words": ["red alert"],
     "records": [
         {"source_record_id": "barr-lake-red-alert-2026-08-03", "event_type": "hab_advisory",
          "status": "advisory_active", "waterbody_text": "Barr Lake", "started_at": "2026-08-03T19:00:00-06:00",
          "time_precision": "minute", "authority": f"{CPW}, Barr Lake State Park",
          "advice_text": ("The reservoir is on red alert for high concentrations of toxic algae, which can be harmful to "
                          "humans and pets; avoid contact with the water."),
          "quotes": ["As of August 3 at 7pm, NO hand launched vessels are allowed as the reservoir is now on red alert "
                     "due to high concentrations of toxic algae which can be harmful to humans and pets.",
                     "Visitors should avoid contact with the water and take precautions to prevent exposure."],
          # the warning itself: while this sentence is on the page, each read confirms the advisory
          "core_quotes": ["As of August 3 at 7pm, NO hand launched vessels are allowed as the reservoir is now on red "
                          "alert due to high concentrations of toxic algae which can be harmful to humans and pets."],
          "raw": {"time_zone": TZ,
                  "start_basis": "the park page: \"As of August 3 at 7pm\" (2026, the season the page names)",
                  "not_a_record": "the boating closure for low reservoir levels on the same line",
                  "county": "Adams",
                  "placement_hint": {"name": "Barr Lake", "county": "Adams", "state": "CO",
                                     "basis": "the reservoir of Barr Lake State Park"}}},
     ]},
]


def main(argv=None) -> int:
    fetched = now_iso()
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    try:
        recs, meta = NS.build(SOURCE_ID, NOTICES, fetched, prev)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    ok = not meta["unvalidated"]
    path = write_events(SOURCE_ID, recs, ok=ok, partial=not ok, meta=meta,
                        error=None if ok else "; ".join(f"{u['notice']}: {u['reason']}" for u in meta["unvalidated"])[:300])
    print(f"{SOURCE_ID}: {meta['pages_read']}/{meta['notices']} pages read, {len(recs)} records -> {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
