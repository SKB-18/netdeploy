# NetDeploy

> Production-grade GitOps platform for automated BGP/OSPF deployment across datacenter routers — with canary/rolling/atomic strategies, automatic rollback, and a full observability stack.

[![CI](https://github.com/your-org/netdeploy/actions/workflows/test.yml/badge.svg)](https://github.com/your-org/netdeploy/actions/workflows/test.yml)
[![Security](https://github.com/your-org/netdeploy/actions/workflows/security.yml/badge.svg)](https://github.com/your-org/netdeploy/actions/workflows/security.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## The Problem

Manual BGP/OSPF provisioning across multi-region datacenters is slow, risky, and unauditable:

- **Error-prone** — copy-paste typos trigger production BGP flaps
- **Slow** — SSH-ing into 100+ routers individually takes hours
- **Risky** — no rollback strategy when a push breaks a session
- **Unobservable** — zero audit trail for compliance and post-mortems

## The Solution

NetDeploy treats network configuration as code: validate → version → deploy → verify → rollback if needed.

```
Git (source of truth)
       │
       ▼
ConfigValidator ── catches BGP/OSPF conflicts before they reach production
       │
       ▼
DeploymentOrchestrator ── canary | rolling | atomic
       │
       ├── CommandBuilder  ── vendor CLI generation (Cisco XR / JunOS / Arista / Nokia)
       ├── SSHDevice       ── Netmiko multi-vendor SSH
       ├── StateVerifier   ── post-deploy BGP/OSPF state check
       └── SnapshotManager ── before/after SHA-256 snapshots for safe rollback
```

## Quick Start

```bash
git clone https://github.com/your-org/netdeploy.git
cd netdeploy
cp .env.example .env

# Start all services (API, Celery, Postgres, Redis, Prometheus, Grafana)
docker compose up -d
sleep 10

# Verify
curl http://localhost:8000/health
# {"status": "healthy", "database": "ok", "redis": "ok", ...}

# Load demo data
python scripts/seed_data.py

# Run the end-to-end demo
python scripts/demo.py
```

| Service | URL |
|---|---|
| REST API + Swagger | http://localhost:8000/docs |
| Dashboard | http://localhost:8501 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

## Features

**Deployment strategies**

| Strategy | Behavior | Use Case |
|---|---|---|
| **Canary** | 1 device → 5 min health check → remaining | High-risk changes |
| **Rolling** | Sequential, device-by-device with health gates | Standard rollouts |
| **Atomic** | All devices in parallel; full rollback if any fail | Must-be-consistent changes |

**Safety**

- Pre-deploy config validation: BGP ASN range, duplicate neighbor detection, OSPF area conflicts, policy clash rules
- Config snapshots with SHA-256 integrity check before and after every push
- Automatic rollback triggered when `StateVerifier` detects BGP/OSPF session failure post-deploy
- Immutable audit log: every action records who, what, when, from where

**Observability**

- 11 Prometheus metrics (deploy count/duration, SSH latency, rate-limit hits, Celery queue depth)
- Grafana dashboard pre-configured for deployment SLOs
- Per-IP sliding-window rate limiting (Redis ZSET) with 429 headers

**Multi-vendor SSH support**

| Vendor | Netmiko type | BGP | OSPF | Save config |
|---|---|---|---|---|
| Cisco IOS XR | `cisco_xr` | ✅ | ✅ | commit (auto) |
| Cisco IOS | `cisco_ios` | ✅ | ✅ | write memory |
| Juniper JunOS | `junos` | ✅ | ✅ | commit (auto) |
| Arista EOS | `arista_eos` | ✅ | ✅ | write memory |
| Nokia SR-OS | `nokia_sros` | ✅ | ✅ | commit (auto) |

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness + DB/Redis status |
| `GET` | `/metrics` | Prometheus metrics (text/plain) |
| `GET/POST` | `/api/devices` | List / register devices |
| `GET/DELETE` | `/api/devices/{id}` | Get / delete device |
| `GET` | `/api/devices/{id}/health` | Live SSH health check |
| `POST` | `/api/devices/{id}/sync` | Pull running config from device |
| `GET/POST` | `/api/configs` | List / create config versions |
| `POST` | `/api/configs/validate` | Validate BGP/OSPF config |
| `GET` | `/api/configs/diff` | Diff desired vs running |
| `GET/POST` | `/api/deployments` | List / trigger deployments |
| `GET` | `/api/deployments/{id}` | Get deployment status |
| `GET` | `/api/deployments/{id}/logs` | Stream deployment logs |
| `GET` | `/api/deployments/{id}/snapshot` | Before/after config diff |
| `POST` | `/api/deployments/{id}/rollback` | Manual rollback |
| `GET` | `/api/audit` | Search audit trail |

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.104, Uvicorn, Pydantic v1 |
| Task Queue | Celery 5.3, Redis 7 |
| Database | PostgreSQL 15, SQLAlchemy 2.x, Alembic |
| Network SSH | Netmiko 4.3, Paramiko |
| Version Control | GitPython |
| Dashboard | Streamlit 1.28, Plotly, pandas |
| Monitoring | Prometheus, Grafana, prometheus-client |
| Security | Bandit, Safety, Trivy, Gitleaks |
| Infrastructure | Docker Compose, Kubernetes, Helm 3 |
| CI/CD | GitHub Actions (test + lint + security + deploy) |
| Load Testing | Locust 2.x |
| Testing | pytest, pytest-asyncio, fakeredis |

## Development

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt -r requirements-test.txt
docker compose up -d db redis
alembic upgrade head

# Tests
pytest tests/unit/ -v                          # fast, no DB needed
pytest tests/integration/ -v                   # requires DB + Redis
pytest tests/security/ -m "not rate_limit" -v  # OWASP security tests
pytest tests/ -q --tb=short                    # full suite

# Coverage
pytest tests/unit/ tests/integration/ \
  --cov=api --cov=core --cov=tasks --cov=dashboard \
  --cov-report=html

# Load test (requires running stack)
locust -f tests/load/locustfile.py --host=http://localhost:8000

# Security scan
bandit -r . --exclude tests -c .bandit
safety check -r requirements.txt

# Code quality
black api core tasks tests
isort api core tasks tests
mypy api core tasks
```

## Kubernetes Deployment

```bash
# Apply manifests
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl create secret generic netdeploy-secrets \
  --from-literal=DATABASE_URL="..." \
  --from-literal=REDIS_URL="..." \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --namespace=netdeploy
kubectl apply -f k8s/

# Or use Helm
helm dependency update helm/netdeploy
helm install netdeploy helm/netdeploy \
  --namespace netdeploy \
  --create-namespace \
  --set api.secretName=netdeploy-secrets
```

## Project Status

| Phase | Status | What was built |
|---|---|---|
| 1 — Foundation | ✅ Complete | Models, schemas, Docker, CI/CD, Alembic migrations |
| 2 — Validation | ✅ Complete | ConfigValidator, BGP/OSPF rules, validation API |
| 3 — Orchestration | ✅ Complete | Orchestrator, CommandBuilder, StateVerifier, SnapshotManager, SSH |
| 4 — Dashboard | ✅ Complete | Streamlit pages, NetDeployClient, formatting utils |
| 5 — Production | ✅ Complete | k8s, Helm, Prometheus metrics, rate limiting, security CI |
| 6 — Portfolio | ✅ Complete | Demo scripts, seed data, comprehensive test suite, architecture docs |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, commit conventions, and PR process.

## License

MIT — see [LICENSE](LICENSE).
