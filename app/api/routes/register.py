# Provide machine registration and deregistration endpoints.
# 提供机器注册与注销接口。

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from app.services.machine_service import machine_service
from laundry_contracts.contracts import (
    DeregistrationRequest,
    DeregistrationResponse,
    RegistrationRequest,
    RegistrationResponse,
)


router = APIRouter(prefix="/machines", tags=["machines"])


@router.post(
    "/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_machine(request: RegistrationRequest) -> RegistrationResponse:
    if not machine_service.machine_register(
        request.machine_id,
        request.machine_type,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Machine is already registered",
        )

    return RegistrationResponse(
        machine_id=request.machine_id,
        machine_type=request.machine_type,
        accepted_at=datetime.now(UTC),
    )


@router.post(
    "/deregister",
    response_model=DeregistrationResponse,
)
def deregister_machine(
    request: DeregistrationRequest,
) -> DeregistrationResponse:
    if not machine_service.machine_deregister(request.machine_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Machine is not registered",
        )

    return DeregistrationResponse(
        machine_id=request.machine_id,
        accepted_at=datetime.now(UTC),
    )
