# Verify the SQLite database scaffold and its three core tables.
# 验证 SQLite 数据库骨架及其三张核心表。

from sqlalchemy import create_engine, inspect

from app.database.base import Base
from app.database import models  # noqa: F401


def test_database_declares_three_core_tables() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)

    table_names = set(inspect(test_engine).get_table_names())

    assert table_names == {
        "machines",
        "sensor_readings",
        "fault_events",
    }


def test_readings_and_faults_reference_machines() -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    database_inspector = inspect(test_engine)

    reading_foreign_keys = database_inspector.get_foreign_keys("sensor_readings")
    fault_foreign_keys = database_inspector.get_foreign_keys("fault_events")

    assert reading_foreign_keys[0]["referred_table"] == "machines"
    assert fault_foreign_keys[0]["referred_table"] == "machines"
