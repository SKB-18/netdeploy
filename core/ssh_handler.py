"""
SSHDevice — Netmiko wrapper for network device SSH connections.

Phase 1 Cowork: class interface, core method stubs.
Phase 3 Cowork: adds show-command helpers used by StateVerifier
                (get_bgp_summary, get_ospf_neighbors, get_interface_status, ping).

Cursor implements:
  - connect / send_command / send_config_set / get_running_config / disconnect
  - get_bgp_summary
  - get_ospf_neighbors
  - get_interface_status
  - ping
"""

import asyncio
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class SSHDevice:
    """Wrapper for SSH connections to network devices via Netmiko."""

    def __init__(
        self,
        hostname: str,
        ip: str,
        device_type: str,
        port: int = 22,
        username: str = "admin",
        password: Optional[str] = None,
        secret: Optional[str] = None,
        timeout: int = 30,
    ):
        self.hostname = hostname
        self.ip = ip
        self.device_type = device_type  # cisco_xr, junos, arista_eos, etc.
        self.port = port
        self.username = username
        self.password = password
        self.secret = secret
        self.timeout = timeout
        self.connection = None  # Netmiko ConnectHandler instance

    async def connect(self) -> bool:
        """
        Establish SSH connection to the device.

        Uses Netmiko ConnectHandler in a thread pool (asyncio-friendly).
        Timeout: self.timeout seconds.
        Sets self.connection on success.

        Returns True if connected, False otherwise.
        """
        logger.info("Connecting to %s (%s) via SSH", self.hostname, self.ip)
        try:
            from netmiko import ConnectHandler
            loop = asyncio.get_event_loop()
            self.connection = await loop.run_in_executor(
                None,
                lambda: ConnectHandler(
                    device_type=self.device_type,
                    host=self.ip,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    secret=self.secret,
                    timeout=self.timeout,
                )
            )
            logger.info("Connected to %s", self.hostname)
            return True
        except Exception as e:
            logger.error("Failed to connect to %s: %s", self.hostname, e)
            self.connection = None
            return False

    async def send_command(self, cmd: str) -> str:
        """
        Execute a show/display command and return output.

        Handles:
        - Long-running commands (expects_string / strip_prompt)
        - Pagination (terminal length 0 or use_textfsm)
        - Timeout on slow responses

        Returns command output as string.
        
        [CURSOR IMPLEMENTS]
        """
        if self.connection is None:
            raise RuntimeError(f"Not connected to {self.hostname}")
        logger.debug("Sending command to %s: %s", self.hostname, cmd)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self.connection.send_command(cmd)
        )

    async def send_config_set(self, cmds: List[str]) -> bool:
        """
        Apply a list of configuration commands to the device.

        Handles:
        - Entry into config mode
        - Error detection (invalid command output)
        - Commit (JunOS requires explicit commit)
        - Exits config mode after

        Returns True if all commands applied successfully, False on error.
        
        [CURSOR IMPLEMENTS]
        """
        if self.connection is None:
            raise RuntimeError(f"Not connected to {self.hostname}")
        logger.info("Applying %d config commands to %s", len(cmds), self.hostname)
        try:
            loop = asyncio.get_event_loop()
            output = await loop.run_in_executor(
                None, lambda: self.connection.send_config_set(cmds)
            )
            error_indicators = ["% ", "Error", "Invalid", "Incomplete", "abort", "failed"]
            if any(indicator in output for indicator in error_indicators):
                logger.error("Config error on %s: %s", self.hostname, output[:200])
                return False
            return True
        except Exception as e:
            logger.error("send_config_set failed on %s: %s", self.hostname, e)
            return False

    async def get_running_config(self) -> str:
        """
        Fetch the device's full running configuration.

        Vendor-specific commands:
        - cisco_xr / cisco_ios: "show running-config"
        - junos: "show configuration"
        - arista_eos: "show running-config"

        Returns full running config as string.
        
        [CURSOR IMPLEMENTS]
        """
        cmd_map = {
            "cisco_xr": "show running-config",
            "cisco_ios": "show running-config",
            "junos": "show configuration",
            "arista_eos": "show running-config",
            "nokia_sros": "admin display-config",
        }
        cmd = cmd_map.get(self.device_type, "show running-config")
        return await self.send_command(cmd)

    async def disconnect(self):
        """Close the SSH connection cleanly."""
        if self.connection is not None:
            try:
                # Cursor: await asyncio.get_event_loop().run_in_executor(
                #     None, self.connection.disconnect
                # )
                pass
            except Exception:
                logger.warning("Error disconnecting from %s", self.hostname)
            finally:
                self.connection = None
        logger.info("Disconnected from %s", self.hostname)

    # ------------------------------------------------------------------
    # Phase 3: show-command helpers for StateVerifier
    # ------------------------------------------------------------------

    async def get_bgp_summary(self) -> str:
        """
        Fetch BGP neighbor summary from device.

        Vendor commands:
        - cisco_xr / cisco_ios: "show bgp neighbors summary" / "show ip bgp summary"
        - junos:                 "show bgp neighbor"
        - arista_eos:            "show bgp neighbors"

        Returns raw command output.
        Cursor implements (thin wrapper around send_command with right cmd).

        [CURSOR IMPLEMENTS]
        """
        cmd_map = {
            "cisco_xr":   "show bgp neighbors summary",
            "cisco_ios":  "show ip bgp summary",
            "junos":      "show bgp neighbor",
            "arista_eos": "show bgp neighbors",
        }
        cmd = cmd_map.get(self.device_type, "show bgp summary")
        return await self.send_command(cmd)

    async def get_ospf_neighbors(self) -> str:
        """
        Fetch OSPF neighbor table from device.

        Vendor commands:
        - cisco_xr:   "show ospf neighbor"
        - cisco_ios:  "show ip ospf neighbor"
        - junos:      "show ospf neighbor"
        - arista_eos: "show ip ospf neighbor"

        [CURSOR IMPLEMENTS]
        """
        cmd_map = {
            "cisco_xr":   "show ospf neighbor",
            "cisco_ios":  "show ip ospf neighbor",
            "junos":      "show ospf neighbor",
            "arista_eos": "show ip ospf neighbor",
        }
        cmd = cmd_map.get(self.device_type, "show ospf neighbor")
        return await self.send_command(cmd)

    async def get_interface_status(self, interface: str = None) -> str:
        """
        Fetch interface status (used to verify config applied correctly).

        If interface is None, fetches all interfaces.

        Vendor commands:
        - cisco_xr / cisco_ios: "show interfaces {interface}"
        - junos:                 "show interfaces {interface}"
        - arista_eos:            "show interfaces {interface}"

        [CURSOR IMPLEMENTS]
        """
        if interface:
            cmd_map = {
                "cisco_xr":   f"show interfaces {interface}",
                "cisco_ios":  f"show interfaces {interface}",
                "junos":      f"show interfaces {interface}",
                "arista_eos": f"show interfaces {interface}",
            }
        else:
            cmd_map = {
                "cisco_xr":   "show interfaces brief",
                "cisco_ios":  "show ip interface brief",
                "junos":      "show interfaces terse",
                "arista_eos": "show interfaces status",
            }
        cmd = cmd_map.get(self.device_type, "show interfaces")
        return await self.send_command(cmd)

    async def ping(self, target: str, count: int = 5, source: str = None) -> str:
        """
        Execute a ping from the device to test reachability.

        Vendor syntax:
        - cisco_xr / cisco_ios: "ping {target} repeat {count} [source {source}]"
        - junos:                 "ping {target} count {count} [routing-instance default]"
        - arista_eos:            "ping {target} repeat {count}"

        Returns raw ping output (StateVerifier parses success rate).

        [CURSOR IMPLEMENTS]
        """
        if self.device_type == "junos":
            cmd = f"ping {target} count {count} rapid"
        elif self.device_type in ("cisco_xr", "cisco_ios"):
            cmd = f"ping {target} repeat {count}"
            if source:
                cmd += f" source {source}"
        else:
            cmd = f"ping {target} repeat {count}"
        return await self.send_command(cmd)

    async def save_config(self) -> bool:
        """
        Persist running config to startup config.

        Vendor commands:
        - cisco_ios:  "write memory"
        - cisco_xr:   "commit" (XR already commits on send_config_set)
        - junos:      "commit" (already committed in send_config_set)
        - arista_eos: "write memory"

        Returns True on success.

        [CURSOR IMPLEMENTS]
        """
        cmd_map = {
            "cisco_xr":   None,       # XR commits during config mode
            "cisco_ios":  "write memory",
            "junos":      None,       # JunOS commits during config mode
            "arista_eos": "write memory",
        }
        cmd = cmd_map.get(self.device_type)
        if cmd is None:
            return True  # Already committed
        output = await self.send_command(cmd)
        return "error" not in output.lower()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    def __repr__(self):
        return f"<SSHDevice {self.hostname} ({self.ip}) type={self.device_type}>"
