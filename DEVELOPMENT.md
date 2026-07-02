# NetDeploy Development Guide

## Workflow: Cowork → Cursor

Each phase follows this pattern:

1. **Cowork** creates scaffold (structure, stubs, docstrings)
2. **Local test** — verify scaffold loads, Docker builds
3. **Cursor** implements logic (marked with `[CURSOR IMPLEMENTS]` comments)
4. **Local test** — verify tests pass, endpoints respond
5. **Git commit** + move to next phase

## Phase 1 Checklist (Cursor)

- [ ] Run `alembic init alembic` and create initial migration
- [ ] Run `alembic upgrade head` — verify tables in `psql netdeploy`
- [ ] Implement `api/dependencies.py → get_current_user()` with real JWT
- [ ] Implement `api/database.py` session management
- [ ] Run `docker compose up` — all services healthy
- [ ] Run `curl http://localhost:8000/health` — returns `{"status": "healthy"}`
- [ ] Run `pytest tests/` — all existing tests pass
- [ ] Implement `tests/fixtures/mock_devices.py` (already done as scaffold)

## Running Locally

```bash
cp .env.example .env
docker compose up

# In another terminal — run migrations
docker compose exec api alembic upgrade head

# Test
curl http://localhost:8000/health
curl http://localhost:8000/docs   # Swagger UI
```

## Running Tests

```bash
# All tests
docker compose exec api pytest tests/ -v

# With coverage
docker compose exec api pytest tests/ --cov=api --cov=core --cov-report=term-missing

# Specific file
docker compose exec api pytest tests/unit/test_validator.py -v
```

## Code Style

```bash
black --line-length 100 api core tasks tests
isort --profile black api core tasks tests
flake8 api core tasks tests --max-line-length=100
mypy api core tasks --ignore-missing-imports
```

## Adding a New Device Type

1. Add to `DeviceRequest.validate_device_type()` in `api/schemas.py`
2. Add command map in `SSHDevice.get_running_config()` in `core/ssh_handler.py`
3. Add command generator in `DeploymentOrchestrator._config_to_commands()` in `core/orchestrator.py`
4. Add unit test in `tests/unit/test_ssh_handler.py`

## Environment Variables

See `.env.example` for all supported variables.
Key ones for development:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://...` | PostgreSQL connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for Celery broker |
| `GIT_REPO_PATH` | `/app/config_repo` | Local Git repo path |
| `SSH_TIMEOUT` | `30` | SSH connection timeout (seconds) |
| `CANARY_HEALTH_WAIT_SECONDS` | `300` | Wait after canary before deploying rest |
