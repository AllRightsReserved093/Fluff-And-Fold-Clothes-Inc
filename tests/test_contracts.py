# Verify shared wire contracts and their structural validation rules.
# 验证共享传输契约及其结构校验规则。

from copy import deepcopy
from datetime import UTC, datetime
from math import nan

import pytest
from pydantic import TypeAdapter, ValidationError

from laundry_contracts.contracts import (
    ChangeOfStateReport,
    DeregistrationRequest,
    DryerPeriodicReport,
    ErrorReport,
    ErrorResolutionReport,
    ErrorSource,
    MachineError,
    PeriodicReport,
    RegistrationRequest,
    WasherChangeOfStateReport,
    WasherErrorReport,
    WasherPeriodicReport,
)


periodic_report_adapter = TypeAdapter(PeriodicReport)
change_report_adapter = TypeAdapter(ChangeOfStateReport)
error_report_adapter = TypeAdapter(ErrorReport)


def washer_periodic_payload() -> dict[str, object]:
    return {
        "machine_id": "washer-01",
        "machine_type": "washer",
        "report_id": "report-01",
        "recorded_at": "2026-07-20T12:00:00-07:00",
        "operation_state": "running",
        "cycle_stage": "washing",
        "general_sensor_readings": {
            "vibration": 1.2,
            "door_locked": True,
        },
        "special_sensor_readings": {
            "water_level": 50.0,
            "water_temperature": 40.0,
        },
    }


def test_periodic_report_selects_machine_specific_model() -> None:
    washer_report = periodic_report_adapter.validate_python(
        washer_periodic_payload()
    )
    dryer_payload = washer_periodic_payload()
    dryer_payload.update(
        {
            "machine_id": "dryer-01",
            "machine_type": "dryer",
            "cycle_stage": "drying",
            "special_sensor_readings": {
                "air_temperature": 55.0,
                "air_flow_speed": 2.5,
                "moisture": 25.0,
            },
        }
    )
    dryer_report = periodic_report_adapter.validate_python(
        dryer_payload
    )

    assert isinstance(washer_report, WasherPeriodicReport)
    assert isinstance(dryer_report, DryerPeriodicReport)
    assert washer_report.recorded_at.tzinfo is UTC


def test_periodic_report_rejects_cross_machine_payload() -> None:
    payload = washer_periodic_payload()
    payload["machine_type"] = "dryer"

    with pytest.raises(ValidationError):
        periodic_report_adapter.validate_python(payload)


def test_contracts_reject_unknown_fields_and_invalid_numbers() -> None:
    payload_with_extra = washer_periodic_payload()
    general_readings = payload_with_extra["general_sensor_readings"]
    assert isinstance(general_readings, dict)
    general_readings["unknown_sensor"] = 1

    with pytest.raises(ValidationError):
        periodic_report_adapter.validate_python(payload_with_extra)

    payload_with_nan = washer_periodic_payload()
    general_readings = payload_with_nan["general_sensor_readings"]
    assert isinstance(general_readings, dict)
    general_readings["vibration"] = nan

    with pytest.raises(ValidationError):
        periodic_report_adapter.validate_python(payload_with_nan)

    payload_with_bad_percentage = washer_periodic_payload()
    special_readings = payload_with_bad_percentage[
        "special_sensor_readings"
    ]
    assert isinstance(special_readings, dict)
    special_readings["water_level"] = 101

    with pytest.raises(ValidationError):
        periodic_report_adapter.validate_python(
            payload_with_bad_percentage
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("machine_id", "   "),
        ("report_id", ""),
    ],
)
def test_report_identifiers_are_validated(
    field_name: str,
    invalid_value: object,
) -> None:
    payload = washer_periodic_payload()
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError):
        periodic_report_adapter.validate_python(payload)


def test_change_report_rejects_dryer_phase_for_washer() -> None:
    payload = {
        "machine_id": "washer-01",
        "machine_type": "washer",
        "report_id": "report-02",
        "recorded_at": "2026-07-20T12:00:01-07:00",
        "previous_operation_state": "idle",
        "new_operation_state": "running",
        "previous_cycle_stage": None,
        "new_cycle_stage": "filling",
    }
    report = change_report_adapter.validate_python(payload)

    assert isinstance(report, WasherChangeOfStateReport)

    invalid_payload = deepcopy(payload)
    invalid_payload["new_cycle_stage"] = "drying"

    with pytest.raises(ValidationError):
        change_report_adapter.validate_python(invalid_payload)


def test_registration_and_deregistration_times_are_utc() -> None:
    registration = RegistrationRequest(
        machine_id="washer-01",
        machine_type="washer",
        registered_at="2026-07-20T12:00:00-07:00",
    )
    deregistration = DeregistrationRequest(
        machine_id="washer-01",
        deregistered_at="2026-07-20T13:00:00-07:00",
    )

    assert registration.registered_at.tzinfo is UTC
    assert deregistration.deregistered_at.tzinfo is UTC

    with pytest.raises(ValidationError):
        RegistrationRequest(
            machine_id="washer-01",
            machine_type="washer",
            registered_at="2026-07-20T12:00:00",
        )


def test_error_resolution_references_existing_error_only() -> None:
    resolution = ErrorResolutionReport(
        machine_id="washer-01",
        machine_type="washer",
        report_id="report-03",
        recorded_at=datetime.now(UTC),
        error_id="error-01",
        resolution_message="Door latch was reset",
    )

    assert resolution.error_id == "error-01"

    with pytest.raises(ValidationError):
        ErrorResolutionReport(
            machine_id="washer-01",
            machine_type="washer",
            report_id="report-03",
            recorded_at=datetime.now(UTC),
            error_id="error-01",
            error_code="door_fault",
        )


def test_error_report_rejects_cross_machine_sensor_payload() -> None:
    payload = washer_periodic_payload()
    payload.pop("operation_state")
    payload.pop("cycle_stage")
    payload.update(
        {
            "error_id": "error-01",
            "error_code": "door_fault",
            "error_message": "Door did not lock",
            "error_source": "device",
        }
    )
    report = error_report_adapter.validate_python(payload)

    assert isinstance(report, WasherErrorReport)

    payload["machine_type"] = "dryer"

    with pytest.raises(ValidationError):
        error_report_adapter.validate_python(payload)


def test_machine_error_tracks_active_and_resolved_lifecycle() -> None:
    active_error = MachineError(
        error_id="heartbeat-timeout-washer-01",
        error_code="heartbeat_timeout",
        error_message="No report received before the deadline",
        error_source=ErrorSource.HEARTBEAT_MONITOR,
        raised_at="2026-07-20T12:00:00-07:00",
    )
    resolved_error = active_error.model_copy(
        update={"resolved_at": datetime(2026, 7, 20, 20, 0, tzinfo=UTC)},
    )

    assert active_error.is_active
    assert not resolved_error.is_active

    with pytest.raises(ValidationError):
        MachineError(
            error_id="error-01",
            error_code="door_fault",
            error_source=ErrorSource.DEVICE,
            raised_at="2026-07-20T12:00:00Z",
            resolved_at="2026-07-20T11:59:59Z",
        )
