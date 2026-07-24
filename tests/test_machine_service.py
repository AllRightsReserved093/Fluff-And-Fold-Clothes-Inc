# Verify the in-memory machine service and monitor coordination.

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.machines import machine_monitor as machine_monitor_module
from app.machines.machine_monitor import MachineMonitor
from app.machines.machines import Machine
from app.services import machine_service as machine_service_module
from app.services.machine_service import MachineService
from laundry_contracts.contracts import (
    ErrorSource,
    MachineType,
    OperationState,
    ReportProcessingResult,
    WasherChangeOfStateReport,
    WasherErrorReport,
    WasherPeriodicReport,
    WasherCyclePhase,
)
from laundry_contracts.fault_codes import DiagnosticCode


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

    def update_machine(self, machine_id: str, _recorded_at: datetime | None) -> None:
        self.updated_machine_ids.append(machine_id)

    def start_monitor(self) -> None:
        self.start_count += 1
        self.is_working = True

    def end_monitor(self) -> None:
        self.stop_count += 1
        self.is_working = False


# Isolate every service test in a fresh shared in-memory SQLite database.
@pytest.fixture(autouse=True)
def isolated_database(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    test_session_factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(machine_service_module, "SessionFactory", test_session_factory)

    yield

    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


# Keep monitoring after one timeout callback fails.
def test_monitor_survives_timeout_callback_exception(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(machine_monitor_module, "HEARTBEAT_TIMEOUT_MILLISECONDS", 10)
    second_callback_received = Event()
    callback_count = 0

    def on_timeout(_machine_id: str, _recorded_at: datetime | None) -> None:
        nonlocal callback_count
        callback_count += 1
        if callback_count == 1:
            raise RuntimeError("Test callback failure")
        second_callback_received.set()

    monitor = MachineMonitor(on_timeout)
    monitor.add_machine(Machine("washer-monitor", MachineType.WASHER))
    monitor.start_monitor()

    try:
        assert second_callback_received.wait(timeout=1)
        assert monitor.monitor_thread is not None
        assert monitor.monitor_thread.is_alive()
        assert "Heartbeat timeout callback failed for machine washer-monitor" in caplog.text
    finally:
        monitor.end_monitor()


def test_new_report_invalidates_popped_heartbeat_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_monitor_module, "HEARTBEAT_TIMEOUT_MILLISECONDS", 10)
    callback_started = Event()
    continue_callback = Event()
    callback_finished = Event()
    callback_results: list[bool] = []
    service: MachineService | None = None

    def delayed_timeout(machine_id: str, expected_recorded_at: datetime | None) -> None:
        callback_started.set()
        if not continue_callback.wait(timeout=1):
            raise RuntimeError("Timed out while waiting to continue the test callback")
        if service is not None:
            callback_results.append(service.handle_heartbeat_timeout(machine_id, expected_recorded_at))
        callback_finished.set()

    monitor = MachineMonitor(delayed_timeout)
    service = MachineService(monitor)
    assert service.machine_register("washer-race", MachineType.WASHER)

    try:
        assert callback_started.wait(timeout=1)
        monkeypatch.setattr(machine_monitor_module, "HEARTBEAT_TIMEOUT_MILLISECONDS", 1_000)
        report = WasherPeriodicReport(
            machine_id="washer-race",
            machine_type=MachineType.WASHER,
            report_id="race-periodic-01",
            recorded_at=datetime.now(UTC),
            operation_state=OperationState.RUNNING,
            cycle_stage=WasherCyclePhase.WASHING,
            general_sensor_readings={"vibration": 0.1, "door_locked": True},
            special_sensor_readings={"water_level": 50.0, "water_temperature": 40.0},
        )
        assert service.handle_periodic_report(report) is ReportProcessingResult.ACCEPTED

        continue_callback.set()
        assert callback_finished.wait(timeout=1)
    finally:
        continue_callback.set()
        monitor.end_monitor()

    machine = service.machines_registry["washer-race"]
    assert callback_results == [False]
    assert machine.is_online
    assert not machine.error_list


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


def test_shutdown_stops_monitor() -> None:
    monitor = StubMachineMonitor()
    service = MachineService(monitor)

    service.shutdown()

    assert monitor.stop_count == 1


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

    assert service.handle_periodic_report(report) is ReportProcessingResult.ACCEPTED
    assert machine.operation_state is OperationState.RUNNING
    assert machine.cycle_stage is WasherCyclePhase.WASHING
    assert machine.is_online
    assert machine.recorded_at == report.recorded_at
    assert machine.latest_reading is not None
    assert machine.latest_reading.recorded_at == report.recorded_at
    assert machine.latest_reading.general_readings.vibration == 0.1
    assert machine.latest_reading.special_readings.water_temperature == 40.0
    assert monitor.updated_machine_ids == ["washer-01"]
    older_report = report.model_copy(update={"report_id": "report-old", "recorded_at": report.recorded_at - timedelta(seconds=1)})
    assert service.handle_periodic_report(older_report) is ReportProcessingResult.DUPLICATE
    assert machine.recorded_at == report.recorded_at


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

    assert service.handle_change_of_state_report(report) is ReportProcessingResult.ACCEPTED
    assert machine.operation_state is OperationState.RUNNING
    assert machine.cycle_stage is WasherCyclePhase.FILLING
    older_report = report.model_copy(update={"report_id": "report-old", "recorded_at": report.recorded_at - timedelta(seconds=1)})
    assert service.handle_change_of_state_report(older_report) is ReportProcessingResult.DUPLICATE
    assert machine.recorded_at == report.recorded_at
    assert not service.handle_heartbeat_timeout("washer-01", None)
    assert machine.is_online
    assert service.handle_heartbeat_timeout("washer-01", machine.recorded_at)
    assert not machine.is_online
    assert machine.is_error
    heartbeat_error = next(iter(machine.error_list.values()))
    assert heartbeat_error.error_code == DiagnosticCode.DEVICE_COMMUNICATION_LOST.value
    assert heartbeat_error.error_source is ErrorSource.HEARTBEAT_MONITOR

    recovery_report = WasherChangeOfStateReport(
        machine_id="washer-01",
        machine_type=MachineType.WASHER,
        report_id="report-03",
        recorded_at=datetime.now(UTC),
        previous_operation_state=OperationState.RUNNING,
        new_operation_state=OperationState.RUNNING,
        previous_cycle_stage=WasherCyclePhase.FILLING,
        new_cycle_stage=WasherCyclePhase.WASHING,
    )

    assert service.handle_change_of_state_report(recovery_report) is ReportProcessingResult.ACCEPTED
    assert machine.is_online
    assert machine.recorded_at == recovery_report.recorded_at
    assert not machine.is_error
    assert not machine.error_list


def test_heartbeat_timeout_database_failure_does_not_update_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = StubMachineMonitor()
    service = MachineService(monitor)
    service.machine_register("washer-01", MachineType.WASHER)
    machine = service.machines_registry["washer-01"]

    def fail_to_add_heartbeat_timeout(*_args) -> bool:
        raise RuntimeError("Test database failure")

    monkeypatch.setattr(service.database_operation, "add_heartbeat_timeout", fail_to_add_heartbeat_timeout)

    with pytest.raises(RuntimeError, match="Test database failure"):
        service.handle_heartbeat_timeout("washer-01", machine.recorded_at)

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
        error_code=DiagnosticCode.DOOR_INTERLOCK_LOST.value,
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

    assert service.handle_error_report(report) is ReportProcessingResult.ACCEPTED
    assert machine.is_online
    assert machine.recorded_at == report.recorded_at
    assert machine.latest_reading is not None
    assert machine.latest_reading.general_readings.door_locked is False
    assert machine.error_list["door-error-01"].raised_at == report.recorded_at
    assert monitor.updated_machine_ids == ["washer-01"]
    older_report = report.model_copy(
        update={
            "report_id": "report-error-old",
            "recorded_at": report.recorded_at - timedelta(seconds=1),
            "error_id": "door-error-old",
        }
    )
    assert service.handle_error_report(older_report) is ReportProcessingResult.DUPLICATE
    assert "door-error-old" not in machine.error_list

    assert service.handle_heartbeat_timeout("washer-01", machine.recorded_at)
    machine.recover_online()

    assert machine.is_online
    assert set(machine.error_list) == {"door-error-01"}
    assert machine.is_error
