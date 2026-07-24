# Verify the minimal machine and report API routing chain.

import asyncio

from httpx import ASGITransport, AsyncClient

from app.api.routes import faults as fault_routes
from app.api.routes import register as register_routes
from app.api.routes import reports as report_routes
from app.main import app
from laundry_contracts.contracts import ReportProcessingResult


class StubMachineService:
    def __init__(self) -> None:
        self.registration_result = True
        self.deregistration_result = True
        self.report_result = ReportProcessingResult.ACCEPTED
        self.acknowledgement_result = True

    def machine_register(self, machine_id: str, machine_type: object) -> bool:
        return self.registration_result

    def machine_deregister(self, machine_id: str) -> bool:
        return self.deregistration_result

    def handle_periodic_report(self, report: object) -> ReportProcessingResult:
        return self.report_result

    def handle_change_of_state_report(self, report: object) -> ReportProcessingResult:
        return self.report_result

    def handle_error_report(self, report: object) -> ReportProcessingResult:
        return self.report_result

    def handle_error_resolution_report(self, report: object) -> ReportProcessingResult:
        return self.report_result

    def acknowledge_error(self, machine_id: str, error_id: str) -> bool:
        return self.acknowledgement_result


async def post_json(path: str, payload: dict[str, object]):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.post(path, json=payload)


def test_business_routes_are_exposed() -> None:
    assert set(app.openapi()["paths"]) == {
        "/api/v1/health",
        "/api/v1/machines/register",
        "/api/v1/machines/deregister",
        "/api/v1/reports/periodic",
        "/api/v1/reports/change-of-state",
        "/api/v1/reports/error",
        "/api/v1/reports/error-resolution",
        "/api/v1/machines",
        "/api/v1/machines/{machine_id}",
        "/api/v1/machines/{machine_id}/readings",
        "/api/v1/data-events",
        "/api/v1/faults",
        "/api/v1/faults/{fault_event_id}/context",
        "/api/v1/machines/{machine_id}/faults",
        "/api/v1/machines/{machine_id}/faults/{error_id}/acknowledge",
        "/api/v1/machines/{machine_id}/faults/{error_id}/resolve",
    }


def test_registration_returns_created_response(monkeypatch) -> None:
    service = StubMachineService()
    monkeypatch.setattr(register_routes, "machine_service", service)

    response = asyncio.run(
        post_json(
            "/api/v1/machines/register",
            {
                "machine_id": "washer-01",
                "machine_type": "washer",
                "registered_at": "2026-07-21T12:00:00Z",
            },
        )
    )

    assert response.status_code == 201
    assert response.json()["machine_id"] == "washer-01"
    assert response.json()["machine_type"] == "washer"


def test_registration_conflict_returns_409(monkeypatch) -> None:
    service = StubMachineService()
    service.registration_result = False
    monkeypatch.setattr(register_routes, "machine_service", service)

    response = asyncio.run(
        post_json(
            "/api/v1/machines/register",
            {
                "machine_id": "washer-01",
                "machine_type": "washer",
                "registered_at": "2026-07-21T12:00:00Z",
            },
        )
    )

    assert response.status_code == 409


def test_periodic_report_returns_accepted_response(monkeypatch) -> None:
    service = StubMachineService()
    monkeypatch.setattr(report_routes, "machine_service", service)
    payload = {
        "machine_id": "washer-01",
        "machine_type": "washer",
        "report_id": "report-01",
        "recorded_at": "2026-07-21T12:00:00Z",
        "operation_state": "running",
        "cycle_stage": "washing",
        "general_sensor_readings": {
            "vibration": 1.2,
            "door_locked": True,
        },
        "special_sensor_readings": {
            "water_level": 50.0,
            "water_temperature": 40.0,
        },
    }

    response = asyncio.run(
        post_json("/api/v1/reports/periodic", payload)
    )

    assert response.status_code == 200
    assert response.json()["report_id"] == "report-01"
    assert response.json()["is_duplicate"] is False

    service.report_result = ReportProcessingResult.DUPLICATE
    duplicate_response = asyncio.run(post_json("/api/v1/reports/periodic", payload))

    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["is_duplicate"] is True


def test_fault_acknowledgement_returns_acknowledged_response(monkeypatch) -> None:
    service = StubMachineService()
    monkeypatch.setattr(fault_routes, "machine_service", service)

    response = asyncio.run(
        post_json(
            "/api/v1/machines/washer-01/faults/door-error-01/acknowledge",
            {},
        )
    )

    assert response.status_code == 200
    assert response.json() == {
        "machine_id": "washer-01",
        "error_id": "door-error-01",
        "is_acknowledged": True,
    }


def test_fault_acknowledgement_returns_not_found(monkeypatch) -> None:
    service = StubMachineService()
    service.acknowledgement_result = False
    monkeypatch.setattr(fault_routes, "machine_service", service)

    response = asyncio.run(
        post_json(
            "/api/v1/machines/washer-01/faults/missing-error/acknowledge",
            {},
        )
    )

    assert response.status_code == 404


def test_error_resolution_report_returns_accepted_response(monkeypatch) -> None:
    service = StubMachineService()
    monkeypatch.setattr(report_routes, "machine_service", service)

    response = asyncio.run(
        post_json(
            "/api/v1/reports/error-resolution",
            {
                "machine_id": "washer-01",
                "machine_type": "washer",
                "report_id": "resolution-01",
                "recorded_at": "2026-07-22T12:01:00Z",
                "error_id": "door-error-01",
                "resolution_message": "Door lock recovered",
                "operation_state": "idle",
                "cycle_stage": None,
                "general_sensor_readings": {
                    "vibration": 0.1,
                    "door_locked": False,
                },
                "special_sensor_readings": {
                    "water_level": 0.0,
                    "water_temperature": 20.0,
                },
            },
        )
    )

    assert response.status_code == 200
    assert response.json()["report_id"] == "resolution-01"
