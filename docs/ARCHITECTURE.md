# Architecture

## Scope

Milestone 0 is a backend foundation for collecting public booru metadata. It creates
stable seams for later site-family implementations and scheduling while leaving all
product features outside the milestone unimplemented.

## Dependency direction

```text
apps/api ─────┐
              ├──> services ──> adapters
apps/worker ──┘         │
                        └──────> models

core <── shared configuration, persistence setup, enums, and logging
```

- `apps` contains deployable process entry points and transport concerns.
- `services` coordinates use cases and depends on contracts, not FastAPI routes.
- `adapters` translates public remote APIs into family-neutral Pydantic objects.
- `models` owns SQLAlchemy persistence and the Pydantic metric envelope.
- `core` contains small cross-cutting infrastructure modules.

The API and worker never import each other. Site-family checks stay inside concrete
adapters rather than spreading across routes or services.

## Runtime processes

### API

`apps.api.main` creates the FastAPI application. Milestone 0 exposes process liveness
and PostgreSQL readiness only. Feature routes will be added when corresponding use
cases exist.

### Worker

`apps.worker.main` supplies signal handling and a polling shell. It performs no crawl
until a later milestone adds scheduling. The registered Danbooru adapter and first
snapshot service are invoked explicitly; they are not a production scheduler.

## Collection boundary

All remote I/O in an adapter is asynchronous and uses an injected
`httpx.AsyncClient`. Injection centralizes later timeout, retry, rate-limit, and test
policies. Runtime persistence uses SQLAlchemy 2 `AsyncSession` objects, while Alembic
uses a synchronous administrative connection for predictable migrations.

The adapter contract permits only:

- site detection;
- health checking;
- capability discovery;
- public aggregate statistics;
- recent post metadata;
- tag statistics.

Recent-post DTOs contain identifiers, timestamps, ratings, tag names, and an optional
HTML post URL. There are deliberately no image bytes, image URLs, download methods, or
media-storage fields.

## First snapshot quality boundary

The modern Danbooru path is:

```text
public API → normalized adapter result → candidate validation → anomaly check
           → accepted BooruSnapshot
```

Impossible values and malformed required structures are **hard invalid**. They fail
the crawl and never create a snapshot. Structurally valid values can be
**suspicious** when they differ catastrophically from the latest accepted
`total_posts`; they are also blocked, but remain distinct from hard-invalid data.
The hard gate requires `total_posts` to be a non-boolean, non-negative integer with
`estimated` provenance and `posts` as its unit; the adapter applies corresponding
shape/type checks before constructing normalized post and tag metadata.
Because Danbooru's count is estimated, ordinary decreases are allowed. The initial
bootstrap policy blocks a drop below half the previous value only when the absolute
drop is at least 100,000 posts, or growth above five times the previous value only
when the absolute increase is at least 1,000,000 posts. These injectable thresholds
are not a universal trust rule.

Site health remains in `BooruSnapshot.health_status`. Observation quality is recorded
separately in `CrawlRun.details` and is never encoded as a health value.

## Extension model

`AdapterRegistry` accepts any concrete `BooruAdapter`. Built-in implementations will
live under the `danbooru`, `gelbooru`, and `shimmie` namespaces. One-off integrations
live under `custom`. This is an explicit in-process registry; dynamic plugin loading
is deferred until a real deployment requires it.

Canonical URL uniqueness does not solve aliases, historical domains, API hostnames,
redirects, or `www` variants. Alias modeling remains required before broad automatic
discovery, but is intentionally deferred together with scheduling.

## Configuration and logging

Configuration is read from `BOORURADAR_*` environment variables and optionally a
local `.env` file. `.env.example` documents non-secret development defaults. Standard
library logging writes timestamped records to stdout so container runtimes can
collect them without a file-based log lifecycle.

## Deliberate exclusions

There is no frontend, user or authentication model, Claim Your Booru flow, payment,
recommendation engine, global score, image pipeline, or NekoPrice integration. These
boundaries prevent premature schema and service coupling.
