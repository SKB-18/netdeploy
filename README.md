# NetDeploy: Automated Network Provisioning Platform

> GitOps-based declarative platform for deploying BGP/OSPF configurations safely across datacenter routers.

## Problem

Manual BGP/OSPF deployment across multi-region datacenters is:
- **Error-prone** — copy-paste typos cause production incidents
- **Slow** — SSH-ing into 100+ devices individually
- **Risky** — no rollback strategy when a deploy fails
- **Unobservable** — zero audit trail for compliance

**Impact:** 50%+ of provisioning time wasted on manual operations.

## Solution

NetDeploy is a production-grade GitOps platform for declarative network automation:

| Capability | Description |
|---|---|
| **Config Repository** | Git source of truth for all device configs |
| **Validation Engine** | Catch BGP/OSPF conflicts before they reach production |
| **Deployment Orchestrator** | Canary / rolling / atomic strategies with rollback |
| **SSH Handler** | Multi-vendor support (Cisco XR, JunOS, Arista EOS) |
| **Audit Trail** | Immutable log of every change (who, what, when, why) |
| **Web Dashboard** | Streamlit UI for deployment status and device health |

## Architecture

```
Git Repo (source of truth)
       │
       ▼
FastAPI (validate → deploy → audit)
       │
       ├── ConfigValidator   (Pydantic + custom rules)
       ├── DeploymentOrchestrator  (Celery tasks)
       │       ├── Canary strategy
       │       ├── Rolling strategy
       │       └── Atomic strategy + rollback
       └── SSHDevice (Netmiko → router)
```

## Quick Start

```bash
git clone https://github.com/<you>/netdeploy
cd netdeploy
cp .env.example .env

docker compose up
# All services start: API, Celery, PostgreSQL, Redis, Prometheus, Grafana

curl http://localhost:8000/health
# {"status": "healthy", ...}

open http://localhost:8000/docs    # Swagger UI
open http://localhost:8501         # Dashboard
open http://localhost:3000         # Grafana
```

## Tech Stack

- **Backend:** FastAPI, Celery, PostgreSQL, Redis
- **Network:** Netmiko, Paramiko, Nornir
- **Version Control:** GitPython
- **Frontend:** Streamlit, Plotly
- **DevOps:** Docker, Kubernetes, GitHub Actions
- **Monitoring:** Prometheus, Grafana
- **Testing:** pytest, pytest-asyncio, Locust

## Deployment Strategies

| Strategy | Behavior | Use Case |
|---|---|---|
| **Canary** | Deploy to 1 device → wait 5 min health check → rest | High-risk changes |
| **Rolling** | Sequential device-by-device with health checks | Standard updates |
| **Atomic** | All devices in parallel; rollback all if any fail | Must-be-consistent |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/configs/validate` | Validate config before deploy |
| `POST` | `/api/configs/deploy` | Trigger deployment (returns batch_id) |
| `GET` | `/api/configs/diff` | Diff desired vs running config |
| `GET` | `/api/devices/` | List all devices |
| `POST` | `/api/devices/` | Register device |
| `GET` | `/api/devices/{id}/health` | Real-time SSH health check |
| `GET` | `/api/deployments/` | List deployments |
| `POST` | `/api/deployments/{id}/rollback` | Trigger rollback |
| `GET` | `/api/audit-log/` | Search audit trail |

## Development

```bash
pip install -r requirements-dev.txt

# Run tests
pytest tests/ -v --cov=api --cov=core

# Format
black api core tasks tests
isort api core tasks tests

# Type check
mypy api core tasks
```

## Project Phases

| Phase | Status | Description |
|---|---|---|
| 1 — Foundation | ✅ Cowork scaffold | Repo structure, models, Docker, CI/CD |
| 2 — Validation | 🔲 Cursor | Full ConfigValidator implementation |
| 3 — Orchestration | 🔲 Cursor | DeploymentOrchestrator + SSH handler |
| 4 — Dashboard | 🔲 Cursor | Streamlit pages + real-time updates |
| 5 — Production | 🔲 Cursor | k8s manifests, load testing, security audit |
| 6 — Portfolio | 🔲 Cursor | Demo, metrics, blog post |

## Resume Alignment

Built to demonstrate skills from Hexagon R&D (BGP/OSPF 10K+ nodes, 99.9% uptime, 50% provisioning improvement):
- Production-grade orchestration (not just scripts)
- Distributed systems (Celery async task queue)
- Formal infrastructure-as-code (Git + validation)
- Observability + compliance (audit trail, Prometheus)
