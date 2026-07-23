# Verify the complete MachineService persistence flow with in-memory SQLite.
# 使用内存 SQLite 验证 MachineService 的完整持久化流程。

import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import DataEventRecord, FaultEventRecord, MachineRecord, MachineStateEventRecord, SensorReadingRecord
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
    WasherErrorResolutionReport,
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

    def add_machine(self, machine: Machine) -> None:
        self.added_machine_ids.append(machine.machine_id)

    def remove_machine(self, machine_id: str) -> None:
        self.removed_machine_ids.append(machine_id)

    def update_machine(self, machine_id: str) -> None:
        self.updated_machine_ids.append(machine_id)

    def start_monitor(self) -> None:
        self.is_working = True


# Replace the production SessionFactory with one shared in-memory database.
# 用一个共享的内存数据库替换生产环境的 SessionFactory。
@pytest.fixture
def database_session_factory(monkeypatch: pytest.MonkeyPatch) -> Generator[sessionmaker[Session], None, None]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    test_session_factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(machine_service_module, "SessionFactory", test_session_factory)

    yield test_session_factory

    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


# Provide a disposable snapshot directory inside the writable test folder.
# 在可写的测试目录中提供一个用后即删的快照目录。
@pytest.fixture
def fault_snapshot_directory() -> Generator[Path, None, None]:
    directory = Path(__file__).parent / "artifacts"
    yield directory
    for snapshot_file in directory.glob("fault-*.json"):
        snapshot_file.unlink()


