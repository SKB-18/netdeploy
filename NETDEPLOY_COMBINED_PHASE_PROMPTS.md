# NetDeploy: COMBINED PHASE PROMPTS (Cowork + Cursor)

**WORKFLOW FOR EACH PHASE:**
1. Run Cowork Phase N prompt → Get scaffold
2. Test locally (docker compose up, pytest)
3. Run Cursor Phase N prompt → Implement
4. Test locally (docker compose up, pytest)
5. Push to GitHub
6. Move to Phase N+1

---

# PHASE 1: FOUNDATION

## Step 1: Cowork Phase 1 Prompt

[Copy from NETDEPLOY_COWORK_WITH_LOCAL_TESTING.md → PHASE 1: FOUNDATION section]

## Step 2: Local Testing After Cowork

```bash
# Extract files, create repo structure
# Copy .env.example to .env

# Test 1: Docker build
docker build -t netdeploy .

# Test 2: Docker compose
docker compose up
# Wait for all services to be healthy (shows as "healthy" for each service)

# Test 3: API health check
curl http://localhost:8000/health
# Should return: {"status": "healthy"}

# Test 4: Swagger UI
curl http://localhost:8000/docs
# Should return HTML (Swagger UI)

# Test 5: Database is working
docker compose exec db psql -U postgres -d netdeploy -c "\dt"
# Should show empty tables (ready for migrations)

# Test 6: Redis is working
docker compose exec redis redis-cli ping
# Should return: PONG

# Test 7: Prometheus is working
curl http://localhost:9090/metrics
# Should return metrics

# Test 8: Grafana is working
curl http://localhost:3000
# Should return HTML

# Test 9: Python imports work
docker compose exec api python -c "import api; from api.models import Device"
# Should not error

# Test 10: Pytest finds tests
docker compose exec api pytest --collect-only
# Should list test files
```

If all pass → git commit Phase 1 scaffold

## Step 3: Cursor Phase 1 Prompt

[Copy from NETDEPLOY_CURSOR_WITH_LOCAL_TESTING.md → PHASE 1: FOUNDATION section]

## Step 4: Local Testing After Cursor

```bash
# Test 1: Run tests
docker compose exec api pytest tests/ -v

# Expected output:
# tests/unit/test_schemas.py::test_device_request_valid PASSED
# tests/unit/test_schemas.py::test_device_request_invalid_asn PASSED
# ... (all tests pass)

# Test 2: Check coverage
docker compose exec api pytest tests/ --cov=api --cov=core --cov-report=term-missing

# Expected: 85%+ coverage

# Test 3: Verify all imports
docker compose exec api python -c "
from api.models import Device, Configuration, Deployment, AuditLog, ConfigSnapshot
from api.schemas import DeviceRequest, ConfigRequest, DeploymentRequest
from api.database import engine, SessionLocal
from api.main import app
from api.dependencies import get_db, get_current_user
from tests.fixtures.mock_devices import MockRouter
print('All imports successful!')
"

# Test 4: Health check still works
curl http://localhost:8000/health

# Test 5: Database migrations
docker compose exec api alembic upgrade head
docker compose exec db psql -U postgres -d netdeploy -c "\dt"
# Should show: devices, configurations, deployments, audit_logs, config_snapshots

# Test 6: Create test device via mock
docker compose exec api python -c "
from tests.fixtures.mock_devices import MockRouter
router = MockRouter('test-router', 65001)
assert router.connect()
output = router.send_command('show version')
print('Mock router works!')
"
```

If all pass → git commit Phase 1 implementation

---

# PHASE 2: CONFIG VALIDATION

## Step 1: Cowork Phase 2 Prompt

[Copy from NETDEPLOY_COWORK_WITH_LOCAL_TESTING.md → PHASE 2: CONFIG VALIDATION section]

## Step 2: Local Testing After Cowork

```bash
docker compose up

# Verify Phase 2 structure was added
docker compose exec api python -c "
from core.validator import ConfigValidator, ValidationResult
from core.config import Settings
from api.routes import configs
"

# Verify new schemas
docker compose exec api pytest tests/unit/test_schemas.py -v
```

## Step 3: Cursor Phase 2 Prompt

