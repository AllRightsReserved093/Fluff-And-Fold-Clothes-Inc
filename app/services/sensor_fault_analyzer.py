# Detect sensor faults in periodic reports with explicit prototype thresholds.

from laundry_contracts.contracts import (
    DryerErrorResolutionReport,
    DryerPeriodicReport,
    ErrorResolutionReport,
    OperationState,
    PeriodicReport,
    WasherErrorResolutionReport,
    WasherPeriodicReport,
)
from laundry_contracts.fault_codes import DiagnosticCode


# Prototype thresholds must be replaced with manufacturer-specific values later.
MAX_VIBRATION = 10.0
MAX_WASHER_WATER_TEMPERATURE = 80.0
MAX_DRYER_AIR_TEMPERATURE = 90.0
MIN_DRYER_AIR_FLOW_SPEED = 0.5

SENSOR_FAULT_ERROR_CODES = {
    DiagnosticCode.EXCESSIVE_VIBRATION.value,
    DiagnosticCode.WASHER_WATER_TEMPERATURE_HIGH.value,
    DiagnosticCode.DRYER_AIR_TEMPERATURE_HIGH.value,
    DiagnosticCode.DRYER_AIR_FLOW_LOW.value,
}


# Return the active sensor fault codes and messages for one complete report.
def detect_sensor_faults(report: PeriodicReport | ErrorResolutionReport) -> dict[str, str]:
    detected_faults: dict[str, str] = {}

    if report.general_sensor_readings.vibration > MAX_VIBRATION:
        detected_faults[DiagnosticCode.EXCESSIVE_VIBRATION.value] = f"Vibration exceeds {MAX_VIBRATION} m/s^2"

    if isinstance(report, (WasherPeriodicReport, WasherErrorResolutionReport)):
        if report.special_sensor_readings.water_temperature > MAX_WASHER_WATER_TEMPERATURE:
            detected_faults[DiagnosticCode.WASHER_WATER_TEMPERATURE_HIGH.value] = f"Water temperature exceeds {MAX_WASHER_WATER_TEMPERATURE} C"

    if isinstance(report, (DryerPeriodicReport, DryerErrorResolutionReport)):
        if report.special_sensor_readings.air_temperature > MAX_DRYER_AIR_TEMPERATURE:
            detected_faults[DiagnosticCode.DRYER_AIR_TEMPERATURE_HIGH.value] = f"Air temperature exceeds {MAX_DRYER_AIR_TEMPERATURE} C"
        if report.operation_state is OperationState.RUNNING and report.special_sensor_readings.air_flow_speed < MIN_DRYER_AIR_FLOW_SPEED:
            detected_faults[DiagnosticCode.DRYER_AIR_FLOW_LOW.value] = f"Air flow speed is below {MIN_DRYER_AIR_FLOW_SPEED} m/s while running"

    return detected_faults
