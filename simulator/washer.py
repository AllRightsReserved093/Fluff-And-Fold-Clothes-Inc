# Simulate a washer's normal workflow and sensor reports.
# 模拟洗衣机的正常工作流程与传感器报告。

from datetime import UTC, datetime

import httpx

from laundry_contracts.contracts import MachineType, OperationState, WasherChangeOfStateReport, WasherCyclePhase, WasherPeriodicReport
from simulator.machine import COMPLETE_DURATION_SECONDS, IDLE_DURATION_SECONDS, Machine


WASHER_STAGES = (
    WasherCyclePhase.FILLING,
    WasherCyclePhase.WASHING,
    WasherCyclePhase.DRAINING,
    WasherCyclePhase.SPINNING,
)
WASHER_PHASE_DURATIONS = {
    WasherCyclePhase.FILLING: 20.0,
    WasherCyclePhase.WASHING: 45.0,
    WasherCyclePhase.DRAINING: 20.0,
    WasherCyclePhase.SPINNING: 30.0,
}


class Washer(Machine):
    def __init__(self, machine_id: str, http_client: httpx.Client, api_base_url: str) -> None:
        super().__init__(machine_id, MachineType.WASHER, http_client, api_base_url)
        self.water_level = 0.0
        self.water_temperature = 20.0

    # Keep a safe placeholder until washer fault simulation is implemented.
    # 在洗衣机故障模拟实现前，保留一个安全的占位入口。
    def inject_fault(self, fault_name: str) -> bool:
        print(f"[{self.machine_id}] Fault {fault_name} is not supported")
        return False

    def tick(self, elapsed_seconds: float) -> None:
        if not self.is_registered:
            return

        # IDLE
        if self.operation_state is OperationState.IDLE:
            if self.advance_phase_timer(elapsed_seconds, IDLE_DURATION_SECONDS):
                # IDLE state ended and transfer to RUNNING
                self._transition(OperationState.RUNNING, WASHER_STAGES[0], "Automatic cycle started")
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
        if not self.advance_phase_timer(elapsed_seconds, WASHER_PHASE_DURATIONS[self.cycle_stage]):
            # Phase not ended yet
            return

        # Phase ended, move to the next phase
        stage_index = WASHER_STAGES.index(self.cycle_stage)
        if stage_index == len(WASHER_STAGES) - 1:
            # Cycle completed, move to COMPLETE state
            self._transition(OperationState.COMPLETE, None, "Automatic cycle completed")
        else:
            # Move to the next phase
            self._transition(OperationState.RUNNING, WASHER_STAGES[stage_index + 1], "Automatic cycle stage advanced")

    def _update_readings(self, elapsed_seconds: float) -> None:
        if self.cycle_stage is WasherCyclePhase.FILLING:
            self.water_level = min(60.0, self.water_level + 3.0 * elapsed_seconds)
            self.water_temperature = min(40.0, self.water_temperature + elapsed_seconds)
        elif self.cycle_stage is WasherCyclePhase.WASHING:
            self.water_level = 60.0
            self.water_temperature = 40.0
        elif self.cycle_stage is WasherCyclePhase.DRAINING:
            self.water_level = max(0.0, self.water_level - 3.0 * elapsed_seconds)
            self.water_temperature = max(25.0, self.water_temperature - 0.75 * elapsed_seconds)
        elif self.cycle_stage is WasherCyclePhase.SPINNING:
            self.water_level = 0.0
            self.water_temperature = 25.0

    def _transition(self, new_operation_state: OperationState, new_cycle_stage: WasherCyclePhase | None, reason: str) -> None:
        previous_operation_state = self.operation_state
        previous_cycle_stage = self.cycle_stage

        # Update machine state
        self.operation_state = new_operation_state
        self.cycle_stage = new_cycle_stage
        self.phase_elapsed_seconds = 0.0

        if new_operation_state in {OperationState.IDLE, OperationState.COMPLETE}:
            self.door_locked = False
            self.vibration = 0.1
            self.water_level = 0.0
            self.water_temperature = 20.0
        else:
            self.door_locked = True
            self.vibration = {
                WasherCyclePhase.FILLING: 0.5,
                WasherCyclePhase.WASHING: 2.0,
                WasherCyclePhase.DRAINING: 1.0,
                WasherCyclePhase.SPINNING: 4.0,
            }[new_cycle_stage]

        # Generate report 
        report = WasherChangeOfStateReport(
            machine_id=self.machine_id,
            machine_type=MachineType.WASHER,
            report_id=self.new_report_id("state"),
            recorded_at=datetime.now(UTC),
            previous_operation_state=previous_operation_state,
            new_operation_state=new_operation_state,
            previous_cycle_stage=previous_cycle_stage,
            new_cycle_stage=new_cycle_stage,
            reason=reason,
        )

        self.post("/reports/change-of-state", report, {200})

    def send_periodic_report(self) -> bool:
        report = WasherPeriodicReport(
            machine_id=self.machine_id,
            machine_type=MachineType.WASHER,
            report_id=self.new_report_id("periodic"),
            recorded_at=datetime.now(UTC),
            operation_state=self.operation_state,
            cycle_stage=self.cycle_stage,
            general_sensor_readings={"vibration": self.vibration, "door_locked": self.door_locked},
            special_sensor_readings={"water_level": self.water_level, "water_temperature": self.water_temperature},
        )
        return self.post("/reports/periodic", report, {200})

    def status_line(self) -> str:
        stage = self.cycle_stage.value if self.cycle_stage is not None else "none"
        return f"{self.machine_id}: state={self.operation_state.value}, stage={stage}, water={self.water_level:.1f}%, temperature={self.water_temperature:.1f}C, vibration={self.vibration:.1f}"
