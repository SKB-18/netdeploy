"""Deployment status, rollback, logs, snapshot, and listing endpoints."""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db, get_current_user
from api.models import ConfigSnapshot, Deployment
from api.schemas import DeploymentResponse, RollbackRequest

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


@router.get("/", response_model=List[DeploymentResponse])
async def list_deployments(
    skip: int = 0,
    limit: int = 20,
    status: str = None,
    db: Session = Depends(get_db),
):
    """List recent deployments, optionally filtered by status."""
    query = db.query(Deployment)
    if status:
        query = query.filter(Deployment.status == status.upper())
    return query.order_by(Deployment.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{deployment_id}", response_model=DeploymentResponse)
async def get_deployment(deployment_id: UUID, db: Session = Depends(get_db)):
    """Get deployment details + logs by ID."""
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return deployment


@router.get("/batch/{batch_id}")
async def get_batch(batch_id: UUID, db: Session = Depends(get_db)):
    """Get all deployments belonging to a batch."""
    deployments = db.query(Deployment).filter(Deployment.batch_id == batch_id).all()
    if not deployments:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {
        "batch_id": str(batch_id),
        "total": len(deployments),
        "deployments": [
            {
                "id": str(d.id),
                "device_id": str(d.device_id),
                "status": d.status,
                "start_time": d.start_time.isoformat() if d.start_time else None,
                "end_time": d.end_time.isoformat() if d.end_time else None,
                "error_message": d.error_message,
            }
            for d in deployments
        ],
    }


@router.post("/{deployment_id}/rollback")
async def rollback_deployment(
    deployment_id: UUID,
    request_body: RollbackRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Trigger rollback for a deployment.
    
    [CURSOR IMPLEMENTS]:
    1. Fetch deployment
    2. Enqueue rollback Celery task
    3. Return rollback status
    """
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if deployment.status not in ("SUCCESS", "FAILED"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot rollback deployment in status: {deployment.status}",
        )

    from tasks.deployment import rollback_device
    task = rollback_device.delay(
        device_id=str(deployment.device_id),
        deployment_id=str(deployment_id),
        user_id=user["user_id"],
    )

    return {
        "status": "ROLLBACK_QUEUED",
        "deployment_id": str(deployment_id),
        "task_id": task.id,
    }


@router.get("/{deployment_id}/logs", response_model=Dict[str, Any])
async def get_deployment_logs(
    deployment_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Stream accumulated logs for a deployment.

    Returns all log lines written during the deployment lifecycle
    (connect, apply, verify, rollback).  Logs are stored in the
    Deployment.logs TEXT column and appended by _update_deployment_status().

    Response:
        {
          "deployment_id": "...",
          "status": "...",
          "logs": ["line1", "line2", ...],
          "log_count": int,
          "start_time": "ISO8601",
          "end_time":   "ISO8601 | null"
        }

    [CURSOR EXTENDS with SSE streaming when Deployment.status == IN_PROGRESS]
    """
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    raw_logs: str = deployment.logs or ""
    log_lines = [line for line in raw_logs.splitlines() if line.strip()]

    return {
        "deployment_id": str(deployment_id),
        "status": deployment.status,
        "logs": log_lines,
        "log_count": len(log_lines),
        "start_time": deployment.start_time.isoformat() if deployment.start_time else None,
        "end_time": deployment.end_time.isoformat() if deployment.end_time else None,
    }


@router.get("/{deployment_id}/snapshot", response_model=Dict[str, Any])
async def get_deployment_snapshot(
    deployment_id: UUID,
    device_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
):
    """
    Fetch before/after ConfigSnapshot records for a deployment.

    If device_id is provided, returns snapshots for that specific device only.
    Otherwise returns all snapshots for the deployment (batch view).

    Also returns a unified diff between BEFORE and AFTER snapshots when
    both are available (delegates to SnapshotManager.diff_snapshots).

    Response:
        {
          "deployment_id": "...",
          "snapshots": [
            {
              "id": "...",
              "device_id": "...",
              "is_before": true,
              "config_hash": "sha256:...",
              "created_at": "ISO8601"
            },
            ...
          ],
          "diff": "unified diff string | null"
        }

    [CURSOR EXTENDS with full diff using SnapshotManager.diff_snapshots()]
    """
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    query = db.query(ConfigSnapshot).filter(ConfigSnapshot.deployment_id == deployment_id)
    if device_id:
        query = query.filter(ConfigSnapshot.device_id == device_id)
    snapshots = query.order_by(ConfigSnapshot.created_at).all()

    diff_text: Optional[str] = None
    if device_id and snapshots:
        # Attempt diff if we have both before + after
        before = next((s for s in snapshots if s.is_before), None)
        after = next((s for s in snapshots if not s.is_before), None)
        if before and after:
            try:
                from core.snapshot_manager import SnapshotManager
                sm = SnapshotManager(db, ssh_device=None)
                diff_text = sm.diff_snapshots(deployment_id, device_id)
            except Exception:
                diff_text = None  # Non-fatal — snapshot diff is best-effort

    return {
        "deployment_id": str(deployment_id),
        "snapshots": [
            {
                "id": str(s.id),
                "device_id": str(s.device_id),
                "is_before": s.is_before,
                "config_hash": s.config_hash,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in snapshots
        ],
        "diff": diff_text,
    }
