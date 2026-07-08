# Pitfalls Research

**Domain:** Knowledge Lake Framework — v2.0 Agent-Ready Lake (MCP interfaces, hybrid search, domain-segmented storage, scheduled re-crawl)
**Researched:** 2026-07-08
**Confidence:** HIGH (verified against MCP spec 2025-06-18/2025-11-25, Qdrant 1.10+ Query API docs, and this system's v1.0 constraints)

> Scope: mistakes specific to **adding these v2.0 features to the existing shipped `klake` system**. Every pitfall is filtered through the system's hard constraints: immutable SHA256-content-addressed raw zone, full lineage via stable IDs + content hashes, LiteLLM-only model calls, Dagster-from-day-1, structlog structured logging on stdout, robots.txt/license compliance. Generic "use rate limiting" advice is omitted — v1.0 already has it; the pitfalls here are about the *interactions* the new features create.

---

## Critical Pitfalls

### Pitfall 1: structlog on stdout corrupts the MCP stdio JSON-RPC stream

**What goes wrong:**
The MCP stdio transport uses **stdout as the JSON-RPC message channel** — every byte on stdout must be a valid framed JSON-RPC message. This system's constraint is "structlog structured logging **on stdout**." The moment `klake mcp` (stdio) boots and *anything* — a structlog line, a stray `print()`, a Typer/Click echo, a library warning, an uncaught traceback, a tqdm/rich progress bar, a LiteLLM cost log, a Dagster init banner, an unflushed buffer — writes to stdout, the client's JSON-RPC parser sees garbage and the session dies or silently drops messages. This is the single highest-probability v2.0 failure because the existing logging default *actively fights* the new transport.

**Why it happens:**
Every dependency in the stack logs to stdout by default (structlog is explicitly configured that way here; LiteLLM prints cost/verbose lines; Docling/Crawl4AI emit progress). Developers test the MCP server, it "works" in a quick manual check, then a single enrichment or crawl tool call triggers a downstream library that writes one line to stdout and the whole session breaks intermittently — hard to reproduce.

**How to avoid:**
- **Before any MCP tool logic**, at `klake mcp` (stdio mode) entry: reconfigure structlog to write to **stderr** (or a file), and redirect the root stdout. Concretely: set the structlog `WriteLoggerFactory`/`PrintLoggerFactory` to `sys.stderr`, and defensively `sys.stdout = sys.stderr` (or swap the real stdout fd to a saved handle the transport owns) so *any* third-party stdout write lands on stderr.
- Silence known offenders explicitly: set `litellm.suppress_debug_info = True` / route LiteLLM logging to stderr; disable Crawl4AI/Docling verbose/progress in MCP mode; set `logging.basicConfig` stream to stderr.
- Add a startup self-test: in stdio mode, write a canary line via the normal logging path and assert nothing landed on the fd the transport reads.
- **stdio vs SSE/HTTP mode must diverge here**: only stdio needs the stdout lockdown. Gate it on transport mode, not globally (HTTP mode still wants normal logs).

**Warning signs:**
- MCP client reports "invalid JSON", "unexpected token", or the session hangs after the first tool call that touches enrichment/crawl/parse.
- It works for `list_tools` but breaks on real operations (because those trigger noisy libraries).
- Intermittent/unreproducible disconnects tied to specific tools.

**Phase to address:** AI Agent Skills phase (MCP-01/MCP-02). This is a **first-task gate** — write the stdout-isolation shim and its self-test before implementing a single tool.

---

### Pitfall 2: Building v2.0 MCP on the deprecated SSE transport

**What goes wrong:**
Requirement MCP-01/MCP-02 says "stdio + **SSE**" and `klake mcp --sse --port 3001`. The standalone **HTTP+SSE transport was deprecated in the MCP spec revision 2025-03-26** and superseded by **Streamable HTTP** (spec 2025-11-25 defines only `stdio` and `Streamable HTTP` as standard). Building fresh on SSE means shipping v2.0 on a transport that current MCP clients (Claude Desktop/Code newer builds, IDEs) are dropping support for — you get an agent interface that agents can't reliably connect to, plus a near-term rewrite.

**Why it happens:**
Older tutorials, blog posts, and the requirement text itself still say "SSE" because it was the original remote transport. The MCP Python SDK still *ships* an SSE server class, so it compiles and runs — masking that it's the wrong target.

**How to avoid:**
- Implement the remote transport as **Streamable HTTP** (single endpoint, POST + optional SSE upgrade) even though the requirement says "SSE." Keep the `--sse`/`--port` CLI surface if desired for familiarity, but back it with Streamable HTTP. Note the substitution in the phase plan / decision log so it's an intentional deviation, not a silent one.
- If a legacy SSE client must be supported, add it as an *additional* endpoint, not the primary.
- Pin the MCP SDK version and record which spec revision it targets.

**Warning signs:**
- Newer MCP clients fail to connect to the remote server but the old `mcp` inspector works.
- SDK deprecation warnings mentioning `SSEServerTransport` / "use streamable HTTP".

**Phase to address:** AI Agent Skills phase (MCP-01). Decide the transport target at design time — flag to roadmapper as a requirement-vs-current-spec conflict to resolve up front.

---

### Pitfall 3: Two tool registries drift between stdio and HTTP transports

**What goes wrong:**
Because stdio and SSE/HTTP are wired up separately, developers register the lake operations (search, add-source, export-dataset, crawl, etc.) twice — once per transport — or duplicate the Pydantic→tool-schema conversion. Over time a tool is added/renamed on one path and not the other, so an agent gets different capabilities depending on how it connects. This also multiplies the surface for the SKILL-03 OpenAI-format definitions and SKILL-02 OpenAPI export to disagree.

**Why it happens:**
The MCP SDK encourages per-server registration; the two entrypoints (`klake mcp` vs `klake mcp --sse`) feel like two apps. Nobody notices drift until an agent complains a tool is "missing."

**How to avoid:**
- Define **one tool registry module** — a single list of tool objects (name, description, Pydantic input model, handler) — and have both transports mount that same registry. The transport is a thin adapter; the tool set is transport-agnostic.
- Derive the OpenAI-format tool defs (SKILL-03) and the static OpenAPI export (SKILL-02) from the **same registry / same Pydantic schemas**, not hand-written copies.
- Add a test asserting `stdio.list_tools() == http.list_tools()` and that every registry tool appears in the generated OpenAI/OpenAPI artifacts.

**Warning signs:**
- A tool works over stdio but 404s/absent over HTTP (or vice versa).
- `docs/openapi.json` or the OpenAI tool JSON lists a different tool set than `list_tools`.

**Phase to address:** AI Agent Skills phase (MCP-01, SKILL-02, SKILL-03). Establish the single-registry pattern before adding the second transport.

---

### Pitfall 4: Domain-scoped S3 keys break content-hash dedup and existing lineage pointers

**What goes wrong:**
STORE-01 restructures keys to `{zone}/{domain}/{source_id}/{hash}.{ext}`. Two collisions with the immutability/lineage constraints:
1. **Dedup regression:** v1.0 dedup is content-addressed (same SHA256 = same object = one copy). If the domain/source_id is now *in the path*, the **same bytes ingested under two domains (or two sources) produce two objects** at two keys. Cross-source dedup silently dies; the raw zone grows with byte-identical duplicates and the registry may mint two document IDs for one content hash.
2. **Lineage break:** Every v1.0 artifact, bronze/silver/gold pointer, and registry row references the **old key layout**. Changing the key scheme without a migration + pointer-rewrite orphans existing lineage — you can no longer resolve a stored object from a v1.0 artifact's parent pointer.

**Why it happens:**
"Segment storage by domain" reads as a pure organizational change, but in a content-addressed WORM store the key *is* the dedup identity and *is* the lineage anchor. Putting mutable classification (domain/source) into an immutable content-addressed path conflates identity with organization.

**How to avoid:**
- **Keep content identity separate from organization.** Options, in order of safety:
  - Preferred: keep the raw object physically content-addressed by hash (dedup intact) and express domain/source segmentation via **object tags** (STORE-02) and/or registry columns and/or a thin index prefix — not by relocating the canonical raw bytes.
  - If keys must carry domain, make **dedup a registry-level check on content_hash** that runs *before* choosing a key, and when the same hash appears under a new domain, **link to the existing object** rather than writing a second copy (store the additional domain as a tag/association, not a duplicate blob).
- **Never rewrite existing raw-zone keys** — immutability forbids moving objects. New scheme applies to **new writes only**; old objects stay put and remain resolvable. Maintain a key-scheme version on each object/registry row so both layouts resolve.
- Migration for *derived* zones (bronze/silver/gold) is a copy-forward with lineage pointer rewrites in a transaction, never an in-place raw mutation.
- Define `_unclassified` fallback deterministically: assert exactly one domain resolution path, and make `_unclassified` a real routed value (never null/empty segment producing `//`).

**Warning signs:**
- Raw-zone object count climbs faster than unique content hashes.
- A v1.0 artifact's parent pointer no longer resolves to an object.
- Two document registry rows share one content_hash across different domains.
- Keys containing `//` or literal `None`/empty domain segments.

**Phase to address:** MinIO Domain Segmentation phase (STORE-01/02/03). This is the highest-risk storage change — treat immutability + dedup + lineage as explicit acceptance criteria, not incidental.

---

### Pitfall 5: Content-hash re-crawl detection thrashes on dynamic HTML (false positives) or misses real edits (false negatives)

**What goes wrong:**
SCHED-02 "skip unchanged" hashes crawled content to decide whether to re-ingest. Two failure modes, both costly:
- **False positives (needless re-ingest):** Pages embed CSRF tokens, nonces, session IDs, ad slots, `generated-at` timestamps, view counters, or randomized script bundles. The *meaningful* content is identical but the raw bytes differ every fetch → the hash changes every tick → the sensor re-ingests, re-parses, re-enriches (LiteLLM spend), re-embeds, and **writes a new immutable raw object every schedule cycle**, permanently bloating the WORM raw zone with near-duplicates.
- **False negatives (missed updates):** If you hash only normalized/extracted text and a source updates data inside a table or PDF the extractor mangles, or updates only a linked asset, the text hash is unchanged and a real update is silently skipped → stale corpus.

**Why it happens:**
Naive `sha256(raw_bytes)` is the obvious change signal and matches the existing content-addressing, but raw bytes are the *wrong* signal for "did the meaningful content change." Dynamic boilerplate is nearly universal on real sites.

**How to avoid:**
- Detect change on a **normalized content signature**, not raw bytes: strip volatile regions (scripts, nonces, timestamps, tracking params) → canonicalize → hash the *cleaned/extracted* text (this system already produces cleaned text in the silver stage — reuse it). Keep the raw-bytes SHA256 for storage identity, but gate *re-ingest* on the normalized signature.
- Store per-source a `last_content_signature`; only proceed when it changes. Record both the raw hash and the signature so you can audit false pos/neg.
- Guard against false negatives by *also* re-ingesting on a max-staleness interval (force refresh every N cycles) and by including linked-asset hashes in the signature where INGEST-01 follows PDFs.
- Respect immutability: an unchanged-signature re-crawl must **not** write a new raw object. Only a genuine change writes a new content-addressed object (new version, old retained).

**Warning signs:**
- Raw-zone object count grows on every schedule tick with no real source updates.
- LiteLLM enrichment spend rises on a schedule with no new sources.
- A source known to update daily never produces a new document version.

**Phase to address:** Crawl Scheduling phase (SCHED-02). Pair the signature design with the Dagster sensor (Pitfall 6).

---

### Pitfall 6: Dagster re-crawl sensor — cursor/idempotency gaps cause duplicate runs and tick storms

**What goes wrong:**
The SCHED-01 sensor evaluates on an interval and yields `RunRequest`s for sources due for re-crawl. Common failures:
- **No/duplicate `run_key`:** if RunRequests don't carry a stable, deterministic `run_key`, the sensor fires the same source repeatedly across ticks → duplicate concurrent crawls of one source → racing writes, doubled spend, lineage confusion.
- **Cursor mismanagement:** the sensor cursor isn't advanced/persisted correctly, so on each evaluation it re-scans and re-emits everything (tick storm), or advances past sources and never re-crawls them.
- **Long evaluation blocking:** doing the crawl/DB work *inside* the sensor evaluation (instead of just emitting RunRequests) exceeds the sensor tick timeout, causing skipped ticks and backlog.
- **Overlap:** a scheduled re-crawl fires while the previous run for that source is still in-flight (slow crawl), stacking runs.

**Why it happens:**
Sensors feel like "just a function that returns runs," but Dagster's dedup/idempotency depends entirely on `run_key` semantics and correct cursor persistence. The existing v1.0 pipeline used assets/schedules, not change-driven sensors, so this is new territory here.

**How to avoid:**
- Give each RunRequest a **deterministic `run_key`** encoding source_id + the change signal (e.g., `f"{source_id}:{content_signature}"` or `:{crawl_window}`), so Dagster dedups repeats automatically.
- Keep sensor evaluation **cheap and fast**: query "sources due by `crawl_schedule`" from Postgres, emit RunRequests, update cursor to a monotonic watermark (e.g., last evaluated timestamp/id). Do the actual crawl in the launched run, not in the sensor.
- Prevent overlap: skip a source whose previous run is still active (query run status, or use a Dagster concurrency key / `RunsFilter`), and set a per-source concurrency limit.
- Tune `minimum_interval_seconds` to the crawl cadence — not seconds — to avoid tick storms; this interacts with adaptive rate limiting (Pitfall 7) and resumable jobs.
- Make the sensor idempotent under replay: re-emitting the same `run_key` after a crash must not double-crawl.

**Warning signs:**
- Two active runs for the same source_id.
- Dagster daemon logs show skipped ticks / evaluation timeouts.
- Sensor re-emits the full source list every tick (cursor not advancing).

**Phase to address:** Crawl Scheduling phase (SCHED-01). Design `run_key` + cursor together with the change signature (Pitfall 5).

---

### Pitfall 7: Adaptive rate limiting deadlocks the crawl or overrides robots.txt crawl-delay

**What goes wrong:**
CRAWL-03 adds per-host cooldown + backoff on 429/403. Interactions that bite:
- **Starvation/deadlock in `crawl-all`:** a single hot host that keeps returning 429 drives its cooldown ever longer; if the batch scheduler blocks the shared worker pool waiting on that host (or a global lock), the whole `crawl-all` (CRAWL-02) stalls even though other hosts are idle. Worst case: all workers parked on cooling-down hosts → no forward progress.
- **Backoff undercuts robots.txt:** the new adaptive limiter computes its own delay and *ignores* the crawl-delay already parsed from robots.txt in v1.0 → you crawl faster than the site's stated policy, violating the legal constraint, or you race two subsystems both throttling.
- **Resumable-job interaction:** cooldown/backoff state lives only in memory; a resumed job (v1.0 resumable crawls) forgets it was backing off and hammers a host that just banned it.

**Why it happens:**
Adaptive limiting is bolted onto an existing static rate limiter + robots.txt handler without deciding which one wins. Per-host cooldown naturally couples hosts if the work queue isn't host-partitioned.

**How to avoid:**
- **Effective delay = max(robots.txt crawl-delay, adaptive backoff, per-source `crawl_config.rate_limit_rps`).** Adaptive backoff may only *slow down*, never speed up past the robots/policy floor. Make this a single composed function with a unit test asserting robots-delay is never violated.
- Make the scheduler **host-partitioned and non-blocking**: a cooling-down host yields its worker to other hosts (ready-queue keyed by host + next-eligible-time), so one bad host can't starve the batch. Add a global deadline / max-cooldown cap and a "give up this host, continue batch" path.
- Persist per-host cooldown/backoff state (in Postgres/registry) so resumable jobs restore it and don't re-hammer a banned host.
- Cap cooldown growth and emit a structured event when a host is parked so it's observable.

**Warning signs:**
- `crawl-all` wall-clock stalls with workers idle and one host repeatedly 429ing.
- Request timestamps to a host closer together than its robots crawl-delay.
- After a resume, immediate 403/429 bursts to a previously-throttled host.

**Phase to address:** Metadata & Crawl Maturation phase (CRAWL-03), with a cross-check against SCHED-01 scheduling.

---

### Pitfall 8: Partial-JSON recovery silently caches a corrupt/misassigned enrichment result

**What goes wrong:**
ENRICH-01 recovers truncated LLM output by closing braces/heuristically repairing JSON. Failure modes that poison the corpus:
- **Wrong values from brace-closing:** naive "append `}`/`]` until it parses" can close a string mid-token, drop the last (partial) field, or — worse — mis-terminate so a value lands in the wrong key, producing a *valid-looking but incorrect* object that passes schema validation.
- **Caching the bad result:** v1.0 caches enrichment by `hash(prompt_version + content)` with **one call per document**. If the repaired partial is written to that cache, every future run returns the corrupt enrichment forever — the truncation happened once, but the poison is permanent and invisible.
- **Silent field misassignment:** partial recovery fills required fields with defaults/nulls that downstream code treats as "enriched," so the document looks processed but has degraded metadata (feeding Qdrant payload PAYLOAD-01 and search filters PAYLOAD-02 with wrong tags/title/org).

**Why it happens:**
Truncation is usually a `max_tokens`/timeout symptom; "just recover what we can" feels graceful. But partial recovery + a content-hash cache = durably persisting a one-time defect. The single-call-per-doc design means there's no second signal to catch it.

**How to avoid:**
- **Detect truncation explicitly first:** check the LiteLLM finish_reason (`length`/truncated) — don't infer it from a parse failure. If truncated, prefer **retry with higher max_tokens / continuation** over guessing.
- Only accept a recovered partial if it **validates against the full Pydantic schema AND all required fields are present and typed**; mark the result with a `partial_recovery=True` / `enrichment_incomplete` flag in the artifact + payload.
- **Do not cache incomplete/recovered results under the normal key** (or cache them under a distinct key/status so a later full run overwrites them). Never let a `partial=True` result short-circuit future full enrichment.
- Prefer a real streaming/greedy JSON parser (parse the longest valid prefix and *drop* the trailing incomplete object) over blind brace-appending, so you never invent values.
- Emit a structured warning + count of truncations so this is observable, not silent.

**Warning signs:**
- Enrichment cache entries with missing/`null` required fields.
- Qdrant payloads with empty `title`/`organization`/`tags` where the source clearly had them.
- LiteLLM responses with `finish_reason=length` that still produced a "successful" enrichment.

**Phase to address:** Metadata & Crawl Maturation phase (ENRICH-01), coordinated with PAYLOAD-01/02 (bad enrichment flows straight into search payloads).

---

### Pitfall 9: PDF-from-crawl link-following opens SSRF and unbounded crawl explosion, and breaks license/robots scope

**What goes wrong:**
INGEST-01 follows links on a crawled page to ingest linked PDFs/docs. Four hazards:
- **SSRF:** a followed link points at `http://169.254.169.254/…` (cloud metadata), `http://localhost:9000` (the MinIO instance), internal Docker service names, or `file://` — the crawler fetches internal resources. v1.0 has an SSRF guard for *seed* URLs, but followed/derived links are a **new, untrusted input path** that may bypass it.
- **Crawl explosion:** "follow links to PDFs" without depth/count/domain bounds turns a single page into an unbounded frontier (link farms, paginated document indexes) → runaway crawl, cost, and raw-zone growth.
- **Robots/license scope:** the linked PDF may be on a *different host* with its own robots.txt and its own license, or off the source's licensed scope entirely — following it can violate the legal constraint and ingest content whose license isn't tracked.
- **Dedup across HTML + its PDF:** the same document exists as the HTML page *and* the linked PDF (or the PDF is linked from many pages) → double-ingest unless dedup spans both.

**How to avoid:**
- Route **every followed link through the same SSRF guard** as seed URLs (block private/link-local/loopback/metadata IPs, non-http(s) schemes, and internal hostnames) — resolve DNS and re-check after redirects, not just the literal URL.
- Bound following hard: max additional depth (e.g., 1), max linked assets per page, allowed content-types (PDF/doc only), and a **same-registered-domain (or explicitly allowlisted host) restriction** by default.
- Re-evaluate robots.txt **for the linked asset's host** before fetching; record the linked asset's own `license_type` (flag `unknown` for review, per v1.0 policy).
- Dedup by content hash across formats: after download, if the PDF's content_hash already exists (from HTML extraction or another page's link), link to the existing document instead of re-ingesting. Track the HTML↔PDF relationship in lineage.

