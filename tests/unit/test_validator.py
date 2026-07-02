"""Unit tests for ConfigValidator — Cowork provides structure, Cursor implements assertions."""

import pytest
from core.validator import ConfigValidator, ValidationResult


def test_validate_valid_bgp_config(valid_bgp_config):
    validator = ConfigValidator()
    result = validator.validate(valid_bgp_config)
    assert result.valid is True
    assert result.errors == []


def test_validate_invalid_asn(invalid_bgp_config):
    validator = ConfigValidator()
    result = validator.validate(invalid_bgp_config)
    assert result.valid is False
    assert any("ASN" in e or "asn" in e.lower() for e in result.errors)


def test_validate_loopback_neighbor():
    config = {
        "bgp": {
            "local_asn": 65001,
            "neighbors": [{"neighbor_ip": "127.0.0.1", "remote_asn": 65002}],
        }
    }
    result = ConfigValidator().validate(config)
    assert result.valid is False
    assert any("loopback" in e.lower() for e in result.errors)


def test_validate_policy_conflict(conflicting_policy_config):
    result = ConfigValidator().validate(conflicting_policy_config)
    assert result.valid is False
    assert any("conflict" in e.lower() for e in result.errors)


def test_validate_valid_ospf(valid_ospf_config):
    result = ConfigValidator().validate(valid_ospf_config)
    assert result.valid is True


def test_validate_invalid_ospf_area():
    config = {"ospf": {"areas": [{"area_id": "999.999.999.999"}]}}
    result = ConfigValidator().validate(config)
    assert result.valid is False


def test_validate_empty_config():
    result = ConfigValidator().validate({})
    assert result.valid is True  # Empty config is valid (no protocols configured)


def test_validate_non_dict_config():
    result = ConfigValidator().validate("not a dict")
    assert result.valid is False


def test_ibgp_warning():
    """Same local + remote ASN should produce a warning (not an error)."""
    config = {
        "bgp": {
            "local_asn": 65001,
            "neighbors": [{"neighbor_ip": "192.168.1.2", "remote_asn": 65001}],
        }
    }
    result = ConfigValidator().validate(config)
    assert result.valid is True  # iBGP is valid
    assert len(result.warnings) > 0


def test_duplicate_bgp_neighbor():
    config = {
        "bgp": {
            "local_asn": 65001,
            "neighbors": [
                {"neighbor_ip": "192.168.1.2", "remote_asn": 65002},
                {"neighbor_ip": "192.168.1.2", "remote_asn": 65003},  # duplicate IP
            ],
        }
    }
    result = ConfigValidator().validate(config)
    assert result.valid is False
    assert any("duplicate" in e.lower() for e in result.errors)
