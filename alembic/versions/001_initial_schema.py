"""Initial schema: devices, configurations, deployments, audit_logs, config_snapshots

Revision ID: 001
Revises:
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ devices
    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("hostname", sa.String(255), nullable=False, unique=True),
        sa.Column("device_type", sa.String(50), nullable=False),
        sa.Column("management_ip", sa.String(15), nullable=False),
        sa.Column("ssh_port", sa.Integer(), nullable=False, server_default="22"),
        sa.Column("bgp_asn", sa.Integer(), nullable=True),
        sa.Column("ospf_area", sa.String(50), nullable=True),
        sa.Column("os_version", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("idx_devices_hostname", "devices", ["hostname"])
    op.create_index("idx_devices_ip", "devices", ["management_ip"])

    # ----------------------------------------------------------- configurations
    op.create_table(
        "configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            nullable=False,
        ),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("desired_state", postgresql.JSON(), nullable=False),
        sa.Column("running_state", postgresql.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("deployed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("idx_configs_device_id", "configurations", ["device_id"])
    op.create_index("idx_configs_version", "configurations", ["version"])

    # ------------------------------------------------------------ deployments
    op.create_table(
        "deployments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            nullable=False,
        ),
        sa.Column("config_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="QUEUED"),
        sa.Column("strategy", sa.String(20), nullable=False, server_default="atomic"),
        sa.Column("start_time", sa.DateTime(), nullable=True),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("rollback_to_version", sa.String(40), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("logs", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_deployments_batch_id", "deployments", ["batch_id"])
    op.create_index("idx_deployments_device_id", "deployments", ["device_id"])
    op.create_index("idx_deployments_status", "deployments", ["status"])

    # ------------------------------------------------------------ audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("details", postgresql.JSON(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("ip_address", sa.String(45), nullable=True),
    )
    op.create_index("idx_audit_timestamp", "audit_logs", ["timestamp"])
    op.create_index("idx_audit_user", "audit_logs", ["user_id"])
    op.create_index("idx_audit_action", "audit_logs", ["action"])

    # -------------------------------------------------------- config_snapshots
    op.create_table(
        "config_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "deployment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("deployments.id"),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            nullable=False,
        ),
        sa.Column("config_before", postgresql.JSON(), nullable=True),
        sa.Column("config_after", postgresql.JSON(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("snapshot_hash", sa.String(64), nullable=True),
    )
    op.create_index("idx_snapshots_deployment_id", "config_snapshots", ["deployment_id"])


def downgrade() -> None:
    op.drop_table("config_snapshots")
    op.drop_table("audit_logs")
    op.drop_table("deployments")
    op.drop_table("configurations")
    op.drop_table("devices")
