# Build the operator console's plain ASCII views.

import json
from datetime import datetime

from laundry_contracts.contracts import DataEventResponse, FaultContextResponse, FaultEventResponse, MachineStatusResponse
from laundry_contracts.fault_codes import DIAGNOSTIC_DEFINITIONS, DiagnosticCode


# --------- Diagnostic Helpers ---------
# Resolve one diagnostic code to its catalog kind and severity.
def _diagnostic_metadata(code_value: str) -> tuple[str, str]:
    code = DiagnosticCode(code_value)
    definition = DIAGNOSTIC_DEFINITIONS[code]
    return definition.kind.value, definition.severity.value

# Convert a Boolean value into a compact table label.
def _yes_no(value: bool) -> str:
    return "yes" if value else "no"

# --------- Table Formatting ---------
# Build a plain ASCII table from headers and rows.
def _format_time(value: datetime | None) -> str:
    return value.isoformat(sep=" ", timespec="seconds") if value is not None else "-"

# Format historical sensor values to one decimal place without changing stored data.
def _format_sensor_readings(readings: dict[str, object]) -> str:
    formatted_readings = {}
    for name, value in readings.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = round(value, 1)
        formatted_readings[name] = value
    return json.dumps(formatted_readings, ensure_ascii=False, sort_keys=True)

