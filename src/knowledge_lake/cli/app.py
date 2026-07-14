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

import json
from pathlib import Path
from urllib.parse import urlparse

import typer

import knowledge_lake
from knowledge_lake.registry.repo import set_source_schedule

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
    name: str | None = typer.Option(
        None, "--name", "-n", help="Human-readable source name (defaults to URL hostname)."
    ),
    domain: str | None = typer.Option(
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
            typer.echo("Registered new source:")
        else:
            typer.echo("Source already exists (dedup hit):")
        typer.echo(f"  source_id:      {result['source_id']}")
        typer.echo(f"  name:           {result['name']}")
        typer.echo(f"  url:            {result['url']}")
        typer.echo(f"  normalized_url: {result['normalized_url']}")
        if result.get("domain"):
            typer.echo(f"  domain:         {result['domain']}")
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command(name="upload")
def cmd_upload(
    file_path: str = typer.Argument(..., help="Path to the local file to upload."),
    source_name: str | None = typer.Option(
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
        typer.echo("Uploaded:")
        typer.echo(f"  source_id:    {result['source_id']}")
        typer.echo(f"  artifact_id:  {result['artifact_id']}")
        typer.echo(f"  storage_uri:  {result['storage_uri']}")
        typer.echo(f"  content_hash: {result['content_hash']}")
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command(name="discover")
def cmd_discover(
    query: str = typer.Argument(..., help="Natural-language search query for source discovery."),
    limit: int = typer.Option(
        20, "--limit", "-l", help="Maximum number of results (1–100).", min=1, max=100
    ),
    domain: str | None = typer.Option(
        None,
        "--domain",
        "-d",
        help="Domain classification for discovered sources (e.g. 'healthcare'). "
        "Defaults to the active settings.domain.domain_name when omitted.",
    ),
) -> None:
    """Discover candidate sources via meta-search and auto-register them.

    Each result URL is SSRF-validated and URL-deduped before registration.
    Discovered sources have source_type='discovered' with minimal metadata
    (URL + title only, D-09).
    """
    from knowledge_lake.config.settings import get_settings
    from knowledge_lake.pipeline.discover import discover_sources

    effective_domain = domain or get_settings().domain.domain_name

    try:
        results = discover_sources(query=query, limit=limit, domain=effective_domain)
    except (RuntimeError, LookupError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

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
    mime_type: str | None = typer.Option(
        None, "--mime", "-m", help="MIME type override. Auto-detected from artifact if omitted."
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
        typer.echo("Parsed:")
        typer.echo(f"  artifact_id:   {result['artifact_id']}")
        typer.echo(f"  quality_score: {result.get('quality_score', 'n/a')}")
        typer.echo(f"  parser_used:   {result.get('parser_used', 'n/a')}")
        typer.echo(f"  content_hash:  {result.get('content_hash', 'n/a')}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


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
        typer.echo("Cleaned:")
        typer.echo(f"  artifact_id:   {result['artifact_id']}")
        typer.echo(f"  language:      {result['language']}")
        typer.echo(f"  dedup_status:  {result['dedup_status']}")
        typer.echo(f"  content_hash:  {result['content_hash']}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


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
    from knowledge_lake.registry import repo as registry_repo
    from knowledge_lake.registry.db import get_session
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
        typer.echo("Chunked:")
        typer.echo(f"  chunk_count:  {len(result)}")
        if result:
            typer.echo(f"  first_chunk:  {result[0]['artifact_id']}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


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
    from knowledge_lake.registry import repo as registry_repo
    from knowledge_lake.registry.db import get_session

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
        domain_system_prompt: str | None = None
        from knowledge_lake.config.settings import get_settings as _get_settings
        _s = _get_settings()
        if _s.domain.domain_name:
            from knowledge_lake.domains.loader import DomainLoader
            domain_system_prompt = DomainLoader.from_name(_s.domain.domain_name).render_prompt("enrich.j2")
        result = enrich_document(
            cleaned_artifact_id, source_id, parsed_doc=parsed_doc,
            domain_system_prompt=domain_system_prompt,
        )
        typer.echo("Enriched:")
        typer.echo(f"  status:        {result['status']}")
        typer.echo(f"  artifact_id:   {result.get('artifact_id')}")
        typer.echo(f"  quality_score: {result.get('quality_score')}")
        typer.echo(f"  cached:        {result.get('cached', False)}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


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
        raise typer.Exit(code=1) from exc


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
        raise typer.Exit(code=1) from exc


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

        typer.echo("Dataset example generated:")
        typer.echo(f"  status:      {result['status']}")
        typer.echo(f"  example_id:  {result.get('example_id')}")
        typer.echo(f"  dataset_id:  {result.get('dataset_id')}")
        typer.echo(f"  cost_usd:    {result.get('cost_usd')}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command(name="crawl")
def cmd_crawl(
    url: str = typer.Argument(..., help="https:// seed URL to crawl."),
    crawler: str | None = typer.Option(
        None,
        "--crawler",
        "-c",
        help="Override crawler adapter (default: settings.crawler). Must be a registered crawler.",
    ),
    max_pages: int | None = typer.Option(
        None,
        "--max-pages",
        "-m",
        help="Maximum number of pages to crawl (1–10000).",
        min=1,
        max=10000,
    ),
    domain: str | None = typer.Option(
        None,
        "--domain",
        "-d",
        help="Domain classification for the crawled source (e.g. 'healthcare'). "
        "Defaults to the active settings.domain.domain_name when omitted.",
    ),
) -> None:
    """Crawl a public site into the lake: raw HTML + bronze markdown per page.

    Creates a crawl job, fetches pages with rate limiting and robots.txt respect,
    and writes two artifacts per page (raw HTML + bronze markdown) with full lineage.
    Resume-safe: re-running fetches only pending URLs.
    """
    import asyncio

    from knowledge_lake.config.settings import get_settings
    from knowledge_lake.pipeline.crawl import crawl_source

    effective_domain = domain or get_settings().domain.domain_name

    try:
        result = asyncio.run(crawl_source(
            url,
            crawler=crawler,
            max_pages=max_pages,
            domain=effective_domain,
        ))
        typer.echo("Crawl complete:")
        typer.echo(f"  job_id:              {result['job_id']}")
        typer.echo(f"  source_id:           {result['source_id']}")
        typer.echo(f"  crawler:             {result['crawler']}")
        typer.echo(f"  pages_complete:      {result['pages_complete']}")
        typer.echo(f"  pages_robots_blocked: {result['pages_robots_blocked']}")
        typer.echo(f"  pages_failed:        {result['pages_failed']}")
        typer.echo(f"  pages_total:         {result['pages_total']}")
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command(name="crawl-all")
def cmd_crawl_all(
    domain: str | None = typer.Option(
        None,
        "--domain",
        "-d",
        help="Filter to sources matching this domain (e.g. 'healthcare'). Crawls all sources if omitted.",
    ),
) -> None:
    """Batch-crawl all registered sources into the lake.

    Loops over all sources (optionally filtered by --domain), running per-source
    crawl in sequence.  Per-source failures are logged and counted but do not
    abort the batch (CRAWL-02 D-07/D-09).
    """
    import asyncio

    from knowledge_lake.pipeline.crawl import crawl_all_sources

    try:
        result = asyncio.run(crawl_all_sources(domain=domain))
        typer.echo("Crawl-all complete:")
        typer.echo(f"  total:     {result['total']}")
        typer.echo(f"  succeeded: {result['succeeded']}")
        typer.echo(f"  failed:    {result['failed']}")
        for entry in result.get("results", []):
            status = entry.get("status", "unknown")
            source_id = entry.get("source_id", "")
            error = entry.get("error")
            if error:
                typer.echo(f"  {source_id}: {status} — {error}")
            else:
                typer.echo(f"  {source_id}: {status}")
    except Exception as exc:  # L-01 fix: OperationalError, ValidationError etc. need clean output
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command(name="ingest-url")
def cmd_ingest_url(
    url: str = typer.Argument(..., help="https:// URL to ingest (SSRF-checked)."),
    source_name: str | None = typer.Option(
        None, "--source", "-s", help="Human-readable source name."
    ),
    mime_type: str | None = typer.Option(
        None, "--mime", "-m", help="MIME type override. Auto-detected from HTTP Content-Type if omitted."
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
        raise typer.Exit(code=1) from exc


@app.command(name="process-crawled")
def cmd_process_crawled(
    source_id: str | None = typer.Option(
        None, "--source", "-s", help="Process only raw docs from this source ID."
    ),
    limit: int = typer.Option(
        100, "--limit", "-l", help="Maximum number of documents to process."
    ),
    collection: str = typer.Option(
        "klake_chunks", "--collection", "-c", help="Qdrant collection to index into."
    ),
) -> None:
    """Process crawled raw_document artifacts through parse→chunk→embed→index.

    Finds all raw_document artifacts that have no corresponding parsed_document
    child and runs the full pipeline on each. Useful after bulk crawling to
    convert raw HTML into searchable vector chunks.
    """
    from knowledge_lake.pipeline.process import process_crawled

    result = process_crawled(source_id=source_id, limit=limit, collection=collection)

    if result["processed"] == 0 and result["failed"] == 0:
        typer.echo("No unprocessed raw documents found.")
        return

    typer.echo(
        f"\nProcess complete: {result['processed']} docs, "
        f"{result['chunks_indexed']} chunks indexed, "
        f"{result['failed']} failed."
    )


@app.command(name="search")
def cmd_search(
    query: str = typer.Argument(..., help="Natural-language search query."),
    collection: str = typer.Option(
        "klake_chunks", "--collection", "-c", help="Qdrant collection to search."
    ),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Maximum number of results."),
    domain: str | None = typer.Option(
        None, "--domain", help="Filter results to this domain."
    ),
    document_type: str | None = typer.Option(
        None, "--document-type", help="Filter results to this document_type."
    ),
    min_quality_score: float | None = typer.Option(
        None, "--min-quality-score", help="Filter results to quality_score >= this value."
    ),
    source_name: str | None = typer.Option(
        None, "--source-name", help="Filter results to this source name."
    ),
    format: str | None = typer.Option(
        None, "--format", help="Filter results to this source format (e.g. 'html', 'pdf')."
    ),
    source_id: str | None = typer.Option(
        None, "--source-id", help="Filter results to this source ID."
    ),
    tag: list[str] | None = typer.Option(
        None, "--tag",
        help="Filter results to chunks tagged with this tag (repeatable: --tag a --tag b uses OR logic)."
    ),
    mode: str | None = typer.Option(
        None, "--mode",
        help="Search mode: hybrid|dense|sparse (default from KLAKE_SEARCH__MODE, else hybrid)."
    ),
    route: str | None = typer.Option(
        None, "--route",
        help="Retrieval route: chunk|tree|two_stage|auto (default from KLAKE_ROUTER__DEFAULT_ROUTE, else auto).",
    ),
    tree_mode: str | None = typer.Option(
        None, "--tree-mode",
        help="Tree-traversal mode: heuristic|llm (only used when route is tree/two_stage/auto+tree).",
    ),
) -> None:
    """Embed a query and return the top-K matching chunks with citation.

    Each result shows score, section, page, chunk text snippet, and source provenance fields.

    New filter flags (Phase 7 PAYLOAD-02):
        --source-name, --format, --source-id, --tag (repeatable).

    Mode selection (Phase 10 RETR-03):
        --mode hybrid|dense|sparse — overrides KLAKE_SEARCH__MODE for this call.
        Omitting --mode lets pipeline.search fall back to settings.search.mode (default hybrid).

    Route selection (Phase 15 ROUTE-01):
        --route chunk|tree|two_stage|auto — selects retrieval path.
        Omitting --route lets routed_search fall back to settings.router.default_route (auto).

    Tree-traversal mode (Phase 15 ROUTE-01):
        --tree-mode heuristic|llm — controls tree_search() traversal strategy.
        Only relevant when route resolves to tree or two_stage.

    D-13 backward-compat note:
        source_name, format, tags, source_id filters are only effective on points indexed
        after Phase 7 (or after a full reindex from source chunks). Pre-Phase-7 points
        will not match.
    """
    VALID_MODES = {"hybrid", "dense", "sparse"}
    if mode is not None and mode not in VALID_MODES:
        typer.echo(
            f"Error: --mode must be one of {sorted(VALID_MODES)}, got {mode!r}",
            err=True,
        )
        raise typer.Exit(code=1)

    VALID_ROUTES = {"chunk", "tree", "two_stage", "auto"}
    if route is not None and route not in VALID_ROUTES:
        typer.echo(
            f"Error: --route must be one of {sorted(VALID_ROUTES)}, got {route!r}",
            err=True,
        )
        raise typer.Exit(code=1)

    VALID_TREE_MODES = {"heuristic", "llm"}
    if tree_mode is not None and tree_mode not in VALID_TREE_MODES:
        typer.echo(
            f"Error: --tree-mode must be one of {sorted(VALID_TREE_MODES)}, got {tree_mode!r}",
            err=True,
        )
        raise typer.Exit(code=1)

    from knowledge_lake.pipeline.route import routed_search

    hits = routed_search(
        query,
        route=route,
        collection=collection,
        top_k=top_k,
        domain=domain,
        document_type=document_type,
        min_quality_score=min_quality_score,
        source_name=source_name,
        format=format,
        source_id=source_id,
        tags=tag,  # CLI param is named 'tag' (list[str]); routed_search() expects 'tags'
        mode=mode,
        tree_mode=tree_mode,
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
        typer.echo(f"      source_name:  {payload.get('source_name', '?')}")
        typer.echo(f"      source_id:    {payload.get('source_id', '?')}")
        typer.echo(f"      format:       {payload.get('format', '?')}")
        typer.echo(f"      tags:         {payload.get('tags', [])}")
        typer.echo(f"      organization: {payload.get('organization', '?')}")
        typer.echo(f"      title:        {payload.get('title', '?')}")
        text_snippet = (payload.get("text") or "")[:120].replace("\n", " ")
        if text_snippet:
            typer.echo(f"      text:         {text_snippet!r}")
        typer.echo()


@app.command(name="tree-search")
def cmd_tree_search(
    query: str = typer.Argument(..., help="Natural-language search query."),
    top_k: int | None = typer.Option(
        None, "--top-k", "-k",
        help="Maximum number of results (default from KLAKE_TREE_SEARCH__TOP_K, else 5).",
    ),
    mode: str | None = typer.Option(
        None, "--mode",
        help="Tree traversal mode: heuristic|llm (default from KLAKE_TREE_SEARCH__MODE, else heuristic).",
    ),
) -> None:
    """Two-stage tree retrieval: Qdrant shortlist -> per-document tree search (RETR-04).

    Thin shim over pipeline.tree_search.tree_search() — validates args and
    delegates; no orchestration logic lives here (D-13).
    """
    VALID_MODES = {"heuristic", "llm"}
    if mode is not None and mode not in VALID_MODES:
        typer.echo(
            f"Error: --mode must be one of {sorted(VALID_MODES)}, got {mode!r}",
            err=True,
        )
        raise typer.Exit(code=1)

    from knowledge_lake.pipeline.tree_search import tree_search

    hits = tree_search(query, top_k=top_k, mode=mode)

    if not hits:
        typer.echo(f"No results for query: {query!r}")
        return

    typer.echo(f"Results for: {query!r}")
    typer.echo()
    for i, hit in enumerate(hits, 1):
        payload = hit.payload
        typer.echo(f"  [{i}] score={hit.score:.4f}")
        typer.echo(f"      document:     {payload.get('document', '?')}")
        typer.echo(f"      section_path: {payload.get('section_path', '?')}")
        typer.echo(f"      pages:        {payload.get('page_start', '?')}-{payload.get('page_end', '?')}")
        typer.echo(f"      node_path:    {payload.get('node_path', '?')}")
        typer.echo()


@app.command(name="reindex")
def cmd_reindex(
    collection: str = typer.Option(
        "klake_chunks", "--collection", "-c", help="Qdrant alias to reindex."
    ),
    hybrid: bool = typer.Option(
        False, "--hybrid",
        help=(
            "Migrate the alias to named dense+sparse vectors via a re-embedding reindex "
            "(RETR-01 live migration). "
            "Runs assert_server_supports_hybrid preflight first — aborts cleanly if the "
            "server is too old or the parity gate fails; the alias keeps the old collection "
            "on any preflight/parity abort (rollback)."
        ),
    ),
) -> None:
    """Reindex a Qdrant alias with zero search downtime (INDEX-02).

    Creates the next versioned physical collection, copies all existing points
    into it, then atomically repoints the alias. The prior physical collection
    is retained (never auto-dropped).

    With --hybrid: triggers the RETR-01 operator live migration — re-embeds all
    existing points with dense+sparse named vectors.  The D-07 server preflight
    and D-06 parity gate run before any data is touched; on failure the alias
    continues to point at the old collection (safe rollback).
    """
    from knowledge_lake.pipeline.index import reindex_collection

    try:
        result = reindex_collection(collection, hybrid=hybrid)
        typer.echo(f"Reindexed: {result['collection']}")
        typer.echo(f"  new_physical: {result['new_physical']}")
        typer.echo(f"  old_physical: {result.get('old_physical')}")
    except (ValueError, LookupError, RuntimeError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


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
        raise typer.Exit(code=1) from exc

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
    from knowledge_lake.lineage import render_tree, resolve_ancestry
    from knowledge_lake.pipeline.run import run_document
    from knowledge_lake.pipeline.search import search as do_search

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


class ExportKind(str):
    """Valid export kind values for the klake export command (T-05-09)."""

    RAG_CORPUS = "rag-corpus"
    PRETRAIN = "pretrain"
    FINETUNE = "finetune"

    @classmethod
    def _valid_values(cls) -> list[str]:
        return [cls.RAG_CORPUS, cls.PRETRAIN, cls.FINETUNE]


@app.command(name="export")
def cmd_export(
    kind: str = typer.Argument(
        ...,
        help="Export kind: 'rag-corpus' (Parquet), 'pretrain' (JSONL), or 'finetune' (JSONL).",
    ),
    dataset_name: str | None = typer.Option(
        None,
        "--dataset-name",
        "-d",
        help="Required for kind=finetune. The logical Dataset name to export.",
    ),
) -> None:
    """Export the curated corpus or a dataset to the gold zone.

    Writes gold-zone Parquet (rag-corpus) or JSONL (pretrain, finetune) files to S3.
    Fails closed with an error if any undocumented train/eval contamination exists
    (05-AI-SPEC Section 6/7 hard gate).

    Examples:
        klake export rag-corpus
        klake export pretrain
        klake export finetune --dataset-name my_rag_eval_v1
    """
    from knowledge_lake.pipeline.export import (
        TrainEvalContaminationError,
        export_finetune_dataset,
        export_pretrain_corpus,
        export_rag_corpus,
    )

    valid_kinds = ["rag-corpus", "pretrain", "finetune"]
    if kind not in valid_kinds:
        typer.echo(f"Error: kind must be one of {valid_kinds}, got {kind!r}", err=True)
        raise typer.Exit(code=1)

    if kind == "finetune" and dataset_name is None:
        typer.echo("Error: --dataset-name is required for kind=finetune", err=True)
        raise typer.Exit(code=1)

    try:
        if kind == "rag-corpus":
            result = export_rag_corpus()
        elif kind == "pretrain":
            result = export_pretrain_corpus()
        else:
            assert dataset_name is not None
            result = export_finetune_dataset(dataset_name)
    except TrainEvalContaminationError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("Export complete:")
    typer.echo(f"  dataset_id:  {result['dataset_id']}")
    typer.echo(f"  storage_uri: {result['storage_uri']}")
    typer.echo(f"  row_count:   {result['row_count']}")
    if result.get("skipped_dangling_lineage") is not None:
        typer.echo(f"  skipped_dangling_lineage: {result['skipped_dangling_lineage']}")


@app.command(name="export-wiki")
def cmd_export_wiki(
    domain: str = typer.Option(
        ..., "--domain", "-d", help="Domain to compile wiki for (required)."
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Ignore manifest, full rebuild."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing."),
    archive: bool = typer.Option(False, "--archive", help="Also write a .tar.gz archive of the wiki."),
) -> None:
    """Compile the interlinked wiki knowledge base for a domain.

    Reads enriched document artifacts for the given domain, applies IDF
    filtering for concept pages, and writes Markdown pages + manifest to
    the S3 gold zone.  Supports manifest-based incremental rebuild (only
    changed pages are re-written) and optional .tar.gz archive.

    Examples:
        klake export-wiki --domain healthcare
        klake export-wiki --domain healthcare --force
        klake export-wiki --domain healthcare --dry-run
        klake export-wiki --domain healthcare --archive
    """
    from botocore.exceptions import ClientError as BotocoreClientError

    from knowledge_lake.pipeline.wiki import compile_wiki

    try:
        result = compile_wiki(
            domain=domain,
            force=force,
            dry_run=dry_run,
            archive=archive,
        )
    except (ValueError, LookupError, BotocoreClientError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("Wiki export complete:")
    typer.echo(f"  pages_created:   {result['pages_created']}")
    typer.echo(f"  pages_updated:   {result['pages_updated']}")
    typer.echo(f"  pages_unchanged: {result['pages_unchanged']}")
    typer.echo(f"  concept_pages:   {result['concept_pages']}")
    typer.echo(f"  manifest_uri:    {result['manifest_uri']}")
    if result.get("archive_uri") is not None:
        typer.echo(f"  archive_uri:     {result['archive_uri']}")


@app.command(name="init")
def cmd_init(
    domain: str = typer.Option(
        ..., "--domain", "-d", help="Domain pack name to load (e.g. 'healthcare')."
    ),
) -> None:
    """Load a domain pack and bulk-register its seed sources.

    Reads domains/<domain>/sources.yaml and registers every crawl-type source
    into the registry. Upload-type sources (bulk data files) are reported but
    not auto-registered — download them manually first.

    Delegates to ``pipeline.domains.load_domain()`` — logic lives in exactly
    one place (D-05, D-03).
    """
    import re

    _DOMAIN_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    if not _DOMAIN_NAME_RE.fullmatch(domain):
        typer.echo(
            f"Error: Invalid domain name {domain!r}: must match "
            r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$ (path traversal guard)",
            err=True,
        )
        raise typer.Exit(code=1)

    from knowledge_lake.pipeline.domains import load_domain

    try:
        result = load_domain(domain)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Registered {result['loaded_count']} sources from {domain} pack.")
    if result["skipped_count"] > 0:
        typer.echo(f"{result['skipped_count']} sources already registered (dedup).")
    if result["upload_required_count"] > 0:
        typer.echo(
            f"{result['upload_required_count']} sources require manual upload "
            f"— see domains/{domain}/sources.yaml."
        )


@app.command(name="index")
def cmd_index(
    collection: str = typer.Option(
        "klake_chunks", "--collection", "-c", help="Qdrant collection alias to reindex."
    ),
) -> None:
    """Reindex a Qdrant collection alias with zero-downtime alias swap.

    Wraps the 'reindex' command — 'index' is the canonical name per IFACE-01.
    'reindex' remains as a power-user alias.
    """
    from knowledge_lake.pipeline.index import reindex_collection

    try:
        result = reindex_collection(collection)
        typer.echo(f"Reindexed: {result['collection']}")
        typer.echo(f"  new_physical: {result['new_physical']}")
        typer.echo(f"  old_physical: {result.get('old_physical')}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command(name="set-schedule")
def cmd_set_schedule(
    source_id: str = typer.Argument(..., help="Source ID to update."),
    cron: str | None = typer.Option(
        None, "--cron", help="5-field UTC cron string (e.g. '0 3 * * *')."
    ),
    clear: bool = typer.Option(False, "--clear", help="Clear the crawl schedule."),
) -> None:
    """Set or clear a source's crawl schedule.

    Validates the cron expression with Dagster's is_valid_cron_string before
    persisting. A malformed cron is rejected with a non-zero exit.
    Use --clear to remove the schedule (disable auto-recrawl).
    """
    from dagster._utils.schedules import is_valid_cron_string

    from knowledge_lake.registry.db import get_session

    if clear:
        with get_session() as session:
            result = set_source_schedule(session, source_id, None)
            if not result:
                typer.echo(f"Error: Source '{source_id}' not found.", err=True)
                raise typer.Exit(code=1)
            session.commit()
        typer.echo(f"Cleared crawl schedule for source '{source_id}'.")
        return

    if cron is None:
        typer.echo("Error: Must provide --cron <expression> or --clear.", err=True)
        raise typer.Exit(code=1)

    if not is_valid_cron_string(cron):
        typer.echo(f"Error: Invalid cron expression '{cron}'.", err=True)
        raise typer.Exit(code=1)

    with get_session() as session:
        result = set_source_schedule(session, source_id, cron)
        if not result:
            typer.echo(f"Error: Source '{source_id}' not found.", err=True)
            raise typer.Exit(code=1)
        session.commit()
    typer.echo(f"Set crawl schedule for source '{source_id}': {cron}")


@app.command(name="mcp")
def cmd_mcp(
    sse: bool = typer.Option(
        False, "--sse", help="Serve over Streamable HTTP instead of stdio."
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        help="HTTP port (localhost only, --sse mode). Defaults to settings.mcp.port.",
    ),
) -> None:
    """Run the MCP agent server: stdio (default, fd-locked) or Streamable HTTP (--sse).

    Both transports serve the SAME Server built from
    ``registered_tools(settings.mcp.readonly)`` so ``stdio == http`` by construction.
    The ``--sse`` flag name backs MCP **Streamable HTTP** (build_http_app), NOT the
    deprecated HTTP+SSE transport. The bind host/port and bearer token come from
    ``settings.mcp`` (host defaults to 127.0.0.1 — never 0.0.0.0).
    """
    from knowledge_lake.agent.registry import registered_tools
    from knowledge_lake.agent.server import build_server
    from knowledge_lake.config.settings import get_settings

    settings = get_settings()
    server = build_server(registered_tools(readonly=settings.mcp.readonly))

    if sse:
        # Streamable HTTP — no stdout lockdown in this mode (D-08). Bind host and
        # bearer come from settings.mcp; --port overrides the configured port.
        # Bind port falls back to settings.mcp.port so KLAKE_MCP__PORT takes
        # effect (WR-05) — an explicit --port still overrides.
        bind_port = port if port is not None else settings.mcp.port

        # Fail-closed (WR-04): refuse to serve write tools over HTTP with no auth.
        # The 127.0.0.1 bind + Host guard do not stop a same-host attacker, so an
        # unauthenticated, writable HTTP surface is a real exposure. stdio and an
        # explicitly-tokened or explicitly-readonly HTTP server are unaffected.
        if not settings.mcp.token and not settings.mcp.readonly:
            raise typer.BadParameter(
                "Refusing to serve write tools over HTTP without KLAKE_MCP__TOKEN. "
                "Set a token or run with KLAKE_MCP__READONLY=true."
            )

        import uvicorn

        from knowledge_lake.agent.http import build_http_app

        http_app = build_http_app(
            server,
            host=settings.mcp.host,
            port=bind_port,
            token=settings.mcp.token,
        )
        uvicorn.run(http_app, host=settings.mcp.host, port=bind_port)
    else:
        # stdio transport — run_stdio applies the fd-level stdout lockdown (D-08).
        import anyio

        from knowledge_lake.agent.stdio import run_stdio

        init_opts = server.create_initialization_options()
        anyio.run(run_stdio, server, init_opts)


@app.command(name="openapi")
def cmd_openapi() -> None:
    """Write the deterministic OpenAPI schema to docs/openapi.json (SKILL-02).

    Dumps ``app.openapi()`` with ``sort_keys=True`` and a trailing newline so
    re-runs produce a no-op git diff (Pitfall 3).
    """
    try:
        from knowledge_lake.api.app import app as fastapi_app
    except ImportError as exc:  # pragma: no cover - import guard
        typer.echo(f"Error: could not import the FastAPI app: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    docs_dir = Path(__file__).resolve().parents[3] / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    out_path = docs_dir / "openapi.json"
    payload = json.dumps(fastapi_app.openapi(), indent=2, sort_keys=True) + "\n"
    out_path.write_text(payload, encoding="utf-8")
    typer.echo(f"Wrote {out_path}")


# ── Domain pack authoring ──────────────────────────────────────────────────────

domain_app = typer.Typer(
    name="domain",
    help="Author and manage domain packs.",
    add_completion=False,
)
app.add_typer(domain_app, name="domain")


@domain_app.command(name="new")
def cmd_domain_new(
    name: str = typer.Argument(
        ..., help="Domain pack name — must match ^[a-zA-Z][a-zA-Z0-9_-]{0,63}$."
    ),
    root: str = typer.Option(
        "domains",
        "--root",
        "-r",
        help="Parent directory for the new pack. The default 'domains' is loadable "
        "via `klake init --domain <name>`.",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite an existing pack directory."
    ),
) -> None:
    """Scaffold a new domain pack skeleton.

    Generates domain.yaml, sources.yaml, taxonomy.yaml, prompts/, and
    validators/ so authoring a domain is a real workflow instead of copy-paste.
    """
    from knowledge_lake.domains.scaffold import scaffold_domain

    try:
        result = scaffold_domain(name, root=root, force=force)
    except (ValueError, FileExistsError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Created domain pack '{name}' at {result['path']}/")
    for f in result["files"]:
        typer.echo(f"  {f}")

    typer.echo("\nNext steps:")
    typer.echo("  1. Edit sources.yaml to add your sources.")
    typer.echo("  2. Customize prompts/ and validators/validate.py.")
    if Path(root).resolve() == (Path.cwd() / "domains").resolve():
        typer.echo(f"  3. Register its sources:  klake init --domain {name}")
    else:
        typer.echo(
            f"  3. Move the pack under 'domains/' to load it, then:  "
            f"klake init --domain {name}"
        )


if __name__ == "__main__":
    app()
