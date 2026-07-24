# Verify the public health-check contract through the ASGI application.

import asyncio

from httpx import ASGITransport, AsyncClient, Response

from app import main as main_module


app = main_module.app


# Send a request without starting a network server.
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


def test_application_lifespan_initializes_and_restores_database(monkeypatch) -> None:
    lifecycle_calls: list[str] = []
    monkeypatch.setattr(
        main_module,
        "initialize_database",
        lambda: lifecycle_calls.append("initialize"),
    )
    monkeypatch.setattr(
        main_module.machine_service,
        "restore_from_database",
        lambda: lifecycle_calls.append("restore"),
    )
    monkeypatch.setattr(
        main_module.machine_service,
        "shutdown",
        lambda: lifecycle_calls.append("shutdown"),
    )
    test_application = main_module.create_app()

    async def run_lifespan() -> None:
        async with test_application.router.lifespan_context(test_application):
            assert lifecycle_calls == ["initialize", "restore"]

    asyncio.run(run_lifespan())

    assert lifecycle_calls == ["initialize", "restore", "shutdown"]
