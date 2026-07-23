# Verify operator-facing machine, reading, and fault query endpoints.
# 验证面向操作员的机器、读数和故障查询接口。

import asyncio

from httpx import ASGITransport, AsyncClient

from app.api.routes import data_events as data_event_routes
from app.api.routes import faults as fault_routes
from app.api.routes import machines as machine_routes
from app.api.routes import readings as reading_routes
from app.main import app


class StubManagementService:
    def __init__(self) -> None:
        self.machine_result = {
            "machine_id": "washer-01",
            "machine_type": "washer",
            "is_registered": True,
            "is_online": True,
            "operation_state": "running",
            "cycle_stage": "washing",
            "registered_at": "2026-07-22T12:00:00Z",
            "last_online": "2026-07-22T12:01:00Z",
            "recorded_at": "2026-07-22T12:01:00Z",
        }
        self.reading_result = {
            "reading_id": 1,
            "machine_id": "washer-01",
            "report_id": "periodic-01",
            "recorded_at": "2026-07-22T12:01:00Z",
            "received_at": "2026-07-22T12:01:01Z",
            "operation_state": "running",
            "cycle_stage": "washing",
            "general_readings": {"vibration": 0.1, "door_locked": True},
            "special_readings": {"water_level": 50.0, "water_temperature": 40.0},
        }
        self.fault_result = {
            "fault_event_id": 1,
            "machine_id": "washer-01",
            "report_id": "error-report-01",
            "error_id": "door-error-01",
            "error_code": "door_fault",
            "error_message": "Door did not lock",
            "error_source": "device",
            "is_acknowledged": True,
            "raised_at": "2026-07-22T12:01:00Z",
            "resolved_at": None,
            "resolution_message": None,
        }
        self.data_event_result = {
            "data_event_id": 1,
            "machine_id": "washer-01",
            "report_id": "periodic-02",
            "event_code": "D9001",
            "event_message": "Periodic report state differs from the stored state",
            "event_details": {
                "stored_operation_state": "idle",
                "reported_operation_state": "running",
            },
            "recorded_at": "2026-07-22T12:01:00Z",
            "received_at": "2026-07-22T12:01:01Z",
        }
        self.fault_context_result = {
            "fault": self.fault_result,
            "window_start": "2026-07-22T11:56:00Z",
            "window_end": "2026-07-22T12:01:00Z",
            "sensor_readings": [self.reading_result],
            "state_events": [
                {
                    "state_event_id": 1,
                    "machine_id": "washer-01",
                    "report_id": "state-01",
                    "event_source": "change_of_state_report",
                    "recorded_at": "2026-07-22T12:00:30Z",
                    "received_at": "2026-07-22T12:00:31Z",
                    "previous_operation_state": "idle",
                    "new_operation_state": "running",
                    "previous_cycle_stage": None,
                    "new_cycle_stage": "filling",
                    "reason": "Automatic cycle started",
                }
            ],
            "data_events": [self.data_event_result],
        }
        self.return_missing = False
        self.resolution_result = True
        self.last_fault_query = None
        self.last_fault_context_query = None
        self.last_data_event_query = None

    def list_machines(self):
        return [self.machine_result]

    def get_machine(self, machine_id: str):
        return None if self.return_missing else self.machine_result

    def list_sensor_readings(self, machine_id, start_time, end_time, operation_state, limit):
        return None if self.return_missing else [self.reading_result]

    def list_faults(self, machine_id, active, acknowledged, limit):
        self.last_fault_query = (machine_id, active, acknowledged, limit)
        if self.return_missing and machine_id is not None:
            return None
        return [self.fault_result]

    def list_data_events(self, machine_id, event_code, limit):
        self.last_data_event_query = (machine_id, event_code, limit)
        if self.return_missing and machine_id is not None:
            return None
        return [self.data_event_result]

    def get_fault_context(self, fault_event_id, minutes):
        self.last_fault_context_query = (fault_event_id, minutes)
        if self.return_missing or fault_event_id == 999:
            return None
        return self.fault_context_result

    def resolve_error(self, machine_id: str, error_id: str, resolution_message: str | None) -> bool:
        return self.resolution_result


async def get(path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


async def post(path: str, payload: dict[str, object]):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(path, json=payload)


def test_operator_query_and_resolution_routes(monkeypatch) -> None:
    service = StubManagementService()
    monkeypatch.setattr(machine_routes, "machine_service", service)
    monkeypatch.setattr(reading_routes, "machine_service", service)
    monkeypatch.setattr(fault_routes, "machine_service", service)
    monkeypatch.setattr(data_event_routes, "machine_service", service)

    machines_response = asyncio.run(get("/api/v1/machines"))
    machine_response = asyncio.run(get("/api/v1/machines/washer-01"))
    readings_response = asyncio.run(get("/api/v1/machines/washer-01/readings?operation_state=running&limit=10"))
    faults_response = asyncio.run(get("/api/v1/faults?active=true&acknowledged=true&limit=10"))
    machine_faults_response = asyncio.run(get("/api/v1/machines/washer-01/faults"))
    fault_context_response = asyncio.run(get("/api/v1/faults/1/context?minutes=5"))
    data_events_response = asyncio.run(get("/api/v1/data-events?machine_id=washer-01&event_code=D9001&limit=10"))
    resolution_response = asyncio.run(post("/api/v1/machines/washer-01/faults/door-error-01/resolve", {"resolution_message": "Door repaired"}))

    assert machines_response.status_code == 200
    assert machine_response.status_code == 200
    assert readings_response.status_code == 200
    assert faults_response.status_code == 200
    assert machine_faults_response.status_code == 200
    assert fault_context_response.status_code == 200
    assert data_events_response.status_code == 200
    assert resolution_response.status_code == 200
    assert service.last_fault_query == ("washer-01", None, None, 100)
    assert service.last_fault_context_query == (1, 5)
    assert service.last_data_event_query == ("washer-01", "D9001", 10)
    assert fault_context_response.json()["fault"]["fault_event_id"] == 1
    assert fault_context_response.json()["state_events"][0]["report_id"] == "state-01"
    assert data_events_response.json()[0]["event_code"] == "D9001"
    assert resolution_response.json()["is_resolved"] is True


def test_operator_machine_routes_return_not_found(monkeypatch) -> None:
    service = StubManagementService()
    service.return_missing = True
    service.resolution_result = False
    monkeypatch.setattr(machine_routes, "machine_service", service)
    monkeypatch.setattr(reading_routes, "machine_service", service)
    monkeypatch.setattr(fault_routes, "machine_service", service)
    monkeypatch.setattr(data_event_routes, "machine_service", service)

    assert asyncio.run(get("/api/v1/machines/missing-machine")).status_code == 404
    assert asyncio.run(get("/api/v1/machines/missing-machine/readings")).status_code == 404
    assert asyncio.run(get("/api/v1/machines/missing-machine/faults")).status_code == 404
    assert asyncio.run(get("/api/v1/faults/999/context")).status_code == 404
    assert asyncio.run(get("/api/v1/faults/1/context?minutes=0")).status_code == 422
    assert asyncio.run(get("/api/v1/faults/1/context?minutes=61")).status_code == 422
    assert asyncio.run(get("/api/v1/data-events?machine_id=missing-machine")).status_code == 404
    assert asyncio.run(get("/api/v1/data-events?event_code=F3102")).status_code == 422
    assert asyncio.run(post("/api/v1/machines/missing-machine/faults/missing-error/resolve", {})).status_code == 404
