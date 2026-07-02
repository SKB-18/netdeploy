"""Integration tests for rollback flow — [CURSOR IMPLEMENTS]."""

import pytest


@pytest.mark.asyncio
async def test_atomic_rollback(client, mock_device):
    """
    CURSOR: Simulate atomic failure → verify rollback triggered.
    """
    pass


@pytest.mark.asyncio
async def test_manual_rollback_endpoint(client, mock_device):
    """
    CURSOR: POST /api/deployments/{id}/rollback → rollback queued.
    """
    pass
