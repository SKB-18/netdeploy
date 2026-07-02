"""
ConfigValidator — validates network configurations before deployment.

Cowork provides: class structure, rule stubs, validation pipeline.
Cursor implements: _validate_bgp, _validate_ospf, _check_policy_conflicts,
                   _check_device_compatibility
"""

import ipaddress
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ValidationResult(BaseModel):
    valid: bool
    errors: List[str] = []
    warnings: List[str] = []


class BGPValidationRule:
    """BGP neighbor configuration validation rules."""

    @staticmethod
    def validate_asn(asn: int) -> List[str]:
        """
        Rule: ASN must be in valid range 1-4294967295.
        Private 16-bit: 64512-65534
        Public 16-bit: 1-64511
        32-bit: up to 4294967295
        """
        errors = []
        if not isinstance(asn, int) or not (1 <= asn <= 4294967295):
            errors.append(f"Invalid ASN {asn}: must be 1-4294967295")
        return errors

    @staticmethod
    def validate_neighbor_ip(ip: str) -> List[str]:
        """
        Rule: BGP neighbor must be valid, non-loopback, non-reserved IPv4.
        """
        errors = []
        try:
            addr = ipaddress.IPv4Address(ip)
            if addr.is_loopback:
                errors.append(f"BGP neighbor {ip} is a loopback address")
            if addr.is_reserved:
                errors.append(f"BGP neighbor {ip} is a reserved address")
            if addr == ipaddress.IPv4Address("0.0.0.0"):
                errors.append(f"BGP neighbor {ip} is 0.0.0.0 — invalid")
        except (ipaddress.AddressValueError, ValueError):
            errors.append(f"BGP neighbor {ip!r} is not a valid IPv4 address")
        return errors

    @staticmethod
    def validate_local_remote_asn(local_asn: int, remote_asn: int) -> List[str]:
        """Warn if local == remote (iBGP, usually intentional but worth noting)."""
        warnings = []
        if local_asn == remote_asn:
            warnings.append(
                f"Local ASN {local_asn} == Remote ASN: this is iBGP (internal peering)"
            )
        return warnings


class OSPFValidationRule:
    """OSPF configuration validation rules."""

    @staticmethod
    def validate_area_id(area_id: str) -> List[str]:
        """
        Rule: OSPF area ID must be dotted-decimal (0.0.0.x) or integer 0-4294967295.
        Area 0 / 0.0.0.0 is the backbone.
        """
        errors = []
        try:
            if "." in str(area_id):
                parts = str(area_id).split(".")
                if len(parts) != 4:
                    errors.append(f"OSPF area {area_id!r} must be dotted-decimal (a.b.c.d)")
                    return errors
                for part in parts:
                    val = int(part)
                    if not (0 <= val <= 255):
                        errors.append(f"OSPF area {area_id!r} has octet out of range: {part}")
            else:
                val = int(area_id)
                if not (0 <= val <= 4294967295):
                    errors.append(f"OSPF area {area_id!r} is out of range 0-4294967295")
        except (ValueError, TypeError):
            errors.append(f"OSPF area {area_id!r} cannot be parsed as area ID")
        return errors

    @staticmethod
    def validate_hello_interval(hello: int, dead: int) -> List[str]:
        """Dead interval should be >= 4× hello interval."""
        warnings = []
        if dead < hello * 4:
            warnings.append(
                f"OSPF dead interval ({dead}s) is less than 4× hello ({hello}s) — "
                "adjacencies may flap"
            )
        return warnings


