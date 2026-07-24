# Provide the service health-check endpoint.

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


# Define the response returned by the health-check endpoint.
class HealthResponse(BaseModel):
    status: Literal["ok"]


# Report whether the API process is available.
@router.get("", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")
