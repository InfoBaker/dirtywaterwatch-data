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
#                  Arizona: echo_sewer_overflow_events (EPA's overflow tables, AZ permits: the statewide record of
#                  AZPDES overflows and bypasses, with ADEQ's waterbody identifiers named from
#                  data/reference/az-adeq-wbids.json; scripts/az_adeq_wbids.py refreshes that file by hand)
#                  South Dakota: echo_sewer_overflow_events (EPA's overflow tables, SD permits: the statewide record,
#                  the 5-day written reports; times in the zone of the event's point, Mountain or Central, from
#                  data/reference/sd-mountain-time-counties.json, written by scripts/sd_mountain_time_counties.py),
#                  sd_danr_hab_advisories (the list of the year's bloom advisories on DANR's HAB page)
#                  Mississippi: echo_sewer_overflow_events (EPA's overflow tables, MS permits in Central time: the
#                  statewide record; MDEQ posts none), ms_mdeq_water_contact (MDEQ's news releases: water contact
#                  advisories issued and lifted, the standing Pearl River advisory) and ms_mdeq_beaches (MDEQ's
#                  beach layer: advisories, closures and coastal blooms on both flags and MDEQ's start date)
#                  Nebraska: echo_sewer_overflow_events (EPA's overflow tables, NE permits: the statewide record, each
#                  event in the zone of its own point, data/reference/ne-mountain-time-counties.json) and the generic
#                  ArcGIS block ne-dwee-beachwatch (DWEE Beach Watch: microcystin health alerts and elevated E. coli)
#                  Alaska: echo_sewer_overflow_events (EPA's overflow tables, AK permits: the only dated record;
#                  Alaska time, Hawaii-Aleutian for a point in the Aleutians west of 169 30 W); Juneau's CSO notice page is a
#                  register row read by notification_pages
#                  New Mexico: echo_sewer_overflow_events (EPA's overflow tables, NM permits and the Navajo Nation's
#                  reports located in New Mexico: the only public record of New Mexico overflows; NMED's own notices
#                  under 20.6.2.1203 NMAC are not published), and the generic block nm-nmed-hab-mapper (NMED's HAB
#                  advisory map layer, blooms; ingest/nm_transforms.py)
#                  Kentucky: echo_sewer_overflow_events (EPA's overflow tables, KY permits: Kentucky's own system sent
#                  its reports for December 2025 and January 2026 only; Eastern or Central time by the event's
#                  county, data/reference/ky-central-time-counties.json), ky_louisville_msd (Louisville MSD's
#                  Overflow Advisory Level banner, polled: MSD-01 advisories and MSD-02 notices; the state file
#                  data/build/ky-louisville-msd-state.json is the archive) and the generic block ky-dow-hab-viewer
#                  (the Division of Water's HAB Viewer layer, blooms; ingest/ky_transforms.py), ky_dow_swimming_advisories
#                  (the Division's standing swimming advisories page, read as standing advisories; its state file
#                  data/build/ky-dow-swimming-advisories-state.json); SD1's rain rule is in
#                  data/rules.json rain_likely.fallback.by_permit
#                  Hawaii: hi_doh_cwb_events (the Department of Health Clean Water Branch's events endpoint, the newest
#                  500 advisories every run: sewage spill and permit exceedance advisories in the Department's own
#                  window, Brown Water Advisories as rainfall advisories, beach advisories and retest notices; placed
#                  by the names the notices give, per island; no history backfill: the endpoint ignores paging)
#                  Alabama: al_adem_sso (ADEM's SSO report layers: every report filed through AEPACS since 2012, posted
#                  within minutes, with the live map's received time and cause; the last 60 days each hour, the whole
#                  layer every 20 hours) and al_adem_beaches (ADEM and ADPH's coastal beach monitoring layer: an
#                  advisory code other than 11 opens a beach advisory)
#                  Texas: the generic Socrata block tx-tceq-sso-opendata (TCEQ's Sanitary Sewer Overflows table since
#                  2010: dates only, no locations, published in batches months late; read only when its rowsUpdatedAt
#                  moves, if_changed; ingest/tx_transforms.py; operators by data/reference/tx-tceq-permits.json, rebuilt
#                  by scripts/tx_permit_crosswalk.py) and the generic ArcGIS block tx-glo-beach-watch (Texas Beach
#                  Watch's coastal stations: High is the program's advisory, Medium its label)
#                  Utah: the generic ArcGIS blocks ut-deq-environmental-incidents (DEQ's spill hotline log since 1991:
#                  the sewage rows by a title rule, dated to the day of discovery, the public's reports marked;
#                  ingest/ut_transforms.py) and ut-dwq-recreational-advisories (DWQ's map of bloom and E. coli
#                  advisories), and echo_sewer_overflow_events (EPA's overflow tables, UT permits)
#                  Oregon: or_bes_news (Portland Environmental Services' CSO and sewage advisories: the news RSS and
#                  each advisory's page, the City's 48-hour window), or_deq_oers_spills (DEQ's OERS spills 2013 to
#                  March 2025, the sewage rows as a frozen archive: the layer's metadata each run, the rows only when
#                  DEQ edits it), or_oha_beaches (OHA's beach conditions table, a snapshot: ADVISORY and SEWAGE, in
#                  season) and the generic ArcGIS block or-oha-hab-advisories (OHA's bloom advisories and
#                  precautions; ingest/or_transforms.py)
#                  Tennessee: the generic CSV block tn-tdec-events-report (TDEC's Events Report, an APEX table of
#                  every overflow, release and bypass since 2020: dates only, county, city and street, no water; the
#                  session step opens the page first; ingest/tn_transforms.py) and the generic ArcGIS block
#                  tn-tdec-hab-advisory-status (TDEC's HAB advisories, advisory fields only), and
#                  tn_tdec_posted_streams (TDEC's posted-streams PDF: standing water-contact advisories, read daily)
#                  Ohio: oh_neorsd_cso (NEORSD's CSO alerts layers: each outfall's last wet- and dry-weather overflow,
#                  snapshotted hourly into dated records, metered or modelled), oh_akron_cso (Akron's overflow status
#                  layer: status 1 opens, 0 ends at the poll), oh_columbus_overflows (Columbus's overflow events table
#                  since 2002, day precision), oh_bowling_green_cso (Bowling Green's CSO events table), oh_clyde_cso
#                  (Clyde's yearly CSO report tables), oh_lakewood_cso (Lakewood's CSO alerts cards, snapshotted hourly
#                  into dated records; no backfill), oh_willard_cso (Willard's initial and supplemental CSO notices, one
#                  record per overflow; no backfill), oh_epa_spills (Ohio EPA's spills layer, the human sewage, sewage
#                  sludge and waste water rows: supplementary, day precision, no end) and oh_odh_beachguard (ODH BeachGuard's current bacteria and algal-bloom advisories)
#                  Minnesota: mn_mces_spill_notices (the Metropolitan Council's spill pages: the day it responded, its signs as
#                  its window), the generic ArcGIS block mn-wlssd-overflows (Resource Renew's overflow points; ingest/mn_transforms.py)
#                  and echo_sewer_overflow_events (EPA's overflow tables, MN permits: the Bois Forte report)
#                  North Dakota: nd_deq_hab_listings (DEQ's bloom advisories and warnings PDF) and nd_deq_eir_legacy (DEQ's
#                  incident archive 1975-2020, the sewage rows, re-read every 30 days); HazConnect is a bot wall (register)
#                  Missouri: mo_kc_water_news (KC Water's overflow news posts through the site search's RSS feed; the
#                  first two pages each run, `--backfill` for the 2016- archive), mo_msd_alerts (MSD Project Clear's own
#                  overflow alerts and releases through its WordPress API; `--backfill` for 2013-) and mo_dnr_concerns
#                  (DNR's monthly Water Pollution Control concern reports, the sewer overflow concerns with the allegation
#                  filter; each PDF read once), mo_dnr_hab (DNR's public HAB map layer: the waters it shows with a
#                  bloom present or closed, standing advisories dated to the reads); data/outfalls-mo.json is DNR's
#                  outfall layer (scripts/mo_outfall_layer.py)
#                  Kansas: ks_leavenworth_sso (Leavenworth's Sanitary Sewer Overflow Transparency Reports: the index, the
#                  last two years' pages and new overflow pages; `--backfill` for 2020-), ks_kdhe_stream_advisories (KDHE's
#                  news flash feed: stream advisories issued and rescinded; the feed holds about a month) and ks_kdhe_hab
#                  (KDHE's HAB status layer, lakes under a Hazard, Warning or Watch, dated to the polls); Mountain time in
#                  Sherman, Wallace, Greeley and Hamilton counties (pipeline/zones.py kansas_zone)
#                  Arkansas: ar_deq_overflow_incidents (DEQ's Reported Noncompliance Incident Data, an HTML form
#                  search read by start-day window, each window's count checked: every SSO, bypass, upset and
#                  unpermitted discharge since 2025, day precision; ingest/ar_transforms.py), the generic JSON block
#                  ar-deq-hab-advisories (DEQ's bloom advisories with the days posted and lifted) and
#                  ar_adh_swim_beaches (the Department of Health's closed swim beaches, a standing list)
#                  Wisconsin: wi_mmsd_storm_updates (the Milwaukee Metropolitan Sewerage District's Storm Update posts:
#                  the overflows it reports to the DNR, dated by the post, two list pages a run; the DNR publishes none)
#                  and wi_dnr_beach_health (DNR's Beach Health map layer: the advisories and closures in effect, algae
#                  as blooms, dated by the Department's Date of Advisory; state data/build/wi-dnr-beach-health-state.json)
#                  Delaware: de_dnrec_derns (DNREC's DERNS Recent Releases: the sewage and sanitary-wastewater
#                  releases by rule, a few detail pages a run; state data/build/de-dnrec-derns-state.json) and
#                  de_dnrec_recwater (DNREC's beach advisory history on data.delaware.gov and the FirstMap stations)
#                  South Carolina: sc_florence_sso (the City of Florence's sewer overflow notices),
#                  sc_des_advisories (DES's beach station layer, long-term and short-term advisories, and its bloom
#                  delineations and watch table, polled; state data/build/sc-des-advisories-state.json)
#                  Indiana: in_echo_cso_monthly (EPA's discharge monitoring reports: each combined sewer outfall's
#                  monthly events, hours and million gallons, month precision; a compact weekly cache in data/build,
#                  at most 120 requests a run), echo_sewer_overflow_events (EPA's overflow tables, IN permits; Eastern or
#                  Central time by the event's county, data/reference/in-central-time-counties.json) and the generic
#                  ArcGIS block in-idem-cyanobacteria (IDEM's beach samples with IDEM's advisory level; ingest/
#                  in_transforms.py); IDEM's outfall layer is data/outfalls-in.json (scripts/build_in_outfalls.py)
#                  West Virginia: wv_echo_cso_monthly (EPA's monthly DMRs at combined sewer outlets: two permits report flow
#                  at an outlet; month precision; a weekly cache in data/build) and wv_dep_hab_advisories (DEP's algal bloom
#                  advisory map, three layers, poll-dated); outlets from DEP's layer (data/outfalls-wv.json, built by hand with
#                  scripts/build_wv_outfalls.py --fetch)
#                  Louisiana: la_baton_rouge_quarterly (Baton Rouge's consent-decree quarterly reports, Part D collection-
#                  system tables read with pypdf; a report used only when its rows match its own summary; each report once)
#                  Nevada: nv_state_parks_hab (the state parks' HAB Advisory page: Watch, Warning and Danger bloom
#                  advisories at waters in state parks, from the first read that lists them; no sewage feed exists) and
#                  nv_ose_hab_list (the Office of State Epidemiology's statewide bloom list: each advisory from the date
#                  the Office gives; a water with no record listed with its place; one the parks carry shown once)
#                  Oklahoma: ok_nps_chickasaw_bacteria (the National Park Service's E. coli table for Chickasaw
#                  National Recreation Area: a result over the posted threshold is a sample caution, never an
#                  advisory; no sewage feed exists)
#                  Puerto Rico: echo_sewer_overflow_events (EPA's overflow tables, PR permits: PRASA's reports, the only dated record;
#                  Atlantic Standard Time all year) and pr_drna_beaches (DRNA's weekly beach notices, WordPress JSON: the beaches over the
#                  enterococci value, one advisory per run of notices; its state file data/build/pr-drna-beach-notices-state.json)
#                  Colorado: co_cdphe_toxic_algae (CDPHE's toxic algae status sheet: algal-bloom advisories by water)
#                  and co_official_notices (a reviewed set of official notices: CPW's John Martin advisory after the
#                  Pueblo spill, NPS's Blue Mesa release, Barr Lake's red alert; the state publishes no spill list)
#                  Montana: mt_deq_hab_map (DEQ's harmful algal bloom map layer: bloom advisories with DEQ's issue
#                  and lift dates; the state publishes no overflow list)
#                  Wyoming: wy_deq_hcb_bulletins (WDEQ's HCB bulletin topic, RSS: bloom and toxin advisories with the
#                  date issued, ended by a lift bulletin or by a later table that no longer lists them)
#                  Iowa: ia_dnr_focomp (DNR's Field Office Compliance incoming bypass reports of the 105 major municipal
#                  facilities, one page per report, 20 facility and 60 report pages a run; state data/build/ia-dnr-focomp-
#                  state.json), ia_waterloo_sso (the City of Waterloo's SSO and bypass notices) and ia_dnr_news (DNR's
#                  advisory-topic releases on municipal wastewater discharges)
#                  Idaho: id_deq_cyanohab (DEQ's CyanoHAB Risk Data Table with DHW's advisory points: Health Advisory
#                  as the authority's advisory, Watch and Alert as the site's caution; Pacific or Mountain time by
#                  county, 49 CFR 71.9; state data/build/id-deq-cyanohab-state.json); Idaho publishes no sewage report
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
#   make rain-history  each combined sewer operator's rain levels ("possible", "likely") from its own dated
#                  overflow reports against NOAA MRMS daily rain at its outfalls (build/rain_history.py ->
#                  data/build/rain-levels.json; the seed copy is data/rain-levels.json). make build runs it with
#                  --if-older-h 20, so the hourly refresh makes it a daily pass; at most 1500 point-service requests
#                  a run (--budget), the rest continue from the cache on the next run
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
#   make obl-sync  openboatlaunch's changed-since check (ingest/obl_changes.py: its API, key in OBL_API_KEY)
#   make refresh   obl-sync, ingest, provisional outfalls, reaches, build, charts, export (REFRESH_STAGES; stops at
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

