"""
NetDeploy load test suite using Locust.

Run:
    pip install locust
    locust -f tests/load/locustfile.py --host=http://localhost:8000

Or headless (CI):
    locust -f tests/load/locustfile.py --host=http://localhost:8000 \
           --headless --users 50 --spawn-rate 5 --run-time 60s \
           --html tests/load/report.html

Scenarios:
    NetDeployReadUser   — read-heavy (list devices, list deployments, audit log)
    NetDeployWriteUser  — write-heavy (create device, trigger deployment, rollback)
    NetDeployMixedUser  — realistic 80/20 read/write mix (default)

Target SLOs (adjust in locust.conf):
    p50 < 100ms, p95 < 500ms, p99 < 2s
    Error rate < 1%

[CURSOR IMPLEMENTS task weights and realistic payload generation]
"""

import json
import random
import string
from uuid import uuid4

from locust import HttpUser, task, between, events
from locust.runners import MasterRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEVICE_TYPES = ["cisco_xr", "cisco_ios", "junos", "arista_eos", "nokia_sros"]
STRATEGIES = ["atomic", "rolling", "canary"]


def random_hostname(prefix="load-r"):
    """Generate a unique hostname for load test devices."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{prefix}-{suffix}"


def random_ip():
    """Generate a random RFC-1918 management IP."""
    return f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"


def random_asn():
    return random.randint(64512, 65535)


# ---------------------------------------------------------------------------
# Read-heavy user (monitoring/dashboard simulation)
# ---------------------------------------------------------------------------

class NetDeployReadUser(HttpUser):
    """
    Simulates a read-only dashboard user polling for status updates.

    [CURSOR IMPLEMENTS]: Each task should:
      - Call the appropriate endpoint
      - Assert response.status_code in (200, 404)
      - Log failures via self.environment.events.request.fire() if needed
    """
    wait_time = between(1, 3)
    weight = 3  # 3x more read users than write users

    def on_start(self):
        """Cache a list of device IDs for subsequent read tasks."""
        r = self.client.get("/api/devices", name="/api/devices [list]")
        if r.status_code == 200:
            devices = r.json()
            self.device_ids = [d["id"] for d in devices] if devices else []
        else:
            self.device_ids = []

        r = self.client.get("/api/deployments", name="/api/deployments [list]")
        if r.status_code == 200:
            deps = r.json()
            self.deployment_ids = [d["id"] for d in deps] if deps else []
        else:
            self.deployment_ids = []

    @task(5)
    def list_devices(self):
        """GET /api/devices — highest frequency (dashboard refresh)."""
        self.client.get("/api/devices", name="/api/devices [list]")

    @task(5)
    def list_deployments(self):
        """GET /api/deployments — dashboard deployment table."""
        self.client.get("/api/deployments?limit=20", name="/api/deployments [list]")

    @task(3)
    def get_audit_log(self):
        """GET /api/audit — audit log page."""
        self.client.get("/api/audit?limit=50", name="/api/audit [list]")

    @task(2)
    def health_check(self):
        """GET /health — monitoring agent polling."""
        self.client.get("/health", name="/health")

    @task(2)
    def get_device_detail(self):
        """GET /api/devices/{id} — device detail panel."""
        if not self.device_ids:
            return
        device_id = random.choice(self.device_ids)
        self.client.get(f"/api/devices/{device_id}", name="/api/devices/[id]")

    @task(1)
    def get_deployment_detail(self):
        """GET /api/deployments/{id} — deployment detail + logs."""
        if not self.deployment_ids:
            return
        dep_id = random.choice(self.deployment_ids)
        self.client.get(f"/api/deployments/{dep_id}", name="/api/deployments/[id]")
        self.client.get(f"/api/deployments/{dep_id}/logs", name="/api/deployments/[id]/logs")

    @task(1)
    def list_configs(self):
        """GET /api/configs — config inventory."""
        self.client.get("/api/configs", name="/api/configs [list]")


# ---------------------------------------------------------------------------
# Write-heavy user (CI/CD pipeline simulation)
# ---------------------------------------------------------------------------

class NetDeployWriteUser(HttpUser):
    """
    Simulates automated deployment pipelines triggering changes.

    [CURSOR IMPLEMENTS]: Populate self.created_device_ids on start; clean up in on_stop.
    """
    wait_time = between(5, 15)  # writes are slower / less frequent
    weight = 1

    def on_start(self):
        self.created_device_ids = []

    def on_stop(self):
        """Clean up devices created during the load test."""
        # [CURSOR IMPLEMENTS]: DELETE each device in self.created_device_ids
        pass

    @task(4)
    def register_device(self):
        """POST /api/devices — register a new device."""
        payload = {
            "hostname": random_hostname(),
            "management_ip": random_ip(),
            "device_type": random.choice(DEVICE_TYPES),
            "ssh_port": 22,
            "bgp_asn": random_asn(),
            "ospf_area": "0.0.0.0",
        }
        with self.client.post(
            "/api/devices",
            json=payload,
            name="/api/devices [create]",
            catch_response=True,
        ) as r:
            if r.status_code == 201:
                self.created_device_ids.append(r.json().get("id"))
                r.success()
            elif r.status_code == 409:
                r.success()  # duplicate is ok under load
            else:
                r.failure(f"Unexpected status {r.status_code}: {r.text[:200]}")

    @task(2)
    def trigger_deployment(self):
        """POST /api/deployments — trigger a deployment."""
        if not self.created_device_ids:
            return
        device_id = random.choice(self.created_device_ids)
        payload = {
            "device_ids": [device_id],
            "config_version": "latest",
            "strategy": random.choice(STRATEGIES),
            "dry_run": True,  # safety: don't actually SSH in load tests
        }
        with self.client.post(
            "/api/deployments",
            json=payload,
            name="/api/deployments [trigger]",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 201, 202):
                r.success()
            elif r.status_code == 422:
                r.success()  # validation error is ok (no real device)
            else:
                r.failure(f"Deploy failed {r.status_code}: {r.text[:200]}")

    @task(1)
    def validate_config(self):
        """POST /api/configs/validate — config validation."""
        # [CURSOR IMPLEMENTS]: POST a minimal BGP config payload for validation
        payload = {
            "device_id": str(uuid4()),
            "config": {
                "bgp": {"asn": random_asn(), "neighbors": []},
                "ospf": {"areas": []},
            }
        }
        self.client.post("/api/configs/validate", json=payload, name="/api/configs [validate]")


# ---------------------------------------------------------------------------
# Mixed user (default — realistic 80/20)
# ---------------------------------------------------------------------------

class NetDeployMixedUser(NetDeployReadUser):
    """
    Realistic user: mostly reads with occasional writes.
    Inherits all read tasks, adds write tasks at lower weight.
    """
    wait_time = between(2, 8)
    weight = 2

    def on_start(self):
        super().on_start()
        self.my_device_ids = []

    @task(1)
    def register_and_read(self):
        """Register a device then immediately read it back."""
        payload = {
            "hostname": random_hostname("mix-r"),
            "management_ip": random_ip(),
            "device_type": random.choice(DEVICE_TYPES),
            "ssh_port": 22,
        }
        r = self.client.post("/api/devices", json=payload, name="/api/devices [create]")
        if r.status_code == 201:
            device_id = r.json().get("id")
            self.my_device_ids.append(device_id)
            self.client.get(f"/api/devices/{device_id}", name="/api/devices/[id]")


# ---------------------------------------------------------------------------
# Locust event hooks — aggregate SLO report at end of run
# ---------------------------------------------------------------------------

@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    """Print SLO pass/fail summary when the test ends."""
    stats = environment.runner.stats.total
    if stats.num_requests == 0:
        return

    p95 = stats.get_response_time_percentile(0.95)
    p99 = stats.get_response_time_percentile(0.99)
    error_pct = stats.fail_ratio * 100

    print("\n" + "=" * 60)
    print("NetDeploy Load Test — SLO Summary")
    print("=" * 60)
    print(f"  Total requests : {stats.num_requests:,}")
    print(f"  Failures       : {stats.num_failures:,} ({error_pct:.2f}%)")
    print(f"  p95 latency    : {p95:.0f} ms  {'✅ PASS' if p95 < 500 else '❌ FAIL'}")
    print(f"  p99 latency    : {p99:.0f} ms  {'✅ PASS' if p99 < 2000 else '❌ FAIL'}")
    print(f"  Error rate     : {error_pct:.2f}%  {'✅ PASS' if error_pct < 1 else '❌ FAIL'}")
    print("=" * 60)

    # Fail CI if SLOs are breached
    if p95 >= 500 or error_pct >= 1:
        environment.process_exit_code = 1
