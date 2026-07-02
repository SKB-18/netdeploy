"""Configuration validate, deploy, diff, and history endpoints."""

from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.dependencies import get_db, get_current_user, get_client_ip
from api.models import Configuration, Device, AuditLog
from api.schemas import (
    ConfigRequest,
    ConfigResponse,
    ConfigDiffResponse,
    DeploymentRequest,
    DeploymentBatchResponse,
    ValidationResponse,
)
from core.validator import ConfigValidator

router = APIRouter(prefix="/api/configs", tags=["configurations"])


def _write_audit(db: Session, user_id: str, action: str, resource_id, details: dict, ip: str = None):
    """Helper: append an AuditLog row."""
    from uuid import UUID as PyUUID
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type="Configuration",
        resource_id=resource_id if isinstance(resource_id, PyUUID) else uuid4(),
        details=details,
        ip_address=ip,
    )
    db.add(entry)
    db.commit()


@router.post("/validate", response_model=ValidationResponse)
async def validate_config(
    request_body: ConfigRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Validate a network configuration before deployment.

    - Runs schema validation, BGP/OSPF rule checks, policy conflict detection.
    - Writes an audit log entry in the background.
    - Does NOT persist the config or trigger any deployment.

    Response:
        { "valid": bool, "errors": [...], "warnings": [...] }
    """
    device = db.query(Device).filter(Device.id == request_body.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    validator = ConfigValidator()
    result = validator.validate(request_body.desired_state, device_type=device.device_type)

    # Audit: record validation attempt in background so it doesn't slow response
    background_tasks.add_task(
        _write_audit,
        db=db,
        user_id=user["user_id"],
        action="VALIDATE",
        resource_id=request_body.device_id,
        details={
            "valid": result.valid,
            "error_count": len(result.errors),
            "warning_count": len(result.warnings),
            "description": request_body.description,
        },
        ip=get_client_ip(request),
    )

    return result


@router.post("/validate-batch", response_model=List[Dict[str, Any]])
async def validate_config_batch(
    items: List[ConfigRequest],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Validate configurations for multiple devices in one call.

    Useful for pre-deployment CI checks across an entire device group.

    Request body: list of ConfigRequest objects (same schema as /validate).

    Response: list of per-device results:
        [{ "device_id": "...", "valid": bool, "errors": [...], "warnings": [...] }, ...]

    [CURSOR IMPLEMENTS async fan-out using validate_batch_task]
    """
    results = []
    validator = ConfigValidator()

    for item in items:
        device = db.query(Device).filter(Device.id == item.device_id).first()
        if not device:
            results.append({
                "device_id": str(item.device_id),
                "valid": False,
                "errors": [f"Device {item.device_id} not found"],
                "warnings": [],
            })
            continue

        result = validator.validate(item.desired_state, device_type=device.device_type)
        results.append({
            "device_id": str(item.device_id),
            "hostname": device.hostname,
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
        })

    return results


@router.post("/validate-async", response_model=Dict[str, Any])
async def validate_config_async(
    request_body: ConfigRequest,
    run_preflight: bool = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Enqueue a validation task and return immediately with a task_id.

    Poll GET /api/configs/validate-status/{task_id} for results.

    Use this when run_preflight=True (ping checks add latency) or when
    validating very large configs.

    [CURSOR IMPLEMENTS polling endpoint + Celery task wiring]
    """
    device = db.query(Device).filter(Device.id == request_body.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    from tasks.validation import validate_config_task
    task = validate_config_task.delay(
        device_id=str(request_body.device_id),
        desired_state=request_body.desired_state,
        device_type=device.device_type,
        run_preflight=run_preflight,
        user_id=user["user_id"],
    )
    return {"task_id": task.id, "status": "PENDING", "device_id": str(request_body.device_id)}


@router.get("/validate-status/{task_id}", response_model=Dict[str, Any])
async def validate_status(task_id: str):
    """
    Poll result of an async validation task.

    Returns task state (PENDING / SUCCESS / FAILURE) and result when done.

    [CURSOR IMPLEMENTS using Celery AsyncResult]
    """
    from celery.result import AsyncResult
    from tasks.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)
    if result.state == "PENDING":
        return {"task_id": task_id, "status": "PENDING"}
    elif result.state == "SUCCESS":
        return {"task_id": task_id, "status": "SUCCESS", "result": result.result}
    elif result.state == "FAILURE":
        return {"task_id": task_id, "status": "FAILURE", "error": str(result.result)}
    return {"task_id": task_id, "status": result.state}


@router.post("/deploy", response_model=dict)
async def deploy_config(
    request_body: DeploymentRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Trigger configuration deployment.

    Strategies: canary, rolling, atomic.
    
    [CURSOR IMPLEMENTS]:
    1. Validate all device IDs exist
    2. Create Deployment records (status=QUEUED)
    3. Enqueue Celery tasks
    4. Return batch_id + deployment IDs
    """
    from tasks.deployment import validate_and_deploy_task
    from datetime import datetime

    # Verify all devices exist
    for device_id in request_body.device_ids:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

    batch_id = uuid4()

    # Enqueue task (Cursor will wire up full logic)
    task = validate_and_deploy_task.delay(
        device_ids=[str(d) for d in request_body.device_ids],
        config_version=request_body.config_version,
        strategy=request_body.strategy,
        batch_id=str(batch_id),
        user_id=user["user_id"],
    )

    return {
        "batch_id": str(batch_id),
        "task_id": task.id,
        "status": "QUEUED",
        "strategy": request_body.strategy,
        "device_count": len(request_body.device_ids),
    }


@router.get("/diff", response_model=ConfigDiffResponse)
async def get_config_diff(
    device_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Get diff between desired and running configuration.
    
    [CURSOR IMPLEMENTS]:
    1. Fetch desired config from DB
    2. SSH to device, get running config
    3. Compute unified diff
    4. Return diff
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    config = (
        db.query(Configuration)
        .filter(Configuration.device_id == device_id)
        .order_by(Configuration.created_at.desc())
        .first()
    )

    return ConfigDiffResponse(
        device_id=device_id,
        desired=config.desired_state if config else None,
        running=None,  # Cursor: SSH to device
        diff=None,
    )


@router.get("/history")
async def config_history(
    device_id: UUID,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """
    Get configuration version history for a device.
    
    [CURSOR IMPLEMENTS]: Pull from Git log + DB Configuration records.
    """
    configs = (
        db.query(Configuration)
        .filter(Configuration.device_id == device_id)
        .order_by(Configuration.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(c.id),
            "version": c.version,
            "status": c.status,
            "deployed_at": c.deployed_at.isoformat() if c.deployed_at else None,
            "created_by": c.created_by,
        }
        for c in configs
    ]


@router.get("/", response_model=List[Dict[str, Any]])
async def list_configs(
    device_id: Optional[UUID] = None,
    limit: int = 50,
    skip: int = 0,
    db: Session = Depends(get_db),
):
    """List stored configurations, optionally filtered by device_id."""
    query = db.query(Configuration)
    if device_id:
        query = query.filter(Configuration.device_id == device_id)
    configs = query.order_by(Configuration.created_at.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": str(c.id),
            "device_id": str(c.device_id),
            "version": c.version,
            "status": c.status,
            "created_by": c.created_by,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in configs
    ]


@router.post("/", response_model=ConfigResponse, status_code=201)
async def create_config(
    request_body: ConfigRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Store desired configuration for a device.
    
    [CURSOR IMPLEMENTS]: Commit to Git, store in DB, return config record.
    """
    device = db.query(Device).filter(Device.id == request_body.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    config = Configuration(
        device_id=request_body.device_id,
        version="pending",  # Cursor: replace with Git commit hash
        desired_state=request_body.desired_state,
        status="PENDING",
        created_by=request_body.created_by or user["user_id"],
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config
