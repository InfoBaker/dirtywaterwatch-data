# Legal forms of operators: one controlled list

Every operator row in `data/dischargers.json` may carry `legal_form`: what kind of body holds the permit. The value
decides how a row is described (a public body is never called privately owned, a company never a public utility) and
groups operators across states. Until now each state build chose its own words; the registry holds 17 values on 191
rows (4,476 rows in all; the rest have none yet). This page proposes one short list, the mapping of every value in use,
and the rows whose name contradicts their value. Nothing is renamed yet: the renaming is its own reviewed change, made
once the open state branches have merged (so `data/dischargers.json` does not conflict).

The check runs from `pipeline/`:

```
python -m ingest.dischargers_schema            # counts per value and its controlled value; warnings; exit 0
python -m ingest.dischargers_schema --strict   # exit 1 when a value is neither on the list nor mapped
```

It warns (never fails) on a value that is neither on the list nor mapped, on a private form whose row name reads as a
public body (the North Carolina review's P2-1: a public water and sewer district filed as a privately owned facility),
and on a public form whose row name reads as a company or association. On today's file it gives no warning.

## The list

| Side | Value | Means |
|---|---|---|
| public | `city` | a city or other municipality's own department or utility (a consolidated city-county included) |
| public | `town` | a town, village, borough or township |
| public | `county` | a county or parish, or its department |
| public | `authority` | a public authority or commission created by law (a water and sewer authority, a utilities authority) |
| public | `special district` | a special-purpose district (sanitary, utility, improvement, municipal utility district, public service district) |
| public | `federal facility` | a federal installation (a military base, a national park, a federal prison) |
| public | `state facility` | a state installation (a state park, university, prison or hospital) |
| public | `tribal` | a tribal government or tribal utility |
| private | `investor-owned utility` | a company whose business is water or sewer service (Aqua, American Water, Corix, a small sewer company) |
| private | `homeowners' association` | a homeowners', property owners' or condominium association |
| private | `mobile-home park` | a mobile-home or manufactured-housing community |
| private | `campground or resort` | a campground, RV park, marina or resort |
| private | `private club` | a country, golf or other private club |
| private | `business or industrial` | any other company: a developer, a restaurant, a plant treating its own sewage |
| private | `institution` | a private school, college, hospital, nursing home, church, camp or retreat |
| private | `facility (permittee not named)` | the permittee is an individual and is never named; the row names the facility |

## Values in use and their mapping

Counts are rows of `data/dischargers.json` on main (2026-11-04), plus the values two other sources allow.

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

## Rows whose name contradicts their value

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

## To decide before the renaming

1. **The list itself.** In particular whether `investor-owned utility` should read `private utility`: a Texas water
   supply corporation (WSC) is a member-owned non-profit, not investor-owned, and 46 of them (all in Texas) are
   among the private candidates. Either keep `investor-owned utility` and add `member-owned utility (cooperative)`,
   or use `private utility` for both.
2. **`municipal` in Georgia** maps to `city`, with the four county departments as overrides; or the eight rows are
   re-read one by one.
3. **JEA** as `authority` (its charter) or `city` (Jacksonville's utility).
4. **The four North Carolina `private company` rows** as `business or industrial`, or one by one from the permit
   documents (one may be a utility).
5. **When to rename**: one reviewed change after the open state branches merge; the check then runs with `--strict`
   in the tests, so every new row uses the list.

The private candidates of every state (`research/<st>/private-utilities-candidates.json`, from
`scripts/private_utilities.py`) already propose values from this list (`legal_form_proposed`), as hints from the names
that the state builder confirms from the permit documents.
