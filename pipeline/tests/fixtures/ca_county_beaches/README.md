# County beach fixtures

Read Nov. 28, 2026. These contain real public records trimmed to the fields used by the tests; variants are made in the tests.

- `sd_notifications.json`: native responses from San Diego County's public `MainFlow.Home` app, `https://cosdapps.sandiegocounty.gov/sdbeachinfo/screenservices/CoSD_Beach_Water_CW/MainFlow/BlockNotification/ScreenDataSetGetEventsList`, action types 1 and 2. Four of 13 current station actions; the accompanying update is from `HomeBlockNew/DataActionGetLastDateTime`. Zero/unused entity fields and irrelevant rows are omitted. No session cookies, request headers, manifest or app configuration are fixtures.
- `oc_current.html`: semantic HTML transcription of the text and notice link read through the web client at <https://ocbeachinfo.com/>. This is **not a saved DOM**: the Mac could not connect. It tests the observed headings and text; native HTML verification remains required on the runner.
- `oc_closures_2025.txt` and `oc_closures_2026.txt`: trimmed text transcriptions from <https://ocbeachinfo.com/wp-content/uploads/Closure-Chart-2025-for-OCBeachInfo.pdf> and <https://ocbeachinfo.com/wp-content/uploads/Closure-Chart-2026-for-OCBeachInfo.pdf>, read through the web client. They preserve source row/cell order, spill numbers, dates, closure extents, causes, volume revisions and source-estimate footnotes where used. They are **not claimed to be native pypdf output**. Fetching the PDFs and checking native extraction and visual column layout remain runner work; unknown layouts fail without replacing existing history.

Charts describe beach actions. A phase reduction is not a second spill, and its date is not a discharge end. San Diego's generic station descriptions do not establish a current action's cause.
