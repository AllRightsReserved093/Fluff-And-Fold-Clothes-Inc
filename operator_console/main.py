# Run a command-driven ASCII dashboard with automatic backend refresh.
# 运行一个支持命令交互并自动刷新后端数据的 ASCII 仪表板。
#
# Textual is kept only as a small event-loop and input layer. The screen has
# two widgets: one plain-text output area and one command input box.
# Textual 只负责事件循环和输入；整个界面只有纯文本信息区和命令输入框两个组件。

import argparse
import asyncio
from datetime import datetime

from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Input, RichLog

from laundry_contracts.contracts import DataEventResponse, FaultContextResponse, FaultEventResponse, MachineStatusResponse
from operator_console.api_client import DEFAULT_API_BASE_URL, OperatorApiClient, OperatorApiError
from operator_console.views import build_dashboard_text, build_diagnostics_text, build_fault_context_text


DEFAULT_REFRESH_INTERVAL_SECONDS = 2.0
HELP_TEXT = (
    "Commands:\n"
    "  help\n"
    "  refresh\n"
    "  diagnostics\n"
    "  diagnostics machine <machine_id>\n"
    "  diagnostics fault <fault_id>\n"
    "  dashboard\n"
    "  ack <fault_id>\n"
    "  resolve <fault_id> [message]\n"
    "  quit"
)

