# Provide the operator console with a small asynchronous FastAPI client.

from urllib.parse import quote

import httpx
from pydantic import TypeAdapter, ValidationError

from laundry_contracts.contracts import (
    DataEventResponse,
    FaultContextResponse,
    FaultEventResponse,
    MachineStatusResponse,
)


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api/v1"


class OperatorApiError(RuntimeError):
    """Represent a connection, HTTP, or response-validation failure."""


# Send validated asynchronous requests from the operator console to the backend.
class OperatorApiClient:
    # Initialize the reusable asynchronous HTTP client.
    def __init__(
        self,
        api_base_url: str = DEFAULT_API_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.http_client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=api_base_url.rstrip("/"),
            timeout=5.0,
            transport=transport,
        )

    # Close the underlying asynchronous HTTP connection pool.
    async def close(self) -> None:
        await self.http_client.aclose()

    # Send one request and convert transport and HTTP failures into one frontend error.
    async def _request_json(self,
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

    # Fetch and validate all current machine statuses.
    async def list_machines(self) -> list[MachineStatusResponse]:
        payload = await self._request_json("GET", "/machines")
        try:
            return TypeAdapter(list[MachineStatusResponse]).validate_python(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned invalid machine data") from error

    # Fetch and validate recent immutable data events.
    async def list_data_events(self) -> list[DataEventResponse]:
        payload = await self._request_json("GET", "/data-events", params={"limit": 100})
        try:
            return TypeAdapter(list[DataEventResponse]).validate_python(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned invalid data event data") from error

    # Fetch and validate active or resolved fault events.
    async def list_faults(self, active: bool) -> list[FaultEventResponse]:
        payload = await self._request_json("GET", "/faults", params={"limit": 100, "active": active})
        try:
            return TypeAdapter(list[FaultEventResponse]).validate_python(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned invalid fault data") from error

    # Fetch and validate the history surrounding one fault.
    async def get_fault_context(self, fault_event_id: int) -> FaultContextResponse:
        payload = await self._request_json(
            "GET",
            f"/faults/{fault_event_id}/context",
            params={"minutes": 5},
        )
        try:
            return FaultContextResponse.model_validate(payload)
        except ValidationError as error:
            raise OperatorApiError("Backend returned invalid fault context data") from error

    # Acknowledge one active machine fault.
    async def acknowledge_fault(self, machine_id: str, error_id: str) -> None:
        machine_path = quote(machine_id, safe="")
        error_path = quote(error_id, safe="")
        await self._request_json("POST", f"/machines/{machine_path}/faults/{error_path}/acknowledge")

    # Manually resolve one active machine fault.
    async def resolve_fault(
        self,
        machine_id: str,
        error_id: str,
        resolution_message: str,
    ) -> None:
        machine_path = quote(machine_id, safe="")
        error_path = quote(error_id, safe="")
        await self._request_json(
            "POST",
            f"/machines/{machine_path}/faults/{error_path}/resolve",
            json={"resolution_message": resolution_message},
        )