.PHONY: setup obl-sync ingest waters-nhd conditions rainfall rain-history rain-thresholds rain-thresholds-radar provisional-outfalls reaches fixtures build charts export refresh tally test

VENV_PY := $(abspath pipeline/.venv/bin/python)
OBL_PY := $(abspath ../openboatlaunch/pipeline/.venv/bin/python)
PYTHON ?= $(if $(wildcard $(VENV_PY)),$(VENV_PY),$(OBL_PY))
PY = cd pipeline && $(PYTHON)
TIMED = sh $(abspath scripts/timed.sh)
# every feed of the ingest loops runs under a wall-clock cap (scripts/timed.sh --cap): past it the feed is stopped,
# logged "(exit 124, stopped at the cap)" and counted as failed, its previous events file kept whole, and the refresh
# goes on. One feed's own cap: FEED_CAP_<name> in the environment (FEED_CAP_ingest_fl_doh_beaches=900; 0 is none);
# a --backfill run has none.
FEED_CAP_S ?= 600
TIMED_FEED = $(TIMED) --cap $(FEED_CAP_S)

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
# Feed cadence (pipeline/cadence.py): a feed whose name starts with the code of a state not in data/rules.json
# live_states (al_adem_sso, tx-glo-beach-watch) runs on a daily pass, not hourly: its records are neither coloured nor
# exported until the state goes live, and the switch in live_states makes it hourly with no other edit. The last good
# run of each is in data/build/feed-cadence.json; FEEDS_ALL=1 runs every feed. A cadence check that fails or
# answers without its "cadence:ok" mark runs every feed (ALL): a feed is never skipped by accident.
CADENCE_DUE = due=" $$(cd pipeline && $(PYTHON) -m cadence due $(1)) "; case "$$due" in *" cadence:ok "*) ;; *) due=" ALL " ;; esac;
CADENCE_GATE = case "$$due" in *" ALL "*|*" $(1) "*) d= ;; *" $(1):daily "*) d=daily ;; \
	  *) echo "== $(1): a state not yet live; on its daily pass (data/build/feed-cadence.json)"; continue ;; esac;
