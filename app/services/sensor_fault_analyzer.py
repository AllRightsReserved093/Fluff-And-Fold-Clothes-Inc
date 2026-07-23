# Detect sensor faults in periodic reports with explicit prototype thresholds.
# 使用明确的原型阈值检测周期报告中的传感器故障。

from laundry_contracts.contracts import (
    DryerErrorResolutionReport,
    DryerPeriodicReport,
    ErrorResolutionReport,
    OperationState,
    PeriodicReport,
    WasherErrorResolutionReport,
    WasherPeriodicReport,
)


# Prototype thresholds must be replaced with manufacturer-specific values later.
# 这些原型阈值后续必须替换为设备制造商提供的实际数值。
MAX_VIBRATION = 10.0
MAX_WASHER_WATER_TEMPERATURE = 80.0
MAX_DRYER_AIR_TEMPERATURE = 90.0
MIN_DRYER_AIR_FLOW_SPEED = 0.5

SENSOR_FAULT_ERROR_CODES = {
    "excessive_vibration",
    "door_unlocked_while_running",
    "washer_water_temperature_high",
    "dryer_air_temperature_high",
    "dryer_air_flow_low",
}


# Return the active sensor fault codes and messages for one complete report.
# 返回一份完整报告中当前存在的传感器故障代码与消息。
def detect_sensor_faults(report: PeriodicReport | ErrorResolutionReport) -> dict[str, str]:
    detected_faults: dict[str, str] = {}

    if report.general_sensor_readings.vibration > MAX_VIBRATION:
        detected_faults["excessive_vibration"] = f"Vibration exceeds {MAX_VIBRATION} m/s^2"

    if report.operation_state is OperationState.RUNNING and not report.general_sensor_readings.door_locked:
        detected_faults["door_unlocked_while_running"] = "Machine door is not locked while running"

    if isinstance(report, (WasherPeriodicReport, WasherErrorResolutionReport)):
        if report.special_sensor_readings.water_temperature > MAX_WASHER_WATER_TEMPERATURE:
            detected_faults["washer_water_temperature_high"] = f"Water temperature exceeds {MAX_WASHER_WATER_TEMPERATURE} C"

    if isinstance(report, (DryerPeriodicReport, DryerErrorResolutionReport)):
        if report.special_sensor_readings.air_temperature > MAX_DRYER_AIR_TEMPERATURE:
            detected_faults["dryer_air_temperature_high"] = f"Air temperature exceeds {MAX_DRYER_AIR_TEMPERATURE} C"
        if report.operation_state is OperationState.RUNNING and report.special_sensor_readings.air_flow_speed < MIN_DRYER_AIR_FLOW_SPEED:
            detected_faults["dryer_air_flow_low"] = f"Air flow speed is below {MIN_DRYER_AIR_FLOW_SPEED} m/s while running"

    return detected_faults
