"""Plain-function pipeline stages for the Knowledge Lake walking skeleton (Plan 05).

Each stage is a pure function that:
  - Accepts typed inputs (artifact IDs, bytes, etc.)
  - Calls plugins + storage + registry through the established seams
  - Creates a registry artifact node linking to its parent (the lineage chain)
  - Returns the artifact node or processed data for the next stage

Stages in order:
  ingest.py  — download/load raw bytes → raw_document artifact
  parse.py   — parse bytes → parsed_document artifact + ParsedDoc
  chunk.py   — split ParsedDoc → chunk artifacts
  embed.py   — embed chunk texts → vectors
  index.py   — upsert vectors with citation payload into Qdrant
  search.py  — embed query, ANN search → Hits with citation
  run.py     — orchestrates all stages in-process (no Dagster in Plan 05)

No Dagster asset/job definitions here — those come in Plan 06.
"""