CADENCE_RAN = { [ -z "$$d" ] || (cd pipeline && $(PYTHON) -m cadence ran $(1)) || true; }

setup:
	cd pipeline && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest

ingest:
	@$(call CADENCE_DUE,$(addprefix ingest.,$(INGEST_PRE) $(filter-out $(INGEST_SKIP) $(INGEST_PRE) $(INGEST_SNAPSHOTS),$(INGEST_MODULES)))) \
	for m in $(INGEST_PRE) $(filter-out $(INGEST_SKIP) $(INGEST_PRE) $(INGEST_SNAPSHOTS),$(INGEST_MODULES)); do \
	  $(call CADENCE_GATE,ingest.$$m) \
	  echo "== ingest.$$m"; \
	  (cd pipeline && $(TIMED_FEED) ingest.$$m $(PYTHON) -m ingest.$$m) && $(call CADENCE_RAN,ingest.$$m) || echo "!! ingest.$$m failed (exit $$?)"; \
	done
	@ids=$$(cd pipeline && $(PYTHON) -m ingest.generic --list) || echo "!! ingest.generic --list reported problems (exit $$?)"; \
	$(call CADENCE_DUE,$$(for g in $$ids; do printf 'generic.%s ' "$$g"; done)) \
	for g in $$ids; do \
	  $(call CADENCE_GATE,generic.$$g) \
	  echo "== ingest.generic $$g"; \
	  (cd pipeline && $(TIMED_FEED) generic.$$g $(PYTHON) -m ingest.generic $$g) && $(call CADENCE_RAN,generic.$$g) || echo "!! ingest.generic $$g failed (exit $$?)"; \
	done
	@for m in $(INGEST_SNAPSHOTS); do \
	  echo "== ingest.$$m"; \
	  (cd pipeline && $(TIMED_FEED) ingest.$$m $(PYTHON) -m ingest.$$m) || echo "!! ingest.$$m failed (exit $$?)"; \
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

