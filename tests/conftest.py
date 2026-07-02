"""pytest fixtures for NetDeploy tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from api.models import Base
from api.main import app
from api.dependencies import get_db


import os

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://netdeploy:password@localhost:5432/netdeploy_test",
)


@pytest.fixture(scope="session")
def test_db_engine():
    """Create test PostgreSQL database schema."""
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(test_db_engine):
    """Provide a transactional DB session that rolls back after each test."""
    connection = test_db_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection)
    session = SessionLocal()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def client(db_session):
    """FastAPI test client wired to the test DB session."""
    from unittest.mock import patch

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # Disable rate limiting in unit/integration tests — prevents cross-test
    # IP count accumulation on the shared "testclient" host address.
    # The rate_limit marker tests opt back in explicitly.
    with patch(
        "api.middleware.rate_limiter._get_settings_limits",
        return_value={"limit": 100, "window": 60, "enabled": False},
    ):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_device(db_session):
    """Create a mock device in the test database."""
    from api.models import Device
    device = Device(
        hostname="test-router-1",
        device_type="cisco_xr",
        management_ip="192.168.1.1",
        ssh_port=22,
        bgp_asn=65001,
        os_version="7.3.1",
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    return device


@pytest.fixture
def mock_device_junos(db_session):
    """Create a JunOS mock device."""
    from api.models import Device
    device = Device(
        hostname="test-junos-1",
        device_type="junos",
        management_ip="192.168.1.10",
        bgp_asn=65002,
        os_version="21.4R1",
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    return device


@pytest.fixture
def valid_bgp_config():
    """Valid BGP configuration dict."""
    return {
        "bgp": {
            "local_asn": 65001,
            "router_id": "192.168.1.1",
            "neighbors": [
                {
                    "neighbor_ip": "192.168.1.2",
                    "remote_asn": 65002,
                    "description": "peer-router-2",
                }
            ],
            "route_policies": [
                {"prefix": "10.0.0.0/8", "action": "permit"},
            ],
        }
    }


@pytest.fixture
def invalid_bgp_config():
    """Invalid BGP configuration (ASN out of range)."""
    return {
        "bgp": {
            "local_asn": 99999999999,  # Invalid: exceeds 4294967295
            "neighbors": [
                {
                    "neighbor_ip": "127.0.0.1",  # Invalid: loopback
                    "remote_asn": 0,  # Invalid: 0 not allowed
                }
            ],
        }
    }


@pytest.fixture
def valid_ospf_config():
    """Valid OSPF configuration dict."""
    return {
        "ospf": {
            "process_id": 1,
            "areas": [
                {
                    "area_id": "0.0.0.0",
                    "hello_interval": 10,
                    "dead_interval": 40,
                    "networks": ["192.168.1.0/24"],
                }
            ],
        }
    }


@pytest.fixture
def conflicting_policy_config():
    """BGP config with conflicting route policies."""
    return {
        "bgp": {
            "local_asn": 65001,
            "neighbors": [],
            "route_policies": [
                {"prefix": "10.0.0.0/8", "action": "permit"},
                {"prefix": "10.0.0.0/8", "action": "deny"},  # Conflict!
            ],
        }
    }
