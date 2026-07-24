# Provide operator-facing sensor reading query endpoints.

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.services.machine_service import machine_service
from laundry_contracts.contracts import OperationState, SensorReadingResponse


router = APIRouter(prefix="/machines", tags=["readings"])


# Return filtered sensor reading history for one machine.
@router.get("/{machine_id}/readings", response_model=list[SensorReadingResponse])
def list_machine_readings(
    machine_id: Annotated[str, Path(min_length=1, max_length=128)],
    start_time: Annotated[datetime | None, Query()] = None,
    end_time: Annotated[datetime | None, Query()] = None,
    operation_state: Annotated[OperationState | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 100,
) -> list[SensorReadingResponse]:
    if start_time is not None and end_time is not None and start_time > end_time:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start_time cannot be later than end_time")

    readings = machine_service.list_sensor_readings(machine_id, start_time, end_time, operation_state, limit)
    if readings is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")
    return readings
