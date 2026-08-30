# Production Danbooru Collection

## Scope

Production collection runs as a one-shot Railway process that records normalized
Danbooru metadata in the same PostgreSQL database used by the public web service.
Only Danbooru may be scheduled. Safebooru remains an explicit manual target.

BooruRadar does not bypass Cloudflare, download or store media, persist direct media
URLs, retain raw response bodies, or expose credentials.

## Runtime architecture

```text
GitHub main
├── web
│   └── FastAPI and dashboard ───────────────┐
└── collector-danbooru                       │
    └── one-shot collection CLI ──> Danbooru │
                                             v
                                      Railway PostgreSQL
```

The processes have separate responsibilities:

- `web` serves HTTP traffic and reads public catalog projections;
- `collector-danbooru` performs one collection attempt and exits;
- PostgreSQL stores durable crawl-run evidence and accepted snapshots.

The collector has no public domain, HTTP server, or healthcheck. Its restart policy is
`NEVER`, so an upstream or database failure is not turned into a restart loop.
`apps.worker` remains an unused compatibility shell; production invokes the one-shot
CLI directly.

## Railway service configuration

| Setting | Value |
| --- | --- |
| Service | `collector-danbooru` |
| Repository | `DiogoSS0/BooruRadar` |
| Branch | `main` |
| Start command | `python -m booruradar.collect danbooru` |
| Restart policy | `NEVER` |
| Healthcheck | none |
| Public domain | none |
| Environment | `production` |

Configure these variables:

| Variable | Required | Purpose |
| --- | --- | --- |
| `BOORURADAR_DATABASE_URL` | yes | Reference to the existing Railway Postgres service |
| `BOORURADAR_ENVIRONMENT=production` | yes | Select production configuration |
| `BOORURADAR_DEBUG=false` | yes | Disable debug behavior |
| `BOORURADAR_LOG_LEVEL=INFO` | yes | Select normal operational logging |
| `BOORURADAR_HTTP_TIMEOUT_SECONDS` | no | Override the bounded upstream timeout |
| `DANBOORU_LOGIN` | no | Official Danbooru account login |
| `DANBOORU_API_KEY` | no | Official Danbooru API key |

Use the Railway reference `${{Postgres.DATABASE_URL}}` for
`BOORURADAR_DATABASE_URL`. Provider-style PostgreSQL schemes are normalized by
`Settings`; never copy the resolved password or URL into files, docs, commands, or
logs.

Danbooru authentication uses HTTP Basic Auth only when both credential variables are
present and non-blank. Partial configuration remains unauthenticated. Credentials
never belong in endpoint query strings. The polling worker's interval setting does
not apply to this service.

## Collection command

Run one local collection against an explicitly configured development database:

```bash
.venv/bin/python -m booruradar.collect danbooru
```

The command checks the newest accepted Danbooru snapshot before an upstream request.
When it is less than 20 hours old, the command exits successfully as skipped.
`--force` bypasses only that interval:

```bash
.venv/bin/python -m booruradar.collect danbooru --force
```

It does not bypass provenance, normalization, anomaly protection, source-access
classification, or concurrent-run exclusion. Production cron must not use `--force`.
Do not point local commands at production or retained history without explicit
authorization.

## Concurrent invocation safety

Before booru creation, the interval query, or HTTP, collection attempts to acquire a
target-scoped PostgreSQL advisory lock on a dedicated connection. It stays held
across the collector's deliberate transaction commits. If another collector owns
the same target lock, the second invocation makes no upstream request or snapshot and
reports:

```text
COLLECTION=SKIPPED
TARGET=danbooru
REASON=collection_in_progress
```

Different explicit targets use different locks. `--force` never bypasses the lock.

## Result interpretation

A successful accepted observation reports:

```text
COLLECTION=SUCCEEDED
TARGET=danbooru
BOORU=Danbooru
SNAPSHOT_ID=<uuid>
CAPTURED_AT=<timestamp>
TOTAL_POSTS=<integer>
PROVENANCE=estimated
UNIT=posts
```

A recent accepted observation reports `COLLECTION=SKIPPED` with
`REASON=minimum_interval` and `LAST_SNAPSHOT_AT`. An overlapping invocation reports
the skip reason above. An actual failure reports `COLLECTION=FAILED`, the target, and
an allowlisted diagnostic category.

