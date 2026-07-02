"""NetDeploy FastAPI application entry point."""

import time
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import configs, devices, deployments, audit, auth
from api.routes.audit import audit_alias_router
from api.metrics import metrics_router, HTTP_REQUEST_COUNTER, HTTP_REQUEST_DURATION
from api.middleware.security_headers import SecurityHeadersMiddleware
from api.middleware.rate_limiter import RateLimitMiddleware
from core.config import settings

app = FastAPI(
    title="NetDeploy",
    description="Automated Network Provisioning Platform — GitOps for BGP/OSPF",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Middleware (order matters — added last = runs first)
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests and record Prometheus HTTP metrics."""
    import logging
    logger = logging.getLogger("netdeploy")
    start = time.monotonic()
    response = await call_next(request)
    duration = time.monotonic() - start
    logger.info(
        "%s %s → %d (%.3fs)",
        request.method,
        request.url.path,
        response.status_code,
        duration,
    )
    try:
        HTTP_REQUEST_COUNTER.labels(
            method=request.method,
            path=request.url.path,
            status_code=str(response.status_code),
        ).inc()
        HTTP_REQUEST_DURATION.labels(
            method=request.method,
            path=request.url.path,
        ).observe(duration)
    except Exception:
        pass
    return response


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    import logging
    logging.getLogger("netdeploy").exception("Unhandled exception: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth.router)
app.include_router(devices.router)
app.include_router(configs.router)
app.include_router(deployments.router)
app.include_router(audit.router)
app.include_router(audit_alias_router)
app.include_router(metrics_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"])
async def health_check():
    """Service liveness check."""
    import redis as redis_lib
    from sqlalchemy import text
    from api.database import engine

    db_status = "ok"
    redis_status = "ok"

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    try:
        r = redis_lib.from_url(settings.REDIS_URL)
        r.ping()
    except Exception:
        redis_status = "error"

    return {
        "status": "healthy" if db_status == "ok" and redis_status == "ok" else "degraded",
        "version": "1.0.0",
        "database": db_status,
        "redis": redis_status,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "NetDeploy API — visit /docs"}
