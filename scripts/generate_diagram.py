#!/usr/bin/env python3
"""
Generate NetDeploy architecture diagrams using the `diagrams` library.

Outputs:
  docs/architecture_overview.png    — full system architecture
  docs/deployment_flow.png          — deployment state machine
  docs/network_topology.png         — simulated router topology

Install:
    pip install diagrams
    # also requires graphviz: https://graphviz.org/download/

Usage:
    python scripts/generate_diagram.py
    python scripts/generate_diagram.py --output-dir docs/
"""

import argparse
import os
import sys

try:
    from diagrams import Diagram, Cluster, Edge
    from diagrams.onprem.database import PostgreSQL
    from diagrams.onprem.queue import Redis
    from diagrams.onprem.monitoring import Prometheus, Grafana
    from diagrams.onprem.vcs import Git
    from diagrams.onprem.client import Users
    from diagrams.onprem.network import Nginx
    from diagrams.programming.framework import FastAPI
    from diagrams.programming.language import Python
    from diagrams.generic.network import Router, Firewall
    from diagrams.generic.storage import Storage
    from diagrams.generic.compute import Rack
    DIAGRAMS_AVAILABLE = True
except ImportError:
    DIAGRAMS_AVAILABLE = False


def generate_architecture_overview(output_dir: str):
    """Full NetDeploy system architecture."""
    filename = os.path.join(output_dir, "architecture_overview")

    with Diagram(
        "NetDeploy — System Architecture",
        filename=filename,
        show=False,
        direction="TB",
    ):
        users = Users("Network Engineers\n+ CI/CD Pipelines")

        with Cluster("Ingress / Load Balancer"):
            ingress = Nginx("nginx-ingress\n(TLS + Rate Limit)")

        with Cluster("NetDeploy Application Tier"):
            with Cluster("FastAPI (3 replicas)"):
                api = FastAPI("API Server\n:8000")

            with Cluster("Streamlit Dashboard"):
                dashboard = Python("Dashboard\n:8501")

            with Cluster("Celery Workers (2+ replicas)"):
                workers = Python("Deployment Workers\n+ Validation")

        with Cluster("Data Tier"):
            db = PostgreSQL("PostgreSQL\n(devices, configs,\ndeployments, audit)")
            cache = Redis("Redis\n(broker + rate limit)")

        with Cluster("Observability"):
            prom = Prometheus("Prometheus\n:9090")
            graf = Grafana("Grafana\n:3000")

        with Cluster("Version Control"):
            git = Git("Git Repository\n(config source of truth)")

        with Cluster("Network Infrastructure"):
            r1 = Router("spine-01\n(Cisco XR)")
            r2 = Router("spine-02\n(Cisco XR)")
            r3 = Router("leaf-01\n(JunOS)")
            r4 = Router("leaf-02\n(JunOS)")
            r5 = Router("border-01\n(Arista EOS)")

        # Flows
        users >> ingress >> [api, dashboard]
        api >> Edge(label="queue tasks") >> workers
        api >> Edge(label="read/write") >> db
        api >> Edge(label="rate limit\n+ cache") >> cache
        workers >> Edge(label="read/write") >> db
        workers >> Edge(label="SSH\n(Netmiko)") >> [r1, r2, r3, r4, r5]
        workers >> Edge(label="commit\nconfigs") >> git
        api >> Edge(label="scrape\n/metrics") >> prom
        workers >> prom
        prom >> graf
        dashboard >> Edge(label="REST API") >> api

    print(f"  ✅ {filename}.png")


