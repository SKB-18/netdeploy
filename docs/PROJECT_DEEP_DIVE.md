# NetDeploy — Full Technical Deep Dive

Exhaustive reference document: every module, every endpoint, every data model field, exact test results, and an honest inventory of what's fully implemented vs. stubbed. Written for interview prep — detailed enough to answer "walk me through this codebase" at any level of follow-up.

---

## 1. What NetDeploy Is

A GitOps-style platform for automating BGP/OSPF configuration deployment to real network routers (Cisco IOS-XR, Cisco IOS, Juniper JunOS, Arista EOS, Nokia SR-OS). Config lives in Git as the source of truth; a FastAPI backend validates it, a Celery task queue orchestrates the actual SSH push using one of three rollout strategies (canary/rolling/atomic), and a Streamlit dashboard gives operators visibility into deployments, devices, and an audit trail.

**Why this is a non-trivial problem to automate:** pushing config to routers is high-blast-radius — a bad BGP push can take down a datacenter's routing. That risk shapes every design decision: validate before touching hardware, snapshot before/after every push, verify state after every push, and default to conservative rollout strategies.

---

## 2. Architecture — Full Request Flow

```
Git repo (devices/{device_id}.yaml)  ←── GitConfigRepository (implemented, NOT wired in — see §7)
        │
        ▼
FastAPI (api/main.py)
  Middleware chain (outer→inner): CORS → SecurityHeaders → RateLimit → request-logging/metrics
  Routers: /api/auth, /api/devices, /api/configs, /api/deployments, /api/audit-log (+ /api/audit alias), /metrics
        │
        ▼
ConfigValidator (core/validator.py) — BGP/OSPF rule engine, runs BEFORE any SSH connection
        │
        ▼
Celery (tasks/deployment.py, tasks/validation.py) — broker+backend on Redis, 3 queues (deploy/rollback/sync)
        │
        ▼
DeploymentOrchestrator (core/orchestrator.py) — canary | rolling | atomic
  ├── CommandBuilder (core/command_builder.py)   — desired_state dict → vendor CLI command list
  ├── SSHDevice (core/ssh_handler.py)             — Netmiko wrapper, async-safe via run_in_executor
  ├── StateVerifier (core/state_verifier.py)      — post-deploy BGP/OSPF session state check
  └── SnapshotManager (core/snapshot_manager.py)  — SHA-256'd before/after config snapshots
        │
        ▼
PostgreSQL (devices, configurations, deployments, audit_logs, config_snapshots)
Redis (Celery broker/backend + rate-limiter ZSETs)
        │
        ▼
Streamlit dashboard (dashboard/app.py) — Deployments / Devices / Audit Log pages, via NetDeployClient HTTP wrapper
```

---

## 3. Data Model (PostgreSQL, via SQLAlchemy 2.x)

### `devices`
| Field | Type | Notes |
|---|---|---|
| id | UUID PK | default `uuid4()` |
| hostname | String(255) | **unique**, not null |
| device_type | String(50) | not null — `cisco_xr`\|`cisco_ios`\|`junos`\|`arista_eos`\|`nokia_sros` |
| management_ip | String(15) | not null |
| ssh_port | Integer | default 22 |
| bgp_asn | Integer | nullable |
| ospf_area | String(50) | nullable |
| os_version | String(100) | nullable |
| created_at / updated_at | DateTime | auto |

Indexes: `idx_devices_hostname`, `idx_devices_ip`. Relationships: `configurations`, `deployments`.

### `configurations`
`id` UUID PK, `device_id` FK→devices, `version` String(40) (intended: git commit hash), `desired_state` JSON, `running_state` JSON nullable, `status` String(20) default `PENDING` (`PENDING`→`SYNCED`|`DRIFT`|`FAILED`), `deployed_at` nullable, `created_by` default `"system"`, timestamps. Indexes on `device_id`, `version`.

