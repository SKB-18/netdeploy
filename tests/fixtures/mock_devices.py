"""MockRouter — simulated network router for testing without real SSH connections."""


class MockRouter:
    """Simulate a network router for unit/integration tests."""

    def __init__(self, hostname: str, asn: int, device_type: str = "cisco_xr"):
        self.hostname = hostname
        self.asn = asn
        self.device_type = device_type
        self.bgp_neighbors: list = []
        self.ospf_areas: list = []
        self.running_config = self._generate_default_config()
        self._connected = False
        self._should_fail = False  # Set True to simulate SSH failure

    # ------------------------------------------------------------------
    # Connection simulation
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Simulate SSH connection."""
        if self._should_fail:
            raise ConnectionError(f"Simulated SSH failure for {self.hostname}")
        self._connected = True
        return True

    def disconnect(self):
        self._connected = False

    # ------------------------------------------------------------------
    # Command simulation
    # ------------------------------------------------------------------

    def send_command(self, cmd: str) -> str:
        """Return simulated output for common show commands."""
        cmd_lower = cmd.lower().strip()

        if "show bgp summary" in cmd_lower or "show bgp neighbors" in cmd_lower:
            return self._bgp_summary()
        elif "show ospf neighbor" in cmd_lower or "show ip ospf neighbor" in cmd_lower:
            return self._ospf_neighbors()
        elif "show version" in cmd_lower:
            return self._version_output()
        elif "show running-config" in cmd_lower or "show configuration" in cmd_lower:
            return self.running_config
        elif "show interfaces" in cmd_lower:
            return "GigabitEthernet0/0/0  192.168.1.1/24  Up/Up"
        else:
            return f"% Command not found: {cmd}"

    def send_config_set(self, cmds: list) -> bool:
        """Simulate applying configuration commands."""
        if self._should_fail:
            raise RuntimeError(f"Simulated config failure on {self.hostname}")
        applied = "\n".join(cmds)
        self.running_config = f"! Applied commands:\n{applied}\n\n{self.running_config}"
        return True

    # ------------------------------------------------------------------
    # Output generators
    # ------------------------------------------------------------------

    def _bgp_summary(self) -> str:
        lines = [
            f"BGP router identifier 192.168.1.1, local AS number {self.asn}",
            "BGP table version is 1",
            "",
            "Neighbor        V    AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down  State/PfxRcd",
        ]
        for neighbor in self.bgp_neighbors:
            lines.append(
                f"{neighbor['ip']:<16} 4 {neighbor['remote_asn']:<6} 100 100 1 0 0 00:10:00 Established"
            )
        return "\n".join(lines)

    def _ospf_neighbors(self) -> str:
        lines = ["Neighbor ID  Pri State  Dead Time  Address    Interface"]
        for area in self.ospf_areas:
            lines.append(f"192.168.0.2  1   FULL/-   00:00:35  192.168.1.2  Gi0/0/0")
        return "\n".join(lines)

    def _version_output(self) -> str:
        return (
            f"Cisco IOS XR Software, Version 7.3.1\n"
            f"Compiled Tue 01-Jan-23 by developer\n"
            f"Router uptime is 1 day, 2 hours\n"
            f"hostname {self.hostname}\n"
        )

    def _generate_default_config(self) -> str:
        return f"""
hostname {self.hostname}
!
router bgp {self.asn}
 bgp router-id 192.168.1.1
 address-family ipv4 unicast
 !
!
router ospf 1
 area 0
  interface GigabitEthernet0/0/0
  !
 !
!
interface GigabitEthernet0/0/0
 ipv4 address 192.168.1.1 255.255.255.0
!
end
"""

    def add_bgp_neighbor(self, ip: str, remote_asn: int):
        """Add a simulated BGP neighbor."""
        self.bgp_neighbors.append({"ip": ip, "remote_asn": remote_asn})

    def simulate_failure(self, fail: bool = True):
        """Make the mock router simulate SSH/config failures."""
        self._should_fail = fail
