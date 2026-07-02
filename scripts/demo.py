#!/usr/bin/env python3
"""
NetDeploy Demo Script — end-to-end portfolio walkthrough.

This script demonstrates the full NetDeploy workflow against a live API:
  1. Register two simulated devices
  2. Create a BGP + OSPF configuration
  3. Validate the configuration (catches intentional errors)
  4. Fix the config and validate again (passes)
  5. Trigger an atomic deployment
  6. Poll deployment status until complete
  7. Fetch deployment logs + config diff
  8. Trigger a manual rollback
  9. Show audit log trail
  10. Clean up demo devices

Usage:
    # Start the stack first:
    docker compose up -d
    alembic upgrade head

    # Run the demo:
    python scripts/demo.py

    # Run against a remote server:
    python scripts/demo.py --api-url https://api.netdeploy.example.com
"""

import argparse
import json
import sys
import time
from uuid import uuid4

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEMO_DEVICES = [
    {
        "hostname": f"demo-spine-01-{uuid4().hex[:6]}",
        "management_ip": "10.100.0.1",
        "device_type": "cisco_xr",
        "ssh_port": 22,
        "bgp_asn": 65001,
        "ospf_area": "0.0.0.0",
        "os_version": "7.9.1",
    },
    {
        "hostname": f"demo-spine-02-{uuid4().hex[:6]}",
        "management_ip": "10.100.0.2",
        "device_type": "cisco_xr",
        "ssh_port": 22,
        "bgp_asn": 65001,
        "ospf_area": "0.0.0.0",
        "os_version": "7.9.1",
    },
]

# Intentionally bad config (duplicate neighbor) for validation demo
BAD_BGP_CONFIG = {
    "asn": 65001,
    "router_id": "10.100.0.1",
    "neighbors": [
        {"peer_ip": "10.100.0.2", "remote_asn": 65002, "description": "spine-02"},
        {"peer_ip": "10.100.0.2", "remote_asn": 65003, "description": "spine-02-dup"},  # duplicate!
    ],
    "networks": ["10.100.0.0/24"],
}

# Fixed config
GOOD_BGP_CONFIG = {
    "asn": 65001,
    "router_id": "10.100.0.1",
    "neighbors": [
        {"peer_ip": "10.100.0.2", "remote_asn": 65002, "description": "spine-02"},
        {"peer_ip": "10.100.0.3", "remote_asn": 65003, "description": "leaf-01"},
    ],
    "networks": ["10.100.0.0/24", "10.200.0.0/16"],
}