def test_machine_service_persists_complete_lifecycle(database_session_factory: sessionmaker[Session], fault_snapshot_directory: Path) -> None:
    monitor = StubMachineMonitor()
    service = MachineService(monitor, fault_snapshot_directory)
    recorded_at = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)

    assert service.machine_register("washer-01", MachineType.WASHER)

    first_periodic_report = WasherPeriodicReport(
        machine_id="washer-01",
        machine_type=MachineType.WASHER,
        report_id="periodic-01",
        recorded_at=recorded_at,
        operation_state=OperationState.RUNNING,
        cycle_stage=WasherCyclePhase.WASHING,
        general_sensor_readings={"vibration": 0.1, "door_locked": True},
        special_sensor_readings={"water_level": 50.0, "water_temperature": 40.0},
    )
    assert service.handle_periodic_report(first_periodic_report) is ReportProcessingResult.ACCEPTED
    assert service.handle_periodic_report(first_periodic_report) is ReportProcessingResult.DUPLICATE

    assert service.handle_heartbeat_timeout("washer-01")
    machine = service.machines_registry["washer-01"]
    assert not machine.is_online

    recovery_report = WasherPeriodicReport(
        machine_id="washer-01",
        machine_type=MachineType.WASHER,
        report_id="periodic-02",
        recorded_at=recorded_at + timedelta(seconds=15),
        operation_state=OperationState.RUNNING,
        cycle_stage=WasherCyclePhase.WASHING,
        general_sensor_readings={"vibration": 0.1, "door_locked": True},
        special_sensor_readings={"water_level": 45.0, "water_temperature": 39.0},
    )
    assert service.handle_periodic_report(recovery_report) is ReportProcessingResult.ACCEPTED
    assert machine.is_online
    assert not machine.error_list

    state_report = WasherChangeOfStateReport(
        machine_id="washer-01",
        machine_type=MachineType.WASHER,
        report_id="state-01",
        recorded_at=recorded_at + timedelta(seconds=20),
        previous_operation_state=OperationState.RUNNING,
        new_operation_state=OperationState.PAUSED,
        previous_cycle_stage=WasherCyclePhase.WASHING,
        new_cycle_stage=WasherCyclePhase.WASHING,
        reason="Operator paused the machine",
    )
    assert service.handle_change_of_state_report(state_report) is ReportProcessingResult.ACCEPTED

    error_report = WasherErrorReport(
        machine_id="washer-01",
        machine_type=MachineType.WASHER,
        report_id="error-report-01",
        recorded_at=recorded_at + timedelta(seconds=25),
        error_id="door-error-01",
        error_code="door_fault",
        error_message="Door did not lock",
        error_source=ErrorSource.DEVICE,
        general_sensor_readings={"vibration": 0.1, "door_locked": False},
        special_sensor_readings={"water_level": 45.0, "water_temperature": 39.0},
    )
    assert service.handle_error_report(error_report) is ReportProcessingResult.ACCEPTED

    snapshot_files = list(fault_snapshot_directory.glob("fault-*.json"))
    assert len(snapshot_files) == 1
    snapshot_data = json.loads(snapshot_files[0].read_text(encoding="utf-8"))
    assert snapshot_data["fault"]["error_id"] == "door-error-01"
    assert [reading["report_id"] for reading in snapshot_data["sensor_readings"]] == [
        "periodic-01",
        "periodic-02",
        "error-report-01",
    ]
    assert [event["report_id"] for event in snapshot_data["state_events"]] == ["state-01"]

    assert service.acknowledge_error("washer-01", "door-error-01")
    assert machine.error_list["door-error-01"].is_acknowledged
    assert not service.acknowledge_error("washer-01", "missing-error")

    machine_statuses = service.list_machines()
    machine_status = service.get_machine("washer-01")
    reading_results = service.list_sensor_readings("washer-01", None, None, OperationState.RUNNING, 100)
    active_faults = service.list_faults(None, True, None, 100)
    acknowledged_faults = service.list_faults("washer-01", None, True, 100)

    assert len(machine_statuses) == 1
    assert machine_status is not None and machine_status.is_online
    assert machine_status.recorded_at == error_report.recorded_at
    assert machine_status.latest_reading is not None
    assert machine_status.latest_reading.general_readings.door_locked is False
    assert machine_statuses[0].latest_reading == machine_status.latest_reading
    assert reading_results is not None and len(reading_results) == 2
    assert active_faults is not None and [fault.error_id for fault in active_faults] == ["door-error-01"]
    assert acknowledged_faults is not None and [fault.error_id for fault in acknowledged_faults] == ["door-error-01"]

    assert service.resolve_error("washer-01", "door-error-01", "Door repaired")
    assert "door-error-01" not in machine.error_list

    assert service.machine_deregister("washer-01")

    with database_session_factory() as database_session:
        machine_record = database_session.get(MachineRecord, "washer-01")
        sensor_readings = database_session.scalars(select(SensorReadingRecord)).all()
        state_events = database_session.scalars(select(MachineStateEventRecord)).all()
        fault_events = database_session.scalars(select(FaultEventRecord)).all()

    assert machine_record is not None
    assert not machine_record.is_registered
    assert machine_record.operation_state is None
    assert machine_record.cycle_stage is None
    assert len(sensor_readings) == 3
    assert len(state_events) == 1
    assert len(fault_events) == 2

    heartbeat_fault = next(fault for fault in fault_events if fault.error_code == DiagnosticCode.DEVICE_COMMUNICATION_LOST.value)
    device_fault = next(fault for fault in fault_events if fault.error_id == "door-error-01")
    assert heartbeat_fault.resolved_at is not None
    assert heartbeat_fault.resolution_message == "Machine contact restored"
    assert not heartbeat_fault.is_acknowledged
    assert device_fault.resolved_at is not None
    assert device_fault.resolution_message == "Door repaired"
    assert device_fault.is_acknowledged

    fault_context = service.get_fault_context(device_fault.fault_event_id, 5)
    assert fault_context is not None
    assert fault_context.fault.error_id == "door-error-01"
    assert fault_context.window_end - fault_context.window_start == timedelta(minutes=5)
    assert [reading.report_id for reading in fault_context.sensor_readings] == [
        "periodic-01",
        "periodic-02",
        "error-report-01",
    ]
    assert [event.report_id for event in fault_context.state_events] == ["state-01"]
    assert fault_context.data_events == []
    assert service.get_fault_context(999_999, 5) is None