### `deployments`
`id` UUID PK, `batch_id` UUID default `uuid4()` (groups multi-device deploys), `device_id` FK→devices, `config_version` String(40), `status` String(20) default `QUEUED` (`QUEUED`→`IN_PROGRESS`→`SUCCESS`|`ROLLBACK`|`FAILED`), `start_time`/`end_time` nullable, `rollback_to_version` nullable, `error_message` Text, `logs` Text (newline-joined running log), `strategy` String(20) default `"atomic"`, `created_at`. Indexes on `batch_id`, `device_id`, `status`. Relationships: `device`, `snapshots`.

**⚠️ Schema drift found:** the `strategy` column exists on the ORM model but the one Alembic migration (`001_initial_schema.py`) never creates it on the `deployments` table. A fresh DB built purely from migrations would be missing this column — a real gap worth calling out if asked "how would you find schema drift."

### `audit_logs`
`id` UUID PK, `user_id` String(100), `action` String(50) (`CREATE`/`DEPLOY`/`ROLLBACK`/`SYNC`/`DELETE`/`VALIDATE`), `resource_type` String(50), `resource_id` UUID not null, `details` JSON nullable, `timestamp` default `utcnow`, `ip_address` String(45) (sized for IPv6). Indexes on `timestamp`, `user_id`, `action`. **Append-only by convention** — no UPDATE/DELETE code path exists anywhere in the app.

### `config_snapshots`
`id` UUID PK, `deployment_id` FK→deployments, `device_id` FK→devices, `config_before` JSON nullable, `config_after` JSON nullable (mutually exclusive per row — **one row per snapshot event**, not one row per before+after pair), `applied_at` default `utcnow`, `snapshot_hash` String(64) (SHA-256 hex). Index on `deployment_id`.

---

## 4. API Reference (FastAPI, `api/`)

### `api/main.py`
- App: `FastAPI(title="NetDeploy", version="1.0.0", docs_url="/docs", redoc_url="/redoc")`.
- Middleware order (outermost first): CORS (`allow_origins` from settings, `*` by default) → `SecurityHeadersMiddleware` → `RateLimitMiddleware` → request-logging middleware (records `HTTP_REQUEST_COUNTER`/`HTTP_REQUEST_DURATION`, wrapped in try/except so metrics never break a request).
- Global exception handler: any uncaught `Exception` → logged in full server-side, client gets a generic `{"detail": "Internal server error"}` 500 (no stack trace leakage).
- `GET /health` — pings DB (`SELECT 1`) and Redis (`.ping()`); returns `{"status": "healthy"|"degraded", "version", "database": "ok"|"error", "redis": "ok"|"error", "timestamp"}`.
- `GET /` — `{"message": "NetDeploy API — visit /docs"}`.

### Auth — `api/routes/auth.py` (prefix `/api/auth`)
- `POST /api/auth/token` — OAuth2 password flow against **hardcoded in-memory dev users**: `admin/admin` (role=admin), `readonly/readonly` (role=viewer). Passwords hashed via `passlib` `pbkdf2_sha256`. Issues a JWT (HS256, 24h expiry) with claims `sub`, `email`, `role`.
- `GET /api/auth/me` — decodes bearer token, returns user info.
- **This is dev-grade auth** — no user table, no way to add real users without redeploying code.

### Auth dependency layer — `api/dependencies.py`
- `get_current_user()` — **if no bearer token is present at all, silently returns an anonymous admin user** (`{"user_id": "anonymous", "role": "admin"}`) rather than rejecting the request. Since every route uses this dependency (not the stricter `require_auth`), **the entire API is effectively unauthenticated by default** — a token, if provided, is validated, but omitting one entirely is treated as full-admin access. `require_auth()` (the strict version that 401s on missing credentials) exists in the file but **is never imported or used by any route** — dead code / an unused hardening hook. This is one of the most interview-relevant findings in the whole codebase: a very common real-world "security theater" pattern where auth infrastructure exists but isn't actually enforced.