def generate_deployment_flow(output_dir: str):
    """Deployment state machine and orchestrator flow."""
    filename = os.path.join(output_dir, "deployment_flow")

    with Diagram(
        "NetDeploy — Deployment Flow",
        filename=filename,
        show=False,
        direction="LR",
    ):
        with Cluster("Trigger"):
            api_req = FastAPI("POST /api/deployments")

        with Cluster("Validation"):
            validator = Python("ConfigValidator\n• BGP rules\n• OSPF rules\n• Conflicts")

        with Cluster("Orchestration"):
            with Cluster("Strategy Selection"):
                canary = Python("Canary\n1 device → wait → rest")
                rolling = Python("Rolling\nSequential + health checks")
                atomic = Python("Atomic\nAll parallel or rollback all")

            snapshot_before = Storage("Snapshot BEFORE\n(SHA-256 hash)")
            cmd_builder = Python("CommandBuilder\n(vendor CLI gen)")
            ssh = Python("SSHDevice\n(Netmiko)")
            snapshot_after = Storage("Snapshot AFTER")
            verifier = Python("StateVerifier\n• show bgp summary\n• show ospf neighbor")

        with Cluster("Outcomes"):
            success = Python("✅ SUCCESS\nAudit log entry")
            rollback = Python("↩️ ROLLBACK\nRestore BEFORE snapshot")
            failed = Python("❌ FAILED\nNotify + log error")

        with Cluster("Target Devices"):
            routers = Router("Network Devices\n(Cisco / Juniper / Arista)")

        api_req >> validator
        validator >> Edge(label="valid") >> [canary, rolling, atomic]
        canary >> snapshot_before
        rolling >> snapshot_before
        atomic >> snapshot_before
        snapshot_before >> cmd_builder >> ssh >> routers
        routers >> Edge(label="response") >> snapshot_after
        snapshot_after >> verifier
        verifier >> Edge(label="pass") >> success
        verifier >> Edge(label="fail") >> rollback
        ssh >> Edge(label="SSH error") >> failed

    print(f"  ✅ {filename}.png")


def generate_text_diagrams(output_dir: str):
    """Fallback ASCII art diagrams when graphviz is not installed."""
    os.makedirs(output_dir, exist_ok=True)

    arch = """
NetDeploy — Architecture Overview
==================================

  [Network Engineers / CI-CD]
           │
           ▼
    [nginx-ingress]  ← TLS termination, rate limiting
           │
     ┌─────┴──────┐
     ▼             ▼
 [FastAPI API]  [Streamlit Dashboard]
   :8000           :8501
     │
     ├──[queue tasks]──► [Celery Workers]
     │                        │
     │                        ├──[SSH/Netmiko]──► spine-01 (Cisco XR)
     │                        ├──[SSH/Netmiko]──► spine-02 (Cisco XR)
     │                        ├──[SSH/Netmiko]──► leaf-01  (JunOS)
     │                        ├──[SSH/Netmiko]──► leaf-02  (JunOS)
     │                        └──[SSH/Netmiko]──► border-01 (Arista EOS)
     │
     ├──[read/write]──► [PostgreSQL]
     │                   devices, configs
     │                   deployments, audit
     │
     ├──[cache/broker]─► [Redis]
     │
     └──[metrics]──────► [Prometheus] ──► [Grafana]


NetDeploy — Deployment State Machine
======================================

  QUEUED
    │
    ▼
  IN_PROGRESS ──────────────────┐
    │                           │ SSH error
    │ [Validate config]         │
    │ [Snapshot BEFORE]         │
    │ [Build commands]          ▼
    │ [Push via SSH]         FAILED
    │ [Snapshot AFTER]
    │ [Verify state]
    │
    ├──[verify pass]──► SUCCESS
    │
    └──[verify fail]──► ROLLBACK
                         │
                         ▼
                    [Restore BEFORE snapshot]
                    [Push rollback commands]
                    [Verify rollback state]
"""

    with open(os.path.join(output_dir, "architecture_overview.txt"), "w") as f:
        f.write(arch)
    print(f"  ✅ {output_dir}/architecture_overview.txt (text fallback)")


def main():
    parser = argparse.ArgumentParser(description="Generate NetDeploy architecture diagrams")
    parser.add_argument("--output-dir", default="docs", help="Output directory")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"\n📊 Generating diagrams → {args.output_dir}/")

    if not DIAGRAMS_AVAILABLE:
        print("  ⚠️  'diagrams' package not installed. Generating text fallback.")
        print("  Install with: pip install diagrams")
        print("  Also requires graphviz: https://graphviz.org/download/\n")
        generate_text_diagrams(args.output_dir)
        return

    try:
        generate_architecture_overview(args.output_dir)
        generate_deployment_flow(args.output_dir)
        print(f"\n  All diagrams saved to {args.output_dir}/")
    except Exception as e:
        print(f"  ❌ Diagram generation failed: {e}")
        print("  Falling back to text diagrams...")
        generate_text_diagrams(args.output_dir)


if __name__ == "__main__":
    main()
