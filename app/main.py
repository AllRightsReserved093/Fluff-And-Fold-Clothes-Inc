# Create and expose the FastAPI application.
# 创建并导出 FastAPI 应用。

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.database.session import initialize_database
from app.services.machine_service import machine_service


# Initialize persistent storage when the application starts.
# 在应用启动时初始化持久化存储。
@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncGenerator[None, None]:
    initialize_database()
    try:
        yield
    finally:
        machine_service.shutdown()


# Build the application and register its routes.
# 构建应用并注册路由。
def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
