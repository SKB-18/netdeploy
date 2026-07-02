"""
Celery tasks for deployment, rollback, and sync operations.

Cowork provides: task signatures, retry config, docstrings.
Cursor implements: task bodies using DeploymentOrchestrator + SSHDevice.
"""

import asyncio
import logging
from uuid import uuid4

from celery import shared_task, current_task

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


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

    Process:
    1. Open DB session
    2. Fetch devices + desired configs from DB
    3. Run ConfigValidator for each device
    4. If all valid: call DeploymentOrchestrator.deploy()
    5. If invalid: update Deployment status=FAILED, log errors
    6. On exception: retry with exponential backoff (max 3)

    [CURSOR IMPLEMENTS]
    """
    batch_id = batch_id or str(uuid4())
    logger.info(
        "validate_and_deploy_task: batch=%s devices=%s strategy=%s",
        batch_id, device_ids, strategy,
    )

    try:
        from core.orchestrator import DeploymentOrchestrator
        orchestrator = DeploymentOrchestrator()
        result = asyncio.run(
            orchestrator.deploy(
                device_ids=device_ids,
                config_version=config_version,
                strategy=strategy,
                batch_id=batch_id,
                user_id=user_id,
            )
        )
        logger.info("Deployment batch %s result: %s", batch_id, result.get("status"))
        return result
    except Exception as exc:
        logger.exception("Deployment task failed: %s", exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def deploy_to_device(
    self,
    device_id: str,
    config_version: str,
    batch_id: str = None,
    user_id: str = "system",
):
    """
    Celery task: Deploy config to a single device.

    Steps:
    1. SSH connect
    2. Backup running config → ConfigSnapshot
    3. Apply new config commands
    4. Verify state
    5. Update Deployment record in DB
    6. Write AuditLog entry
    7. On failure: restore backup, update status=ROLLBACK

    Retry: exponential backoff, max 3 times.
    Timeout: 30 minutes.

    [CURSOR IMPLEMENTS]
    """
    logger.info("deploy_to_device: device=%s version=%s", device_id, config_version)
    try:
        from core.orchestrator import DeploymentOrchestrator
        orchestrator = DeploymentOrchestrator()
        result = asyncio.run(
            orchestrator._deploy_to_device(device_id, config_version, user_id)
        )
        return result
    except Exception as exc:
        logger.exception("deploy_to_device failed for %s: %s", device_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True)
def rollback_device(
    self,
    device_id: str,
    deployment_id: str = None,
    backup_version: str = None,
    user_id: str = "system",
):
    """
    Celery task: Rollback a device to its previous configuration.

    Steps:
    1. Fetch ConfigSnapshot.config_before from DB
    2. SSH to device
    3. Apply backup config
    4. Verify
    5. Update Deployment.status = ROLLBACK
    6. Write AuditLog

    [CURSOR IMPLEMENTS]
    """
    logger.info("rollback_device: device=%s deployment=%s", device_id, deployment_id)
    try:
        from core.orchestrator import DeploymentOrchestrator
        orchestrator = DeploymentOrchestrator()
        result = asyncio.run(orchestrator._rollback_device(device_id, user_id))
        return {"success": result, "device_id": device_id}
    except Exception as exc:
        logger.exception("rollback_device failed for %s: %s", device_id, exc)
        raise self.retry(exc=exc)


@celery_app.task
def sync_device_state(device_id: str):
    """
    Celery task: SSH to device, fetch running config, update Configuration.running_state in DB.

    Used to detect config drift (desired != running).
    
    [CURSOR IMPLEMENTS]
    """
    logger.info("sync_device_state: device=%s", device_id)
    # Cursor: SSH → get_running_config → update DB
    return {"status": "not_implemented", "device_id": device_id}


@celery_app.task
def check_deployment_health(deployment_id: str):
    """
    Celery task: Post-deployment health check.

    - Fetch deployment + device
    - SSH health check (BGP neighbors, OSPF adjacencies)
    - Update Deployment.status if unhealthy

    [CURSOR IMPLEMENTS]
    """
    logger.info("check_deployment_health: deployment=%s", deployment_id)
    return {"status": "not_implemented", "deployment_id": deployment_id}
