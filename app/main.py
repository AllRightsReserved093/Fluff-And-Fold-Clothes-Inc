# Create and expose the FastAPI application.
# 创建并导出 FastAPI 应用。

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings


# Build the application and register its routes.
# 构建应用并注册路由。
def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
    )
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()

