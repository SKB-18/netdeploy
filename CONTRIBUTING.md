# Contributing to NetDeploy

Thank you for your interest in contributing! This guide covers everything you need to set up your development environment, submit changes, and understand the project conventions.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Commit Conventions](#commit-conventions)
- [Pull Request Process](#pull-request-process)
- [Architecture Decisions](#architecture-decisions)

---

## Code of Conduct

Be respectful, constructive, and professional. Network automation mistakes have real-world consequences — we take correctness seriously.

---

## Development Setup

### Prerequisites

- Python 3.11+
- Docker + Docker Compose
- Git

### 1. Clone and install

```bash
git clone https://github.com/your-org/netdeploy.git
cd netdeploy

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
pip install -r requirements-dev.txt
pip install -r requirements-test.txt
```

### 2. Start infrastructure

```bash
docker compose up -d db redis
# Wait for healthchecks, then:
alembic upgrade head
```

### 3. Run the API

```bash
uvicorn api.main:app --reload --port 8000
# Swagger UI: http://localhost:8000/docs
```

### 4. Run Celery worker

```bash
celery -A tasks.celery_app worker --loglevel=info --queues=deployments,validation,default
```

### 5. Run the dashboard

```bash
streamlit run dashboard/app.py
# Dashboard: http://localhost:8501
```

---

## Project Structure

```
netdeploy/
├── api/                    # FastAPI application
│   ├── main.py             # App factory, middleware, routers
│   ├── models.py           # SQLAlchemy ORM models
│   ├── schemas.py          # Pydantic request/response schemas
│   ├── config_schemas.py   # Typed BGP/OSPF config schemas
│   ├── routes/             # Route handlers (devices, configs, deployments, audit, auth)
│   ├── middleware/         # Rate limiter, security headers
│   └── metrics.py          # Prometheus counters/histograms
│
├── core/                   # Business logic (no FastAPI dependencies)
│   ├── orchestrator.py     # Deployment orchestrator (canary/rolling/atomic)
│   ├── ssh_handler.py      # SSHDevice — Netmiko wrapper, vendor dispatch
│   ├── command_builder.py  # CLI command generation per vendor + protocol
│   ├── state_verifier.py   # Post-deploy BGP/OSPF verification
│   ├── snapshot_manager.py # Config snapshot save/restore/diff
│   ├── validator.py        # BGP/OSPF semantic validation rules
│   ├── git_handler.py      # GitPython operations
│   └── config.py           # Settings (pydantic BaseSettings)
│
├── tasks/                  # Celery task definitions
│   ├── celery_app.py       # Celery app + broker config
│   ├── deployment.py       # Deployment + rollback tasks
│   └── validation.py       # Async validation tasks
│
├── dashboard/              # Streamlit UI
│   ├── app.py              # Entry point + sidebar navigation
│   ├── pages/              # deployments.py, devices.py, audit_log.py
│   └── utils/              # api_client.py, formatting.py
│
├── tests/
│   ├── unit/               # Pure unit tests (no DB, no network)
│   ├── integration/        # Tests against real DB via TestClient
│   ├── security/           # OWASP security tests
│   └── load/               # Locust load test scripts
│
├── k8s/                    # Kubernetes manifests
├── helm/netdeploy/         # Helm chart
├── .github/workflows/      # CI/CD pipelines
└── docker-compose.yml      # Local dev environment
```

---

## Making Changes

### Branch naming

```
feature/short-description       # new features
fix/short-description           # bug fixes
chore/short-description         # dependency bumps, refactors
docs/short-description          # documentation only
test/short-description          # test additions only
```

### Adding a new vendor

1. Add the vendor string to `DEVICE_TYPES` in `api/schemas.py`
2. Add a command map entry in `core/command_builder.py` → `CommandBuilder`
3. Add show-command dispatch in `core/ssh_handler.py` → `SSHDevice`
4. Add state verification logic in `core/state_verifier.py` → `StateVerifier`
5. Add tests in `tests/unit/test_command_builder.py` + `tests/unit/test_ssh_handler.py`

### Adding a new API endpoint

1. Add the route handler in the appropriate `api/routes/*.py` file
2. Add Pydantic request/response schemas in `api/schemas.py`
3. Add a `NetDeployClient` method in `dashboard/utils/api_client.py`
4. Add unit tests in `tests/unit/test_api_client.py`
5. Add integration tests in `tests/integration/`

---

## Testing

### Run the full suite

```bash
# Fast unit tests only
pytest tests/unit/ -v --tb=short

# Integration tests (requires DB + Redis via Docker)
pytest tests/integration/ -v --tb=short

# Security tests (skip rate-limit which needs real Redis)
pytest tests/security/ -v -m "not rate_limit"

# Full suite (excluding load tests)
pytest tests/ -v -m "not rate_limit" --tb=short -q
```

### Coverage

```bash
pytest tests/unit/ tests/integration/ \
  --cov=api --cov=core --cov=tasks --cov=dashboard \
  --cov-report=term-missing --cov-report=html
open htmlcov/index.html
```

### Load tests

```bash
# Start the full stack first
docker compose up -d

# Run headless for 2 minutes at 20 users
locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --headless --users 20 --spawn-rate 2 --run-time 120s \
  --html tests/load/report.html
```

### Test conventions

- **Unit tests** must mock all I/O (DB, SSH, Redis). Use `AsyncMock` for async SSH methods.
- **Integration tests** use the conftest `client` fixture (FastAPI `TestClient` with in-memory SQLite or test PostgreSQL).
- **No real SSH** in any automated test — always mock `SSHDevice.send_command`.
- Test files mirror source structure: `core/orchestrator.py` → `tests/unit/test_orchestrator.py`.
- Use `pytest.mark.asyncio` for async test functions.

---

## Commit Conventions

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `test`, `chore`, `refactor`, `perf`, `ci`

Examples:
```
feat(orchestrator): add blue-green deployment strategy
fix(ssh_handler): handle Junos commit timeout after 30s
test(security): add SQL injection parametrized test cases
docs(api): document rate limiting headers in OpenAPI
chore(deps): bump netmiko to 4.3.1
```

---

## Pull Request Process

1. Fork the repo and create your branch from `main`
2. Write tests — PRs without tests for new behaviour are not accepted
3. Run `pytest tests/unit/ tests/integration/` locally — all must pass
4. Run `bandit -r . --exclude tests` — no HIGH severity findings
5. Open a PR with:
   - **What** changed and **why**
   - Link to any related issue
   - Test coverage diff (paste the summary line from `pytest --cov`)
6. PRs require 1 approval + CI green before merge
7. Squash-merge into `main` with a conventional commit message

---

## Architecture Decisions

### Why SQLAlchemy 2.x (not async)?
Celery workers are synchronous, and Netmiko's SSH I/O is blocking. Using sync SQLAlchemy avoids complexity of mixing async/sync contexts. FastAPI routes use `run_in_executor` for the blocking DB calls.

### Why Celery + Redis (not asyncio tasks)?
Deployment tasks can take 5–30 minutes. We need distributed execution across multiple worker nodes, task retry logic, and result persistence — Celery provides all of this. Redis is already in the stack for rate limiting.

### Why Pydantic v1 (not v2)?
Current dependency tree (FastAPI 0.104, SQLAlchemy 2.x) works cleanly with Pydantic v1. Migration to v2 is planned but blocked on upstream FastAPI compatibility for the JWT auth flow.

### Why Streamlit (not React)?
Streamlit gives us a production-quality network operations dashboard with ~200 lines of Python vs. thousands of lines of JS/CSS. The target audience is network engineers, not end consumers.

### Why per-IP sliding window rate limiting (not token bucket)?
Sliding window Redis ZSET is simple to reason about, auditable (the ZSET itself shows the request timestamps), and handles burst traffic correctly. Token bucket requires more complex atomic operations.
