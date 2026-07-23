# Aggregate versioned API routes in one router.
# 将版本化 API 路由集中到一个路由器中。

from fastapi import APIRouter

from app.api.routes.data_events import router as data_event_router
from app.api.routes.faults import router as faults_router
from app.api.routes.health import router as health_router
from app.api.routes.machines import router as machine_query_router
from app.api.routes.readings import router as reading_router
from app.api.routes.register import router as machine_router
from app.api.routes.reports import router as report_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(machine_router)
api_router.include_router(report_router)
api_router.include_router(machine_query_router)
api_router.include_router(reading_router)
api_router.include_router(data_event_router)
api_router.include_router(faults_router)
