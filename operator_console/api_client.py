# Provide the operator console with a small asynchronous FastAPI client.
# 为操作员控制台提供一个精简的异步 FastAPI 客户端。

from urllib.parse import quote

import httpx
from pydantic import TypeAdapter, ValidationError

from laundry_contracts.contracts import (
    DataEventResponse,
    FaultAcknowledgementResponse,
    FaultContextResponse,
    FaultEventResponse,
    FaultResolutionResponse,
    MachineStatusResponse,
    SensorReadingResponse,
)


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api/v1"
DEFAULT_HTTP_TIMEOUT_SECONDS = 5.0


class OperatorApiError(RuntimeError):
    """Represent a connection, HTTP, or response-validation failure."""


class OperatorApiClient:
    def __init__(
        self,
        api_base_url: str = DEFAULT_API_BASE_URL,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.http_client = httpx.AsyncClient(
            base_url=api_base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )

    async def close(self) -> None:
        await self.http_client.aclose()

    # Send one request and convert transport and HTTP failures into one frontend error.
    # 发送一次请求，并将连接错误和 HTTP 错误统一转换为前端错误。
    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, bool | int | str] | None = None,
        json: dict[str, str | None] | None = None,
    ) -> object:
        try:
            response = await self.http_client.request(method, path, params=params, json=json)
        except httpx.RequestError as error:
            raise OperatorApiError(f"Cannot connect to the backend: {error}") from error

        if response.is_error:
            try:
                response_body = response.json()
                detail = response_body.get("detail", response.text) if isinstance(response_body, dict) else response.text
            except ValueError:
                detail = response.text
            raise OperatorApiError(f"Backend returned HTTP {response.status_code}: {detail or response.reason_phrase}")

        try:
            return response.json()
        except ValueError as error:
            raise OperatorApiError("Backend returned invalid JSON") from error

    async def health(self) -> bool:
        payload = await self._request_json("GET", "/health")
        if not isinstance(payload, dict):
            raise OperatorApiError("Backend returned an invalid health response")
        return payload.get("status") == "ok"

    async def list_machines(self) -> list[MachineStatusResponse]:
        payload = await self._request_json("GET", "/machines")
        try:
            return TypeAdapter(list[MachineStatusResponse]).validate_python(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned invalid machine data") from error

    async def get_machine(self, machine_id: str) -> MachineStatusResponse:
        payload = await self._request_json("GET", f"/machines/{quote(machine_id, safe='')}")
        try:
            return MachineStatusResponse.model_validate(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned invalid machine data") from error

    async def list_readings(self, machine_id: str, limit: int = 20) -> list[SensorReadingResponse]:
        payload = await self._request_json(
            "GET",
            f"/machines/{quote(machine_id, safe='')}/readings",
            params={"limit": limit},
        )
        try:
            return TypeAdapter(list[SensorReadingResponse]).validate_python(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned invalid sensor reading data") from error

    async def list_data_events(
        self,
        machine_id: str | None = None,
        event_code: str | None = None,
        limit: int = 100,
    ) -> list[DataEventResponse]:
        params: dict[str, int | str] = {"limit": limit}
        if machine_id is not None:
            params["machine_id"] = machine_id
        if event_code is not None:
            params["event_code"] = event_code

        payload = await self._request_json("GET", "/data-events", params=params)
        try:
            return TypeAdapter(list[DataEventResponse]).validate_python(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned invalid data event data") from error

    async def list_faults(
        self,
        active: bool | None = None,
        acknowledged: bool | None = None,
        limit: int = 100,
    ) -> list[FaultEventResponse]:
        params: dict[str, bool | int] = {"limit": limit}
        if active is not None:
            params["active"] = active
        if acknowledged is not None:
            params["acknowledged"] = acknowledged

        payload = await self._request_json("GET", "/faults", params=params)
        try:
            return TypeAdapter(list[FaultEventResponse]).validate_python(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned invalid fault data") from error

    async def list_machine_faults(
        self,
        machine_id: str,
        active: bool | None = None,
        acknowledged: bool | None = None,
        limit: int = 100,
    ) -> list[FaultEventResponse]:
        params: dict[str, bool | int] = {"limit": limit}
        if active is not None:
            params["active"] = active
        if acknowledged is not None:
            params["acknowledged"] = acknowledged

        payload = await self._request_json(
            "GET",
            f"/machines/{quote(machine_id, safe='')}/faults",
            params=params,
        )
        try:
            return TypeAdapter(list[FaultEventResponse]).validate_python(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned invalid fault data") from error

    async def get_fault_context(self, fault_event_id: int, minutes: int = 5) -> FaultContextResponse:
        payload = await self._request_json(
            "GET",
            f"/faults/{fault_event_id}/context",
            params={"minutes": minutes},
        )
        try:
            return FaultContextResponse.model_validate(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned invalid fault context data") from error

    async def acknowledge_fault(self, machine_id: str, error_id: str) -> FaultAcknowledgementResponse:
        machine_path = quote(machine_id, safe="")
        error_path = quote(error_id, safe="")
        payload = await self._request_json("POST", f"/machines/{machine_path}/faults/{error_path}/acknowledge")
        try:
            return FaultAcknowledgementResponse.model_validate(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned an invalid acknowledgement response") from error

    async def resolve_fault(
        self,
        machine_id: str,
        error_id: str,
        resolution_message: str | None = None,
    ) -> FaultResolutionResponse:
        machine_path = quote(machine_id, safe="")
        error_path = quote(error_id, safe="")
        payload = await self._request_json(
            "POST",
            f"/machines/{machine_path}/faults/{error_path}/resolve",
            json={"resolution_message": resolution_message},
        )
        try:
            return FaultResolutionResponse.model_validate(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned an invalid resolution response") from error
