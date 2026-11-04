# State builder brief (shared by every agent building a state or a structural piece, 2026-11-04)

Read this whole file first. Then the files it names. You get no other context besides your task prompt.

## The two repositories

- **The data repository**, public, `InfoBaker/dirtywaterwatch-data`, cloned at `/home/user/dirtywaterwatch-data`
  (branch `main`). It holds the pipeline (`pipeline/`), the Makefile, the registries (`data/`), the structured
  research (`research/<st>/sources.json`, `dischargers.json`, `profile.json`, `federal-seed.json`) and the
  generated source documents. **This is where you build.** Everything you commit here will be public: no
  personal names, no secrets, no local paths, no working notes that read as internal chatter.
- **The site repository**, private, cloned at `/home/user/dirtywaterwatch`. Read-only for you except where your
  prompt says otherwise. Read there: `docs/plan.md` (§2 status rules, §3 the event record, §4 registries, §5
  pipeline), `docs/collection-checklist.md` (what a state needs before it goes live), `docs/national-approach.md`
  (the design), `docs/national-waters.md` (the water-record rule), `research/<st>/report.md` (the narrative
  research for your state, with the law quoted and the feeds described), `CLAUDE.md` (the owner's standing rules).

## How to work in git

- Make your own worktree of the data repository on your own branch and stay in it:
  `git -C /home/user/dirtywaterwatch-data worktree add /home/user/dww-<name> -b <branch>`; then
  `cd /home/user/dww-<name>`. Never edit `/home/user/dirtywaterwatch-data` itself (other agents share it).
- `make setup` in your worktree creates `pipeline/.venv` (about a minute). `make test` runs the suite; run the
  tests you add with `cd pipeline && .venv/bin/python -m pytest tests/test_<x>.py -q`.
- Commit early and often on your branch with clear messages. **Do not push** and do not touch `main`; the
  coordinator reviews, runs the suite and merges. Do not create pull requests.
- Raw downloads go under `data/raw/<source>/` (git-ignored). Keep fixture samples small and name-free under
  `pipeline/tests/fixtures/`.

## The owner's rules that bind every record (CLAUDE.md; do not relitigate)

- A report is never a safety verdict; nothing reads "safe" or "clean"; grey means no report.
- Cite everything: every record carries its source id, the source's record id, the source's own times, the
  publication time and the fetch time, kept apart; never invent an end or a receipt date; `time_precision`
  honest (`minute`, `hour`, `day`, `month`, `poll`).
- Red is the authority's own window, quoted as theirs; the site's 72-hour caution is the default yellow; a
  month-precision report gets the monthly mark; a report that says the sewage never reached water is kept but
  not placed on a water.
- Every outfall and every reported receiving water must end as a water record or a stated reason.
- Personal data: request only safe fields; `common.strip_personal` on every raw record; the blocklist runs on
  free text; a fixture test proves a known personal field never reaches the records.
- Sewage, beach advisories and algal blooms are separate categories (`event_type` and `category`).

## What a state build produces (the checklist is `docs/collection-checklist.md` in the site repository)

1. **Ingesters** (`pipeline/ingest/<st>_<source>.py`), one per machine-readable feed named in the profile's
   `readiness.first_feed` and the sources it marks `used` or `candidate`: the module docstring states the
   source, the endpoint, the record rules and the privacy rule (read `pipeline/ingest/md_mde_overflows.py`
   for a Socrata table, `md_baltimore_sso.py` for an ArcGIS layer, `va_deq_prep.py` for an API with personal
   fields, `pa_phila_csocast.py` for a status snapshot turned into events, `echo_sewer_overflow_events.py` for
   EPA's tables). Writes `data/build/events/<source-id>.json` in the plan §3 shape through `common.event(...)`.
   A `--file` option reads a saved response so tests need no network. A fixture test per feed.
2. **Registry rows**: `data/sources/<id>.yaml` for every used and candidate source (the shape of
   `data/sources/md-mde-overflows.yaml`); `docs/source-checklist.json` rows for everything considered
   (`scripts/gen_source_checklist.py` and `scripts/registry_rows_from_research.py` build them from
   `research/<st>/sources.json`: read their docstrings); `data/dischargers.json` rows for every permit
   (from `research/<st>/dischargers.json` and `federal-seed.json`, one row per permit, with `short_name`,
   `legal_form`, `towns`, `npdes_permits`, the notification channel and sign-up URL; `scripts/add_federal_operators.py`
   shows the shape).
3. **The register**: `data/notice-channels.json` rows per channel per operator or agency (law, permit,
   voluntary), validated by `cd pipeline && .venv/bin/python -m ingest.notification_pages --validate`; rows
   sorted by (state, id); every CSO permittee named by a row or covered by a statewide row. Once the register is
   split (`--split`), a state's rows are in `data/notice-channels/<st>.json` (the same schema, sorted by id) and
   `--validate` checks every file and the ids across them; add rows to your state's file only.
4. **Rules**: `data/rules.json` `red.by_state.<ST>` (hours or null, clock, basis in public voice, source
   citation) and the state's law entries for the site (the `meta.states` block the export writes: find where
   `MD` is defined and add the state the same way).
5. **Outfalls**: state outfall layers that improve on EPA's rows go into `data/outfalls-<st>.json` in the
   registry row shape (`data/outfalls-mid-atlantic.json`), each row citing its layer; EPA's row for the same
   permit and outfall is kept and marked `superseded_by`. Do not touch `data/outfalls-us.json`.
6. **Waters**: do not build water records yourself. The water batch for the state is a workflow:
   `gh workflow run state-build.yml -f state=XX` (steps `waters ties` by default; `obl-check` first checks the
   state's openboatlaunch extract) runs `ingest.waters_from_nhd --state XX` within a budget and
   `ingest.outfall_waters --state XX`, keeps the NHD answers in the saved raw caches so the next dispatch resumes,
   and opens a pull request `batch/<xx>-<date>` with the changed registry files for review; dispatch it again until
   the pull request's table shows every target with a record or a reason. It shares the hourly refresh's queue,
   which holds one waiting run: dispatch only when no run of either workflow is queued or waiting
   (`gh run list --workflow refresh.yml --status queued`, the same for `state-build.yml`, and `--status pending`),
   wait for your run to finish before the next, and treat a run shown as cancelled before it started as replaced:
   dispatch it again later. Never dispatch two batches at once. `python scripts/state_batch.py plan
   --state XX` prints the commands without running them. List in your final message the receiving-water names your
   feed uses that `data/receiving-waters-national.json` lacks for your state (`research/<st>/receiving-waters-missing.json`).
7. **Do not add the state to `data/rules.json` `live_states`.** The coordinator does that after the checklist.
8. **A short public-voice paragraph** for the state page's "Data and its limits" (what the law requires, what
   each feed gives and does not, what is not published, known problems) in `research/<st>/state-text.md`:
   no file names, no working notes, never "safe" or "clean".

## Private sewer utilities (every state)

Privately owned sewer systems are operators like any other: registry rows, register rows, outfalls and water
records. North Carolina set the pattern (`scripts/add_nc_operators.py`, `research/nc/private-utilities.json`).

1. **Start from the candidates file**, `research/<st>/private-utilities-candidates.json` (NH and VT:
   `research/nh-vt/private-utilities-candidates-<st>.json`), made by `scripts/private_utilities.py` from EPA's
   ICIS-NPDES discharge points: every active individual sewage permit whose permittee is not a public body, with the
   permit, facility, county, city, EPA's owner type and its date, the permit's SIC/NAICS codes, design flow, receiving
   waters as EPA names them, and whether the permit is already in the outfall registry (`in_plant_registry`) or held
   by a row (`registry_row`, `research_row`). `public_by_name` lists permits EPA types private whose name reads as a
   public body (a municipal utility district, a county, a school district), and permits whose permittee reads as both
   a public body and a company: check each against the permit and file it as a public operator when it is one. A public body filed as private is the error to avoid here.
2. **Take the permittee from the state's permit documents** (the permit, its fact sheet, the state's permit search or
   document repository), not from EPA's name, and cite the document. Group the permits of one permittee into one row.
   `legal_form_proposed` is a hint from the names; set `legal_form` from the controlled list (`docs/legal-forms.md`;
   `cd pipeline && python -m ingest.dischargers_schema` warns on anything off the list).
