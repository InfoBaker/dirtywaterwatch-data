# DirtyWaterWatch pipeline (docs/plan.md §5). Run from the project root.
#   make setup     create pipeline/.venv (requests, pyyaml, shapely, pytest)
#   make ingest    run every feed module in pipeline/ingest/ (helpers marked "not a feed" and
#                  INGEST_SKIP are left out), then the modules in INGEST_EXTRA (conditions); one
#                  failing feed does not stop the others. New York: ny_beaches_habs, ny_sprtk,
#                  ny_sprtk_web, nyc_dep_advisories (sorted order matters: ny_sprtk_web dedupes
#                  against the ny_sprtk events file, so it must run after ny_sprtk). Pennsylvania:
#                  pa_alcosan (SOAK log pages 1-3 + news posts; `--backfill` once to load 2025-),
#                  pa_crw (stub: licence, fetches nothing), pa_erie (last 30 days; `--backfill` from
#                  2025-01-01), pa_habs_beaches (PA DOH HAB layer + Erie County beach sheets),
#                  pa_phila_csocast (snapshot state machine, events dated to the poll); pa_waters is a
#                  helper (no __main__). New Jersey:
#                  INGEST_PRE nj_outfalls first (NJDEP CSO outfall layer -> data/build/nj-cso-outfalls.json,
#                  refetched weekly; nj_echo_monthly joins it), then the feeds nj_beaches, nj_ccmua (CCMUA's
#                  one-outfall gate status, events dated to the poll), nj_echo_monthly
#                  (ECHO asked once a month per permit), nj_hab, and after them INGEST_SNAPSHOTS
#                  nj_cso_likely (data/build/nj-cso-likely.json for the rain-likely rule; no events).
#                  nj_beaches --backfill (incident CSVs, 2025 to this year) is run by hand. Maryland:
#                  md_aa_health_closings (Anne Arundel health closings), md_baltimore_sso (City DPW SSO
#                  layer), md_mde_overflows (MDE statewide table; sorted order matters: it marks its
#                  copies of City SSOs duplicate_of the md-baltimore-sso records, so it runs after);
#                  md_waters is a helper (`python -m ingest.md_waters --extract` re-extracts waters-md.json).
#                  Virginia: va_alexrenew_cso (status layer snapshot state machine: poll every 15
#                  minutes), va_deq_prep (DEQ PReP sewage reports, last 30 days; `--backfill` from
#                  2025-01-01), va_richmond_cso (Richmond monthly workbooks; `--backfill` from
#                  January 2025), va_vdh_advisories (VDH issued/lifted releases; `--backfill` pages
#                  back to 2025); va_waters is a helper ("not a feed"; `python -m ingest.va_waters`
#                  re-extracts waters-va.json and the VA rows of waters-mid-atlantic.csv)
#                  North Carolina: nc_dwr_sso (DWR SSO layers, every Sanitary_Sewer_Overflows_since_Jan_<year>
#                  layer found; `--backfill` once for September 2022 - December 2025), nc_rwq_advisories (DMF
#                  coastal station status snapshot, advisory spells), nc_algal_blooms (DWR bloom reports;
#                  `--backfill` once for the 2020 - March 2026 archive layer)
#                  Generic feeds (docs/generic-ingesters.md): every data/sources/<id>.yaml whose fetch block says
#                  live: true runs as `python -m ingest.generic <id>`, sorted by id (a block's `after` first; a live
#                  block whose module is still a feed is refused; --list problems print "!!"), after every module and before
#                  INGEST_SNAPSHOTS (so a generic feed can dedupe against a module's events file); blocks with
#                  live: false (ports being compared with their modules) are not run.
#                  Florida: fl_dep_pnp (DEP Public Notice of Pollution, last 30 days; `--backfill` once
#                  for every notice since 2017), fl_dep_habs (DEP algal bloom visits), fl_doh_beaches
#                  (Healthy Beaches result pages: a full pass starts at most every 20 hours and is spread over
#                  hourly runs, at most 6 minutes of pages a run, resumed where it stopped)
#                  Michigan: mi_egle_mienviro (EGLE MiEnviro CSO/SSO List: every open report and the completed
#                  reports that started in the last 60 days; `--backfill [--from YEAR]` once, default from 2001,
#                  resumable, about 18 minutes for 2001-2026)
#                  Washington: wa_ecology_spills (Ecology's sewage spill list, RCW 90.48.636: the whole layer every
#                  run, every report since mid-2026, so no backfill) and the generic snapshot block
#                  wa-kc-cso-status-csv (King County / Seattle CSO status file, events dated to the poll); EPA's
#                  eRule tables carry JBLM and Puyallup (echo_sewer_overflow_events)
#                  California: ca_swrcb_ciwqs_spills (State Water Board CIWQS spill file: If-Modified-Since, a
#                  304 most hours and about 11 MB once a day; spills of the last 60 days and those on record;
#                  `--backfill` once for every spill since June 2023), ca_sfpuc_beaches (SFPUC beach map snapshot:
#                  the combined sewer discharge sign and postings), ca_swrcb_fhab (FHAB bloom reports) and
#                  ca_beachwatch (Beach Watch postings and closures; `--backfill` once for 1985 on), both read
#                  only when their data.ca.gov table changes; ca_datagov is a helper
#                  Illinois: echo_sewer_overflow_events (EPA's overflow tables, IL permits: the statewide record),
#                  il_mwrd_possible_cso (MWRD's daily-reset map of possible CSO events, polled), il_mwrd_lake_reversals
#                  (MWRD's table of reversals to Lake Michigan since 1985; needs pdftotext), il_idph_beachguard (IDPH's
#                  list of beach advisories in effect and each listed beach's page); il_mwrd is a helper
#                  Nebraska: echo_sewer_overflow_events (EPA's overflow tables, NE permits: the statewide record, each
#                  event in the zone of its own point, data/reference/ne-mountain-time-counties.json) and the generic
#                  ArcGIS block ne-dwee-beachwatch (DWEE Beach Watch: microcystin health alerts and elevated E. coli)
#   make conditions  the nearest USGS gauge per water and its latest flow, level, temperature,
#                  turbidity and conductance, NWS flood stages, cold/turbid/high-flow flags
#                  (ingest/gauges.py -> data/build/conditions.json; readings refetched when older
#                  than 15 minutes); shown beside the status, never changing it
#   make rainfall  NOAA MRMS radar rainfall (one 1-hour and one 24-hour grid an hour, sampled at every
#                  outfall point; per-point identify only when the grid fails) and the NWS 24-hour
#                  forecast (each grid cell every 3 hours) at every CSO outfall (New England, NY, PA, MD,
#                  VA, DC)
#                  (ingest/rainfall.py -> data/build/rainfall.json, rainfall-history.json); feeds the
#                  "discharge likely; no report received" caution (docs/rain-likely.md)
#   make rain-thresholds  per-permittee rainfall thresholds from the MassDEP reports
#                  (build/rain_thresholds.py -> data/build/rain-thresholds.json; run by make build)
#   make rain-thresholds-radar  Georgia and Michigan operators' amounts from the radar on their discharge days
#                  (one-off, by hand, after the states' backfills: about 600 point-service requests ->
#                  data/rain-thresholds-radar.json, tracked in git and merged by make build)
#   make provisional-outfalls  places where operators' own reports put an overflow, for operators with no
#                  official outfall point (build/provisional_outfalls.py -> data/build/outfalls-reported.json;
#                  docs/national-outfalls.md): clustered per operator (50 m), superseded by a registry outfall
#                  within 100 m, receiving water by USGS NLDI + NHDPlus names (cached in
#                  data/build/provisional-outfalls-cache.json; 45 s / 150 requests a run, the rest next run;
#                  NLDI allows 3,600 requests an hour per address, shared with reaches and waters_from_nhd).
#                  Reports without a point are geolocated (build/report_geolocate.py: Census, OSM, EPA FRS) and
#                  language models read what rules cannot (build/llm_judge.py; answers cached; $0.25 a run here).
#                  After ingest, before reaches and status. Batches by hand (most reports first):
#                  cd pipeline && python -m build.provisional_outfalls --budget-s 1500 --max-requests 1000 \
#                    --geolocate --geo-budget-s 900 --llm -v
#   make reaches   trace new river outfalls downstream (NLDI + NHDPlus, cached 30 days) and refresh
#                  the gauge readings (USGS OGC API); first run takes about 45 minutes
#   make build     research fixtures + per-water status and hourly history (data/build/)
#   make export    write out/ for the site
#   make charts    chart series (build/charts.py)
#   make refresh   ingest, provisional outfalls, reaches, build, charts, export (REFRESH_STAGES, in order; stops at
#                  the first that fails). Every feed, extra and stage prints "timing: NAME SECONDS s"
#                  (scripts/timed.sh; TIMINGS_FILE collects them, scripts/refresh-data.sh prints the longest at the end)
#   make tally     docs/source-tally.md: every information source by state, what we collect, what we do not and
#                  what would unlock it (scripts/gen_source_tally.py; reads out/ and data/, writes only the doc;
#                  scripts/refresh.sh runs it after the export)
#   make test      pipeline tests
# Research fixture events are off by default. FIXTURES=1 builds and includes them (--fixtures); the
# export then also needs DWW_ALLOW_FIXTURES=1 in the environment, so out/ never carries them by accident.
# NHDES=1 includes events files marked distribution_discouraged (--include-nhdes; owner's call pending).
# Until `make setup` has run, the openboatlaunch venv next door is used; `make test` uses it too
# while pipeline/.venv has no pytest (`make setup` installs it).

