# Ranking Readiness

## Scope

Recurring accepted snapshots make BooruRadar's history structurally suitable for a
first ranking API. This document is an implementation plan, not a ranking feature.
It deliberately excludes a global Booru Score and any speculative Trending Score.

## Reusable foundation

No ranking table or migration is currently required:

- `BooruSnapshot` stores `booru_id`, timezone-aware `captured_at`, and JSONB metrics,
  with an index on `(booru_id, captured_at)`;
- `MetricEnvelope` and `MetricMap` retain value, unit, and provenance;
- `calculate_growth_metrics()` already rejects cross-booru pairs, malformed values,
  mismatched provenance or units, and non-positive time intervals, then returns the
  real elapsed hours, delta, posts/day, and provenance;
- `CatalogReadService._project_total_posts()` safely rejects malformed public metric
  envelopes;
- `CatalogReadService.compare()` demonstrates a single window query using
  `row_number()` partitioned by booru and deterministic snapshot order
  (`captured_at DESC, id DESC`);
- existing API schemas use discriminated available/unavailable responses.

One valid snapshot is enough for largest-by-total eligibility. Growth modes require
two latest compatible accepted observations. A target does not become eligible merely
because the scheduler exists.

## Proposed modes

1. `largest`: latest valid `total_posts`, descending.
2. `fastest_growth`: existing normalized `posts_per_day`, descending.
3. `relative_growth`:

   ```text
   (posts_delta / previous_total_posts) * (24 / elapsed_hours) * 100
   ```

   Unit: `percent/day`. A zero previous value is explicitly ineligible.

Negative deltas and genuine zero deltas remain valid results. Missing or incompatible
history is unavailable, not numeric zero. Do not interpolate or skip an incompatible
latest observation to cherry-pick an older pair in the first version.

## Suggested endpoint

```text
GET /api/v1/rankings?mode=largest|fastest_growth|relative_growth&limit=50&offset=0
```

Suggested top-level fields:

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

`total` and `eligible_count` describe the complete enabled-source result set before
pagination.

Each item should be a discriminated `eligible` or `ineligible` record. Eligible items
carry the global rank, mode-specific value, provenance, relevant snapshot IDs and
timestamps, and elapsed hours for growth modes. Ineligible items use `rank: null` and
a stable reason such as:

- `missing_total_posts`;
- `insufficient_history`;
- `incompatible_provenance`;
- `incompatible_unit`;
- `invalid_time_interval`;
- `zero_baseline`.

Do not expose raw metrics JSON, crawl evidence, snapshot source/evidence endpoint URLs,
or media fields. A booru's canonical public site URL remains part of its catalog data.

## Query and ranking strategy

Extend `CatalogReadService` rather than introduce a separate ranking subsystem:

1. Load enabled boorus and at most their newest two snapshots in one database query,
   reusing the comparison window-query pattern.
2. Validate metric envelopes and calculate growth in Python with the existing safe
   projection and analytics functions. Add a small typed pre-validation result for
   stable ineligibility reasons; do not derive public reason codes by parsing exception
   messages.
3. Build the complete enabled-source result set before pagination.
4. Order eligible entries first by numeric value descending, then
   `lower(booru.name)` ascending, then booru UUID ascending.
5. Assign unique global ranks after deterministic ordering and before `offset` and
   `limit` are applied. Order ineligible entries after eligible entries by reason,
   `lower(booru.name)`, then booru UUID before applying pagination.
6. Return ineligible entries explicitly rather than dropping them or filling zeros.

The first version should preserve latest-pair semantics. If later performance data
justifies moving ranking calculations into SQL or materialized views, do so without
changing the public eligibility and provenance contract.

## Provenance rules

Ranking never promotes `estimated` to `observed`. `largest` returns the latest metric's
provenance. Growth modes require matching provenance and return that shared value.
Danbooru will normally rank with `estimated`; Safebooru will normally rank with
`observed`. Cross-provenance growth is ineligible.

## Test strategy

Add focused coverage for:

- all three modes and units;
- descending order and deterministic ties;
- global rank assignment before pagination;
- disabled boorus excluded;
- a single bounded query rather than N+1 reads;
- missing/malformed totals and insufficient history explicitly ineligible;
- incompatible provenance/unit and invalid timestamps explicitly ineligible;
- estimated Danbooru provenance retained;
- zero baseline for relative growth;
- negative and genuine zero deltas valid;
- unavailable growth never serialized as zero;
- PostgreSQL ordering when snapshot timestamps tie;
- OpenAPI discrimination, pagination bounds, and absence of unsafe fields.

## Recommended next implementation step

Add the three-mode read-only method to `CatalogReadService` plus typed API schemas and
the endpoint above, reusing the existing latest-two window query and analytics
validation. Do not add a ranking table or Trending Score until measurements show a
need and enough trustworthy history exists.
