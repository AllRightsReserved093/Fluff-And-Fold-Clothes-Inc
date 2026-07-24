# Define the shared executable diagnostic code catalog.

from dataclasses import dataclass
from enum import StrEnum, unique


# Enumerate every diagnostic code accepted by the system.
@unique
class DiagnosticCode(StrEnum):
    EXCESSIVE_VIBRATION = "W1001"
    DOOR_INTERLOCK_LOST = "F1101"
    WASHER_WATER_TEMPERATURE_HIGH = "W2101"
    DRYER_AIR_TEMPERATURE_HIGH = "W3101"
    DRYER_AIR_FLOW_LOW = "W3201"
    DRYER_OVERTEMPERATURE_TRIP = "F3102"
    DEVICE_COMMUNICATION_LOST = "S8001"
    STATE_REPORT_GAP_DETECTED = "D9001"
    STATE_SEQUENCE_MISMATCH = "D9002"


# Classify diagnostics by their lifecycle and operational meaning.
@unique
class DiagnosticKind(StrEnum):
    WARNING = "warning"
    FAULT = "fault"
    SYSTEM_CONDITION = "system_condition"
    DATA_EVENT = "data_event"


# Rank the operational impact of a diagnostic.
@unique
class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Identify whether the device or server owns diagnostic detection.
@unique
class DetectionAuthority(StrEnum):
    DEVICE = "device"
    SERVER = "server"


# Enumerate the machine action associated with a diagnostic.
@unique
class EquipmentAction(StrEnum):
    NONE = "none"
    CONTROLLED_STOP = "controlled_stop"
    HEATING_OFF_AND_STOP = "heating_off_and_stop"


# Describe the stable behavior attached to one diagnostic code.
@dataclass(frozen=True)
class DiagnosticDefinition:
    kind: DiagnosticKind
    severity: Severity
    detection_authority: DetectionAuthority
    equipment_action: EquipmentAction
    latched: bool
    ack_required: bool
    reset_required: bool


DIAGNOSTIC_DEFINITIONS: dict[DiagnosticCode, DiagnosticDefinition] = {
    DiagnosticCode.EXCESSIVE_VIBRATION: DiagnosticDefinition(
        kind=DiagnosticKind.WARNING,
        severity=Severity.MEDIUM,
        detection_authority=DetectionAuthority.SERVER,
        equipment_action=EquipmentAction.NONE,
        latched=False,
        ack_required=True,
        reset_required=False,
    ),
    DiagnosticCode.DOOR_INTERLOCK_LOST: DiagnosticDefinition(
        kind=DiagnosticKind.FAULT,
        severity=Severity.CRITICAL,
        detection_authority=DetectionAuthority.DEVICE,
        equipment_action=EquipmentAction.CONTROLLED_STOP,
        latched=True,
        ack_required=True,
        reset_required=True,
    ),
    DiagnosticCode.WASHER_WATER_TEMPERATURE_HIGH: DiagnosticDefinition(
        kind=DiagnosticKind.WARNING,
        severity=Severity.MEDIUM,
        detection_authority=DetectionAuthority.SERVER,
        equipment_action=EquipmentAction.NONE,
        latched=False,
        ack_required=True,
        reset_required=False,
    ),
    DiagnosticCode.DRYER_AIR_TEMPERATURE_HIGH: DiagnosticDefinition(
        kind=DiagnosticKind.WARNING,
        severity=Severity.HIGH,
        detection_authority=DetectionAuthority.SERVER,
        equipment_action=EquipmentAction.NONE,
        latched=False,
        ack_required=True,
        reset_required=False,
    ),
    DiagnosticCode.DRYER_AIR_FLOW_LOW: DiagnosticDefinition(
        kind=DiagnosticKind.WARNING,
        severity=Severity.MEDIUM,
        detection_authority=DetectionAuthority.SERVER,
        equipment_action=EquipmentAction.NONE,
        latched=False,
        ack_required=True,
        reset_required=False,
    ),
    DiagnosticCode.DRYER_OVERTEMPERATURE_TRIP: DiagnosticDefinition(
        kind=DiagnosticKind.FAULT,
        severity=Severity.CRITICAL,
        detection_authority=DetectionAuthority.DEVICE,
        equipment_action=EquipmentAction.HEATING_OFF_AND_STOP,
        latched=True,
        ack_required=True,
        reset_required=True,
    ),
    DiagnosticCode.DEVICE_COMMUNICATION_LOST: DiagnosticDefinition(
        kind=DiagnosticKind.SYSTEM_CONDITION,
        severity=Severity.HIGH,
        detection_authority=DetectionAuthority.SERVER,
        equipment_action=EquipmentAction.NONE,
        latched=False,
        ack_required=True,
        reset_required=False,
    ),
    DiagnosticCode.STATE_REPORT_GAP_DETECTED: DiagnosticDefinition(
        kind=DiagnosticKind.DATA_EVENT,
        severity=Severity.LOW,
        detection_authority=DetectionAuthority.SERVER,
        equipment_action=EquipmentAction.NONE,
        latched=False,
        ack_required=False,
        reset_required=False,
    ),
    DiagnosticCode.STATE_SEQUENCE_MISMATCH: DiagnosticDefinition(
        kind=DiagnosticKind.DATA_EVENT,
        severity=Severity.MEDIUM,
        detection_authority=DetectionAuthority.SERVER,
        equipment_action=EquipmentAction.NONE,
        latched=False,
        ack_required=False,
        reset_required=False,
    ),
}