# Build an aligned ASCII table from a title, headers, and rows.
def build_ascii_table(title: str, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    if not rows:
        return f"{title}\n(no data)"

    widths = []
    for column_index, header in enumerate(headers):
        column_width = len(header)
        for row in rows:
            column_width = max(column_width, len(row[column_index]))
        widths.append(column_width)

    # Build one padded row using the calculated column widths.
    def build_row(values: tuple[str, ...]) -> str:
        cells = [value.ljust(widths[index]) for index, value in enumerate(values)]
        return "| " + " | ".join(cells) + " |"

    border = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    lines = [title, border, build_row(headers), border]
    lines.extend(build_row(row) for row in rows)
    lines.append(border)
    return "\n".join(lines)

# Format one machine's latest in-memory reading for the dashboard.
def _format_latest_reading(machine: MachineStatusResponse) -> tuple[str, str]:
    reading = machine.latest_reading
    if reading is None:
        return "-", "-"

    values = reading.general_readings.model_dump()
    values.update(reading.special_readings.model_dump())
    formatted_values = []
    for name, value in values.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = f"{value:.1f}"
        formatted_values.append(f"{name}={value}")
    summary = ", ".join(formatted_values)

    return _format_time(reading.recorded_at), summary

# --------- Views ---------
# Convert the latest machine and fault data into the dashboard view.
def build_dashboard_text(machines: list[MachineStatusResponse], faults: list[FaultEventResponse], backend_online: bool, last_refresh_at: datetime | None, status_message: str) -> str:
    registered_count = sum(machine.is_registered for machine in machines)
    online_count = sum(machine.is_registered and machine.is_online for machine in machines)
    backend_status = "ONLINE" if backend_online else "OFFLINE"
    refresh_time = _format_time(last_refresh_at)

    machine_rows = []
    for machine in machines:
        active_fault_count = sum(fault.machine_id == machine.machine_id for fault in faults)
        reading_time, reading_summary = _format_latest_reading(machine)
        machine_rows.append(
            (
                machine.machine_id,
                machine.machine_type.value,
                _yes_no(machine.is_registered),
                _yes_no(machine.is_online) if machine.is_registered else "-",
                machine.operation_state.value if machine.operation_state is not None else "-",
                machine.cycle_stage or "-",
                str(active_fault_count),
                reading_time,
                reading_summary,
            )
        )

    fault_rows = [
        (
            str(fault.fault_event_id),
            fault.machine_id,
            fault.error_code,
            fault.error_source.value,
            _yes_no(fault.is_acknowledged),
            _format_time(fault.raised_at),
        )
        for fault in faults
    ]

    machine_table = build_ascii_table(
        "MACHINES",
        ("Machine", "Type", "Reg", "Online", "State", "Stage", "Faults", "Reading time", "Latest readings"),
        machine_rows,
    )
    fault_table = build_ascii_table(
        "ACTIVE FAULTS",
        ("Fault ID", "Machine", "Code", "Source", "Ack", "Raised"),
        fault_rows,
    )
    summary = (
        f"FLUFF & FOLD OPERATOR CONSOLE\n"
        f"Backend: {backend_status} | Registered: {registered_count} | "
        f"Online: {online_count} | Active faults: {len(faults)} | "
        f"Last refresh: {refresh_time}"
    )
    return f"{summary}\n\n{machine_table}\n\n{fault_table}\n\n{status_message}"


# Convert fault history and immutable data events into one diagnostic view.
def build_diagnostics_text(faults: list[FaultEventResponse], resolved_faults: list[FaultEventResponse], data_events: list[DataEventResponse], backend_online: bool, last_refresh_at: datetime | None, status_message: str) -> str:
    backend_status = "ONLINE" if backend_online else "OFFLINE"
    refresh_time = _format_time(last_refresh_at)

    active_fault_rows = []
    for fault in faults:
        kind, severity = _diagnostic_metadata(fault.error_code)
        active_fault_rows.append(
            (
                str(fault.fault_event_id),
                fault.machine_id,
                fault.error_code,
                kind,
                severity,
                _yes_no(fault.is_acknowledged),
                _format_time(fault.raised_at),
                fault.error_message or "-",
            )
        )

    resolved_fault_rows = []
    for fault in resolved_faults:
        kind, severity = _diagnostic_metadata(fault.error_code)
        resolved_fault_rows.append(
            (
                str(fault.fault_event_id),
                fault.machine_id,
                fault.error_code,
                kind,
                severity,
                _format_time(fault.resolved_at),
                fault.resolution_message or fault.error_message or "-",
            )
        )

    data_event_rows = []
    for event in data_events:
        kind, severity = _diagnostic_metadata(event.event_code)
        data_event_rows.append(
            (
                str(event.data_event_id),
                event.machine_id,
                event.event_code,
                kind,
                severity,
                _format_time(event.recorded_at),
                event.event_message,
                json.dumps(event.event_details, ensure_ascii=False, sort_keys=True),
            )
        )

    active_fault_table = build_ascii_table(
        "ACTIVE DIAGNOSTICS",
        ("Fault ID", "Machine", "Code", "Kind", "Severity", "Ack", "Raised", "Message"),
        active_fault_rows,
    )
    resolved_fault_table = build_ascii_table(
        "RESOLVED DIAGNOSTICS",
        ("Fault ID", "Machine", "Code", "Kind", "Severity", "Resolved", "Message"),
        resolved_fault_rows,
    )
    data_event_table = build_ascii_table(
        "DATA EVENTS",
        ("Event", "Machine", "Code", "Kind", "Severity", "Recorded", "Message", "Details"),
        data_event_rows,
    )
    summary = (
        f"FLUFF & FOLD DIAGNOSTICS\n"
        f"Backend: {backend_status} | Active: {len(faults)} | "
        f"Resolved: {len(resolved_faults)} | Data events: {len(data_events)} | "
        f"Last refresh: {refresh_time}"
    )
    return f"{summary}\n\n{active_fault_table}\n\n{resolved_fault_table}\n\n{data_event_table}\n\n{status_message}"


# Convert one fault context response into a readable pre-fault history view.
def build_fault_context_text(fault_context: FaultContextResponse | None, context_fault_id: int | None, status_message: str) -> str:
    if fault_context is None:
        return f"FAULT CONTEXT\n\nLoading fault {context_fault_id}...\n\n{status_message}"

    fault = fault_context.fault
    kind, severity = _diagnostic_metadata(fault.error_code)
    fault_summary = (
        f"FAULT CONTEXT {fault.fault_event_id}\n"
        f"Machine: {fault.machine_id} | Code: {fault.error_code} | Kind: {kind} | Severity: {severity}\n"
        f"Source: {fault.error_source.value} | Acknowledged: {_yes_no(fault.is_acknowledged)} | "
        f"Raised: {_format_time(fault.raised_at)} | Resolved: {_format_time(fault.resolved_at)}\n"
        f"Message: {fault.error_message or '-'}\n"
        f"Resolution: {fault.resolution_message or '-'}\n"
        f"History window: {_format_time(fault_context.window_start)} to {_format_time(fault_context.window_end)}"
    )

    reading_rows = []
    for reading in fault_context.sensor_readings:
        reading_rows.append(
            (
                _format_time(reading.recorded_at),
                reading.operation_state.value if reading.operation_state is not None else "-",
                reading.cycle_stage or "-",
                _format_sensor_readings(reading.general_readings),
                _format_sensor_readings(reading.special_readings),
            )
        )

    state_event_rows = []
    for state_event in fault_context.state_events:
        state_event_rows.append(
            (
                _format_time(state_event.recorded_at),
                state_event.event_source.value,
                state_event.previous_operation_state.value,
                state_event.new_operation_state.value,
                state_event.previous_cycle_stage or "-",
                state_event.new_cycle_stage or "-",
                state_event.reason or "-",
            )
        )

    data_event_rows = []
    for data_event in fault_context.data_events:
        data_event_rows.append(
            (
                str(data_event.data_event_id),
                data_event.event_code,
                _format_time(data_event.recorded_at),
                data_event.event_message,
                json.dumps(data_event.event_details, ensure_ascii=False, sort_keys=True),
            )
        )

    reading_table = build_ascii_table(
        "SENSOR HISTORY",
        ("Recorded", "State", "Stage", "General", "Special"),
        reading_rows,
    )
    state_event_table = build_ascii_table(
        "STATE HISTORY",
        ("Recorded", "Source", "Previous state", "New state", "Previous stage", "New stage", "Reason"),
        state_event_rows,
    )
    data_event_table = build_ascii_table(
        "DATA EVENTS",
        ("Event", "Code", "Recorded", "Message", "Details"),
        data_event_rows,
    )
    return f"{fault_summary}\n\n{reading_table}\n\n{state_event_table}\n\n{data_event_table}\n\n{status_message}"