[Copy from NETDEPLOY_CURSOR_WITH_LOCAL_TESTING.md → PHASE 2: CONFIG VALIDATION section]

## Step 4: Local Testing After Cursor

```bash
# Test 1: Validator works
docker compose exec api python -c "
from core.validator import ConfigValidator

validator = ConfigValidator()

# Test valid BGP config
valid_config = {
    'bgp': {
        'local_asn': 65001,
        'neighbors': [
            {'neighbor_ip': '192.168.1.1', 'remote_asn': 65002}
        ]
    }
}
result = validator.validate(valid_config)
assert result.valid, f'Should be valid, got errors: {result.errors}'
print('Valid config passed!')

# Test invalid ASN
invalid_config = {
    'bgp': {
        'local_asn': 999999999  # Invalid
    }
}
result = validator.validate(invalid_config)
assert not result.valid, 'Should be invalid'
assert len(result.errors) > 0, 'Should have errors'
print('Invalid ASN correctly rejected!')
"

# Test 2: API validation endpoint
curl -X POST http://localhost:8000/api/configs/validate \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "device-1",
    "desired_state": {
      "bgp": {
        "local_asn": 65001,
        "neighbors": [{"neighbor_ip": "192.168.1.1", "remote_asn": 65002}]
      }
    },
    "description": "Test config"
  }'
# Should return: {"valid": true, "errors": [], "warnings": []}

# Test 3: Run test suite
docker compose exec api pytest tests/ -v --cov=core --cov=api

# Expected: All tests pass, 85%+ coverage
```

If all pass → git commit Phase 2 implementation

---

# PHASE 3: DEPLOYMENT ORCHESTRATION

## Step 1: Cowork Phase 3 Prompt

[Copy from NETDEPLOY_COWORK_WITH_LOCAL_TESTING.md → PHASE 3: DEPLOYMENT ORCHESTRATION section]

## Step 2: Local Testing After Cowork

```bash
docker compose up

# Verify Phase 3 structure
docker compose exec api python -c "
from core.orchestrator import DeploymentOrchestrator
from core.ssh_handler import SSHDevice
from core.git_handler import GitConfigRepository
from api.routes import deployments
"
```

## Step 3: Cursor Phase 3 Prompt

[Copy from NETDEPLOY_CURSOR_WITH_LOCAL_TESTING.md → PHASE 3: DEPLOYMENT ORCHESTRATION section]

## Step 4: Local Testing After Cursor

```bash
# Test 1: Orchestrator strategies
docker compose exec api pytest tests/unit/test_orchestrator.py -v

# Expected: All strategy tests pass
# - test_canary_strategy PASSED
# - test_rolling_strategy PASSED
# - test_atomic_strategy PASSED

# Test 2: SSH handler with mock
docker compose exec api pytest tests/unit/test_ssh_handler.py -v

# Expected: SSH tests pass
# - test_connect PASSED
# - test_send_command PASSED
# - test_get_running_config PASSED

# Test 3: Git handler
docker compose exec api pytest tests/unit/test_git_handler.py -v

# Expected: Git tests pass
# - test_commit_config PASSED
# - test_get_version PASSED
# - test_get_diff PASSED

# Test 4: Deployment API endpoints
curl -X GET http://localhost:8000/api/deployments
# Should return: [] (empty list)

# Test 5: Full test suite
docker compose exec api pytest tests/ -v --cov=core --cov=api

# Expected: All tests pass, 85%+ coverage
```

If all pass → git commit Phase 3 implementation

---

# PHASE 4: DASHBOARD

## Step 1: Cowork Phase 4 Prompt

[Copy from NETDEPLOY_COWORK_WITH_LOCAL_TESTING.md → PHASE 4: DASHBOARD section]

## Step 2: Local Testing After Cowork

```bash
docker compose up

# Verify Phase 4 structure
docker compose exec api python -c "
from dashboard.utils.api_client import NetDeployClient
from dashboard import app
"

# Verify dashboard service is running
curl http://localhost:8501
# Should return Streamlit HTML
```

## Step 3: Cursor Phase 4 Prompt

[Copy from NETDEPLOY_CURSOR_WITH_LOCAL_TESTING.md → PHASE 4: DASHBOARD section]

## Step 4: Local Testing After Cursor