OSPF_CONFIG = {
    "process_id": 1,
    "router_id": "10.100.0.1",
    "areas": [
        {
            "area_id": "0.0.0.0",
            "interfaces": [
                {"name": "GigabitEthernet0/0/0", "type": "point-to-point", "hello_interval": 10},
                {"name": "GigabitEthernet0/0/1", "type": "point-to-point", "hello_interval": 10},
            ],
        }
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DemoClient:
    def __init__(self, api_url: str):
        self.base = api_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"

    def _url(self, path: str) -> str:
        return f"{self.base}{path}"

    def get(self, path, **kw):
        return self.session.get(self._url(path), **kw)

    def post(self, path, **kw):
        return self.session.post(self._url(path), **kw)

    def delete(self, path, **kw):
        return self.session.delete(self._url(path), **kw)


def banner(text: str):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def ok(msg: str):
    print(f"  ✅ {msg}")


def warn(msg: str):
    print(f"  ⚠️  {msg}")


def fail(msg: str):
    print(f"  ❌ {msg}")
    sys.exit(1)


def pretty(data) -> str:
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Demo steps
# ---------------------------------------------------------------------------

def step_0_health(client: DemoClient):
    banner("Step 0: Health Check")
    r = client.get("/health")
    if r.status_code != 200:
        fail(f"API not reachable: {r.status_code} {r.text}")
    body = r.json()
    status = body.get("status", "unknown")
    print(f"  API status : {status}")
    print(f"  Database   : {body.get('database', '?')}")
    print(f"  Redis      : {body.get('redis', '?')}")
    print(f"  Version    : {body.get('version', '?')}")
    if status not in ("healthy", "degraded"):
        fail("API is not healthy")
    ok("API is up")
    return body


def step_1_register_devices(client: DemoClient) -> list[str]:
    banner("Step 1: Register Demo Devices")
    device_ids = []
    for device in DEMO_DEVICES:
        r = client.post("/api/devices", json=device)
        if r.status_code not in (200, 201):
            fail(f"Failed to register {device['hostname']}: {r.text}")
        created = r.json()
        device_ids.append(created["id"])
        ok(f"Registered {device['hostname']} → ID: {created['id'][:8]}...")
    return device_ids


def step_2_validate_bad_config(client: DemoClient, device_ids: list[str]):
    banner("Step 2: Validate Config (expects FAILURE — duplicate neighbor)")
    payload = {
        "device_id": device_ids[0],
        "bgp": BAD_BGP_CONFIG,
        "ospf": OSPF_CONFIG,
    }
    r = client.post("/api/configs/validate", json=payload)
    body = r.json()
    if body.get("valid") is True:
        warn("Validator did not catch the duplicate neighbor — check validator logic")
    else:
        errors = body.get("errors", [])
        ok(f"Validation correctly rejected config with {len(errors)} error(s):")
        for e in errors[:3]:
            print(f"     • {e}")


def step_3_validate_good_config(client: DemoClient, device_ids: list[str]) -> str:
    banner("Step 3: Validate Config (expects PASS — fixed config)")
    payload = {
        "device_id": device_ids[0],
        "bgp": GOOD_BGP_CONFIG,
        "ospf": OSPF_CONFIG,
    }
    r = client.post("/api/configs/validate", json=payload)
    body = r.json()
    if not body.get("valid", False):
        warn(f"Fixed config still failing: {body.get('errors')}")
    else:
        ok(f"Config validated successfully (warnings: {len(body.get('warnings', []))})")

    # Save config
    save_payload = {
        "device_id": device_ids[0],
        "version": "demo-v1",
        "bgp": GOOD_BGP_CONFIG,
        "ospf": OSPF_CONFIG,
        "created_by": "demo-script",
    }
    r = client.post("/api/configs", json=save_payload)
    if r.status_code in (200, 201):
        config_version = r.json().get("version", "demo-v1")
        ok(f"Config saved as version: {config_version}")
        return config_version
    else:
        warn(f"Config save failed ({r.status_code}) — using 'latest'")
        return "latest"


def step_4_trigger_deployment(client: DemoClient, device_ids: list[str], config_version: str) -> str:
    banner("Step 4: Trigger Atomic Deployment")
    payload = {
        "device_ids": device_ids,
        "config_version": config_version,
        "strategy": "atomic",
        "dry_run": True,  # safe — no real SSH in demo
    }
    r = client.post("/api/deployments", json=payload)
    if r.status_code not in (200, 201, 202):
        fail(f"Deployment trigger failed: {r.status_code} {r.text[:300]}")
    body = r.json()
    deployment_id = body.get("deployment_id") or body.get("id") or body.get("batch_id")
    if not deployment_id:
        warn(f"No deployment_id in response: {body}")
        deployment_id = "unknown"
    ok(f"Deployment triggered → ID: {str(deployment_id)[:8]}...")
    print(f"  Strategy: atomic | Devices: {len(device_ids)} | Dry run: True")
    return str(deployment_id)


def step_5_poll_status(client: DemoClient, deployment_id: str):
    banner("Step 5: Poll Deployment Status")
    if deployment_id == "unknown":
        warn("Skipping poll — no deployment ID")
        return

    terminal_states = {"SUCCESS", "FAILED", "ROLLBACK"}
    max_polls = 15
    for i in range(max_polls):
        r = client.get(f"/api/deployments/{deployment_id}")
        if r.status_code == 404:
            warn(f"Deployment {deployment_id[:8]} not found — may be batch")
            break
        if r.status_code != 200:
            warn(f"Poll failed: {r.status_code}")
            break

        body = r.json()
        status = body.get("status", "UNKNOWN")
        elapsed = body.get("elapsed_seconds", "?")
        print(f"  [{i+1:02d}/{max_polls}] Status: {status} | Elapsed: {elapsed}s")

        if status in terminal_states:
            if status == "SUCCESS":
                ok("Deployment completed successfully!")
            elif status == "ROLLBACK":
                warn("Deployment triggered automatic rollback")
            else:
                warn(f"Deployment ended with status: {status}")
            break

        time.sleep(3)
    else:
        warn("Timed out waiting for deployment to complete")


def step_6_fetch_logs_and_diff(client: DemoClient, deployment_id: str):
    banner("Step 6: Deployment Logs + Config Diff")
    if deployment_id == "unknown":
        warn("Skipping — no deployment ID")
        return

    r = client.get(f"/api/deployments/{deployment_id}/logs")
    if r.status_code == 200:
        body = r.json()
        logs = body.get("logs", [])
        ok(f"Fetched {len(logs)} log lines")
        for line in logs[:5]:
            print(f"     {line}")
        if len(logs) > 5:
            print(f"     ... ({len(logs) - 5} more lines)")
    else:
        warn(f"Log fetch returned {r.status_code}")

    r = client.get(f"/api/deployments/{deployment_id}/snapshot")
    if r.status_code == 200:
        body = r.json()
        diff = body.get("diff", "")
        snapshots = body.get("snapshots", [])
        ok(f"Fetched {len(snapshots)} snapshots (before/after pairs)")
        if diff:
            print("  Config diff preview (first 10 lines):")
            for line in diff.splitlines()[:10]:
                print(f"     {line}")
    else:
        warn(f"Snapshot fetch returned {r.status_code}")


def step_7_rollback(client: DemoClient, deployment_id: str):
    banner("Step 7: Manual Rollback")
    if deployment_id == "unknown":
        warn("Skipping rollback — no deployment ID")
        return

    r = client.post(f"/api/deployments/{deployment_id}/rollback")
    if r.status_code in (200, 201, 202):
        body = r.json()
        ok(f"Rollback triggered: {body.get('message', 'queued')}")
    elif r.status_code == 400:
        warn(f"Rollback rejected (may already be in terminal state): {r.json().get('detail')}")
    else:
        warn(f"Rollback returned {r.status_code}: {r.text[:200]}")


def step_8_audit_log(client: DemoClient):
    banner("Step 8: Audit Log Trail")
    r = client.get("/api/audit?limit=10")
    if r.status_code != 200:
        warn(f"Audit log returned {r.status_code}")
        return

    entries = r.json()
    ok(f"Last {len(entries)} audit events:")
    for entry in entries[:5]:
        ts = entry.get("timestamp", "?")[:19]
        action = entry.get("action", "?")
        resource = entry.get("resource_type", "?")
        user = entry.get("user_id", "system")
        print(f"     [{ts}] {action:12s} {resource:15s} by {user}")


def step_9_cleanup(client: DemoClient, device_ids: list[str]):
    banner("Step 9: Cleanup Demo Devices")
    for device_id in device_ids:
        r = client.delete(f"/api/devices/{device_id}")
        if r.status_code in (200, 204):
            ok(f"Deleted device {device_id[:8]}...")
        else:
            warn(f"Delete returned {r.status_code} for {device_id[:8]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="NetDeploy Demo Script")
    parser.add_argument("--api-url", default="http://localhost:8000", help="NetDeploy API base URL")
    parser.add_argument("--skip-cleanup", action="store_true", help="Leave demo devices in place")
    args = parser.parse_args()

    print(f"\n🚀 NetDeploy Demo — connecting to {args.api_url}")
    client = DemoClient(args.api_url)

    device_ids = []
    deployment_id = "unknown"

    try:
        step_0_health(client)
        device_ids = step_1_register_devices(client)
        step_2_validate_bad_config(client, device_ids)
        config_version = step_3_validate_good_config(client, device_ids)
        deployment_id = step_4_trigger_deployment(client, device_ids, config_version)
        step_5_poll_status(client, deployment_id)
        step_6_fetch_logs_and_diff(client, deployment_id)
        step_7_rollback(client, deployment_id)
        step_8_audit_log(client)

        banner("Demo Complete!")
        print("  ✅ All steps completed successfully.")
        print(f"\n  📊 Dashboard  : http://localhost:8501")
        print(f"  📖 API Docs   : {args.api_url}/docs")
        print(f"  📈 Grafana    : http://localhost:3000")
        print(f"  🔥 Prometheus : http://localhost:9090")

    finally:
        if not args.skip_cleanup and device_ids:
            step_9_cleanup(client, device_ids)


if __name__ == "__main__":
    main()
