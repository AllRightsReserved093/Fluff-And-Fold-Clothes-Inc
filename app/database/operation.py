# Persist machine registration, reports, faults, and heartbeat events.
# 持久化机器注册、报告、故障与心跳事件。

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    FaultEventRecord,
    MachineRecord,
    MachineStateEventRecord,
    SensorReadingRecord,
)
from app.machines.machines import Machine
from laundry_contracts.contracts import (
    ChangeOfStateReport,
    ErrorReport,
    ErrorSource,
    FaultEventResponse,
    MachineError,
    MachineStatusResponse,
    OperationState,
    PeriodicReport,
    SensorReadingResponse,
    StateEventSource,
)


class DatabaseOperation:
    # Add a new machine record or reactivate an existing record.
    # 新增机器记录，或重新启用已有记录。
    def add_machine_record(self, database_session: Session, machine: Machine, registered_at: datetime):

        machine_record = database_session.get(MachineRecord, machine.machine_id)
        cycle_stage = machine.cycle_stage.value if machine.cycle_stage is not None else None

        if machine_record is None:
            machine_record = MachineRecord(
                machine_id=machine.machine_id,
                machine_type=machine.machine_type,
                is_registered=True,
                registered_at=registered_at,
                operation_state=machine.operation_state,
                cycle_stage=cycle_stage,
                last_online=machine.last_online,
                recorded_at=None,
            )
            database_session.add(machine_record)
            return

        machine_record.is_registered = True
        machine_record.registered_at = registered_at
        machine_record.operation_state = machine.operation_state
        machine_record.cycle_stage = cycle_stage
        machine_record.last_online = machine.last_online
        machine_record.recorded_at = None

    # Mark a machine record as no longer registered.
    def deregister_machine_record(self, database_session: Session, machine_id: str) -> bool:
        machine_record = database_session.get(MachineRecord, machine_id)

        if machine_record is None:
            return False

        machine_record.is_registered = False
        machine_record.operation_state = None
        machine_record.cycle_stage = None
        return True

    # Update one machine's latest valid device contact.
    # 更新一台机器最近一次有效的设备联系时间。
    def update_machine_contact(self, database_session: Session, machine_id: str, recorded_at: datetime) -> bool:
        machine_record = database_session.get(MachineRecord, machine_id)
        if machine_record is None or not machine_record.is_registered:
            return False

        machine_record.last_online = datetime.now(UTC)
        machine_record.recorded_at = recorded_at
        return True

    # Store a periodic reading and reconcile the current machine snapshot.
    def add_periodic_report(self, database_session: Session, report: PeriodicReport) -> bool:
        machine_record = database_session.get(MachineRecord, report.machine_id)
        if machine_record is None or not machine_record.is_registered:
            return False

        # Check if a reading with this report ID already exists
        existing_reading = database_session.scalar(
            select(SensorReadingRecord).where(
                SensorReadingRecord.machine_id == report.machine_id,
                SensorReadingRecord.report_id == report.report_id,
            )
        )
        if existing_reading is not None:
            # A reading with this report ID already exists
            return False

        # Assign cycle stage
        cycle_stage = report.cycle_stage.value if report.cycle_stage is not None else None

        # Check if the state has changed
        state_changed = False
        if machine_record.operation_state is not None:
            if machine_record.operation_state != report.operation_state:
                state_changed = True
            elif machine_record.cycle_stage != cycle_stage:
                state_changed = True


        if state_changed:
            # Record the state change
            # The change of state should have been reported by change_of_state_report, not periodic report
            # Update the machine record
            database_session.add(
                MachineStateEventRecord(
                    machine_id=report.machine_id,
                    report_id=report.report_id,
                    event_source=StateEventSource.PERIODIC_RECONCILIATION,
                    recorded_at=report.recorded_at,
                    previous_operation_state=machine_record.operation_state,
                    new_operation_state=report.operation_state,
                    previous_cycle_stage=machine_record.cycle_stage,
                    new_cycle_stage=cycle_stage,
                    reason="Inferred from a periodic report",
                )
            )
            # Record the fault
            database_session.add(
                FaultEventRecord(
                    error_id=f"state-report-gap-{uuid4()}",
                    machine_id=report.machine_id,
                    report_id=report.report_id,
                    error_code="state_change_report_missing",
                    error_message="Periodic report state differs from the stored state",
                    error_source=ErrorSource.ANALYTICS,
                    is_acknowledged=False,
                    raised_at=report.recorded_at,
                )
            )

        # Record the sensor readings history
        database_session.add(
            SensorReadingRecord(
                machine_id=report.machine_id,
                report_id=report.report_id,
                recorded_at=report.recorded_at,
                operation_state=report.operation_state,
                cycle_stage=cycle_stage,
                general_readings=report.general_sensor_readings.model_dump(mode="json"),
                special_readings=report.special_sensor_readings.model_dump(mode="json"),
            )
        )

        # Update the machine record
        machine_record.operation_state = report.operation_state
        machine_record.cycle_stage = cycle_stage
        machine_record.last_online = datetime.now(UTC)
        machine_record.recorded_at = report.recorded_at
        return True

    # Store a state-change report and update the current snapshot.
    def add_state_change_report(self, database_session: Session, report: ChangeOfStateReport) -> bool:
        machine_record = database_session.get(MachineRecord, report.machine_id)
        if machine_record is None or not machine_record.is_registered:
            return False

        # Check if a state change report already exists
        existing_event = database_session.scalar(
            select(MachineStateEventRecord).where(
                MachineStateEventRecord.machine_id == report.machine_id,
                MachineStateEventRecord.report_id == report.report_id,
            )
        )
        if existing_event is not None:
            return False

        # Get the previous cycle stage and new cycle stage
        previous_cycle_stage = report.previous_cycle_stage.value if report.previous_cycle_stage is not None else None
        new_cycle_stage = report.new_cycle_stage.value if report.new_cycle_stage is not None else None

        # Check for previous state mismatch
        previous_state_mismatch = False
        if machine_record.operation_state is not None:
            if machine_record.operation_state != report.previous_operation_state:
                previous_state_mismatch = True
            elif machine_record.cycle_stage != previous_cycle_stage:
                previous_state_mismatch = True

        if previous_state_mismatch:
            # Record the previous state mismatch
            # The system failed to record the previous state
            # Add a fault event
            database_session.add(
                FaultEventRecord(
                    error_id=f"state-history-mismatch-{uuid4()}",
                    machine_id=report.machine_id,
                    report_id=report.report_id,
                    error_code="state_history_mismatch",
                    error_message="Reported previous state differs from the stored state",
                    error_source=ErrorSource.ANALYTICS,
                    is_acknowledged=False,
                    raised_at=report.recorded_at,
                )
            )

        # Record the new state
        database_session.add(
            MachineStateEventRecord(
                machine_id=report.machine_id,
                report_id=report.report_id,
                event_source=StateEventSource.CHANGE_OF_STATE_REPORT,
                recorded_at=report.recorded_at,
                previous_operation_state=report.previous_operation_state,
                new_operation_state=report.new_operation_state,
                previous_cycle_stage=previous_cycle_stage,
                new_cycle_stage=new_cycle_stage,
                reason=report.reason,
            )
        )

        # Update the machine record
        machine_record.operation_state = report.new_operation_state
        machine_record.cycle_stage = new_cycle_stage
        machine_record.last_online = datetime.now(UTC)
        machine_record.recorded_at = report.recorded_at
        return True

    # Store an error report.
    def add_error_report(self, database_session: Session, report: ErrorReport) -> bool:
        machine_record = database_session.get(MachineRecord, report.machine_id)
        if machine_record is None or not machine_record.is_registered:
            return False

        existing_fault = database_session.scalar(
            select(FaultEventRecord).where(
                FaultEventRecord.machine_id == report.machine_id,
                FaultEventRecord.error_id == report.error_id,
            )
        )
        existing_reading = database_session.scalar(
            select(SensorReadingRecord).where(
                SensorReadingRecord.machine_id == report.machine_id,
                SensorReadingRecord.report_id == report.report_id,
            )
        )
        if existing_fault is not None or existing_reading is not None:
            return False

        state_report = report.change_of_state_report
        if report.change_of_state:
            if state_report is None:
                return False
        else:
            if state_report is not None:
                return False

        if state_report is not None:
            if state_report.machine_id != report.machine_id:
                return False
            if state_report.machine_type != report.machine_type:
                return False

        operation_state = None
        cycle_stage = None
        if state_report is not None:
            operation_state = state_report.new_operation_state
            cycle_stage = state_report.new_cycle_stage.value if state_report.new_cycle_stage is not None else None

        database_session.add(
            SensorReadingRecord(
                machine_id=report.machine_id,
                report_id=report.report_id,
                recorded_at=report.recorded_at,
                operation_state=operation_state,
                cycle_stage=cycle_stage,
                general_readings=report.general_sensor_readings.model_dump(mode="json"),
                special_readings=report.special_sensor_readings.model_dump(mode="json"),
            )
        )
        database_session.add(
            FaultEventRecord(
                error_id=report.error_id,
                machine_id=report.machine_id,
                report_id=report.report_id,
                error_code=report.error_code,
                error_message=report.error_message,
                error_source=report.error_source,
                is_acknowledged=False,
                raised_at=report.recorded_at,
            )
        )

        if state_report is not None:
            existing_event = database_session.scalar(
                select(MachineStateEventRecord).where(
                    MachineStateEventRecord.machine_id == report.machine_id,
                    MachineStateEventRecord.report_id == state_report.report_id,
                )
            )
            if existing_event is None:
                previous_cycle_stage = state_report.previous_cycle_stage.value if state_report.previous_cycle_stage is not None else None
                database_session.add(
                    MachineStateEventRecord(
                        machine_id=report.machine_id,
                        report_id=state_report.report_id,
                        event_source=StateEventSource.ERROR_REPORT,
                        recorded_at=state_report.recorded_at,
                        previous_operation_state=state_report.previous_operation_state,
                        new_operation_state=state_report.new_operation_state,
                        previous_cycle_stage=previous_cycle_stage,
                        new_cycle_stage=cycle_stage,
                        reason=state_report.reason,
                    )
                )

            machine_record.operation_state = operation_state
            machine_record.cycle_stage = cycle_stage
            machine_record.recorded_at = state_report.recorded_at
        else:
            machine_record.recorded_at = report.recorded_at

        machine_record.last_online = datetime.now(UTC)
        return True

    # Acknowledge one persisted fault without resolving it.
    def acknowledge_fault_event(self, database_session: Session, machine_id: str, error_id: str) -> bool:
        # Check if the fault event exists
        fault_event = database_session.scalar(
            select(FaultEventRecord).where(
                FaultEventRecord.machine_id == machine_id,
                FaultEventRecord.error_id == error_id,
            )
        )
        if fault_event is None:
            return False

        # Edit the fault event acknowledge status
        fault_event.is_acknowledged = True
        return True

    # Resolve one persisted fault without deleting its history.
    def resolve_fault_event(self, database_session: Session, machine_id: str, error_id: str, resolved_at: datetime, resolution_message: str | None) -> bool:
        fault_event = database_session.scalar(
            select(FaultEventRecord).where(
                FaultEventRecord.machine_id == machine_id,
                FaultEventRecord.error_id == error_id,
            )
        )
        if fault_event is None:
            return False

        if fault_event.resolved_at is None:
            fault_event.resolved_at = resolved_at
            fault_event.resolution_message = resolution_message
        return True

    # Store one heartbeat timeout fault event.
    def add_heartbeat_timeout(self, database_session: Session, machine_id: str, error: MachineError) -> bool:
        machine_record = database_session.get(MachineRecord, machine_id)
        if machine_record is None or not machine_record.is_registered:
            return False

        existing_fault = database_session.scalar(
            select(FaultEventRecord).where(
                FaultEventRecord.machine_id == machine_id,
                FaultEventRecord.error_id == error.error_id,
            )
        )
        if existing_fault is not None:
            return False

        database_session.add(
            FaultEventRecord(
                error_id=error.error_id,
                machine_id=machine_id,
                report_id=None,
                error_code=error.error_code,
                error_message=error.error_message,
                error_source=error.error_source,
                is_acknowledged=error.is_acknowledged,
                raised_at=error.raised_at,
            )
        )
        return True

    # Resolve every active heartbeat timeout fault after contact is restored.
    def resolve_heartbeat_timeout(self, database_session: Session, machine_id: str, resolved_at: datetime) -> int:
        fault_events = database_session.scalars(
            select(FaultEventRecord).where(
                FaultEventRecord.machine_id == machine_id,
                FaultEventRecord.error_source == ErrorSource.HEARTBEAT_MONITOR,
                FaultEventRecord.resolved_at.is_(None),
            )
        ).all()

        for fault_event in fault_events:
            fault_event.resolved_at = resolved_at
            fault_event.resolution_message = "Machine contact restored"

        return len(fault_events)

    # Create, retain, or automatically resolve detected sensor faults.
    # 新增、保留或自动解除检测到的传感器故障。
    def reconcile_sensor_faults(self, database_session: Session, report: PeriodicReport, detected_sensor_faults: dict[str, str], managed_error_codes: set[str]) -> tuple[list[MachineError], list[str]]:
        active_fault_events = database_session.scalars(
            select(FaultEventRecord).where(
                FaultEventRecord.machine_id == report.machine_id,
                FaultEventRecord.error_source == ErrorSource.ANALYTICS,
                FaultEventRecord.error_code.in_(managed_error_codes),
                FaultEventRecord.resolved_at.is_(None),
            )
        ).all()
        active_faults_by_code = {fault_event.error_code: fault_event for fault_event in active_fault_events}
        active_errors = []
        resolved_error_ids = []

        for error_code, error_message in detected_sensor_faults.items():
            fault_event = active_faults_by_code.get(error_code)
            if fault_event is None:
                fault_event = FaultEventRecord(
                    error_id=f"analytics-{error_code}-{uuid4()}",
                    machine_id=report.machine_id,
                    report_id=report.report_id,
                    error_code=error_code,
                    error_message=error_message,
                    error_source=ErrorSource.ANALYTICS,
                    is_acknowledged=False,
                    raised_at=report.recorded_at,
                )
                database_session.add(fault_event)

            raised_at = fault_event.raised_at
            if raised_at.tzinfo is None:
                raised_at = raised_at.replace(tzinfo=UTC)

            active_errors.append(
                MachineError(
                    error_id=fault_event.error_id,
                    error_code=fault_event.error_code,
                    error_message=fault_event.error_message,
                    error_source=fault_event.error_source,
                    is_acknowledged=fault_event.is_acknowledged,
                    raised_at=raised_at,
                )
            )

        for error_code, fault_event in active_faults_by_code.items():
            if error_code in detected_sensor_faults:
                continue

            fault_event.resolved_at = report.recorded_at
            fault_event.resolution_message = "Sensor readings returned to normal"
            resolved_error_ids.append(fault_event.error_id)

        return active_errors, resolved_error_ids

    # Return every stored machine status with its runtime online state.
    # 返回所有已保存的机器状态及其运行时在线状态。
    def list_machine_statuses(self, database_session: Session, online_machine_ids: set[str]) -> list[MachineStatusResponse]:
        machine_records = database_session.scalars(select(MachineRecord).order_by(MachineRecord.machine_id)).all()
        machine_statuses = []

        for machine_record in machine_records:
            machine_statuses.append(
                MachineStatusResponse(
                    machine_id=machine_record.machine_id,
                    machine_type=machine_record.machine_type,
                    is_registered=machine_record.is_registered,
                    is_online=machine_record.machine_id in online_machine_ids,
                    operation_state=machine_record.operation_state,
                    cycle_stage=machine_record.cycle_stage,
                    registered_at=machine_record.registered_at,
                    last_online=machine_record.last_online,
                    recorded_at=machine_record.recorded_at,
                )
            )

        return machine_statuses

    # Return one stored machine status by ID.
    # 根据 ID 返回一条已保存的机器状态。
    def get_machine_status(self, database_session: Session, machine_id: str, is_online: bool) -> MachineStatusResponse | None:
        machine_record = database_session.get(MachineRecord, machine_id)
        if machine_record is None:
            return None

        return MachineStatusResponse(
            machine_id=machine_record.machine_id,
            machine_type=machine_record.machine_type,
            is_registered=machine_record.is_registered,
            is_online=is_online,
            operation_state=machine_record.operation_state,
            cycle_stage=machine_record.cycle_stage,
            registered_at=machine_record.registered_at,
            last_online=machine_record.last_online,
            recorded_at=machine_record.recorded_at,
        )

    # Query one machine's sensor readings with basic filters.
    # 使用基础筛选条件查询一台机器的传感器读数。
    def list_sensor_readings(self, database_session: Session, machine_id: str, start_time: datetime | None, end_time: datetime | None, operation_state: OperationState | None, limit: int) -> list[SensorReadingResponse] | None:
        if database_session.get(MachineRecord, machine_id) is None:
            return None

        statement = select(SensorReadingRecord).where(SensorReadingRecord.machine_id == machine_id)
        if start_time is not None:
            statement = statement.where(SensorReadingRecord.recorded_at >= start_time)
        if end_time is not None:
            statement = statement.where(SensorReadingRecord.recorded_at <= end_time)
        if operation_state is not None:
            statement = statement.where(SensorReadingRecord.operation_state == operation_state)

        statement = statement.order_by(SensorReadingRecord.recorded_at.desc()).limit(limit)
        reading_records = database_session.scalars(statement).all()
        reading_results = []

        for reading_record in reading_records:
            reading_results.append(
                SensorReadingResponse(
                    reading_id=reading_record.reading_id,
                    machine_id=reading_record.machine_id,
                    report_id=reading_record.report_id,
                    recorded_at=reading_record.recorded_at,
                    received_at=reading_record.received_at,
                    operation_state=reading_record.operation_state,
                    cycle_stage=reading_record.cycle_stage,
                    general_readings=reading_record.general_readings,
                    special_readings=reading_record.special_readings,
                )
            )

        return reading_results

    # Query fault events across all machines or one selected machine.
    # 查询所有机器或指定机器的故障事件。
    def list_fault_events(self, database_session: Session, machine_id: str | None, is_active: bool | None, is_acknowledged: bool | None, limit: int) -> list[FaultEventResponse] | None:
        if machine_id is not None and database_session.get(MachineRecord, machine_id) is None:
            return None

        statement = select(FaultEventRecord)
        if machine_id is not None:
            statement = statement.where(FaultEventRecord.machine_id == machine_id)
        if is_active is True:
            statement = statement.where(FaultEventRecord.resolved_at.is_(None))
        elif is_active is False:
            statement = statement.where(FaultEventRecord.resolved_at.is_not(None))
        if is_acknowledged is not None:
            statement = statement.where(FaultEventRecord.is_acknowledged == is_acknowledged)

        statement = statement.order_by(FaultEventRecord.raised_at.desc()).limit(limit)
        fault_records = database_session.scalars(statement).all()
        fault_results = []

        for fault_record in fault_records:
            fault_results.append(
                FaultEventResponse(
                    fault_event_id=fault_record.fault_event_id,
                    machine_id=fault_record.machine_id,
                    report_id=fault_record.report_id,
                    error_id=fault_record.error_id,
                    error_code=fault_record.error_code,
                    error_message=fault_record.error_message,
                    error_source=fault_record.error_source,
                    is_acknowledged=fault_record.is_acknowledged,
                    raised_at=fault_record.raised_at,
                    resolved_at=fault_record.resolved_at,
                    resolution_message=fault_record.resolution_message,
                )
            )

        return fault_results
