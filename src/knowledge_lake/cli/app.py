"""Knowledge Lake CLI — Typer application entry point.

Entry point: klake = "knowledge_lake.cli.app:app"

Commands:
  version     — print package version
  ingest-url  — download a URL and ingest as a raw_document artifact
  parse       — parse a raw_document artifact into a parsed_document artifact
  clean       — clean a parsed_document artifact (boilerplate removal, dedup)
  chunk       — chunk a parsed_document artifact into chunk artifacts
  enrich      — enrich a cleaned_document artifact with LLM-judged metadata
  search      — embed a query and return cited, filterable search results
  reindex     — zero-downtime reindex of a Qdrant alias (INDEX-02)
  lineage     — print ancestry tree (or JSON) for a given artifact ID
  demo        — run the full spike end-to-end (ingest → search → lineage)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import typer

import knowledge_lake

app = typer.Typer(
    name="klake",
    help="Knowledge Lake CLI — manage domain resources and AI-ready pipelines.",
    add_completion=False,
)


@app.command(name="version")
def cmd_version(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show verbose version info."
    ),
) -> None:
    """Print the package version and exit."""
    v = knowledge_lake.__version__
    if verbose:
        typer.echo(f"knowledge-lake {v}")
    else:
        typer.echo(v)


@app.command(name="status", hidden=True)
def cmd_status() -> None:
    """(Internal) reserved — will be wired in later plans."""
    typer.echo("ok")


@app.command(name="add-source")
def cmd_add_source(
    url: str = typer.Argument(..., help="https:// URL of the source to register."),
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Human-readable source name (defaults to URL hostname)."
    ),
    domain: Optional[str] = typer.Option(
        None, "--domain", "-d", help="Domain classification (e.g. 'healthcare', 'legal')."
    ),
    license_type: str = typer.Option(
        "unknown", "--license", "-l", help="SPDX license identifier."
    ),
) -> None:
    """Register a source URL with optional domain classification.

    URL-first dedup: re-registering the same URL is a silent no-op returning
    the existing source_id.
    """
    from knowledge_lake.pipeline.ingest import register_source

    effective_name = name or (urlparse(url).hostname or url)
    try:
        result = register_source(
            url=url,
            name=effective_name,
            domain=domain,
            license_type=license_type,
        )
        if result["is_new"]:
            typer.echo(f"Registered new source:")
        else:
            typer.echo(f"Source already exists (dedup hit):")
        typer.echo(f"  source_id:      {result['source_id']}")
        typer.echo(f"  name:           {result['name']}")
        typer.echo(f"  url:            {result['url']}")
        typer.echo(f"  normalized_url: {result['normalized_url']}")
        if result.get("domain"):
            typer.echo(f"  domain:         {result['domain']}")
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command(name="upload")
def cmd_upload(
    file_path: str = typer.Argument(..., help="Path to the local file to upload."),
    source_name: Optional[str] = typer.Option(
        None, "--source", "-s", help="Human-readable source name."
    ),
    license_type: str = typer.Option(
        "unknown", "--license", "-l", help="SPDX license identifier."
    ),
) -> None:
    """Upload a local file into the raw zone with provenance metadata.

    Hash-second dedup: re-uploading identical content is a silent no-op
    returning the existing artifact_id.
    """
    from knowledge_lake.pipeline.ingest import ingest_file

    effective_name = source_name or Path(file_path).stem
    try:
        result = ingest_file(
            path=file_path,
            source_name=effective_name,
            license_type=license_type,
        )
        typer.echo(f"Uploaded:")
        typer.echo(f"  source_id:    {result['source_id']}")
        typer.echo(f"  artifact_id:  {result['artifact_id']}")
        typer.echo(f"  storage_uri:  {result['storage_uri']}")
        typer.echo(f"  content_hash: {result['content_hash']}")
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command(name="discover")
def cmd_discover(
    query: str = typer.Argument(..., help="Natural-language search query for source discovery."),
    limit: int = typer.Option(
        20, "--limit", "-l", help="Maximum number of results (1–100).", min=1, max=100
    ),
) -> None:
    """Discover candidate sources via meta-search and auto-register them.

    Each result URL is SSRF-validated and URL-deduped before registration.
    Discovered sources have source_type='discovered' with minimal metadata
    (URL + title only, D-09).
    """
    from knowledge_lake.pipeline.discover import discover_sources

    try:
        results = discover_sources(query=query, limit=limit)
    except (RuntimeError, LookupError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    registered = [r for r in results if r["status"] == "registered"]
    existing = [r for r in results if r["status"] == "existing"]
    skipped = [r for r in results if r["status"] == "skipped_ssrf"]

    typer.echo(f"Discovery: {len(results)} results, "
               f"{len(registered)} registered, "
               f"{len(existing)} existing, "
               f"{len(skipped)} skipped (SSRF)")

    for r in results:
        status_marker = {
            "registered": "+",
            "existing": "=",
            "skipped_ssrf": "X",
        }.get(r["status"], "?")
        sid = r["source_id"] or "n/a"
        typer.echo(f"  [{status_marker}] {sid} {r['url']}")


@app.command(name="parse")
def cmd_parse(
    raw_artifact_id: str = typer.Argument(..., help="ID of the raw_document artifact to parse."),
    source_id: str = typer.Argument(..., help="Source ID that owns the raw artifact."),
    mime_type: str = typer.Option(
        "application/pdf", "--mime", "-m", help="MIME type of the raw document."
    ),
) -> None:
    """Parse a raw_document artifact into a parsed_document artifact.

    Runs the parser fallback chain (Docling → JSON/XML → Unstructured → Tika) and
    records the quality score and parser used in the registry.  Prints artifact_id,
    quality_score, and parser_used on success.
    """
    from knowledge_lake.pipeline.parse import parse

    try:
        result, _parsed_doc = parse(raw_artifact_id, source_id, mime_type=mime_type)
        typer.echo(f"Parsed:")
        typer.echo(f"  artifact_id:   {result['artifact_id']}")
        typer.echo(f"  quality_score: {result.get('quality_score', 'n/a')}")
        typer.echo(f"  parser_used:   {result.get('parser_used', 'n/a')}")
        typer.echo(f"  content_hash:  {result.get('content_hash', 'n/a')}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command(name="clean")
def cmd_clean(
    parsed_artifact_id: str = typer.Argument(
        ..., help="ID of the parsed_document artifact to clean."
    ),
    source_id: str = typer.Argument(..., help="Source ID that owns the parsed artifact."),
) -> None:
    """Clean a parsed_document artifact: remove boilerplate, detect language, near-dup flag.

    Writes a cleaned_document artifact to the registry and silver zone.
    Prints artifact_id, language, and dedup_status on success.
    """
    from knowledge_lake.pipeline.clean import clean

    try:
        result = clean(parsed_artifact_id, source_id)
        typer.echo(f"Cleaned:")
        typer.echo(f"  artifact_id:   {result['artifact_id']}")
        typer.echo(f"  language:      {result['language']}")
        typer.echo(f"  dedup_status:  {result['dedup_status']}")
        typer.echo(f"  content_hash:  {result['content_hash']}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command(name="chunk")
def cmd_chunk(
    parsed_artifact_id: str = typer.Argument(
        ..., help="ID of the parsed_document artifact to chunk."
    ),
    source_id: str = typer.Argument(..., help="Source ID that owns the parsed artifact."),
) -> None:
    """Chunk a parsed_document artifact into token-aware chunk artifacts.

    Note: In production usage the full pipeline (parse → clean → chunk) is orchestrated
    by Dagster assets which pass ParsedDoc in-memory across stages.  This CLI command
    is a convenience wrapper for manual testing and debugging — it fetches the parsed
    text from the silver zone and reconstructs a minimal ParsedDoc with no section
    structure (full text as one section).

    For structured, section-aware chunking use the Dagster pipeline or klake ingest-url.
    Prints chunk_count and first chunk_id on success.
    """
    from knowledge_lake.config.settings import get_settings
    from knowledge_lake.pipeline.chunk import chunk
    from knowledge_lake.plugins.protocols import ParsedDoc
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry import repo as registry_repo
    from knowledge_lake.storage.s3 import StorageBackend

    s = get_settings()
    storage = StorageBackend(s.storage)

    try:
        # Fetch the parsed artifact metadata to get the storage URI
        with get_session() as session:
            parsed_artifact = registry_repo.get_artifact(session, parsed_artifact_id)
            if parsed_artifact is None:
                raise ValueError(f"Parsed artifact {parsed_artifact_id!r} not found in registry")
            storage_uri = parsed_artifact.storage_uri
            if not storage_uri:
                raise ValueError(
                    f"Parsed artifact {parsed_artifact_id!r} has no storage_uri"
                )

        # Extract S3 key from URI — use shared helper to raise a descriptive
        # ValueError on malformed URIs instead of an unhandled IndexError.
        from knowledge_lake.pipeline.utils import uri_to_key
        key = uri_to_key(storage_uri)
        raw_bytes = storage.get_object(key)
        parsed_text = raw_bytes.decode("utf-8")

        # Reconstruct a minimal ParsedDoc with no section structure
        # Full text treated as one section — production Dagster pipeline passes ParsedDoc in-memory
        doc = ParsedDoc(text=parsed_text, sections=[])

        result = chunk(parsed_artifact_id, source_id, doc)
        typer.echo(f"Chunked:")
        typer.echo(f"  chunk_count:  {len(result)}")
        if result:
            typer.echo(f"  first_chunk:  {result[0]['artifact_id']}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command(name="enrich")
def cmd_enrich(
    cleaned_artifact_id: str = typer.Argument(
        ..., help="ID of the cleaned_document artifact to enrich."
    ),
    source_id: str = typer.Argument(..., help="Source ID that owns the cleaned artifact."),
) -> None:
    """Enrich a cleaned_document artifact with LLM-judged metadata.

    Runs deterministic (non-LLM) extraction first, then a single cached,
    budget-capped LiteLLM call producing summary/document_type/organization/
    jurisdiction/keywords/entities/quality_score. Prints status, artifact_id,
    quality_score, and cached on success.
    """
    from knowledge_lake.pipeline.enrich import enrich_document
    from knowledge_lake.plugins.protocols import ParsedDoc
    from knowledge_lake.registry.db import get_session
    from knowledge_lake.registry import repo as registry_repo

    try:
        # Reconstruct a minimal ParsedDoc from the cleaned artifact's parent
        # parsed_document artifact's stored metadata (which carries a "title"
        # key persisted by pipeline.parse.parse()) so the deterministic title
        # is not silently dropped to "" on this entry point (CR-01) — mirrors
        # the parent-artifact-fetch pattern already used by cmd_chunk.
        with get_session() as session:
            cleaned_artifact = registry_repo.get_artifact(session, cleaned_artifact_id)
            if cleaned_artifact is None:
                raise ValueError(f"Cleaned artifact {cleaned_artifact_id!r} not found in registry")
            parsed_artifact = (
                registry_repo.get_artifact(session, cleaned_artifact.parent_artifact_id)
                if cleaned_artifact.parent_artifact_id
                else None
            )
            parsed_metadata = (parsed_artifact.metadata_ if parsed_artifact else None) or {}

        parsed_doc = ParsedDoc(text="", sections=[], metadata=parsed_metadata)
        result = enrich_document(cleaned_artifact_id, source_id, parsed_doc=parsed_doc)
        typer.echo(f"Enriched:")
        typer.echo(f"  status:        {result['status']}")
        typer.echo(f"  artifact_id:   {result.get('artifact_id')}")
        typer.echo(f"  quality_score: {result.get('quality_score')}")
        typer.echo(f"  cached:        {result.get('cached', False)}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command(name="curate")
def cmd_curate(
    cleaned_artifact_id: str = typer.Argument(
        ..., help="ID of the cleaned_document artifact to curate."
    ),
    source_id: str = typer.Argument(..., help="Source ID that owns the cleaned artifact."),
) -> None:
    """Run DataTrove-style quality filters on a cleaned_document artifact (CURATE-01..03).

    Records per-heuristic filter pass/fail in the curated_document artifact's metadata,
    computes a composite quality score (parse + enrich + curation), and prints the result.
    Run `klake dedupe` separately to update dedup_status after curation.
    """
    from knowledge_lake.pipeline.curate import curate_document

    try:
        result = curate_document(cleaned_artifact_id, source_id)
        typer.echo("Curated:")
        typer.echo(f"  status:        {result['status']}")
        typer.echo(f"  artifact_id:   {result.get('artifact_id')}")
        typer.echo(f"  quality_score: {result.get('quality_score')}")
        typer.echo(f"  cached:        {result.get('cached', False)}")
        typer.echo(f"  dedup_status:  {result.get('dedup_status', 'not_yet_computed')}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command(name="dedupe")
def cmd_dedupe() -> None:
    """Run corpus-wide MinHash deduplication over all cleaned_document artifacts (CURATE-02).

    Builds ONE MinHash LSH index over the entire corpus in a single pass and
    updates each curated_document artifact's dedup_status to 'near_dup' or 'unique'.
    This is the authoritative batch dedup replacing Phase 3's transient per-call scan.
    """
    from knowledge_lake.pipeline.curate import batch_dedup_corpus

    try:
        summary = batch_dedup_corpus()
        typer.echo("Deduplication complete:")
        typer.echo(f"  total:                {summary['total']}")
        typer.echo(f"  unique:               {summary['unique']}")
        typer.echo(f"  near_dup:             {summary['near_dup']}")
        typer.echo(f"  skipped_no_curation:  {summary['skipped_no_curation']}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


class DatasetKind(str):
    """Dataset kind enum for the generate-dataset command."""

    QA = "qa"
    INSTRUCTION = "instruction"


@app.command(name="generate-dataset")
def cmd_generate_dataset(
    kind: str = typer.Argument(
        ...,
        help="Dataset kind to generate: 'qa' (chunk → Q&A pair via eval_model) or "
             "'instruction' (enriched_document → instruction pair via strong_model).",
    ),
    source_artifact_id: str = typer.Argument(
        ...,
        help="ID of the source artifact: chunk artifact ID for 'qa', "
             "enriched_document artifact ID for 'instruction'.",
    ),
    dataset_name: str = typer.Option(
        ...,
        "--dataset-name",
        "-d",
        help="Name of the dataset to accumulate this example into (get-or-create).",
    ),
) -> None:
    """Generate a dataset example from a chunk (qa) or enriched document (instruction).

    qa:          Generates a citation-grounded Q&A/RAG-eval pair from a chunk artifact
                 via the eval_model task alias (DATA-01).
    instruction: Generates an instruction-tuning pair from an enriched_document artifact
                 via the strong_model task alias (DATA-02).

    Every example records lineage back to its source artifact (DATA-03).
    Re-running for the same source artifact + prompt_version is a no-op (cached).
    """
    from knowledge_lake.pipeline.datasets import (
        generate_instruction_example,
        generate_qa_example,
    )

    if kind not in ("qa", "instruction"):
        typer.echo(f"Error: kind must be 'qa' or 'instruction', got {kind!r}", err=True)
        raise typer.Exit(code=1)

    try:
        if kind == "qa":
            result = generate_qa_example(source_artifact_id, dataset_name)
        else:
            result = generate_instruction_example(source_artifact_id, dataset_name)

        typer.echo(f"Dataset example generated:")
        typer.echo(f"  status:      {result['status']}")
        typer.echo(f"  example_id:  {result.get('example_id')}")
        typer.echo(f"  dataset_id:  {result.get('dataset_id')}")
        typer.echo(f"  cost_usd:    {result.get('cost_usd')}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command(name="crawl")
def cmd_crawl(
    url: str = typer.Argument(..., help="https:// seed URL to crawl."),
    crawler: Optional[str] = typer.Option(
        None,
        "--crawler",
        "-c",
        help="Override crawler adapter (default: settings.crawler). Must be a registered crawler.",
    ),
    max_pages: Optional[int] = typer.Option(
        None,
        "--max-pages",
        "-m",
        help="Maximum number of pages to crawl (1–10000).",
        min=1,
        max=10000,
    ),
) -> None:
    """Crawl a public site into the lake: raw HTML + bronze markdown per page.

    Creates a crawl job, fetches pages with rate limiting and robots.txt respect,
    and writes two artifacts per page (raw HTML + bronze markdown) with full lineage.
    Resume-safe: re-running fetches only pending URLs.
    """
    import asyncio
    from knowledge_lake.pipeline.crawl import crawl_source

    try:
        result = asyncio.run(crawl_source(
            url,
            crawler=crawler,
            max_pages=max_pages,
        ))
        typer.echo(f"Crawl complete:")
        typer.echo(f"  job_id:              {result['job_id']}")
        typer.echo(f"  source_id:           {result['source_id']}")
        typer.echo(f"  crawler:             {result['crawler']}")
        typer.echo(f"  pages_complete:      {result['pages_complete']}")
        typer.echo(f"  pages_robots_blocked: {result['pages_robots_blocked']}")
        typer.echo(f"  pages_failed:        {result['pages_failed']}")
        typer.echo(f"  pages_total:         {result['pages_total']}")
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command(name="ingest-url")
def cmd_ingest_url(
    url: str = typer.Argument(..., help="https:// URL to ingest (SSRF-checked)."),
    source_name: Optional[str] = typer.Option(
        None, "--source", "-s", help="Human-readable source name."
    ),
    mime_type: str = typer.Option(
        "application/pdf", "--mime", "-m", help="MIME type of the document."
    ),
    collection: str = typer.Option(
        "klake_chunks", "--collection", "-c", help="Qdrant collection to index into."
    ),
) -> None:
    """Download a URL, ingest, parse, chunk, embed, and index into Qdrant.

    Prints source_id, artifact IDs, and chunk count on success.
    """
    from knowledge_lake.pipeline.run import run_document

    effective_name = source_name or url.split("/")[-1] or "Web Source"
    try:
        result = run_document(
            url=url,
            source_name=effective_name,
            collection=collection,
            mime_type=mime_type,
        )
        typer.echo(f"Ingested: {result['chunk_count']} chunks indexed")
        typer.echo(f"  source_id:          {result['source_id']}")
        typer.echo(f"  raw_artifact_id:    {result['raw_artifact_id']}")
        typer.echo(f"  parsed_artifact_id: {result['parsed_artifact_id']}")
        typer.echo(f"  collection:         {result['collection']}")
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command(name="search")
def cmd_search(
    query: str = typer.Argument(..., help="Natural-language search query."),
    collection: str = typer.Option(
        "klake_chunks", "--collection", "-c", help="Qdrant collection to search."
    ),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Maximum number of results."),
    domain: Optional[str] = typer.Option(
        None, "--domain", help="Filter results to this domain."
    ),
    document_type: Optional[str] = typer.Option(
        None, "--document-type", help="Filter results to this document_type."
    ),
    min_quality_score: Optional[float] = typer.Option(
        None, "--min-quality-score", help="Filter results to quality_score >= this value."
    ),
) -> None:
    """Embed a query and return the top-K matching chunks with citation.

    Each result shows score, section, page, and a text snippet.
    """
    from knowledge_lake.pipeline.search import search

    hits = search(
        query,
        collection=collection,
        top_k=top_k,
        domain=domain,
        document_type=document_type,
        min_quality_score=min_quality_score,
    )

    if not hits:
        typer.echo(f"No results for query: {query!r}")
        return

    typer.echo(f"Results for: {query!r}")
    typer.echo(f"Collection: {collection}")
    typer.echo()
    for i, hit in enumerate(hits, 1):
        payload = hit.payload
        typer.echo(f"  [{i}] score={hit.score:.4f}")
        typer.echo(f"      document:     {payload.get('document', '?')}")
        typer.echo(f"      section:      {payload.get('section_path', '?')}")
        typer.echo(f"      page:         {payload.get('page', '?')}")
        typer.echo(f"      chunk_id:     {payload.get('chunk_id', hit.id)}")
        typer.echo(f"      domain:       {payload.get('domain', '?')}")
        typer.echo(f"      document_type:{payload.get('document_type', '?')}")
        typer.echo(f"      quality_score:{payload.get('quality_score', '?')}")
        text_snippet = (payload.get("text") or "")[:120].replace("\n", " ")
        if text_snippet:
            typer.echo(f"      text:         {text_snippet!r}")
        typer.echo()


@app.command(name="reindex")
def cmd_reindex(
    collection: str = typer.Option(
        "klake_chunks", "--collection", "-c", help="Qdrant alias to reindex."
    ),
) -> None:
    """Reindex a Qdrant alias with zero search downtime (INDEX-02).

    Creates the next versioned physical collection, copies all existing points
    into it, then atomically repoints the alias. The prior physical collection
    is retained (never auto-dropped).
    """
    from knowledge_lake.pipeline.index import reindex_collection

    try:
        result = reindex_collection(collection)
        typer.echo(f"Reindexed: {result['collection']}")
        typer.echo(f"  new_physical: {result['new_physical']}")
        typer.echo(f"  old_physical: {result.get('old_physical')}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command(name="lineage")
def cmd_lineage(
    artifact_id: str = typer.Argument(
        ...,
        help="Artifact ID or unambiguous prefix to trace (e.g. 'chk_019f...' or 'chk_019f').",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Output machine-readable JSON instead of the tree."
    ),
) -> None:
    """Print the full lineage ancestry of an artifact.

    Walks parent_artifact_id via recursive CTE from the given artifact back to
    its source.  Default output is a human-readable tree; use --json for the
    machine graph.

    Each node shows: id, type, content_hash, timestamp, pipeline_version, storage_uri
    (the six FOUND-06 lineage fields).
    """
    from knowledge_lake.lineage import nodes_to_json, render_tree, resolve_ancestry

    try:
        nodes = resolve_ancestry(artifact_id)
    except (LookupError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    if as_json:
        typer.echo(nodes_to_json(nodes))
    else:
        typer.echo(f"Lineage for: {artifact_id}")
        typer.echo(f"Chain depth: {len(nodes)} nodes")
        typer.echo()
        typer.echo(render_tree(nodes))


@app.command(name="demo")
def cmd_demo(
    collection: str = typer.Option(
        "klake_spike", "--collection", "-c", help="Qdrant collection for the demo."
    ),
    query: str = typer.Option(
        "what are administrative safeguards",
        "--query",
        "-q",
        help="Demo search query.",
    ),
    top_k: int = typer.Option(3, "--top-k", "-k", help="Number of results."),
    use_live: bool = typer.Option(
        False,
        "--live",
        help="Download the live HHS PDF instead of using the cached fixture.",
    ),
) -> None:
    """Run the full end-to-end demo: ingest → search → lineage.

    Uses the cached HIPAA Security Rule fixture by default (D-05, hermetic).
    Pass --live to download the live HHS PDF instead.

    The fixed query 'what are administrative safeguards' returns cited results
    from the Administrative Safeguards section.  Lineage of the top hit is
    resolved and printed.

    This is the smoke test that proves the walking skeleton end-to-end (D-03).
    """
    from knowledge_lake.pipeline.run import run_document
    from knowledge_lake.pipeline.search import search as do_search
    from knowledge_lake.lineage import nodes_to_json, render_tree, resolve_ancestry

    typer.echo("=" * 60)
    typer.echo("Knowledge Lake — End-to-End Demo")
    typer.echo("=" * 60)
    typer.echo()

    # ── Step 1: Ingest ────────────────────────────────────────────────────────
    if use_live:
        live_url = (
            "https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/"
            "understanding/srsummary.pdf"
        )
        typer.echo(f"Ingesting live PDF: {live_url}")
        try:
            result = run_document(url=live_url, source_name="HHS HIPAA Security Rule", collection=collection)
        except Exception as exc:
            typer.echo(f"Live URL failed ({exc}). Falling back to cached fixture.", err=True)
            use_live = False

    if not use_live:
        fixture_path = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "hhs_security_rule.pdf"
        # Try the path relative to the package first, then relative to cwd
        if not fixture_path.exists():
            fixture_path = Path("tests/fixtures/hhs_security_rule.pdf")
        if not fixture_path.exists():
            typer.echo("Error: Cached fixture not found. Run from the project root.", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"Ingesting cached fixture: {fixture_path}")
        result = run_document(
            fixture_path=fixture_path,
            source_name="HHS HIPAA Security Rule (Fixture)",
            collection=collection,
        )

    typer.echo(f"  ✓ Ingested: {result['chunk_count']} chunks indexed")
    typer.echo(f"  source_id:   {result['source_id']}")
    typer.echo(f"  collection:  {result['collection']}")
    typer.echo()

    # ── Step 2: Search ────────────────────────────────────────────────────────
    typer.echo(f"Query: {query!r}")
    typer.echo("-" * 40)
    hits = do_search(query, collection=collection, top_k=top_k)

    if not hits:
        typer.echo("No results — is the collection populated?")
        raise typer.Exit(code=1)

    for i, hit in enumerate(hits, 1):
        payload = hit.payload
        typer.echo(f"[{i}] score={hit.score:.4f}")
        typer.echo(f"    document:  {payload.get('document', '?')}")
        typer.echo(f"    section:   {payload.get('section_path', '?')}")
        typer.echo(f"    page:      {payload.get('page', '?')}")
        text_snippet = (payload.get("text") or "")[:100].replace("\n", " ")
        if text_snippet:
            typer.echo(f"    text:      {text_snippet!r}")

    typer.echo()

    # ── Step 3: Lineage ───────────────────────────────────────────────────────
    top_chunk_id = hits[0].payload.get("chunk_id") or hits[0].id
    typer.echo(f"Lineage for top hit: {top_chunk_id}")
    typer.echo("-" * 40)

    try:
        nodes = resolve_ancestry(top_chunk_id)
        typer.echo(render_tree(nodes))
        typer.echo()
        typer.echo(f"Chain depth: {len(nodes)} nodes (chunk → ... → source)")
    except Exception as exc:
        typer.echo(f"Warning: lineage resolution failed: {exc}", err=True)

    typer.echo()
    typer.echo("Demo complete. Walking skeleton is alive.")


if __name__ == "__main__":
    app()
