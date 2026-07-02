"""
Unit tests for ConfigValidator.

Phase 1: basic structure tests.
Phase 2: router_id, CIDR, timer, cross-protocol, pre-flight, device-compat tests.

All tests here run without a DB or network — pure unit tests.
"""

import pytest
from core.validator import ConfigValidator, ValidationResult, BGPValidationRule, OSPFValidationRule, CIDRValidationRule


# ---------------------------------------------------------------------------
# ValidationResult model
# ---------------------------------------------------------------------------

def test_validation_result_valid():
    r = ValidationResult(valid=True)
    assert r.valid is True
    assert r.errors == []
    assert r.warnings == []


def test_validation_result_with_errors():
    r = ValidationResult(valid=False, errors=["e1", "e2"], warnings=["w1"])
    assert r.valid is False
    assert len(r.errors) == 2
    assert len(r.warnings) == 1


# ---------------------------------------------------------------------------
# BGPValidationRule — unit tests
# ---------------------------------------------------------------------------

class TestBGPValidationRule:
    def test_valid_asn_private_16bit(self):
        assert BGPValidationRule.validate_asn(65001) == []

    def test_valid_asn_public(self):
        assert BGPValidationRule.validate_asn(100) == []

    def test_valid_asn_32bit(self):
        assert BGPValidationRule.validate_asn(4200000001) == []

    def test_invalid_asn_zero(self):
        errs = BGPValidationRule.validate_asn(0)
        assert len(errs) > 0

    def test_invalid_asn_too_large(self):
        errs = BGPValidationRule.validate_asn(4294967296)
        assert len(errs) > 0

    def test_invalid_asn_negative(self):
        errs = BGPValidationRule.validate_asn(-1)
        assert len(errs) > 0

    def test_valid_neighbor_ip(self):
        assert BGPValidationRule.validate_neighbor_ip("192.168.1.1") == []

    def test_invalid_neighbor_loopback(self):
        errs = BGPValidationRule.validate_neighbor_ip("127.0.0.1")
        assert len(errs) > 0
        assert any("loopback" in e.lower() for e in errs)

    def test_invalid_neighbor_not_ip(self):
        errs = BGPValidationRule.validate_neighbor_ip("not-an-ip")
        assert len(errs) > 0

    def test_invalid_neighbor_zero(self):
        errs = BGPValidationRule.validate_neighbor_ip("0.0.0.0")
        assert len(errs) > 0

    def test_ibgp_warning(self):
        warnings = BGPValidationRule.validate_local_remote_asn(65001, 65001)
        assert len(warnings) > 0
        assert any("ibgp" in w.lower() or "internal" in w.lower() for w in warnings)

    def test_ebgp_no_warning(self):
        warnings = BGPValidationRule.validate_local_remote_asn(65001, 65002)
        assert warnings == []

    def test_valid_router_id(self):
        errs = BGPValidationRule.validate_router_id("10.0.0.1")
        assert errs == []

    def test_invalid_router_id_zero(self):
        errs = BGPValidationRule.validate_router_id("0.0.0.0")
        assert len(errs) > 0

    def test_invalid_router_id_not_ip(self):
        errs = BGPValidationRule.validate_router_id("not-valid")
        assert len(errs) > 0

    def test_valid_timers(self):
        errs = BGPValidationRule.validate_timers(keepalive=60, hold_time=180)
        assert errs == []

    def test_invalid_timers_hold_too_low(self):
        errs = BGPValidationRule.validate_timers(keepalive=60, hold_time=100)
        assert len(errs) > 0
        assert any("rfc" in e.lower() or "hold" in e.lower() for e in errs)

    def test_timers_hold_zero_disabled(self):
        # hold_time=0 means keepalive disabled — valid
        errs = BGPValidationRule.validate_timers(keepalive=60, hold_time=0)
        assert errs == []


# ---------------------------------------------------------------------------
# OSPFValidationRule — unit tests
# ---------------------------------------------------------------------------

class TestOSPFValidationRule:
    def test_valid_area_backbone(self):
        assert OSPFValidationRule.validate_area_id("0.0.0.0") == []

    def test_valid_area_dotted(self):
        assert OSPFValidationRule.validate_area_id("0.0.0.1") == []

    def test_valid_area_integer(self):
        assert OSPFValidationRule.validate_area_id("1") == []

    def test_invalid_area_bad_octet(self):
        errs = OSPFValidationRule.validate_area_id("999.0.0.0")
        assert len(errs) > 0

    def test_invalid_area_too_many_octets(self):
        errs = OSPFValidationRule.validate_area_id("0.0.0.0.0")
        assert len(errs) > 0

    def test_invalid_area_string(self):
        errs = OSPFValidationRule.validate_area_id("backbone")
        assert len(errs) > 0

    def test_hello_dead_ok(self):
        warnings = OSPFValidationRule.validate_hello_interval(10, 40)
        assert warnings == []

    def test_hello_dead_too_short(self):
        warnings = OSPFValidationRule.validate_hello_interval(10, 20)
        assert len(warnings) > 0


