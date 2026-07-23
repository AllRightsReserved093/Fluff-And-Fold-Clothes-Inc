# Provide operator-facing fault management endpoints.
# 提供面向操作员的故障管理接口。

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.services.machine_service import machine_service
from laundry_contracts.contracts import (
    FaultAcknowledgementResponse,
    FaultEventResponse,
    FaultResolutionRequest,
    FaultResolutionResponse,
)


router = APIRouter(tags=["faults"])


@router.get("/faults", response_model=list[FaultEventResponse])
def list_faults(
    active: Annotated[bool | None, Query()] = None,
    acknowledged: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 100,
) -> list[FaultEventResponse]:
    faults = machine_service.list_faults(None, active, acknowledged, limit)
    return faults if faults is not None else []


@router.get("/machines/{machine_id}/faults", response_model=list[FaultEventResponse])
def list_machine_faults(
    machine_id: Annotated[str, Path(min_length=1, max_length=128)],
    active: Annotated[bool | None, Query()] = None,
    acknowledged: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 100,
) -> list[FaultEventResponse]:
    faults = machine_service.list_faults(machine_id, active, acknowledged, limit)
    if faults is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")
    return faults


# Acknowledge one known machine fault without resolving it.
# 确认一条已知机器故障，但不解除该故障。
@router.post("/machines/{machine_id}/faults/{error_id}/acknowledge", response_model=FaultAcknowledgementResponse)
def acknowledge_fault(
    machine_id: Annotated[str, Path(min_length=1, max_length=128)],
    error_id: Annotated[str, Path(min_length=1, max_length=128)],
) -> FaultAcknowledgementResponse:
    if not machine_service.acknowledge_error(machine_id, error_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Machine or fault not found",
        )

    return FaultAcknowledgementResponse(
        machine_id=machine_id,
        error_id=error_id,
        is_acknowledged=True,
    )


# Manually resolve one known machine fault without deleting its history.
# 手动解除一条已知机器故障，但不删除其历史记录。
@router.post("/machines/{machine_id}/faults/{error_id}/resolve", response_model=FaultResolutionResponse)
def resolve_fault(
    machine_id: Annotated[str, Path(min_length=1, max_length=128)],
    error_id: Annotated[str, Path(min_length=1, max_length=128)],
    request: FaultResolutionRequest,
) -> FaultResolutionResponse:
    if not machine_service.resolve_error(machine_id, error_id, request.resolution_message):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine or fault not found")
    return FaultResolutionResponse(machine_id=machine_id, error_id=error_id, is_resolved=True)
