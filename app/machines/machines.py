# Represent the backend state of a registered laundry machine.
# 表示已注册洗衣设备在后端中的状态。

from datetime import UTC, datetime
from uuid import uuid4

from laundry_contracts.contracts import (
    DryerSensorReadings,
    DryerCyclePhase,
    ErrorSource,
    GeneralSensorReadings,
    LatestSensorReading,
    MachineError,
    MachineType,
    OperationState,
    WasherSensorReadings,
    WasherCyclePhase,
)
from laundry_contracts.fault_codes import DiagnosticCode

class Machine:

    machine_id: str
    machine_type: MachineType

    is_online: bool
    operation_state: OperationState | None
    cycle_stage: WasherCyclePhase | DryerCyclePhase | None

    is_error: bool
    error_list: dict[str, MachineError]
    
    is_registered: bool
    last_online: datetime | None
    recorded_at: datetime | None
    latest_reading: LatestSensorReading | None

    def __init__(self, machine_id: str, machine_type: MachineType):
        self.machine_id = machine_id
        self.machine_type = machine_type
        
        self.is_online = False
        self.operation_state = None
        self.cycle_stage = None
        
        self.is_error = False
        self.error_list = {}

        self.is_registered = False

        self.last_online = None
        self.recorded_at = None
        self.latest_reading = None



    def __str__(self):
        return f"Machine(id={self.machine_id}, type={self.machine_type}, online={self.is_online})"

    # Mark the machine as currently reachable and record the server time.
    # 将机器标记为当前在线，并记录服务器时间。
    def mark_online(self) -> None:
        self.is_online = True
        self.last_online = datetime.now(UTC)

    # Mark the machine as unreachable without discarding its last-seen time.
    # 将机器标记为离线，同时保留最后在线时间。
    def mark_offline(self) -> None:
        self.is_online = False

    # Restore an offline machine and clear only active heartbeat errors.
    # 恢复离线机器，并且只解除活动的心跳超时错误。
    def recover_online(self) -> None:
        self.mark_online()
        self.resolve_heartbeat_timeout()

    # Resolve active heartbeat errors while preserving other machine errors.
    # 解除活动的心跳超时错误，同时保留机器的其他错误。
    def resolve_heartbeat_timeout(self) -> None:
        resolved_at = datetime.now(UTC)

        for error_id, error in list(self.error_list.items()):
            if (
                error.error_code != DiagnosticCode.DEVICE_COMMUNICATION_LOST.value
                or not error.is_active
            ):
                continue

            error.resolved_at = resolved_at
            del self.error_list[error_id]

        self.is_error = bool(self.error_list)
    
    def register(self):
        self.is_registered = True
        self.mark_online()

    # Deregister the machine, remove from the machine list
    def deregister(self):
        self.mark_offline()
        self.is_registered = False
        self.operation_state = None
        self.cycle_stage = None
    

    def update_state(self, operation_state: OperationState | None, cycle_stage: WasherCyclePhase | DryerCyclePhase | None):
        self.operation_state = operation_state
        self.cycle_stage = cycle_stage

    # Store the newest accepted sensor values without querying their persisted history.
    # 保存最新接受的传感器读数，避免查询其持久化历史。
    def update_latest_reading(
        self,
        recorded_at: datetime,
        general_readings: GeneralSensorReadings,
        special_readings: WasherSensorReadings | DryerSensorReadings,
    ) -> None:
        self.latest_reading = LatestSensorReading(
            recorded_at=recorded_at,
            general_readings=general_readings,
            special_readings=special_readings,
        )

    def set_error_heartbeat_timeout(self):
        # Set an error due to heartbeat timeout
        self.mark_offline()
        raised_at = datetime.now(UTC)
        self.add_error(
            MachineError(
                error_id=f"heartbeat-timeout-{uuid4()}",
                error_code=DiagnosticCode.DEVICE_COMMUNICATION_LOST.value,
                error_message="No device report received before the heartbeat deadline",
                error_source=ErrorSource.HEARTBEAT_MONITOR,
                raised_at=raised_at,
            )
        )

    def add_error(self, error: MachineError):
        self.is_error = True
        if error.error_id not in self.error_list:
            self.error_list[error.error_id] = error
        else:
            print(f"Error {error.error_id} already exists")
        
    def remove_error(self, error_id: str):
        error = self.error_list.get(error_id)

        if error is None:
            print(f"Error {error_id} not found")
            return

        if not error.is_active:
            print(f"Error {error_id} is already resolved")
            return

        error.resolved_at = datetime.now(UTC)

        del self.error_list[error_id]
        print(f"Error {error_id} removed")

        if not self.error_list:
            self.is_error = False