# Display live data and translate submitted text commands into API calls.
# 显示实时数据，并把用户提交的文本命令转换成 API 调用。
class OperatorConsoleApp(App[None]):
    TITLE = "Fluff & Fold Operator Console"

    # RichLog occupies the remaining screen space; Input keeps its default height.
    # RichLog 占用剩余屏幕空间，Input 保持默认输入框高度。
    CSS = """
    #output {
        height: 1fr;
    }
    #command {
        height: 1;
        border: none;
        padding: 0;
        background: transparent;
    }
    #command:focus {
        border: none;
    }
    """

    def __init__(
        self,
        api_base_url: str = DEFAULT_API_BASE_URL,
        refresh_interval_seconds: float = DEFAULT_REFRESH_INTERVAL_SECONDS,
        api_client: OperatorApiClient | None = None,
    ) -> None:
        super().__init__()
        self.api_client = api_client or OperatorApiClient(api_base_url)
        self.refresh_interval_seconds = refresh_interval_seconds
        self.machines: list[MachineStatusResponse] = []
        self.faults: list[FaultEventResponse] = []
        self.resolved_faults: list[FaultEventResponse] = []
        self.data_events: list[DataEventResponse] = []
        self.fault_context: FaultContextResponse | None = None
        self.context_fault_id: int | None = None
        self.view_mode = "dashboard"
        self.diagnostic_machine_id: str | None = None
        self.backend_online = False
        self.last_refresh_at: datetime | None = None
        self.status_message = "Connecting to backend..."

    # Define the complete interface: one scrollable output area and one command line.
    # 定义完整界面：一个可滚动的信息区和一行命令输入框。
    def compose(self) -> ComposeResult:
        yield RichLog(id="output", wrap=False, highlight=False, markup=False, auto_scroll=False)
        yield Input(placeholder="> command", id="command")

    # Fetch immediately, schedule later refreshes, and keep keyboard focus in the command box.
    # 启动后立即获取数据、安排后续刷新，并让键盘焦点停留在命令输入框。
    def on_mount(self) -> None:
        self.query_one("#command", Input).focus()
        self.refresh_view()
        self.set_interval(self.refresh_interval_seconds, self.refresh_view)

    # Release the HTTP connection pool when Textual shuts down.
    # Textual 关闭时释放 HTTP 连接池。
    async def on_unmount(self) -> None:
        await self.api_client.close()

    # Refresh only the data required by the current view without blocking command input.
    # 只刷新当前视图所需的数据，同时不阻塞命令输入。
    @work(exclusive=True, group="view-refresh")
    async def refresh_view(self) -> None:
        # Check if the application is still running
        if not self.is_running:
            return

        connection_was_online = self.backend_online
        try:
            if self.view_mode == "fault_context":
                # fault context page
                if self.context_fault_id is None:
                    return
                self.fault_context = await self.api_client.get_fault_context(self.context_fault_id)

            elif self.view_mode == "diagnostics":
                # diagnostics page
                if self.diagnostic_machine_id is None:
                    # Get all faults, resolved faults, and data events
                    faults, resolved_faults, data_events = await asyncio.gather(
                        self.api_client.list_faults(active=True),
                        self.api_client.list_faults(active=False),
                        self.api_client.list_data_events(),
                    )
                else:
                    # Get the faults for the specified machine
                    faults, resolved_faults, data_events = await asyncio.gather(
                        self.api_client.list_machine_faults(self.diagnostic_machine_id, active=True),
                        self.api_client.list_machine_faults(self.diagnostic_machine_id, active=False),
                        self.api_client.list_data_events(machine_id=self.diagnostic_machine_id),
                    )

                # Update the view with the new data
                self.faults = sorted(faults, key=lambda fault: fault.raised_at, reverse=True)
                self.resolved_faults = sorted(resolved_faults, key=lambda fault: fault.raised_at, reverse=True)
                self.data_events = sorted(data_events, key=lambda event: event.recorded_at, reverse=True)
            else:
                # dashboard page
                machines, faults = await asyncio.gather(
                    self.api_client.list_machines(),
                    self.api_client.list_faults(active=True),
                )
                self.machines = sorted(machines, key=lambda machine: machine.machine_id)
                self.faults = sorted(faults, key=lambda fault: fault.raised_at, reverse=True)
            
        except OperatorApiError as error:
            if not self.is_running:
                return
            self.backend_online = False
            self.status_message = str(error)
            self._render_current_view()
            return

        if not self.is_running:
            return

        # Update the status message
        self.backend_online = True
        self.last_refresh_at = datetime.now().astimezone()
        if not connection_was_online:
            self.status_message = "Connected. Type 'help' to list commands."
        self._render_current_view()

    # Replace the complete output with a newly generated ASCII snapshot.
    # 使用新生成的 ASCII 快照替换整个信息区。
    def _render_current_view(self) -> None:
        output = self.query_one("#output", RichLog)
        output.clear()
        if self.view_mode == "fault_context":
            output.write(build_fault_context_text(self.fault_context, self.context_fault_id, self.status_message))
        elif self.view_mode == "diagnostics":
            output.write(
                build_diagnostics_text(
                    self.faults,
                    self.resolved_faults,
                    self.data_events,
                    self.diagnostic_machine_id,
                    self.backend_online,
                    self.last_refresh_at,
                    self.status_message,
                )
            )
        else:
            output.write(
                build_dashboard_text(
                    self.machines,
                    self.faults,
                    self.backend_online,
                    self.last_refresh_at,
                    self.status_message,
                )
            )

    # Input.Submitted is emitted when the user presses Enter in the command box.
    # 用户在命令输入框中按下 Enter 时，Textual 会发送 Input.Submitted 事件。
    def on_input_submitted(self, event: Input.Submitted) -> None:
        command_text = event.value.strip()
        event.input.value = ""
        if not command_text:
            return

        parts = command_text.split(maxsplit=2)
        command = parts[0].lower()

        # Command handling
        if command == "help":
            self.status_message = HELP_TEXT
            self._render_current_view()
        elif command == "refresh":
            self.status_message = "Refreshing..."
            self._render_current_view()
            self.refresh_view()
        elif command == "diagnostics":
            if len(parts) == 1:
                self.diagnostic_machine_id = None
                self.context_fault_id = None
                self.view_mode = "diagnostics"
            elif len(parts) == 3 and parts[1].lower() == "machine":
                self.diagnostic_machine_id = parts[2]
                self.context_fault_id = None
                self.view_mode = "diagnostics"
            elif len(parts) == 3 and parts[1].lower() == "fault":
                try:
                    fault_event_id = int(parts[2])
                except ValueError:
                    self._show_usage("Fault ID must be an integer")
                    return
                if fault_event_id < 1:
                    self._show_usage("Fault ID must be greater than zero")
                    return
                self.context_fault_id = fault_event_id
                self.fault_context = None
                self.view_mode = "fault_context"
            else:
                self._show_usage("Usage: diagnostics [machine <machine_id> | fault <fault_id>]")
                return
            self.status_message = "Refreshing diagnostics..."
            self._render_current_view()
            self.refresh_view()
        elif command == "dashboard":
            if len(parts) != 1:
                self._show_usage("Usage: dashboard")
                return
            self.view_mode = "dashboard"
            self.context_fault_id = None
            self.status_message = "Refreshing dashboard..."
            self._render_current_view()
            self.refresh_view()
        elif command == "ack":
            if len(parts) != 2:
                self._show_usage("Usage: ack <fault_id>")
                return
            fault = self._find_active_fault(parts[1])
            if fault is None:
                return
            self._acknowledge_fault(fault)
        elif command == "resolve":
            if len(parts) < 2:
                self._show_usage("Usage: resolve <fault_id> [message]")
                return
            fault = self._find_active_fault(parts[1])
            if fault is None:
                return
            resolution_message = parts[2] if len(parts) == 3 else "Manually resolved from the operator console"
            self._resolve_fault(fault, resolution_message)
        elif command == "quit":
            self.exit()
        else:
            # Undefined command
            self._show_usage(f"Unknown command: {command}\nType 'help' to list commands.")

    # Find the active fault represented by the short database identifier shown to the operator.
    # 根据显示给操作员的数据库短编号查找活动故障。
    def _find_active_fault(self, fault_id_text: str) -> FaultEventResponse | None:
        try:
            fault_event_id = int(fault_id_text)
        except ValueError:
            self._show_usage("Fault ID must be an integer")
            return None

        for fault in self.faults:
            if fault.fault_event_id == fault_event_id:
                return fault

        self._show_usage(f"Active fault {fault_event_id} was not found")
        return None

    # Send one acknowledgement command; repeated commands cannot create stacked workers.
    # 发送一次确认命令；连续输入时不会堆积多个故障操作 Worker。
    @work(exclusive=True, group="fault-action")
    async def _acknowledge_fault(self, fault: FaultEventResponse) -> None:
        try:
            await self.api_client.acknowledge_fault(fault.machine_id, fault.error_id)
        except OperatorApiError as error:
            if not self.is_running:
                return
            self.status_message = str(error)
            self._render_current_view()
            return

        if not self.is_running:
            return
        self.status_message = f"Acknowledged fault {fault.fault_event_id} on {fault.machine_id}"
        self.refresh_view()

    # Send one manual resolution command and refresh the complete fault snapshot afterward.
    # 发送一次手动解除命令，成功后重新获取完整故障快照。
    @work(exclusive=True, group="fault-action")
    async def _resolve_fault(self, fault: FaultEventResponse, resolution_message: str) -> None:
        try:
            await self.api_client.resolve_fault(fault.machine_id, fault.error_id, resolution_message)
        except OperatorApiError as error:
            if not self.is_running:
                return
            self.status_message = str(error)
            self._render_current_view()
            return

        if not self.is_running:
            return
        self.status_message = f"Resolved fault {fault.fault_event_id} on {fault.machine_id}"
        self.refresh_view()

    def _show_usage(self, message: str) -> None:
        self.status_message = message
        self._render_current_view()

# Parse the optional backend address and start Textual's event loop.
# 解析可选后端地址，然后启动 Textual 事件循环。
def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Fluff & Fold operator console")
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    arguments = parser.parse_args()
    OperatorConsoleApp(api_base_url=arguments.api_base_url).run()


if __name__ == "__main__":
    main()
