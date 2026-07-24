# Verify the SQLite database scaffold and its five core tables.

from sqlalchemy import create_engine, inspect

from app.database.base import Base
from app.database import models  # noqa: F401


def test_database_declares_five_core_tables() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)

    table_names = set(inspect(test_engine).get_table_names())

    assert table_names == {
        "machines",
        "machine_state_events",
        "data_events",
        "sensor_readings",
        "fault_events",
    }


def test_history_tables_reference_machines() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    database_inspector = inspect(test_engine)

    state_event_foreign_keys = database_inspector.get_foreign_keys(
        "machine_state_events"
    )
    reading_foreign_keys = database_inspector.get_foreign_keys("sensor_readings")
    fault_foreign_keys = database_inspector.get_foreign_keys("fault_events")
    data_event_foreign_keys = database_inspector.get_foreign_keys("data_events")

    assert state_event_foreign_keys[0]["referred_table"] == "machines"
    assert reading_foreign_keys[0]["referred_table"] == "machines"
    assert fault_foreign_keys[0]["referred_table"] == "machines"
    assert data_event_foreign_keys[0]["referred_table"] == "machines"


def test_fault_events_include_acknowledgement_state() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)

    fault_columns = {column["name"] for column in inspect(test_engine).get_columns("fault_events")}

    assert "is_acknowledged" in fault_columns


def test_data_events_do_not_include_fault_lifecycle_state() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)

    data_event_columns = {column["name"] for column in inspect(test_engine).get_columns("data_events")}

    assert "is_acknowledged" not in data_event_columns
    assert "resolved_at" not in data_event_columns
