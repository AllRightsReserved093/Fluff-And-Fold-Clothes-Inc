# Verify simulator workflows and fault reporting without a live backend.

import json
from queue import Queue
from threading import Event

import httpx

from laundry_contracts.contracts import DryerCyclePhase, OperationState, WasherCyclePhase
from laundry_contracts.fault_codes import DiagnosticCode
from simulator.dryer import Dryer
from simulator.faults import apply_blocked_vent
from simulator.main import Command, create_machines, handle_command, parse_console_command, run_simulation
from simulator.machine import REPORT_INTERVAL_SECONDS
from simulator.washer import Washer


def create_recording_client() -> tuple[httpx.Client, list[tuple[str, dict[str, object]]]]:
    requests: list[tuple[str, dict[str, object]]] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        requests.append((request.url.path, payload))
        status_code = 201 if request.url.path.endswith("/machines/register") else 200
        return httpx.Response(status_code, request=request)

    return httpx.Client(transport=httpx.MockTransport(handle_request)), requests


def test_simulator_creates_requested_machine_inventory() -> None:
    client, _ = create_recording_client()
    machines = create_machines(client)

    assert len(machines) == 36
    assert "washer-01" in machines
    assert "washer-20" in machines
    assert "dryer-01" in machines
    assert "dryer-16" in machines
    client.close()


def test_simulator_uses_custom_api_base_url() -> None:
    client, _ = create_recording_client()
    machines = create_machines(client, "http://test/custom-api")

    assert all(machine.api_base_url == "http://test/custom-api" for machine in machines.values())
    client.close()


def test_washer_advances_workflow_and_reports_every_fifteen_seconds() -> None:
    client, requests = create_recording_client()
    washer = Washer("washer-01", client, "http://test/api/v1")

    assert washer.register()
    washer.tick(10.0)
    assert washer.operation_state is OperationState.RUNNING
    assert washer.cycle_stage is WasherCyclePhase.FILLING

    washer.tick(20.0)
    assert washer.cycle_stage is WasherCyclePhase.WASHING
    assert REPORT_INTERVAL_SECONDS == 15.0
    assert washer.send_periodic_report()
    assert washer.deregister()

    request_paths = [path for path, _ in requests]
    assert request_paths.count("/api/v1/reports/change-of-state") == 2
    assert request_paths.count("/api/v1/reports/periodic") == 1
    assert request_paths[-1] == "/api/v1/machines/deregister"

    state_payloads = [payload for path, payload in requests if path == "/api/v1/reports/change-of-state"]
    assert state_payloads[0]["previous_operation_state"] == "idle"
    assert state_payloads[0]["new_operation_state"] == "running"
    assert state_payloads[1]["previous_cycle_stage"] == "filling"
    assert state_payloads[1]["new_cycle_stage"] == "washing"
    client.close()


def test_unbalanced_load_waits_for_spinning_and_freezes_until_repair() -> None:
    client, requests = create_recording_client()
    washer = Washer("washer-01", client, "http://test/api/v1")

    assert washer.register()
    assert not washer.inject_fault("blocked-vent")
    assert not washer.inject_fault("unbalanced-load")

    washer.tick(10.0)
    assert washer.cycle_stage is WasherCyclePhase.FILLING
    assert washer.inject_fault("unbalanced-load")

    washer.tick(20.0)
    assert washer.cycle_stage is WasherCyclePhase.WASHING
    washer.tick(45.0)
    assert washer.cycle_stage is WasherCyclePhase.DRAINING
    washer.tick(20.0)
    assert washer.cycle_stage is WasherCyclePhase.SPINNING

    washer.tick(7.0)
    assert washer.cycle_stage is WasherCyclePhase.SPINNING
    assert washer.phase_elapsed_seconds == 0.0
    assert washer.vibration == 11.0
    assert washer.send_periodic_report()

    assert washer.repair()
    washer.tick(4.0)
    assert washer.active_fault is None
    assert washer.cycle_stage is WasherCyclePhase.SPINNING
    assert washer.phase_elapsed_seconds == 0.0
    assert washer.vibration == 4.0

    periodic_payloads = [payload for path, payload in requests if path == "/api/v1/reports/periodic"]
    assert periodic_payloads[-2]["general_sensor_readings"]["vibration"] == 11.0
    assert periodic_payloads[-1]["general_sensor_readings"]["vibration"] == 4.0

    washer.tick(30.0)
    assert washer.operation_state is OperationState.COMPLETE
    client.close()


def test_offline_and_online_commands_toggle_machine_communication() -> None:
    client, _ = create_recording_client()
    washer = Washer("washer-01", client, "http://test/api/v1")
    machines = {washer.machine_id: washer}

    offline_command, selected_machine_id = parse_console_command("offline", washer.machine_id, set(machines))
    assert offline_command == ("offline", washer.machine_id, None)
    assert selected_machine_id == washer.machine_id
    assert handle_command(offline_command, machines)
    assert not washer.is_communication_enabled
    assert "signals=off" in washer.status_line()

    online_command, selected_machine_id = parse_console_command("online", washer.machine_id, set(machines))
    assert online_command == ("online", washer.machine_id, None)
    assert selected_machine_id == washer.machine_id
    assert handle_command(online_command, machines)
    assert washer.is_communication_enabled
    assert "signals=on" in washer.status_line()
    client.close()


def test_blocked_vent_progresses_to_device_shutdown_and_repair() -> None:
    client, requests = create_recording_client()
    dryer = Dryer("dryer-01", client, "http://test/api/v1")

    assert dryer.register()
    dryer.tick(10.0)
    assert dryer.cycle_stage is DryerCyclePhase.HEATING
    assert dryer.inject_fault("blocked-vent")

    dryer.tick(85.0)
    assert dryer.operation_state is OperationState.FAULTED
    assert dryer.active_fault is not None

    error_payload = next(payload for path, payload in requests if path == "/api/v1/reports/error")
    assert error_payload["error_code"] == DiagnosticCode.DRYER_OVERTEMPERATURE_TRIP.value
    assert error_payload["change_of_state"] is True
    assert error_payload["change_of_state_report"]["new_operation_state"] == "faulted"

    assert dryer.repair()
    dryer.tick(20.0)
    assert dryer.operation_state is OperationState.IDLE
    assert dryer.active_fault is None

    request_paths = [path for path, _ in requests]
    assert "/api/v1/reports/error-resolution" in request_paths
    assert request_paths[-1] == "/api/v1/reports/change-of-state"

    resolution_payload = next(payload for path, payload in requests if path == "/api/v1/reports/error-resolution")
    assert resolution_payload["special_sensor_readings"]["air_temperature"] == 70.0
    assert resolution_payload["special_sensor_readings"]["air_flow_speed"] == 2.0
    client.close()


def test_blocked_vent_function_changes_only_fault_sensor_values() -> None:
    temperature, airflow, should_trip = apply_blocked_vent(60.0, 2.5, 15.0)

    assert temperature == 75.0
    assert airflow == 1.75
    assert not should_trip


def test_simulation_quit_deregisters_every_registered_machine() -> None:
    client, requests = create_recording_client()
    machines = create_machines(client)
    command_queue: Queue[Command] = Queue()
    stopped_event = Event()
    command_queue.put(("quit", None, None))

    run_simulation(command_queue, stopped_event, machines)

    request_paths = [path for path, _ in requests]
    registered_count = request_paths.count("/api/v1/machines/register")
    deregistered_count = request_paths.count("/api/v1/machines/deregister")
    assert registered_count > 0
    assert deregistered_count == registered_count
    assert stopped_event.is_set()
    client.close()
