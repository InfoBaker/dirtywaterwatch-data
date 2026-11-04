# Generic ingesters: a feed as a `fetch` block

Most public sewage-overflow and water-advisory feeds sit on a handful of platforms: Socrata open-data tables,
ArcGIS REST layers, RSS or Atom feeds, plain CSV or JSON downloads, and status maps that show only the current
state of each outfall. For a feed on one of these platforms, the ingester is not new code: it is a `fetch` block in
the source's registry record, `data/sources/<id>.yaml`, and a test on a saved response.

```
cd pipeline
python -m ingest.generic <source-id>                       # fetch, map, write data/build/events/<source-id>.json
python -m ingest.generic <source-id> --file saved.json     # the same from a saved response (tests, replays)
python -m ingest.generic <source-id> --file rows.csv --meta view.json --out /tmp/x.json
python -m ingest.generic --check                           # validate every fetch block
python -m ingest.generic --list                            # the blocks make ingest runs
```

The events file has the same shape as every other feed's: one record per source record, in the event record of
the pipeline (`common.event`), with `meta` carrying the run's counts, the credit and the registry ids. `make ingest`
runs every block with `live: true` after the feed modules (so a generic feed can mark its copies of another feed's
records) and before the snapshot steps. A block with `live: false` runs only with `--out`, so it never replaces
another ingester's events file.

The code is `pipeline/ingest/generic/`: `fieldmap.py` (the field map), one reader per platform (`socrata.py`,
`arcgis.py`, `csv_json.py`, `rss.py`, `snapshot.py`), `runner.py` and `transforms.py`.

## What every record keeps

- **Three clocks, kept apart.** The source's own times (`started_at`, `ended_at`, and `source_updated_at`, the
  record's or the dataset's last edit), the publication time (`published_at`, `reported_at`) and our fetch time
  (`fetched_at`). Each is filled only from what the source gives; a time the source does not give stays empty. A
  date without a time of day is `time_precision: day`; a snapshot's times are `poll`.
- **Nothing dropped.** A row that cannot be read becomes a record with `event_type: unknown` and a `parse_error`
  saying why. An end before the start is not used, and the record says so.
- **Only the safe fields.** `safe_fields` lists every field the block may read or keep; everything else is dropped
  before anything is mapped or stored, and on Socrata (`$select`) and ArcGIS (`outFields`) only those fields are
  requested. `raw.row` holds the safe fields as the source gave them, and `raw` notes say how each value was read
  (`_basis`, `_water`, `_source_type`, `_duplicate_basis`, `_first_seen_at`, `_revisions`).
- **Personal data removed.** A safe field whose name looks personal (a reporter, contact, inspector, email or
  phone field) is refused unless `reviewed_fields` gives the reason it is not; emails, phone numbers and names
  after a title or an honorific are removed from the `free_text` fields; `common.strip_personal` runs on every
  `raw`; and the name redactor runs over every record before it is written.
- **History.** Records that leave the source stay in the events file (`raw._missing_from_source_since`), with the
  first time each was seen and, where the block asks, every change of its fields between runs.

## The block

| Key | What it says |
|---|---|
| `platform` | `socrata`, `arcgis`, `csv`, `json`, `rss` (RSS 2.0 or Atom) or `snapshot` |
| `live` | `true` for a block `make ingest` runs |
| endpoint keys | per platform, below |
| `time_zone` | the zone of the source's times that carry none (IANA name) |
| `safe_fields` | every field the block may read or keep |
| `reviewed_fields` | `{field: reason}` for a safe field whose name looks personal but is not |
| `free_text` | the safe fields the scrubbers run on |
| `filter` | `[{field, regex, exclude}]`: rows kept (all rules must hold) |
| `bounds` | `[lon_min, lat_min, lon_max, lat_max]`: a point outside is not used (`raw._coords_rejected`) |
| `record` | the field map, one entry per event field (below) |
| `transform` | one or more `module.function` names: `fn(row, rec, notes, ctx)` after the field map |
| `waters` | `matcher` (`fn(text, rec, row, ctx)`), its options, and `no_water` patterns |
| `dedupe` | `repeats: suffix` (copies kept as `id~2`, `id~3`, `duplicate_of` the first, in `order`) or `first`; `ignore` |
| `post` | `fn(records, ctx)` over all the records of a run (rules across records or sources) |
| `history` | `keep_missing` (default true), `revisions`, `track` (fields whose values are kept as seen) |
| `meta` | added to the events file's meta: `credit`, `license`, `caveat` |

