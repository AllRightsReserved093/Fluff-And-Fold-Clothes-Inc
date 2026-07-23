# Provide operator-facing immutable data event queries.
# 提供面向操作员的不可变数据事件查询接口。

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.services.machine_service import machine_service
from laundry_contracts.contracts import DataEventResponse


router = APIRouter(prefix="/data-events", tags=["data events"])


@router.get("", response_model=list[DataEventResponse])
def list_data_events(
    machine_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    event_code: Annotated[str | None, Query(pattern=r"^D[0-9]{4}$")] = None,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 100,
) -> list[DataEventResponse]:
    data_events = machine_service.list_data_events(machine_id, event_code, limit)
    if data_events is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")
    return data_events