Successful and skipped outcomes exit zero. Failures exit non-zero. A fixed
`CLEANUP=FAILED` warning can follow a terminal result if post-outcome client, session,
lock, or engine cleanup fails; it never changes a committed success into a collection
failure or prints the underlying exception. Diagnose that warning before scheduling.
Output never contains credentials, authorization headers, resolved database URLs,
response bodies, or media URLs. Danbooru `total_posts` remains `estimated` by design.

## First remote run

Do not configure cron until the remote path is validated:

1. Confirm the collector points to the tested `main` commit and existing Postgres.
2. Confirm its command, no-domain state, absent healthcheck, and `NEVER` restart.
3. Start one collector deployment.
4. Inspect logs for exactly one terminal result.
5. Accept only `SUCCEEDED` or a legitimate `SKIPPED` due to the minimum interval.
6. Verify the production database with read-only queries.
7. Configure cron only after these checks pass.

Inspect a known deployment without listing service variables:

```bash
railway logs <deployment-id> \
  --service collector-danbooru \
  --environment production \
  --lines 200 \
  --json
```

Do not use `railway up` as a deployment workaround, and do not redeploy `web` to run
collection. Do not use variable-listing commands that print resolved values.

## Database verification

Use a trusted PostgreSQL console and an explicitly read-only transaction:

```sql
BEGIN READ ONLY;

SELECT
    b.name,
    s.id AS snapshot_id,
    s.captured_at,
    s.metrics -> 'total_posts' AS total_posts,
    r.status AS crawl_run_status
FROM boorus AS b
JOIN booru_snapshots AS s ON s.booru_id = b.id
JOIN crawl_runs AS r ON r.id = s.crawl_run_id
WHERE b.canonical_url = 'https://danbooru.donmai.us'
ORDER BY s.captured_at DESC, s.id DESC
LIMIT 1;

SELECT
    b.name,
    count(s.id) AS snapshot_count,
    max(s.captured_at) AS latest_snapshot_at
FROM boorus AS b
LEFT JOIN booru_snapshots AS s ON s.booru_id = b.id
WHERE b.canonical_url IN (
    'https://danbooru.donmai.us',
    'https://safebooru.org'
)
GROUP BY b.id, b.name
ORDER BY lower(b.name), b.id;

COMMIT;
```

Compare counts immediately before and after the first attempt. Success creates one
accepted Danbooru snapshot and succeeded crawl run; a minimum-interval skip creates
nothing; failure creates no accepted snapshot. No attempt may create Safebooru
history. Never repair failure by fabricating a snapshot or rerunning the historical
import.

## Schedule

Only after remote and database validation, configure:

```text
17 3 * * *
```

Railway cron uses UTC. This is 03:17 in Lisbon during standard time and 04:17 during
daylight-saving time. It stays fixed in UTC when Lisbon changes offset. A daily run
comfortably exceeds the 20-hour interval. Attach it only to `collector-danbooru`;
never schedule Safebooru or replace the command with generic target fan-out.

## Failure handling

- **Source blocked:** HTTP 403 or `cf-mitigated: challenge` is a source-access
  failure, not malformed data. There is no retry or bypass. If appropriate, add both
  official credential variables as Railway secrets and validate one new attempt.
- **Timeout/upstream failure:** allow the next daily attempt after recovery; do not
  add an aggressive retry loop.
- **Malformed or suspicious data:** do not coerce or insert a replacement value.
  Investigate the source shape or policy while preserving failed-run evidence.
- **Database failure:** verify the Postgres reference, connectivity, and migration
  state. Do not recreate the database, replace its volume, or re-import history.
- **Explicit async task cancellation:** after the durable `running` commit, candidate
  work is rolled back and the run is marked `cancelled` only when no snapshot from the
  final commit exists. An already-committed snapshot retains its atomic `succeeded`
  run. OS-level termination or a hard kill can prevent cleanup; investigate any stale
  `running` row rather than inventing a terminal result.

Never use browser automation, challenge cookies, proxy rotation, CAPTCHA solving,
alternate evasion domains, or browser-fingerprint spoofing.

## Disabling and recovery

Pause collection by clearing or disabling `cronSchedule` on
`collector-danbooru`; do not delete the service or database. After correcting an
issue, keep restarts disabled, run once, inspect the terminal result, verify the
database read-only, and restore the daily cron only after validation.

## Data and provenance guarantees

The collector persists normalized aggregate metadata and bounded evidence only:
endpoint identifier, HTTP status, bounded content type, and response SHA-256.
Fingerprints cannot reconstruct bodies. Every metric retains provenance; Danbooru
`total_posts` is `estimated`. Unavailable growth remains unavailable, never zero.