rain-history:
	$(PY) -m build.rain_history

rain-thresholds:
	$(PY) -m build.rain_thresholds

rain-thresholds-radar:
	$(PY) -m build.rain_thresholds --radar MI GA

obl-sync:           ## openboatlaunch's hourly changed-since check (ingest/obl_changes.py; never fails the run)
	$(PY) -m ingest.obl_changes || echo "!! openboatlaunch changes check failed; the run goes on with the folder as restored"

provisional-outfalls:   ## provisional outfalls from the reports (a failure keeps the previous file)
	$(PY) -m build.provisional_outfalls --geolocate --geo-budget-s 30 --llm --llm-cap-usd 0.25 --llm-budget-s 60 || echo "!! provisional outfalls failed; the previous data/build/outfalls-reported.json stays"

reaches:
	$(PY) -m build.reaches

fixtures:
	$(PY) -m build.fixtures

build: $(if $(filter 1 yes true,$(FIXTURES)),fixtures,)
	cd pipeline && $(TIMED) rain-history $(PYTHON) -m build.rain_history --if-older-h 20 --budget 200 || echo "!! rain history failed; the previous file stays"
	cd pipeline && $(TIMED) rain-thresholds $(PYTHON) -m build.rain_thresholds || echo "!! rain thresholds failed; the previous file stays"
	cd pipeline && $(TIMED) status $(PYTHON) -m build.status $(FIXTURE_FLAG) --live-only

charts:             ## per-water, per-discharger and per-state chart series (after build, before export)
	$(PY) -m build.charts

export:
	$(PY) -m export.build $(FIXTURE_FLAG)

REFRESH_STAGES = obl-sync ingest provisional-outfalls reaches build charts export
refresh:
	@for t in $(REFRESH_STAGES); do \
	  $(TIMED) stage.$$t $(MAKE) --no-print-directory $$t || exit 1; \
	done

tally:              ## docs/source-tally.md from the checklist, the registry, out/ and the water files (after export)
	$(PYTHON) scripts/gen_source_tally.py

TEST_PY = $(shell $(PYTHON) -c "import pytest" >/dev/null 2>&1 && echo $(PYTHON) || echo $(OBL_PY))

test:
	cd pipeline && $(TEST_PY) -m pytest tests -q
