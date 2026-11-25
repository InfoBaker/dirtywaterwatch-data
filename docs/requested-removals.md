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

Export registers source identities and removed field values from current records, carried history and status. It applies requests to the entire publication tree, including individual events, compact indexes, waters, dischargers, outfalls, CSV downloads, chart files, assessments, feed metadata and other payloads. A final check searches only the explicit requests. A remaining match removes its containing record, removes copies/references of that event throughout the outputs, and warns with the file name and request ID only. A standalone removed payload is replaced by JSON null (or an empty non-JSON file) so uploads overwrite any older object at that key. With an empty list, both passes return immediately without traversing publication files.

Removed event IDs also receive null event files when they are present only in history or no longer in local state. This overwrites old remote event objects even though export rebuilds its current event directory. A warning masks requested text if it appears inside the file name itself.

Collection remains source-specific. Explicit request field selections (`outFields`, `responseFields`, Socrata `$select`, WordPress `_fields`, generic `safe_fields`) have not been widened. Expanding those selections needs a separate source change. Receiving-water validation, malformed-record checks, jurisdiction filters, source-access restrictions and map-placement accuracy checks remain independent of removal requests.
