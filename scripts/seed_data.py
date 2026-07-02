#!/usr/bin/env python3
"""
NetDeploy seed script — populate a fresh database with realistic demo data.

Creates:
  - 6 datacenter routers (2x cisco_xr, 2x junos, 1x arista_eos, 1x nokia_sros)
  - 4 Configuration versions per device
  - 8 Deployment records (mix of SUCCESS, FAILED, ROLLBACK)
  - 20+ Audit log entries

Usage:
    python scripts/seed_data.py
    python scripts/seed_data.py --wipe    # wipe existing data first
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


SEED_DEVICES = [
    {"hostname": "spine-01", "management_ip": "10.0.1.1", "device_type": "cisco_xr",
     "bgp_asn": 65001, "ospf_area": "0.0.0.0", "os_version": "7.9.1", "ssh_port": 22},
    {"hostname": "spine-02", "management_ip": "10.0.1.2", "device_type": "cisco_xr",
     "bgp_asn": 65001, "ospf_area": "0.0.0.0", "os_version": "7.9.1", "ssh_port": 22},
    {"hostname": "leaf-01",  "management_ip": "10.0.2.1", "device_type": "junos",
     "bgp_asn": 65002, "ospf_area": "0.0.0.1", "os_version": "22.4R1", "ssh_port": 22},
    {"hostname": "leaf-02",  "management_ip": "10.0.2.2", "device_type": "junos",
     "bgp_asn": 65002, "ospf_area": "0.0.0.1", "os_version": "22.4R1", "ssh_port": 22},
    {"hostname": "border-01","management_ip": "10.0.0.1", "device_type": "arista_eos",
     "bgp_asn": 65000, "ospf_area": "0.0.0.0", "os_version": "4.30.1F", "ssh_port": 22},
    {"hostname": "border-02","management_ip": "10.0.0.2", "device_type": "nokia_sros",
     "bgp_asn": 65000, "ospf_area": "0.0.0.0", "os_version": "23.10.R1", "ssh_port": 830},
]

DEPLOY_SCENARIOS = [
    {"strategy": "atomic",  "status": "SUCCESS",  "days_ago": 14},
    {"strategy": "rolling", "status": "SUCCESS",  "days_ago": 10},
    {"strategy": "canary",  "status": "SUCCESS",  "days_ago": 7},
    {"strategy": "atomic",  "status": "FAILED",   "days_ago": 5,
     "error_message": "SSH connection timeout to leaf-01 after 30s"},
    {"strategy": "rolling", "status": "ROLLBACK", "days_ago": 3,
     "error_message": "BGP session did not re-establish within 300s after push"},
    {"strategy": "canary",  "status": "SUCCESS",  "days_ago": 2},
    {"strategy": "atomic",  "status": "IN_PROGRESS", "days_ago": 0},
    {"strategy": "rolling", "status": "QUEUED",   "days_ago": 0},
]

AUDIT_ACTIONS = ["CREATE", "DEPLOY", "ROLLBACK", "SYNC", "VALIDATE", "DELETE"]
AUDIT_USERS = ["admin", "ci-pipeline", "alice", "bob", "netops-bot"]


def _now_minus(days: int = 0, hours: int = 0, minutes: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days, hours=hours, minutes=minutes)


def seed(wipe: bool = False):
    from api.database import SessionLocal, engine
    from api import models
    from api.models import Base

    if wipe:
        print("⚠️  Dropping and recreating all tables...")
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        print("✅ Tables recreated")

    db = SessionLocal()

    try:
        # ── Devices ──────────────────────────────────────────────────────────
        print("\n🖧  Seeding devices...")
        device_ids = []
        for d in SEED_DEVICES:
            existing = db.query(models.Device).filter_by(hostname=d["hostname"]).first()
            if existing:
                print(f"   skip {d['hostname']} (already exists)")
                device_ids.append(existing.id)
                continue

            device = models.Device(
                id=uuid4(),
                hostname=d["hostname"],
                management_ip=d["management_ip"],
                device_type=d["device_type"],
                bgp_asn=d.get("bgp_asn"),
                ospf_area=d.get("ospf_area"),
                os_version=d.get("os_version"),
                ssh_port=d.get("ssh_port", 22),
                created_at=_now_minus(days=30),
            )
            db.add(device)
            device_ids.append(device.id)
            print(f"   ✅ {d['hostname']} ({d['device_type']})")

        db.commit()

        # ── Configurations ────────────────────────────────────────────────────
        print("\n📄 Seeding configurations...")
        config_ids = []
        for i, device_id in enumerate(device_ids):
            for ver in range(1, 5):  # 4 versions per device
                cfg = models.Configuration(
                    id=uuid4(),
                    device_id=device_id,
                    version=f"v{ver}.{i}",
                    status="SYNCED" if ver == 4 else "SUPERSEDED",
                    created_by="seed-script",
                    deployed_at=_now_minus(days=30 - (ver * 5)),
                    config_data={
                        "bgp": {"asn": 65001 + (i % 3), "neighbors": []},
                        "ospf": {"areas": [{"area_id": "0.0.0.0"}]},
                    },
                )
                db.add(cfg)
                config_ids.append(cfg.id)

        db.commit()
        print(f"   ✅ {len(config_ids)} configuration versions created")

        # ── Deployments ───────────────────────────────────────────────────────
        print("\n🚀 Seeding deployments...")
        deployment_ids = []
        for scenario in DEPLOY_SCENARIOS:
            start_time = _now_minus(days=scenario["days_ago"], hours=2)
            end_time = start_time + timedelta(minutes=3, seconds=17) \
                if scenario["status"] in ("SUCCESS", "FAILED", "ROLLBACK") else None

            dep = models.Deployment(
                id=uuid4(),
                device_id=device_ids[0] if device_ids else uuid4(),
                configuration_id=config_ids[-1] if config_ids else None,
                status=scenario["status"],
                strategy=scenario["strategy"],
                start_time=start_time,
                end_time=end_time,
                error_message=scenario.get("error_message"),
                logs=f"[{start_time.isoformat()}] Deployment started with {scenario['strategy']} strategy\n"
                     f"[{start_time.isoformat()}] Acquiring config lock...\n"
                     f"[{start_time.isoformat()}] Snapshot BEFORE captured\n"
                     + (f"[{end_time.isoformat() if end_time else '?'}] Deployment {scenario['status']}\n"
                        if end_time else ""),
            )
            db.add(dep)
            deployment_ids.append(dep.id)
            status_emoji = {"SUCCESS": "✅", "FAILED": "❌", "ROLLBACK": "↩️",
                            "IN_PROGRESS": "🔄", "QUEUED": "⏳"}.get(scenario["status"], "?")
            print(f"   {status_emoji} {scenario['strategy']:8s} → {scenario['status']}")

        db.commit()

        # ── Audit Log ─────────────────────────────────────────────────────────
        print("\n📋 Seeding audit log...")
        import random
        random.seed(42)  # deterministic for demo

        for i in range(25):
            action = random.choice(AUDIT_ACTIONS)
            resource_type = random.choice(["Device", "Configuration", "Deployment"])
            resource_id = random.choice(
                device_ids + config_ids[:5] + deployment_ids[:3]
            ) if device_ids else uuid4()

            audit = models.AuditLog(
                id=uuid4(),
                user_id=random.choice(AUDIT_USERS),
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id),
                details={
                    "ip": f"10.{random.randint(0,10)}.{random.randint(0,255)}.{random.randint(1,254)}",
                    "user_agent": "NetDeploy-Dashboard/1.0",
                },
                ip_address=f"10.0.{random.randint(0,10)}.{random.randint(1,254)}",
                timestamp=_now_minus(
                    days=random.randint(0, 14),
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59),
                ),
            )
            db.add(audit)

        db.commit()
        print(f"   ✅ 25 audit log entries created")

        # ── Summary ──────────────────────────────────────────────────────────
        print(f"""
{'='*50}
  NetDeploy Seed Data Summary
{'='*50}
  Devices        : {len(device_ids)}
  Configurations : {len(config_ids)}
  Deployments    : {len(deployment_ids)}
  Audit entries  : 25
{'='*50}

  Dashboard : http://localhost:8501
  API Docs  : http://localhost:8000/docs
""")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Seed failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed NetDeploy demo data")
    parser.add_argument("--wipe", action="store_true",
                        help="Drop all tables before seeding (DESTRUCTIVE)")
    args = parser.parse_args()

    if args.wipe:
        confirm = input("⚠️  This will DELETE all existing data. Type 'yes' to confirm: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    seed(wipe=args.wipe)
