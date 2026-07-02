"""Shared helpers for creating and updating deployment records."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from api.models import Configuration, Deployment


def create_deployment_records(
    db: Session,
    device_ids: list,
    batch_id,
    config_version: str,
    strategy: str,
) -> list:
    """Create one QUEUED Deployment row per device in a batch."""
    records = []
    for device_id in device_ids:
        dep = Deployment(
            batch_id=batch_id,
            device_id=device_id,
            config_version=config_version,
            status="QUEUED",
            strategy=strategy,
        )
        db.add(dep)
        records.append(dep)
    db.commit()
    for dep in records:
        db.refresh(dep)
    return records


def get_latest_config(db: Session, device_id) -> Optional[Configuration]:
    """Return the most recent configuration row for a device, if any."""
    return (
        db.query(Configuration)
        .filter(Configuration.device_id == device_id)
        .order_by(Configuration.created_at.desc())
        .first()
    )


def find_devices_missing_config(
    db: Session,
    device_ids: List[UUID],
    config_version: str = "latest",
) -> List[str]:
    """Return device IDs that have no usable config for the requested version."""
    missing: List[str] = []
    for device_id in device_ids:
        if config_version == "latest":
            config = get_latest_config(db, device_id)
            if not config or not config.desired_state:
                missing.append(str(device_id))
        else:
            config = (
                db.query(Configuration)
                .filter(
                    Configuration.device_id == device_id,
                    Configuration.version == config_version,
                )
                .first()
            )
            if not config:
                missing.append(str(device_id))
    return missing
