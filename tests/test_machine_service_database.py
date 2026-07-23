# Verify the complete MachineService persistence flow with in-memory SQLite.
# 使用内存 SQLite 验证 MachineService 的完整持久化流程。

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import FaultEventRecord, MachineRecord, MachineStateEventRecord, SensorReadingRecord
from app.machines.machines import Machine
from app.services import machine_service as machine_service_module
from app.services.machine_service import MachineService
from laundry_contracts.contracts import (
    ErrorResolutionReport,
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


def test_machine_service_persists_complete_lifecycle(database_session_factory: sessionmaker[Session]) -> None:
    monitor = StubMachineMonitor()
    service = MachineService(monitor)
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
    assert service.handle_periodic_report(first_periodic_report)
    assert not service.handle_periodic_report(first_periodic_report)

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
    assert service.handle_periodic_report(recovery_report)
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
    assert service.handle_change_of_state_report(state_report)

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
    assert service.handle_error_report(error_report)
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

    heartbeat_fault = next(fault for fault in fault_events if fault.error_code == MachineErrorCode.HEARTBEAT_TIMEOUT)
    device_fault = next(fault for fault in fault_events if fault.error_id == "door-error-01")
    assert heartbeat_fault.resolved_at is not None
    assert heartbeat_fault.resolution_message == "Machine contact restored"
    assert not heartbeat_fault.is_acknowledged
    assert device_fault.resolved_at is not None
    assert device_fault.resolution_message == "Door repaired"
    assert device_fault.is_acknowledged


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
    assert service.handle_error_report(error_report)

    resolution_report = ErrorResolutionReport(
        machine_id="washer-02",
        machine_type=MachineType.WASHER,
        report_id="resolution-02",
        recorded_at=recorded_at + timedelta(seconds=5),
        error_id="water-error-01",
        resolution_message="Water sensor recovered",
    )
    assert service.handle_error_resolution_report(resolution_report)
    assert "water-error-01" not in service.machines_registry["washer-02"].error_list

    with database_session_factory() as database_session:
        fault_event = database_session.scalar(select(FaultEventRecord).where(FaultEventRecord.error_id == "water-error-01"))

    assert fault_event is not None
    assert fault_event.resolved_at is not None
    assert fault_event.resolution_message == "Water sensor recovered"


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

    assert service.handle_periodic_report(abnormal_report)
    assert service.handle_periodic_report(repeated_abnormal_report)
    assert len(service.machines_registry["washer-03"].error_list) == 1
    assert service.handle_periodic_report(normal_report)
    assert not service.machines_registry["washer-03"].error_list

    with database_session_factory() as database_session:
        sensor_faults = database_session.scalars(
            select(FaultEventRecord).where(
                FaultEventRecord.machine_id == "washer-03",
                FaultEventRecord.error_code == "washer_water_temperature_high",
            )
        ).all()

    assert len(sensor_faults) == 1
    assert sensor_faults[0].error_source is ErrorSource.ANALYTICS
    assert sensor_faults[0].resolved_at is not None
    assert sensor_faults[0].resolution_message == "Sensor readings returned to normal"
