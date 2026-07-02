"""Audit log search and retrieval endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.dependencies import get_db
from api.models import AuditLog
from api.schemas import AuditLogResponse

router = APIRouter(prefix="/api/audit-log", tags=["audit"])

# Short-path alias: /api/audit maps to the same handlers
audit_alias_router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/", response_model=List[AuditLogResponse])
async def list_audit_log(
    user_id: str = Query(None),
    action: str = Query(None),
    resource_type: str = Query(None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Search audit log with optional filters.
    
    Filters: user_id, action, resource_type.
    """
    query = db.query(AuditLog)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action.upper())
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)

    return query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()


@router.get("/{log_id}", response_model=AuditLogResponse)
async def get_audit_entry(log_id: UUID, db: Session = Depends(get_db)):
    """Get a single audit log entry by ID."""
    from fastapi import HTTPException
    entry = db.query(AuditLog).filter(AuditLog.id == log_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Audit log entry not found")
    return entry


@audit_alias_router.get("/", response_model=List[AuditLogResponse])
async def list_audit_log_alias(
    user_id: str = Query(None),
    action: str = Query(None),
    resource_type: str = Query(None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Short alias for /api/audit-log/ — returns the same results."""
    return await list_audit_log(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        limit=limit,
        offset=offset,
        db=db,
    )
