# Verify operator-facing machine, reading, and fault query endpoints.
# 验证面向操作员的机器、读数和故障查询接口。

import asyncio

from httpx import ASGITransport, AsyncClient

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
        self.return_missing = False
        self.resolution_result = True
        self.last_fault_query = None

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

    machines_response = asyncio.run(get("/api/v1/machines"))
    machine_response = asyncio.run(get("/api/v1/machines/washer-01"))
    readings_response = asyncio.run(get("/api/v1/machines/washer-01/readings?operation_state=running&limit=10"))
    faults_response = asyncio.run(get("/api/v1/faults?active=true&acknowledged=true&limit=10"))
    machine_faults_response = asyncio.run(get("/api/v1/machines/washer-01/faults"))
    resolution_response = asyncio.run(post("/api/v1/machines/washer-01/faults/door-error-01/resolve", {"resolution_message": "Door repaired"}))

    assert machines_response.status_code == 200
    assert machine_response.status_code == 200
    assert readings_response.status_code == 200
    assert faults_response.status_code == 200
    assert machine_faults_response.status_code == 200
    assert resolution_response.status_code == 200
    assert service.last_fault_query == ("washer-01", None, None, 100)
    assert resolution_response.json()["is_resolved"] is True


def test_operator_machine_routes_return_not_found(monkeypatch) -> None:
    service = StubManagementService()
    service.return_missing = True
    service.resolution_result = False
    monkeypatch.setattr(machine_routes, "machine_service", service)
    monkeypatch.setattr(reading_routes, "machine_service", service)
    monkeypatch.setattr(fault_routes, "machine_service", service)

    assert asyncio.run(get("/api/v1/machines/missing-machine")).status_code == 404
    assert asyncio.run(get("/api/v1/machines/missing-machine/readings")).status_code == 404
    assert asyncio.run(get("/api/v1/machines/missing-machine/faults")).status_code == 404
    assert asyncio.run(post("/api/v1/machines/missing-machine/faults/missing-error/resolve", {})).status_code == 404