**Warning signs:**
- Crawl requests to RFC1918 / `169.254.169.254` / internal service hostnames.
- Frontier size growing without bound during a single-source crawl.
- Ingested PDFs with `license_type=unknown` slipping past review.
- Same content_hash ingested from both an HTML page and a PDF link as two documents.

**Phase to address:** Metadata & Crawl Maturation phase (INGEST-01). Treat followed links as untrusted seed-equivalent input.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Global `sys.stdout = stderr` for all `klake` commands (not just stdio MCP) | One-line "fix" for MCP framing | Breaks/relocates normal CLI output for every other command; confuses users | Never — gate the redirect on stdio MCP transport only |
| Register tools separately per transport | Fast to get second transport working | Registry drift (Pitfall 3); OpenAPI/OpenAI defs diverge | Never — single registry from the start |
| Put domain/source into the raw-zone content-addressed key | "Storage is organized by domain" | Kills cross-domain dedup, entangles identity with mutable classification (Pitfall 4) | Never for raw zone; acceptable for derived/gold zones with lineage pointers |
| Hash raw bytes for re-crawl change detection | Reuses existing content-addressing | Thrashing on dynamic HTML → WORM bloat + spend (Pitfall 5) | Only as a coarse pre-filter *before* normalized-signature check |
| Cache recovered partial-JSON enrichment under the normal key | Avoids re-calling the LLM | Permanently poisons corpus with one-time truncation defect (Pitfall 8) | Never — flag + separate status, allow later overwrite |
| Do crawl work inside the Dagster sensor evaluation | Simpler than emitting RunRequests | Tick timeouts, skipped ticks, no idempotency (Pitfall 6) | Never — sensor emits, run executes |
| Ship SSE remote transport per the requirement text | Matches the written requirement literally | Deprecated transport; near-term rewrite; agents can't connect (Pitfall 2) | Only as a secondary/legacy endpoint alongside Streamable HTTP |
| Commit `docs/openapi.json` and hand-maintain it | Static file for agents/skills to read | Drifts from live app on every endpoint change (Pitfall 10) | Only if generated in CI and drift-checked |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| MCP stdio ↔ structlog/LiteLLM/Docling | Any of them writing to stdout corrupts JSON-RPC framing | Lock stdout to the transport; route ALL logs to stderr/file in stdio mode; suppress LiteLLM/Docling/Crawl4AI verbose output |
| MCP remote transport ↔ MCP spec | Implementing deprecated HTTP+SSE | Implement Streamable HTTP (spec 2025-11-25); keep `--sse` flag as alias if desired |
| MCP SSE/HTTP server ↔ security | No auth, permissive CORS, exposing lake mutations (add-source, export) to any origin | Require auth token; restrict CORS origins; bind to localhost by default; treat write tools as privileged |
| Qdrant client 1.18 ↔ Qdrant **server** | Query API + sparse vectors + IDF require **server ≥ 1.10**; a stale server container fails or silently degrades | Verify running server version at startup; Query API/IDF need server 1.10+, not just client 1.18 |
| Qdrant sparse vectors (RETR-01) | Prefetch `limit` < main `limit+offset` → empty/short hybrid results | Set each prefetch limit ≥ main query `limit + offset`; tune RRF fusion, don't leave defaults |
| Qdrant IDF sparse | Forgetting to enable IDF modifier in the sparse vector config → BM25-style weighting absent | Set `modifier: idf` on the sparse vector at collection creation |
| Qdrant existing collection ↔ sparse vectors | Adding sparse vectors but not backfilling existing points → hybrid search only covers new chunks (partial-collection problem) | Re-index existing points with sparse vectors via the alias-swap reindex pattern already used in v1.0; verify count parity |
| S3 object tags (STORE-02) | Assuming MinIO ≡ AWS S3 tagging semantics/limits (AWS: 10 tags, 128-char key/256-char value, tagging billed/API-limited) | Cap tag count/size to AWS limits even on MinIO; don't rely on tags for anything the registry should own; batch tag writes |
| LiteLLM finish_reason (ENRICH-01) | Inferring truncation from a JSON parse error instead of `finish_reason=length` | Read finish_reason explicitly; retry-with-more-tokens before recovering |
| Dagster sensor ↔ Postgres registry | Sensor scans full source table every tick | Cursor watermark + "due now" query; deterministic `run_key` |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Hybrid prefetch over-fetch | Slow hybrid queries; high memory | Keep prefetch limits tight (≥ limit+offset but not 10×); add payload indexes for new PAYLOAD-01 filter fields | As collection grows past ~10^5–10^6 points |
| Missing payload indexes on new filter fields | PAYLOAD-02 filters (source_name, format, tags, source_id) do full scans | Create Qdrant payload indexes for every new filterable field at collection/reindex time | As chunk count grows |
| `crawl-all` host starvation | Batch stalls with idle workers | Host-partitioned non-blocking scheduler (Pitfall 7) | Any batch with one slow/429ing host |
| Re-crawl WORM bloat | Raw-zone object count grows every schedule tick | Normalized-signature change detection (Pitfall 5) | Immediately, on any dynamic-HTML source |
| Sensor tick storm | Dagster daemon busy, skipped ticks | `minimum_interval_seconds` sized to crawl cadence; cheap evaluation | As number of scheduled sources grows |
| Re-embedding whole corpus for sparse backfill | Long reindex, cost | Sparse vectors are computed (BM25/IDF), not model-embedded — build sparse without re-calling the embedding model where possible | Large existing collection |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| MCP HTTP transport with no auth / bound to 0.0.0.0 | Any network client can trigger crawls, add sources, export datasets, run LiteLLM spend | Require auth token; default-bind localhost; separate read vs write tool permissions |
| Permissive CORS on MCP/SSE endpoint | Browser-based cross-origin calls drive lake mutations | Explicit allowlist of origins; deny by default |
| Followed-link SSRF (INGEST-01) | Crawler fetches cloud metadata / internal MinIO/Postgres/Docker services | Run every followed link + post-redirect target through the SSRF guard; block private/link-local/metadata IPs and non-http(s) schemes |
| Trusting agent/tool input to write tools | An agent (or prompt-injected page content) calls add-source/export with hostile args | Validate tool inputs via Pydantic; apply the same robots/license/SSRF guards on agent-initiated crawls as on CLI-initiated ones |
| Leaking internal paths/keys in MCP tool outputs or OpenAPI export | Exposes MinIO keys, internal hostnames, registry internals to agents | Scrub tool responses; export only the intended public schema |
| Object tags used as a trust/authorization signal | Tags are mutable and not lineage-grade | Keep authoritative classification in the registry; tags are convenience/discovery only |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Over-large tool schemas for agents (SKILL-03) | Bloated context, agent picks wrong tool, higher token cost | Keep tool descriptions/schemas lean; expose a small set of high-level tools (search, add-source, export), not every CRUD endpoint; trim Pydantic schema to essential fields |
| Search mode config (RETR-02) with silent fallback | User asks for `sparse` but gets `dense` because sparse vectors weren't built for that collection | Fail loudly (or clearly report mode used) when the requested mode's vectors are absent; expose which mode actually ran |
| `crawl-all` with no dry-run / progress | User triggers a huge batch blind; can't tell what will be crawled or budget impact | `--dry-run` listing sources + estimated scope; structured progress; `--domain` filter surfaced clearly |
| MCP tool errors as opaque failures | Agent can't recover; user sees "tool failed" | Return structured, actionable error messages (which guard tripped, which field invalid) |

