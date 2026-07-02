"""SQLAlchemy ORM models for NetDeploy."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Column, String, Integer, Text, DateTime, JSON, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Device(Base):
    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    hostname = Column(String(255), unique=True, nullable=False)
    device_type = Column(String(50), nullable=False)  # cisco_xr, junos, arista_eos
    management_ip = Column(String(15), nullable=False)
    ssh_port = Column(Integer, default=22)
    bgp_asn = Column(Integer, nullable=True)
    ospf_area = Column(String(50), nullable=True)
    os_version = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    configurations = relationship("Configuration", back_populates="device")
    deployments = relationship("Deployment", back_populates="device")

    __table_args__ = (
        Index("idx_devices_hostname", "hostname"),
        Index("idx_devices_ip", "management_ip"),
    )

    def __repr__(self):
        return f"<Device {self.hostname} ({self.management_ip})>"


class Configuration(Base):
    __tablename__ = "configurations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    version = Column(String(40), nullable=False)  # git commit hash
    desired_state = Column(JSON, nullable=False)
    running_state = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, SYNCED, DRIFT, FAILED
    deployed_at = Column(DateTime, nullable=True)
    created_by = Column(String(100), nullable=False, default="system")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device = relationship("Device", back_populates="configurations")

    __table_args__ = (
        Index("idx_configs_device_id", "device_id"),
        Index("idx_configs_version", "version"),
    )


class Deployment(Base):
    __tablename__ = "deployments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    batch_id = Column(UUID(as_uuid=True), nullable=False, default=uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    config_version = Column(String(40), nullable=False)
    status = Column(String(20), nullable=False, default="QUEUED")
    # QUEUED, IN_PROGRESS, SUCCESS, ROLLBACK, FAILED
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    rollback_to_version = Column(String(40), nullable=True)
    error_message = Column(Text, nullable=True)
    logs = Column(Text, nullable=True)
    strategy = Column(String(20), nullable=False, default="atomic")
    created_at = Column(DateTime, default=datetime.utcnow)

    device = relationship("Device", back_populates="deployments")
    snapshots = relationship("ConfigSnapshot", back_populates="deployment")

    __table_args__ = (
        Index("idx_deployments_batch_id", "batch_id"),
        Index("idx_deployments_device_id", "device_id"),
        Index("idx_deployments_status", "status"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(String(100), nullable=False)
    action = Column(String(50), nullable=False)  # CREATE, DEPLOY, ROLLBACK, SYNC, DELETE
    resource_type = Column(String(50), nullable=False)  # Device, Configuration, Deployment
    resource_id = Column(UUID(as_uuid=True), nullable=False)
    details = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    ip_address = Column(String(45), nullable=True)  # supports IPv6

    __table_args__ = (
        Index("idx_audit_timestamp", "timestamp"),
        Index("idx_audit_user", "user_id"),
        Index("idx_audit_action", "action"),
    )


class ConfigSnapshot(Base):
    __tablename__ = "config_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    deployment_id = Column(UUID(as_uuid=True), ForeignKey("deployments.id"), nullable=False)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    config_before = Column(JSON, nullable=True)
    config_after = Column(JSON, nullable=True)
    applied_at = Column(DateTime, default=datetime.utcnow)
    snapshot_hash = Column(String(64), nullable=True)

    deployment = relationship("Deployment", back_populates="snapshots")

    __table_args__ = (
        Index("idx_snapshots_deployment_id", "deployment_id"),
    )
