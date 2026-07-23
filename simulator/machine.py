# Provide shared machine state and HTTP communication helpers.
# 提供机器共用状态与 HTTP 通信辅助方法。

from datetime import UTC, datetime
from uuid import uuid4

import httpx
from pydantic import BaseModel

from laundry_contracts.contracts import DeregistrationRequest, DryerCyclePhase, MachineType, OperationState, RegistrationRequest, WasherCyclePhase


REPORT_INTERVAL_SECONDS = 15.0
IDLE_DURATION_SECONDS = 10.0
COMPLETE_DURATION_SECONDS = 10.0

CycleStage = WasherCyclePhase | DryerCyclePhase | None


class Machine:
    def __init__(self, machine_id: str, machine_type: MachineType, http_client: httpx.Client, api_base_url: str) -> None:
        self.machine_id = machine_id
        self.machine_type = machine_type
        self.http_client = http_client
        self.api_base_url = api_base_url.rstrip("/")

        self.operation_state = OperationState.IDLE
        self.cycle_stage: CycleStage = None
        self.phase_elapsed_seconds = 0.0

        self.is_registered = False
        self.next_report_at = 0.0
        self.vibration = 0.1
        self.door_locked = False

    # Advance the current phase timer and report whether its duration was reached.
    # 推进当前阶段计时，并返回是否已经达到阶段时长。
    def advance_phase_timer(self, elapsed_seconds: float, duration_seconds: float) -> bool:
        self.phase_elapsed_seconds += elapsed_seconds
        return self.phase_elapsed_seconds >= duration_seconds

    def register(self) -> bool:
        request = RegistrationRequest(machine_id=self.machine_id, machine_type=self.machine_type, registered_at=datetime.now(UTC))
        self.is_registered = self.post("/machines/register", request, {201, 409})
        return self.is_registered

    def deregister(self) -> bool:
        if not self.is_registered:
            return True

        request = DeregistrationRequest(machine_id=self.machine_id, deregistered_at=datetime.now(UTC), reason="Simulator shutdown")
        succeeded = self.post("/machines/deregister", request, {200})
        if succeeded:
            self.is_registered = False
        return succeeded

    def post(self, path: str, contract: BaseModel, expected_status_codes: set[int]) -> bool:
        try:
            response = self.http_client.post(f"{self.api_base_url}{path}", json=contract.model_dump(mode="json"))
        except httpx.RequestError as error:
            print(f"[{self.machine_id}] HTTP request failed: {error}")
            return False

        if response.status_code not in expected_status_codes:
            print(f"[{self.machine_id}] HTTP {response.status_code} returned for {path}")
            return False
        return True

    def new_report_id(self, report_type: str) -> str:
        return f"{report_type}-{uuid4()}"
