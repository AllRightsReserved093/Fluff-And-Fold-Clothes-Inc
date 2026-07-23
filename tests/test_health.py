# Verify the public health-check contract through the ASGI application.
# 通过 ASGI 应用验证公开的健康检查接口契约。

import asyncio

from httpx import ASGITransport, AsyncClient, Response

from app import main as main_module


app = main_module.app


# Send a request without starting a network server.
# 无需启动网络服务器即可发送请求。
async def get_health_response() -> Response:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.get("/api/v1/health")


def test_health_check() -> None:
    response = asyncio.run(get_health_response())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_application_lifespan_initializes_database(monkeypatch) -> None:
    initialization_calls: list[bool] = []
    monkeypatch.setattr(
        main_module,
        "initialize_database",
        lambda: initialization_calls.append(True),
    )
    test_application = main_module.create_app()

    async def run_lifespan() -> None:
        async with test_application.router.lifespan_context(test_application):
            pass

    asyncio.run(run_lifespan())

    assert initialization_calls == [True]
