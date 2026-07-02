"""Unit tests for StateVerifier — post-deployment state checks."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from core.state_verifier import (
    StateVerifier,
    VerificationResult,
    _parse_bgp_neighbor_state,
    _parse_ping_success,
)


@pytest.fixture
def verifier():
    return StateVerifier()


# ---------------------------------------------------------------------------
# VerificationResult
# ---------------------------------------------------------------------------

class TestVerificationResult:
    def test_initial_state_passes(self):
        r = VerificationResult()
        assert r.passed is True
        assert r.checks == []

    def test_add_passing_check(self):
        r = VerificationResult()
        r.add_check("bgp_neighbor_1.2.3.4", True, "Established")
        assert r.passed is True
        assert len(r.checks) == 1
        assert r.checks[0]["passed"] is True

    def test_add_failing_check_sets_passed_false(self):
        r = VerificationResult()
        r.add_check("bgp_neighbor_1.2.3.4", False, "Not Established")
        assert r.passed is False

    def test_mixed_checks_fails(self):
        r = VerificationResult()
        r.add_check("check_a", True, "ok")
        r.add_check("check_b", False, "fail")
        assert r.passed is False

    def test_to_dict(self):
        r = VerificationResult()
        r.add_check("test", True, "detail")
        d = r.to_dict()
        assert d["passed"] is True
        assert isinstance(d["checks"], list)
        assert d["checks"][0]["name"] == "test"


# ---------------------------------------------------------------------------
# _parse_bgp_neighbor_state
# ---------------------------------------------------------------------------

class TestParseBGPNeighborState:
    def test_cisco_established_inline(self):
        output = (
            "Neighbor        V    AS MsgRcvd MsgSent State\n"
            "192.168.1.2     4  65002    100    100 Established\n"
        )
        assert _parse_bgp_neighbor_state(output, "192.168.1.2", "cisco_xr") is True

    def test_cisco_not_established(self):
        output = (
            "Neighbor        V    AS MsgRcvd MsgSent State\n"
            "192.168.1.2     4  65002      0      0 Active\n"
        )
        assert _parse_bgp_neighbor_state(output, "192.168.1.2", "cisco_xr") is False

    def test_ip_not_in_output(self):
        output = "BGP router identifier 10.0.0.1"
        assert _parse_bgp_neighbor_state(output, "192.168.1.2", "cisco_xr") is False

    def test_junos_state_on_next_line(self):
        output = (
            "Peer: 192.168.1.2+179 AS 65002\n"
            "Type: External    State: Established\n"
        )
        assert _parse_bgp_neighbor_state(output, "192.168.1.2", "junos") is True

    def test_junos_not_established(self):
        output = (
            "Peer: 192.168.1.2+179 AS 65002\n"
            "Type: External    State: Active\n"
        )
        assert _parse_bgp_neighbor_state(output, "192.168.1.2", "junos") is False

    def test_case_insensitive_established(self):
        output = "192.168.1.5 4 65005 established\n"
        assert _parse_bgp_neighbor_state(output, "192.168.1.5", "cisco_ios") is True


# ---------------------------------------------------------------------------
# _parse_ping_success
# ---------------------------------------------------------------------------

class TestParsePingSuccess:
    def test_cisco_100_percent(self):
        output = "Success rate is 100 percent (5/5), round-trip min/avg/max = 1/2/3 ms"
        assert _parse_ping_success(output, "cisco_xr", 5) is True

    def test_cisco_0_percent(self):
        output = "Success rate is 0 percent (0/5)"
        assert _parse_ping_success(output, "cisco_xr", 5) is False

    def test_cisco_60_percent_fails_threshold(self):
        output = "Success rate is 60 percent (3/5)"
        assert _parse_ping_success(output, "cisco_xr", 5) is False

    def test_cisco_80_percent_passes(self):
        output = "Success rate is 80 percent (4/5)"
        assert _parse_ping_success(output, "cisco_xr", 5) is True

    def test_junos_all_received(self):
        output = "5 packets transmitted, 5 received, 0% packet loss"
        assert _parse_ping_success(output, "junos", 5) is True

    def test_junos_all_lost(self):
        output = "5 packets transmitted, 0 received, 100% packet loss"
        assert _parse_ping_success(output, "junos", 5) is False

    def test_junos_2_of_3_fails_threshold(self):
        # 2/3 = 0.667 which is less than 0.67 threshold — correctly fails
        output = "3 packets transmitted, 2 received"
        assert _parse_ping_success(output, "junos", 3) is False

    def test_junos_3_of_4_passes_threshold(self):
        # 3/4 = 0.75 which exceeds 0.67 threshold
        output = "4 packets transmitted, 3 received"
        assert _parse_ping_success(output, "junos", 4) is True

    def test_exclamation_fallback(self):
        output = "!!!!!"
        assert _parse_ping_success(output, "cisco_xr", 5) is True

    def test_unknown_output_fails(self):
        output = "PING timed out"
        assert _parse_ping_success(output, "arista_eos", 5) is False


# ---------------------------------------------------------------------------
# verify_bgp_neighbors
# ---------------------------------------------------------------------------

class TestVerifyBGPNeighbors:
    @pytest.mark.asyncio
    async def test_all_neighbors_established(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value=(
            "Neighbor        V    AS  State\n"
            "10.0.0.2        4  65002  Established\n"
            "10.0.0.3        4  65003  Established\n"
        ))
        bgp = {
            "neighbors": [
                {"neighbor_ip": "10.0.0.2"},
                {"neighbor_ip": "10.0.0.3"},
            ]
        }
        result = await verifier.verify_bgp_neighbors(mock_ssh, bgp, "cisco_xr")
        assert result.passed is True
        assert len(result.checks) == 2

    @pytest.mark.asyncio
    async def test_one_neighbor_not_established(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value=(
            "Neighbor        V    AS  State\n"
            "10.0.0.2        4  65002  Established\n"
            "10.0.0.3        4  65003  Active\n"
        ))
        bgp = {
            "neighbors": [
                {"neighbor_ip": "10.0.0.2"},
                {"neighbor_ip": "10.0.0.3"},
            ]
        }
        result = await verifier.verify_bgp_neighbors(mock_ssh, bgp, "cisco_xr")
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_ssh_error_returns_failure(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(side_effect=RuntimeError("SSH error"))
        result = await verifier.verify_bgp_neighbors(mock_ssh, {"neighbors": []}, "cisco_xr")
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_no_neighbors_configured(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value="BGP summary output")
        result = await verifier.verify_bgp_neighbors(mock_ssh, {"neighbors": []}, "cisco_ios")
        assert result.passed is True
        assert result.checks == []

    @pytest.mark.asyncio
    async def test_junos_bgp_command(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value="Peer: 10.0.0.2+179 AS 65002\nState: Established")
        bgp = {"neighbors": [{"neighbor_ip": "10.0.0.2"}]}
        await verifier.verify_bgp_neighbors(mock_ssh, bgp, "junos")
        mock_ssh.send_command.assert_awaited_once_with("show bgp neighbor")

    @pytest.mark.asyncio
    async def test_arista_bgp_command(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value="BGP summary")
        bgp = {"neighbors": []}
        await verifier.verify_bgp_neighbors(mock_ssh, bgp, "arista_eos")
        mock_ssh.send_command.assert_awaited_once_with("show bgp neighbors")


# ---------------------------------------------------------------------------
# verify_ospf_adjacencies
# ---------------------------------------------------------------------------

class TestVerifyOSPFAdjacencies:
    @pytest.mark.asyncio
    async def test_full_adjacency_passes(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value=(
            "Neighbor ID    Pri  State    Dead Time\n"
            "192.168.0.2    1    FULL/-   00:00:35\n"
        ))
        result = await verifier.verify_ospf_adjacencies(mock_ssh, {}, "cisco_xr")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_no_full_adjacency_fails(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value=(
            "Neighbor ID    Pri  State    Dead Time\n"
            "192.168.0.2    1    EXSTART  00:00:35\n"
        ))
        result = await verifier.verify_ospf_adjacencies(mock_ssh, {}, "cisco_xr")
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_ssh_error_returns_failure(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(side_effect=RuntimeError("connection lost"))
        result = await verifier.verify_ospf_adjacencies(mock_ssh, {}, "cisco_ios")
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_cisco_ios_ospf_command(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value="FULL/DR")
        await verifier.verify_ospf_adjacencies(mock_ssh, {}, "cisco_ios")
        mock_ssh.send_command.assert_awaited_once_with("show ip ospf neighbor")

    @pytest.mark.asyncio
    async def test_arista_eos_ospf_command(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value="FULL")
        await verifier.verify_ospf_adjacencies(mock_ssh, {}, "arista_eos")
        mock_ssh.send_command.assert_awaited_once_with("show ip ospf neighbor")


# ---------------------------------------------------------------------------
# verify_reachability
# ---------------------------------------------------------------------------

class TestVerifyReachability:
    @pytest.mark.asyncio
    async def test_all_prefixes_reachable(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value="Success rate is 100 percent (3/3)")
        result = await verifier.verify_reachability(mock_ssh, ["10.0.0.0/8", "192.168.1.0/24"], "cisco_xr", count=3)
        assert result.passed is True
        assert len(result.checks) == 2

    @pytest.mark.asyncio
    async def test_one_prefix_unreachable(self, verifier):
        mock_ssh = MagicMock()
        responses = [
            "Success rate is 100 percent (3/3)",
            "Success rate is 0 percent (0/3)",
        ]
        mock_ssh.send_command = AsyncMock(side_effect=responses)
        result = await verifier.verify_reachability(
            mock_ssh, ["10.0.0.1/32", "172.16.0.1/32"], "cisco_xr", count=3
        )
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_ssh_error_per_prefix(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(side_effect=RuntimeError("SSH error"))
        result = await verifier.verify_reachability(mock_ssh, ["10.0.0.1/32"], "cisco_xr")
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_empty_prefixes(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock()
        result = await verifier.verify_reachability(mock_ssh, [], "cisco_xr")
        assert result.passed is True
        mock_ssh.send_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_junos_ping_command(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value="3 packets transmitted, 3 received")
        await verifier.verify_reachability(mock_ssh, ["10.0.0.1/32"], "junos", count=3)
        mock_ssh.send_command.assert_awaited_once_with("ping 10.0.0.1 count 3 rapid")

    @pytest.mark.asyncio
    async def test_cisco_ping_command(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value="Success rate is 100 percent")
        await verifier.verify_reachability(mock_ssh, ["192.168.1.1/24"], "cisco_xr", count=5)
        mock_ssh.send_command.assert_awaited_once_with("ping 192.168.1.1 repeat 5")


# ---------------------------------------------------------------------------
# verify_all
# ---------------------------------------------------------------------------

class TestVerifyAll:
    @pytest.mark.asyncio
    async def test_bgp_and_ospf_run_when_both_present(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value="FULL Established")
        config = {
            "bgp": {"neighbors": [{"neighbor_ip": "10.0.0.2"}]},
            "ospf": {},
        }
        result = await verifier.verify_all(mock_ssh, config, "cisco_xr")
        # Both send_command called (bgp + ospf)
        assert mock_ssh.send_command.await_count == 2

    @pytest.mark.asyncio
    async def test_only_bgp_checks_run(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock(return_value="Established")
        config = {"bgp": {"neighbors": []}}
        await verifier.verify_all(mock_ssh, config, "cisco_xr")
        assert mock_ssh.send_command.await_count == 1

    @pytest.mark.asyncio
    async def test_empty_config_no_checks(self, verifier):
        mock_ssh = MagicMock()
        mock_ssh.send_command = AsyncMock()
        result = await verifier.verify_all(mock_ssh, {}, "cisco_xr")
        assert result.passed is True
        mock_ssh.send_command.assert_not_awaited()
