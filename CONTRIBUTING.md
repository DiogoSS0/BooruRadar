# Contributing to BooruRadar

BooruRadar is a public alpha: features, design and data coverage are still evolving.
Contributions are welcome, whether or not you write code.

[Visit the preview](https://web-production-58150.up.railway.app/) ·
[About the project](https://web-production-58150.up.railway.app/welcome) ·
[Browse issues](https://github.com/DiogoSS0/BooruRadar/issues)

## Ways to help

- **Report a bug:** describe what happened, what you expected and how to reproduce
  it. For interface problems, include your browser and screen size.
- **Suggest an improvement:** explain the problem it would solve and who would
  benefit. Small, concrete suggestions are a useful starting point.
- **Improve documentation:** clarify instructions, fix mistakes or explain a
  confusing metric.
- **Improve the interface:** help with readability, accessibility, responsive
  layouts and clear English copy.
- **Contribute code or source research:** fix an issue or document a public booru's
  aggregate endpoints and measurement limitations. Include public references when
  proposing a new source or a classification correction.

Search [existing issues](https://github.com/DiogoSS0/BooruRadar/issues) first, then
[open an issue](https://github.com/DiogoSS0/BooruRadar/issues/new) for bugs and ideas.
You need a GitHub account to open issues or pull requests. Please leave credentials,
private account information and raw external API responses out of reports.

For a substantial change, discuss the approach in an issue before implementing it.
Small fixes can go straight to a pull request. Be respectful and focus feedback on
the work.

## Run the project locally

You need Python 3.12 or newer, Git, and Docker with Docker Compose. Fork
[DiogoSS0/BooruRadar](https://github.com/DiogoSS0/BooruRadar), clone your fork, and
create a branch for your change:

```bash
git clone https://github.com/YOUR_USERNAME/BooruRadar.git
cd BooruRadar
git switch -c describe-your-change
cp .env.example .env
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
docker compose up -d postgres
alembic upgrade head
python -m apps.api.main
```

Replace `YOUR_USERNAME` with your GitHub username. If your installed Python has a
different command, use that command to create the environment (Python 3.12+).
The commands above use a POSIX shell.

Open <http://127.0.0.1:8000/welcome> for the introduction, <http://127.0.0.1:8000/>
for the dashboard, or <http://127.0.0.1:8000/docs> for the API documentation.
The default `.env.example` connects to the local Compose database. Use your own
local database and keep `.env` out of Git.

A new database has no collected history, so empty rankings are expected. The
welcome page needs no database connection. Frontend files are served directly by
FastAPI; there is no Node build step. Restart the API after editing HTML, CSS or
JavaScript because these resources are read when the process starts.

If your change requires real local history, stop the API and use the
[manual collection instructions](README.md#manual-collection) against your own
development database. A single collection cannot establish growth; compatible
observations at different times are required. Do not invent data to fill the UI.

## Validate your change

With the virtual environment active:

```bash
python -m pytest
```

The default tests do not require live external services. PostgreSQL integration
tests are opt-in and may only use a migrated, disposable database named
`booruradar_integration`; see [the test instructions](README.md#tests).
Never run those tests against retained history or production.

For frontend work, check the affected page at mobile, tablet and desktop widths,
including keyboard navigation, readable contrast and loading, empty and error
states where applicable. The welcome page's two links must also work without
JavaScript. The dashboard's live rankings require JavaScript.

## Project conventions

- Keep product copy, code identifiers and contribution discussions in English.
- Preserve the dark editorial design, existing wordmark and mascot.
- Rankings, order, units and provenance come from the API. Missing data is not zero;
  the browser must not invent rankings or replace unavailable values.
- BooruRadar collects aggregate metadata, not image/video bytes, direct media URLs
  or raw external response bodies. Adapters must preserve that boundary.
- Keep changes focused. Add dependencies only when the change needs them.

See the [architecture](docs/ARCHITECTURE.md), [adapter guide](docs/ADAPTERS.md) and
[README](README.md) for the relevant subsystem before changing its behavior.

## Send a pull request

Commit your change, push your branch to your fork, then open a pull request against
`DiogoSS0/BooruRadar:main`. Explain the problem, the resulting behavior and how you
checked it. Link a related issue when there is one; include screenshots for visual
changes when useful. Maintainers review contributions before they reach the live
preview.

The project's original code and documentation are available under the
[MIT license](LICENSE). Submit contributions under the same license and retain
existing third-party attribution and license notices, including the Manrope font's
OFL notice. Only contribute material you have the right to share.
