# Provide operator-facing machine status query endpoints.
# 提供面向操作员的机器状态查询接口。

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from app.services.machine_service import machine_service
from laundry_contracts.contracts import MachineStatusResponse


router = APIRouter(prefix="/machines", tags=["machines"])


@router.get("", response_model=list[MachineStatusResponse])
def list_machines() -> list[MachineStatusResponse]:
    return machine_service.list_machines()


@router.get("/{machine_id}", response_model=MachineStatusResponse)
def get_machine(machine_id: Annotated[str, Path(min_length=1, max_length=128)]) -> MachineStatusResponse:
    machine = machine_service.get_machine(machine_id)
    if machine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found")
    return machine
