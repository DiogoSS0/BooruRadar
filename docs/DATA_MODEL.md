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

### `booru_snapshots`

Append-only site observations associated with a crawl run. Health and capabilities
have explicit provenance columns. Open-ended public statistics are stored in the
`metrics` JSONB object using the metric envelope below.

### `tags`

Stable, booru-scoped tag identity. The same tag name on two boorus is intentionally
two records because source categories and counts can differ.

### `tag_snapshots`

Append-only tag observations associated with a crawl run. The frequently queried
`post_count` is a typed `BIGINT` paired with `post_count_provenance`. Less common future
tag metrics use the same JSONB metric envelope as booru snapshots.

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
  },
  "monthly_visitors": {
    "value": 80000,
    "provenance": "estimated",
    "unit": "visitors"
  }
}
```

A snapshot-wide provenance flag is intentionally avoided because one snapshot may
combine observed and estimated values.

## Retention and deletion

Snapshots are append-only application records. Foreign keys cascade only when their
owning booru, tag, or crawl run is deliberately deleted. No cleanup or retention job
is included in Milestone 0.
