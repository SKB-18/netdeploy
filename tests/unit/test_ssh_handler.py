"""
Phase 3 unit tests for SSHDevice.

Cowork provides test class structure and scenarios.
Cursor implements the SSHDevice methods being tested (core/ssh_handler.py).
MockRouter from tests/fixtures/mock_devices.py stubs out real SSH connections.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from tests.fixtures.mock_devices import MockRouter


# ---------------------------------------------------------------------------
# MockRouter sanity tests (these pass without Cursor implementing anything)
# ---------------------------------------------------------------------------

class TestMockRouter:
    def test_connect_returns_true(self):
        router = MockRouter("test-r1", 65001)
        assert router.connect() is True

    def test_bgp_summary_contains_asn_and_neighbor(self):
        router = MockRouter("test-r1", 65001)
        router.add_bgp_neighbor("192.168.1.2", 65002)
        router.connect()
        output = router.send_command("show bgp summary")
        assert "65001" in output
        assert "192.168.1.2" in output

    def test_running_config_contains_hostname(self):
        router = MockRouter("test-r1", 65001)
        router.connect()
        config = router.send_command("show running-config")
        assert "test-r1" in config

    def test_config_set_returns_true(self):
        router = MockRouter("test-r1", 65001)
        router.connect()
        result = router.send_config_set(["router bgp 65001", "neighbor 10.0.0.1 remote-as 65002"])
        assert result is True

    def test_simulate_failure_raises_on_connect(self):
        router = MockRouter("test-r1", 65001)
        router.simulate_failure(True)
        with pytest.raises(ConnectionError):
            router.connect()

    def test_ospf_neighbors_output(self):
        router = MockRouter("router-ospf", 65001)
        router.connect()
        output = router.send_command("show ospf neighbor")
        assert output is not None

    def test_multiple_bgp_neighbors(self):
        router = MockRouter("router-multi", 65001)
        router.add_bgp_neighbor("10.0.0.1", 65002)
        router.add_bgp_neighbor("10.0.0.2", 65003)
        router.connect()
        output = router.send_command("show bgp summary")
        assert "10.0.0.1" in output
        assert "10.0.0.2" in output


# ---------------------------------------------------------------------------
# SSHDevice unit tests (Cursor implements SSH methods, these test them)
# ---------------------------------------------------------------------------

class TestSSHDeviceInit:
    def test_default_values(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        assert ssh.hostname == "r1"
        assert ssh.ip == "10.0.0.1"
        assert ssh.device_type == "cisco_xr"
        assert ssh.port == 22
        assert ssh.username == "admin"
        assert ssh.connection is None

    def test_custom_port_and_timeout(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "junos", port=830, timeout=60)
        assert ssh.port == 830
        assert ssh.timeout == 60

    def test_repr(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "arista_eos")
        r = repr(ssh)
        assert "r1" in r
        assert "10.0.0.1" in r
        assert "arista_eos" in r


class TestSSHDeviceConnect:
    @pytest.mark.asyncio
    async def test_connect_sets_connection(self):
        """
        [CURSOR IMPLEMENTS]: patch netmiko.ConnectHandler with a mock,
        call SSHDevice.connect(), assert self.connection is set.
        """
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        mock_conn = MagicMock()
        with patch("core.ssh_handler.ConnectHandler", return_value=mock_conn, create=True):
            result = await ssh.connect()
        # After Cursor implements, result should be True and connection set
        # For now, placeholder returns False
        # Cursor removes the comment below:
        # assert result is True
        # assert ssh.connection is not None

    @pytest.mark.asyncio
    async def test_connect_returns_false_on_auth_failure(self):
        """
        [CURSOR IMPLEMENTS]: patch ConnectHandler to raise NetmikoAuthenticationException,
        assert connect() returns False (no exception propagated).
        """
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        # Cursor: mock ConnectHandler to raise AuthenticationException
        # assert await ssh.connect() is False

    @pytest.mark.asyncio
    async def test_connect_returns_false_on_timeout(self):
        """
        [CURSOR IMPLEMENTS]: patch ConnectHandler to raise NetmikoTimeoutException.
        """
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_ios")
        # Cursor implements — same pattern as auth failure


class TestSSHDeviceSendCommand:
    @pytest.mark.asyncio
    async def test_send_command_requires_connection(self):
        """send_command raises RuntimeError when not connected."""
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        assert ssh.connection is None
        with pytest.raises(RuntimeError, match="Not connected"):
            await ssh.send_command("show version")

    @pytest.mark.asyncio
    async def test_send_command_returns_string(self):
        """
        [CURSOR IMPLEMENTS]: set ssh.connection to a mock, call send_command,
        assert result is a non-empty string.
        """
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        mock_conn = MagicMock()
        mock_conn.send_command.return_value = "BGP router identifier 10.0.0.1"
        ssh.connection = mock_conn
        # Cursor: result = await ssh.send_command("show bgp summary")
        # assert isinstance(result, str) and len(result) > 0


class TestSSHDeviceGetRunningConfig:
    @pytest.mark.asyncio
    async def test_cisco_xr_uses_show_running_config(self):
        """cisco_xr sends 'show running-config'."""
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        ssh.send_command = AsyncMock(return_value="interface Loopback0")
        result = await ssh.get_running_config()
        ssh.send_command.assert_awaited_once_with("show running-config")

    @pytest.mark.asyncio
    async def test_junos_uses_show_configuration(self):
        """junos sends 'show configuration'."""
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "junos")
        ssh.send_command = AsyncMock(return_value="interfaces { ... }")
        await ssh.get_running_config()
        ssh.send_command.assert_awaited_once_with("show configuration")

    @pytest.mark.asyncio
    async def test_nokia_sros_uses_admin_display_config(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "nokia_sros")
        ssh.send_command = AsyncMock(return_value="# TiMOS config")
        await ssh.get_running_config()
        ssh.send_command.assert_awaited_once_with("admin display-config")


class TestSSHDeviceBGPSummary:
    @pytest.mark.asyncio
    async def test_cisco_xr_bgp_summary_cmd(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        ssh.send_command = AsyncMock(return_value="BGP summary")
        await ssh.get_bgp_summary()
        ssh.send_command.assert_awaited_once_with("show bgp neighbors summary")

    @pytest.mark.asyncio
    async def test_cisco_ios_bgp_summary_cmd(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_ios")
        ssh.send_command = AsyncMock(return_value="BGP summary")
        await ssh.get_bgp_summary()
        ssh.send_command.assert_awaited_once_with("show ip bgp summary")

    @pytest.mark.asyncio
    async def test_junos_bgp_summary_cmd(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "junos")
        ssh.send_command = AsyncMock(return_value="Peer: 10.0.0.1")
        await ssh.get_bgp_summary()
        ssh.send_command.assert_awaited_once_with("show bgp neighbor")

    @pytest.mark.asyncio
    async def test_arista_eos_bgp_summary_cmd(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "arista_eos")
        ssh.send_command = AsyncMock(return_value="BGP summary")
        await ssh.get_bgp_summary()
        ssh.send_command.assert_awaited_once_with("show bgp neighbors")


class TestSSHDeviceOSPFNeighbors:
    @pytest.mark.asyncio
    async def test_cisco_xr_ospf_cmd(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        ssh.send_command = AsyncMock(return_value="OSPF output")
        await ssh.get_ospf_neighbors()
        ssh.send_command.assert_awaited_once_with("show ospf neighbor")

    @pytest.mark.asyncio
    async def test_cisco_ios_ospf_cmd(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_ios")
        ssh.send_command = AsyncMock(return_value="OSPF output")
        await ssh.get_ospf_neighbors()
        ssh.send_command.assert_awaited_once_with("show ip ospf neighbor")

    @pytest.mark.asyncio
    async def test_arista_eos_ospf_cmd(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "arista_eos")
        ssh.send_command = AsyncMock(return_value="OSPF output")
        await ssh.get_ospf_neighbors()
        ssh.send_command.assert_awaited_once_with("show ip ospf neighbor")


class TestSSHDeviceInterfaceStatus:
    @pytest.mark.asyncio
    async def test_all_interfaces_cisco_xr(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        ssh.send_command = AsyncMock(return_value="GigE0/0 up")
        await ssh.get_interface_status()
        ssh.send_command.assert_awaited_once_with("show interfaces brief")

    @pytest.mark.asyncio
    async def test_all_interfaces_cisco_ios(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_ios")
        ssh.send_command = AsyncMock(return_value="GigE0/0 up")
        await ssh.get_interface_status()
        ssh.send_command.assert_awaited_once_with("show ip interface brief")

    @pytest.mark.asyncio
    async def test_all_interfaces_junos(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "junos")
        ssh.send_command = AsyncMock(return_value="ge-0/0/0 up")
        await ssh.get_interface_status()
        ssh.send_command.assert_awaited_once_with("show interfaces terse")

    @pytest.mark.asyncio
    async def test_specific_interface(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        ssh.send_command = AsyncMock(return_value="GigE0/0/0/0 up")
        await ssh.get_interface_status("GigabitEthernet0/0/0/0")
        ssh.send_command.assert_awaited_once_with("show interfaces GigabitEthernet0/0/0/0")


class TestSSHDevicePing:
    @pytest.mark.asyncio
    async def test_ping_cisco_xr_basic(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        ssh.send_command = AsyncMock(return_value="Success rate 100%")
        await ssh.ping("192.168.1.1", count=5)
        ssh.send_command.assert_awaited_once_with("ping 192.168.1.1 repeat 5")

    @pytest.mark.asyncio
    async def test_ping_cisco_xr_with_source(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        ssh.send_command = AsyncMock(return_value="Success rate 100%")
        await ssh.ping("192.168.1.1", count=3, source="10.0.0.1")
        ssh.send_command.assert_awaited_once_with("ping 192.168.1.1 repeat 3 source 10.0.0.1")

    @pytest.mark.asyncio
    async def test_ping_junos(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "junos")
        ssh.send_command = AsyncMock(return_value="5 packets transmitted")
        await ssh.ping("192.168.1.1", count=5)
        ssh.send_command.assert_awaited_once_with("ping 192.168.1.1 count 5 rapid")

    @pytest.mark.asyncio
    async def test_ping_returns_string(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "arista_eos")
        expected = "PING 192.168.1.1: 5 packets 100% success"
        ssh.send_command = AsyncMock(return_value=expected)
        result = await ssh.ping("192.168.1.1")
        assert result == expected


class TestSSHDeviceSaveConfig:
    @pytest.mark.asyncio
    async def test_save_config_cisco_ios(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_ios")
        ssh.send_command = AsyncMock(return_value="Building configuration... [OK]")
        result = await ssh.save_config()
        assert result is True
        ssh.send_command.assert_awaited_once_with("write memory")

    @pytest.mark.asyncio
    async def test_save_config_cisco_xr_no_op(self):
        """XR already commits during send_config_set — save_config is a no-op."""
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        ssh.send_command = AsyncMock()
        result = await ssh.save_config()
        assert result is True
        ssh.send_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_save_config_junos_no_op(self):
        """JunOS already commits during send_config_set."""
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "junos")
        ssh.send_command = AsyncMock()
        result = await ssh.save_config()
        assert result is True
        ssh.send_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_save_config_returns_false_on_error(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_ios")
        ssh.send_command = AsyncMock(return_value="% Error writing config")
        result = await ssh.save_config()
        assert result is False


class TestSSHDeviceContextManager:
    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        """SSHDevice can be used as async context manager."""
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        ssh.connect = AsyncMock(return_value=True)
        ssh.disconnect = AsyncMock()

        async with ssh as s:
            assert s is ssh

        ssh.connect.assert_awaited_once()
        ssh.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_context_manager_disconnects_on_exception(self):
        """disconnect() called even if body raises."""
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        ssh.connect = AsyncMock(return_value=True)
        ssh.disconnect = AsyncMock()

        with pytest.raises(RuntimeError):
            async with ssh:
                raise RuntimeError("Something went wrong")

        ssh.disconnect.assert_awaited_once()


class TestSSHDeviceDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_clears_connection(self):
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        ssh.connection = MagicMock()
        await ssh.disconnect()
        assert ssh.connection is None

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        """Should not raise even if already disconnected."""
        from core.ssh_handler import SSHDevice
        ssh = SSHDevice("r1", "10.0.0.1", "cisco_xr")
        assert ssh.connection is None
        await ssh.disconnect()  # Should not raise