class ConfigValidator:
    """Main validation orchestrator for network device configurations."""

    def __init__(self):
        self.bgp_rules = BGPValidationRule()
        self.ospf_rules = OSPFValidationRule()

    def validate(
        self,
        device_config: Dict[str, Any],
        device_type: Optional[str] = None,
    ) -> ValidationResult:
        """
        Run full validation pipeline:

        1. Top-level schema sanity check
        2. BGP section checks
        3. OSPF section checks
        4. Policy conflict detection
        5. Device compatibility warnings

        Returns ValidationResult(valid, errors, warnings).
        """
        errors: List[str] = []
        warnings: List[str] = []

        if not isinstance(device_config, dict):
            return ValidationResult(valid=False, errors=["Config must be a JSON object"])

        # 2. BGP validation
        if "bgp" in device_config:
            bgp_errors, bgp_warnings = self._validate_bgp(device_config["bgp"])
            errors.extend(bgp_errors)
            warnings.extend(bgp_warnings)

        # 3. OSPF validation
        if "ospf" in device_config:
            ospf_errors, ospf_warnings = self._validate_ospf(device_config["ospf"])
            errors.extend(ospf_errors)
            warnings.extend(ospf_warnings)

        # 4. Policy conflicts
        conflict_errors = self._check_policy_conflicts(device_config)
        errors.extend(conflict_errors)

        # 5. Device compatibility
        compat_warnings = self._check_device_compatibility(device_config, device_type)
        warnings.extend(compat_warnings)

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def _validate_bgp(self, bgp_config: dict):
        """
        Validate BGP section.
        
        [CURSOR IMPLEMENTS full logic]
        Checks: local_asn range, neighbor IPs, duplicate neighbors, route policies.
        """
        errors: List[str] = []
        warnings: List[str] = []

        # local_asn check
        local_asn = bgp_config.get("local_asn")
        if local_asn is not None:
            errors.extend(self.bgp_rules.validate_asn(local_asn))

        # neighbor checks
        neighbors = bgp_config.get("neighbors", [])
        seen_ips = set()
        for neighbor in neighbors:
            ip = neighbor.get("neighbor_ip", "")
            remote_asn = neighbor.get("remote_asn")

            # Validate IP
            errors.extend(self.bgp_rules.validate_neighbor_ip(ip))

            # Validate remote ASN
            if remote_asn is not None:
                errors.extend(self.bgp_rules.validate_asn(remote_asn))

            # iBGP warning
            if local_asn and remote_asn:
                warnings.extend(self.bgp_rules.validate_local_remote_asn(local_asn, remote_asn))

            # Duplicate neighbor check
            if ip in seen_ips:
                errors.append(f"Duplicate BGP neighbor IP: {ip}")
            seen_ips.add(ip)

        return errors, warnings

    def _validate_ospf(self, ospf_config: dict):
        """
        Validate OSPF section.
        
        [CURSOR IMPLEMENTS full logic]
        Checks: area IDs, hello/dead timers, duplicate areas.
        """
        errors: List[str] = []
        warnings: List[str] = []

        areas = ospf_config.get("areas", [])
        seen_areas = set()

        for area in areas:
            area_id = area.get("area_id")
            if area_id is not None:
                errors.extend(self.ospf_rules.validate_area_id(str(area_id)))
                if area_id in seen_areas:
                    errors.append(f"Duplicate OSPF area: {area_id}")
                seen_areas.add(area_id)

            # Timer checks
            hello = area.get("hello_interval")
            dead = area.get("dead_interval")
            if hello and dead:
                warnings.extend(self.ospf_rules.validate_hello_interval(hello, dead))

        return errors, warnings

    def _check_policy_conflicts(self, config: dict) -> List[str]:
        """
        Detect contradictory route policies (e.g., permit + deny same prefix).
        
        [CURSOR IMPLEMENTS full logic]
        """
        errors: List[str] = []

        bgp = config.get("bgp", {})
        policies = bgp.get("route_policies", [])

        seen: Dict[str, str] = {}
        for policy in policies:
            prefix = policy.get("prefix")
            action = policy.get("action")
            if prefix and action:
                if prefix in seen and seen[prefix] != action:
                    errors.append(
                        f"Policy conflict on prefix {prefix}: "
                        f"both '{seen[prefix]}' and '{action}' actions defined"
                    )
                seen[prefix] = action

        return errors

    def _check_device_compatibility(
        self, config: dict, device_type: Optional[str]
    ) -> List[str]:
        """
        Check OS version / feature compatibility.
        
        [CURSOR IMPLEMENTS full logic]
        """
        warnings: List[str] = []

        if device_type is None:
            return warnings

        # Example: Arista EOS doesn't support certain OSPF auth types
        if device_type == "arista_eos":
            ospf = config.get("ospf", {})
            for area in ospf.get("areas", []):
                auth_type = area.get("authentication")
                if auth_type == "md5":
                    warnings.append(
                        "Arista EOS: MD5 OSPF authentication requires EOS 4.22+; verify OS version"
                    )

        return warnings