### The field map

Each entry under `record` names an event field and how to read it.

| Form | Reads |
|---|---|
| `FIELD` | the field's text |
| `{field: [A, B]}` | the first with a value (a fallback used is noted in `raw._basis`) |
| `{const: X}` | a constant |
| `{template: "{A\|upper\|slug}-{@started_at\|compact}"}` | a string from fields (`@x` is a record field already read); empty when a field it names is empty, unless `\|default:x` |
| `upper`, `lower`, `regex` + `replace`, `map` + `unmapped` (`keep`, `null` or a value) + `match: regex`, `parse` (`number`, `int`, `text`), `transform` | applied in that order |

Template filters: `clean`, `upper`, `lower`, `slug`, `address` (street words abbreviated, punctuation dropped),
`num` (`672,000.07`), `int`, `compact` (a time as `20260523T0205`, or `20260523` at day precision), `strftime:%Y`,
`default:x`.

Special entries:

- **Times** (`started_at`, `ended_at`, `reported_at`, `published_at`, `source_updated_at`):
  `{field, parse, formats, time, time_formats, precision}`. `parse` is `datetime` (ISO 8601, RFC 2822 and the
  common US forms, or the block's `formats`), `date`, `epoch_ms`, `epoch_s` or `epoch_ms_wallclock` (local
  wall-clock time stored as if it were UTC, common on ArcGIS layers). `time` names a separate time-of-day field.
  `ended_at` may be `{duration: {days, hours, minutes}}`: the start plus the source's duration.
- **`event_type`**: a `map` onto the event types; a value it does not map is `unknown`, with the source's label in
  `raw._source_type`.
