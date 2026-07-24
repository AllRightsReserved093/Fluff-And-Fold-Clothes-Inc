# Verify pure periodic sensor fault detection rules.

from datetime import UTC, datetime

from app.services.sensor_fault_analyzer import detect_sensor_faults
from laundry_contracts.contracts import (
    DryerCyclePhase,
    DryerPeriodicReport,
    MachineType,
    OperationState,
    WasherCyclePhase,
    WasherPeriodicReport,
)
from laundry_contracts.fault_codes import DiagnosticCode


def test_washer_analyzer_detects_sensor_warnings() -> None:
    report = WasherPeriodicReport(
        machine_id="washer-01",
        machine_type=MachineType.WASHER,
        report_id="washer-fault-01",
        recorded_at=datetime.now(UTC),
        operation_state=OperationState.RUNNING,
        cycle_stage=WasherCyclePhase.WASHING,
        general_sensor_readings={"vibration": 10.1, "door_locked": False},
        special_sensor_readings={"water_level": 50.0, "water_temperature": 80.1},
    )

    detected_faults = detect_sensor_faults(report)

    assert set(detected_faults) == {
        DiagnosticCode.EXCESSIVE_VIBRATION.value,
        DiagnosticCode.WASHER_WATER_TEMPERATURE_HIGH.value,
    }


def test_dryer_analyzer_detects_temperature_and_air_flow_faults() -> None:
    report = DryerPeriodicReport(
        machine_id="dryer-01",
        machine_type=MachineType.DRYER,
        report_id="dryer-fault-01",
        recorded_at=datetime.now(UTC),
        operation_state=OperationState.RUNNING,
        cycle_stage=DryerCyclePhase.DRYING,
        general_sensor_readings={"vibration": 0.1, "door_locked": True},
        special_sensor_readings={"air_temperature": 90.1, "air_flow_speed": 0.4, "moisture": 25.0},
    )

    detected_faults = detect_sensor_faults(report)

    assert set(detected_faults) == {
        DiagnosticCode.DRYER_AIR_TEMPERATURE_HIGH.value,
        DiagnosticCode.DRYER_AIR_FLOW_LOW.value,
    }


def test_idle_machine_does_not_trigger_running_only_faults() -> None:
    report = DryerPeriodicReport(
        machine_id="dryer-01",
        machine_type=MachineType.DRYER,
        report_id="dryer-idle-01",
        recorded_at=datetime.now(UTC),
        operation_state=OperationState.IDLE,
        cycle_stage=None,
        general_sensor_readings={"vibration": 0.1, "door_locked": False},
        special_sensor_readings={"air_temperature": 40.0, "air_flow_speed": 0.0, "moisture": 0.0},
    )

    assert detect_sensor_faults(report) == {}
