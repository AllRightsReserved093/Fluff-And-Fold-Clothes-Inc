# Define shared wire data types and pure validation helpers.

from datetime import UTC, datetime
import enum
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# --------- Shared Validation Types ---------

Identifier: TypeAlias = Annotated[str, Field(min_length=1, max_length=128)]

MessageText: TypeAlias = Annotated[str, Field(min_length=1, max_length=1_024)]

ErrorCode: TypeAlias = Annotated[str, Field(min_length=1, max_length=128)]

FiniteFloat: TypeAlias = Annotated[float, Field(allow_inf_nan=False)]

NonNegativeFiniteFloat: TypeAlias = Annotated[float, Field(ge=0, allow_inf_nan=False)]

Percentage: TypeAlias = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]


# Reject unknown fields while preserving normal JSON parsing behavior.
class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )


# Normalize one timezone-aware datetime to UTC.
def normalize_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must include timezone information")

    return value.astimezone(UTC)


# --------- Enumerations ---------


# Enumerate the operational states shared by all machine types.
class OperationState(str, enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETE = "complete"
    FAULTED = "faulted"

# Enumerate the machine types supported by the system.
class MachineType(str, enum.Enum):
    WASHER = "washer"
    DRYER = "dryer"

# Enumerate the cycle phases reported by washers.
class WasherCyclePhase(str, enum.Enum):
    FILLING = "filling"
    WASHING = "washing"
    DRAINING = "draining"
    SPINNING = "spinning"

# Enumerate the cycle phases reported by dryers.
class DryerCyclePhase(str, enum.Enum):
    HEATING = "heating"
    DRYING = "drying"
    COOLING = "cooling"


# Identify the component that originally detected an error.
class ErrorSource(str, enum.Enum):
    DEVICE = "device"
    HEARTBEAT_MONITOR = "heartbeat_monitor"
    ANALYTICS = "analytics"


# Identify the source used to create a machine state event.
class StateEventSource(str, enum.Enum):
    CHANGE_OF_STATE_REPORT = "change_of_state_report"
    PERIODIC_RECONCILIATION = "periodic_reconciliation"
    ERROR_REPORT = "error_report"
    ANALYTICS = "analytics"


# Describe the outcome of processing one device report.
class ReportProcessingResult(enum.Enum):
    ACCEPTED = enum.auto()
    DUPLICATE = enum.auto()
    NOT_FOUND = enum.auto()

# --------- Sensor Readings ---------

# Define sensor readings shared by washers and dryers.
class GeneralSensorReadings(ContractModel):
    vibration: NonNegativeFiniteFloat = Field(description="Vibration acceleration in meters per second squared.")
    door_locked: bool


# Define readings produced only by washers.
class WasherSensorReadings(ContractModel):
    water_level: Percentage = Field(description="Water level as a percentage from 0 to 100.")
    water_temperature: FiniteFloat = Field(description="Water temperature in degrees Celsius.")


# Define readings produced only by dryers.
class DryerSensorReadings(ContractModel):
    air_temperature: FiniteFloat = Field(description="Air temperature in degrees Celsius.")
    # Air speed at the vent, can cause over heating if the vent is blocked
    air_flow_speed: NonNegativeFiniteFloat = Field(description="Air flow speed in meters per second.")
    moisture: Percentage = Field(description="Moisture as a percentage from 0 to 100.",)

# --------- Machine Reports ---------

# Common envelope for one device event.
class BaseMachineReport(ContractModel):
    machine_id: Identifier
    machine_type: MachineType
    report_id: Identifier
    recorded_at: AwareDatetime # Device-recorded event time.

    # Normalize the device event timestamp to UTC.
    @field_validator("recorded_at")
    @classmethod
    def normalize_recorded_at(cls, recorded_at: datetime) -> datetime:
        return normalize_to_utc(recorded_at)

# Define state-transition fields shared by washer and dryer reports.
class BaseChangeOfStateReport(BaseMachineReport):
    previous_operation_state: OperationState
    new_operation_state: OperationState
    reason: MessageText | None = None


# Define a washer state-change report.
class WasherChangeOfStateReport(BaseChangeOfStateReport):
    machine_type: Literal[MachineType.WASHER]
    previous_cycle_stage: WasherCyclePhase | None
    new_cycle_stage: WasherCyclePhase | None


# Define a dryer state-change report.
class DryerChangeOfStateReport(BaseChangeOfStateReport):
    machine_type: Literal[MachineType.DRYER]
    previous_cycle_stage: DryerCyclePhase | None
    new_cycle_stage: DryerCyclePhase | None


ChangeOfStateReport: TypeAlias = Annotated[
    WasherChangeOfStateReport | DryerChangeOfStateReport,
    Field(discriminator="machine_type"),
]

# Define fields shared by all periodic sensor reports.
class BasePeriodicReport(BaseMachineReport):
    operation_state: OperationState
    general_sensor_readings: GeneralSensorReadings


# Define one periodic washer report.
class WasherPeriodicReport(BasePeriodicReport):
    machine_type: Literal[MachineType.WASHER]
    cycle_stage: WasherCyclePhase | None
    special_sensor_readings: WasherSensorReadings


# Define one periodic dryer report.
class DryerPeriodicReport(BasePeriodicReport):
    machine_type: Literal[MachineType.DRYER]
    cycle_stage: DryerCyclePhase | None
    special_sensor_readings: DryerSensorReadings


# Select the report branch in O(1) from machine_type.
PeriodicReport: TypeAlias = Annotated[
    WasherPeriodicReport | DryerPeriodicReport,
    Field(discriminator="machine_type"),
]


# Define fields shared by all device error reports.
class BaseErrorReport(BaseMachineReport):
    error_id: Identifier
    error_code: ErrorCode
    error_message: MessageText | None = None
    error_source: ErrorSource
    
    general_sensor_readings: GeneralSensorReadings

    change_of_state: bool = False
    change_of_state_report: ChangeOfStateReport | None = None


# Define one washer error report.
class WasherErrorReport(BaseErrorReport):
    machine_type: Literal[MachineType.WASHER]
    special_sensor_readings: WasherSensorReadings


# Define one dryer error report.
class DryerErrorReport(BaseErrorReport):
    machine_type: Literal[MachineType.DRYER]
    special_sensor_readings: DryerSensorReadings


ErrorReport: TypeAlias = Annotated[
    WasherErrorReport | DryerErrorReport,
    Field(discriminator="machine_type"),
]


# Resolve an existing error
class BaseErrorResolutionReport(BaseMachineReport):
    error_id: Identifier
    resolution_message: MessageText | None = None
    operation_state: OperationState
    general_sensor_readings: GeneralSensorReadings


# Define one washer error-resolution report.
class WasherErrorResolutionReport(BaseErrorResolutionReport):
    machine_type: Literal[MachineType.WASHER]
    cycle_stage: WasherCyclePhase | None
    special_sensor_readings: WasherSensorReadings


# Define one dryer error-resolution report.
class DryerErrorResolutionReport(BaseErrorResolutionReport):
    machine_type: Literal[MachineType.DRYER]
    cycle_stage: DryerCyclePhase | None
    special_sensor_readings: DryerSensorReadings


ErrorResolutionReport: TypeAlias = Annotated[
    WasherErrorResolutionReport | DryerErrorResolutionReport,
    Field(discriminator="machine_type"),
]

# --------- Registration ---------

# Define the payload used to register a machine.
class RegistrationRequest(ContractModel):
    machine_id: Identifier
    machine_type: MachineType
    registered_at: AwareDatetime

    # Normalize registration timestamps to UTC after timezone validation.
    @field_validator("registered_at")
    @classmethod
    def normalize_registered_at(
        cls,
        registered_at: datetime,
    ) -> datetime:
        return normalize_to_utc(registered_at)


# Define the payload used to deregister a machine.
class DeregistrationRequest(ContractModel):
    machine_id: Identifier
    deregistered_at: AwareDatetime
    reason: MessageText | None = None

    # Normalize the deregistration timestamp to UTC.
    @field_validator("deregistered_at")
    @classmethod
    def normalize_deregistered_at(
        cls,
        deregistered_at: datetime,
    ) -> datetime:
        return normalize_to_utc(deregistered_at)


# --------- API Responses ---------

# Define the timestamp shared by successful API responses.
class BaseAcceptedResponse(ContractModel):
    accepted_at: AwareDatetime

    # Normalize the server acceptance timestamp to UTC.
    @field_validator("accepted_at")
    @classmethod
    def normalize_accepted_at(
        cls,
        accepted_at: datetime,
    ) -> datetime:
        return normalize_to_utc(accepted_at)


# Confirm that a machine registration was accepted.
class RegistrationResponse(BaseAcceptedResponse):
    machine_id: Identifier
    machine_type: MachineType


# Confirm that a machine deregistration was accepted.
class DeregistrationResponse(BaseAcceptedResponse):
    machine_id: Identifier


# Confirm whether a device report was newly accepted or duplicated.
class ReportAcceptedResponse(BaseAcceptedResponse):
    machine_id: Identifier
    report_id: Identifier
    is_duplicate: bool = False


# Confirm that an operator acknowledged a fault.
class FaultAcknowledgementResponse(ContractModel):
    machine_id: Identifier
    error_id: Identifier
    is_acknowledged: Literal[True]


# Define the optional message supplied during manual fault resolution.
class FaultResolutionRequest(ContractModel):
    resolution_message: MessageText | None = None


# Confirm that an operator manually resolved a fault.
class FaultResolutionResponse(ContractModel):
    machine_id: Identifier
    error_id: Identifier
    is_resolved: Literal[True]


# --------- Query Responses ---------

# Describe the most recent sensor values held in memory for one machine.
class LatestSensorReading(ContractModel):
    recorded_at: AwareDatetime
    general_readings: GeneralSensorReadings
    special_readings: WasherSensorReadings | DryerSensorReadings

    # Normalize the latest reading timestamp to UTC.
    @field_validator("recorded_at")
    @classmethod
    def normalize_recorded_at(cls, recorded_at: datetime) -> datetime:
        return normalize_to_utc(recorded_at)


# Describe the current backend state exposed for one machine.
class MachineStatusResponse(ContractModel):
    machine_id: Identifier
    machine_type: MachineType
    is_registered: bool
    is_online: bool
    operation_state: OperationState | None
    cycle_stage: str | None
    registered_at: datetime | None
    last_online: datetime | None
    recorded_at: datetime | None
    latest_reading: LatestSensorReading | None = None


# Describe one persisted sensor reading.
class SensorReadingResponse(ContractModel):
    reading_id: int
    machine_id: Identifier
    report_id: Identifier
    recorded_at: datetime
    received_at: datetime
    operation_state: OperationState | None
    cycle_stage: str | None
    general_readings: dict[str, Any]
    special_readings: dict[str, Any]


# Describe one immutable data-quality event.
class DataEventResponse(ContractModel):
    data_event_id: int
    machine_id: Identifier
    report_id: Identifier
    event_code: ErrorCode
    event_message: MessageText
    event_details: dict[str, Any]
    recorded_at: datetime
    received_at: datetime


# Describe one persisted machine state transition.
class MachineStateEventResponse(ContractModel):
    state_event_id: int
    machine_id: Identifier
    report_id: Identifier
    event_source: StateEventSource
    recorded_at: datetime
    received_at: datetime
    previous_operation_state: OperationState
    new_operation_state: OperationState
    previous_cycle_stage: str | None
    new_cycle_stage: str | None
    reason: MessageText | None


# Describe one persisted fault lifecycle record.
class FaultEventResponse(ContractModel):
    fault_event_id: int
    machine_id: Identifier
    report_id: Identifier | None
    error_id: Identifier
    error_code: ErrorCode
    error_message: MessageText | None
    error_source: ErrorSource
    is_acknowledged: bool
    raised_at: datetime
    resolved_at: datetime | None
    resolution_message: MessageText | None


# Return one fault together with the persisted history immediately preceding it.
class FaultContextResponse(ContractModel):
    fault: FaultEventResponse
    window_start: datetime
    window_end: datetime
    sensor_readings: list[SensorReadingResponse]
    state_events: list[MachineStateEventResponse]
    data_events: list[DataEventResponse]


# --------- Error State ---------

# Represent one server-side error record derived from device or server events.
class MachineError(ContractModel):
    error_id: Identifier
    error_code: ErrorCode
    error_message: MessageText | None = None
    error_source: ErrorSource
    is_acknowledged: bool = False
    raised_at: AwareDatetime
    resolved_at: AwareDatetime | None = None

    # Normalize error lifecycle timestamps to UTC.
    @field_validator("raised_at", "resolved_at")
    @classmethod
    def normalize_error_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None

        return normalize_to_utc(value)

    # Reject a resolution timestamp that predates the error.
    @model_validator(mode="after")
    def validate_resolution_time(self) -> "MachineError":
        if (self.resolved_at is not None and self.resolved_at < self.raised_at):
            raise ValueError("resolved_at cannot be earlier than raised_at")
        return self

    # Report whether the error has not yet been resolved.
    @property
    def is_active(self) -> bool:
        return self.resolved_at is None