```bash
# Test 1: API client works
docker compose exec api python -c "
from dashboard.utils.api_client import NetDeployClient

client = NetDeployClient('http://localhost:8000')

# Test health check
assert client.health_check(), 'API should be healthy'

# Test list devices (empty for now)
devices = client.list_devices()
assert isinstance(devices, list), 'Should return list'

print('API client works!')
"

# Test 2: Dashboard loads without errors
# Open http://localhost:8501 in browser
# All pages should load:
# - Deployments
# - Devices
# - Audit Log
# - Settings

# Test 3: No Python errors in dashboard
docker compose logs dashboard
# Should not show Python exceptions

# Test 4: Run all tests
docker compose exec api pytest tests/ -v

# Expected: All tests pass
```

If all pass → git commit Phase 4 implementation

---

# PHASE 5: PRODUCTION READINESS

## Step 1: Cowork Phase 5 Prompt

[Copy from NETDEPLOY_COWORK_WITH_LOCAL_TESTING.md → PHASE 5: PRODUCTION READINESS section]

## Step 2: Local Testing After Cowork

```bash
# Verify k8s manifests syntax
# Note: Need kubectl installed for this
kubectl apply -f k8s/ --dry-run=client -o yaml

# Verify Helm chart syntax
helm lint helm/netdeploy/
helm template netdeploy helm/netdeploy/ | head -50

# Verify prometheus.yml
docker compose exec api python -c "
import yaml
with open('prometheus.yml') as f:
    config = yaml.safe_load(f)
    print('Prometheus config valid!')
"

# Verify grafana-dashboards.json
docker compose exec api python -c "
import json
with open('grafana-dashboards.json') as f:
    dashboard = json.load(f)
    print('Grafana dashboard valid!')
"
```

## Step 3: Cursor Phase 5 Prompt

[Copy from NETDEPLOY_CURSOR_WITH_LOCAL_TESTING.md → PHASE 5: PRODUCTION READINESS section]

## Step 4: Local Testing After Cursor

```bash
# Test 1: Metrics endpoint works
curl http://localhost:8000/metrics
# Should return Prometheus format metrics

# Test 2: Load testing (if locust installed)
docker compose up

# In another terminal:
pip install locust
locust -f tests/load/locustfile.py --host=http://localhost:8000
# Run for 1 minute, verify:
# - Response time < 100ms p99
# - No errors
# - Throughput > 100 req/sec

# Test 3: Security check
docker compose exec api safety check
# Should show no CRITICAL vulnerabilities

# Test 4: Run all tests with coverage
docker compose exec api pytest tests/ -v --cov=api --cov=core --cov-report=term-missing

# Expected: 85%+ coverage
```

If all pass → git commit Phase 5 implementation

---

# PHASE 6: PORTFOLIO POLISH

## Step 1: Cowork Phase 6 Prompt

[Copy from NETDEPLOY_COWORK_WITH_LOCAL_TESTING.md → PHASE 6: PORTFOLIO POLISH section]

## Step 2: Cursor Phase 6 Prompt

[Copy from NETDEPLOY_CURSOR_WITH_LOCAL_TESTING.md → PHASE 6: PORTFOLIO POLISH section]

## Step 3: Final Comprehensive Testing

```bash
# Test 1: Everything still works
docker compose up
# Wait for all services healthy

# Test 2: All tests pass
docker compose exec api pytest tests/ -v --cov=api --cov=core
# Expected: 100% of code covered, all tests PASSED

# Test 3: All endpoints respond
curl http://localhost:8000/health
curl http://localhost:8000/docs
curl http://localhost:8000/api/devices
curl http://localhost:8000/api/deployments
curl http://localhost:8000/api/audit-log

# Test 4: Dashboard works
curl http://localhost:8501
# Should get Streamlit HTML

# Test 5: Load test passes
pip install locust
locust -f tests/load/locustfile.py --host=http://localhost:8000 -u 10 -r 1 --run-time 60s
# Expected:
# - p99 latency < 100ms
# - Failure rate < 1%
# - Throughput > 100 req/sec

# Test 6: Security scan
docker compose exec api safety check
# Expected: No CRITICAL vulnerabilities

# Test 7: Documentation valid
ls -la README.md ARCHITECTURE.md CONTRIBUTING.md
wc -l README.md ARCHITECTURE.md
# Expected: All files exist and have substantial content

# Test 8: Code style
docker compose exec api black --check api core tasks tests
docker compose exec api flake8 api core tasks tests --max-line-length=100
# Expected: No style errors

# Test 9: Docker image builds
docker build -t netdeploy:latest .
# Expected: Build successful

# Test 10: Final check - no TODO comments in production code
docker compose exec api grep -r "TODO\|FIXME" api core tasks --include="*.py"
# Expected: No output (no TODOs in production code)
```

