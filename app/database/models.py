# Define persistent models for machines, state events, data events, sensor readings, and faults.

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
    StateEventSource,
)


# --------- Machines ---------

# Storage of current machine state
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
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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

    # Server-observed last contact time, separate from the device event time.
    last_online: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sensor_readings: Mapped[list["SensorReadingRecord"]] = relationship(
        back_populates="machine"
    )
    state_events: Mapped[list["MachineStateEventRecord"]] = relationship(
        back_populates="machine"
    )
    fault_events: Mapped[list["FaultEventRecord"]] = relationship(
        back_populates="machine"
    )
    data_events: Mapped[list["DataEventRecord"]] = relationship(
        back_populates="machine"
    )


# --------- Machine State Events ---------


# Persist one immutable machine state transition.
class MachineStateEventRecord(Base):
    __tablename__ = "machine_state_events"
    __table_args__ = (
        UniqueConstraint(
            "machine_id",
            "report_id",
            name="uq_machine_state_events_machine_report",
        ),
        Index(
            "ix_machine_state_events_machine_recorded_at",
            "machine_id",
            "recorded_at",
        ),
    )

    state_event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[str] = mapped_column(
        ForeignKey("machines.machine_id"),
        nullable=False,
    )
    report_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_source: Mapped[StateEventSource] = mapped_column(
        Enum(
            StateEventSource,
            name="state_event_source",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        ),
        nullable=False,
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    previous_operation_state: Mapped[OperationState] = mapped_column(
        Enum(
            OperationState,
            name="previous_machine_operation_state",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        ),
        nullable=False,
    )
    new_operation_state: Mapped[OperationState] = mapped_column(
        Enum(
            OperationState,
            name="new_machine_operation_state",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        ),
        nullable=False,
    )
    previous_cycle_stage: Mapped[str | None] = mapped_column(String(64))
    new_cycle_stage: Mapped[str | None] = mapped_column(String(64))

    reason: Mapped[str | None] = mapped_column(Text)

    machine: Mapped[MachineRecord] = relationship(back_populates="state_events")


# --------- Data Events ---------


# Store immutable data-quality and report-consistency events.
class DataEventRecord(Base):
    __tablename__ = "data_events"
    __table_args__ = (
        UniqueConstraint(
            "machine_id",
            "report_id",
            "event_code",
            name="uq_data_events_machine_report_code",
        ),
        Index(
            "ix_data_events_machine_recorded_at",
            "machine_id",
            "recorded_at",
        ),
    )

    data_event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[str] = mapped_column(
        ForeignKey("machines.machine_id"),
        nullable=False,
    )
    report_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_code: Mapped[str] = mapped_column(String(16), nullable=False)
    event_message: Mapped[str] = mapped_column(Text, nullable=False)
    event_details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    machine: Mapped[MachineRecord] = relationship(back_populates="data_events")


# --------- Sensor Readings ---------


# Persist one historical machine sensor reading.
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

    operation_state: Mapped[OperationState | None] = mapped_column(
        Enum(
            OperationState,
            name="sensor_reading_operation_state",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        ),
        nullable=True,
    )
    cycle_stage: Mapped[str | None] = mapped_column(String(64))

    general_readings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    special_readings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    machine: Mapped[MachineRecord] = relationship(
        back_populates="sensor_readings"
    )


# --------- Fault Events ---------


# Persist one fault from detection through acknowledgement and resolution.
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
    machine_id: Mapped[str] = mapped_column(
        ForeignKey("machines.machine_id"),
        nullable=False,
    )
    report_id: Mapped[str | None] = mapped_column(String(128))
    error_id: Mapped[str] = mapped_column(String(128), nullable=False)

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
    is_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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
