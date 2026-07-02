"""
StateVerifier — verifies device state matches desired config after deployment.

Phase 3 Cowork: verification method stubs with exact show-command patterns
                and parsing logic outlines.

Cursor implements:
  - verify_bgp_neighbors (parse show bgp summary output)
  - verify_ospf_adjacencies (parse show ospf neighbor output)
  - verify_reachability (ping test routes)
  - verify_all (orchestrates all checks)
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class VerificationResult:
    """Result of a post-deployment state verification."""

    def __init__(self):
        self.passed: bool = True
        self.checks: List[Dict[str, Any]] = []

    def add_check(self, name: str, passed: bool, detail: str = ""):
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.passed = False

    def to_dict(self) -> dict:
        return {"passed": self.passed, "checks": self.checks}


class StateVerifier:
    """
    Verifies post-deployment device state via SSH show commands.

    Each verify_* method:
    1. Sends the appropriate show command via ssh_device
    2. Parses the output
    3. Compares against expected state from desired_config
    4. Returns pass/fail with detail
    """

    async def verify_all(
        self,
        ssh_device,
        desired_config: dict,
        device_type: str,
    ) -> VerificationResult:
        """
        Run all applicable verifications for a device.

        Runs BGP checks if "bgp" in desired_config.
        Runs OSPF checks if "ospf" in desired_config.
        Always runs basic reachability.

        Returns VerificationResult with per-check results.

        [CURSOR IMPLEMENTS by calling individual verify_* methods]
        """
        result = VerificationResult()

        if "bgp" in desired_config:
            bgp_result = await self.verify_bgp_neighbors(
                ssh_device, desired_config["bgp"], device_type
            )
            for check in bgp_result.checks:
                result.add_check(check["name"], check["passed"], check["detail"])

        if "ospf" in desired_config:
            ospf_result = await self.verify_ospf_adjacencies(
                ssh_device, desired_config["ospf"], device_type
            )
            for check in ospf_result.checks:
                result.add_check(check["name"], check["passed"], check["detail"])

        return result

    async def verify_bgp_neighbors(
        self,
        ssh_device,
        bgp_config: dict,
        device_type: str,
    ) -> VerificationResult:
        """
        Verify all configured BGP neighbors are in Established state.

        Show commands by device type:
        - cisco_xr / cisco_ios: "show bgp neighbors summary"
        - junos:                 "show bgp neighbor"
        - arista_eos:            "show bgp neighbors"

        Parsing strategy (Cursor implements):
        1. Send show command
        2. Extract neighbor IP + state from output (regex or textfsm)
        3. For each neighbor in bgp_config["neighbors"]:
           - Check if IP appears in output
           - Check if state == "Established" (Cisco) / "Active" (JunOS)
        4. Add a check per neighbor: pass if Established, fail otherwise

        Example regex for Cisco:
            pattern = r"(\\d+\\.\\d+\\.\\d+\\.\\d+)\\s+\\d+\\s+\\d+\\s+\\d+\\s+\\d+\\s+\\d+\\s+(\\w+)"
            # group(1) = neighbor IP, group(2) = state

        [CURSOR IMPLEMENTS]
        """
        result = VerificationResult()
        cmd_map = {
            "cisco_xr": "show bgp neighbors summary",
            "cisco_ios": "show ip bgp summary",
            "junos": "show bgp neighbor",
            "arista_eos": "show bgp neighbors",
        }
        cmd = cmd_map.get(device_type, "show bgp summary")

        try:
            output = await ssh_device.send_command(cmd)
        except Exception as e:
            result.add_check("bgp_show_command", False, f"SSH error: {e}")
            return result

        expected_neighbors = bgp_config.get("neighbors", [])
        for neighbor in expected_neighbors:
            ip = neighbor.get("neighbor_ip", "")
            # Cursor: parse output to find ip + state
            # Placeholder: assume not verified until Cursor implements parser
            established = _parse_bgp_neighbor_state(output, ip, device_type)
            result.add_check(
                f"bgp_neighbor_{ip}",
                established,
                f"State: {'Established' if established else 'NOT Established'} (from: {cmd})",
            )

        return result

    async def verify_ospf_adjacencies(
        self,
        ssh_device,
        ospf_config: dict,
        device_type: str,
    ) -> VerificationResult:
        """
        Verify OSPF adjacencies are in Full state.

        Show commands by device type:
        - cisco_xr:   "show ospf neighbor"
        - cisco_ios:  "show ip ospf neighbor"
        - junos:      "show ospf neighbor"
        - arista_eos: "show ip ospf neighbor"

        Parsing strategy (Cursor implements):
        1. Send show command
        2. Extract neighbor ID + state
        3. Check state is "FULL" for each expected adjacency

        [CURSOR IMPLEMENTS]
        """
        result = VerificationResult()
        cmd_map = {
            "cisco_xr": "show ospf neighbor",
            "cisco_ios": "show ip ospf neighbor",
            "junos": "show ospf neighbor",
            "arista_eos": "show ip ospf neighbor",
        }
        cmd = cmd_map.get(device_type, "show ospf neighbor")

        try:
            output = await ssh_device.send_command(cmd)
        except Exception as e:
            result.add_check("ospf_show_command", False, f"SSH error: {e}")
            return result

        # Cursor: parse output for Full adjacencies
        # Placeholder check — passes if output contains "FULL"
        has_full = "FULL" in output.upper() or "Full" in output
        result.add_check(
            "ospf_adjacencies_full",
            has_full,
            f"Output contains FULL state: {has_full} (from: {cmd})",
        )

        return result

    async def verify_reachability(
        self,
        ssh_device,
        test_prefixes: List[str],
        device_type: str,
        count: int = 3,
    ) -> VerificationResult:
        """
        Ping test prefixes from the device to verify reachability.

        Sends "ping {prefix} count {count}" and checks for success rate.

        Success threshold: ≥ 67% of pings must succeed (2 of 3).

        [CURSOR IMPLEMENTS]
        """
        result = VerificationResult()

        for prefix in test_prefixes:
            # Extract host from CIDR for ping
            host = prefix.split("/")[0]
            if device_type == "junos":
                cmd = f"ping {host} count {count} rapid"
            else:
                cmd = f"ping {host} repeat {count}"

            try:
                output = await ssh_device.send_command(cmd)
                # Cursor: parse success rate from ping output
                # Cisco: "Success rate is 100 percent (3/3)"
                # JunOS: "3 packets transmitted, 3 packets received"
                success = _parse_ping_success(output, device_type, count)
                result.add_check(
                    f"ping_{host}",
                    success,
                    f"Ping {host}: {'OK' if success else 'FAILED'} — {output[:80]}",
                )
            except Exception as e:
                result.add_check(f"ping_{host}", False, f"SSH error: {e}")

        return result


# ---------------------------------------------------------------------------
# Parser helpers (Cursor implements full regex logic)
# ---------------------------------------------------------------------------

def _parse_bgp_neighbor_state(output: str, neighbor_ip: str, device_type: str) -> bool:
    """
    Parse BGP show output to determine if neighbor_ip is Established.

    Cisco IOS/XR pattern:
        192.168.1.2      4  65002    100    100        1    0    0 00:10:00 Established
    JunOS pattern:
        Peer: 192.168.1.2+179 AS 65002 ...
        Type: External    State: Established

    Returns True if neighbor is in Established state.

    [CURSOR IMPLEMENTS full parser]
    """
    if neighbor_ip not in output:
        return False

    # Placeholder heuristic — Cursor replaces with real parser
    established_keywords = ["Established", "established", "ESTABLISHED"]
    lines = [l for l in output.splitlines() if neighbor_ip in l]
    for line in lines:
        if any(kw in line for kw in established_keywords):
            return True

    # JunOS: state may be on the next line
    if device_type == "junos" and "State: Established" in output:
        return True

    return False


def _parse_ping_success(output: str, device_type: str, expected_count: int) -> bool:
    """
    Parse ping output and return True if success rate >= 67%.

    [CURSOR IMPLEMENTS full parser with regex]
    """
    # Cisco: "Success rate is 100 percent (3/3)"
    cisco_match = re.search(r"Success rate is (\d+) percent", output)
    if cisco_match:
        return int(cisco_match.group(1)) >= 67

    # JunOS: "3 packets transmitted, 3 received"
    junos_match = re.search(r"(\d+) packets transmitted, (\d+) received", output)
    if junos_match:
        sent, rcvd = int(junos_match.group(1)), int(junos_match.group(2))
        return rcvd / max(sent, 1) >= 0.67

    # Fallback: look for "!!!" (each ! = success in Cisco)
    if "!!!" in output:
        return True

    return False
