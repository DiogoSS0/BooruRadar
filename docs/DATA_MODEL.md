# Data Model

PostgreSQL is the application datastore. SQLAlchemy 2 declares the current model and
Alembic is the only supported way to change deployed schemas.

## Entities

### `boorus`

Stable identity for a monitored site. `canonical_url` is unique. `adapter_family` is
a string rather than a database enum so new and custom families do not require an
enum migration. `adapter_name` identifies the concrete registered implementation.

### `crawl_runs`

Operational record for one adapter attempt against one booru. The status lifecycle is
`pending`, `running`, then one of `succeeded`, `failed`, or `cancelled`. Error text and
small structured execution details belong here; collected statistics do not.

For both current collection families, `details` stores the adapter/version, endpoint
identifiers, HTTP status, bounded content type, SHA-256 response fingerprint, and
quality status/flags. The hash is only a fingerprint: response bodies are not
archived and cannot be reconstructed from it. Details and sanitized error messages
contain neither raw payload text, media URLs, nor image data.

Collection persists attempts in two phases. A `running` crawl run is committed before
remote inspection. An accepted snapshot and the transition to `succeeded` are then
committed together. On failure, candidate work is rolled back and the durable run is
reloaded, marked `failed`, and committed with bounded evidence and a sanitized error.

### `booru_snapshots`

Append-only site observations associated with a crawl run. Health and capabilities
have explicit provenance columns. Open-ended public statistics are stored in the
`metrics` JSONB object using the metric envelope below.

`source_url` identifies the public aggregate endpoint used for the observation; it is
not a media URL. Each `(booru_id, crawl_run_id)` pair is unique, and historical reads
are indexed by booru and capture time.

### `tags`

Stable, booru-scoped tag identity. The same tag name on two boorus is intentionally
two records because source categories and counts can differ.

### `tag_snapshots`

Append-only tag observations associated with a crawl run. The frequently queried
`post_count` is a typed `BIGINT` paired with `post_count_provenance`. Other tag metrics
use the same JSONB metric envelope as booru snapshots.

## Metric provenance

Every metric records one evidence class:

- `observed`: read directly from a public source;
- `estimated`: derived or sampled and not an exact source value;
- `owner_verified`: explicitly supplied or verified by the site owner.

Supporting `owner_verified` as provenance does not implement users, authentication,
or an ownership-claim workflow. It only makes the metric representation forward
compatible.

JSONB metric maps are validated with Pydantic before persistence and have this shape:

```json
{
  "total_posts": {
    "value": 125000,
    "provenance": "observed",
    "unit": "posts"
  }
}
```

A snapshot-wide provenance flag is intentionally avoided because one snapshot may
combine observed and estimated values.

The current collection policies are explicit per adapter family: Danbooru accepts an
`estimated` `total_posts` value in `posts`, while Safebooru through the Gelbooru
family accepts an `observed` value in `posts`. The stored envelope retains that
difference for API responses and analytics.

## Compatible history

Historical comparisons are always scoped to one `booru_id`.

For collection anomaly protection, only the latest snapshot is considered as a
baseline. Its `total_posts` value must be a valid non-negative integer with the
provenance and unit required by the active target policy. Incompatible history is
ignored as a baseline rather than coerced or compared across evidence classes.

For growth, the latest two snapshots must both have valid non-negative integer
`total_posts` values, the `posts` unit, matching provenance, and a strictly increasing
capture interval. Danbooru therefore normally compares estimated with estimated;
Safebooru normally compares observed with observed. Mixed provenance and malformed or
invalid intervals yield an unavailable result. Growth is normalized to a 24-hour
rate from the actual elapsed time, and the stats path performs no writes.

## Retention and deletion

Snapshots are append-only application records. Foreign keys cascade only when their
owning booru, tag, or crawl run is deliberately deleted. No cleanup or retention job
is included in the current slice.