### Devices — `api/routes/devices.py` (prefix `/api/devices`)
| Endpoint | Behavior |
|---|---|
| `POST /` (201) | Create device; 409 on duplicate hostname; writes `CREATE` audit entry |
| `GET /` | Paginated list (`skip`/`limit`), no filters |
| `GET /{id}` | 404 if missing |
| `PUT /{id}` | Partial update via `exclude_unset`; **no audit log written** despite intent |
| `DELETE /{id}` (204) | Hard delete; **no audit log written** |
| `GET /{id}/health` | **Stub** — always returns `reachable=False`, never actually SSHes |
| `POST /{id}/sync` | **Stub** — returns `sync_queued` without enqueuing any real Celery task |

### Configs — `api/routes/configs.py` (prefix `/api/configs`)
| Endpoint | Behavior |
|---|---|
| `POST /validate` | Runs `ConfigValidator` synchronously; audit write happens as a non-blocking `BackgroundTask` |
| `POST /validate-batch` | Loop over multiple device configs, per-device results, no audit writes |
| `POST /validate-async` | Enqueues `validate_config_task.delay(...)`, returns `task_id` |
| `GET /validate-status/{task_id}` | Polls Celery `AsyncResult` |
| `POST /deploy` | Verifies devices exist, generates `batch_id`, enqueues `validate_and_deploy_task.delay(...)`. **Does not create any `Deployment` DB row itself** — see orchestrator gap below |
| `GET /diff` | Returns `desired` config only — `running`/`diff` are always `None` (SSH-based diff not implemented) |
| `GET /history` | DB-only version history (Git log integration mentioned in docstring, not wired) |
| `GET /` | Paginated list, filterable by `device_id` |
| `POST /` (201) | Creates `Configuration` row with **hardcoded `version="pending"`** — Git commit hash integration not wired in |

### Deployments — `api/routes/deployments.py` (prefix `/api/deployments`)
| Endpoint | Behavior |
|---|---|
| `POST /` (202) | Functionally duplicates `configs.deploy_config` — same enqueue call, same batch_id generation. Two server-side endpoints do the same thing |
| `GET /` | Paginated, optional `status` filter |
| `GET /{id}` | 404 if missing |
| `GET /batch/{batch_id}` | All deployments sharing a batch_id |
| `POST /{id}/rollback` | Only allowed if status is `SUCCESS`/`FAILED` (400 otherwise); enqueues `rollback_device.delay(...)` |
| `GET /{id}/logs` | Splits the `logs` TEXT column into lines |
| `GET /{id}/snapshot` | Fetches `ConfigSnapshot` rows, attempts a diff via `SnapshotManager` (best-effort, swallows errors) |

### Audit — `api/routes/audit.py`
Two routers mounted at `/api/audit-log` and `/api/audit` — **the alias literally calls the same handler function**, so they're identical endpoints under two paths. Filters: `user_id`, `action`, `resource_type`; pagination `limit` (1-1000)/`offset`.

### Middleware
- **Rate limiter** (`api/middleware/rate_limiter.py`) — sliding-window algorithm via Redis ZSET (`ZREMRANGEBYSCORE` to evict old entries → `ZADD` → `ZCARD` → `EXPIRE`). Default 100 req/60s per IP; strict 10 req/60s on `POST /api/deployments` and `POST /api/devices`. Exempt paths: `/health`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`, `/`. **Fails open** if Redis is unreachable (never blocks traffic due to an infra outage). Returns `X-RateLimit-*` headers and `Retry-After` on 429. Honors `X-Forwarded-For`. **Perf note:** opens a brand-new Redis connection per check rather than using a pooled client — a real scalability gap under load.
- **Security headers** (`api/middleware/security_headers.py`) — adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection`, `Referrer-Policy`, `Content-Security-Policy: default-src 'self'`; strips the `Server` header.

### Prometheus metrics (`api/metrics.py`)
Gracefully no-ops if `prometheus_client` isn't installed (test-friendly). 11 metrics defined:

