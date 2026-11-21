# State water quality assessments (EPA ATTAINS) beside a water's status

Each state assesses its waters under the Clean Water Act and reports to EPA which assessment units support their
uses, which do not, and what the state believes causes an impairment. This pipeline joins those assessments to the
water records and publishes, per water, the units that match it: whether the state lists the unit as impaired by
bacteria (the parameter group PATHOGENS: E. coli, enterococci, fecal coliform), the sewage sources the state names
for that impairment, the cycle year, the dates of the samples behind it and a link to the state's assessment.

**An assessment is not a current condition and never a status.** It is the state's finding on samples taken in past
years. It changes no water's status, colour or reach; it is shown in its own block on a water's page, beside the
status, like the gauge conditions. A unit with no pathogen listing is not a finding that the water is clean or safe:
most units are "Not Assessed" or "Insufficient Information" for recreation, and a listing covers only the samples the
state took, in the years it took them.

Code: `pipeline/build/attains.py` (the build), `scripts/attains_context.py` (its command line),
`pipeline/export/build.py` (`public_assessments`), `.github/workflows/attains.yml` (the weekly job), tests in
`pipeline/tests/test_attains.py`.

## Sources

All three are public. The first two need no key and are all the pipeline uses.

| Source | Address | What is read | Dates (read 2026-11-21) |
|---|---|---|---|
| Expert Query national downloads | the file list is the `metadata` object of `https://owapps.epa.gov/expertquery/api/lookupFiles`; the files sit on an EPA S3 bucket (`.../national-downloads/<folder>/<file>.csv.zip`; the folder number changes, so the addresses are read from the list each run) | `assessments.csv.zip` (203,056,994 bytes; 11,207,281 rows; 4.1 GB of CSV), `sources.csv.zip` (55,784,762 bytes; 2,974,172 rows), `assessment_units.csv.zip` (84,419,702 bytes; 3,337,072 rows) | all three timestamped 2026-11-14 in the list |
| ATTAINS map layers | `https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/ATTAINS_Assessment/FeatureServer`: layers 0 (points), 1 (lines), 2 (areas), table 5 (the control table: each organization's cycle and load date) | each state organization's assessment units: id, name, cycle, report link, recreation use, pathogens flag, cycle status, geometry | layers last edited 2026-09-02 (`editingInfo.dataLastEditDate`); each state's cycle and load date in the control table |
| ATTAINS web services (optional) | `https://api.epa.gov/attains/` | `assessments` for one unit, only to fill a matched unit the national files lack | every documented call answered HTTP 500 on 2026-11-21 from 13:19Z (an EPA outage); answering again at 18:52Z, when one test call with a key in the `X-Api-Key` header returned Black Bayou's 2026 assessment and the parser read it |

Not used: the other Expert Query files (`catchment_correspondence`, 1.4 GB, and `documents_text`, 472 MB, among
them) and How's My Waterway itself, which is a viewer of these services.

**The web services key.** EPA's "ATTAINS Web Services: How to Get an API Key" (version 2026-04-28,
`https://www.epa.gov/system/files/documents/2026-04/attains_web_services_api_key_2026-04-28.pdf`) sets the base
address `https://api.epa.gov/attains/` (the older `attains.epa.gov/attains-public/api/` stopped working after EPA's
May 2026 change), takes an api.data.gov key in the `api_key` query parameter or by api.data.gov's other options
(`https://api.data.gov/docs/developer-manual/`, among them the `X-Api-Key` header), and says Expert Query users (the
national downloads) need no key. The pipeline sends the key, when the environment variable `ATTAINS_API_KEY` is set,
in the `X-Api-Key` header only: an address can be printed in a public Actions log, a header is not. The key is never
logged, written or put in an address; the weekly workflow passes none, and everything runs and is tested without one.
With a key, at most 100 units a run are looked up, and only units the national files lack.

