Real public Power BI query evidence, read 2026-11-28 without sign-in.
Endpoint: https://wabi-us-north-central-k-primary-api.analysis.windows.net/public/reports/querydata?synchronous=true
Public report resource key: 180b341d-826b-4829-9bc2-0bf9cc0054c7, model 346.

states.json: first six compressed CSOs rows from the 13:13 UTC researcher read,
retaining the response descriptor/dictionaries and repeat/null encoding.
refreshed.json: single Refreshed.Updated query value from the 13:40 UTC read;
tests the alternate single-value encoding, not used to date events.
active-site.json: one decoded CSOs+CSO_Info row (CSO-223), 13:51 UTC live read.
Tests vary its state/timestamp explicitly to simulate subsequent transitions;
those transitions are synthetic, not claims of a witnessed stop.
No reporter contacts or customer identifiers are in these queried tables.
Public facility_id is the monitored sewer asset identifier, not a customer id.

snapshot.json: all 205 decoded CSOs + CSO_Info rows from the saved live-events.state.json
read of 2026-11-28. Includes both source facility IDs for CSO-403 (11511001,
11511034), each named CSO-403 in facility_name and facility_name_edmr, in the
Muddy Creek sewershed. Tests change statuses/timestamps and remove a row to
simulate transitions and inventory retirement; these changes are not live events.

published-state.json: the four saved events and their open/site entries from
live-events.state.json, without the unrelated quiet-site entries or snapshot.
Tests verify migration keeps those published source_record_id/event_id values.
