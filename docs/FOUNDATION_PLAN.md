# Milestone 0 Foundation Plan

## Repository boundary

This project is created under `BooruRadar/` because the surrounding checkout is an
existing NekoPrice repository with its own catalogue pipeline, SQLite data, public
snapshots, and deployment process. BooruRadar is self-contained and does not import,
modify, migrate, or deploy any NekoPrice component or data.

## Proposed structure

```text
BooruRadar/
├── apps/
│   ├── api/                 # FastAPI process and HTTP routes
│   └── worker/              # Background collection process entry point
├── booruradar/
│   ├── core/                # Configuration, database sessions, and logging
│   ├── adapters/            # Adapter contract, DTOs, registry, and family namespaces
│   │   ├── danbooru/
│   │   ├── gelbooru/
│   │   ├── shimmie/
│   │   └── custom/
│   ├── models/              # SQLAlchemy persistence models
│   └── services/            # Application orchestration independent of FastAPI
├── migrations/              # Alembic environment and versioned schema
├── tests/                   # Unit and lightweight API tests
├── docs/                    # Architecture and data-model decisions
├── compose.yaml             # Local PostgreSQL only
├── pyproject.toml           # Python 3.12+ package and dependencies
└── README.md                # Developer setup and commands
```

## Important choices

1. **One deployable package, two process entry points.** The API and worker share the
   domain, adapters, persistence models, and services without importing one another.
2. **Adapters return metadata only.** The contract exposes detection, health,
   public statistics, recent-post metadata, tag statistics, and capability discovery.
   It intentionally has no image-download or image-storage operation.
3. **Family implementations are plug-ins behind one contract.** Danbooru, Gelbooru,
   Shimmie, and custom namespaces can register concrete adapters without adding
   family-specific conditions to API routes or services.
4. **Metric provenance is metric-level.** A snapshot can contain values from different
   evidence classes, so a single provenance flag on the entire snapshot is
   insufficient. Each stored metric is an envelope containing `value` and one of
   `observed`, `estimated`, or `owner_verified`. The common envelope is validated by
   Pydantic before persistence.
5. **Snapshots are append-only observations.** `boorus` and `tags` hold stable identity;
   `booru_snapshots` and `tag_snapshots` hold time-series observations; `crawl_runs`
   records operational execution state and errors.
6. **PostgreSQL is the only supported application database.** SQLAlchemy 2 owns the
   model metadata, Alembic owns schema changes, and configuration supplies the
   connection URL. Tests that do not exercise persistence remain database-free.
7. **Asynchronous I/O at process boundaries.** API persistence uses SQLAlchemy's
   `AsyncSession`, and adapter I/O uses `httpx.AsyncClient`. Alembic remains a
   synchronous administrative process, keeping runtime requests non-blocking without
   complicating migrations.
8. **Milestone exclusions stay explicit.** There are no frontend assets, users,
   authentication, ownership claims, payments, recommendations, global scoring, or
   image storage in this foundation.

## Initial schema outline

- `boorus`: stable booru identity, canonical URL, detected adapter family, and enabled
  state.
- `crawl_runs`: one collection attempt for one booru, with lifecycle timestamps,
  status, adapter name, and operational details/errors.
- `booru_snapshots`: append-only health, capability, and public-statistic observations;
  each metric uses the provenance envelope.
- `tags`: a booru-scoped tag identity and optional source category.
- `tag_snapshots`: append-only tag counts and additional metrics, each with explicit
  provenance.

The first migration will create only these five tables and their indexes/constraints.
