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

A state's water records are built by a separate, on-demand workflow (`.github/workflows/state-build.yml`), never
inside the hourly run, because a state takes hours of rate-limited requests:

    gh workflow run state-build.yml -f state=NC -f steps="waters ties" -f budget_s=1500 -f max_requests=1000

It runs the NHD pass for the state's receiving waters (`ingest.waters_from_nhd --state`) within the budget, ties
every outfall of the state to its record or a stated reason (`ingest.outfall_waters --state`), saves the raw caches
so the next dispatch resumes where this one stopped, and opens a pull request (branch `batch/<st>-<date>`) with the
changed registry files and the counts, for a person to review. It never runs beside the hourly refresh: it shares
its queue, which holds one waiting run, so dispatch one batch at a time and not while a refresh is waiting.
`scripts/state_batch.py` is the same batch by hand (`plan` prints the commands without running them).

openboatlaunch's water records and their outlines come from the private state object `state/obl-water.tar.gz`
(its `out/water` and `out/meta.json`), restored read only into `../openboatlaunch/out` beside the checkout, where the
pipeline reads them, by both workflows; neither ever saves it. With it in R2 no step needs the openboatlaunch checkout
or OpenStreetMap from a particular machine: the `extract` step writes a state's `data/waters-<st>.json` from it
(`ingest.obl_waters`, dated from the snapshot's `meta.json`), the `waters`, `osm` and `ties` steps measure against
its outlines, and the `osm` step gives OpenStreetMap's Overpass pass up to 20 minutes (`osm_budget`, with `budget_s` at most 3,780 s
together; GitHub's runners reach Overpass), resumed by the next dispatch. A new openboatlaunch snapshot is uploaded the same way it was
first (on a machine with the openboatlaunch checkout, from the site repository's folder so `worker/` has wrangler;
wrangler uploads up to 300 MiB, and the batch refuses an extract without `meta.json`'s date):

    COPYFILE_DISABLE=1 tar -czf /tmp/obl-water.tar.gz -C ../openboatlaunch/out water meta.json && (cd worker && npx wrangler r2 object put dirtywaterwatch-data/state/obl-water.tar.gz --file /tmp/obl-water.tar.gz --remote)

For example `-f state=MI -f steps="extract obl-check waters ties"` for a state with no extract yet, and
`-f state=FL -f steps="osm ties"` for the names NHDPlus does not carry. The registry match (`registry`,
`scripts/match_outfalls.py`) needs EPA's CSO inventory as well and runs where that is; the reach traces have no
per-state run yet.

## Using the data

The dataset release (`out/`) holds every normalised report (`events.json`, one record per report with its source,
record id, times, water, operator, volume as reported and the rule applied), the water statuses, the coverage
grades, the outfalls, the operators and the sources. CSV downloads per water, operator and state are on the site.
The dataset is released under the Open Database License (ODbL) 1.0 with attribution to DirtyWaterWatch and to each
source named in the records; the code under MIT. See `DATA-LICENSE.md`.

Licence: see `DATA-LICENSE.md`. Each source's own terms are quoted in its `data/sources/*.yaml` record and must be
honoured when the data is reused; records from sources whose terms discourage redistribution are not in the
release.

## Reporting a problem

Open an issue with the record id or the page URL. Please do not post personal information in issues; the pipeline
removes personal fields from source records and the project does not publish them.
