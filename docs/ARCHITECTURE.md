# Architecture

## Scope

BooruRadar is a metadata-only monitoring application. The current slice supports
a production-ready one-shot Danbooru collector, explicit manual Safebooru collection,
accepted snapshot history, compatible growth analytics, a read-only public catalog
and ranking API, and a dashboard served by that API.

The system stores normalized aggregate metadata and bounded response evidence. It
does not download or persist image/video bytes, direct media URLs, or raw response
bodies.

## Dependency direction

```text
browser dashboard ──> apps/api routes ──> catalog service ──> models
Railway cron (when enabled) ──> collect CLI ──> collection service ──> adapters
manual collect CLI ───────────> target registry ──> collection service ──> adapters
manual stats CLI ────────────────────────> analytics service ──> models
apps/worker ─────────────────────────────> unused compatibility shell

core <── shared configuration, persistence setup, enums, and logging
```

- `apps` owns deployable entry points, HTTP routes, and dashboard assets.
- `services` coordinates collection, quality, analytics, and read projections.
- `adapters` translates public remote APIs into family-neutral Pydantic objects.
- `models` owns SQLAlchemy persistence and metric envelopes.
- `core` contains cross-cutting configuration, database, enum, and logging support.

The dashboard talks to the API rather than the database. API routes and the worker do
not import each other. Family-specific response parsing stays inside adapters;
family-specific acceptance requirements are explicit collection policies.

## Runtime surfaces

### API and dashboard

`apps.api.main` creates one FastAPI application with:

- `GET /` for the read-only dashboard and `/assets/*` for its local static assets;
- `GET /health` for liveness and `GET /health/ready` for PostgreSQL readiness;
- `/docs` for OpenAPI documentation;
- `/api/v1/boorus`, `/api/v1/boorus/{booru_id}`,
  `/api/v1/boorus/{booru_id}/snapshots`, and
  `/api/v1/boorus/{booru_id}/growth` for bounded catalog projections;
- `/api/v1/compare` for two to eight unique enabled booru IDs;
- `/api/v1/rankings` for largest, absolute-growth, and relative-growth rankings over
  all enabled boorus.

Catalog operations are read-only. A comparison calculates growth independently
within each selected booru; it never treats two different boorus as a historical
pair. Malformed or incompatible snapshot metrics are projected as absent or
unavailable rather than passed through as raw data.

### Collection processes, manual CLIs, and worker

`python -m booruradar.collect danbooru` and
`python -m booruradar.collect safebooru` are explicit one-shot collection entry
points. `python -m booruradar.stats danbooru` and
`python -m booruradar.stats safebooru` are read-only analytics entry points.

Production uses a dedicated `collector-danbooru` Railway service. The web and
collector processes share the same PostgreSQL history database but have separate
lifecycles. The collector has no HTTP domain or healthcheck, exits after each
attempt, and uses a `NEVER` restart policy.

Railway scheduling may invoke only the explicit Danbooru target after a successful
remote validation. Safebooru remains manual and cannot be included implicitly
through a generic schedule. `apps.worker.main` remains an unused compatibility shell,
not the production scheduler. See
[the production collection runbook](production-collection.md).

## Metadata and adapter boundary

All remote I/O is asynchronous and uses an injected `httpx.AsyncClient`. The adapter
contract permits only:

- site detection;
- health checking;
- capability discovery;
- public aggregate statistics;
- recent post metadata;
- tag statistics.

Recent-post DTOs contain an external ID, optional creation time, rating, tag names,
and an optional HTML post-page URL. They contain no image bytes or direct media URL
fields. Response bodies may be parsed transiently, but they do not cross the adapter
boundary or enter persistence, CLI output, API responses, or the dashboard.

The explicit target registry binds a key and canonical URL to an adapter family,
concrete adapter, and `SnapshotCollectionPolicy`. Construction rejects mismatches
between those parts. The current policies require:

- Danbooru: `total_posts` is a non-negative integer with `estimated` provenance and
  the `posts` unit;
- Safebooru through the Gelbooru family: `total_posts` is a non-negative integer with
  `observed` provenance and the `posts` unit.

## Collection, quality, and durability

The accepted path is:

```text
target → normalized inspection → policy validation → compatible-baseline anomaly check
       → accepted BooruSnapshot
```

Impossible values, malformed normalized structures, wrong provenance, and wrong
units are **hard invalid**. They fail the run and never create a snapshot.
Structurally valid values can be **suspicious** when they change catastrophically
from compatible history; those values are also blocked.

