# Define simulator fault behavior independently from machine communication.

from collections.abc import Callable
from enum import Enum, auto
from typing import Protocol
from uuid import uuid4

from laundry_contracts.contracts import DryerCyclePhase, OperationState, WasherCyclePhase
from laundry_contracts.fault_codes import DiagnosticCode


UNBALANCED_LOAD_MAX_VIBRATION = 14.0
UNBALANCED_LOAD_REPAIR_VIBRATION = 4.0
BLOCKED_VENT_TRIP_TEMPERATURE = 110.0
BLOCKED_VENT_REPAIR_TEMPERATURE = 70.0
BLOCKED_VENT_REPAIR_AIR_FLOW = 2.0


# Enumerate lifecycle states shared by simulated faults.
class FaultState(Enum):
    DEVELOPING = auto()
    TRIPPED = auto()
    REPAIRING = auto()
    REPAIRED = auto()


# Define the fault behavior required by shared machine repair logic.
class MachineFault(Protocol):
    state: FaultState

    # Begin restoring sensor values after a simulated repair command.
    def start_repair(self) -> None: ...


# Define washer fault behavior required by the washer simulator.
class WasherFault(MachineFault, Protocol):
    name: str
    injection_error_message: str

    # Report whether the washer is currently eligible for fault injection.
    def can_inject(self, operation_state: OperationState, cycle_stage: WasherCyclePhase | None) -> bool: ...

    # Advance washer fault degradation or recovery.
    def tick(self, vibration: float, elapsed_seconds: float) -> tuple[float, FaultState | None]: ...


# Define dryer fault behavior required by the dryer simulator.
class DryerFault(MachineFault, Protocol):
    name: str
    error_id: str
    error_code: str
    error_message: str
    resolution_message: str
    trip_reason: str
    repair_reason: str
    injection_error_message: str
    state: FaultState

    # Report whether the dryer is currently eligible for fault injection.
    def can_inject(self, operation_state: OperationState, cycle_stage: DryerCyclePhase | None) -> bool: ...

    # Advance dryer fault degradation or recovery.
    def tick(self, air_temperature: float, air_flow_speed: float, elapsed_seconds: float) -> tuple[float, float, FaultState | None]: ...


# Simulate excessive washer vibration caused by an unbalanced load.
class UnbalancedLoadFault:
    name = "unbalanced-load"
    injection_error_message = "Unbalanced load requires a running washer"

    # Initialize the fault in its developing state.
    def __init__(self) -> None:
        self.state: FaultState = FaultState.DEVELOPING

    # Allow injection while the washer is running.
    def can_inject(self, operation_state: OperationState, cycle_stage: WasherCyclePhase | None) -> bool:
        return operation_state is OperationState.RUNNING

    # Increase spin vibration until repair returns it to the normal level.
    def tick(self, vibration: float, elapsed_seconds: float) -> tuple[float, FaultState | None]:
        if self.state is FaultState.DEVELOPING:
            vibration = min(UNBALANCED_LOAD_MAX_VIBRATION, vibration + elapsed_seconds)
        elif self.state is FaultState.REPAIRING:
            vibration = max(UNBALANCED_LOAD_REPAIR_VIBRATION, vibration - 2.0 * elapsed_seconds)
            if vibration <= UNBALANCED_LOAD_REPAIR_VIBRATION:
                self.state = FaultState.REPAIRED
                return vibration, self.state

        return vibration, None

    # Begin lowering vibration toward its repaired level.
    def start_repair(self) -> None:
        self.state = FaultState.REPAIRING


# Simulate dryer overheating caused by restricted airflow.
class BlockedVentFault:
    name = "blocked-vent"
    error_code = DiagnosticCode.DRYER_OVERTEMPERATURE_TRIP.value
    error_message = "Dryer overtemperature protection was activated"
    resolution_message = "Dryer temperature and airflow returned to a safe range after repair"
    trip_reason = "Dryer overtemperature protection activated"
    repair_reason = "Dryer repaired after overtemperature trip"
    injection_error_message = "Blocked vent requires a running heating or drying stage"

    # Initialize a uniquely identified developing blocked-vent fault.
    def __init__(self) -> None:
        self.error_id: str = f"blocked-vent-{uuid4()}"
        self.state: FaultState = FaultState.DEVELOPING

    # Allow injection during an active dryer heating or drying phase.
    def can_inject(self, operation_state: OperationState, cycle_stage: DryerCyclePhase | None) -> bool:
        return operation_state is OperationState.RUNNING and cycle_stage in {DryerCyclePhase.HEATING, DryerCyclePhase.DRYING}

    # Advance fault degradation or repair and report lifecycle transitions.
    def tick(self, air_temperature: float, air_flow_speed: float, elapsed_seconds: float) -> tuple[float, float, FaultState | None]:
        if self.state is FaultState.DEVELOPING:
            air_temperature, air_flow_speed, should_trip = apply_blocked_vent(air_temperature, air_flow_speed, elapsed_seconds)
            if should_trip:
                self.state = FaultState.TRIPPED
                return air_temperature, air_flow_speed, self.state

        elif self.state is FaultState.REPAIRING:
            air_temperature = max(BLOCKED_VENT_REPAIR_TEMPERATURE, air_temperature - 2.0 * elapsed_seconds)
            air_flow_speed = min(BLOCKED_VENT_REPAIR_AIR_FLOW, air_flow_speed + 0.1 * elapsed_seconds)
            if air_temperature <= BLOCKED_VENT_REPAIR_TEMPERATURE and air_flow_speed >= BLOCKED_VENT_REPAIR_AIR_FLOW:
                self.state = FaultState.REPAIRED
                return air_temperature, air_flow_speed, self.state

        return air_temperature, air_flow_speed, None

    # Begin restoring dryer temperature and airflow.
    def start_repair(self) -> None:
        self.state = FaultState.REPAIRING


WASHER_FAULT_FACTORIES: dict[str, Callable[[], WasherFault]] = {
    UnbalancedLoadFault.name: UnbalancedLoadFault,
}


# Create one supported washer fault by its console name.
def create_washer_fault(fault_name: str) -> WasherFault | None:
    fault_factory = WASHER_FAULT_FACTORIES.get(fault_name)
    if fault_factory is None:
        return None
    return fault_factory()


DRYER_FAULT_FACTORIES: dict[str, Callable[[], DryerFault]] = {
    BlockedVentFault.name: BlockedVentFault,
}


# Create one supported dryer fault by its console name.
def create_dryer_fault(fault_name: str) -> DryerFault | None:
    fault_factory = DRYER_FAULT_FACTORIES.get(fault_name)
    if fault_factory is None:
        return None
    return fault_factory()


# Apply one interval of blocked-vent sensor degradation.
def apply_blocked_vent(air_temperature: float, air_flow_speed: float, elapsed_seconds: float) -> tuple[float, float, bool]:
    air_temperature += elapsed_seconds
    air_flow_speed = max(0.1, air_flow_speed - 0.05 * elapsed_seconds)
    return air_temperature, air_flow_speed, air_temperature >= BLOCKED_VENT_TRIP_TEMPERATURE