def test_machine_service_reactivates_existing_machine_record(database_session_factory: sessionmaker[Session]) -> None:
    service = MachineService(StubMachineMonitor())

    assert service.machine_register("dryer-01", MachineType.DRYER)
    assert service.machine_deregister("dryer-01")
    assert service.machine_register("dryer-01", MachineType.DRYER)

    with database_session_factory() as database_session:
        machine_records = database_session.scalars(select(MachineRecord)).all()

    assert len(machine_records) == 1
    assert machine_records[0].machine_id == "dryer-01"
    assert machine_records[0].is_registered


def test_device_error_resolution_updates_database_and_memory(database_session_factory: sessionmaker[Session]) -> None:
    service = MachineService(StubMachineMonitor())
    recorded_at = datetime(2026, 7, 22, 13, 0, tzinfo=UTC)
    assert service.machine_register("washer-02", MachineType.WASHER)

    error_report = WasherErrorReport(
        machine_id="washer-02",
        machine_type=MachineType.WASHER,
        report_id="error-report-02",
        recorded_at=recorded_at,
        error_id="water-error-01",
        error_code="water_fault",
        error_message="Water level is invalid",
        error_source=ErrorSource.DEVICE,
        general_sensor_readings={"vibration": 0.1, "door_locked": True},
        special_sensor_readings={"water_level": 10.0, "water_temperature": 40.0},
    )
    assert service.handle_error_report(error_report) is ReportProcessingResult.ACCEPTED

    resolution_report = WasherErrorResolutionReport(
        machine_id="washer-02",
        machine_type=MachineType.WASHER,
        report_id="resolution-02",
        recorded_at=recorded_at + timedelta(seconds=5),
        error_id="water-error-01",
        resolution_message="Water sensor recovered",
        operation_state=OperationState.IDLE,
        cycle_stage=None,
        general_sensor_readings={"vibration": 0.1, "door_locked": False},
        special_sensor_readings={"water_level": 0.0, "water_temperature": 20.0},
    )
    assert service.handle_error_resolution_report(resolution_report) is ReportProcessingResult.ACCEPTED
    machine = service.machines_registry["washer-02"]
    assert "water-error-01" not in machine.error_list
    assert machine.recorded_at == resolution_report.recorded_at
    assert machine.latest_reading is not None
    assert machine.latest_reading.special_readings.water_temperature == 20.0

    with database_session_factory() as database_session:
        fault_event = database_session.scalar(select(FaultEventRecord).where(FaultEventRecord.error_id == "water-error-01"))
        recovery_reading = database_session.scalar(select(SensorReadingRecord).where(SensorReadingRecord.report_id == "resolution-02"))

    assert fault_event is not None
    assert fault_event.resolved_at is not None
    assert fault_event.resolution_message == "Water sensor recovered"
    assert recovery_reading is not None
    assert recovery_reading.special_readings["water_temperature"] == 20.0


def test_periodic_reports_create_deduplicate_and_resolve_sensor_fault(database_session_factory: sessionmaker[Session]) -> None:
    service = MachineService(StubMachineMonitor())
    recorded_at = datetime(2026, 7, 22, 14, 0, tzinfo=UTC)
    assert service.machine_register("washer-03", MachineType.WASHER)

    abnormal_report = WasherPeriodicReport(
        machine_id="washer-03",
        machine_type=MachineType.WASHER,
        report_id="sensor-fault-report-01",
        recorded_at=recorded_at,
        operation_state=OperationState.RUNNING,
        cycle_stage=WasherCyclePhase.WASHING,
        general_sensor_readings={"vibration": 0.1, "door_locked": True},
        special_sensor_readings={"water_level": 50.0, "water_temperature": 85.0},
    )
    repeated_abnormal_report = abnormal_report.model_copy(update={"report_id": "sensor-fault-report-02", "recorded_at": recorded_at + timedelta(seconds=15)})
    normal_report = abnormal_report.model_copy(
        update={
            "report_id": "sensor-fault-report-03",
            "recorded_at": recorded_at + timedelta(seconds=30),
            "special_sensor_readings": abnormal_report.special_sensor_readings.model_copy(update={"water_temperature": 40.0}),
        }
    )

    assert service.handle_periodic_report(abnormal_report) is ReportProcessingResult.ACCEPTED
    assert service.handle_periodic_report(repeated_abnormal_report) is ReportProcessingResult.ACCEPTED
    assert len(service.machines_registry["washer-03"].error_list) == 1
    assert service.handle_periodic_report(normal_report) is ReportProcessingResult.ACCEPTED
    assert not service.machines_registry["washer-03"].error_list

    with database_session_factory() as database_session:
        sensor_faults = database_session.scalars(
            select(FaultEventRecord).where(
                FaultEventRecord.machine_id == "washer-03",
                FaultEventRecord.error_code == DiagnosticCode.WASHER_WATER_TEMPERATURE_HIGH.value,
            )
        ).all()

    assert len(sensor_faults) == 1
    assert sensor_faults[0].error_source is ErrorSource.ANALYTICS
    assert sensor_faults[0].resolved_at is not None
    assert sensor_faults[0].resolution_message == "Sensor readings returned to normal"


