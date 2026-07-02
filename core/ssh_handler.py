"""
SSHDevice — Netmiko wrapper for network device SSH connections.

Cowork provides: class interface, method stubs with docstrings.
Cursor implements: connect, send_command, send_config_set, get_running_config, disconnect.
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
        
        [CURSOR IMPLEMENTS]
        """
        logger.info("Connecting to %s (%s) via SSH", self.hostname, self.ip)
        # Placeholder — Cursor implements:
        # from netmiko import ConnectHandler
        # self.connection = await asyncio.get_event_loop().run_in_executor(
        #     None,
        #     lambda: ConnectHandler(
        #         device_type=self.device_type,
        #         host=self.ip,
        #         port=self.port,
        #         username=self.username,
        #         password=self.password,
        #         secret=self.secret,
        #         timeout=self.timeout,
        #     )
        # )
        return False  # Cursor replaces

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
        # Cursor: return await asyncio.get_event_loop().run_in_executor(
        #     None, lambda: self.connection.send_command(cmd)
        # )
        return f"[NOT IMPLEMENTED] Output for: {cmd}"

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
        # Cursor: output = await asyncio.get_event_loop().run_in_executor(
        #     None, lambda: self.connection.send_config_set(cmds)
        # )
        # Check output for error indicators
        return False  # Cursor replaces

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

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    def __repr__(self):
        return f"<SSHDevice {self.hostname} ({self.ip}) type={self.device_type}>"
