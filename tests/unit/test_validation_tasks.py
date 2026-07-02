"""Unit tests for Celery validation tasks (tasks/validation.py)."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# ---------------------------------------------------------------------------
# validate_config_task
# ---------------------------------------------------------------------------

class TestValidateConfigTask:
    def test_valid_config_returns_valid_true(self):
        from tasks.validation import validate_config_task

        desired_state = {
            "bgp": {
                "local_asn": 65001,
                "router_id": "10.0.0.1",
                "neighbors": [{"neighbor_ip": "192.168.1.2", "remote_asn": 65002}],
            }
        }

        result = validate_config_task(
            device_id="dev-1",
            desired_state=desired_state,
            device_type="cisco_xr",
            run_preflight=False,
        )

        assert result["valid"] is True
        assert isinstance(result["errors"], list)
        assert isinstance(result["warnings"], list)
        assert result["preflight"] is None

    def test_invalid_config_returns_valid_false(self):
        from tasks.validation import validate_config_task

        desired_state = {
            "bgp": {
                "local_asn": -1,
                "neighbors": [{"neighbor_ip": "192.168.1.2", "remote_asn": 65002}],
            }
        }

        result = validate_config_task(
            device_id="dev-1",
            desired_state=desired_state,
            device_type="cisco_xr",
            run_preflight=False,
        )

        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_empty_config_returns_result_dict(self):
        from tasks.validation import validate_config_task

        result = validate_config_task(
            device_id="dev-empty",
            desired_state={},
            device_type="cisco_xr",
        )
        assert "valid" in result
        assert "errors" in result
        assert "warnings" in result

    def test_preflight_not_run_when_config_invalid(self):
        from tasks.validation import validate_config_task

        invalid_state = {
            "bgp": {
                "local_asn": -1,  # Invalid: negative ASN
                "neighbors": [{"neighbor_ip": "10.0.0.1", "remote_asn": 65002}],
            }
        }

        result = validate_config_task(
            device_id="dev-1",
            desired_state=invalid_state,
            run_preflight=True,  # Should NOT run if validation fails
        )
        assert result["preflight"] is None

    def test_preflight_run_when_valid_config_no_neighbors(self):
        from tasks.validation import validate_config_task

        valid_state = {
            "bgp": {
                "local_asn": 65001,
                "router_id": "10.0.0.1",
                "neighbors": [],  # No neighbors = nothing to preflight
            }
        }

        result = validate_config_task(
            device_id="dev-1",
            desired_state=valid_state,
            run_preflight=True,
        )
        assert result["valid"] is True
        # No neighbor IPs → preflight not triggered
        assert result["preflight"] is None

    def test_result_contains_all_expected_keys(self):
        from tasks.validation import validate_config_task

        result = validate_config_task(
            device_id="dev-test",
            desired_state={"bgp": {"local_asn": 65001, "neighbors": []}},
        )

        assert set(result.keys()) >= {"valid", "errors", "warnings", "preflight"}

    def test_device_type_none_does_not_crash(self):
        from tasks.validation import validate_config_task

        result = validate_config_task(
            device_id="dev-1",
            desired_state={"bgp": {"local_asn": 65001, "neighbors": []}},
            device_type=None,
        )
        assert "valid" in result

    def test_valid_ospf_config(self):
        from tasks.validation import validate_config_task

        result = validate_config_task(
            device_id="dev-ospf",
            desired_state={
                "ospf": {
                    "process_id": 1,
                    "router_id": "10.0.0.1",
                    "areas": [{"area_id": "0", "networks": ["10.0.0.0/8"]}],
                }
            },
        )
        assert result["valid"] is True


# ---------------------------------------------------------------------------
# validate_batch_task
# ---------------------------------------------------------------------------

class TestValidateBatchTask:
    def test_batch_all_valid(self):
        from tasks.validation import validate_batch_task

        validations = [
            {
                "device_id": "dev-a",
                "desired_state": {
                    "bgp": {"local_asn": 65001, "router_id": "10.0.0.1", "neighbors": []}
                },
                "device_type": "cisco_xr",
            },
            {
                "device_id": "dev-b",
                "desired_state": {
                    "bgp": {"local_asn": 65002, "router_id": "10.0.0.2", "neighbors": []}
                },
                "device_type": "cisco_ios",
            },
        ]

        results = validate_batch_task(validations=validations, user_id="admin")

        assert len(results) == 2
        assert all(r["valid"] is True for r in results)
        assert results[0]["device_id"] == "dev-a"
        assert results[1]["device_id"] == "dev-b"

    def test_batch_mixed_valid_invalid(self):
        from tasks.validation import validate_batch_task

        validations = [
            {
                "device_id": "dev-good",
                "desired_state": {
                    "bgp": {"local_asn": 65001, "router_id": "10.0.0.1", "neighbors": []}
                },
            },
            {
                "device_id": "dev-bad",
                "desired_state": {
                    "bgp": {"local_asn": -1, "neighbors": []}  # Invalid ASN
                },
            },
        ]

        results = validate_batch_task(validations=validations)

        assert len(results) == 2
        good = next(r for r in results if r["device_id"] == "dev-good")
        bad = next(r for r in results if r["device_id"] == "dev-bad")
        assert good["valid"] is True
        assert bad["valid"] is False

    def test_batch_empty_list(self):
        from tasks.validation import validate_batch_task

        results = validate_batch_task(validations=[])
        assert results == []

    def test_batch_handles_exception_per_item(self):
        from tasks.validation import validate_batch_task

        validations = [
            {"device_id": "dev-err", "desired_state": None},  # None will cause issues
        ]

        results = validate_batch_task(validations=validations)
        assert len(results) == 1
        assert results[0]["device_id"] == "dev-err"
        # Should not crash, returns error entry

    def test_batch_result_has_required_keys(self):
        from tasks.validation import validate_batch_task

        validations = [
            {
                "device_id": "dev-1",
                "desired_state": {"bgp": {"local_asn": 65001, "neighbors": []}},
            }
        ]

        results = validate_batch_task(validations=validations)
        assert len(results) == 1
        r = results[0]
        assert "device_id" in r
        assert "valid" in r
        assert "errors" in r
        assert "warnings" in r


# ---------------------------------------------------------------------------
# drift_detection_task
# ---------------------------------------------------------------------------

class TestDriftDetectionTask:
    def test_drift_task_exists_and_is_callable(self):
        from tasks.validation import drift_detection_task
        assert callable(drift_detection_task)

    def test_drift_task_returns_not_implemented(self):
        from tasks.validation import drift_detection_task

        result = drift_detection_task(device_id="dev-1")
        assert isinstance(result, dict)
        assert result["device_id"] == "dev-1"
        assert "status" in result
