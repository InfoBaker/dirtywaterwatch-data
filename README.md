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

`make refresh` runs every feed, the builds and the export (`out/`); the GitHub Actions workflow runs it on a
schedule, keeps the pipeline's state between runs in object storage, publishes the live files for the site and
attaches the full dataset to a release. `make test` runs the test suite. Python 3.12 or later; `make setup`
creates the virtual environment.

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
