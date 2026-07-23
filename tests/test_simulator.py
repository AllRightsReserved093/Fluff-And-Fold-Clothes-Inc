# Verify simulator workflows and fault reporting without a live backend.
# 在不连接真实后端的情况下验证模拟器流程与故障报告。

import json
from queue import Queue
from threading import Event

import httpx

from laundry_contracts.contracts import DryerCyclePhase, OperationState, WasherCyclePhase
from simulator.dryer import Dryer
from simulator.faults import apply_blocked_vent
from simulator.main import Command, create_machines, run_simulation
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


def test_washer_fault_commands_use_safe_placeholders() -> None:
    client, _ = create_recording_client()
    washer = Washer("washer-01", client, "http://test/api/v1")

    assert not washer.inject_fault("blocked-vent")
    assert not washer.repair()
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
    assert error_payload["error_code"] == "blocked_vent_overheat"
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
