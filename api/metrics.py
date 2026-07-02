"""
Prometheus metrics for NetDeploy.

Exposes a /metrics endpoint (text format) and provides shared Counter/Histogram
objects that the rest of the application imports.

Usage in routes:
    from api.metrics import DEPLOY_COUNTER, DEPLOY_DURATION
    DEPLOY_COUNTER.labels(strategy="atomic", status="success").inc()

The metrics endpoint is mounted on the FastAPI app in api/main.py:
    from api.metrics import metrics_router
    app.include_router(metrics_router)
"""

import time
from functools import wraps

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        REGISTRY,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:  # graceful degradation in test environments
    PROMETHEUS_AVAILABLE = False


# Always defined so it is importable regardless of prometheus_client presence
class _NoopMetric:
    """Drop-in stub for Prometheus metrics when prometheus_client is unavailable."""
    def labels(self, **kwargs):
        return self
    def inc(self, *a, **kw): pass
    def dec(self, *a, **kw): pass
    def set(self, *a, **kw): pass
    def observe(self, *a, **kw): pass
    def time(self):
        import contextlib
        return contextlib.nullcontext()


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

if PROMETHEUS_AVAILABLE:
    # ── Deployment metrics ──────────────────────────────────────────────────
    DEPLOY_COUNTER = Counter(
        "netdeploy_deployments_total",
        "Total number of deployment attempts",
        ["strategy", "status"],  # labels: strategy=atomic|rolling|canary, status=success|failed|rollback
    )

    DEPLOY_DURATION = Histogram(
        "netdeploy_deployment_duration_seconds",
        "Time taken to complete a deployment",
        ["strategy"],
        buckets=[1, 5, 15, 30, 60, 120, 300, 600],
    )

    ROLLBACK_COUNTER = Counter(
        "netdeploy_rollbacks_total",
        "Total number of rollback operations",
        ["reason"],  # labels: reason=verify_failed|manual|timeout
    )

    # ── Device metrics ──────────────────────────────────────────────────────
    DEVICE_COUNT = Gauge(
        "netdeploy_devices_total",
        "Total registered devices",
        ["device_type"],  # cisco_xr, junos, etc.
    )

    SSH_CONNECTION_ERRORS = Counter(
        "netdeploy_ssh_connection_errors_total",
        "SSH connection failures by device type",
        ["device_type"],
    )

    SSH_COMMAND_DURATION = Histogram(
        "netdeploy_ssh_command_duration_seconds",
        "Time to execute an SSH command",
        ["command_type"],  # config_push, show_command, save_config
        buckets=[0.1, 0.5, 1, 5, 10, 30, 60],
    )

    # ── API request metrics ─────────────────────────────────────────────────
    HTTP_REQUEST_COUNTER = Counter(
        "netdeploy_http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status_code"],
    )

    HTTP_REQUEST_DURATION = Histogram(
        "netdeploy_http_request_duration_seconds",
        "HTTP request latency",
        ["method", "path"],
        buckets=[0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
    )

    RATE_LIMIT_COUNTER = Counter(
        "netdeploy_rate_limit_exceeded_total",
        "Number of requests rejected by rate limiter",
        ["path"],
    )

    # ── Task queue metrics ──────────────────────────────────────────────────
    CELERY_TASK_COUNTER = Counter(
        "netdeploy_celery_tasks_total",
        "Celery task completions",
        ["task_name", "status"],  # status=success|failure|retry
    )

    CELERY_QUEUE_DEPTH = Gauge(
        "netdeploy_celery_queue_depth",
        "Approximate number of tasks in the Celery queue",
        ["queue_name"],
    )

else:
    DEPLOY_COUNTER = _NoopMetric()
    DEPLOY_DURATION = _NoopMetric()
    ROLLBACK_COUNTER = _NoopMetric()
    DEVICE_COUNT = _NoopMetric()
    SSH_CONNECTION_ERRORS = _NoopMetric()
    SSH_COMMAND_DURATION = _NoopMetric()
    HTTP_REQUEST_COUNTER = _NoopMetric()
    HTTP_REQUEST_DURATION = _NoopMetric()
    RATE_LIMIT_COUNTER = _NoopMetric()
    CELERY_TASK_COUNTER = _NoopMetric()
    CELERY_QUEUE_DEPTH = _NoopMetric()


# ---------------------------------------------------------------------------
# Metrics endpoint router
# ---------------------------------------------------------------------------

metrics_router = APIRouter(tags=["observability"])


@metrics_router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def prometheus_metrics():
    """
    Expose Prometheus metrics in text format.

    Scraped by Prometheus at the configured scrape interval (default: 15s).
    Do NOT expose this endpoint publicly — put it behind internal network
    or protect it with IP allowlisting / basic auth at the ingress level.
    """
    if not PROMETHEUS_AVAILABLE:
        return PlainTextResponse("# prometheus_client not installed\n", status_code=200)

    data = generate_latest(REGISTRY)
    return PlainTextResponse(
        content=data.decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )


# ---------------------------------------------------------------------------
# Decorator helpers
# ---------------------------------------------------------------------------

def track_deployment(strategy: str):
    """
    Decorator for deployment functions — records count and duration.

    Usage:
        @track_deployment("atomic")
        async def _deploy_atomic(self, ...):
            ...
    """
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            start = time.monotonic()
            status = "success"
            try:
                result = await fn(*args, **kwargs)
                # If the function returns a result dict, check for failures
                if isinstance(result, dict) and not result.get("success", True):
                    status = "failed"
                return result
            except Exception:
                status = "failed"
                raise
            finally:
                duration = time.monotonic() - start
                DEPLOY_COUNTER.labels(strategy=strategy, status=status).inc()
                DEPLOY_DURATION.labels(strategy=strategy).observe(duration)
        return wrapper
    return decorator


def track_ssh_command(command_type: str = "config_push"):
    """
    Decorator for SSHDevice methods — records command latency.

    Usage:
        @track_ssh_command("show_command")
        async def get_bgp_summary(self):
            ...
    """
    def decorator(fn):
        @wraps(fn)
        async def wrapper(self, *args, **kwargs):
            start = time.monotonic()
            try:
                return await fn(self, *args, **kwargs)
            except Exception:
                device_type = getattr(self, "device_type", "unknown")
                SSH_CONNECTION_ERRORS.labels(device_type=device_type).inc()
                raise
            finally:
                SSH_COMMAND_DURATION.labels(command_type=command_type).observe(
                    time.monotonic() - start
                )
        return wrapper
    return decorator
