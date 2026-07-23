# Coordinate machine state, registration, reports, and heartbeat monitoring.
# 协调机器状态、注册、报告与心跳监控。

import logging
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from app.database.operation import DatabaseOperation
from app.database.session import SessionFactory
from app.machines import machine_monitor
from app.machines.machine_monitor import MachineMonitor
from app.machines.machines import Machine
from app.services.fault_snapshot import DEFAULT_FAULT_SNAPSHOT_DIRECTORY, FAULT_SNAPSHOT_WINDOW_MINUTES, save_fault_snapshot
from app.services.sensor_fault_analyzer import SENSOR_FAULT_ERROR_CODES, detect_sensor_faults
from laundry_contracts.contracts import (
    ChangeOfStateReport,
    DataEventResponse,
    ErrorReport,
    ErrorResolutionReport,
    FaultContextResponse,
    FaultEventResponse,
    MachineError,
    MachineStatusResponse,
    MachineType,
    OperationState,
    PeriodicReport,
    ReportProcessingResult,
    SensorReadingResponse,
)


logger = logging.getLogger(__name__)


# Manage the in-memory machine registry and its monitor.
# 管理内存中的机器注册表及其监控器。
class MachineService:
    machines_registry: dict[str, Machine]
    machine_monitor: MachineMonitor
    machines_lock: Lock
    database_operation: DatabaseOperation
    fault_snapshot_directory: Path | None

    def __init__(self, machine_monitor: MachineMonitor | None = None, fault_snapshot_directory: Path | None = None) -> None:
        self.machines_registry: dict[str, Machine] = {}
        self.machine_monitor = machine_monitor if machine_monitor is not None else MachineMonitor(self.handle_heartbeat_timeout)
        self.machines_lock = Lock()
        self.database_operation = DatabaseOperation()
        self.fault_snapshot_directory = fault_snapshot_directory

    # Stop the heartbeat monitor owned by this service.
    # 停止当前服务持有的心跳监控器。
    def shutdown(self) -> None:
        self.machine_monitor.end_monitor()

    # Record a valid device contact and recover it when previously offline.
    # 记录一次有效设备联系，并在机器此前离线时恢复上线。
    def _record_machine_contact(self, machine: Machine, recorded_at: datetime) -> None:
        machine.recorded_at = recorded_at

        if machine.is_online:
            machine.mark_online()
            return

        machine.recover_online()

    def machine_monitor_shutdown(self) -> None:
        self.machine_monitor.end_monitor()


    # Register one machine and add it to heartbeat monitoring.
    # 注册一台机器，并将其加入心跳监控。
    def machine_register(self, machine_id: str, machine_type: MachineType) -> bool:
        with self.machines_lock:
            # Validation check
            if not machine_id.strip():
                return False
            if machine_type is None:
                return False
            if machine_id in self.machines_registry:
                return False

            # Initialize the new machine
            new_machine = Machine(machine_id, machine_type)
            new_machine.register()  

            # Database operation
            with SessionFactory.begin() as database_session:
                self.database_operation.add_machine_record(database_session, new_machine, datetime.now(UTC))

            # Add the machine to the registry
            self.machines_registry[machine_id] = new_machine

            # Add the machine to the monitor and start the monitor if it's not already working
            self.machine_monitor.add_machine(new_machine)
            if not self.machine_monitor.is_working:
                self.machine_monitor.start_monitor()

            return True

    # Deregister one machine and remove it from heartbeat monitoring.
    # 注销一台机器，并将其移出心跳监控。
    def machine_deregister(self, machine_id: str) -> bool:
        with self.machines_lock:
            # Validation check
            machine = self.machines_registry.get(machine_id)
            if machine is None:
                return False

            # Database operation
            with SessionFactory.begin() as database_session:
                if not self.database_operation.deregister_machine_record(database_session, machine_id):
                    return False

            # Deregister the machine
            machine.deregister()

            # Remove the machine from the monitor and registry
            self.machine_monitor.remove_machine(machine_id)
            del self.machines_registry[machine_id]
            return True

    # Apply a periodic report and refresh the machine heartbeat deadline.
    # 应用周期报告，并刷新机器的心跳截止时间。
    def handle_periodic_report(self, report: PeriodicReport) -> ReportProcessingResult:
        with self.machines_lock:
            # Validation check
            machine = self.machines_registry.get(report.machine_id)
            if machine is None:
                print(f"Machine with ID {report.machine_id} was not registered.")
                return ReportProcessingResult.NOT_FOUND

            detected_sensor_faults = detect_sensor_faults(report)

            # Database operation
            with SessionFactory.begin() as database_session:
                processing_result = self.database_operation.add_periodic_report(database_session, report)
                if processing_result is not ReportProcessingResult.ACCEPTED:
                    return processing_result
                if not machine.is_online:
                    self.database_operation.resolve_heartbeat_timeout(database_session, report.machine_id, datetime.now(UTC))
                active_sensor_faults, resolved_sensor_fault_ids = self.database_operation.reconcile_sensor_faults(database_session, report, detected_sensor_faults, SENSOR_FAULT_ERROR_CODES)

            # Update the machine state
            self._record_machine_contact(machine, report.recorded_at)
            machine.update_state(report.operation_state, report.cycle_stage)
            machine.update_latest_reading(report.recorded_at, report.general_sensor_readings, report.special_sensor_readings)

            # Update active sensor faults in memory.
            # 更新内存中的活动传感器故障。
            for sensor_fault in active_sensor_faults:
                if sensor_fault.error_id not in machine.error_list:
                    machine.add_error(sensor_fault)

            for error_id in resolved_sensor_fault_ids:
                if error_id in machine.error_list:
                    machine.remove_error(error_id)

            # Update the machine in the monitor
            self.machine_monitor.update_machine(report.machine_id)
            return ReportProcessingResult.ACCEPTED

    # Apply a state-change report and refresh the heartbeat deadline.
    # 应用状态变化报告，并刷新心跳截止时间。
    def handle_change_of_state_report(self, report: ChangeOfStateReport) -> ReportProcessingResult:
        with self.machines_lock:
            # Validation check
            machine = self.machines_registry.get(report.machine_id)
            if machine is None:
                return ReportProcessingResult.NOT_FOUND

            # Database operation
            with SessionFactory.begin() as database_session:
                processing_result = self.database_operation.add_state_change_report(database_session, report)
                if processing_result is not ReportProcessingResult.ACCEPTED:
                    return processing_result
                if not machine.is_online:
                    self.database_operation.resolve_heartbeat_timeout(database_session, report.machine_id, datetime.now(UTC))

            # Update the machine state
            self._record_machine_contact(machine, report.recorded_at)
            machine.update_state(report.new_operation_state, report.new_cycle_stage)

            # Update the machine in the monitor
            self.machine_monitor.update_machine(report.machine_id)
            return ReportProcessingResult.ACCEPTED

    # Apply an error report and refresh the machine heartbeat deadline.
    # 应用错误报告，并刷新机器的心跳截止时间。
    def handle_error_report(self, report: ErrorReport) -> ReportProcessingResult:
        with self.machines_lock:
            # Validation check
            machine = self.machines_registry.get(report.machine_id)
            if machine is None:
                return ReportProcessingResult.NOT_FOUND

            # Database operation
            with SessionFactory.begin() as database_session:
                processing_result = self.database_operation.add_error_report(database_session, report)
                if processing_result is not ReportProcessingResult.ACCEPTED:
                    return processing_result
                if not machine.is_online:
                    self.database_operation.resolve_heartbeat_timeout(database_session, report.machine_id, datetime.now(UTC))
                fault_context = None
                if self.fault_snapshot_directory is not None:
                    database_session.flush()
                    fault_context = self.database_operation.get_fault_context_by_error_id(
                        database_session,
                        report.machine_id,
                        report.error_id,
                        FAULT_SNAPSHOT_WINDOW_MINUTES,
                    )

            # Update the machine state
            self._record_machine_contact(machine, report.recorded_at)
            machine.update_latest_reading(report.recorded_at, report.general_sensor_readings, report.special_sensor_readings)
            machine_error = MachineError(
                error_id=report.error_id,
                error_code=report.error_code,
                error_message=report.error_message,
                error_source=report.error_source,
                raised_at=report.recorded_at,
            )

            machine.add_error(machine_error)

            if report.change_of_state:
                machine.update_state(report.change_of_state_report.new_operation_state, report.change_of_state_report.new_cycle_stage)

            # Update the machine in the monitor
            self.machine_monitor.update_machine(report.machine_id)

            if fault_context is not None:
                try:
                    save_fault_snapshot(fault_context, self.fault_snapshot_directory)
                except OSError:
                    logger.exception("Failed to save fault snapshot for fault %s", fault_context.fault.fault_event_id)

            return ReportProcessingResult.ACCEPTED

    # Apply a device error-resolution report and refresh the heartbeat deadline.
    # 应用设备错误解除报告，并刷新心跳截止时间。
    def handle_error_resolution_report(self, report: ErrorResolutionReport) -> ReportProcessingResult:
        with self.machines_lock:
            # Validation check
            machine = self.machines_registry.get(report.machine_id)
            if machine is None:
                return ReportProcessingResult.NOT_FOUND

            detected_sensor_faults = detect_sensor_faults(report)

            # Database operation
            with SessionFactory.begin() as database_session:
                processing_result = self.database_operation.add_error_resolution_report(database_session, report)
                if processing_result is not ReportProcessingResult.ACCEPTED:
                    return processing_result
                self.database_operation.update_machine_contact(database_session, report.machine_id, report.recorded_at)
                if not machine.is_online:
                    self.database_operation.resolve_heartbeat_timeout(database_session, report.machine_id, datetime.now(UTC))
                active_sensor_faults, resolved_sensor_fault_ids = self.database_operation.reconcile_sensor_faults(database_session, report, detected_sensor_faults, SENSOR_FAULT_ERROR_CODES)

            # Update the machine state
            self._record_machine_contact(machine, report.recorded_at)
            machine.update_latest_reading(report.recorded_at, report.general_sensor_readings, report.special_sensor_readings)
            if report.error_id in machine.error_list:
                machine.remove_error(report.error_id)

            for sensor_fault in active_sensor_faults:
                if sensor_fault.error_id not in machine.error_list:
                    machine.add_error(sensor_fault)

            for error_id in resolved_sensor_fault_ids:
                if error_id in machine.error_list:
                    machine.remove_error(error_id)

            # Update the machine in the monitor
            self.machine_monitor.update_machine(report.machine_id)
            return ReportProcessingResult.ACCEPTED

    # Acknowledge one persisted machine error without resolving it.
    # 确认一条已保存的机器错误，但不解除该错误。
    def acknowledge_error(self, machine_id: str, error_id: str) -> bool:
        with self.machines_lock:
            # Validation check
            machine = self.machines_registry.get(machine_id)
            if machine is None:
                return False

            # Database operation
            with SessionFactory.begin() as database_session:
                if not self.database_operation.acknowledge_fault_event(database_session, machine_id, error_id):
                    return False

            # Update the machine error
            machine_error = machine.error_list.get(error_id)
            if machine_error is not None:
                machine_error.is_acknowledged = True

            return True

    # Manually resolve one persisted machine error.
    # 手动解除一条已保存的机器错误。
    def resolve_error(self, machine_id: str, error_id: str, resolution_message: str | None) -> bool:
        with self.machines_lock:
            # Validation check
            machine = self.machines_registry.get(machine_id)
            if machine is None:
                return False

            # Database operation
            with SessionFactory.begin() as database_session:
                if not self.database_operation.resolve_fault_event(database_session, machine_id, error_id, datetime.now(UTC), resolution_message):
                    return False

            # Update the machine error
            if error_id in machine.error_list:
                machine.remove_error(error_id)

            return True

    # Apply a heartbeat timeout reported by the monitor.
    # 应用监控器报告的心跳超时。
    def handle_heartbeat_timeout(self, machine_id: str) -> bool:
        with self.machines_lock:
            # Validation check
            machine = self.machines_registry.get(machine_id)
            if machine is None:
                return False

            # Update the machine state
            machine.set_error_heartbeat_timeout()

            # Database operation
            heartbeat_error = list(machine.error_list.values())[-1]
            with SessionFactory.begin() as database_session:
                if not self.database_operation.add_heartbeat_timeout(database_session, machine_id, heartbeat_error):
                    return False

            return True

    # Return all known machine statuses.
    # 返回所有已知机器的状态。
    def list_machines(self) -> list[MachineStatusResponse]:
        with self.machines_lock:
            online_machine_ids = set()
            for machine_id, machine in self.machines_registry.items():
                if machine.is_online:
                    online_machine_ids.add(machine_id)

            with SessionFactory() as database_session:
                machine_statuses = self.database_operation.list_machine_statuses(database_session, online_machine_ids)

            for machine_status in machine_statuses:
                machine = self.machines_registry.get(machine_status.machine_id)
                if machine is None:
                    continue

                machine_status.recorded_at = machine.recorded_at
                machine_status.latest_reading = machine.latest_reading

            return machine_statuses

    # Return one known machine status.
    # 返回一台已知机器的状态。
    def get_machine(self, machine_id: str) -> MachineStatusResponse | None:
        with self.machines_lock:
            is_online = False
            machine = self.machines_registry.get(machine_id)
            if machine is not None:
                is_online = machine.is_online

            with SessionFactory() as database_session:
                machine_status = self.database_operation.get_machine_status(database_session, machine_id, is_online)

            if machine_status is not None and machine is not None:
                machine_status.recorded_at = machine.recorded_at
                machine_status.latest_reading = machine.latest_reading

            return machine_status

    # Return filtered sensor readings for one known machine.
    # 返回一台已知机器经过筛选的传感器读数。
    def list_sensor_readings(self, machine_id: str, start_time: datetime | None, end_time: datetime | None, operation_state: OperationState | None, limit: int) -> list[SensorReadingResponse] | None:
        with SessionFactory() as database_session:
            return self.database_operation.list_sensor_readings(database_session, machine_id, start_time, end_time, operation_state, limit)

    # Return filtered immutable data events across all machines or one known machine.
    # 返回所有机器或一台已知机器经过筛选的不可变数据事件。
    def list_data_events(self, machine_id: str | None, event_code: str | None, limit: int) -> list[DataEventResponse] | None:
        with SessionFactory() as database_session:
            return self.database_operation.list_data_events(database_session, machine_id, event_code, limit)

    # Return one fault with the persisted machine history preceding it.
    # 返回一条故障及其发生前已保存的机器历史。
    def get_fault_context(self, fault_event_id: int, minutes: int) -> FaultContextResponse | None:
        with SessionFactory() as database_session:
            return self.database_operation.get_fault_context(database_session, fault_event_id, minutes)

    # Return filtered fault events across all machines or one known machine.
    # 返回所有机器或一台已知机器经过筛选的故障事件。
    def list_faults(self, machine_id: str | None, is_active: bool | None, is_acknowledged: bool | None, limit: int) -> list[FaultEventResponse] | None:
        with SessionFactory() as database_session:
            return self.database_operation.list_fault_events(database_session, machine_id, is_active, is_acknowledged, limit)


# Shared service instance for the application process.
# 当前应用进程共享的服务实例。
machine_service = MachineService(fault_snapshot_directory=DEFAULT_FAULT_SNAPSHOT_DIRECTORY)