# ---------------------------------------------------------------------------
# CIDRValidationRule — unit tests
# ---------------------------------------------------------------------------

class TestCIDRValidationRule:
    def test_valid_cidr(self):
        assert CIDRValidationRule.validate_prefix("10.0.0.0/8") == []

    def test_valid_cidr_host_bits(self):
        # strict=False normalises host bits — not an error
        assert CIDRValidationRule.validate_prefix("10.0.0.1/8") == []

    def test_invalid_cidr_garbage(self):
        errs = CIDRValidationRule.validate_prefix("not-a-prefix")
        assert len(errs) > 0

    def test_invalid_cidr_empty(self):
        errs = CIDRValidationRule.validate_prefix("")
        assert len(errs) > 0

    def test_loopback_prefix_flagged(self):
        errs = CIDRValidationRule.validate_prefix("127.0.0.0/8")
        assert len(errs) > 0

    def test_prefix_list_collects_all_errors(self):
        errs = CIDRValidationRule.validate_prefix_list(["bad1", "bad2", "10.0.0.0/8"])
        assert len(errs) == 2  # two bad, one good


# ---------------------------------------------------------------------------
# ConfigValidator.validate() — end-to-end unit tests
# ---------------------------------------------------------------------------

class TestConfigValidator:
    def setup_method(self):
        self.v = ConfigValidator()

    def test_empty_config_is_valid(self):
        r = self.v.validate({})
        assert r.valid is True

    def test_non_dict_invalid(self):
        r = self.v.validate("string")
        assert r.valid is False

    def test_valid_bgp(self, valid_bgp_config):
        r = self.v.validate(valid_bgp_config)
        assert r.valid is True
        assert r.errors == []

    def test_invalid_asn(self, invalid_bgp_config):
        r = self.v.validate(invalid_bgp_config)
        assert r.valid is False
        assert any("asn" in e.lower() for e in r.errors)

    def test_loopback_neighbor(self):
        r = self.v.validate({
            "bgp": {"local_asn": 65001, "neighbors": [{"neighbor_ip": "127.0.0.1", "remote_asn": 65002}]}
        })
        assert r.valid is False

    def test_duplicate_neighbor(self):
        r = self.v.validate({
            "bgp": {
                "local_asn": 65001,
                "neighbors": [
                    {"neighbor_ip": "192.168.1.2", "remote_asn": 65002},
                    {"neighbor_ip": "192.168.1.2", "remote_asn": 65003},
                ],
            }
        })
        assert r.valid is False
        assert any("duplicate" in e.lower() for e in r.errors)

    def test_policy_conflict(self, conflicting_policy_config):
        r = self.v.validate(conflicting_policy_config)
        assert r.valid is False
        assert any("conflict" in e.lower() for e in r.errors)

    def test_valid_ospf(self, valid_ospf_config):
        r = self.v.validate(valid_ospf_config)
        assert r.valid is True

    def test_duplicate_ospf_area(self):
        r = self.v.validate({
            "ospf": {
                "process_id": 1,
                "areas": [
                    {"area_id": "0.0.0.1"},
                    {"area_id": "0.0.0.1"},  # duplicate
                ],
            }
        })
        assert r.valid is False
        assert any("duplicate" in e.lower() for e in r.errors)

    def test_ospf_timer_warning(self):
        r = self.v.validate({
            "ospf": {
                "process_id": 1,
                "areas": [{"area_id": "0", "hello_interval": 10, "dead_interval": 20}],
            }
        })
        # Timer mismatch is a warning, not an error
        assert r.valid is True
        assert len(r.warnings) > 0

    def test_bgp_timer_violation(self):
        r = self.v.validate({
            "bgp": {
                "local_asn": 65001,
                "neighbors": [
                    {"neighbor_ip": "192.168.1.2", "remote_asn": 65002, "keepalive": 30, "hold_time": 60}
                ],
            }
        })
        assert r.valid is False

    def test_invalid_cidr_in_bgp_networks(self):
        r = self.v.validate({
            "bgp": {"local_asn": 65001, "neighbors": [], "networks": ["not-a-cidr"]}
        })
        assert r.valid is False

    def test_cross_protocol_router_id_mismatch_warning(self):
        r = self.v.validate({
            "bgp": {"local_asn": 65001, "router_id": "10.0.0.1", "neighbors": []},
            "ospf": {"process_id": 1, "router_id": "10.0.0.2", "areas": []},
        })
        assert r.valid is True  # mismatch is a warning only
        assert len(r.warnings) > 0

    def test_arista_md5_ospf_warning(self):
        r = self.v.validate(
            {"ospf": {"process_id": 1, "areas": [{"area_id": "0", "authentication": "md5"}]}},
            device_type="arista_eos",
        )
        assert r.valid is True  # just a warning
        assert any("arista" in w.lower() for w in r.warnings)

    def test_ibgp_produces_warning_not_error(self):
        r = self.v.validate({
            "bgp": {
                "local_asn": 65001,
                "neighbors": [{"neighbor_ip": "10.0.0.2", "remote_asn": 65001}],
            }
        })
        assert r.valid is True
        assert len(r.warnings) > 0
