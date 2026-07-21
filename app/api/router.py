# Aggregate versioned API routes in one router.
# 将版本化 API 路由集中到一个路由器中。

from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.register import router as machine_router
from app.api.routes.reports import router as report_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(machine_router)
api_router.include_router(report_router)
