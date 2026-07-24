# Represent the backend state of a registered laundry machine.

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

# Represent the mutable in-memory state of one registered machine.
class Machine:
    # Initialize one machine with no registration, readings, or active errors.
    def __init__(self, machine_id: str, machine_type: MachineType) -> None:
        self.machine_id: str = machine_id
        self.machine_type: MachineType = machine_type
        
        self.is_online: bool = False
        self.operation_state: OperationState | None = None
        self.cycle_stage: WasherCyclePhase | DryerCyclePhase | None = None
        
        self.is_error: bool = False
        self.error_list: dict[str, MachineError] = {}

        self.is_registered: bool = False
        self.registered_at: datetime | None = None

        self.last_online: datetime | None = None
        self.recorded_at: datetime | None = None
        self.latest_reading: LatestSensorReading | None = None



    # Return a compact human-readable machine description.
    def __str__(self) -> str:
        return f"Machine(id={self.machine_id}, type={self.machine_type}, online={self.is_online})"

    # Mark the machine as currently reachable and record the server time.
    def mark_online(self) -> None:
        self.is_online = True
        self.last_online = datetime.now(UTC)

    # Mark the machine as unreachable without discarding its last-seen time.
    def mark_offline(self) -> None:
        self.is_online = False

    # Restore an offline machine and clear only active heartbeat errors.
    def recover_online(self) -> None:
        self.mark_online()
        self.resolve_heartbeat_timeout()

    # Resolve active heartbeat errors while preserving other machine errors.
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
    
    # Mark the machine as registered and online.
    def register(self) -> None:
        if self.is_registered:
            return
        self.is_registered = True
        self.mark_online()
        self.registered_at = datetime.now(UTC)

    # Deregister the machine, remove from the machine list
    def deregister(self) -> None:
        self.mark_offline()
        self.is_registered = False
        self.operation_state = None
        self.cycle_stage = None
    

    # Replace the machine's current operation state and cycle stage.
    def update_state(self, operation_state: OperationState | None, cycle_stage: WasherCyclePhase | DryerCyclePhase | None) -> None:
        self.operation_state = operation_state
        self.cycle_stage = cycle_stage

    # Store the newest accepted sensor values without querying their persisted history.
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

    # Create a heartbeat timeout error without changing the machine state.
    def create_heartbeat_timeout_error(self) -> MachineError:
        raised_at = datetime.now(UTC)
        return MachineError(
            error_id=f"heartbeat-timeout-{uuid4()}",
            error_code=DiagnosticCode.DEVICE_COMMUNICATION_LOST.value,
            error_message="No device report received before the heartbeat deadline",
            error_source=ErrorSource.HEARTBEAT_MONITOR,
            raised_at=raised_at,
        )

    # Add one active error unless it is already present.
    def add_error(self, error: MachineError) -> None:
        self.is_error = True
        if error.error_id not in self.error_list:
            self.error_list[error.error_id] = error
        else:
            print(f"Error {error.error_id} already exists")
        
    # Resolve and remove one active in-memory error.
    def remove_error(self, error_id: str) -> None:
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