## How it runs

    pipeline/.venv/bin/python -I scripts/attains_context.py --out data/build/attains/attains-waters.json
    pipeline/.venv/bin/python -I scripts/attains_context.py --states TN MA      # a few states
    pipeline/.venv/bin/python -I scripts/attains_context.py --offline           # the cached files only
    pipeline/.venv/bin/python -I scripts/attains_context.py --refresh-geometry  # every state's geometry again

1. **File list.** The lookup is read; each address is checked (https, an EPA or Amazon S3 host, the expected file
   name). A file is downloaded again only when the list's timestamp or size differs from the cached copy's sidecar
   (`data/raw/attains/<file>.csv.zip` and `.meta.json`, git-ignored).
2. **Geometry.** For each live state (`data/rules.json` `live_states`) with a state organization in the control
   table, the three layers are read with `where orgtype='State' AND state='<ST>'`, 2,000 rows a page, paged by
   OBJECTID, `outSR=4326`, `maxAllowableOffset=0.0002` (about 20 m) and `geometryPrecision=5`; one request at a time,
   a one-second pause between requests, and back-off on HTTP 429, 5xx and ArcGIS errors (Retry-After honoured up to
   two minutes, six tries). Each state is cached as `data/raw/attains/geom/<ST>.json.gz` and fetched again only when
   its load date in the control table changes, after 90 days, or with `--refresh-geometry`. The rows repeat per
   geometry part; they are grouped by organization and unit id. All 52 live jurisdictions took 438 requests and 16
   minutes on 2026-11-21 (Pennsylvania's 185,225 line features 2.5 minutes); the cache is about 190 MB.
3. **Join** (below).
4. **National files.** Each zip's one CSV is streamed (zipfile and csv, never read whole; the assessments file took
   about 100 seconds) and only the rows of the matched units are kept. Several cycles per organization are in the
   files: for each organization the latest cycle **in each file** is kept, so a unit's assessment and its sources
   can come from different cycles (Illinois's and Delaware's newest source rows are from 2018), and each carries its
   own cycle. A matched unit that is not in its organization's latest cycle of the assessments file keeps the map
   layer's identity, link and flags (`"from": "layer"`).
5. **Output.** `data/build/attains/attains-waters.json` (below). A state whose geometry could not be fetched stops
   the run before anything is written: a partial file never replaces a whole one.

**Weekly.** `.github/workflows/attains.yml` runs on Mondays and by hand (with `refresh_geometry: yes` to refetch
all geometry). It restores openboatlaunch's outlines from R2 `state/obl-water.tar.gz` (the copy the hourly refresh
keeps; its API only when that copy is missing) and the geometry cache from `state/attains-geom.tar.gz`, runs the
build, and saves `state/attains.tar.gz` (the assessment file) and the geometry cache back to R2 through R2's S3
endpoint (`scripts/r2-s3-keys.sh`, every wrangler call behind `scripts/wrangler-guard.sh`). It honours R2
`state/PAUSE`. A failed run saves nothing; a geometry cache it could not fetch is not saved over. It has its own
concurrency group: it writes only its own two objects, never `state/build.tar.gz` or `current/`, so it never waits on,
blocks or cancels the hourly refresh or a state batch, which share the refresh's one waiting place. The hourly
refresh restores `state/attains.tar.gz` read only after its build state (`state_paths.py unpack-attains --only
cache`, which writes the assessment file and nothing else); the copy that then rides in `state/build.tar.gz` is the
fallback when the object cannot be fetched.

## The join

The water records are the export's: the live states' records (`build/status.py` `load_waters`, aliases from
`data/water-aliases.json` included) with their outlines (openboatlaunch's `out/water/<slug>.json`, or the inline
geometry of a `data/waters-extra.json`, `waters-dc.json` or `waters-nhd.json` record), simplified to about 10 m.

A unit matches a water when **both** hold:

