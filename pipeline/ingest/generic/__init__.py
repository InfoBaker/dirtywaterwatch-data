"""Generic ingesters by platform (docs/generic-ingesters.md): a feed on Socrata, ArcGIS REST, RSS or Atom, a plain
CSV or JSON download, or a status snapshot is a `fetch` block in data/sources/<id>.yaml and a fixture test, not a
module. Not a feed itself: run `python -m ingest.generic <source-id>`."""
