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
#                  Generic feeds (docs/generic-ingesters.md): every data/sources/<id>.yaml whose fetch block says
#                  live: true runs as `python -m ingest.generic <id>`, sorted by id, after every module and before
#                  INGEST_SNAPSHOTS (so a generic feed can dedupe against a module's events file); blocks with
#                  live: false (ports being compared with their modules) are not run.
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
#   make refresh   ingest, reaches, build, charts, export
#   make tally     docs/source-tally.md: every information source by state, what we collect, what we do not and
#                  what would unlock it (scripts/gen_source_tally.py; reads out/ and data/, writes only the doc;
#                  scripts/refresh.sh runs it after the export)
#   make test      pipeline tests
# Research fixture events are off by default. FIXTURES=1 builds and includes them (--fixtures); the
# export then also needs DWW_ALLOW_FIXTURES=1 in the environment, so out/ never carries them by accident.
# NHDES=1 includes events files marked distribution_discouraged (--include-nhdes; owner's call pending).
# Until `make setup` has run, the openboatlaunch venv next door is used; `make test` uses it too
# while pipeline/.venv has no pytest (`make setup` installs it).

.PHONY: setup ingest conditions rainfall rain-thresholds provisional-outfalls reaches fixtures build charts export refresh tally test

VENV_PY := $(abspath pipeline/.venv/bin/python)
OBL_PY := $(abspath ../openboatlaunch/pipeline/.venv/bin/python)
PYTHON ?= $(if $(wildcard $(VENV_PY)),$(VENV_PY),$(OBL_PY))
PY = cd pipeline && $(PYTHON)

FIXTURES ?= 0
FIXTURE_FLAG = $(if $(filter 1 yes true,$(FIXTURES)),--fixtures,) $(if $(filter 1 yes true,$(NHDES)),--include-nhdes,)
INGEST_SKIP ?= outfalls waters_extra
INGEST_PRE = nj_outfalls             # registries the feeds join (not feeds), run before them
INGEST_SNAPSHOTS = nj_cso_likely     # snapshots read by build/ (not feeds), run after them
INGEST_EXTRA = conditions rainfall   # not feeds (no events file), run after them
INGEST_MODULES = $(sort $(basename $(notdir $(shell grep -l '__name__ == .__main__.' pipeline/ingest/*.py 2>/dev/null | xargs grep -L 'not a feed' 2>/dev/null))))

setup:
	cd pipeline && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest

ingest:
	@for m in $(INGEST_PRE) $(filter-out $(INGEST_SKIP) $(INGEST_PRE) $(INGEST_SNAPSHOTS),$(INGEST_MODULES)); do \
	  echo "== ingest.$$m"; \
	  (cd pipeline && $(PYTHON) -m ingest.$$m) || echo "!! ingest.$$m failed (exit $$?)"; \
	done
	@for g in $$(cd pipeline && $(PYTHON) -m ingest.generic --list); do \
	  echo "== ingest.generic $$g"; \
	  (cd pipeline && $(PYTHON) -m ingest.generic $$g) || echo "!! ingest.generic $$g failed (exit $$?)"; \
	done
	@for m in $(INGEST_SNAPSHOTS); do \
	  echo "== ingest.$$m"; \
	  (cd pipeline && $(PYTHON) -m ingest.$$m) || echo "!! ingest.$$m failed (exit $$?)"; \
	done
	@for t in $(INGEST_EXTRA); do \
	  echo "== $$t"; \
	  $(MAKE) --no-print-directory $$t || echo "!! $$t failed (exit $$?)"; \
	done

conditions:
	$(PY) -m ingest.gauges

rainfall:
	$(PY) -m ingest.rainfall

rain-thresholds:
	$(PY) -m build.rain_thresholds

provisional-outfalls:   ## provisional outfalls from the reports (a failure keeps the previous file)
	$(PY) -m build.provisional_outfalls --geolocate --geo-budget-s 30 --llm --llm-cap-usd 0.25 --llm-budget-s 60 || echo "!! provisional outfalls failed; the previous data/build/outfalls-reported.json stays"

reaches:
	$(PY) -m build.reaches

fixtures:
	$(PY) -m build.fixtures

build: $(if $(filter 1 yes true,$(FIXTURES)),fixtures,)
	$(PY) -m build.rain_thresholds || echo "!! rain thresholds failed; the previous file stays"
	$(PY) -m build.status $(FIXTURE_FLAG)

charts:             ## per-water, per-discharger and per-state chart series (after build, before export)
	$(PY) -m build.charts

export:
	$(PY) -m export.build $(FIXTURE_FLAG)

refresh: ingest provisional-outfalls reaches build charts export

tally:              ## docs/source-tally.md from the checklist, the registry, out/ and the water files (after export)
	$(PYTHON) scripts/gen_source_tally.py

TEST_PY = $(shell $(PYTHON) -c "import pytest" >/dev/null 2>&1 && echo $(PYTHON) || echo $(OBL_PY))

test:
	cd pipeline && $(TEST_PY) -m pytest tests -q