## "Looks Done But Isn't" Checklist

- [ ] **MCP stdio server:** Boots and lists tools — but verify a *real* tool call that triggers enrichment/crawl/parse doesn't leak library output to stdout and break the session. Test with the actual noisy code paths, not just `list_tools`.
- [ ] **MCP remote transport:** "SSE works" — verify it's Streamable HTTP (not deprecated HTTP+SSE) and that a *current* MCP client connects, with auth + CORS configured.
- [ ] **Single tool registry:** Both transports "have the tools" — assert `stdio.list_tools() == http.list_tools()` and that OpenAPI/OpenAI exports match the same set.
- [ ] **Domain-scoped keys:** New objects land under `{zone}/{domain}/{source_id}/{hash}` — verify same-content-across-domains does NOT create duplicate raw blobs, and old v1.0 keys still resolve.
- [ ] **Object tagging:** Tags written — verify tag count/size within AWS limits (so prod S3 won't reject) and that no tag exceeds 10 tags / 128:256 chars.
- [ ] **Re-crawl change detection:** "Skips unchanged" — verify it skips a page whose only diff is a nonce/timestamp, AND that it re-ingests a page with a real content edit.
- [ ] **Dagster sensor:** Fires re-crawls — verify no duplicate concurrent runs for one source (deterministic `run_key`) and cursor advances (no tick storm).
- [ ] **Partial-JSON recovery:** Recovers truncated output — verify a recovered partial is flagged, NOT cached as a normal result, and can be overwritten by a later full run; verify finish_reason drives the decision.
- [ ] **Adaptive rate limiting:** Backs off on 429 — verify it never crawls faster than robots.txt crawl-delay and one hot host doesn't stall `crawl-all`.
- [ ] **PDF-from-crawl:** Ingests linked PDFs — verify followed links go through the SSRF guard, respect the linked host's robots/license, and dedup against the HTML source.
- [ ] **Hybrid search:** Returns results — verify sparse vectors exist for ALL points (including pre-existing ones), IDF modifier is set, and requested `search_mode` is actually honored.
- [ ] **OpenAPI export:** `docs/openapi.json` committed — verify it's regenerated from the live app in CI and drift-checked against endpoints.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| stdout pollution broke MCP sessions | LOW | Add the stdio stdout-isolation shim + self-test; gate on transport mode; re-test with noisy tool calls |
| Shipped deprecated SSE transport | MEDIUM | Add Streamable HTTP endpoint; keep SSE as legacy alias; update client configs |
| Domain-scoped keys created duplicate raw blobs | HIGH | Cannot delete from WORM raw zone; add registry-level content_hash dedup going forward, associate extra domains as tags, accept existing duplicates as sunk; fix write path so no new duplicates |
| Broken lineage pointers after key change | HIGH | Rebuild pointer map from registry content_hash ↔ old-key index; add key-scheme version; backfill resolvable pointers; never touch raw objects |
| WORM bloat from re-crawl thrashing | HIGH | Switch to normalized-signature detection; existing duplicate versions are permanent (immutability) — stop the bleeding, accept sunk storage |
| Poisoned enrichment cache (bad partials) | MEDIUM | Query cache/artifacts for `partial=True`/missing-required-field entries; invalidate + re-enrich those documents with higher max_tokens |
| Sparse vectors missing on old points | MEDIUM | Run alias-swap reindex building sparse vectors for all points; verify count parity before swap |
| Sensor duplicate/thrashing runs | LOW | Add deterministic `run_key`, fix cursor watermark, add per-source concurrency limit |

## Pitfall-to-Phase Mapping

Phases named by the four v2.0 feature groups in PROJECT.md (roadmapper may reorder/rename).

| Pitfall | Prevention Phase (feature group) | Verification |
|---------|----------------------------------|--------------|
| 1. stdout corrupts MCP stdio | AI Agent Skills (MCP-01/02) | Self-test asserts no bytes on transport fd from logging; real tool call keeps session alive |
| 2. Deprecated SSE transport | AI Agent Skills (MCP-01) | Current MCP client connects via Streamable HTTP |
| 3. Dual tool-registry drift | AI Agent Skills (MCP-01, SKILL-02/03) | `stdio.list_tools()==http.list_tools()==openapi==openai defs` |
| 4. Domain keys break dedup/lineage | MinIO Domain Segmentation (STORE-01/02/03) | Same content/two domains = one raw blob; old keys resolve; no `//`/`None` segments |
| 5. Re-crawl change-detection false pos/neg | Crawl Scheduling (SCHED-02) | Nonce-only diff skipped; real edit re-ingested; no per-tick WORM growth |
| 6. Dagster sensor idempotency | Crawl Scheduling (SCHED-01) | No duplicate active runs per source; cursor advances; no tick storm |
| 7. Adaptive limiter starvation / robots override | Metadata & Crawl Maturation (CRAWL-03) | robots crawl-delay never violated; one 429 host doesn't stall `crawl-all`; state survives resume |
| 8. Partial-JSON poisons cache | Metadata & Crawl Maturation (ENRICH-01) | Partials flagged, not cached as final; finish_reason drives recovery; overwritable |
| 9. Followed-link SSRF / explosion / scope | Metadata & Crawl Maturation (INGEST-01) | Followed links pass SSRF guard + robots/license check; bounded frontier; HTML↔PDF dedup |
| 10. OpenAPI drift | AI Agent Skills (SKILL-02) | CI regenerates + drift-checks `docs/openapi.json` |
| Qdrant partial-collection / IDF / prefetch | Hybrid Search (RETR-01/02) | Sparse vectors on all points; IDF set; prefetch ≥ limit+offset; server ≥1.10 |
| MCP HTTP auth/CORS | AI Agent Skills (MCP-01) | Auth required; CORS allowlist; localhost default bind |

## Sources

- MCP Transports specification, revisions 2025-03-26 (HTTP+SSE deprecated → Streamable HTTP) and 2025-06-18 / 2025-11-25 (stdio + Streamable HTTP standard): https://modelcontextprotocol.io/specification/2025-06-18/basic/transports [HIGH — official spec, verified]
- MCP stdio stdout-pollution / logging-to-stderr requirement: modelcontextprotocol.io transports + community writeups (chatforest.com/guides/mcp-transports-explained, startdebugging.net MCP transport guide) [HIGH — consistent across official + multiple sources]
- Qdrant 1.10 — Universal Query API, built-in IDF, sparse vectors, prefetch: https://qdrant.tech/blog/qdrant-1.10.x/ and https://qdrant.tech/documentation/search/hybrid-queries/ [HIGH — official docs; prefetch limit ≥ limit+offset and `modifier: idf` verified]
- Qdrant hybrid search / RRF fusion + prefetch semantics: https://qdrant.tech/articles/hybrid-search/ [HIGH — official]
- AWS S3 object tagging limits (10 tags/object, 128-char key, 256-char value, tagging API/cost) vs MinIO parity: AWS S3 developer guide (object tagging) [MEDIUM — well-established S3 limits]
- Dagster sensors: `run_key` idempotency, cursor persistence, evaluation interval: docs.dagster.io (sensors) [MEDIUM — official docs + v1.0 team experience]
- LiteLLM `finish_reason`/truncation, budget/cooldown behavior: docs.litellm.ai [MEDIUM — carried from v1.0 PITFALLS, still applicable]
- This system's v1.0 PITFALLS.md and PROJECT.md constraints (immutability, content-addressing, lineage, LiteLLM-only, structlog) [HIGH — internal, authoritative]

---
*Pitfalls research for: Knowledge Lake Framework v2.0 Agent-Ready Lake*
*Researched: 2026-07-08*
