# Verify the operator console API boundary without starting a network server.

import asyncio
import json

import httpx
import pytest

from laundry_contracts.fault_codes import DiagnosticCode
from operator_console.api_client import OperatorApiClient, OperatorApiError


MACHINE_RESPONSE = {
    "machine_id": "washer-01",
    "machine_type": "washer",
    "is_registered": True,
    "is_online": True,
    "operation_state": "running",
    "cycle_stage": "washing",
    "registered_at": "2026-07-23T12:00:00Z",
    "last_online": "2026-07-23T12:01:00Z",
    "recorded_at": "2026-07-23T12:01:00Z",
    "latest_reading": {
        "recorded_at": "2026-07-23T12:01:00Z",
        "general_readings": {"vibration": 1.0, "door_locked": True},
        "special_readings": {"water_level": 50.0, "water_temperature": 40.0},
    },
}

READING_RESPONSE = {
    "reading_id": 1,
    "machine_id": "washer-01",
    "report_id": "periodic-01",
    "recorded_at": "2026-07-23T12:01:00Z",
    "received_at": "2026-07-23T12:01:01Z",
    "operation_state": "running",
    "cycle_stage": "washing",
    "general_readings": {"vibration": 1.0, "door_locked": True},
    "special_readings": {"water_level": 50.0, "water_temperature": 40.0},
}

FAULT_RESPONSE = {
    "fault_event_id": 1,
    "machine_id": "washer-01",
    "report_id": "error-report-01",
    "error_id": "door-error-01",
    "error_code": DiagnosticCode.DOOR_INTERLOCK_LOST.value,
    "error_message": "Door did not lock",
    "error_source": "device",
    "is_acknowledged": False,
    "raised_at": "2026-07-23T12:01:00Z",
    "resolved_at": None,
    "resolution_message": None,
}

DATA_EVENT_RESPONSE = {
    "data_event_id": 1,
    "machine_id": "washer-01",
    "report_id": "periodic-02",
    "event_code": "D9001",
    "event_message": "Periodic report state differs from the stored state",
    "event_details": {
        "stored_operation_state": "idle",
        "reported_operation_state": "running",
    },
    "recorded_at": "2026-07-23T12:01:00Z",
    "received_at": "2026-07-23T12:01:01Z",
}

FAULT_CONTEXT_RESPONSE = {
    "fault": FAULT_RESPONSE,
    "window_start": "2026-07-23T11:56:00Z",
    "window_end": "2026-07-23T12:01:00Z",
    "sensor_readings": [READING_RESPONSE],
    "state_events": [
        {
            "state_event_id": 1,
            "machine_id": "washer-01",
            "report_id": "state-01",
            "event_source": "change_of_state_report",
            "recorded_at": "2026-07-23T12:00:30Z",
            "received_at": "2026-07-23T12:00:31Z",
            "previous_operation_state": "idle",
            "new_operation_state": "running",
            "previous_cycle_stage": None,
            "new_cycle_stage": "filling",
            "reason": "Automatic cycle started",
        }
    ],
    "data_events": [DATA_EVENT_RESPONSE],
}


def test_operator_api_client_parses_query_responses() -> None:
    requested_urls: list[str] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/api/v1/machines":
            return httpx.Response(200, json=[MACHINE_RESPONSE])
        if request.url.path == "/api/v1/faults":
            return httpx.Response(200, json=[FAULT_RESPONSE])
        if request.url.path == "/api/v1/faults/1/context":
            return httpx.Response(200, json=FAULT_CONTEXT_RESPONSE)
        if request.url.path == "/api/v1/data-events":
            return httpx.Response(200, json=[DATA_EVENT_RESPONSE])
        return httpx.Response(404, json={"detail": "Not found"})

    async def run_scenario() -> None:
        client = OperatorApiClient(transport=httpx.MockTransport(handle_request))
        try:
            machines = await client.list_machines()
            faults = await client.list_faults(active=True)
            data_events = await client.list_data_events()
            fault_context = await client.get_fault_context(1)
        finally:
            await client.close()

        assert machines[0].latest_reading is not None
        assert machines[0].latest_reading.special_readings.water_temperature == 40.0
        assert faults[0].error_id == "door-error-01"
        assert data_events[0].event_code == "D9001"
        assert fault_context.fault.fault_event_id == 1
        assert fault_context.sensor_readings[0].reading_id == 1

    asyncio.run(run_scenario())

    assert any("faults?limit=100&active=true" in url for url in requested_urls)
    assert any("data-events?limit=100" in url for url in requested_urls)
    assert any("faults/1/context?minutes=5" in url for url in requested_urls)


def test_operator_api_client_sends_fault_actions_and_reports_http_errors() -> None:
    resolution_body: dict[str, object] = {}

    def handle_request(request: httpx.Request) -> httpx.Response:
        nonlocal resolution_body
        if request.url.path.endswith("/acknowledge"):
            return httpx.Response(
                200,
                json={"machine_id": "washer-01", "error_id": "door-error-01", "is_acknowledged": True},
            )
        if request.url.path.endswith("/resolve"):
            resolution_body = json.loads(request.content)
            return httpx.Response(
                200,
                json={"machine_id": "washer-01", "error_id": "door-error-01", "is_resolved": True},
            )
        return httpx.Response(404, json={"detail": "Machine not found"})

    async def run_scenario() -> None:
        client = OperatorApiClient(transport=httpx.MockTransport(handle_request))
        try:
            await client.acknowledge_fault("washer-01", "door-error-01")
            await client.resolve_fault("washer-01", "door-error-01", "Door repaired")
            with pytest.raises(OperatorApiError, match="HTTP 404"):
                await client.get_fault_context(999)
        finally:
            await client.close()

    asyncio.run(run_scenario())
    assert resolution_body == {"resolution_message": "Door repaired"}


def test_operator_api_client_rejects_invalid_data_event_response() -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"data_event_id": 1}])

    async def run_scenario() -> None:
        client = OperatorApiClient(transport=httpx.MockTransport(handle_request))
        try:
            with pytest.raises(OperatorApiError, match="invalid data event data"):
                await client.list_data_events()
        finally:
            await client.close()

    asyncio.run(run_scenario())
