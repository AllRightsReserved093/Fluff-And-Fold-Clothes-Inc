# Simulate a dryer's workflow, blocked vent fault, and repair process.

from datetime import UTC, datetime

import httpx

from laundry_contracts.contracts import DryerChangeOfStateReport, DryerCyclePhase, DryerErrorReport, DryerErrorResolutionReport, DryerPeriodicReport, ErrorSource, MachineType, OperationState
from simulator.faults import DryerFault, FaultState, create_dryer_fault
from simulator.machine import COMPLETE_DURATION_SECONDS, IDLE_DURATION_SECONDS, Machine


DRYER_STAGES = (
    DryerCyclePhase.HEATING,
    DryerCyclePhase.DRYING,
    DryerCyclePhase.COOLING,
)
DRYER_PHASE_DURATIONS = {
    DryerCyclePhase.HEATING: 20.0,
    DryerCyclePhase.DRYING: 45.0,
    DryerCyclePhase.COOLING: 20.0,
}


# Simulate dryer cycles, readings, reports, and injected faults.
class Dryer(Machine):
    # --------- Simulation Workflow ---------

    # Initialize dryer-specific sensor values.
    def __init__(self, machine_id: str, http_client: httpx.Client, api_base_url: str) -> None:
        super().__init__(machine_id, MachineType.DRYER, http_client, api_base_url)
        self.active_fault: DryerFault | None = None
        self.air_temperature: float = 25.0
        self.air_flow_speed: float = 0.0
        self.moisture: float = 70.0

    # Advance the dryer workflow or its active fault.
    def tick(self, elapsed_seconds: float) -> None:
        if not self.is_registered:
            return

        # ACTIVE FAULT
        if self.active_fault is not None:
            self.air_temperature, self.air_flow_speed, fault_state = self.active_fault.tick(self.air_temperature, self.air_flow_speed, elapsed_seconds)
            if fault_state is FaultState.TRIPPED:
                self._report_active_fault()
            elif fault_state is FaultState.REPAIRED:
                self._resolve_active_fault()
            return

        # IDLE
        if self.operation_state is OperationState.IDLE:
            if self.advance_phase_timer(elapsed_seconds, IDLE_DURATION_SECONDS):
                # IDLE state ended and transfer to RUNNING
                self._transition(OperationState.RUNNING, DRYER_STAGES[0], "Automatic cycle started")
            return

        # COMPLETE
        if self.operation_state is OperationState.COMPLETE:
            if self.advance_phase_timer(elapsed_seconds, COMPLETE_DURATION_SECONDS):
                # COMPLETE state ended and transfer to IDLE
                self._transition(OperationState.IDLE, None, "Cycle completed")
            return

        if self.operation_state is not OperationState.RUNNING:
            return

        # RUNNING
        self._update_readings(elapsed_seconds)
        if not self.advance_phase_timer(elapsed_seconds, DRYER_PHASE_DURATIONS[self.cycle_stage]):
            # Phase not ended yet
            return

        # Phase ended, move to the next phase
        stage_index = DRYER_STAGES.index(self.cycle_stage)
        if stage_index == len(DRYER_STAGES) - 1:
            # Cycle completed, move to COMPLETE state
            self._transition(OperationState.COMPLETE, None, "Automatic cycle completed")
        else:
            # Move to the next phase
            self._transition(OperationState.RUNNING, DRYER_STAGES[stage_index + 1], "Automatic cycle stage advanced")

    # Update normal dryer sensor values for the current cycle phase.
    def _update_readings(self, elapsed_seconds: float) -> None:
        if self.cycle_stage is DryerCyclePhase.HEATING:
            self.air_temperature = min(60.0, self.air_temperature + 2.0 * elapsed_seconds)
            self.air_flow_speed = 2.5
            self.moisture = max(60.0, self.moisture - 0.5 * elapsed_seconds)
        elif self.cycle_stage is DryerCyclePhase.DRYING:
            self.air_temperature = 60.0
            self.air_flow_speed = 2.5
            self.moisture = max(10.0, self.moisture - 1.1 * elapsed_seconds)
        elif self.cycle_stage is DryerCyclePhase.COOLING:
            self.air_temperature = max(30.0, self.air_temperature - 1.5 * elapsed_seconds)
            self.air_flow_speed = 2.0
            self.moisture = max(5.0, self.moisture - 0.25 * elapsed_seconds)

    # Apply and report one dryer state transition.
    def _transition(self, new_operation_state: OperationState, new_cycle_stage: DryerCyclePhase | None, reason: str) -> None:
        previous_operation_state = self.operation_state
        previous_cycle_stage = self.cycle_stage

        # Update machine state
        self.operation_state = new_operation_state
        self.cycle_stage = new_cycle_stage
        self.phase_elapsed_seconds = 0.0

        if new_operation_state in {OperationState.IDLE, OperationState.COMPLETE}:
            self.door_locked = False
            self.vibration = 0.1
            self.air_temperature = 25.0
            self.air_flow_speed = 0.0
            self.moisture = 70.0
        else:
            self.door_locked = True
            self.vibration = 0.8
            if new_cycle_stage is DryerCyclePhase.HEATING:
                self.air_temperature = 25.0
                self.air_flow_speed = 2.5
                self.moisture = 70.0
            elif new_cycle_stage is DryerCyclePhase.DRYING:
                self.air_temperature = 60.0
                self.air_flow_speed = 2.5
            elif new_cycle_stage is DryerCyclePhase.COOLING:
                self.air_flow_speed = 2.0

        # Generate report
        report = DryerChangeOfStateReport(
            machine_id=self.machine_id,
            machine_type=MachineType.DRYER,
            report_id=self.new_report_id("state"),
            recorded_at=datetime.now(UTC),
            previous_operation_state=previous_operation_state,
            new_operation_state=new_operation_state,
            previous_cycle_stage=previous_cycle_stage,
            new_cycle_stage=new_cycle_stage,
            reason=reason,
        )

        self.post("/reports/change-of-state", report, {200})

    # --------- Fault Handling ---------

    # Activate one supported dryer fault when its preconditions are met.
    def inject_fault(self, fault_name: str) -> bool:
        fault = create_dryer_fault(fault_name)
        if fault is None:
            print(f"[{self.machine_id}] Fault {fault_name} is not supported")
            return False
        if self.active_fault is not None:
            print(f"[{self.machine_id}] A fault is already active")
            return False
        if not fault.can_inject(self.operation_state, self.cycle_stage):
            print(f"[{self.machine_id}] {fault.injection_error_message}")
            return False

        self.active_fault = fault
        print(f"[{self.machine_id}] Injected fault: {fault_name}")
        return True

    # Report the active dryer fault and its protective shutdown.
    def _report_active_fault(self) -> None:
        # Check if a fault is active
        fault = self.active_fault
        if fault is None:
            return

        # Generate report
        recorded_at = datetime.now(UTC)
        state_report = DryerChangeOfStateReport(
            machine_id=self.machine_id,
            machine_type=MachineType.DRYER,
            report_id=self.new_report_id("state"),
            recorded_at=recorded_at,
            previous_operation_state=self.operation_state,
            new_operation_state=OperationState.FAULTED,
            previous_cycle_stage=self.cycle_stage,
            new_cycle_stage=self.cycle_stage,
            reason=fault.trip_reason,
        )
        error_report = DryerErrorReport(
            machine_id=self.machine_id,
            machine_type=MachineType.DRYER,
            report_id=self.new_report_id("error"),
            recorded_at=recorded_at,
            error_id=fault.error_id,
            error_code=fault.error_code,
            error_message=fault.error_message,
            error_source=ErrorSource.DEVICE,
            general_sensor_readings={"vibration": self.vibration, "door_locked": self.door_locked},
            special_sensor_readings={"air_temperature": self.air_temperature, "air_flow_speed": self.air_flow_speed, "moisture": self.moisture},
            change_of_state=True,
            change_of_state_report=state_report,
        )

        # Update state
        self.operation_state = OperationState.FAULTED
        self.phase_elapsed_seconds = 0.0

        # Post the error report
        self.post("/reports/error", error_report, {200})
        print(f"[{self.machine_id}] Protective shutdown: {fault.error_code}")

    # Report repair completion and return the dryer to idle.
    def _resolve_active_fault(self) -> None:
        # Check if active fault exists
        fault = self.active_fault
        if fault is None:
            return

        # Generate report
        report = DryerErrorResolutionReport(
            machine_id=self.machine_id,
            machine_type=MachineType.DRYER,
            report_id=self.new_report_id("resolution"),
            recorded_at=datetime.now(UTC),
            error_id=fault.error_id,
            resolution_message=fault.resolution_message,
            operation_state=self.operation_state,
            cycle_stage=self.cycle_stage,
            general_sensor_readings={"vibration": self.vibration, "door_locked": self.door_locked},
            special_sensor_readings={"air_temperature": self.air_temperature, "air_flow_speed": self.air_flow_speed, "moisture": self.moisture},
        )
        self.post("/reports/error-resolution", report, {200})
        self.active_fault = None
        self._transition(OperationState.IDLE, None, fault.repair_reason)
        print(f"[{self.machine_id}] Repair completed")

    # --------- Reporting and Status ---------

    # Send the dryer's current state and readings to the backend.
    def send_periodic_report(self) -> bool:
        report = DryerPeriodicReport(
            machine_id=self.machine_id,
            machine_type=MachineType.DRYER,
            report_id=self.new_report_id("periodic"),
            recorded_at=datetime.now(UTC),
            operation_state=self.operation_state,
            cycle_stage=self.cycle_stage,
            general_sensor_readings={"vibration": self.vibration, "door_locked": self.door_locked},
            special_sensor_readings={"air_temperature": self.air_temperature, "air_flow_speed": self.air_flow_speed, "moisture": self.moisture},
        )
        return self.post("/reports/periodic", report, {200})

    # Return a compact dryer status for the simulator console.
    def status_line(self) -> str:
        stage = self.cycle_stage.value if self.cycle_stage is not None else "none"
        fault = f", fault={self.active_fault.name}" if self.active_fault is not None else ""
        signals = "on" if self.is_communication_enabled else "off"
        return f"{self.machine_id}: state={self.operation_state.value}, stage={stage}, temperature={self.air_temperature:.1f}C, airflow={self.air_flow_speed:.1f}m/s, moisture={self.moisture:.1f}%, signals={signals}{fault}"