def test_state_report_gaps_are_stored_as_data_events(database_session_factory: sessionmaker[Session]) -> None:
    service = MachineService(StubMachineMonitor())
    assert service.machine_register("washer-04", MachineType.WASHER)
    recorded_at = datetime.now(UTC)

    baseline_report = WasherPeriodicReport(
        machine_id="washer-04",
        machine_type=MachineType.WASHER,
        report_id="baseline-report-04",
        recorded_at=recorded_at,
        operation_state=OperationState.IDLE,
        cycle_stage=None,
        general_sensor_readings={"vibration": 0.1, "door_locked": False},
        special_sensor_readings={"water_level": 0.0, "water_temperature": 20.0},
    )
    gap_report = baseline_report.model_copy(
        update={
            "report_id": "gap-report-04",
            "recorded_at": recorded_at + timedelta(seconds=15),
            "operation_state": OperationState.RUNNING,
            "cycle_stage": WasherCyclePhase.FILLING,
        }
    )
    mismatch_report = WasherChangeOfStateReport(
        machine_id="washer-04",
        machine_type=MachineType.WASHER,
        report_id="mismatch-report-04",
        recorded_at=recorded_at + timedelta(seconds=20),
        previous_operation_state=OperationState.RUNNING,
        new_operation_state=OperationState.RUNNING,
        previous_cycle_stage=WasherCyclePhase.WASHING,
        new_cycle_stage=WasherCyclePhase.WASHING,
    )

    assert service.handle_periodic_report(baseline_report) is ReportProcessingResult.ACCEPTED
    assert service.handle_periodic_report(gap_report) is ReportProcessingResult.ACCEPTED
    assert service.handle_change_of_state_report(mismatch_report) is ReportProcessingResult.ACCEPTED

    filtered_events = service.list_data_events("washer-04", DiagnosticCode.STATE_REPORT_GAP_DETECTED.value, 10)
    assert filtered_events is not None
    assert [event.event_code for event in filtered_events] == [DiagnosticCode.STATE_REPORT_GAP_DETECTED.value]
    assert service.list_data_events("missing-machine", None, 10) is None

    with database_session_factory() as database_session:
        data_events = database_session.scalars(select(DataEventRecord).order_by(DataEventRecord.data_event_id)).all()
        data_faults = database_session.scalars(
            select(FaultEventRecord).where(
                FaultEventRecord.error_code.in_(
                    {
                        DiagnosticCode.STATE_REPORT_GAP_DETECTED.value,
                        DiagnosticCode.STATE_SEQUENCE_MISMATCH.value,
                    }
                )
            )
        ).all()

    assert [event.event_code for event in data_events] == [
        DiagnosticCode.STATE_REPORT_GAP_DETECTED.value,
        DiagnosticCode.STATE_SEQUENCE_MISMATCH.value,
    ]
    assert data_events[0].event_details["stored_operation_state"] == OperationState.IDLE.value
    assert data_events[0].event_details["reported_operation_state"] == OperationState.RUNNING.value
    assert data_events[1].event_details["expected_previous_cycle_stage"] == WasherCyclePhase.FILLING.value
    assert data_events[1].event_details["reported_previous_cycle_stage"] == WasherCyclePhase.WASHING.value
    assert data_faults == []
