"""
Celery tasks for asynchronous configuration validation.

Phase 2 addition: separates validation from deployment so Cursor can
run pre-flight checks independently (e.g. nightly drift detection,
CI/CD pipeline validation without deploying).

Cowork provides: task signatures + docstrings.
Cursor implements: task bodies.
"""

import logging
from typing import Any, Dict, List

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=10)
def validate_config_task(
    self,
    device_id: str,
    desired_state: Dict[str, Any],
    device_type: str = None,
    run_preflight: bool = False,
    user_id: str = "system",
) -> Dict[str, Any]:
    """
    Async task: validate a single device's desired config.

    Args:
        device_id:      Device UUID string (for audit logging)
        desired_state:  BGP/OSPF config dict
        device_type:    e.g. "cisco_xr" — used for compatibility checks
        run_preflight:  If True, ping-check BGP neighbor IPs before returning
        user_id:        For audit log

    Returns:
        {
            "valid": bool,
            "errors": [...],
            "warnings": [...],
            "preflight": {"reachable": [...], "unreachable": [...]} | None
        }

    Steps (Cursor implements):
    1. Instantiate ConfigValidator
    2. Call validator.validate(desired_state, device_type)
    3. If run_preflight and valid: call preflight_reachability() on neighbor IPs
    4. Write AuditLog entry (action=VALIDATE)
    5. Return combined result dict

    [CURSOR IMPLEMENTS]
    """
    logger.info(
        "validate_config_task: device=%s preflight=%s", device_id, run_preflight
    )
    try:
        from core.validator import ConfigValidator
        import asyncio

        validator = ConfigValidator()
        result = validator.validate(desired_state, device_type=device_type)

        output: Dict[str, Any] = {
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
            "preflight": None,
        }

        # Optional pre-flight reachability check
        if run_preflight and result.valid:
            neighbor_ips = [
                n.get("neighbor_ip")
                for n in desired_state.get("bgp", {}).get("neighbors", [])
                if n.get("neighbor_ip")
            ]
            if neighbor_ips:
                reachable, unreachable = asyncio.run(
                    validator.preflight_reachability(neighbor_ips)
                )
                output["preflight"] = {
                    "reachable": reachable,
                    "unreachable": unreachable,
                }
                if unreachable:
                    output["warnings"].extend(
                        [f"BGP neighbor {ip} is unreachable (ping failed)" for ip in unreachable]
                    )

        # Cursor: write AuditLog here
        return output

    except Exception as exc:
        logger.exception("validate_config_task failed: %s", exc)
        raise self.retry(exc=exc)


@celery_app.task
def validate_batch_task(
    validations: List[Dict[str, Any]],
    user_id: str = "system",
) -> List[Dict[str, Any]]:
    """
    Validate multiple device configs in one task (batch pre-deployment check).

    Args:
        validations: List of dicts, each with keys:
                     { device_id, desired_state, device_type }
        user_id:     For audit logging

    Returns:
        List of result dicts, one per device:
        [{ device_id, valid, errors, warnings }, ...]

    Steps (Cursor implements):
    1. For each item, call validate_config_task.apply() synchronously
    2. Collect results
    3. Return list

    [CURSOR IMPLEMENTS]
    """
    logger.info("validate_batch_task: %d devices", len(validations))
    results = []
    for item in validations:
        try:
            from core.validator import ConfigValidator
            validator = ConfigValidator()
            r = validator.validate(
                item.get("desired_state", {}),
                device_type=item.get("device_type"),
            )
            results.append({
                "device_id": item.get("device_id"),
                "valid": r.valid,
                "errors": r.errors,
                "warnings": r.warnings,
            })
        except Exception as exc:
            logger.exception("validate_batch_task error for %s: %s", item.get("device_id"), exc)
            results.append({
                "device_id": item.get("device_id"),
                "valid": False,
                "errors": [f"Validation task error: {exc}"],
                "warnings": [],
            })
    return results


@celery_app.task
def drift_detection_task(device_id: str):
    """
    Scheduled task: compare desired state (DB) vs running config (SSH).

    Sets Configuration.status = DRIFT if they differ, SYNCED if they match.

    [CURSOR IMPLEMENTS using SSHDevice + difflib]
    """
    logger.info("drift_detection_task: device=%s", device_id)
    # Cursor:
    # 1. Fetch device + latest Configuration from DB
    # 2. SSH to device → get_running_config()
    # 3. Compare desired_state vs running config
    # 4. Update Configuration.status = "SYNCED" | "DRIFT"
    # 5. Write AuditLog if drift detected
    return {"status": "not_implemented", "device_id": device_id}
