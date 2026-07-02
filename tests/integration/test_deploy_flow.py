"""Integration tests for full deploy flow — [CURSOR IMPLEMENTS]."""

import pytest


@pytest.mark.asyncio
async def test_full_deploy_flow(client, mock_device, valid_bgp_config):
    """
    CURSOR: End-to-end test:
    1. POST /api/configs/ with valid BGP config
    2. POST /api/configs/validate → valid=True
    3. POST /api/configs/deploy → batch_id returned
    4. GET /api/deployments/{id} → status progresses
    """
    pass


@pytest.mark.asyncio
async def test_validation_rejects_invalid(client, mock_device, invalid_bgp_config):
    """CURSOR: POST /api/configs/validate with invalid config → valid=False."""
    pass