| Metric | Type | Labels | Actually used? |
|---|---|---|---|
| `netdeploy_deployments_total` | Counter | strategy, status | ✅ (via unused `track_deployment` decorator — see below) |
| `netdeploy_deployment_duration_seconds` | Histogram | strategy | ✅ (same decorator) |
| `netdeploy_rollbacks_total` | Counter | reason | Defined, not incremented anywhere |
| `netdeploy_devices_total` | Gauge | device_type | **Dead — never incremented anywhere in the codebase** |
| `netdeploy_ssh_connection_errors_total` | Counter | device_type | Defined via unused `track_ssh_command` decorator |
| `netdeploy_ssh_command_duration_seconds` | Histogram | command_type | Same |
| `netdeploy_http_requests_total` | Counter | method, path, status_code | ✅ actively used in `main.py` middleware |
| `netdeploy_http_request_duration_seconds` | Histogram | method, path | ✅ same |
| `netdeploy_rate_limit_exceeded_total` | Counter | path | ✅ used in rate limiter |
| `netdeploy_celery_tasks_total` | Counter | task_name, status | **Dead — never incremented** |
| `netdeploy_celery_queue_depth` | Gauge | queue_name | **Dead — never set** |

`track_deployment()` and `track_ssh_command()` decorators exist and are fully implemented but **are never applied to any real function** in `orchestrator.py` or `ssh_handler.py` — so their metrics are effectively dead despite the decorator code being correct. Good "what would you fix" talking point: wiring these up is low-effort, high-value observability work.

---

## 5. Core Business Logic (`core/`)

### `ConfigValidator` (core/validator.py) — the safety gate before any SSH touches hardware
Validation pipeline, run in order, accumulating `errors`/`warnings`:
1. Type check (must be a dict)
2. **BGP** (if `bgp` key present): local ASN range (1–4294967295), router-id validity (rejects `0.0.0.0` and 127.0.0.0/8), per-neighbor IP validity (rejects loopback/reserved/`0.0.0.0`), **duplicate neighbor IP detection**, iBGP warning (local ASN == remote ASN), keepalive/hold-timer validation per RFC 4271 (hold ≥ 3×keepalive unless disabled)
3. **OSPF** (if `ospf` key present): area ID format (dotted-decimal or plain integer), **duplicate area detection**, hello/dead timer sanity (warns if dead < 4×hello)
4. **Policy conflicts** — same prefix with contradictory permit/deny actions across route policies
5. **Cross-protocol conflicts** — warns if BGP and OSPF router-IDs differ on the same device
6. **CIDR validation** — every prefix in BGP networks, route policies, and OSPF area networks
7. **Device compatibility** — currently one rule: Arista EOS + OSPF MD5 auth → warns "requires EOS 4.22+"

`preflight_reachability()` (ping-check for BGP neighbors before deploy) is a **placeholder that always reports every IP reachable** — the real `asyncio subprocess ping` logic described in the docstring isn't implemented. This means the "unreachable neighbor" warning path in `validate_config_task` is currently unreachable code in practice (always empty).

### `CommandBuilder` (core/command_builder.py) — desired-state dict → vendor CLI
Fully implemented for **4 of 5 vendors** for both BGP and OSPF generation (Cisco XR, Cisco IOS, JunOS, Arista EOS) — each vendor gets syntactically correct, vendor-idiomatic config blocks (e.g., JunOS `set`-style commands with EBGP/IBGP peer-group separation; Cisco IOS wildcard-mask computation for OSPF networks). **Nokia SR-OS is a stub** for both BGP and OSPF (`# CURSOR IMPLEMENTS` placeholder). `build_rollback()` generates negation commands, but only at the **coarse level** — it removes the entire `router bgp`/`router ospf` process, not a targeted diff of just the changed lines (JunOS is the exception: does a real `set ` → `delete ` transform per line).

### `DeploymentOrchestrator` (core/orchestrator.py) — the three rollout strategies