- **`status`**: a `map` onto the statuses, and `otherwise: from_end` (ended when the source gives an end, else
  unknown) or a status. An ongoing record never carries an end (the source's is kept in `raw._end_while_ongoing`).
- **`volume`**: `{field, unit (gallons, mg, liters, m3), estimate (estimated or measured), text, bare_number_text}`
  fills `volume_gal`, `volume_text` and `estimate_flag`; ranges and bounds stay text.

Receiving-water text that names no water ("none", "N/A", "ground", "storm drain", "did not reach") is kept as text
and placed on no water. Other text is matched by the block's `waters.matcher` when it has one; otherwise the
status build matches the name.

## Socrata

The Maryland Department of the Environment's statewide overflow table. The whole table is reloaded each time and its
row id is a row number, so the record key is built from the permit, the start and the address.

```yaml
fetch:
  platform: "socrata"
  live: true
  domain: "https://opendata.maryland.gov"
  dataset: "stgj-u72u"
  format: "csv"            # csv: one GET of the whole table; json (the default): SODA pages of $select'ed fields
  metadata: true           # the table's rowsUpdatedAt becomes every record's source_updated_at
  time_zone: "America/New_York"
  safe_fields: [overflow_type, facility_collection_system, npdes_no, start_date, start_time, duration_day,
                duration_hour, duration_minute, overflow_address, zip, owner_name, discharge_volume, overflow_cause,
                receiving_water, county, penalty_id, overflow_latitude, overflow_longitude, id]
  free_text: [overflow_cause, receiving_water]
  record:
    started_at: {field: start_date, time: start_time}
    ended_at: {duration: {days: duration_day, hours: duration_hour, minutes: duration_minute}}
    source_record_id: {template: "{npdes_no|upper|slug|default:none}-{@started_at|compact|default:nodate}-{overflow_address|address|slug|default:no-address}"}
    event_type:
      field: overflow_type
      map: {CSO: cso, SSO: sso, Bypass: bypass, Unauthorized Discharge: sso}
    discharger_name: owner_name
    authority: owner_name
    npdes_permit: {field: npdes_no, upper: true, regex: "^MD\\d{7}$"}
    outfall_name: overflow_address
    waterbody_text: receiving_water
    volume: {field: discharge_volume, bare_number_text: "gallons"}
    source_url: {const: "https://opendata.maryland.gov/dataset/Reported-Sewer-Overflows-New-for-2023-/stgj-u72u"}
  transform: "ingest.generic.transforms.md_mde_record"     # coordinate repairs and the operator
  waters:
    matcher: "ingest.generic.transforms.state_waters"
    state: "MD"
    county_field: county
    no_water: ["^\\s*(nope|duplicate\\b.*)\\s*[.!]*\\s*$"]
  dedupe: {repeats: suffix, order: ["-volume_gal"], ignore: [id]}
  post: "ingest.generic.transforms.md_mde_duplicates"
  history: {keep_missing: true, revisions: true}
  meta:
    credit: "Maryland Department of the Environment, Reported Sewer Overflows (New for 2023), opendata.maryland.gov"
```

Other keys: `where` (a SoQL filter), `order` (`:id`), `page_size` (1000), `max_rows` (200,000).

## ArcGIS REST

Baltimore City's sewer overflow map layer. Its date fields hold local wall-clock time stored as UTC, and its
receiving waters are coded.

```yaml
fetch:
  platform: "arcgis"
  live: true
  url: "https://dpwdata.baltimorecity.gov/pubgis/rest/services/Public/SSO_Points2/MapServer/0"
  order_by: "OBJECTID"
  time_zone: "America/New_York"
  bounds: [-79.5, 37.9, -75.0, 39.8]
  safe_fields: [OBJECTID, SSO_DATE, LOCATION, EST_VOLUME, EST_FLOW, STATUS, REC_WATERS, WATERSHED, START_DATETIME,
                END_DATETIME, RESPONSIBILITY, Latitude, Longitude, SITE_TYPE]
  free_text: [LOCATION]
  record:
    source_record_id: OBJECTID
    started_at: {field: [START_DATETIME, SSO_DATE], parse: epoch_ms_wallclock}
    ended_at: {field: END_DATETIME, parse: epoch_ms_wallclock}
    event_type: {const: sso}
    status: {field: STATUS, upper: true, map: {PROG: ongoing}, otherwise: from_end}
    lat: {field: Latitude, parse: number}
    lon: {field: Longitude, parse: number}
    waterbody_text: {field: REC_WATERS, unmapped: keep, map: {JF: Jones Falls, GWYN: Gwynns Falls, HERR: Herring Run}}
    discharger_id: {field: RESPONSIBILITY, upper: true, unmapped: null, map: {DPW: md-baltimore-city-dpw}}
    outfall_name: LOCATION
    outfall_id: {field: LOCATION, regex: "\\bSSO\\s+Site\\s*#\\s*(\\d+)", replace: "SSO Site #\\1"}
    volume: {field: EST_VOLUME, estimate: estimated, text: "{EST_VOLUME|num} gallons (EST_VOLUME)"}
    authority: {const: "Baltimore City Department of Public Works (Sewer Overflow Map)"}
    source_url: {template: "https://dpwdata.baltimorecity.gov/pubgis/rest/services/Public/SSO_Points2/MapServer/0/query?where=OBJECTID%3D{OBJECTID}&outFields=*&f=json"}
  waters:
    matcher: "ingest.generic.transforms.state_waters"
    state: "MD"
    county: "Baltimore City"
  dedupe: {repeats: first}
  history: {keep_missing: true, track: [STATUS, EST_VOLUME]}
```

Other keys: `where` (`1=1`), `out_fields` (the safe fields by default), `page_size` (1000, paged while the server
says `exceededTransferLimit`), `geometry: true` (points in WGS 84 as the fields `_x` and `_y`), `metadata: true`
(the layer's `editingInfo.lastEditDate` becomes `source_updated_at`).

## CSV download

A county's monthly overflow log published as a CSV file (an illustration; the host is not real).

```yaml
fetch:
  platform: "csv"
  live: true
  url: "https://data.example.gov/sewer/overflows.csv"
  csv: {delimiter: ",", encoding: "utf-8-sig", skip_rows: 0, headers: snake}
  time_zone: "America/Chicago"
  safe_fields: [report_no, date_start, date_end, overflow_type, receiving_stream, est_gallons, cause]
  free_text: [cause, receiving_stream]
  record:
    source_record_id: report_no
    started_at: {field: date_start, formats: ["%m/%d/%Y %H:%M"]}
    ended_at: {field: date_end, formats: ["%m/%d/%Y %H:%M"]}
    event_type: {field: overflow_type, map: {Sanitary Sewer Overflow: sso, Combined Sewer Overflow: cso}}
    waterbody_text: receiving_stream
    volume: {field: est_gallons, estimate: estimated}
    authority: {const: "Example County Utilities"}
    source_url: {const: "https://data.example.gov/sewer/"}
```

## JSON download

A utility's JSON API with offset paging (an illustration).

```yaml
fetch:
  platform: "json"
  live: true
  url: "https://api.example.gov/v1/overflows"
  params: {status: all}
  json:
    records_path: "data.items"
    paging: {param: offset, size_param: limit, size: 500, max_rows: 20000}
  time_zone: "America/Los_Angeles"
  safe_fields: [id, started, minutes, site.name, site.lat, site.lon, water, state]
  record:
    source_record_id: id
    started_at: {field: started}
    ended_at: {duration: {minutes: minutes}}
    status: {field: state, map: {active: ongoing}, otherwise: from_end}
    event_type: {const: sso}
    outfall_name: site.name
    lat: {field: site.lat, parse: number}
    lon: {field: site.lon, parse: number}
    waterbody_text: water
```

`paging: {next: "links.next"}` follows a next-page link instead; `rows_from: properties` reads GeoJSON features.

## RSS and Atom

A health department's advisory feed. Each item's `pubDate` is the publisher's time: it goes to `published_at`, not
to `started_at`. Author fields are never offered (they name people).

```yaml
fetch:
  platform: "rss"
  live: true
  url: "https://health.example.gov/advisories/feed.xml"
  time_zone: "America/Denver"
  safe_fields: [id, title, link, published, updated, summary, categories]
  free_text: [title, summary]
  filter: [{field: title, regex: "sewage|overflow|beach|bloom"}]
  record:
    source_record_id: id
    published_at: published
    source_updated_at: updated
    event_type:
      field: title
      match: regex
      map: {"beach (is )?closed": beach_closure, "advisory": beach_advisory, "bloom|cyanobacteria": hab_advisory}
    status: {field: title, match: regex, map: {"lifted|rescinded|reopen": advisory_lifted}, otherwise: advisory_active}
    advice_text: summary
    source_url: link
```

Each item offers `id`, `title`, `link`, `published`, `updated`, `summary` (HTML removed) and `categories`.

## Snapshot

A status map that shows only what each outfall is doing now (an illustration of the Philadelphia-style layer).
The machine opens an event at the first poll that says active, closes it at the first poll that does not, and keeps
its state in `data/build/generic/<id>-snapshot.json`, the history of every poll seen. All times are the source's
poll times (`time_precision: poll`): the event began at or before its start and ended at or before its end.

```yaml
fetch:
  platform: "snapshot"
  live: true
  rows_from: "arcgis"
  url: "https://services.example.gov/arcgis/rest/services/CSO_Status/FeatureServer/0"
  time_zone: "America/New_York"
  safe_fields: [Name, Status_Message, LastPoll, Latitude, Longitude, Waterbody, Street]
  snapshot:
    unit: Name
    state: Status_Message
    states:
      "currently overflowing": active
      "^overflow in the past": recent
      "^no overflow": clear
      "not currently available": no_data
    poll_time: {field: LastPoll, parse: epoch_ms_wallclock}
    recent_hours: {regex: "past\\s+(\\d+)\\s+hours", default: 72}
    stale_hours: 24
  record:
    event_type: {const: cso}
    outfall_id: Name
    outfall_name: Street
    lat: {field: Latitude, parse: number}
    lon: {field: Longitude, parse: number}
    waterbody_text: {field: Waterbody, map: {D: Delaware River, S: Schuylkill River}}
    advice_text: {const: "Avoid contact with the water near an overflowing outfall and for 72 hours after."}
```

A unit first seen as `recent` had an event that began and ended between polls: it is recorded as ended, with no
start and `raw.occurred_after`, the earliest it can have begun. `no_data` is not an event; an ongoing event becomes
unknown until the unit reports again. A snapshot with fewer than half the units of the last one is treated as a
failed fetch, and the previous records stay.

## Adding a feed

1. Write the block in the source's `data/sources/<id>.yaml`, with `live: false`.
2. Save one response under `pipeline/tests/fixtures/` (small, with no names), and add a test that runs
   `runner.build` on it and checks the records, including that no personal field reaches them.
3. `python -m ingest.generic --check`, then a real fetch with `--out`.
4. Set `live: true`.

## What a block cannot say yet

- HTML lists and PDF tables: there is no reader for them; those feeds keep their own modules.
- Logic across records beyond repeated keys (the same overflow under two owners, a row the source marks as a
  duplicate, another source's copy) needs a `post` function; matching a vanished record to its corrected row is
  not offered.
- Coordinate repairs (swapped or unsigned pairs, degrees and minutes written as decimals) and operator lookups by
  permit need a `transform`.
- Requests that need a session, a token, a form post or a date window in the query.
- One source row that holds several events, and a snapshot whose states are counts rather than messages.