- **Geometry.** Measured in metres on a local projection about the unit. A line lies along the water: within 100 m
  of the water's outline, for at least half its length or 500 m, whichever is less (a tributary that only touches
  the water at its mouth does not match). An area intersects the water or lies within 100 m of it. A point lies
  within 100 m.
- **Name.** The unit's name and one of the water's names (its name and aliases, each also split at "/", ";" and
  parentheses) agree after normalisation: case, punctuation and apostrophes dropped; abbreviations written out
  ("Cr" creek, "R" river, "Res" reservoir, "Lk" lake, "St" saint, "Mt" mount, "Br" branch, "N/S/E/W" and "S.F."
  for directions and forks, among others); "reservoir" counts as "lake" (Kentucky Lake, Kentucky Reservoir); a
  trailing "River" after a fork or creek word is dropped (Caney Fork, Caney Fork River); a trailing id
  ("Larrys Creek-66911819"), parentheses and location words ("from", "above", "below", "to", "mile 12") are cut. The
  names agree when they have the same words in any order; when the unit's name begins with the water's name and the
  next word does not make another water ("Cumberland River Embayment" agrees with Cumberland River; "Mill Creek
  Tributary", "Little Mill Creek" and "Shenandoah River North Fork" do not); when a qualifier of the same water comes
  first ("Upper Mississippi River", "Tidal Anacostia River"); or when one part of a compound unit name agrees
  ("Dalco Passage and East Passage", "Nisqually Reach/Drayton Passage", the reservoir of "Emory River Embayment of
  Watts Bar Reservoir"). A fork written after the name ("Lewis River, E.F.", "White River - West Fork") is the fork,
  never the main stem. A reservoir unit on a river record matches only when the reservoir's name is one of the
  water's aliases (`data/water-aliases.json`) or the unit's name contains the river's name. A name that is the
  other with initials or "of", "the", "and" added also agrees ("A M Puett Reservoir" and "Puett Reservoir."); a name
  that adds a word does not ("Little Mill Creek"; Ohio's watershed "Sawyer Brook-Cuyahoga River" against the
  Cuyahoga River).
- **State.** The unit belongs to the water's state: its state organization's state equals the water record's state
  (its `state` field, else the slug's last part). A water record in one state never carries another state's units
  (a unit that would match the Allegheny River's New York record from Pennsylvania's assessment is left out with the
  reason `other_state`); the water's record in the other state carries them.

Units whose names say they are unnamed or lumped ("Unnamed ...", "UT ...", "Misc. Tribs.", "Tributaries",
"Unsegmented ...", anywhere in the name) never match by name. They match only when 90 percent of the unit lies inside
a lake, pond or reservoir's outline (buffered 100 m), never along a river.

The match is recorded as `method` (`geometry+name` or `geometry_inside`) and `distance_m`. A water can match many
units (a river runs through many) and a unit several waters (a river record in two states, a lake and its arm); all
are kept, sorted with a pathogen listing first, then a sewage source, then distance.

## Sewage sources

Only the probable sources tied to a PATHOGENS cause are kept, and only these count as sewage (kind in brackets):
combined sewer overflows (`cso`); sanitary sewer overflows (`sso`); municipal point source discharges, package
plants, pretreatment failures and sewage lagoons (`municipal`); the mixed "Wet Weather Discharges (Point Source and
Combination of Stormwater, SSO or CSO)" (`wet_weather`); septic systems, sewage discharges in unsewered areas,
unpermitted discharge of domestic wastes, septage disposal and illicit connections to storm sewers (`septic`); and
marina or boating sanitary on-vessel discharges (`boat`). Urban runoff and storm sewers, "Municipal (Urbanized High
Density Area)", municipal separate storm sewer systems (MS4) and other stormwater are not sewage. Not counted either:
"Unspecified Domestic Waste" (3,799 pathogen source rows nationally), "Marina/Boating Pumpout Releases" (154) and the
non-point wet-weather category. Each kept source carries its own cycle (`cycle`).

## Files

**`data/build/attains/attains-waters.json`** (pipeline state; R2 `state/attains.tar.gz`; never in git):

    {"built", "source": {"name", "files": [{"name", "url", "timestamp", "bytes", "rows"}],
                         "layers": {"url", "data_last_edited"}, "fetched_at", "geometry_fetched": {ST: time},
                         "latest_cycles": {"assessments": {org: cycle}, "sources": {org: cycle}}},
     "states": {ST: {"units", "waters", "waters_with_units", "waters_pathogen_listed", "waters_sewage_named"}},
     "waters": {slug: {"units": [UNIT], "summary": SUMMARY}},
     "audit": {slug: [{"org_id", "au_id", "au_name", "reason", "distance_m", "kept"?, "others"?}]}}

UNIT: `org_id`, `org_name`, `state`, `au_id`, `au_name`, `cycle` (the organization's latest cycle in the assessments
file, else the layer's), `cycle_status`, `water_type`, `size`, `size_units`, `location` (the state's text), `recreation`
(`support` in ATTAINS's words: "Not Supporting", "Fully Supporting", "Insufficient Information", "Not Assessed";
"Not Supporting" when any recreation use is; `uses`, the recreation uses; `monitoring_start`, the earliest, and
`monitoring_end`, the latest, of their monitoring dates; `assessment_date`; dates as given, never a time), `pathogens`
(`parameter`, `status` as given: "Cause", "Meeting Criteria", "Insufficient Information", "Observed effect", "Removed";
`ir_category`; `first_listed`; `delisted` when true; `uses` and `use_groups`, the uses the file assesses the parameter
against, left out when it ties it to none), `sewage_sources` (`name`, `kind`, `confirmed`, `cause`, `cycle`),
`sources_cycle` (the one cycle all its sources come from, else null), `has_tmdl` (a pathogen parameter in category 4A
or tied to a TMDL), `report_url` (the cycle-pinned How's My Waterway address, the citation), `latest_url` (the
cycle-less address, which opens the state's latest assessment), `from` ("national files" or "layer") and `match`
(`method`, `distance_m`, `geometry`: the unit's kind, "line", "area" or "point"; `name_from`: "location" when the
unit is named by a station code and its location text was compared).

**Facts by organization, unit and cycle.** A unit is identified by `org_id`, `au_id` and `cycle`. Its assessment is
its organization's latest cycle in the assessments file. Its sewage sources all come from one cycle, the organization's
latest in the sources file (`sources_cycle`, repeated on each source); sources of different cycles are never mixed in
one record, and when `sources_cycle` differs from `cycle` both are shown.

**Audit list** (cache only, never exported). Per water, the units the geometry search found that the join did not
take, with the reason: `name_mismatch` (along the water within 100 m, another name), `too_far` (same name, farther
than 100 m), `not_along` (same name, within 100 m but not along the water: a confluence or a crossing),
`unnamed_on_river` (an unnamed or lumped unit along a river, stream, bay or canal), `not_inside` (an unnamed unit by a
lake that does not lie inside it), `no_name` (a station-coded unit without location text), `other_state` (a unit that
would match, from another state's assessment, with that `state`); and each unit taken by more
than one water, `ambiguous_multi_water` with `kept: true` and the `others`. A unit whose name disagrees and that does
not lie along the water is not listed.

SUMMARY: `units`, `pathogen_listed` (units with a PATHOGENS parameter in status "Cause"), `sewage_named` (units with a
sewage source), `latest_cycle`, `states`.

**Export.** `out/waters/<slug>.json` carries `assessment`: `{"source", "units", "summary"}` for a tracked water with
units, else null; its `source` is the citation (`name`, `files`, `layers`, `fetched_at`). It carries at most 25 units,
a pathogen listing first, then a sewage source named, then distance; its `summary` counts what it carries (`units`,
`pathogen_listed`, `sewage_named`, `latest_cycle`, `states`) and, before the cap, `units_total`,
`pathogen_listed_total` and `sewage_named_total`. The cache and the download keep every unit. `out/assessments.json` is
`{"built", "source", "waters": {slug: SUMMARY}}` with the whole source block (the latest cycle of each organization in
each file, the geometry fetch time of each state) once. `out/meta.json` carries
`assessments`: `waters_with_units`, `waters_pathogen_listed`, `waters_sewage_named`, `waters_capped` (blocks cut to 25
units), `built` and `unavailable` (why nothing is shown, else null). A cache that is missing, unreadable or built more than 30 days before the export leaves
every `assessment` null and says why in the log and in `unavailable`; it never fails the export. A slug the cache knows
under an older name is written under the record's own slug. The report CSV downloads are unchanged. `assessments.json`
is in the export's public payloads, so the blocklist self-check reads it with `waters/*.json`. The code is
`pipeline/export/assessments.py`; `export/build.py` only calls it.

**Download.** `out/csv/assessments.csv`, served by the site as `https://dirtywaterwatch.org/csv/assessments.csv`: one
row per tracked water and matched unit, every unit (no cap), waters by slug, units in the block's order. Same format as the report CSVs (UTF-8
without a byte-order mark, RFC 4180, CRLF, a header row, lists joined with `;`, a leading apostrophe on text that
begins with `=`, `+`, `-` or `@`). Columns: `water_slug`, `water`, `org_id`, `org_name`, `state`, `au_id`, `au_name`,
`cycle`, `cycle_status`, `water_type`, `size`, `size_units`, `location`, `recreation_support`, `recreation_uses`,
`monitoring_start`, `monitoring_end`, `assessment_date`, `pathogen_parameters`, `pathogen_statuses` and
`pathogen_ir_categories` (in the same order), `pathogen_listed` and `has_tmdl` (`true`/`false`), `sewage_sources`
and `sewage_kinds` (in the same order), `sources_cycle`, `report_url`, `latest_url`, `match_method`,
`match_distance_m`, `assessment_from`. No file when no water has a unit (a missing or stale cache). The site's
`docs/data-downloads.md` should list it with these columns.

## Counts from the first run

Run locally on 2026-11-21 (built 23:21Z) against the national files timestamped 2026-11-14 and the map layers as last
edited 2026-09-02, every live jurisdiction, with openboatlaunch's outlines of 2026-11-07 (the export's geometry source)
and the water records at data main of 2026-11-21. Every count here is read from the run's own file.

- **Water records:** 26,882 in the live states, 25,388 with an outline. **14,272 have at least one unit of their own
  state; 3,894 have a unit with a pathogen listing (PATHOGENS in status "Cause"); 964 have a unit with a sewage source
  named.**
- **Matched units:** 44,331 distinct units, 45,120 water-unit pairs: 44,473 by geometry and name, 647 inside a lake's
  outline; 47 units come from the layers alone (not in their organization's latest cycle of the assessments file).
  3,104 units named by a code (3,074 of them South Carolina's points) were compared by their location text: 198 waters.
  183 waters have more than 25 units, 41 more than 100 (Pennsylvania's short units).
- **Sewage sources on matched units:** municipal 1,400, septic and unsewered 1,219, combined sewer overflows 390,
  sanitary sewer overflows 291, mixed wet weather 278, boats 59 (unit-source pairs).
- **Audit list:** 16,737 waters carry one; name_mismatch 39,228, unnamed_on_river 10,289, not_inside 6,829,
  other_state 3,162, not_along 1,658, too_far 201, and 1,522 entries for units kept on more than one water
  (ambiguous_multi_water).
- **Cache:** 47.4 MB (3.8 MB compressed), the audit list about a third of it.
- **Tracked waters** (the 8,120 waters of the export of 2026-11-14): 4,833 with units, 2,170 with a pathogen listing,
  576 with a sewage source named; 135 blocks cut to 25 units.
- **Export size** on those 8,120 waters, after the cap: `assessment` adds 19.6 MB to `out/waters/*.json` (about 5.1 MB
  compressed; 4,833 blocks, median 2.3 KB, none over 100 KB; the largest, the Roanoke River in Virginia, 33 KB) and no
  file. Two files are new: `out/assessments.json` (0.8 MB) and `out/csv/assessments.csv` (11.1 MB, 25,147 rows, every
  unit).

Per state (a water counts in its own state; "Units in the layers" is the state organization's units in its cycle in
the layers):

| St | Units in the layers | Water records | With a unit | With a pathogen listing | With a sewage source named |
|---|---:|---:|---:|---:|---:|
| AK | 626 | 203 | 55 | 2 | 0 |
| AL | 1,909 | 658 | 383 | 143 | 64 |
| AR | 1,367 | 548 | 213 | 12 | 0 |
| AZ | 349 | 162 | 57 | 10 | 7 |
| CA | 3,809 | 686 | 409 | 63 | 13 |
| CO | 1,449 | 315 | 162 | 18 | 0 |
| CT | 1,677 | 268 | 190 | 82 | 43 |
| DC | 35 | 19 | 12 | 12 | 8 |
| DE | 377 | 78 | 49 | 37 | 0 |
| FL | 6,546 | 1,279 | 689 | 204 | 0 |
| GA | 3,165 | 721 | 444 | 236 | 32 |
| HI | 631 | 46 | 15 | 4 | 0 |
| IA | 2,753 | 295 | 203 | 83 | 0 |
| ID | 5,893 | 226 | 170 | 23 | 3 |
| IL | 3,772 | 690 | 434 | 98 | 24 |
| IN | 16,192 | 574 | 388 | 131 | 87 |
| KS | 2,413 | 339 | 279 | 110 | 0 |
| KY | 3,430 | 444 | 287 | 127 | 0 |
| LA | 506 | 577 | 134 | 50 | 50 |
| MA | 2,785 | 774 | 556 | 148 | 82 |
| MD | 1,338 | 367 | 163 | 50 | 10 |
| ME | 810 | 605 | 66 | 9 | 3 |
| MI | 7,874 | 1,523 | 701 | 41 | 13 |
| MN | 24,923 | 2,333 | 355 | 153 | 0 |
| MO | 4,756 | 771 | 524 | 59 | 6 |
| MS | 1,147 | 367 | 156 | 19 | 0 |
| MT | 1,202 | 266 | 127 | 8 | 5 |
| NC | 3,870 | 764 | 388 | 60 | 0 |
| ND | 1,697 | 314 | 184 | 44 | 0 |
| NE | 2,110 | 332 | 214 | 60 | 0 |
| NH | 8,823 | 428 | 384 | 72 | 0 |
| NJ | 958 | 253 | 64 | 43 | 0 |
| NM | 841 | 73 | 61 | 14 | 14 |
| NV | 705 | 34 | 21 | 1 | 0 |
| NY | 4,679 | 695 | 351 | 40 | 0 |
| OH | 1,600 | 1,090 | 305 | 281 | 9 |
| OK | 4,206 | 249 | 219 | 54 | 54 |
| OR | 3,065 | 491 | 254 | 61 | 0 |
| PA | 185,459 | 416 | 323 | 64 | 5 |
| PR | 336 | 31 | 22 | 22 | 22 |
| RI | 886 | 111 | 77 | 18 | 10 |
| SC | 3,080 | 422 | 198 | 115 | 0 |
| SD | 371 | 412 | 186 | 52 | 0 |
| TN | 5,849 | 384 | 301 | 141 | 84 |
| TX | 2,673 | 995 | 515 | 204 | 79 |
| UT | 918 | 155 | 108 | 27 | 0 |
| VA | 8,609 | 553 | 411 | 266 | 224 |
| VT | 1,141 | 203 | 50 | 17 | 5 |
| WA | 9,047 | 658 | 173 | 99 | 0 |
| WI | 34,126 | 2,153 | 1,905 | 22 | 8 |
| WV | 47,452 | 331 | 293 | 162 | 0 |
| WY | 322 | 201 | 44 | 23 | 0 |
| **All** | **434,557** | **26,882** | **14,272** | **3,894** | **964** |

## Costs

Measured on 2026-11-21 on a laptop (the run shared the machine with other work, so the times are
upper bounds), every live jurisdiction:

| Step | Requests or bytes | Wall time | Peak memory |
|---|---|---|---|
| The three national files | 343,261,458 bytes (203,056,994 + 55,784,762 + 84,419,702), once per new timestamp | 9.5 minutes (345 + 157 + 70 s) | small (streamed to disk) |
| Assessment-unit geometry, all 52 jurisdictions | 438 requests, one at a time with a one-second pause; about 193 MB cached (compressed) | 16 minutes | small |
| The join and the files' read (`scripts/attains_context.py`, downloads and geometry cached) | none beyond the file list and the layers' metadata (5 requests) | 4.9 minutes on an idle machine (292 s); 11.8 minutes under load | 3.8 GB resident at most (2.3 to 3.8 GB over three runs) |

Estimate for the weekly job on GitHub's standard runner (4 processors, 16 GB): the downloads from EPA's bucket in
about two to five minutes; the geometry in about 16 minutes on the first run and only for reloaded states after it
(the cache restored from R2); the join and the files' read in about 5 to 15 minutes. A first run takes about 30 to 40
minutes, a later one 10 to 20; the job's limit is 150 minutes. Peak memory, under 4 GB, stays well inside 16 GB. The R2 objects:
`state/attains.tar.gz` about 4 MB, `state/attains-geom.tar.gz` about 200 MB.

## Limits

- An assessment is years old. Cycles run every two years and many states are behind: Massachusetts, North Carolina,
  North Dakota, Nebraska, New Jersey, New York and Washington were on their 2022 cycle in the layers on 2026-11-21, and
  the samples behind a 2026 listing can be from 2021 (Black Bayou, Memphis). Every finding carries its cycle and its
  monitoring dates.
- A listing covers only the samples the state took. "Meeting Criteria" or "Fully Supporting" is not a clean bill, and
  no listing means nothing: most units are not assessed for recreation.
- Fifteen states name no sources at all in the national file (CO, FL, HI, KS, KY, MN, NC, ND, NE, NJ, NV, NY, OR, SC,
  WA), and several more never name a sewage source for pathogens; a missing source is not a missing sewage problem.
- Unit boundaries are the state's: Ohio assesses watershed polygons, Pennsylvania splits streams into very short
  units, Washington uses grid cells on marine waters. A unit can cover part of one of our waters, and a water can cross
  units with different findings.
- The join misses some true matches: reservoir names on river records (Kentucky Reservoir on the Tennessee River)
  until they are aliases, names the states spell differently (Bellingham Harbor and Bellingham Bay (Inner), Duwamish
  River and Duwamish Waterway), "Big Raccoon Creek" for Raccoon Creek. It can also take a unit of the same name that
  runs beside the water for half its length. The distance and the method are published with every match.
- The national files can hold a newer cycle than the map layers (Virginia, Iowa, Ohio, Arkansas and Mississippi were
  2026 in the files and 2024 in the layers); the unit's identity comes from the layers and its findings from the
  files' latest cycle.
- Dates are given as the file gives them, errors included (one Massachusetts unit's assessment date reads 1922);
  monitoring dates are missing for many units, and then no sampling years can be stated.
- The web services were down for hours on 2026-11-21 (HTTP 500 for every documented call, How's My Waterway showing
  "Assessment information is temporarily unavailable"); the pipeline does not depend on them.
