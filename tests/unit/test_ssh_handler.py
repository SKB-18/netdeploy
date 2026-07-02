"""Unit tests for SSHDevice — [CURSOR IMPLEMENTS using MockRouter]."""

import pytest
from tests.fixtures.mock_devices import MockRouter


def test_mock_router_connect():
    router = MockRouter("test-r1", 65001)
    assert router.connect() is True


def test_mock_router_bgp_summary():
    router = MockRouter("test-r1", 65001)
    router.add_bgp_neighbor("192.168.1.2", 65002)
    router.connect()
    output = router.send_command("show bgp summary")
    assert "65001" in output
    assert "192.168.1.2" in output


def test_mock_router_running_config():
    router = MockRouter("test-r1", 65001)
    router.connect()
    config = router.send_command("show running-config")
    assert "test-r1" in config


def test_mock_router_config_set():
    router = MockRouter("test-r1", 65001)
    router.connect()
    result = router.send_config_set(["router bgp 65001", "neighbor 10.0.0.1 remote-as 65002"])
    assert result is True


def test_mock_router_simulate_failure():
    router = MockRouter("test-r1", 65001)
    router.simulate_failure(True)
    with pytest.raises(ConnectionError):
        router.connect()


# [CURSOR IMPLEMENTS] — Real SSHDevice tests using MockRouter patch
def test_ssh_device_connect():
    """CURSOR: Patch netmiko.ConnectHandler with MockRouter, test SSHDevice.connect()"""
    pass


def test_ssh_device_send_command():
    """CURSOR: Test SSHDevice.send_command() with mocked connection."""
    pass


def test_ssh_device_get_running_config():
    """CURSOR: Test SSHDevice.get_running_config() returns non-empty string."""
    pass
