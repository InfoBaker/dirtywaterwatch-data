# Requested removals

Public records keep the names, contact details, address numbers, narrative text and coordinates their sources publish. The former name blocklist is retired; refreshes neither read nor apply it. Secret masking and the protections for infrastructure accounts and machine identity remain active. Previously scrubbed history cannot recover missing text until the source is read again.

The sole public-record removal service is the private R2 object `state/removal-list.json` in the data bucket. Refresh restores it to ignored `data/private/removal-list.json` before collection. An absent object means an empty list. A transfer failure or malformed list stops publication. The list is separate from the build/history archives and is never uploaded under `current/`, included in dataset releases, printed, or committed.

The JSON root is an array. Each entry contains:

| Key | Meaning |
| --- | --- |
| `id` | Unique administrative identifier, restricted to letters, digits, `_` and `-`. |
| `added` | Date the request was added. |
| `kind` | `text`, `field`, or `record`. |
| `match` | Literal text for `text`; a dotted field path or bare field key for `field`; an event identifier or literal source text for `record`. |
| `scope` | Optional `source_id` and/or `event_id`; both must agree when both are given. |
| `replacement` | Optional literal replacement, default `[removed on request]`. |
| `case_sensitive` | Optional boolean; matching is case insensitive by default. |

There are no real requests or sample personal details in this document. Start an unused list with `[]`. A field request removes that field; its text is also removed from copies derived from the field. A record request removes the record and its event references. Literal text matches do not interpret regular expressions. A scope does not affect a known different source or event. A derived payload without identifying provenance is treated conservatively so copied text cannot escape the request.

Use the existing S3 environment configured by `scripts/r2-s3-keys.sh` and the guarded route in `scripts/wrangler_redact.py`. Do not display that environment or put entry text in command arguments, workflow logs or shell history. Keep the input file outside the public checkout, with mode 0600. Operations are:

```
python3 -I scripts/removal_list.py add --file /private/path/request.json
python3 -I scripts/removal_list.py list
python3 -I scripts/removal_list.py remove REQUEST_ID
```

`add` reads a single entry (stdin is also supported); duplicate IDs and invalid entries are rejected. `list` prints IDs only. `remove` requires an existing ID. Each maintenance operation reads the current object; mutations validate and upload the replacement through the S3 route. Serialize maintenance operations: the object is a single administrative list, not a concurrent database. Refresh reads it but never writes it back, so an old run cannot overwrite a maintenance change. A successful change takes effect on the next refresh; it does not immediately rewrite the live site.

A registration pass learns identities and removed field values from publication inputs before any value is filtered. Status, reaches, charts and export share that policy: ingest outputs (including carried history), water/operator/outfall registries, reference data and enrichment are filtered before summaries, counts, traces, CSVs or filenames are built. Source files remain intact. Status built with requests is rebuilt before export, including the first export after the last request is removed. Cached derived rows with withdrawn event provenance are discarded.

Text requests that affect identifiers receive deterministic opaque replacement IDs. References and filenames use the same mapping. Historical ingestion normalization is kept separately for identity only, so retaining more source text cannot duplicate an old record or evade a request for its old ID.

Export applies requests again to all decoded payloads, including JSON, GeoJSON and CSV, then checks content, derived fields and filenames as a backstop. A residual match withdraws its containing record and references; a residual that cannot be removed stops publication. Warnings contain only masked filenames and request IDs. A removed event file is absent, including from the dataset archive. Other standalone payloads can be emptied to overwrite a former object.

Old event filenames and replaced paths are recorded in ignored, mode-0600 `data/private/publication-deletions.json`. Before upload, `scripts/publication_deletions.py` deletes those `current/` object keys through the guarded R2 route without printing keys or provider output; failure stops publication. The manifest is retained for retries and never enters an export or release. The workflow also requires retirement before saving the export archive. The former `export-blocked.json` marker is deleted after restore and is no longer a publication gate.

Each source YAML declares `raw_fields.reporter_contact` and `raw_fields.customer_identifier` as lists of exact raw keys. Export carries them in `sources.json`, both on registry entries and combined for feeds spanning multiple registry entries. These fields remain in downloads; the site uses the declaration to omit them from Record details. `raw_fields.description` documents narrative keys without suppressing them. DC Water declares `PremiseNo` as a customer identifier and `Description` as a description. Other lists remain empty until that reader is widened and its source keys identified. The generic fieldmap privacy gate is retired: ArcGIS and Socrata request all fields and source attributes are retained, including nested values. The internal Houston ID hint still requires parser validation.

Expanded readers include DC Water, CT archives, Baltimore, Michigan and South Carolina MiEnviro lists, Michigan beaches, North Carolina sewage and bloom layers, Oregon OERS, Washington spills, California FHAB and Beach Watch, Florida PNP and bloom sampling, Missouri HAB and South Carolina advisory layers. Source selection, malformed-record checks, jurisdiction filters, access restrictions and map-placement validity checks remain independent of removal requests. Infrastructure and secret protections remain active.
