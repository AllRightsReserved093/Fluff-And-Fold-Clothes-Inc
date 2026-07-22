# Verify UTC timestamp normalization and monotonic millisecond deadlines.
# 验证 UTC 时间归一化与单调毫秒 deadline。

from datetime import UTC
from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import app.machines.machine_monitor as monitor_module
from app.machines.machine_monitor import monotonic_milliseconds
from app.machines.machines import Machine
from laundry_contracts.contracts import MachineType, RegistrationRequest


def test_registration_time_is_normalized_to_utc() -> None:
    request = RegistrationRequest(
        machine_id="washer-01",
        machine_type="washer",
        registered_at="2026-07-20T12:00:00-07:00",
    )

    assert request.registered_at.isoformat() == "2026-07-20T19:00:00+00:00"


def test_registration_time_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        RegistrationRequest(
            machine_id="washer-01",
            machine_type="washer",
            registered_at="2026-07-20T12:00:00",
        )


def test_machine_uses_utc_registration_time() -> None:
    machine = Machine("washer-01", MachineType.WASHER)

    machine.register()

    assert machine.first_registered is not None
    assert machine.first_registered.tzinfo is UTC


def test_monotonic_time_is_expressed_as_integer_milliseconds() -> None:
    current_time = monotonic_milliseconds()

    assert isinstance(current_time, int)


def test_monitor_waits_until_millisecond_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        monitor_module,
        "HEARTBEAT_TIMEOUT_MILLISECONDS",
        30,
    )
    timeout_event = Event()
    monitor = monitor_module.MachineMonitor(
        lambda _machine_id: timeout_event.set()
    )
    monitor.add_machine(SimpleNamespace(machine_id="test-machine"))

    started = monotonic()
    monitor.start_monitor()
    thread = monitor.monitor_thread

    assert thread is not None
    try:
        assert timeout_event.wait(timeout=1)
        elapsed_milliseconds = (monotonic() - started) * 1_000

        assert thread.is_alive()
        assert elapsed_milliseconds >= 25
        assert elapsed_milliseconds < 1_000
    finally:
        monitor.end_monitor()

    assert not thread.is_alive()


def test_timeout_callback_runs_after_monitor_lock_is_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        monitor_module,
        "HEARTBEAT_TIMEOUT_MILLISECONDS",
        0,
    )
    lock_was_available: list[bool] = []
    timeout_event = Event()

    def on_timeout(_machine_id: str) -> None:
        lock_acquired = monitor.monitor_heap_lock.acquire(blocking=False)
        lock_was_available.append(lock_acquired)
        if lock_acquired:
            monitor.monitor_heap_lock.release()
        timeout_event.set()

    monitor = monitor_module.MachineMonitor(on_timeout)
    monitor.add_machine(SimpleNamespace(machine_id="test-machine"))
    monitor.start_monitor()
    thread = monitor.monitor_thread

    assert thread is not None
    try:
        assert timeout_event.wait(timeout=1)
        assert thread.is_alive()
        assert lock_was_available == [True]
    finally:
        monitor.end_monitor()

    assert not thread.is_alive()


def test_monitor_waits_on_empty_heap_and_wakes_for_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        monitor_module,
        "HEARTBEAT_TIMEOUT_MILLISECONDS",
        20,
    )
    timed_out_machine_ids: list[str] = []
    timeout_event = Event()

    def on_timeout(machine_id: str) -> None:
        timed_out_machine_ids.append(machine_id)
        timeout_event.set()

    monitor = monitor_module.MachineMonitor(on_timeout)
    monitor.start_monitor()
    thread = monitor.monitor_thread

    assert thread is not None

    try:
        assert thread.is_alive()
        monitor.update_machine("recovered-machine")
        assert timeout_event.wait(timeout=1)
        assert timed_out_machine_ids == ["recovered-machine"]
        assert thread.is_alive()
    finally:
        monitor.end_monitor()

    assert not thread.is_alive()


def test_update_machine_does_not_create_duplicate_entries() -> None:
    monitor = monitor_module.MachineMonitor(lambda _machine_id: None)

    monitor.update_machine("washer-01")
    monitor.update_machine("washer-01")

    assert len(monitor.monitor_heapq) == 1
    assert monitor.monitor_heapq[0][1] == "washer-01"
