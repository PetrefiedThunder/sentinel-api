# Contributing to Sentinel API

## Setup

```bash
git clone https://github.com/PetrefiedThunder/sentinel-api
cd sentinel-api
uv venv && source .venv/bin/activate
uv sync
pre-commit install
```

You need Postgres ≥ 15 and Redis ≥ 6 running locally:

```bash
createdb sentinel
export DATABASE_URL="postgresql+asyncpg://localhost/sentinel"
export REDIS_URL="redis://localhost:6379/0"
export JWT_SECRET="$(openssl rand -hex 32)"

alembic upgrade head
uvicorn app.main:app --reload
```

## Running tests

```bash
pytest -q                                  # all tests
pytest tests/test_approvals.py -v          # one file
pytest -k "rejection"                      # by name pattern
```

## Migrations

```bash
# create
alembic revision -m "your change"          # edits the file by hand
# apply
alembic upgrade head
# round-trip test before pushing
alembic downgrade -1 && alembic upgrade head
```

**Migration rules:**

- Sequential numeric prefix: `007_<short_name>.py`
- `revision = "007"` and `down_revision = "006"` — strings must match exactly
- One logical change per migration
- All migrations must be reversible (`downgrade()` implemented)
- Test round-trip locally before pushing

## Pull requests

1. Open an issue first if it's a behavior change
2. Small, focused PRs
3. Add tests
4. `pytest` + `ruff check .` must pass (pre-commit enforces this)
5. Document any new env var in README.md
6. If you add a migration, link to it in the PR description

## Release process

The API is continuously deployed from `main`. There is no version tag — every merge to `main` is the new production version. If you need a hotfix, push to `main` and watch Railway auto-deploy.

## Security

See [`SECURITY.md`](SECURITY.md). Never file a public issue for a vulnerability.

## Code style

- Python 3.11+
- Type hints required on all public APIs (`mypy` in pre-commit)
- `ruff` for lint + format (config in `pyproject.toml`)
- Async-first (`async def` for any DB-touching code)

## Code of conduct

Be excellent. Harassment, discrimination, or bigotry → removed from the project.
