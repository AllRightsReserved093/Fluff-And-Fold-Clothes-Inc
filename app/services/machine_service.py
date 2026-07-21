# Coordinate machine state, registration, reports, and heartbeat monitoring.
# 协调机器状态、注册、报告与心跳监控。

from threading import Lock

from app.machines import machine_monitor
from app.machines.machine_monitor import MachineMonitor
from app.machines.machines import Machine
from laundry_contracts.contracts import (
    ChangeOfStateReport,
    ErrorReport,
    MachineError,
    MachineType,
    PeriodicReport,
)


# Manage the in-memory machine registry and its monitor.
# 管理内存中的机器注册表及其监控器。
class MachineService:
    machines_registry: dict[str, Machine]
    machine_monitor: MachineMonitor
    machines_lock: Lock

    def __init__(self, machine_monitor: MachineMonitor | None = None) -> None:
        self.machines_registry: dict[str, Machine] = {}
        self.machine_monitor = machine_monitor if machine_monitor is not None else MachineMonitor(self.handle_heartbeat_timeout)
        self.machines_lock = Lock()


    # Register one machine and add it to heartbeat monitoring.
    # 注册一台机器，并将其加入心跳监控。
    def machine_register(self, machine_id: str, machine_type: MachineType) -> bool:
        with self.machines_lock:
            if not machine_id.strip():
                return False

            if machine_id in self.machines_registry:
                return False

            new_machine = Machine(machine_id, machine_type)
            new_machine.register()  

            self.machines_registry[machine_id] = new_machine
            self.machine_monitor.add_machine(new_machine)

            if not self.machine_monitor.is_working:
                self.machine_monitor.start_monitor()

            return True

    # Deregister one machine and remove it from heartbeat monitoring.
    # 注销一台机器，并将其移出心跳监控。
    def machine_deregister(self, machine_id: str) -> bool:
        with self.machines_lock:
            machine = self.machines_registry.get(machine_id)
            if machine is None:
                return False

            machine.deregister()
            self.machine_monitor.remove_machine(machine_id)
            del self.machines_registry[machine_id]
            return True

    # Apply a periodic report and refresh the machine heartbeat deadline.
    # 应用周期报告，并刷新机器的心跳截止时间。
    def handle_periodic_report(self, report: PeriodicReport) -> bool:
        with self.machines_lock:
            machine = self.machines_registry.get(report.machine_id)
            if machine is None:
                print(f"Machine with ID {report.machine_id} was not registered.")
                return False

            machine.mark_online()
            machine.update_state(
                report.operation_state,
                report.cycle_stage,
            )

            self.machine_monitor.update_machine(report.machine_id)
            return True

    # Apply a state-change report and refresh the heartbeat deadline.
    # 应用状态变化报告，并刷新心跳截止时间。
    def handle_change_of_state_report(self, report: ChangeOfStateReport) -> bool:
        with self.machines_lock:
            machine = self.machines_registry.get(report.machine_id)
            if machine is None:
                return False

            machine.mark_online()
            machine.update_state(
                report.new_operation_state,
                report.new_cycle_stage,
            )

            # Update log

            self.machine_monitor.update_machine(report.machine_id)
            return True

    def handle_error_report(self, report: ErrorReport) -> bool:
        with self.machines_lock:
            machine = self.machines_registry.get(report.machine_id)
            if machine is None:
                return False

            machine.mark_online()
            machine_error = MachineError(
                error_id=report.error_id,
                error_code=report.error_code,
                error_message=report.error_message,
                error_source=report.error_source,
                raised_at=report.recorded_at,
            )

            machine.add_error(machine_error)

            if report.change_of_state:
                machine.update_state(
                    report.change_of_state_report.new_operation_state,
                    report.change_of_state_report.new_cycle_stage,
                )

            self.machine_monitor.update_machine(report.machine_id)

            return True


    # Apply a heartbeat timeout reported by the monitor.
    # 应用监控器报告的心跳超时。
    def handle_heartbeat_timeout(self, machine_id: str) -> bool:
        with self.machines_lock:
            machine = self.machines_registry.get(machine_id)
            if machine is None:
                return False

            machine.set_error_heartbeat_timeout()
            return True


# Shared service instance for the application process.
# 当前应用进程共享的服务实例。
machine_service = MachineService()
