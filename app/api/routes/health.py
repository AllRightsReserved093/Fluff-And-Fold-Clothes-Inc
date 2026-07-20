# Provide the service health-check endpoint.
# 提供服务健康检查端点。

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


# Report whether the API process is available.
# 返回 API 进程是否可用。
@router.get("", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")

