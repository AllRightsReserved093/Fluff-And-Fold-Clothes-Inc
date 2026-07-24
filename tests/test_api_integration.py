# Verify a complete device fault lifecycle through the real API, service, and database layers.

import asyncio

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import faults as fault_routes
from app.api.routes import machines as machine_routes
from app.api.routes import readings as reading_routes
from app.api.routes import register as register_routes
from app.api.routes import reports as report_routes
from app.database.base import Base
from app.main import app
from app.services import machine_service as machine_service_module
from app.services.machine_service import MachineService
from laundry_contracts.contracts import (
    DeregistrationRequest,
    DryerChangeOfStateReport,
    DryerCyclePhase,
    DryerErrorReport,
    DryerErrorResolutionReport,
    DryerPeriodicReport,
    ErrorSource,
    MachineType,
    OperationState,
    RegistrationRequest,
)
from laundry_contracts.fault_codes import DiagnosticCode


def test_device_fault_lifecycle_through_api_and_database(monkeypatch: pytest.MonkeyPatch) -> None:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    test_session_factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(machine_service_module, "SessionFactory", test_session_factory)

    service = MachineService()
    for route_module in (register_routes, report_routes, machine_routes, reading_routes, fault_routes):
        monkeypatch.setattr(route_module, "machine_service", service)

    registration = RegistrationRequest(
        machine_id="dryer-integration",
        machine_type=MachineType.DRYER,
        registered_at="2026-07-24T12:00:00Z",
    )
    start_report = DryerChangeOfStateReport(
        machine_id="dryer-integration",
        machine_type=MachineType.DRYER,
        report_id="start-state-01",
        recorded_at="2026-07-24T12:00:05Z",
        previous_operation_state=OperationState.IDLE,
        new_operation_state=OperationState.RUNNING,
        previous_cycle_stage=None,
        new_cycle_stage=DryerCyclePhase.DRYING,
        reason="Integration test cycle started",
    )
    periodic_report = DryerPeriodicReport(
        machine_id="dryer-integration",
        machine_type=MachineType.DRYER,
        report_id="periodic-01",
        recorded_at="2026-07-24T12:00:15Z",
        operation_state=OperationState.RUNNING,
        cycle_stage=DryerCyclePhase.DRYING,
        general_sensor_readings={"vibration": 0.8, "door_locked": True},
        special_sensor_readings={"air_temperature": 60.0, "air_flow_speed": 2.5, "moisture": 35.0},
    )
    trip_state_report = DryerChangeOfStateReport(
        machine_id="dryer-integration",
        machine_type=MachineType.DRYER,
        report_id="trip-state-01",
        recorded_at="2026-07-24T12:00:30Z",
        previous_operation_state=OperationState.RUNNING,
        new_operation_state=OperationState.FAULTED,
        previous_cycle_stage=DryerCyclePhase.DRYING,
        new_cycle_stage=DryerCyclePhase.DRYING,
        reason="Overtemperature protection activated",
    )
    error_report = DryerErrorReport(
        machine_id="dryer-integration",
        machine_type=MachineType.DRYER,
        report_id="error-01",
        recorded_at="2026-07-24T12:00:30Z",
        error_id="overtemperature-01",
        error_code=DiagnosticCode.DRYER_OVERTEMPERATURE_TRIP.value,
        error_message="Dryer overtemperature trip",
        error_source=ErrorSource.DEVICE,
        general_sensor_readings={"vibration": 0.8, "door_locked": True},
        special_sensor_readings={"air_temperature": 110.0, "air_flow_speed": 0.3, "moisture": 30.0},
        change_of_state=True,
        change_of_state_report=trip_state_report,
    )
    resolution_report = DryerErrorResolutionReport(
        machine_id="dryer-integration",
        machine_type=MachineType.DRYER,
        report_id="resolution-01",
        recorded_at="2026-07-24T12:00:45Z",
        error_id="overtemperature-01",
        resolution_message="Dryer repaired",
        operation_state=OperationState.FAULTED,
        cycle_stage=DryerCyclePhase.DRYING,
        general_sensor_readings={"vibration": 0.1, "door_locked": True},
        special_sensor_readings={"air_temperature": 70.0, "air_flow_speed": 2.0, "moisture": 30.0},
    )
    recovery_state_report = DryerChangeOfStateReport(
        machine_id="dryer-integration",
        machine_type=MachineType.DRYER,
        report_id="recovery-state-01",
        recorded_at="2026-07-24T12:00:46Z",
        previous_operation_state=OperationState.FAULTED,
        new_operation_state=OperationState.IDLE,
        previous_cycle_stage=DryerCyclePhase.DRYING,
        new_cycle_stage=None,
        reason="Repair completed",
    )
    deregistration = DeregistrationRequest(
        machine_id="dryer-integration",
        deregistered_at="2026-07-24T12:01:00Z",
        reason="Integration test completed",
    )

    async def run_scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/api/v1/machines/register", json=registration.model_dump(mode="json"))
            assert response.status_code == 201

            response = await client.post("/api/v1/reports/change-of-state", json=start_report.model_dump(mode="json"))
            assert response.status_code == 200

            response = await client.post("/api/v1/reports/periodic", json=periodic_report.model_dump(mode="json"))
            assert response.status_code == 200
            assert response.json()["is_duplicate"] is False

            response = await client.post("/api/v1/reports/periodic", json=periodic_report.model_dump(mode="json"))
            assert response.status_code == 200
            assert response.json()["is_duplicate"] is True

            response = await client.post("/api/v1/reports/error", json=error_report.model_dump(mode="json"))
            assert response.status_code == 200

            response = await client.get("/api/v1/machines/dryer-integration")
            assert response.status_code == 200
            assert response.json()["operation_state"] == OperationState.FAULTED.value
            assert response.json()["latest_reading"]["special_readings"]["air_temperature"] == 110.0

            response = await client.get("/api/v1/faults?active=true")
            assert response.status_code == 200
            active_faults = response.json()
            assert [fault["error_id"] for fault in active_faults] == ["overtemperature-01"]
            fault_event_id = active_faults[0]["fault_event_id"]

            response = await client.get(f"/api/v1/faults/{fault_event_id}/context?minutes=5")
            assert response.status_code == 200
            fault_context = response.json()
            assert [reading["report_id"] for reading in fault_context["sensor_readings"]] == ["periodic-01", "error-01"]
            assert [event["report_id"] for event in fault_context["state_events"]] == ["start-state-01", "trip-state-01"]

            response = await client.post("/api/v1/machines/dryer-integration/faults/overtemperature-01/acknowledge")
            assert response.status_code == 200

            response = await client.post("/api/v1/reports/error-resolution", json=resolution_report.model_dump(mode="json"))
            assert response.status_code == 200

            response = await client.post("/api/v1/reports/change-of-state", json=recovery_state_report.model_dump(mode="json"))
            assert response.status_code == 200

            response = await client.get("/api/v1/faults?active=false")
            assert response.status_code == 200
            resolved_faults = response.json()
            assert [fault["error_id"] for fault in resolved_faults] == ["overtemperature-01"]
            assert resolved_faults[0]["is_acknowledged"] is True
            assert resolved_faults[0]["resolution_message"] == "Dryer repaired"

            response = await client.get("/api/v1/machines/dryer-integration")
            assert response.status_code == 200
            assert response.json()["operation_state"] == OperationState.IDLE.value

            response = await client.post("/api/v1/machines/deregister", json=deregistration.model_dump(mode="json"))
            assert response.status_code == 200
            assert (await client.get("/api/v1/machines/dryer-integration")).status_code == 404

    try:
        asyncio.run(run_scenario())
    finally:
        service.shutdown()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()
