"""Device CRUD and health check endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.dependencies import get_db, get_current_user, get_client_ip
from api.models import Device, AuditLog
from api.schemas import DeviceRequest, DeviceResponse, DeviceHealthResponse

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.post("/", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def create_device(
    request_body: DeviceRequest,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Register a new network device.
    
    [CURSOR IMPLEMENTS]:
    1. Check for duplicate hostname/IP
    2. Create Device record
    3. Write AuditLog entry
    4. Return DeviceResponse
    """
    # Check duplicate
    existing = db.query(Device).filter(Device.hostname == request_body.hostname).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Device {request_body.hostname} already exists")

    device = Device(**request_body.dict())
    db.add(device)
    db.commit()
    db.refresh(device)

    # Audit log
    audit = AuditLog(
        user_id=user["user_id"],
        action="CREATE",
        resource_type="Device",
        resource_id=device.id,
        details={"hostname": device.hostname},
        ip_address=get_client_ip(request),
    )
    db.add(audit)
    db.commit()

    return device


@router.get("/", response_model=List[DeviceResponse])
async def list_devices(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List all registered devices."""
    return db.query(Device).offset(skip).limit(limit).all()


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: UUID, db: Session = Depends(get_db)):
    """Get a single device by ID."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.put("/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: UUID,
    request_body: DeviceRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Update device properties.
    
    [CURSOR IMPLEMENTS]: Update fields, write audit log, return updated device.
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    for field, value in request_body.dict(exclude_unset=True).items():
        setattr(device, field, value)

    db.commit()
    db.refresh(device)
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a device record."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    db.delete(device)
    db.commit()


@router.get("/{device_id}/health", response_model=DeviceHealthResponse)
async def device_health(device_id: UUID, db: Session = Depends(get_db)):
    """
    Check real-time device health via SSH.
    
    [CURSOR IMPLEMENTS]:
    1. Fetch device from DB
    2. SSH connect
    3. Check BGP neighbor states
    4. Check OSPF adjacencies
    5. Return DeviceHealthResponse
    """
    from datetime import datetime

    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Placeholder — Cursor implements real SSH health check
    return DeviceHealthResponse(
        device_id=device.id,
        hostname=device.hostname,
        reachable=False,
        bgp_neighbors_up=None,
        ospf_adjacencies_up=None,
        last_checked=datetime.utcnow(),
    )


@router.post("/{device_id}/sync", response_model=dict)
async def sync_device(
    device_id: UUID,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Sync running config from device into DB.
    
    [CURSOR IMPLEMENTS]: SSH → get_running_config → update Configuration.running_state
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Placeholder
    return {"status": "sync_queued", "device_id": str(device_id)}