.PHONY: setup ingest waters-nhd conditions rainfall rain-thresholds rain-thresholds-radar provisional-outfalls reaches fixtures build charts export refresh tally test

VENV_PY := $(abspath pipeline/.venv/bin/python)
OBL_PY := $(abspath ../openboatlaunch/pipeline/.venv/bin/python)
PYTHON ?= $(if $(wildcard $(VENV_PY)),$(VENV_PY),$(OBL_PY))
PY = cd pipeline && $(PYTHON)
TIMED = sh $(abspath scripts/timed.sh)

FIXTURES ?= 0
FIXTURE_FLAG = $(if $(filter 1 yes true,$(FIXTURES)),--fixtures,) $(if $(filter 1 yes true,$(NHDES)),--include-nhdes,)
INGEST_SKIP ?= outfalls waters_extra waters_from_nhd   # waters_from_nhd runs as waters-nhd (INGEST_EXTRA), with a budget
INGEST_PRE = nj_outfalls             # registries the feeds join (not feeds), run before them
INGEST_SNAPSHOTS = nj_cso_likely     # snapshots read by build/ (not feeds), run after them
INGEST_EXTRA = waters-nhd conditions rainfall   # not feeds (no events file), run after them
# the NHD receiving-water build in the hourly run: new targets from this hour's reports, within a time budget (it stops
# before a request, writes what it built merged into data/waters-nhd.json, and the next run resumes from data/raw's
# cache). Without the budget, a runner with no data/raw cache asked NHDPlus for every target (about 7,000 requests)
# and passed the workflow's 55-minute limit. --wall-s bounds the whole target, loading and writing included (run
# 41788856038 took 11 minutes with --budget-s 300: the OSM fallback, its mirror check and the placement check over every
# event came on top): NHDPlus and the other places of a name share WATERS_NHD_BUDGET_S of requests, the OSM fallback
# (its mirror check included) gets what is left of the wall less 60 s kept for the hand records, the placement check
# and the write. The last line gives the seconds per phase.
WATERS_NHD_BUDGET_S ?= 150
WATERS_NHD_WALL_S ?= 300
INGEST_MODULES = $(sort $(basename $(notdir $(shell grep -l '__name__ == .__main__.' pipeline/ingest/*.py 2>/dev/null | xargs grep -L 'not a feed' 2>/dev/null))))

setup:
	cd pipeline && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest

ingest:
	@for m in $(INGEST_PRE) $(filter-out $(INGEST_SKIP) $(INGEST_PRE) $(INGEST_SNAPSHOTS),$(INGEST_MODULES)); do \
	  echo "== ingest.$$m"; \
	  (cd pipeline && $(TIMED) ingest.$$m $(PYTHON) -m ingest.$$m) || echo "!! ingest.$$m failed (exit $$?)"; \
	done
	@ids=$$(cd pipeline && $(PYTHON) -m ingest.generic --list) || echo "!! ingest.generic --list reported problems (exit $$?)"; \
	for g in $$ids; do \
	  echo "== ingest.generic $$g"; \
	  (cd pipeline && $(TIMED) generic.$$g $(PYTHON) -m ingest.generic $$g) || echo "!! ingest.generic $$g failed (exit $$?)"; \
	done
	@for m in $(INGEST_SNAPSHOTS); do \
	  echo "== ingest.$$m"; \
	  (cd pipeline && $(TIMED) ingest.$$m $(PYTHON) -m ingest.$$m) || echo "!! ingest.$$m failed (exit $$?)"; \
	done
	@for t in $(INGEST_EXTRA); do \
	  echo "== $$t"; \
	  $(TIMED) $$t $(MAKE) --no-print-directory $$t || echo "!! $$t failed (exit $$?)"; \
	done

waters-nhd:         ## receiving-water records from NHDPlus for new targets (ingest/waters_from_nhd.py), budgeted
	$(PY) -m ingest.waters_from_nhd --budget-s $(WATERS_NHD_BUDGET_S) --wall-s $(WATERS_NHD_WALL_S)

conditions:
	$(PY) -m ingest.gauges

rainfall:
	$(PY) -m ingest.rainfall

rain-thresholds:
	$(PY) -m build.rain_thresholds

rain-thresholds-radar:
	$(PY) -m build.rain_thresholds --radar MI GA

provisional-outfalls:   ## provisional outfalls from the reports (a failure keeps the previous file)
	$(PY) -m build.provisional_outfalls --geolocate --geo-budget-s 30 --llm --llm-cap-usd 0.25 --llm-budget-s 60 || echo "!! provisional outfalls failed; the previous data/build/outfalls-reported.json stays"

reaches:
	$(PY) -m build.reaches

fixtures:
	$(PY) -m build.fixtures

build: $(if $(filter 1 yes true,$(FIXTURES)),fixtures,)
	cd pipeline && $(TIMED) rain-thresholds $(PYTHON) -m build.rain_thresholds || echo "!! rain thresholds failed; the previous file stays"
	cd pipeline && $(TIMED) status $(PYTHON) -m build.status $(FIXTURE_FLAG)

charts:             ## per-water, per-discharger and per-state chart series (after build, before export)
	$(PY) -m build.charts

export:
	$(PY) -m export.build $(FIXTURE_FLAG)

REFRESH_STAGES = ingest provisional-outfalls reaches build charts export
refresh:
	@for t in $(REFRESH_STAGES); do \
	  $(TIMED) stage.$$t $(MAKE) --no-print-directory $$t || exit 1; \
	done

tally:              ## docs/source-tally.md from the checklist, the registry, out/ and the water files (after export)
	$(PYTHON) scripts/gen_source_tally.py

TEST_PY = $(shell $(PYTHON) -c "import pytest" >/dev/null 2>&1 && echo $(PYTHON) || echo $(OBL_PY))

test:
	cd pipeline && $(TEST_PY) -m pytest tests -q
