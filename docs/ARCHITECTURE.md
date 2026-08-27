# Architecture

## Scope

BooruRadar is a metadata-only monitoring application. The current slice supports
manual collection from Danbooru and Safebooru, accepted snapshot history, compatible
growth analytics, a read-only public catalog API, and a dashboard served by that API.

The system stores normalized aggregate metadata and bounded response evidence. It
does not download or persist image/video bytes, direct media URLs, or raw response
bodies.

## Dependency direction

```text
browser dashboard ──> apps/api routes ──> catalog service ──> models
manual collect CLI ──> target registry ──> collection service ──> adapters
manual stats CLI ────────────────────────> analytics service ──> models
apps/worker ─────────────────────────────> empty scheduling shell

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
- `/api/v1/compare` for two to eight unique enabled booru IDs.

Catalog operations are read-only. A comparison calculates growth independently
within each selected booru; it never treats two different boorus as a historical
pair. Malformed or incompatible snapshot metrics are projected as absent or
unavailable rather than passed through as raw data.

### Manual CLIs and worker

`python -m booruradar.collect danbooru` and
`python -m booruradar.collect safebooru` are the collection entry points.
`python -m booruradar.stats danbooru` and
`python -m booruradar.stats safebooru` are read-only analytics entry points.

`apps.worker.main` remains an empty polling shell. Safebooru is not scheduled, and
this slice adds or changes no systemd service or timer. Collection is manual unless
an operator invokes the CLI externally.

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
   both together. On any failure, roll back candidate work, reload the durable run,
   mark it `failed` with sanitized details, and commit that terminal state.

This sequence prevents a rejected candidate or failed final commit from leaving an
accepted snapshot behind. Site health remains in `BooruSnapshot.health_status`;
observation quality remains separately recorded in `CrawlRun.details`.

Each adapter response contributes bounded evidence: an endpoint identifier, HTTP
status, truncated content type, and SHA-256 fingerprint. The fingerprint supports
response equality/change checks without archiving or reconstructing the body.
Evidence and error summaries exclude payload text, media URLs, and image data.

## Collection interval and analytics compatibility

The manual collection CLI queries the latest snapshot for the selected booru. If it
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

## Configuration and operational boundaries

Configuration comes from `BOORURADAR_*` environment variables and optionally `.env`.
`BOORURADAR_DATABASE_URL` selects the runtime application/history database for the
API, collection, and stats commands. The opt-in PostgreSQL tests must use a separate,
migrated, disposable `booruradar_integration` database. Their cleanup rechecks the
actual database name and deletes only UUID-scoped test rows;
`BOORURADAR_RUN_POSTGRES_TESTS=1` keeps them skipped by default.

Standard-library logging writes timestamped records to stdout. The current product
has no user or authentication model, ownership-claim workflow, payment system,
recommendation engine, global score, image pipeline, or NekoPrice integration. The
included dashboard is a read-only view over the local catalog API.