An anomaly baseline is scoped to the selected `booru_id`. The service examines the
latest accepted snapshot, but the target policy accepts its `total_posts` as a
baseline only when value, provenance, and unit are compatible. An incompatible
latest metric is ignored rather than compared across provenance or boorus. The
current injectable anomaly policy blocks a drop below half the previous value when
the absolute drop is at least 100,000 posts, or growth above five times the previous
value when the absolute increase is at least 1,000,000 posts. Ordinary decreases are
otherwise permitted.

Collection uses two durable transaction phases:

1. Create and commit a `running` `CrawlRun` before remote inspection, so an attempt is
   visible independently of its final outcome.
2. After validation succeeds, add the snapshot, mark the run `succeeded`, and commit
   both together. On an ordinary failure, roll back candidate work, reload the durable
   run, mark it `failed` with sanitized details, and commit that terminal state.
   Explicit async task cancellation after the durable `running` commit reconciles the
   final commit before recording `cancelled`.

This sequence prevents a rejected candidate or failed final commit from leaving an
accepted snapshot behind. Site health remains in `BooruSnapshot.health_status`;
observation quality remains separately recorded in `CrawlRun.details`.

Each adapter response contributes bounded evidence: an endpoint identifier, HTTP
status, truncated content type, and SHA-256 fingerprint. The fingerprint supports
response equality/change checks without archiving or reconstructing the body.
Evidence and error summaries exclude payload text, media URLs, and image data.

## Collection interval and analytics compatibility

The one-shot collection CLI queries the latest snapshot for the selected booru. If it
is less than 20 hours old, collection exits as skipped before HTTP or service work.
`--force` bypasses only this interval; policy validation and anomaly protection still
run.

Growth uses the latest two snapshots for one booru and requires both `total_posts`
metrics to be non-boolean, non-negative integers with the `posts` unit and identical
provenance. The current timestamp must be strictly later than the previous timestamp.
Danbooru normally yields compatible `estimated` pairs; Safebooru normally yields
compatible `observed` pairs. Mixed provenance, cross-booru pairs, malformed values,
or invalid time intervals produce an explicit unavailable result. Available growth
is normalized to 24 hours from the real elapsed interval.

## Ranking read path

The route layer validates ranking mode and pagination and serializes a typed,
mode-discriminated response. `CatalogReadService` owns eligibility, ordering, global
rank assignment, and pagination. The analytics layer owns the pure absolute and
relative calculations.

One window query loads all enabled boorus and at most their newest two snapshots,
using `row_number()` per booru with `captured_at DESC, id DESC`. Python then validates
the metric envelopes and calculates rankings without any per-booru database reads.
Eligible entries are sorted by value, case-insensitive name, and UUID; ranks are
assigned before ineligible entries are appended and before pagination is applied.
Ineligible entries sort deterministically by reason, name, and UUID.

Largest rankings need one valid latest total. Growth rankings use exactly the newest
pair and never search older history when that pair is incompatible. Matching
provenance and `posts` units are required, and provenance is returned unchanged.
Negative and genuine zero growth remain eligible, while missing/incompatible history
has no numeric value. Relative growth uses the actual elapsed interval and treats a
zero previous total as explicitly ineligible. The endpoint remains read-only and
exposes neither raw metric JSON nor crawl, response, source-endpoint, or media data.
See [the Ranking API V1 contract](ranking-readiness.md).

## Configuration and operational boundaries

Configuration comes from `BOORURADAR_*` environment variables and optionally `.env`.
`BOORURADAR_DATABASE_URL` selects the runtime application/history database for the
API, collection, and stats commands. The opt-in PostgreSQL tests must use a separate,
migrated, disposable `booruradar_integration` database. Their cleanup rechecks the
actual database name and deletes only UUID-scoped test rows;
`BOORURADAR_RUN_POSTGRES_TESTS=1` keeps them skipped by default.

The Railway `web` and `collector-danbooru` services use the same Postgres service
through environment-variable references. Provider-style `postgres://` and
`postgresql://` URLs are normalized to the installed async psycopg driver. Resolved
database credentials are never stored in repository configuration or documentation.

Standard-library logging writes timestamped records to stdout. The current product
has no user or authentication model, ownership-claim workflow, payment system,
recommendation engine, global score, image pipeline, or NekoPrice integration. The
included dashboard is a read-only view over the local catalog API.
