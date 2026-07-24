# Monitor registered machines for heartbeat timeouts.

import heapq
import logging

from collections.abc import Callable
from datetime import datetime
from threading import Condition, Event, Lock, Thread
from time import monotonic_ns

from app.machines.machines import Machine


logger = logging.getLogger(__name__)


# Configuration
# Reports normally arrive every 15 seconds; allow 16 seconds before timeout.
HEARTBEAT_TIMEOUT_MILLISECONDS = 16_000


# Return monotonic process time as integer milliseconds.
def monotonic_milliseconds() -> int:
    return monotonic_ns() // 1_000_000


# Track machine heartbeat deadlines on a dedicated worker thread.
class MachineMonitor:
    # --------- Monitor State ---------

    # A queue to hold the machines being monitored.
    # (deadline_milliseconds, machine_id, recorded_at)
    def __init__(self, on_timeout: Callable[[str, datetime | None], object]) -> None:
        self.is_working: bool = False
        self.monitor_heapq: list[tuple[int, str, datetime | None]] = []
        self.stop_event: Event = Event()
        self.monitor_thread: Thread | None = None
        self.monitor_heap_lock: Lock = Lock()
        self.monitor_condition: Condition = Condition(self.monitor_heap_lock)
        self.on_timeout: Callable[[str, datetime | None], object] = on_timeout

    # --------- Queue Management ---------

    # Add a machine with a fresh heartbeat deadline.
    def add_machine(self, machine: Machine) -> None:
        with self.monitor_condition:
            deadline_milliseconds = (
                monotonic_milliseconds()
                + HEARTBEAT_TIMEOUT_MILLISECONDS
            )
            heapq.heappush(
                self.monitor_heapq,
                (deadline_milliseconds, machine.machine_id, machine.recorded_at),
            )
            self.monitor_condition.notify()

    # Remove one machine from the heartbeat deadline queue.
    def remove_machine(self, machine_id_to_remove: str) -> None:
        with self.monitor_condition:
            for index, (_, machine_id, _) in enumerate(self.monitor_heapq):
                if machine_id != machine_id_to_remove:
                    continue

                del self.monitor_heapq[index]
                heapq.heapify(self.monitor_heapq)
                self.monitor_condition.notify()
                return

    # Refresh an existing deadline or reinsert a machine after timeout.
    def update_machine(self, machine_id_to_update: str, recorded_at: datetime | None) -> None:
        with self.monitor_condition:
            deadline_milliseconds = (
                monotonic_milliseconds()
                + HEARTBEAT_TIMEOUT_MILLISECONDS
            )

            for index, (_, machine_id, _) in enumerate(self.monitor_heapq):
                if machine_id != machine_id_to_update:
                    continue

                if index == 0:
                    heapq.heappop(self.monitor_heapq)
                    heapq.heappush(
                        self.monitor_heapq,
                        (deadline_milliseconds, machine_id, recorded_at),
                    )
                else:
                    self.monitor_heapq[index] = (
                        deadline_milliseconds,
                        machine_id,
                        recorded_at,
                    )
                    heapq.heapify(self.monitor_heapq)

                self.monitor_condition.notify()
                return

            heapq.heappush(
                self.monitor_heapq,
                (deadline_milliseconds, machine_id_to_update, recorded_at),
            )
            self.monitor_condition.notify()

    # --------- Worker Lifecycle ---------

    # Start the heartbeat worker when it is not already running.
    def start_monitor(self) -> None:
        if (
            self.monitor_thread is not None
            and self.monitor_thread.is_alive()
        ):
            return

        self.stop_event.clear()
        self.monitor_thread = Thread(
            target=self.monitor_machines,
            daemon=True,
        )
        self.is_working = True
        self.monitor_thread.start()

    # Stop the heartbeat worker and wait for its thread to finish.
    def end_monitor(self) -> None:
        with self.monitor_condition:
            self.stop_event.set()
            self.monitor_condition.notify()

        if self.monitor_thread is not None:
            self.monitor_thread.join()
            self.monitor_thread = None

        self.is_working = False

    # Wait for the next deadline while remaining alive when the heap is empty.
    def monitor_machines(self) -> None:
        try:
            while not self.stop_event.is_set():
                timeout_machine_id = None
                timeout_recorded_at = None

                with self.monitor_condition:
                    while (
                        not self.monitor_heapq
                        and not self.stop_event.is_set()
                    ):
                        self.monitor_condition.wait()

                    if self.stop_event.is_set():
                        break

                    next_deadline, _, _ = self.monitor_heapq[0]
                    remaining_milliseconds = (
                        next_deadline - monotonic_milliseconds()
                    )

                    if remaining_milliseconds > 0:
                        self.monitor_condition.wait(
                            timeout=remaining_milliseconds / 1_000
                        )
                        continue

                    _, timeout_machine_id, timeout_recorded_at = heapq.heappop(
                        self.monitor_heapq
                    )

                # Notify the service only after releasing the heap lock.
                if timeout_machine_id is not None:
                    try:
                        self.on_timeout(timeout_machine_id, timeout_recorded_at)
                    except Exception:
                        logger.exception("Heartbeat timeout callback failed for machine %s", timeout_machine_id)
                        if not self.stop_event.is_set():
                            with self.monitor_condition:
                                already_scheduled = False
                                for _, machine_id, _ in self.monitor_heapq:
                                    if machine_id == timeout_machine_id:
                                        already_scheduled = True
                                        break

                                if not already_scheduled:
                                    retry_deadline = monotonic_milliseconds() + HEARTBEAT_TIMEOUT_MILLISECONDS
                                    heapq.heappush(
                                        self.monitor_heapq,
                                        (retry_deadline, timeout_machine_id, timeout_recorded_at),
                                    )
                                    self.monitor_condition.notify()
        finally:
            self.is_working = False