## Step 4: Final Push to GitHub

```bash
# Verify git status
git status
# Should show modified files ready to commit

# Commit everything
git add -A
git commit -m "Phase 6: Complete portfolio and documentation

- Polish all documentation
- Verify all metrics and performance
- Final comprehensive testing
- Ready for production and interviews"

# Push to GitHub
git push origin main

# Go to GitHub and verify:
# - Repo looks professional
# - README is clear
# - All files are there
# - Code is properly formatted
```

---

## QUICK REFERENCE: Phase-by-Phase Checklist

### Phase 1: Foundation ✅
- [ ] docker compose up works
- [ ] curl http://localhost:8000/health returns 200
- [ ] curl http://localhost:8000/docs loads Swagger
- [ ] Database created with proper tables
- [ ] All Python imports work
- [ ] Pytest finds all test files
- [ ] Commit to GitHub

### Phase 2: Config Validation ✅
- [ ] Validator accepts valid configs
- [ ] Validator rejects invalid configs
- [ ] API endpoint POST /api/configs/validate works
- [ ] Validation catches 99% of errors
- [ ] pytest tests/unit/test_validator.py passes
- [ ] pytest tests/ passes with 85%+ coverage
- [ ] Commit to GitHub

### Phase 3: Deployment Orchestration ✅
- [ ] Canary strategy works
- [ ] Rolling strategy works
- [ ] Atomic strategy works
- [ ] SSH handler connects to mock device
- [ ] Git handler commits/diffs configs
- [ ] API endpoints POST /api/configs/deploy works
- [ ] pytest tests/ passes with 85%+ coverage
- [ ] Commit to GitHub

### Phase 4: Dashboard ✅
- [ ] Dashboard loads at http://localhost:8501
- [ ] API client connects to backend
- [ ] Deployments page loads
- [ ] Devices page loads
- [ ] Audit Log page loads
- [ ] Settings page loads
- [ ] No errors in Streamlit console
- [ ] Commit to GitHub

### Phase 5: Production Readiness ✅
- [ ] Kubernetes manifests pass validation
- [ ] Helm chart passes lint
- [ ] Prometheus config valid
- [ ] Grafana dashboard valid
- [ ] Metrics endpoint works
- [ ] Load test: p99 < 100ms
- [ ] Security scan: no CRITICAL
- [ ] Commit to GitHub

### Phase 6: Portfolio Polish ✅
- [ ] README.md is comprehensive
- [ ] ARCHITECTURE.md explains design
- [ ] Blog post outline is complete
- [ ] Interview guide is ready
- [ ] Demo guide is step-by-step
- [ ] All documentation is correct
- [ ] No broken links
- [ ] Commit to GitHub

---

## Total Time Estimate

| Phase | Cowork | Local Test | Cursor | Local Test | Git | Total |
|-------|--------|-----------|--------|-----------|-----|-------|
| 1 | 30 min | 10 min | 60 min | 20 min | 5 min | 2h 5min |
| 2 | 25 min | 10 min | 45 min | 15 min | 5 min | 1h 40min |
| 3 | 30 min | 15 min | 90 min | 25 min | 5 min | 2h 45min |
| 4 | 20 min | 10 min | 45 min | 15 min | 5 min | 1h 35min |
| 5 | 20 min | 15 min | 30 min | 20 min | 5 min | 1h 30min |
| 6 | 15 min | 10 min | 30 min | 20 min | 5 min | 1h 20min |
| **TOTAL** | **2h 20min** | **1h 10min** | **5h 20min** | **2h 15min** | **30min** | **~12 hours** |

**Spread across 6-8 weeks for a high-quality result.**

---

**Ready to start? Begin with Phase 1!**
