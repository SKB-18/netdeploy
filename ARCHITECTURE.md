# NetDeploy Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    NETWORK INFRASTRUCTURE                    │
│  Router 1 (BGP/OSPF) ── Router 2 (BGP/OSPF) ── Router 3    │
└─────────┬───────────────────────────────────────────────────┘
          │ SSH/Netconf via SSHDevice (Netmiko)
          ▼
┌─────────────────────────────────────────────────────────────┐
│              NETDEPLOY ORCHESTRATION PLATFORM                │
│                                                              │
│  Git Repository (Config Source of Truth)                    │
│  └── devices/{device_id}.yaml                               │
│            │                                                 │
│            ▼                                                 │
│  FastAPI (api/main.py)                                      │
│  ├── POST /api/configs/validate                             │
│  ├── POST /api/configs/deploy                               │
│  ├── GET  /api/deployments/{id}                             │
│  └── GET  /api/audit-log                                    │
│            │                                                 │
│            ▼                                                 │
│  ConfigValidator (core/validator.py)                        │
│  ├── Schema validation (Pydantic)                           │
│  ├── BGP: ASN range, neighbor IPs, duplicates               │
│  ├── OSPF: area IDs, timers                                 │
│  ├── Policy conflict detection                              │
│  └── Device compatibility warnings                          │
│            │                                                 │
│            ▼                                                 │
│  Celery Task Queue (tasks/deployment.py)                    │
│  ├── validate_and_deploy_task                               │
│  ├── deploy_to_device                                       │
│  ├── rollback_device                                        │
│  └── sync_device_state                                      │
│            │                                                 │
│            ▼                                                 │
│  DeploymentOrchestrator (core/orchestrator.py)              │
│  ├── Canary: 1 device → health check → rest                 │
│  ├── Rolling: sequential + health checks                    │
│  └── Atomic: parallel + rollback all on failure             │
│            │                                                 │
│            ▼                                                 │
│  SSHDevice (core/ssh_handler.py)                            │
│  ├── connect() → Netmiko ConnectHandler                     │
│  ├── send_command() → show commands                         │
│  ├── send_config_set() → apply config                       │
│  ├── get_running_config() → fetch running state             │
│  └── disconnect()                                           │
│            │                                                 │
│  PostgreSQL (audit, state)    Redis (task broker/cache)     │
│                                                              │
│  Streamlit Dashboard (dashboard/app.py)                     │
│  ├── Deployments page                                       │
│  ├── Devices page                                           │
│  └── Audit Log page                                         │
└─────────────────────────────────────────────────────────────┘
```

## Data Models

### Device
Represents a managed network router. Unique by `hostname`.
Fields: id, hostname, device_type, management_ip, ssh_port, bgp_asn, ospf_area, os_version.

### Configuration
Stores desired vs running config for a device. `version` is the Git commit hash.
Status lifecycle: `PENDING → SYNCED | DRIFT | FAILED`.

### Deployment
Tracks a single device's deploy attempt within a batch.
Status lifecycle: `QUEUED → IN_PROGRESS → SUCCESS | ROLLBACK | FAILED`.

### AuditLog
Immutable record of every action. Indexed by timestamp and user_id for fast search.

### ConfigSnapshot
Stores config_before/config_after for every deployment (enables rollback).

## Deployment State Machine

```
QUEUED
  │
  ▼
IN_PROGRESS ──── (SSH error / verify fails) ──► ROLLBACK
  │
  ▼
SUCCESS
```

## Celery Queue Architecture

| Queue | Tasks | Purpose |
|---|---|---|
| `deploy` | validate_and_deploy_task, deploy_to_device | Deployment work |
| `rollback` | rollback_device | Rollback (high priority) |
| `sync` | sync_device_state, check_deployment_health | Background sync |

## Security Considerations

- SSH credentials stored encrypted (not in Git)
- API auth via Bearer token (JWT — Cursor implements)
- Audit log is append-only (no UPDATE/DELETE)
- All secrets via environment variables / k8s Secrets
- Rate limiting on deploy endpoints (Cursor implements)
