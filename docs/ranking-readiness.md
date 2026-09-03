# Ranking API V1

## Scope

BooruRadar exposes an auditable, read-only ranking API over accepted snapshot
history:

```text
GET /api/v1/rankings?mode=largest|fastest_growth|relative_growth&limit=50&offset=0
```

This contract deliberately excludes composite, Trending, Popularity, and global
Booru scores. The API ranks only metrics that can be explained directly from stored
observations. No ranking table, cache, materialized view, or schema migration is
required for V1.

## Response contract

The top-level response is discriminated by `mode` and includes:

```json
{
  "mode": "fastest_growth",
  "unit": "posts/day",
  "total": 2,
  "eligible_count": 1,
  "limit": 50,
  "offset": 0,
  "items": []
}
```

`total` is the number of enabled sources considered and `eligible_count` is the
number eligible for the selected mode. Both describe the complete result set before
pagination.

Items use an `eligible` discriminator. Eligible records contain a unique global
rank, public booru identity, value, unit, provenance, and the relevant latest
snapshot ID and timestamp. Growth records also contain the previous snapshot ID and
timestamp, elapsed hours, and post delta. Ineligible records contain public identity,
`rank: null`, `eligible: false`, and a stable reason; they do not contain a fake or
nullable metric value.

The projection never exposes raw metrics JSON, crawl evidence, response fingerprints,
source endpoint URLs, media URLs, or raw response data. A booru's canonical public
site URL remains part of its existing catalog identity.

## Modes and formulas

### `largest`

The newest snapshot must contain a valid non-boolean, non-negative integer
`total_posts` metric with unit `posts` and recognized stored provenance. One valid
snapshot is enough. Eligible sources sort by:

```text
total_posts DESC, lower(name) ASC, booru UUID ASC
```

The response unit is `posts`, and the provenance is copied unchanged from the latest
metric.

### `fastest_growth`

The newest two snapshots must form a compatible pair under
`calculate_growth_metrics()`: same booru, valid `total_posts` values, `posts` units,
matching provenance, and a strictly positive elapsed interval. The value is:

```text
posts_delta * 24 / elapsed_hours
```

The response unit is `posts/day`. Negative growth and a genuine zero delta remain
eligible numeric results.

### `relative_growth`

This mode has the same latest-pair compatibility requirements and uses:

```text
(posts_delta / previous_total_posts) * (24 / elapsed_hours) * 100
```

The response unit is `percent/day`. A previous total of zero is explicitly
ineligible with `zero_baseline`. Negative growth and genuine `0%/day` remain eligible.
Calculations and sorting use full Python float precision; the service does not round,
clamp, interpolate, or pre-format values.

## Latest-pair semantics

Growth modes inspect exactly the newest two accepted snapshots, ordered by:

```text
captured_at DESC, snapshot UUID DESC
```

If that pair is incompatible, V1 reports the corresponding ineligibility reason. It
never searches farther backwards for a convenient compatible pair. This prevents
history cherry-picking and makes every result reproducible.

## Ineligibility reasons

Stable public reason codes are:

- `missing_total_posts`: a required latest metric is absent, or no snapshot exists
  for `largest`;
- `invalid_total_posts`: a metric envelope, provenance, or value is malformed;
- `insufficient_history`: a growth mode has fewer than two snapshots;
- `incompatible_provenance`: the newest pair has different provenance;
- `incompatible_unit`: a required metric does not use `posts`;
- `invalid_time_interval`: the newest timestamp is not strictly later than the
  previous timestamp, or the timestamps are incompatible;
- `zero_baseline`: relative growth would divide by a previous total of zero.

These codes come from typed validation outcomes, not parsed exception text. Missing
or incompatible history is never converted to numeric zero and is never silently
omitted.

## Ordering, ranks, and pagination

The service first evaluates every enabled source. Eligible entries sort by value
descending, then case-insensitive name ascending, then UUID ascending. It assigns
unique sequential ranks (`1, 2, 3`) after that deterministic order; it does not use
competition ranks.

Ineligible entries follow all eligible entries and sort by reason, case-insensitive
name, then UUID. Only after the complete ordered result exists does the service apply
`offset` and `limit`. A page beginning at offset 10 therefore retains its global
ranks rather than restarting at one.

## Query strategy

`CatalogReadService.rank_boorus()` performs one database query. A `row_number()`
window partitions snapshots by `booru_id`, orders by `captured_at DESC, id DESC`, and
the outer join retains at most rows one and two for each enabled booru. Metric
validation and calculations then happen in Python through the shared analytics
logic. There is no per-booru query and no N+1 read pattern.

The shape is appropriate for hundreds or low thousands of sources. A future storage
or caching optimization must preserve this public eligibility, ordering, provenance,
and latest-pair contract.

## Provenance and data integrity

`largest` returns the exact provenance stored on its latest valid metric. Growth
modes require both newest metrics to have the same provenance and return that shared
value. `estimated` is never promoted to `observed`, and `owner_verified` remains a
distinct value. No historical values are interpolated or fabricated.

Tests cover all modes and units, ordering and ties, rank-before-pagination, stable
ineligibility, genuine zero and negative growth, provenance preservation, a single
query, unsafe-field exclusion, OpenAPI discrimination, and PostgreSQL-specific
window and UUID tie ordering.
