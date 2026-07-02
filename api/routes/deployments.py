"""Deployment status, rollback, and listing endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db, get_current_user
from api.models import Deployment
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
