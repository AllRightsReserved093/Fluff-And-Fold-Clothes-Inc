# Provide shared machine state and HTTP communication helpers.

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from pydantic import BaseModel

from laundry_contracts.contracts import DeregistrationRequest, DryerCyclePhase, MachineType, OperationState, RegistrationRequest, WasherCyclePhase
from simulator.faults import FaultState, MachineFault


REPORT_INTERVAL_SECONDS = 15.0
IDLE_DURATION_SECONDS = 10.0
COMPLETE_DURATION_SECONDS = 10.0

CycleStage = WasherCyclePhase | DryerCyclePhase | None


# Provide shared simulator state, repair behavior, and HTTP communication.
class Machine(ABC):
    # Initialize one simulated machine with its normal idle state.
    def __init__(self, machine_id: str, machine_type: MachineType, http_client: httpx.Client, api_base_url: str) -> None:
        self.machine_id: str = machine_id
        self.machine_type: MachineType = machine_type
        self.http_client: httpx.Client = http_client
        self.api_base_url: str = api_base_url.rstrip("/")

        self.operation_state: OperationState = OperationState.IDLE
        self.cycle_stage: CycleStage = None
        self.phase_elapsed_seconds: float = 0.0

        self.is_registered: bool = False
        self.is_communication_enabled: bool = True
        self.next_report_at: float = 0.0
        self.vibration: float = 0.1
        self.door_locked: bool = False
        self.active_fault: MachineFault | None = None

    # Advance machine-specific simulation state by one elapsed interval.
    @abstractmethod
    def tick(self, elapsed_seconds: float) -> None: ...

    # Inject one machine-specific simulated fault.
    @abstractmethod
    def inject_fault(self, fault_name: str) -> bool: ...

    # Send one machine-specific periodic report.
    @abstractmethod
    def send_periodic_report(self) -> bool: ...

    # Return one compact console status line.
    @abstractmethod
    def status_line(self) -> str: ...

    # Advance the current phase timer and report whether its duration was reached.
    def advance_phase_timer(self, elapsed_seconds: float, duration_seconds: float) -> bool:
        self.phase_elapsed_seconds += elapsed_seconds
        return self.phase_elapsed_seconds >= duration_seconds

    # Register the simulated machine with the backend.
    def register(self) -> bool:
        request = RegistrationRequest(machine_id=self.machine_id, machine_type=self.machine_type, registered_at=datetime.now(UTC))
        self.is_registered = self.post("/machines/register", request, {201, 409})
        return self.is_registered

    # Deregister the simulated machine from the backend.
    def deregister(self) -> bool:
        if not self.is_registered:
            return True

        request = DeregistrationRequest(machine_id=self.machine_id, deregistered_at=datetime.now(UTC), reason="Simulator shutdown")
        succeeded = self.post("/machines/deregister", request, {200})
        if succeeded:
            self.is_registered = False
        return succeeded

    # Send one validated contract to a backend endpoint.
    def post(self, path: str, contract: BaseModel, expected_status_codes: set[int]) -> bool:
        try:
            response = self.http_client.post(f"{self.api_base_url}{path}", json=contract.model_dump(mode="json"))
        except httpx.RequestError as error:
            print(f"[{self.machine_id}] HTTP request failed: {error}")
            return False

        if response.status_code not in expected_status_codes:
            print(f"[{self.machine_id}] HTTP {response.status_code} returned for {path}")
            return False
        return True

    # Generate a globally unique report identifier.
    def new_report_id(self, report_type: str) -> str:
        return f"{report_type}-{uuid4()}"

    # Start repairing the active fault when the machine is ready for repair.
    def repair(self) -> bool:
        if self.active_fault is None:
            print(f"[{self.machine_id}] No repairable fault is active")
            return False

        if self.active_fault.state is FaultState.REPAIRING:
            print(f"[{self.machine_id}] Repair is already in progress")
            return False

        self.active_fault.start_repair()
        print(f"[{self.machine_id}] Repair started")
        return True
