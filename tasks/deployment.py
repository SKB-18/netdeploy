"""
Celery tasks for deployment, rollback, and sync operations.

Cowork provides: task signatures, retry config, docstrings.
Cursor implements: task bodies using DeploymentOrchestrator + SSHDevice.
"""

import asyncio
import logging
import os
import sys
from uuid import uuid4

from celery import shared_task, current_task

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_with_db(coro_factory):
    """Open a DB session, pass it to an async orchestrator coroutine, then close."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)

    from api.database import SessionLocal
    from core.orchestrator import DeploymentOrchestrator

    db = SessionLocal()
    try:
        orchestrator = DeploymentOrchestrator(db_session=db)
        return asyncio.run(coro_factory(orchestrator)), db
    except Exception:
        db.close()
        raise


def _finalize_batch_status(db, batch_id: str, result: dict):
    """Mark any remaining QUEUED rows in a batch after Celery finishes."""
    from datetime import datetime
    from uuid import UUID
    from api.models import Deployment

    status_map = {
        "SUCCESS": "SUCCESS",
        "FAILED": "FAILED",
        "ROLLBACK": "ROLLBACK",
        "PARTIAL": "FAILED",
    }
    target = status_map.get(result.get("status"), "FAILED")
    error = result.get("error") or "Deployment did not complete"

    try:
        batch_uuid = UUID(str(batch_id))
    except (ValueError, AttributeError):
        return

    stale = (
        db.query(Deployment)
        .filter(Deployment.batch_id == batch_uuid, Deployment.status == "QUEUED")
        .all()
    )
    for dep in stale:
        dep.status = target
        if not dep.error_message:
            dep.error_message = error
        if not dep.end_time:
            dep.end_time = datetime.utcnow()
    if stale:
        db.commit()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def validate_and_deploy_task(
    self,
    device_ids: list,
    config_version: str,
    strategy: str,
    batch_id: str = None,
    user_id: str = "system",
):
    """
    Celery task: Validate config for all devices, then deploy.
    """
    batch_id = batch_id or str(uuid4())
    logger.info(
        "validate_and_deploy_task: batch=%s devices=%s strategy=%s",
        batch_id, device_ids, strategy,
    )

    db = None
    try:
        result, db = _run_with_db(
            lambda orch: orch.deploy(
                device_ids=device_ids,
                config_version=config_version,
                strategy=strategy,
                batch_id=batch_id,
                user_id=user_id,
            )
        )
        _finalize_batch_status(db, batch_id, result)
        logger.info("Deployment batch %s result: %s", batch_id, result.get("status"))
        return result
    except Exception as exc:
        logger.exception("Deployment task failed: %s", exc)
        raise self.retry(exc=exc)
    finally:
        if db is not None:
            db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def deploy_to_device(
    self,
    device_id: str,
    config_version: str,
    batch_id: str = None,
    user_id: str = "system",
):
    """Celery task: Deploy config to a single device."""
    logger.info("deploy_to_device: device=%s version=%s", device_id, config_version)
    db = None
    try:
        result, db = _run_with_db(
            lambda orch: orch._deploy_to_device(
                device_id, config_version, user_id, batch_id=batch_id
            )
        )
        return result
    except Exception as exc:
        logger.exception("deploy_to_device failed for %s: %s", device_id, exc)
        raise self.retry(exc=exc)
    finally:
        if db is not None:
            db.close()


@celery_app.task(bind=True)
def rollback_device(
    self,
    device_id: str,
    deployment_id: str = None,
    backup_version: str = None,
    user_id: str = "system",
):
    """Celery task: Rollback a device to its previous configuration."""
    logger.info("rollback_device: device=%s deployment=%s", device_id, deployment_id)
    db = None
    try:
        result, db = _run_with_db(
            lambda orch: orch._rollback_device(device_id, user_id)
        )
        return {"success": result, "device_id": device_id}
    except Exception as exc:
        logger.exception("rollback_device failed for %s: %s", device_id, exc)
        raise self.retry(exc=exc)
    finally:
        if db is not None:
            db.close()


@celery_app.task
def sync_device_state(device_id: str):
    """Celery task: SSH to device, fetch running config, update Configuration.running_state in DB."""
    logger.info("sync_device_state: device=%s", device_id)
    return {"status": "not_implemented", "device_id": device_id}


@celery_app.task
def check_deployment_health(deployment_id: str):
    """Celery task: Post-deployment health check."""
    logger.info("check_deployment_health: deployment=%s", deployment_id)
    return {"status": "not_implemented", "deployment_id": deployment_id}
