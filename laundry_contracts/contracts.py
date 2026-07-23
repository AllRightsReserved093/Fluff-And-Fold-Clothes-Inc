# Define shared wire data types and pure validation helpers.
# 定义共享的传输数据类型与纯校验辅助函数。

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


# --------- Shared Validation Types ----------

Identifier: TypeAlias = Annotated[str, Field(min_length=1, max_length=128)]

MessageText: TypeAlias = Annotated[str, Field(min_length=1, max_length=1_024)]

ErrorCode: TypeAlias = Annotated[str, Field(min_length=1, max_length=128)]

FiniteFloat: TypeAlias = Annotated[float, Field(allow_inf_nan=False)]

NonNegativeFiniteFloat: TypeAlias = Annotated[float, Field(ge=0, allow_inf_nan=False)]

Percentage: TypeAlias = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]


# Reject unknown fields while preserving normal JSON parsing behavior.
# 拒绝未知字段，同时保留正常的 JSON 类型解析行为。
class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )


# Normalize one timezone-aware datetime to UTC.
# 将一个带时区的时间归一化为 UTC。
def normalize_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must include timezone information")

    return value.astimezone(UTC)


# --------- Enumerations ----------


class OperationState(str, enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETE = "complete"
    FAULTED = "faulted"

class MachineType(str, enum.Enum):
    WASHER = "washer"
    DRYER = "dryer"

class WasherCyclePhase(str, enum.Enum):
    FILLING = "filling"
    WASHING = "washing"
    DRAINING = "draining"
    SPINNING = "spinning"

class DryerCyclePhase(str, enum.Enum):
    HEATING = "heating"
    DRYING = "drying"
    COOLING = "cooling"


class ErrorSource(str, enum.Enum):
    DEVICE = "device"
    HEARTBEAT_MONITOR = "heartbeat_monitor"
    ANALYTICS = "analytics"


class StateEventSource(str, enum.Enum):
    CHANGE_OF_STATE_REPORT = "change_of_state_report"
    PERIODIC_RECONCILIATION = "periodic_reconciliation"
    ERROR_REPORT = "error_report"
    ANALYTICS = "analytics"


class MachineErrorCode(str, enum.Enum):
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"

# --------- Sensor Readings ----------

class GeneralSensorReadings(ContractModel):
    vibration: NonNegativeFiniteFloat = Field(description="Vibration acceleration in meters per second squared.")
    door_locked: bool


class WasherSensorReadings(ContractModel):
    water_level: Percentage = Field(description="Water level as a percentage from 0 to 100.")
    water_temperature: FiniteFloat = Field(description="Water temperature in degrees Celsius.")


class DryerSensorReadings(ContractModel):
    air_temperature: FiniteFloat = Field(description="Air temperature in degrees Celsius.")
    # Air speed at the vent, can cause over heating if the vent is blocked
    air_flow_speed: NonNegativeFiniteFloat = Field(description="Air flow speed in meters per second.")
    moisture: Percentage = Field(description="Moisture as a percentage from 0 to 100.",)

# --------- Machine Reports ----------

# Common envelope for one device event.
# 单次设备事件的公共信封结构。
class BaseMachineReport(ContractModel):
    machine_id: Identifier
    machine_type: MachineType
    report_id: Identifier
    recorded_at: AwareDatetime # Device-recorded event time.

    @field_validator("recorded_at")
    @classmethod
    def normalize_recorded_at(cls, recorded_at: datetime) -> datetime:
        return normalize_to_utc(recorded_at)

class BaseChangeOfStateReport(BaseMachineReport):
    previous_operation_state: OperationState
    new_operation_state: OperationState
    reason: MessageText | None = None


class WasherChangeOfStateReport(BaseChangeOfStateReport):
    machine_type: Literal[MachineType.WASHER]
    previous_cycle_stage: WasherCyclePhase | None
    new_cycle_stage: WasherCyclePhase | None


class DryerChangeOfStateReport(BaseChangeOfStateReport):
    machine_type: Literal[MachineType.DRYER]
    previous_cycle_stage: DryerCyclePhase | None
    new_cycle_stage: DryerCyclePhase | None


ChangeOfStateReport: TypeAlias = Annotated[
    WasherChangeOfStateReport | DryerChangeOfStateReport,
    Field(discriminator="machine_type"),
]

class BasePeriodicReport(BaseMachineReport):
    operation_state: OperationState
    general_sensor_readings: GeneralSensorReadings


class WasherPeriodicReport(BasePeriodicReport):
    machine_type: Literal[MachineType.WASHER]
    cycle_stage: WasherCyclePhase | None
    special_sensor_readings: WasherSensorReadings


class DryerPeriodicReport(BasePeriodicReport):
    machine_type: Literal[MachineType.DRYER]
    cycle_stage: DryerCyclePhase | None
    special_sensor_readings: DryerSensorReadings


# Select the report branch in O(1) from machine_type.
# 根据 machine_type 以 O(1) 选择报告分支。
PeriodicReport: TypeAlias = Annotated[
    WasherPeriodicReport | DryerPeriodicReport,
    Field(discriminator="machine_type"),
]


class BaseErrorReport(BaseMachineReport):
    error_id: Identifier
    error_code: ErrorCode
    error_message: MessageText | None = None
    error_source: ErrorSource
    
    general_sensor_readings: GeneralSensorReadings

    change_of_state: bool = False
    change_of_state_report: ChangeOfStateReport | None = None


class WasherErrorReport(BaseErrorReport):
    machine_type: Literal[MachineType.WASHER]
    special_sensor_readings: WasherSensorReadings


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


class WasherErrorResolutionReport(BaseErrorResolutionReport):
    machine_type: Literal[MachineType.WASHER]
    cycle_stage: WasherCyclePhase | None
    special_sensor_readings: WasherSensorReadings


class DryerErrorResolutionReport(BaseErrorResolutionReport):
    machine_type: Literal[MachineType.DRYER]
    cycle_stage: DryerCyclePhase | None
    special_sensor_readings: DryerSensorReadings


ErrorResolutionReport: TypeAlias = Annotated[
    WasherErrorResolutionReport | DryerErrorResolutionReport,
    Field(discriminator="machine_type"),
]

# --------- Registration ----------

class RegistrationRequest(ContractModel):
    machine_id: Identifier
    machine_type: MachineType
    registered_at: AwareDatetime

    # Normalize registration timestamps to UTC after timezone validation.
    # 校验时区后，将注册时间统一转换为 UTC。
    @field_validator("registered_at")
    @classmethod
    def normalize_registered_at(
        cls,
        registered_at: datetime,
    ) -> datetime:
        return normalize_to_utc(registered_at)


class DeregistrationRequest(ContractModel):
    machine_id: Identifier
    deregistered_at: AwareDatetime
    reason: MessageText | None = None

    @field_validator("deregistered_at")
    @classmethod
    def normalize_deregistered_at(
        cls,
        deregistered_at: datetime,
    ) -> datetime:
        return normalize_to_utc(deregistered_at)


class BaseAcceptedResponse(ContractModel):
    accepted_at: AwareDatetime

    @field_validator("accepted_at")
    @classmethod
    def normalize_accepted_at(
        cls,
        accepted_at: datetime,
    ) -> datetime:
        return normalize_to_utc(accepted_at)


class RegistrationResponse(BaseAcceptedResponse):
    machine_id: Identifier
    machine_type: MachineType


class DeregistrationResponse(BaseAcceptedResponse):
    machine_id: Identifier


class ReportAcceptedResponse(BaseAcceptedResponse):
    machine_id: Identifier
    report_id: Identifier
    is_duplicate: bool = False


class FaultAcknowledgementResponse(ContractModel):
    machine_id: Identifier
    error_id: Identifier
    is_acknowledged: Literal[True]


class FaultResolutionRequest(ContractModel):
    resolution_message: MessageText | None = None


class FaultResolutionResponse(ContractModel):
    machine_id: Identifier
    error_id: Identifier
    is_resolved: Literal[True]


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


# --------- Error State ----------

# Represent one server-side error record derived from device or server events.
# 表示由设备或服务器事件产生的一条服务端错误记录。
class MachineError(ContractModel):
    error_id: Identifier
    error_code: ErrorCode
    error_message: MessageText | None = None
    error_source: ErrorSource
    is_acknowledged: bool = False
    raised_at: AwareDatetime
    resolved_at: AwareDatetime | None = None

    @field_validator("raised_at", "resolved_at")
    @classmethod
    def normalize_error_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None

        return normalize_to_utc(value)

    @model_validator(mode="after")
    def validate_resolution_time(self) -> "MachineError":
        if (self.resolved_at is not None and self.resolved_at < self.raised_at):
            raise ValueError("resolved_at cannot be earlier than raised_at")
        return self

    @property
    def is_active(self) -> bool:
        return self.resolved_at is None
