# Verify the terminal dashboard renders backend data and refreshes automatically.
# 验证终端仪表板能够显示后端数据并自动刷新。

import asyncio

import httpx
from textual.widgets import Input

from operator_console.api_client import OperatorApiClient
from operator_console.main import OperatorConsoleApp
from operator_console.views import build_dashboard_text, build_diagnostics_text, build_fault_context_text


def test_operator_console_renders_and_refreshes_dashboard() -> None:
    machine_request_count = 0
    data_event_request_count = 0
    machine_fault_request_count = 0
    fault_context_request_count = 0
    acknowledged_fault = False
    resolved_fault = False

    def handle_request(request: httpx.Request) -> httpx.Response:
        nonlocal machine_request_count, data_event_request_count, machine_fault_request_count, fault_context_request_count, acknowledged_fault, resolved_fault
        if request.url.path == "/api/v1/machines":
            machine_request_count += 1
            return httpx.Response(
                200,
                json=[
                    {
                        "machine_id": "dryer-01",
                        "machine_type": "dryer",
                        "is_registered": True,
                        "is_online": True,
                        "operation_state": "running",
                        "cycle_stage": "drying",
                        "registered_at": "2026-07-23T12:00:00Z",
                        "last_online": "2026-07-23T12:01:00Z",
                        "recorded_at": "2026-07-23T12:01:00Z",
                        "latest_reading": {
                            "recorded_at": "2026-07-23T12:01:00Z",
                            "general_readings": {"vibration": 0.8, "door_locked": True},
                            "special_readings": {"air_temperature": 65.0, "air_flow_speed": 2.1, "moisture": 30.0},
                        },
                    }
                ],
            )
        if request.url.path == "/api/v1/faults/1/context":
            fault_context_request_count += 1
            return httpx.Response(
                200,
                json={
                    "fault": {
                        "fault_event_id": 1,
                        "machine_id": "dryer-01",
                        "report_id": "error-report-01",
                        "error_id": "blocked-vent-01",
                        "error_code": "W3201",
                        "error_message": "Air flow is too low",
                        "error_source": "analytics",
                        "is_acknowledged": False,
                        "raised_at": "2026-07-23T12:01:00Z",
                        "resolved_at": None,
                        "resolution_message": None,
                    },
                    "window_start": "2026-07-23T11:56:00Z",
                    "window_end": "2026-07-23T12:01:00Z",
                    "sensor_readings": [
                        {
                            "reading_id": 1,
                            "machine_id": "dryer-01",
                            "report_id": "periodic-01",
                            "recorded_at": "2026-07-23T12:00:45Z",
                            "received_at": "2026-07-23T12:00:46Z",
                            "operation_state": "running",
                            "cycle_stage": "drying",
                            "general_readings": {"vibration": 1.0, "door_locked": True},
                            "special_readings": {"air_temperature": 91.0, "air_flow_speed": 0.4, "moisture": 25.0},
                        }
                    ],
                    "state_events": [
                        {
                            "state_event_id": 1,
                            "machine_id": "dryer-01",
                            "report_id": "state-01",
                            "event_source": "change_of_state_report",
                            "recorded_at": "2026-07-23T12:00:30Z",
                            "received_at": "2026-07-23T12:00:31Z",
                            "previous_operation_state": "idle",
                            "new_operation_state": "running",
                            "previous_cycle_stage": None,
                            "new_cycle_stage": "heating",
                            "reason": "Automatic cycle started",
                        }
                    ],
                    "data_events": [
                        {
                            "data_event_id": 1,
                            "machine_id": "dryer-01",
                            "report_id": "periodic-02",
                            "event_code": "D9001",
                            "event_message": "Periodic report state differs from the stored state",
                            "event_details": {
                                "stored_operation_state": "idle",
                                "reported_operation_state": "running",
                            },
                            "recorded_at": "2026-07-23T12:00:50Z",
                            "received_at": "2026-07-23T12:00:51Z",
                        }
                    ],
                },
            )
        if request.url.path in {"/api/v1/faults", "/api/v1/machines/dryer-01/faults"}:
            if request.url.path == "/api/v1/machines/dryer-01/faults":
                machine_fault_request_count += 1
            if request.url.params.get("active") == "false":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "fault_event_id": 2,
                            "machine_id": "dryer-01",
                            "report_id": "legacy-report-01",
                            "error_id": "legacy-error-01",
                            "error_code": "legacy_fault",
                            "error_message": "Legacy diagnostic",
                            "error_source": "device",
                            "is_acknowledged": True,
                            "raised_at": "2026-07-23T11:00:00Z",
                            "resolved_at": "2026-07-23T11:05:00Z",
                            "resolution_message": "Legacy fault resolved",
                        }
                    ],
                )
            return httpx.Response(
                200,
                json=[
                    {
                        "fault_event_id": 1,
                        "machine_id": "dryer-01",
                        "report_id": "error-report-01",
                        "error_id": "blocked-vent-01",
                        "error_code": "W3201",
                        "error_message": "Air flow is too low",
                        "error_source": "analytics",
                        "is_acknowledged": False,
                        "raised_at": "2026-07-23T12:01:00Z",
                        "resolved_at": None,
                        "resolution_message": None,
                    }
                ],
            )
        if request.url.path == "/api/v1/data-events":
            data_event_request_count += 1
            return httpx.Response(
                200,
                json=[
                    {
                        "data_event_id": 1,
                        "machine_id": "dryer-01",
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
                ],
            )
        if request.url.path == "/api/v1/machines/dryer-01/faults/blocked-vent-01/acknowledge":
            acknowledged_fault = True
            return httpx.Response(
                200,
                json={"machine_id": "dryer-01", "error_id": "blocked-vent-01", "is_acknowledged": True},
            )
        if request.url.path == "/api/v1/machines/dryer-01/faults/blocked-vent-01/resolve":
            resolved_fault = True
            return httpx.Response(
                200,
                json={"machine_id": "dryer-01", "error_id": "blocked-vent-01", "is_resolved": True},
            )
        return httpx.Response(404, json={"detail": "Not found"})

    async def run_scenario() -> None:
        api_client = OperatorApiClient(transport=httpx.MockTransport(handle_request))
        app = OperatorConsoleApp(refresh_interval_seconds=0.05, api_client=api_client)

        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            dashboard_text = build_dashboard_text(app.machines, app.faults, app.backend_online, app.last_refresh_at, app.status_message)
            assert "MACHINES" in dashboard_text
            assert "ACTIVE FAULTS" in dashboard_text
            assert "dryer-01" in dashboard_text
            assert "| 1     | dryer-01" in dashboard_text
            assert "blocked-vent-01" not in dashboard_text
            assert "air=65.0C" in dashboard_text
            assert "flow=2.1m/s" in dashboard_text

            command_input = app.query_one("#command", Input)
            command_input.value = "diagnostics"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause(0.12)
            await app.workers.wait_for_complete()

            diagnostics_text = build_diagnostics_text(app.faults, app.resolved_faults, app.data_events, app.diagnostic_machine_id, app.backend_online, app.last_refresh_at, app.status_message)
            assert app.view_mode == "diagnostics"
            assert "ACTIVE DIAGNOSTICS" in diagnostics_text
            assert "RESOLVED DIAGNOSTICS" in diagnostics_text
            assert "DATA EVENTS" in diagnostics_text
            assert "W3201" in diagnostics_text
            assert "D9001" in diagnostics_text
            assert "legacy" in diagnostics_text

            command_input.value = "diagnostics machine dryer-01"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert app.diagnostic_machine_id == "dryer-01"

            command_input.value = "diagnostics fault 1"
            await pilot.press("enter")
            await app.workers.wait_for_complete()

            context_text = build_fault_context_text(app.fault_context, app.context_fault_id, app.status_message)
            assert app.view_mode == "fault_context"
            assert "FAULT CONTEXT 1" in context_text
            assert "W3201" in context_text
            assert "SENSOR HISTORY" in context_text
            assert "STATE HISTORY" in context_text
            assert "DATA EVENTS" in context_text

            command_input.value = "dashboard"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert app.view_mode == "dashboard"

            command_input.value = "ack 1"
            await pilot.press("enter")
            await app.workers.wait_for_complete()

            command_input.value = "resolve 1 Vent repaired"
            await pilot.press("enter")
            await app.workers.wait_for_complete()

            await pilot.pause(0.12)
            await app.workers.wait_for_complete()

    asyncio.run(run_scenario())
    assert machine_request_count >= 2
    assert data_event_request_count >= 2
    assert machine_fault_request_count >= 2
    assert fault_context_request_count >= 1
    assert acknowledged_fault
    assert resolved_fault