3. **Never an individual's name.** The candidates file already writes "[name removed]" for a permittee that is a
   person (a family's trust or partnership, initials and a surname included) and for both names of a
   single-residence system (`system_kind`), which keeps only its permit and state. When the permit document names a
   person as permittee, the row names the facility and its `legal_form` is `facility (permittee not named)`; when a
   person signs for a body (a chairman, a manager), the body is the permittee. Company names that read like
   surnames (registered companies) are bodies.
4. **The register.** Read the state's law for who carries the notice duty:
   - Where the duty binds every owner or operator of a permitted sewer or treatment works (North Carolina,
     G.S. 143-215.1C), the statewide law rows already cover private operators: say "public or private" in their note,
     and add an operator row only for a private operator's own channel (a web page, an e-mail list).
   - Where the duty binds only public systems (a right-to-know law written for publicly owned works) and private
     operators answer only to their permit (a 24-hour report to the agency, no public notice), add a row for the
     private operators' channel as the permit gives it (`basis_kind` "permit"), with its barrier (`no_web_page`
     when the notice goes to the agency only), so the gap is visible.
5. **Outfalls and waters.** A candidate with `in_plant_registry: false` has no outfall row yet: its outfalls come from
   the state's permit layer or EPA's discharge points, each with a water record or a stated reason. For a
   single-residence system, decide with the coordinator before drawing its point (a point there is a home).
6. **Industrial permits that list sewage treatment** (`system_kind: "industrial permit with a sewage code"`) may treat
   only their own staff's sewage: file them when the permit shows a sanitary outfall to public water.

## Your final message to the coordinator

Under 400 words: the branch name and worktree path; what was built, with record counts from a real fetch;
what the tests cover; the receiving waters without a record; what you could not reach; the owner's decisions.
