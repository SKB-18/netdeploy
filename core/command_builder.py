"""
CommandBuilder — converts desired-state config dicts into vendor-specific CLI commands.

Phase 3 Cowork: class structure, per-vendor method stubs with exact command
                examples so Cursor knows what syntax to emit.

Cursor implements:
  - _bgp_commands_cisco_xr
  - _bgp_commands_cisco_ios
  - _bgp_commands_junos
  - _bgp_commands_arista_eos
  - _ospf_commands_cisco_xr
  - _ospf_commands_cisco_ios
  - _ospf_commands_junos
  - _ospf_commands_arista_eos
"""

import logging
from typing import List

logger = logging.getLogger(__name__)

# Supported device types
SUPPORTED_DEVICE_TYPES = {"cisco_xr", "cisco_ios", "junos", "arista_eos", "nokia_sros"}


class CommandBuilder:
    """
    Converts a desired-state config dict into a list of CLI commands
    ready to pass to SSHDevice.send_config_set().

    Each vendor has a different syntax; this class encapsulates all of them.
    """

    def build(self, config: dict, device_type: str) -> List[str]:
        """
        Entry point: generate all commands for a device config.

        Args:
            config:      Desired-state dict (bgp + ospf sections)
            device_type: One of SUPPORTED_DEVICE_TYPES

        Returns:
            Ordered list of CLI commands to apply.

        Raises:
            ValueError: if device_type is unsupported.
        """
        if device_type not in SUPPORTED_DEVICE_TYPES:
            raise ValueError(
                f"Unsupported device type: {device_type!r}. "
                f"Supported: {sorted(SUPPORTED_DEVICE_TYPES)}"
            )

        commands: List[str] = []

        if "bgp" in config:
            commands.extend(self._bgp_commands(config["bgp"], device_type))

        if "ospf" in config:
            commands.extend(self._ospf_commands(config["ospf"], device_type))

        logger.debug(
            "Built %d commands for device_type=%s", len(commands), device_type
        )
        return commands

    # ------------------------------------------------------------------
    # BGP dispatch
    # ------------------------------------------------------------------

    def _bgp_commands(self, bgp: dict, device_type: str) -> List[str]:
        dispatch = {
            "cisco_xr":   self._bgp_commands_cisco_xr,
            "cisco_ios":  self._bgp_commands_cisco_ios,
            "junos":      self._bgp_commands_junos,
            "arista_eos": self._bgp_commands_arista_eos,
            "nokia_sros": self._bgp_commands_nokia_sros,
        }
        return dispatch[device_type](bgp)

    def _bgp_commands_cisco_xr(self, bgp: dict) -> List[str]:
        """
        Generate IOS-XR BGP configuration commands.

        Target syntax example:
            router bgp 65001
             bgp router-id 10.0.0.1
             address-family ipv4 unicast
             !
             neighbor 10.0.0.2
              remote-as 65002
              description peer-r2
              address-family ipv4 unicast
               route-policy PERMIT_ALL in
               route-policy PERMIT_ALL out
              !
             !
            !

        [CURSOR IMPLEMENTS]
        """
        asn = bgp.get("local_asn", "")
        cmds = [f"router bgp {asn}"]

        if bgp.get("router_id"):
            cmds.append(f" bgp router-id {bgp['router_id']}")

        cmds.append(" address-family ipv4 unicast")
        for net in bgp.get("networks", []):
            cmds.append(f"  network {net}")
        cmds.append(" !")

        for neighbor in bgp.get("neighbors", []):
            ip = neighbor.get("neighbor_ip", "")
            remote_asn = neighbor.get("remote_asn", "")
            cmds.append(f" neighbor {ip}")
            cmds.append(f"  remote-as {remote_asn}")
            if neighbor.get("description"):
                cmds.append(f"  description {neighbor['description']}")
            if neighbor.get("shutdown"):
                cmds.append("  shutdown")
            cmds.append("  address-family ipv4 unicast")
            if neighbor.get("next_hop_self"):
                cmds.append("   next-hop-self")
            if neighbor.get("soft_reconfiguration"):
                cmds.append("   soft-reconfiguration inbound")
            cmds.append("  !")
            cmds.append(" !")

        cmds.append("!")
        return cmds

    def _bgp_commands_cisco_ios(self, bgp: dict) -> List[str]:
        """
        Generate classic IOS BGP configuration commands.

        Target syntax example:
            router bgp 65001
             bgp router-id 10.0.0.1
             bgp log-neighbor-changes
             neighbor 10.0.0.2 remote-as 65002
             neighbor 10.0.0.2 description peer-r2
             !
             address-family ipv4
              neighbor 10.0.0.2 activate
              network 192.168.1.0 mask 255.255.255.0
             exit-address-family

        [CURSOR IMPLEMENTS]
        """
        asn = bgp.get("local_asn", "")
        cmds = [f"router bgp {asn}"]
        if bgp.get("router_id"):
            cmds.append(f" bgp router-id {bgp['router_id']}")
        cmds.append(" bgp log-neighbor-changes")

        for neighbor in bgp.get("neighbors", []):
            ip = neighbor.get("neighbor_ip", "")
            cmds.append(f" neighbor {ip} remote-as {neighbor.get('remote_asn', '')}")
            if neighbor.get("description"):
                cmds.append(f" neighbor {ip} description {neighbor['description']}")
            if neighbor.get("password"):
                cmds.append(f" neighbor {ip} password {neighbor['password']}")
            if neighbor.get("shutdown"):
                cmds.append(f" neighbor {ip} shutdown")

        cmds.append(" !")
        cmds.append(" address-family ipv4")
        for neighbor in bgp.get("neighbors", []):
            cmds.append(f"  neighbor {neighbor.get('neighbor_ip', '')} activate")
        for net in bgp.get("networks", []):
            # IOS uses network/mask syntax
            import ipaddress
            n = ipaddress.IPv4Network(net, strict=False)
            cmds.append(f"  network {n.network_address} mask {n.netmask}")
        cmds.append(" exit-address-family")
        return cmds

    def _bgp_commands_junos(self, bgp: dict) -> List[str]:
        """
        Generate JunOS set-format BGP configuration commands.

        Target syntax example:
            set routing-options autonomous-system 65001
            set routing-options router-id 10.0.0.1
            set protocols bgp group EBGP type external
            set protocols bgp group EBGP neighbor 10.0.0.2 peer-as 65002
            set protocols bgp group EBGP neighbor 10.0.0.2 description peer-r2

        [CURSOR IMPLEMENTS]
        """
        asn = bgp.get("local_asn", "")
        cmds = [f"set routing-options autonomous-system {asn}"]

        if bgp.get("router_id"):
            cmds.append(f"set routing-options router-id {bgp['router_id']}")

        # Group neighbors by remote ASN (JunOS uses peer groups)
        for neighbor in bgp.get("neighbors", []):
            ip = neighbor.get("neighbor_ip", "")
            remote_asn = neighbor.get("remote_asn", "")
            group = "IBGP" if remote_asn == asn else "EBGP"
            peer_type = "internal" if remote_asn == asn else "external"
            cmds.append(f"set protocols bgp group {group} type {peer_type}")
            cmds.append(f"set protocols bgp group {group} neighbor {ip} peer-as {remote_asn}")
            if neighbor.get("description"):
                cmds.append(
                    f"set protocols bgp group {group} neighbor {ip} "
                    f"description \"{neighbor['description']}\""
                )

        for net in bgp.get("networks", []):
            cmds.append(f"set policy-options policy-statement EXPORT term BGP from route-filter {net} exact")
            cmds.append("set policy-options policy-statement EXPORT term BGP then accept")

        return cmds

    def _bgp_commands_arista_eos(self, bgp: dict) -> List[str]:
        """
        Generate Arista EOS BGP configuration commands.

        Target syntax example:
            router bgp 65001
               router-id 10.0.0.1
               neighbor 10.0.0.2 remote-as 65002
               neighbor 10.0.0.2 description peer-r2
               !
               address-family ipv4
                  neighbor 10.0.0.2 activate
                  network 10.0.0.0/8

        [CURSOR IMPLEMENTS]
        """
        asn = bgp.get("local_asn", "")
        cmds = [f"router bgp {asn}"]
        if bgp.get("router_id"):
            cmds.append(f"   router-id {bgp['router_id']}")

        for neighbor in bgp.get("neighbors", []):
            ip = neighbor.get("neighbor_ip", "")
            cmds.append(f"   neighbor {ip} remote-as {neighbor.get('remote_asn', '')}")
            if neighbor.get("description"):
                cmds.append(f"   neighbor {ip} description {neighbor['description']}")

        cmds.append("   !")
        cmds.append("   address-family ipv4")
        for neighbor in bgp.get("neighbors", []):
            cmds.append(f"      neighbor {neighbor.get('neighbor_ip', '')} activate")
        for net in bgp.get("networks", []):
            cmds.append(f"      network {net}")

        return cmds

    def _bgp_commands_nokia_sros(self, bgp: dict) -> List[str]:
        """
        Generate Nokia SR-OS BGP configuration commands (MD-CLI style).

        [CURSOR IMPLEMENTS]
        """
        return ["# Nokia SR-OS BGP commands — CURSOR IMPLEMENTS"]

    # ------------------------------------------------------------------
    # OSPF dispatch
    # ------------------------------------------------------------------

    def _ospf_commands(self, ospf: dict, device_type: str) -> List[str]:
        dispatch = {
            "cisco_xr":   self._ospf_commands_cisco_xr,
            "cisco_ios":  self._ospf_commands_cisco_ios,
            "junos":      self._ospf_commands_junos,
            "arista_eos": self._ospf_commands_arista_eos,
            "nokia_sros": self._ospf_commands_nokia_sros,
        }
        return dispatch[device_type](ospf)

    def _ospf_commands_cisco_xr(self, ospf: dict) -> List[str]:
        """
        Generate IOS-XR OSPF configuration commands.

        Target syntax example:
            router ospf 1
             router-id 10.0.0.1
             area 0
              interface GigabitEthernet0/0/0
               cost 10
               hello-interval 10
               dead-interval 40
              !
             !
            !

        [CURSOR IMPLEMENTS]
        """
        pid = ospf.get("process_id", 1)
        cmds = [f"router ospf {pid}"]
        if ospf.get("router_id"):
            cmds.append(f" router-id {ospf['router_id']}")

        for area in ospf.get("areas", []):
            area_id = area.get("area_id", "0")
            cmds.append(f" area {area_id}")

            for net in area.get("networks", []):
                cmds.append(f"  network {net}")

            for iface in area.get("interfaces", []):
                name = iface.get("name", "")
                cmds.append(f"  interface {name}")
                if iface.get("cost"):
                    cmds.append(f"   cost {iface['cost']}")
                cmds.append(f"   hello-interval {iface.get('hello_interval', 10)}")
                cmds.append(f"   dead-interval {iface.get('dead_interval', 40)}")
                if iface.get("passive"):
                    cmds.append("   passive enable")
                cmds.append("  !")
            cmds.append(" !")

        cmds.append("!")
        return cmds

    def _ospf_commands_cisco_ios(self, ospf: dict) -> List[str]:
        """
        Generate classic IOS OSPF configuration commands.

        Target syntax example:
            router ospf 1
             router-id 10.0.0.1
             log-adjacency-changes
             area 1 stub
             network 192.168.1.0 0.0.0.255 area 0

        [CURSOR IMPLEMENTS]
        """
        pid = ospf.get("process_id", 1)
        cmds = [f"router ospf {pid}"]
        if ospf.get("router_id"):
            cmds.append(f" router-id {ospf['router_id']}")
        if ospf.get("log_adjacency_changes", True):
            cmds.append(" log-adjacency-changes")

        for area in ospf.get("areas", []):
            area_id = area.get("area_id", "0")
            area_type = area.get("area_type", "normal")
            if area_type == "stub":
                stub_flag = "no-summary" if area.get("no_summary") else ""
                cmds.append(f" area {area_id} stub {stub_flag}".rstrip())
            elif area_type == "nssa":
                cmds.append(f" area {area_id} nssa")

            for net in area.get("networks", []):
                import ipaddress
                n = ipaddress.IPv4Network(net, strict=False)
                wildcard = str(ipaddress.IPv4Address(int(n.hostmask)))
                cmds.append(f" network {n.network_address} {wildcard} area {area_id}")

        return cmds

    def _ospf_commands_junos(self, ospf: dict) -> List[str]:
        """
        Generate JunOS set-format OSPF configuration commands.

        Target syntax example:
            set protocols ospf area 0.0.0.0 interface ge-0/0/0.0
            set protocols ospf area 0.0.0.0 interface ge-0/0/0.0 hello-interval 10
            set protocols ospf area 0.0.0.0 interface ge-0/0/0.0 dead-interval 40

        [CURSOR IMPLEMENTS]
        """
        cmds = []
        for area in ospf.get("areas", []):
            area_id = area.get("area_id", "0.0.0.0")
            if "." not in str(area_id):
                area_id = f"0.0.0.{area_id}"
            area_type = area.get("area_type", "normal")
            if area_type == "stub":
                cmds.append(f"set protocols ospf area {area_id} stub")
            elif area_type == "nssa":
                cmds.append(f"set protocols ospf area {area_id} nssa")
            for iface in area.get("interfaces", []):
                name = iface.get("name", "")
                cmds.append(f"set protocols ospf area {area_id} interface {name}")
                cmds.append(
                    f"set protocols ospf area {area_id} interface {name} "
                    f"hello-interval {iface.get('hello_interval', 10)}"
                )
                cmds.append(
                    f"set protocols ospf area {area_id} interface {name} "
                    f"dead-interval {iface.get('dead_interval', 40)}"
                )
                if iface.get("passive"):
                    cmds.append(f"set protocols ospf area {area_id} interface {name} passive")
        return cmds

    def _ospf_commands_arista_eos(self, ospf: dict) -> List[str]:
        """
        Generate Arista EOS OSPF configuration commands.

        Target syntax example:
            router ospf 1
               router-id 10.0.0.1
               log-adjacency-changes detail
               area 0.0.0.1 stub
               network 192.168.1.0/24 area 0.0.0.0

        [CURSOR IMPLEMENTS]
        """
        pid = ospf.get("process_id", 1)
        cmds = [f"router ospf {pid}"]
        if ospf.get("router_id"):
            cmds.append(f"   router-id {ospf['router_id']}")
        if ospf.get("log_adjacency_changes", True):
            cmds.append("   log-adjacency-changes detail")
        for area in ospf.get("areas", []):
            area_id = area.get("area_id", "0")
            for net in area.get("networks", []):
                cmds.append(f"   network {net} area {area_id}")
        return cmds

    def _ospf_commands_nokia_sros(self, ospf: dict) -> List[str]:
        """[CURSOR IMPLEMENTS]"""
        return ["# Nokia SR-OS OSPF commands — CURSOR IMPLEMENTS"]

    # ------------------------------------------------------------------
    # Rollback commands
    # ------------------------------------------------------------------

    def build_rollback(self, config: dict, device_type: str) -> List[str]:
        """
        Generate commands to REMOVE a configuration (rollback / negate).

        Each vendor has different negate syntax:
        - Cisco IOS/XR: prefix with "no "
        - JunOS: replace "set " with "delete "
        - Arista EOS: prefix with "no "

        [CURSOR IMPLEMENTS full negate logic per vendor]
        """
        cmds = self.build(config, device_type)

        if device_type in ("cisco_xr", "cisco_ios", "arista_eos"):
            # Negate top-level stanzas
            negated = []
            for cmd in cmds:
                if cmd.startswith("router bgp") or cmd.startswith("router ospf"):
                    negated.append(f"no {cmd}")
            return negated

        elif device_type == "junos":
            return [cmd.replace("set ", "delete ", 1) for cmd in cmds if cmd.startswith("set ")]

        return [f"# Rollback not implemented for {device_type}"]
