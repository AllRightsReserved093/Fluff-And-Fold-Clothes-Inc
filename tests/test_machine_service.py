# Verify the in-memory machine service and monitor coordination.
# 验证内存机器服务及其与监控器的协调行为。

from datetime import UTC, datetime

from app.machines.machines import Machine
from app.services.machine_service import MachineService
from laundry_contracts.contracts import (
    ErrorSource,
    MachineErrorCode,
    MachineType,
    OperationState,
    WasherChangeOfStateReport,
    WasherErrorReport,
    WasherPeriodicReport,
    WasherCyclePhase,
)


class StubMachineMonitor:
    def __init__(self) -> None:
        self.is_working = False
        self.added_machine_ids: list[str] = []
        self.removed_machine_ids: list[str] = []
        self.updated_machine_ids: list[str] = []
        self.start_count = 0
        self.stop_count = 0

    def add_machine(self, machine: Machine) -> None:
        self.added_machine_ids.append(machine.machine_id)

    def remove_machine(self, machine_id: str) -> None:
        self.removed_machine_ids.append(machine_id)

    def update_machine(self, machine_id: str) -> None:
        self.updated_machine_ids.append(machine_id)

    def start_monitor(self) -> None:
        self.start_count += 1
        self.is_working = True

    def end_monitor(self) -> None:
        self.stop_count += 1
        self.is_working = False


def test_register_machine_rejects_empty_and_duplicate_ids() -> None:
    monitor = StubMachineMonitor()
    service = MachineService(monitor)

    assert service.machine_register("washer-01", MachineType.WASHER)
    assert not service.machine_register("washer-01", MachineType.WASHER)
    assert not service.machine_register("", MachineType.WASHER)

    machine = service.machines_registry["washer-01"]
    assert machine.is_online
    assert machine.last_online is not None
    assert machine.last_online.tzinfo is UTC
    assert monitor.added_machine_ids == ["washer-01"]


def test_register_machine_starts_monitor() -> None:
    monitor = StubMachineMonitor()
    service = MachineService(monitor)

    assert monitor.start_count == 0

    service.machine_register("washer-01", MachineType.WASHER)

    assert monitor.start_count == 1


def test_deregister_machine_removes_machine_from_monitor() -> None:
    monitor = StubMachineMonitor()
    service = MachineService(monitor)
    service.machine_register("dryer-01", MachineType.DRYER)

    assert service.machine_deregister("dryer-01")
    assert "dryer-01" not in service.machines_registry
    assert not service.machine_deregister("dryer-01")
    assert monitor.removed_machine_ids == ["dryer-01"]


def test_periodic_report_updates_machine_and_heartbeat() -> None:
    monitor = StubMachineMonitor()
    service = MachineService(monitor)
    service.machine_register("washer-01", MachineType.WASHER)
    machine = service.machines_registry["washer-01"]
    machine.mark_offline()
    report = WasherPeriodicReport(
        machine_id="washer-01",
        machine_type=MachineType.WASHER,
        report_id="report-01",
        recorded_at=datetime.now(UTC),
        operation_state=OperationState.RUNNING,
        cycle_stage=WasherCyclePhase.WASHING,
        general_sensor_readings={
            "vibration": 0.1,
            "door_locked": True,
        },
        special_sensor_readings={
            "water_level": 0.8,
            "water_temperature": 40.0,
        },
    )

    assert service.handle_periodic_report(report)
    assert machine.operation_state is OperationState.RUNNING
    assert machine.cycle_stage is WasherCyclePhase.WASHING
    assert machine.is_online
    assert monitor.updated_machine_ids == ["washer-01"]


def test_change_report_and_heartbeat_timeout_update_machine() -> None:
    monitor = StubMachineMonitor()
    service = MachineService(monitor)
    service.machine_register("washer-01", MachineType.WASHER)
    machine = service.machines_registry["washer-01"]
    report = WasherChangeOfStateReport(
        machine_id="washer-01",
        machine_type=MachineType.WASHER,
        report_id="report-02",
        recorded_at=datetime.now(UTC),
        previous_operation_state=OperationState.IDLE,
        new_operation_state=OperationState.RUNNING,
        previous_cycle_stage=None,
        new_cycle_stage=WasherCyclePhase.FILLING,
    )

    assert service.handle_change_of_state_report(report)
    assert machine.operation_state is OperationState.RUNNING
    assert machine.cycle_stage is WasherCyclePhase.FILLING
    assert service.handle_heartbeat_timeout("washer-01")
    assert not machine.is_online
    assert machine.is_error
    heartbeat_error = next(iter(machine.error_list.values()))
    assert heartbeat_error.error_code == MachineErrorCode.HEARTBEAT_TIMEOUT
    assert heartbeat_error.error_source is ErrorSource.HEARTBEAT_MONITOR

    assert service.handle_change_of_state_report(report)
    assert machine.is_online
    assert not machine.is_error
    assert not machine.error_list


def test_error_report_adds_machine_error() -> None:
    monitor = StubMachineMonitor()
    service = MachineService(monitor)
    service.machine_register("washer-01", MachineType.WASHER)
    machine = service.machines_registry["washer-01"]
    machine.mark_offline()
    report = WasherErrorReport(
        machine_id="washer-01",
        machine_type=MachineType.WASHER,
        report_id="report-error-01",
        recorded_at=datetime.now(UTC),
        error_id="door-error-01",
        error_code="door_fault",
        error_message="Door did not lock",
        error_source=ErrorSource.DEVICE,
        general_sensor_readings={
            "vibration": 0.1,
            "door_locked": False,
        },
        special_sensor_readings={
            "water_level": 50.0,
            "water_temperature": 40.0,
        },
    )

    assert service.handle_error_report(report)
    assert machine.is_online
    assert machine.error_list["door-error-01"].raised_at == report.recorded_at
    assert monitor.updated_machine_ids == ["washer-01"]

    assert service.handle_heartbeat_timeout("washer-01")
    machine.recover_online()

    assert machine.is_online
    assert set(machine.error_list) == {"door-error-01"}
    assert machine.is_error
