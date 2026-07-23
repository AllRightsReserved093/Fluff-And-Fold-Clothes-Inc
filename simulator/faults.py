# Define simulator fault behavior independently from machine communication.
# 独立于机器通信逻辑定义模拟故障行为。

from collections.abc import Callable
from enum import Enum, auto
from typing import Protocol
from uuid import uuid4

from laundry_contracts.contracts import DryerCyclePhase, OperationState


BLOCKED_VENT_TRIP_TEMPERATURE = 110.0
BLOCKED_VENT_REPAIR_TEMPERATURE = 70.0
BLOCKED_VENT_REPAIR_AIR_FLOW = 2.0


class FaultState(Enum):
    DEVELOPING = auto()
    TRIPPED = auto()
    REPAIRING = auto()
    REPAIRED = auto()


class DryerFault(Protocol):
    name: str
    error_id: str
    error_code: str
    error_message: str
    resolution_message: str
    trip_reason: str
    repair_reason: str
    injection_error_message: str
    state: FaultState

    def can_inject(self, operation_state: OperationState, cycle_stage: DryerCyclePhase | None) -> bool: ...

    def tick(self, air_temperature: float, air_flow_speed: float, elapsed_seconds: float) -> tuple[float, float, FaultState | None]: ...

    def start_repair(self) -> bool: ...


class BlockedVentFault:
    name = "blocked-vent"
    error_code = "blocked_vent_overheat"
    error_message = "Blocked dryer vent caused unsafe temperature and airflow"
    resolution_message = "Blocked vent was cleared and sensor readings returned to a safe range"
    trip_reason = "Blocked dryer vent caused protective shutdown"
    repair_reason = "Blocked vent repaired"
    injection_error_message = "Blocked vent requires a running heating or drying stage"

    def __init__(self) -> None:
        self.error_id = f"blocked-vent-{uuid4()}"
        self.state = FaultState.DEVELOPING

    def can_inject(self, operation_state: OperationState, cycle_stage: DryerCyclePhase | None) -> bool:
        return operation_state is OperationState.RUNNING and cycle_stage in {DryerCyclePhase.HEATING, DryerCyclePhase.DRYING}

    # Advance fault degradation or repair and report lifecycle transitions.
    # 推进故障恶化或维修过程，并报告生命周期变化。
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

    def start_repair(self) -> bool:
        if self.state is not FaultState.TRIPPED:
            return False

        self.state = FaultState.REPAIRING
        return True


DRYER_FAULT_FACTORIES: dict[str, Callable[[], DryerFault]] = {
    BlockedVentFault.name: BlockedVentFault,
}


def create_dryer_fault(fault_name: str) -> DryerFault | None:
    fault_factory = DRYER_FAULT_FACTORIES.get(fault_name)
    if fault_factory is None:
        return None
    return fault_factory()


def apply_blocked_vent(air_temperature: float, air_flow_speed: float, elapsed_seconds: float) -> tuple[float, float, bool]:
    air_temperature += elapsed_seconds
    air_flow_speed = max(0.1, air_flow_speed - 0.05 * elapsed_seconds)
    return air_temperature, air_flow_speed, air_temperature >= BLOCKED_VENT_TRIP_TEMPERATURE
