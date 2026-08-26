# BooruRadar

BooruRadar is a metadata monitoring service for public booru sites. Milestone 0
provides the standalone backend foundation: a FastAPI process, a worker process,
PostgreSQL persistence, SQLAlchemy 2 models, Alembic migrations, and an asynchronous
adapter contract.

The first vertical collection path supports the modern public Danbooru API. It
normalizes metadata, applies a small quality gate, records bounded response evidence
on `CrawlRun`, and writes only accepted `BooruSnapshot` observations.

This milestone does **not** include a frontend, users, authentication, ownership
claims, payments, recommendations, a global Booru Score, or image downloading and
storage.

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

Run the API:

```bash
uvicorn apps.api.main:app --reload
```

The liveness endpoint is `GET /health`; `GET /health/ready` also checks PostgreSQL.
Interactive OpenAPI documentation is available at `/docs` while the API is running.

Run the worker shell once:

```bash
python -m apps.worker.main --once
```

The modern Danbooru adapter is registered, but the worker deliberately performs an
empty scheduling cycle. Scheduling, retries, and recurring collection remain future
work.

Run tests:

```bash
pytest
```

Stop local PostgreSQL without deleting its named volume:

```bash
docker compose stop postgres
```

## Repository map

```text
apps/api/              FastAPI entry point and routes
apps/worker/           Background-process entry point
booruradar/core/       Environment, database session, enums, logging
booruradar/adapters/   Metadata adapter contract, DTOs, registry, family namespaces
booruradar/models/     SQLAlchemy tables and metric value objects
booruradar/services/   Framework-independent collection orchestration
migrations/            Alembic environment and revisions
tests/                 Foundation tests
docs/                  Architecture and data-model documentation
```

See [the architecture](docs/ARCHITECTURE.md), [the data model](docs/DATA_MODEL.md),
and [the adapter guide](docs/ADAPTERS.md) for the design boundaries.
