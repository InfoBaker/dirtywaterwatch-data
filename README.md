# DirtyWaterWatch data

The data collection behind [dirtywaterwatch.org](https://dirtywaterwatch.org): reported sewage discharges into
public waters in the United States, with the outfalls, operators, water bodies, public-notice channels and
reporting rules behind them. Public waters. Public record.

This repository holds the pipeline and the registries. The site (pages, maps, charts) is built elsewhere from the
files this pipeline publishes. Nothing here is a safety verdict: a report says a discharge was reported, a grey
water means no report was received, and no colour ever means "clean". How each state reports, and what is not
reported at all, is described on the site at `/reporting/`.

## What is here

| Path | What it holds |
|---|---|
| `pipeline/` | the Python pipeline: one ingester per feed (`ingest/`), the status, reach, rain-caution and provisional-outfall builds (`build/`), the export (`export/`), tests (`tests/`) |
| `data/sources/*.yaml` | one record per source read: name, homepage, licence as the source states it, cadence, access |
| `data/dischargers.json` | every sewer operator and permit tracked, with its public-notice channel |
| `data/notice-channels.json` | every public-notice channel a law, a permit or an operator's own practice names, monitored whether or not it shows anything today |
| `data/outfalls-*.json` | the outfall registry: combined sewer outfalls (EPA's national inventory joined to state layers) and treatment-plant outfalls, each tied to its receiving water |
| `data/waters-*.json`, `data/water-aliases.json` | the water records (openboatlaunch's national records plus NHD records for receiving waters it lacks) |
| `data/rules.json` | the status rules by state, in public wording with their citations |
| `data/state-profiles.json`, `data/receiving-waters-national.json` | per-state readiness and the national receiving-water target list |
| `research/<st>/` | per-state research: sources considered (used or not, with why), dischargers, the state profile |
| `docs/source-checklist.*`, `docs/source-tally.md` | every source considered, and (generated each refresh) what is collected per state and what is not |

Raw fetches are not kept in git; every record carries its source, the source's own times and the fetch time.

## How it runs

`make refresh` runs every feed, the builds and the export (`out/`); the GitHub Actions workflow
(`.github/workflows/refresh.yml`) runs it every hour, publishes the live files for the site and attaches the full
dataset to a release. `make test` runs the test suite. Python 3.12 or later; `make setup` creates the virtual
environment.

Between runs the pipeline's state is kept in object storage as two archives: `data/build` (the feeds' history and
snapshots, the reach traces) and the raw caches, the service answers in `data/raw` the code reads back (NHD, NLDI
and OpenStreetMap answers, the Census state outlines, the rainfall per outfall and a few layers).
`scripts/state_paths.py` lists those caches with the reason for each; every other raw fetch stays on the runner and
is never saved. Both are restored at the start and saved only after a run that ended well; a run that finds the
`data/build` archive but cannot read it stops before it publishes anything, and one that cannot fetch the raw caches
runs without them and leaves the stored ones as they are. The raw caches are capped at 200 MB; the `data/build` archive
warns over 200 MB and is still saved up to the storage upload limit.

**History copies.** Object storage keeps no earlier versions, so each save of the `data/build` archive
(`state/build.tar.gz`) replaces the last one. The refresh keeps three kinds of copy of it, private like it and only
under `state/daily/`, `state/monthly/` and `state/held/` (`scripts/state_paths.py` has the detail):

- `state/daily/build-<Mon..Sun>.tar.gz`: the first save of each UTC day, a ring of seven keys overwritten weekly.
- `state/monthly/build-<YYYY-MM>.tar.gz`: the first save of each month, kept.
- `state/held/build-<date>-<run>.tar.gz`: before each save a history guard compares every feed's record count with
  the restored archive. A feed that lost at least 1% and at least 5 of its records, or whose events file is gone, is
  a warning in the run log and in `data/build/history-guard.json`, and the restored archive is kept here, so the
  history before the run can be recovered. The save still goes on.

Each daily and monthly copy is followed by a small marker (`build-<...>.json` beside it). The next run reads the
marker and only then records the copy in `data/build/state-generations.json`, so the record never names a copy whose
upload failed, and a failed copy is made again by the next run.

At list prices (storage $0.015 per GB-month, Class A operations $4.50 per million, Class B $0.36 per million, no free
allowance netted out) and a 123 MB archive, the ring holds 0.86 GB ($0.013 a month), each monthly copy adds 0.123 GB
($0.0018 a month), the copies and markers are about 63 uploads a month ($0.0003) and the marker reads about 31
($0.00001): about $0.015 a month at first, $0.035 a month after a year. A held copy adds one upload and 0.123 GB until
it is deleted. The figures grow with the archive.

To roll back, by hand: put any small file at `state/PAUSE`, wait until a running refresh has ended (a run already
past its pause check still saves), copy the chosen daily, monthly or held object over `state/build.tar.gz`
(`python3 -I scripts/state_paths.py counts FILE OUT` shows a copy's records per feed), then delete `state/PAUSE`. The
next run makes the day's daily copy again, and the month's monthly copy when the restored archive predates it; copy
either to a `state/held/` key first to keep it as it was.

A state's water records are built by a separate, on-demand workflow (`.github/workflows/state-build.yml`), never
inside the hourly run, because a state takes hours of rate-limited requests:

    gh workflow run state-build.yml -f state=NC -f steps="waters ties" -f budget_s=1500 -f max_requests=1000

It runs the NHD pass for the state's receiving waters (`ingest.waters_from_nhd --state`) within the budget, ties
every outfall of the state to its record or a stated reason (`ingest.outfall_waters --state`), saves the raw caches
so the next dispatch resumes where this one stopped, and opens a pull request (branch `batch/<st>-<date>`) with the
changed registry files and the counts, for a person to review. It never runs beside the hourly refresh: it shares
its queue, which holds one waiting run, so dispatch one batch at a time and not while a refresh is waiting.
`scripts/state_batch.py` is the same batch by hand (`plan` prints the commands without running them).

The states' own Clean Water Act assessments (EPA ATTAINS) are joined to the water records once a week by a
separate, keyless workflow (`.github/workflows/attains.yml`, `scripts/attains_context.py`): EPA's national Expert Query
files and the ATTAINS map layers, matched by geometry within 100 m and the water's name. The result is saved as the
private state object `state/attains.tar.gz`; the hourly refresh restores it read only, and the export shows it on a
water's page as standing context beside the status, never as a status or a colour (`docs/attains.md`).

openboatlaunch's water records and their outlines come from openboatlaunch's API (`https://openboatlaunch.org/api/v1/`,
read only, one way), with the private state object `state/obl-water.tar.gz` as the last good copy:

- **The national file.** At the start of the workflows `scripts/state_paths.py fetch-obl` asks the API's `meta`
  (with its ETag, cached with the raw caches: a 304 most hours in the refresh) and, when there is a snapshot it has not pulled, downloads `bulk/national.tar.gz`,
  checks it against its `.sha256` file and the sha256 in `meta`, and unpacks it into `../openboatlaunch/out` with the
  same rules as the R2 restore (`water/<slug>.json` and `meta.json` only). It pulls at most once a day, unless the
  changes check asks for a full pull. When it is
  not needed, or on any failure (no key, the API down, a wrong checksum: the log says which), the workflow restores
  the R2 copy as before, and without either the run goes on without outlines.
- **The hourly changes.** The refresh's first stage (`make obl-sync`, `ingest.obl_changes`) asks `changes?since=` the
  last `until`, fetches each changed record by slug, writes it into the folder and rewrites the affected live states'
  `data/waters-<st>.json` in the runner. A renamed or merged water becomes a `slug_aliases` entry on its successor, so
  reports, outfall rows and pages follow the new slug; an outline change shows in the record's `geometry_hash` and
  the placement is redone. A water openboatlaunch deletes, or moves into another state, is never dropped: it stays in
  the extract marked `deleted` or `moved` (with its successor), so its reports keep their water until a person moves
  them. Every rename, merge and deletion, and every outline change on a water with a report showing, is listed in
  `data/build/obl-changes.json` and printed in the run log as a `status.md: - HH:MMZ: ...` line. More changes in an
  hour than it fetches one by one are logged from the change list and bring a national pull forward.
- **The daily pull request.** `.github/workflows/obl-extracts.yml` (`scripts/obl_extracts.py`) rewrites every live
  state's openboatlaunch extract from the folder once a day and puts the changed files on a branch `batch/obl-<date>`
  with a pull request listing the counts and the review lines, for a person to review and merge; nothing is committed
  to main by a workflow. A state with no extract on file gets its first one from the state batch's `extract` step, and
  an extract built from another source (DC's, from NHD) is merged, never replaced: its records that are openboatlaunch's by slug or GNIS id (compared as numbers) take openboatlaunch's outline and fields, the waters only openboatlaunch has are added, and its own are kept. In the six New England states the state
  extracts take precedence over `data/waters-new-england.json`.
- **The fallback copy.** When the API changed the folder, the refresh packs it (`state_paths.py pack-obl`) and saves it
  to R2 as `state/obl-water.tar.gz`; if that upload fails, the run's record of what it pulled is put back
  (`obl-not-saved`) so the next run asks again.
- **A state's extract.** The batch's `extract` step reads the state from the API's `states/{ST}/waters` (paged,
  without outlines) when the key is there, with the restored folder as its fallback.

The records carry openboatlaunch's API fields (`water_id`, `gnis_id`, `geometry_hash`, `geometry_tolerance_m`,
`status`, `successor_slug`, `previous_slugs`, `updated_at`); launches the API serves as unpublished (private,
commercial and club launches, as points with no personal fields) are kept in the extract as `launches_unpublished`,
and the site shows published launches only. The older copy's records (short launch keys) are still read.

**The key.** The API takes `Authorization: Bearer <key>`. Set it as the repository's GitHub Actions secret
`OBL_API_KEY` (Settings, Secrets and variables, Actions); both workflows pass it to their steps as an environment
variable. For a run by hand, put it in the environment variable `OBL_API_KEY` only. The pipeline never prints, logs
or writes the key; never commit it. Without it everything runs from the R2 copy as before. The API's answers worth
keeping (its `meta` and a state's pages) are cached under `data/raw/obl-api` with the other raw caches.

Until the API path has run for a while, the copy can still be uploaded by hand from a machine with the
openboatlaunch checkout (from the site repository's folder so `worker/` has wrangler; wrangler uploads up to
300 MiB, and the batch refuses an extract without `meta.json`'s date):

    COPYFILE_DISABLE=1 tar -czf /tmp/obl-water.tar.gz -C ../openboatlaunch/out water meta.json && (cd worker && npx wrangler r2 object put dirtywaterwatch-data/state/obl-water.tar.gz --file /tmp/obl-water.tar.gz --remote)

For example `-f state=MI -f steps="extract obl-check waters ties"` for a state with no extract yet, and
`-f state=FL -f steps="osm ties"` for the names NHDPlus does not carry. The `waters` step builds the waters the
national list holds (the outfalls' receiving waters); the waters only the reports name (a state's
`research/<st>/receiving-waters-missing.json`, for Georgia `scripts/ga_report_water_names.py` over the backfilled
feeds) need the `names` step: `-f state=GA -f steps="names ties"`. The registry match (`registry`,
`scripts/match_outfalls.py`) needs EPA's CSO inventory as well and runs where that is; the reach traces have no
per-state run yet.

## Using the data

The dataset release (`out/`) holds every normalised report (`events.json`, one record per report with its source,
record id, times, water, operator, volume as reported and the rule applied), the water statuses, the coverage
grades, the outfalls, the operators and the sources, and, per water, the state's own assessment units and findings
(`assessments.json` and `assessment` in `waters/<slug>.json`; `docs/attains.md`). CSV downloads per water, operator and state are on the site.
The dataset is released under the Open Database License (ODbL) 1.0 with attribution to DirtyWaterWatch and to each
source named in the records; the code under MIT. See `DATA-LICENSE.md`.

Licence: see `DATA-LICENSE.md`. Each source's own terms are quoted in its `data/sources/*.yaml` record and must be
honoured when the data is reused; records from sources whose terms discourage redistribution are not in the
release.

## Reporting a problem

Open an issue with the record id or the page URL. Please do not post personal information in issues; the pipeline
removes personal fields from source records and the project does not publish them.
