# Define persistent models for machines, sensor readings, and fault events.
# 定义机器、传感器读数和故障事件的持久化模型。

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from laundry_contracts.contracts import (
    ErrorSource,
    MachineType,
    OperationState,
)


# --------- Machines ---------


class MachineRecord(Base):
    __tablename__ = "machines"

    machine_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    machine_type: Mapped[MachineType] = mapped_column(
        Enum(
            MachineType,
            name="machine_type",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        ),
        nullable=False,
    )
    is_registered: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    operation_state: Mapped[OperationState | None] = mapped_column(
        Enum(
            OperationState,
            name="operation_state",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        )
    )
    cycle_stage: Mapped[str | None] = mapped_column(String(64))
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    sensor_readings: Mapped[list["SensorReadingRecord"]] = relationship(
        back_populates="machine"
    )
    fault_events: Mapped[list["FaultEventRecord"]] = relationship(
        back_populates="machine"
    )


# --------- Sensor Readings ---------


class SensorReadingRecord(Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (
        UniqueConstraint(
            "machine_id",
            "report_id",
            name="uq_sensor_readings_machine_report",
        ),
        Index(
            "ix_sensor_readings_machine_recorded_at",
            "machine_id",
            "recorded_at",
        ),
    )

    reading_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[str] = mapped_column(
        ForeignKey("machines.machine_id"),
        nullable=False,
    )
    report_id: Mapped[str] = mapped_column(String(128), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    operation_state: Mapped[OperationState] = mapped_column(
        Enum(
            OperationState,
            name="sensor_reading_operation_state",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        ),
        nullable=False,
    )
    cycle_stage: Mapped[str | None] = mapped_column(String(64))
    general_readings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    special_readings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    machine: Mapped[MachineRecord] = relationship(
        back_populates="sensor_readings"
    )


# --------- Fault Events ---------


class FaultEventRecord(Base):
    __tablename__ = "fault_events"
    __table_args__ = (
        UniqueConstraint(
            "machine_id",
            "error_id",
            name="uq_fault_events_machine_error",
        ),
        Index(
            "ix_fault_events_machine_resolved_at",
            "machine_id",
            "resolved_at",
        ),
        Index(
            "ix_fault_events_code_raised_at",
            "error_code",
            "raised_at",
        ),
    )

    fault_event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    error_id: Mapped[str] = mapped_column(String(128), nullable=False)
    machine_id: Mapped[str] = mapped_column(
        ForeignKey("machines.machine_id"),
        nullable=False,
    )
    report_id: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str] = mapped_column(String(128), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_source: Mapped[ErrorSource] = mapped_column(
        Enum(
            ErrorSource,
            name="error_source",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        ),
        nullable=False,
    )
    raised_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    machine: Mapped[MachineRecord] = relationship(back_populates="fault_events")
