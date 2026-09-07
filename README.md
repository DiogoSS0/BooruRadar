# BooruRadar

**Live demo:** https://web-production-58150.up.railway.app

**Status:** Public alpha

**Deployment target:** Railway (`main` branch)

BooruRadar is an open-source, metadata-only discovery platform for public booru
communities. It collects accepted history for explicit targets, exposes a read-only
catalog API, and serves a public homepage for exploring and comparing that data:

- `danbooru` uses the modern Danbooru adapter and records `total_posts` as
  `estimated`;
- `safebooru` uses the Gelbooru-family adapter and records `total_posts` as
  `observed`.

Adapters normalize public aggregate data and the minimum recent-post metadata needed
for inspection. BooruRadar does not download or persist image/video bytes, direct
media URLs, or raw response bodies. Crawl evidence is limited to endpoint identifiers,
HTTP status, content type, and a SHA-256 response fingerprint.

The product does not include users, authentication, ownership claims, payments,
recommendations, a global Booru Score, or an image pipeline.

## Requirements

- Python 3.12+
- Docker with Docker Compose

## Local setup

```bash
cp .env.example .env
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
docker compose up -d postgres
alembic upgrade head
```

## API and dashboard

Run the development API against the application history database you intend to read:

```bash
BOORURADAR_DATABASE_URL='postgresql+psycopg:///booruradar_history' \
.venv/bin/python -m apps.api.main
```

`booruradar_history` is an application/history target for the API and dashboard, not
the disposable integration-test database. The default Compose setup can instead use
the URL in `.env`.

While the API is running, the homepage opens directly on the API-backed public
rankings. Ranking order, global rank, eligibility, units, and provenance come from
the server; the browser formats those values but does not recalculate or re-rank
them.

Available surfaces:

- `GET /` serves the read-only dashboard;
- `/docs` serves interactive OpenAPI documentation;
- `GET /health` reports process liveness;
- `GET /health/ready` also checks PostgreSQL;
- `GET /api/v1/boorus` lists enabled boorus and their latest snapshot;
- `GET /api/v1/boorus/{booru_id}` returns one enabled booru;
- `GET /api/v1/boorus/{booru_id}/snapshots` returns recent accepted history;
- `GET /api/v1/boorus/{booru_id}/growth` returns latest-pair growth or an explicit
  unavailable reason;
- `GET /api/v1/rankings?mode=largest|fastest_growth|relative_growth` ranks every
  enabled booru, keeps ineligible sources explicit, and assigns global ranks before
  pagination;
- `GET /api/v1/compare?booru_id=<uuid>&booru_id=<uuid>` compares two to eight unique
  enabled boorus, keeping each booru's growth calculation isolated to its own history.

The discovery homepage and catalog API are read-only projections. Growth-ineligible
sources remain visible with an explicit reason and no substitute zero. The activity
section stays in a truthful history-accumulating state until an ecosystem-wide series
exists. These surfaces expose normalized aggregate metrics and provenance, never
adapter response payloads or media data.

## Manual collection

Use the configured application database and invoke either target explicitly:

```bash
.venv/bin/python -m booruradar.collect danbooru
.venv/bin/python -m booruradar.collect safebooru
```

Danbooru can optionally use its official HTTP Basic Auth credentials from
`DANBOORU_LOGIN` and `DANBOORU_API_KEY`. Authentication is enabled only when both
values are present and non-blank; partial configuration remains unauthenticated.
Credentials are sent in the authorization header, never in endpoint URLs.

Danbooru responses with HTTP 403 or `cf-mitigated: challenge` fail the single
collection attempt as `source_access_blocked`. BooruRadar does not retry or attempt
to bypass the challenge, and stores only response evidence (endpoint, status,
content type, and SHA-256), not the HTML response body.

Collection is scoped by the selected booru. If its latest accepted snapshot is less
than 20 hours old, the command exits as skipped before constructing an HTTP client or
collection service. `--force` bypasses only this interval:

```bash
.venv/bin/python -m booruradar.collect danbooru --force
```

Hard-invalid normalization and the historical anomaly policy still apply under
`--force`. Any production automation is restricted to the explicit `danbooru` target
as a one-shot Railway process. Safebooru remains manual: no production cron or generic
multi-target schedule includes it. The polling worker remains an unused compatibility
shell.

See [the production collection runbook](docs/production-collection.md) for Railway
configuration, result interpretation, database verification, scheduling, and recovery.

## Historical analytics

The stats CLI supports both targets and performs no HTTP requests or database writes:

```bash
.venv/bin/python -m booruradar.stats danbooru
.venv/bin/python -m booruradar.stats safebooru
```

Growth uses the latest two accepted snapshots for the selected booru. Both
`total_posts` envelopes must use the `posts` unit and matching provenance, and the
timestamps must form a positive interval. Danbooru history is therefore normally an
`estimated`/`estimated` pair, while Safebooru history is normally an
`observed`/`observed` pair. Mixed provenance is reported as unavailable. Available
growth is normalized to a 24-hour rate using the actual elapsed time.

## Tests

Run the default suite:

```bash
.venv/bin/python -m pytest
```

PostgreSQL integration tests are opt-in. They create and later delete only their own
UUID-scoped rows, but must still run only against a migrated, disposable
`booruradar_integration` database:

```bash
BOORURADAR_DATABASE_URL='postgresql+psycopg:///booruradar_integration' \
BOORURADAR_RUN_POSTGRES_TESTS=1 \
.venv/bin/python -m pytest tests/test_snapshot_collection_postgres.py -v
```

`BOORURADAR_RUN_POSTGRES_TESTS=1` is the guard that enables the module. Never point
that command at `booruradar_history` or another database whose rows must be retained.

Stop local PostgreSQL without deleting its named volume:

```bash
docker compose stop postgres
```

## Repository map

```text
apps/api/              FastAPI entry point, public routes, and dashboard assets
apps/worker/           Unused compatibility shell; production uses the one-shot CLI
booruradar/core/       Environment, database session, enums, logging
booruradar/adapters/   Metadata adapter contract and family implementations
booruradar/models/     SQLAlchemy tables and metric value objects
booruradar/services/   Collection, quality, analytics, and catalog services
migrations/            Alembic environment and revisions
tests/                 Unit, API, CLI, and opt-in PostgreSQL tests
docs/                  Architecture, adapter, and data-model documentation
```

See [the architecture](docs/ARCHITECTURE.md), [the data model](docs/DATA_MODEL.md),
[the adapter guide](docs/ADAPTERS.md),
[the production collection runbook](docs/production-collection.md), and
[the Ranking API V1 contract](docs/ranking-readiness.md) for detailed boundaries.