**Canary**: deploy to `device_ids[0]` alone → if it fails, abort the whole batch untouched. If it succeeds, run `_health_check` (see gap below), then deploy the rest in parallel via `asyncio.gather`. **Note:** the 5-minute `CANARY_HEALTH_WAIT_SECONDS` setting exists but is never actually used — the health check runs immediately after the canary deploy, no wait.

**Rolling**: sequential device-by-device; stops immediately (no rollback of already-deployed devices) on first failure or failed health check.

**Atomic**: all devices in parallel via `asyncio.gather`; if **any** fail, rolls back **every** device in the batch (not just the failed one) in parallel.

**`_deploy_to_device()`** — the real per-device pipeline, fully implemented: fetch device+config → mark `IN_PROGRESS` → SSH connect → capture+save BEFORE snapshot → build vendor commands → push config → verify state → capture+save AFTER snapshot → mark `SUCCESS`, or roll back and mark `ROLLBACK` on any exception → always disconnect SSH in a `finally`.

**Two significant gaps found in this pipeline:**
- `_health_check()` is a **partial stub** — it fetches the device/config but the actual SSH-based verification is not implemented; it **always returns `True`**, logging a warning. This means every canary/rolling health gate currently passes unconditionally.
- `_rollback_device()` is also a **partial stub** — it writes an audit log entry and returns `True`, but never actually calls the fully-implemented `SnapshotManager.restore_snapshot()` to push the pre-deploy config back to the device. Rollback is currently a no-op on the wire.
- `deployment_id = uuid4()` is generated **in-memory** inside `_deploy_to_device` but is never persisted as a `Deployment` row before `_update_deployment_status()` looks it up — so status updates silently no-op (there's a `if not deployment: return` guard). Combined with the next finding below, this means the *entire async deployment path triggered from the API* currently writes no Deployment rows, no audit logs, and no snapshots to the database.
- **The root cause of the above**: `tasks/deployment.py`'s Celery tasks instantiate `DeploymentOrchestrator()` with **no `db_session` argument**, so `self.db` is `None` inside every task-triggered deployment. Every DB-touching method in the orchestrator has an `if self.db is None: return` guard, so they all silently no-op. This is the single most important finding in the whole review — it means the persistence layer for deployments (which all the code for is fully written and tested at the unit level with a real db_session) is disconnected from the actual async execution path used by the live API.

### `SSHDevice` (core/ssh_handler.py) — Netmiko wrapper
Fully implemented: `connect()`/`send_command()`/`send_config_set()` all run the blocking Netmiko call via `loop.run_in_executor()` so the async event loop isn't blocked. `send_config_set()` scans output for error substrings (`% `, `Error`, `Invalid`, `Incomplete`, `abort`, `failed`) to detect silent CLI rejections. Vendor-specific command maps exist for `get_bgp_summary()`, `get_ospf_neighbors()`, `get_interface_status()`, `ping()`, `save_config()`. **`disconnect()` is a partial stub** — the real `self.connection.disconnect()` call is commented out; it only dereferences the Python object, meaning SSH sessions are never cleanly closed on the wire (a real resource-leak risk against actual routers under sustained use).

### `StateVerifier` (core/state_verifier.py) — post-deploy safety check
`verify_bgp_neighbors()` checks each configured neighbor's session state (looks for `Established` in the relevant output lines). `verify_ospf_adjacencies()` does a **coarse, non-per-neighbor check** — it just looks for the substring `"FULL"` anywhere in the `show ospf neighbor` output, so it can't tell you *which* neighbor is down if only some are. The JunOS BGP parser has a related looseness: it checks for `"State: Established"` anywhere in the whole output rather than scoped to a specific neighbor's block, so with multiple JunOS neighbors, one Established session can cause all of them to be reported as healthy.

### `SnapshotManager` (core/snapshot_manager.py) — before/after config protection
`save_snapshot()` is fully implemented: SHA-256 hash of `json.dumps(config, sort_keys=True)`, stored per-row (one row per before-or-after event, matching the `config_snapshots` schema). `restore_snapshot()` is also fully implemented — it can push a captured snapshot back via `send_config_set` (it's the orchestrator's `_rollback_device` that fails to call it, not this class). **`diff_snapshots()` has a real logic gap**: because before/after live on separate rows, and the method only fetches the single earliest snapshot row, it effectively diffs that row's `config_before` against its own (empty) `config_after` rather than against the true later AFTER-snapshot row — the "diff" shown to the dashboard is not actually comparing pre- and post-deploy state correctly.

### `GitConfigRepository` (core/git_handler.py) — fully implemented but **not wired into any live code path**
Complete GitPython wrapper: `commit_config()` (writes YAML, commits, pushes), `get_version()`, `get_diff()`, `list_versions()`. All correct, all unit-tested. But `configs.create_config()` hardcodes `version="pending"` instead of calling `commit_config()`, and the Git-based lookup branch in `orchestrator._get_desired_config()` is commented out. **Practical consequence:** only `config_version="latest"` actually resolves to a real config in the deploy pipeline today; passing a specific commit hash silently fails to find anything, because Git versioning was built but never connected to the rest of the app.

---

## 6. Celery Tasks (`tasks/`)

`celery_app.py`: JSON serialization only, `task_acks_late=True` (safer against worker crash mid-task), `worker_prefetch_multiplier=1` (no head-of-line blocking on long deploys), explicit queue routing for `deploy_to_device`→`deploy`, `rollback_device`→`rollback`, `sync_device_state`→`sync` (the top-level `validate_and_deploy_task` and `check_deployment_health` fall to the default `celery` queue, unrouted).

**⚠️ Queue name mismatch between environments**: `docker-compose.yml`'s celery worker listens on `-Q deploy,rollback,sync,celery`, but `k8s/celery-deployment.yaml` instead configures `--queues=deployments,validation,default` — **different queue names entirely** between the two deployment targets. Tasks routed to `deploy`/`rollback`/`sync` in code would never be picked up by a Kubernetes-deployed worker listening on `deployments`/`validation`/`default`. This is exactly the kind of environment-parity bug that's easy to introduce and easy to miss without integration testing across both deploy targets.

`tasks/deployment.py`: `deploy_to_device`, `rollback_device`, `validate_and_deploy_task` are real logic (subject to the DB-session gap above); `sync_device_state()` and `check_deployment_health()` are both full stubs returning `{"status": "not_implemented"}`.

`tasks/validation.py`: `validate_config_task` and `validate_batch_task` are real; `drift_detection_task()` is a full stub.

---

## 7. Dashboard (Streamlit, `dashboard/`)

`NetDeployClient` (dashboard/utils/api_client.py) wraps every API endpoint with defensive try/except (returns `None`/`[]`/`False` on error rather than raising into the UI). All methods are fully implemented — no remaining stubs here despite a header docstring implying otherwise.

Three pages:
- **Deployments** — live metrics (active count, success rate), a trigger-deployment form, an auto-refreshing (5s) table with color-coded status rows, and a detail view with logs + diff.
- **Devices** — registration form with client-side IP validation, inventory table, and per-device health-check/sync buttons. **Note:** since the backing API endpoints for health-check and sync are stubs (see §4), these buttons will currently always report unhealthy / queue nothing real.
- **Audit Log** — filterable table with CSV export. **Found gap:** the "To date" filter control exists in the UI but its value is never actually applied to the query — only "From date" filtering works.

---

## 8. Infrastructure

**Docker Compose** stands up 6 services: `api`, `celery`, `dashboard`, `db` (Postgres 15), `redis` (7), `prometheus`, `grafana` — with healthchecks gating startup order.

**Kubernetes manifests** (`k8s/`) are comprehensive: namespace, ConfigMap, Secrets (with clear "use Vault/Sealed Secrets in prod" warnings), API Deployment (3 replicas, rolling update with zero downtime, hardened `securityContext` — non-root, read-only rootfs, all capabilities dropped, pod anti-affinity), Celery worker + separately-scaled Celery Beat (fixed at 1 replica, correctly — Beat must never scale out), HPAs for both API (CPU+memory) and Celery (CPU only, slower scale-down since deploys are long-running), and Ingress with both a public (rate-limited, TLS via cert-manager) and an internal-only IP-allowlisted `/metrics` endpoint.

**Helm chart** (`helm/netdeploy/`) is **incomplete relative to its own `values.yaml`**: the values file defines full `celery`, `celeryBeat`, and `dashboard` sections (images, resources, autoscaling), but the `templates/` directory only actually contains a Deployment template for the **API** — no Celery worker/beat or Dashboard Deployment/Service templates exist. The chart's own Ingress template even references a `-dashboard` Service that isn't defined anywhere in the chart. Deploying via Helm today would only stand up the API pod, its ConfigMap, HPA, and Ingress — not the rest of the stack.

**CI/CD** (`.github/workflows/`): `test.yml` (pytest against real Postgres/Redis service containers + Codecov upload), `lint.yml` (black/isort/flake8/mypy), `security.yml` (bandit — fails only on HIGH severity; safety — fails on critical/high; Trivy container scan — hard-fails on any CRITICAL/HIGH; a dedicated security test suite run; gitleaks secret scanning), and `deploy.yml` — which, despite its name, **only builds and pushes a Docker image to Docker Hub; it does not actually deploy anything to Kubernetes** (no `kubectl`/`helm` step exists).

**Alembic**: exactly one migration (`001_initial_schema.py`) creates all 5 tables — and, per §3, is missing the `strategy` column that the ORM model expects on `deployments`.

---

## 9. Test Suite — Actual Results (this session)

**Final state: 1,069 tests passing, 2 skipped, 93% overall coverage.**

### Per-module coverage (from `pytest --cov`)
```
api\routes\devices.py                     100%
api\schemas.py                            100%
core\command_builder.py                   100%
core\config.py                            100%
core\git_handler.py                        99%   (missing line 40)
core\orchestrator.py                      100%
core\snapshot_manager.py                  100%
core\ssh_handler.py                         98%   (missing 163-164, the commented-out disconnect call)
core\state_verifier.py                    100%
core\validator.py                          99%   (missing 168, 335)
dashboard\app.py                          100%
dashboard\pages\audit_log.py               96%   (missing 110-117)
dashboard\pages\deployments.py             88%   (missing 92-93,166,169-171,213,220-224,234,240,242)
dashboard\pages\devices.py                 86%   (missing 82-100,124-126)
dashboard\utils\api_client.py             100%
dashboard\utils\formatting.py             100%
tasks\celery_app.py                       100%
tasks\deployment.py                       100%
tasks\validation.py                       100%
------------------------------------------------
TOTAL (incl. test files)                10290 statements, 728 missed, 93%
```
`scripts/demo.py`, `scripts/seed_data.py`, `scripts/generate_diagram.py`, `tests/load/locustfile.py`, `setup.py` show 0% — expected, these are demo/load-test/packaging code not exercised by `pytest`.

### Test file inventory (36 files)
- `tests/unit/` (22 files, no DB required, fast): `test_api_client.py`, `test_checklist_comprehensive.py` (1,044 statements — the largest file, an exhaustive "face-by-face" checklist of every endpoint/client method), `test_command_builder.py`, `test_config_schemas.py`, `test_dashboard_pages.py`, `test_dependencies.py`, `test_deployment_tasks.py`, `test_formatting.py`, `test_git_handler.py` + `test_git_handler_p3.py`, `test_metrics.py`, `test_orchestrator.py` + `test_orchestrator_commands.py`, `test_phase5_coverage.py`, `test_rate_limiter.py`, `test_snapshot_manager.py`, `test_ssh_connect.py` + `test_ssh_handler.py`, `test_state_verifier.py`, `test_validation_tasks.py`, `test_validator.py`
- `tests/integration/` (15 files, needs live Postgres+Redis): `test_audit_extended.py`, `test_auth_api.py`, `test_comprehensive.py`, `test_configs_phase3.py`, `test_dashboard.py`, `test_deploy_flow.py`, `test_deploy_pipeline.py`, `test_deployments_extended.py`, `test_deployments_phase3.py`, `test_devices_extended.py`, `test_full_system.py`, `test_production_readiness.py`, `test_rollback_flow.py`, `test_validation_api.py`
- `tests/security/` (1 file): `test_security_headers.py` — SQLi/XSS injection payloads against hostname fields, auth bypass checks, sensitive-data-exposure checks (no password fields leaked, no stack traces in error responses), rate-limit enforcement

### Known flake (not a real bug)
`test_entries_ordered_newest_first` occasionally fails under full-suite timing pressure (a timestamp-ordering race — likely needs a monotonic sequence column rather than relying on `DateTime` resolution for `ORDER BY`). Confirmed reliable when run in isolation; reproduced this exact flake once during the session, reran in isolation twice and it passed both times.

### Bugs found and fixed this session
Full before/after detail is in [INTERVIEW_PREP.md](INTERVIEW_PREP.md) §"Bugs found and fixed"; summary:
1. `NetDeployClient(api_url=..., token="tok")` — constructor doesn't accept `token`
2. `patch("tasks.validation.ConfigValidator", ...)` — wrong import path (it's imported inside a function, not at module scope); fixed to patch `core.validator.ConfigValidator`
3. `patch("tasks.validation.asyncio.run", ...)` — same issue; fixed to patch global `asyncio.run`
4. `Deployment(..., created_by="test")` — no such column on the model
5. `_mock_response()` test helper: `json_data or {}` silently replaced a valid empty list `[]` with `{}` because `[]` is falsy in Python — classic "use `is not None`, not truthiness" bug
6. Two assertions checked the wrong return shape (`health_check()` returns `bool` not a dict; `rollback_deployment()`'s mock response was missing the `task_id` field the method actually reads)
7. **Real (non-test) bug**: `.env` pointed `DATABASE_URL`/`REDIS_URL`/`CELERY_BROKER_URL` at Docker Compose network hostnames (`db`, `redis`) instead of `localhost` — broke every host-side integration test with `Connection refused` / `getaddrinfo failed` until fixed to match the ports Compose actually publishes to the host

---

## 10. Build History (from git log)

| Phase | Commit | Result |
|---|---|---|
| 1 — Foundation | `fbb5f0c` | Models, schemas, Docker, CI/CD, Alembic |
| 1 fixes | `534a338` | bcrypt compat, Pydantic `orm_mode`, dev deps |
| 2 — Validation | `f07bc94` | 114/114 tests, 74% coverage |
| 2 extended | `d81803f` | 215/215 tests, 83% coverage |
| 3 — Orchestration | `690ad30` | 474/474 tests, 88% coverage |
| 6 — Portfolio polish | `fac0c77` | Demo scripts, seed data, comprehensive tests |

Each phase shipped with its own recorded test count and coverage number in the commit message.

---

## 11. If Asked "What Would You Fix First"

In priority order, based on actual blast radius:
1. **The orchestrator DB-session gap** (§5) — the live async deployment path currently persists nothing (no Deployment rows, no audit trail, no snapshots) because Celery tasks instantiate the orchestrator without a `db_session`. This is silent data loss on the exact system whose entire purpose is auditability.
2. **`_rollback_device()` being a no-op** (§5) — "rollback" currently only writes an audit log; it never restores the pre-deploy config to the device. In a real incident, an operator clicking "rollback" would get a false sense of safety.
3. **Auth being effectively optional** (§4) — `get_current_user()`'s anonymous-admin fallback means the whole API is unauthenticated unless a caller happens to supply a token. `require_auth()` already exists and is unused — this is a one-line dependency swap per route.
4. **Queue name mismatch between docker-compose and k8s** (§6) — silent task starvation if someone deployed to k8s today.
5. **Incomplete Helm chart** (§8) — would only deploy 1/4 of the services described in its own `values.yaml`.
