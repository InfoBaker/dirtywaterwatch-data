# Legal forms of operators: one controlled list

Every operator row in `data/dischargers.json` may carry `legal_form`: what kind of body holds the permit. The value
decides how a row is described (a public body is never called privately owned, a company never a public utility) and
groups operators across states. Each state build chose its own words (17 values on 95 rows of 4,500 on 2026-11-04);
this page sets one short list, the mapping of every value that was in use, and the rows whose name contradicted their
value. The renaming was applied on 2026-11-04 (branch `eng/registry-hygiene`): every `legal_form` in
`data/dischargers.json` is now on the list, and the tests run the check with `--strict`.

The check runs from `pipeline/`:

```
python -m ingest.dischargers_schema            # counts per value and its controlled value; warnings; exit 0
python -m ingest.dischargers_schema --strict   # exit 1 when a value is neither on the list nor mapped
```

It warns on a value that is neither on the list nor mapped, on a value that is mapped but not on the list (write the
controlled value), on a private form whose row name reads as a public body (a public water and sewer district once filed
as a privately owned facility), and on a public form whose row name reads as a company or association. `--strict` fails
on any value not on the list; on today's file it gives no warning.

## The list

| Side | Value | Means |
|---|---|---|
| public | `city` | a city or other municipality's own department or utility (a consolidated city-county included) |
| public | `town` | a town, village, borough or township |
| public | `county` | a county or parish, or its department |
| public | `authority` | a public authority or commission created by law (a water and sewer authority, a utilities authority) |
| public | `special district` | a special-purpose district (sanitary, utility, improvement, municipal utility district, public service district), or a New Mexico mutual domestic water consumers or sewage works association, a political subdivision under the Sanitary Projects Act (NMSA 1978, Chapter 3, Article 29), and a public school district |
| public | `federal facility` | a federal installation (a military base, a national park, a federal prison) |
| public | `state facility` | a state installation (a state park, university, prison or hospital) |
| public | `tribal` | a tribal government or tribal utility |
| private | `investor-owned utility` | a company whose business is water or sewer service (Aqua, American Water, Corix, a small sewer company) |
| private | `member-owned utility` | a non-profit water or sewer utility owned by its members (a Texas water supply corporation) |
| private | `homeowners' association` | a homeowners', property owners' or condominium association |
| private | `mobile-home park` | a mobile-home or manufactured-housing community |
| private | `campground or resort` | a campground, RV park, marina or resort |
| private | `private club` | a country, golf or other private club |
| private | `business or industrial` | any other company: a developer, a restaurant, a plant treating its own sewage |
| private | `institution` | a private school, college, hospital, nursing home, church, camp or retreat |
| private | `facility (permittee not named)` | the permittee is an individual and is never named; the row names the facility |

## Values that were in use and their mapping

Counts are rows of `data/dischargers.json` on main before the renaming (2026-11-04), plus the values two other sources
allow. The mapping stays in `LEGACY` for the research files and `scripts/add_nc_operators.py`, which writes the
controlled value.

| Value in use | Rows | States | Controlled value | Note |
|---|---|---|---|---|
| `city` | 43 | FL | `city` | |
| `town` | 3 | FL, NC | `town` | |
| `village` | 1 | FL | `town` | the one row is a county's plant (override below) |
| `municipal` | 8 | GA | `city` | four are county departments (overrides below) |
| `municipal utility` | 1 | FL | `city` | the one row, JEA, is an authority (override below) |
| `county` | 1 | NC | `county` | |
| `county department` | 10 | FL | `county` | |
| `authority` | 2 | DC, GA | `authority` | |
| `utility authority` | 2 | FL | `authority` | |
| `special district` | 2 | FL, NC | `special district` | |
| `federal facility` | 3 | FL | `federal facility` | |
| `private utility` | 8 | NC | `investor-owned utility` | |
| `private company` | 4 | NC | `business or industrial` | four companies whose business is not water service |
| `industrial facility` | 2 | NC | `business or industrial` | |
| `owners' association` | 1 | NC | `homeowners' association` | |
| `mobile-home park` | 3 | NC | `mobile-home park` | |
| `private club` | 1 | NC | `private club` | |
| `facility (permittee not named)` | 0 | (NC script) | `facility (permittee not named)` | allowed by `scripts/add_nc_operators.py` |
| `district` | 0 | (research) | `special district` | used in a `research/<st>/dischargers.json` row |
| `borough`, `township` | 0 | | `town` | mapped ahead of Pennsylvania and New Jersey rows |

## Rows whose name contradicted their value (set one by one in the renaming)

| Row | Value | Controlled value | Why |
|---|---|---|---|
| `ga-cobb-county` | `municipal` | `county` | Cobb County Water System is a county department |
| `ga-dekalb-dwm` | `municipal` | `county` | DeKalb County Department of Watershed Management |
| `ga-fulton-county` | `municipal` | `county` | Fulton County Department of Public Works |
| `ga-gwinnett-county` | `municipal` | `county` | Gwinnett County Department of Water Resources |
| `ga-augusta-utilities` | `municipal` | `city` | Augusta-Richmond County is a consolidated city-county |
| `ga-columbus-water-works` | `municipal` | `city` | a board of the consolidated government of Columbus |
| `fl-jea` | `municipal utility` | `authority` | JEA is an independent authority of the City of Jacksonville |
| `fl-fl0039829` | `village` | `county` | Lee County's plant; "Fiesta Village" is the plant's name |

## The renaming (2026-11-04)

The calls of the private-utilities review (2026-11-04): keep `investor-owned utility` and add `member-owned utility`
for Texas water supply corporations; Georgia `municipal` to `city` with the four county departments as `county`; JEA
`authority`; the four North Carolina `private company` rows `business or industrial` by default (a permit document may
still show one runs a utility service for others: then it is set by hand). 37 rows changed; nothing else in them.

| Controlled value | Rows before | Rows after |
|---|---:|---:|
| `city` | 43 | 47 |
| `town` | 3 | 3 |
| `county` | 1 | 16 |
| `authority` | 2 | 5 |
| `special district` | 2 | 2 |
| `federal facility` | 3 | 3 |
| `investor-owned utility` | 0 | 8 |
| `member-owned utility` | 0 | 0 |
| `business or industrial` | 0 | 6 |
| `homeowners' association` | 0 | 1 |
| `mobile-home park` | 3 | 3 |
| `private club` | 1 | 1 |
| values not on the list | 37 | 0 |

No Texas row is in the registry yet; the 47 Texas candidates that name a water supply corporation propose
`member-owned utility`.

The private candidates of every state (`research/<st>/private-utilities-candidates.json`, from
`scripts/private_utilities.py`) already propose values from this list (`legal_form_proposed`), as hints from the names
that the state builder confirms from the permit documents.
