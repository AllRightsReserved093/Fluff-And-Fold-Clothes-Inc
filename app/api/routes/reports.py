# Receive device reports and delegate processing to the machine service.
# 接收设备报告，并将处理交给机器服务。

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from app.services.machine_service import machine_service
from laundry_contracts.contracts import (
    ChangeOfStateReport,
    ErrorReport,
    PeriodicReport,
    ReportAcceptedResponse,
)


router = APIRouter(prefix="/reports", tags=["reports"])


# --------- API Endpoints ----------


@router.post("/periodic", response_model=ReportAcceptedResponse)
def receive_periodic_report(
    report: PeriodicReport,
) -> ReportAcceptedResponse:
    if not machine_service.handle_periodic_report(report):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Machine is not registered",
        )

    return ReportAcceptedResponse(
        machine_id=report.machine_id,
        report_id=report.report_id,
        accepted_at=datetime.now(UTC),
    )


@router.post("/change-of-state", response_model=ReportAcceptedResponse)
def receive_change_of_state_report(
    report: ChangeOfStateReport,
) -> ReportAcceptedResponse:
    if not machine_service.handle_change_of_state_report(report):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Machine is not registered",
        )

    return ReportAcceptedResponse(
        machine_id=report.machine_id,
        report_id=report.report_id,
        accepted_at=datetime.now(UTC),
    )


@router.post("/error", response_model=ReportAcceptedResponse)
def receive_error_report(
    report: ErrorReport,
) -> ReportAcceptedResponse:
    if not machine_service.handle_error_report(report):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Machine is not registered",
        )

    return ReportAcceptedResponse(
        machine_id=report.machine_id,
        report_id=report.report_id,
        accepted_at=datetime.now(UTC),
    )
