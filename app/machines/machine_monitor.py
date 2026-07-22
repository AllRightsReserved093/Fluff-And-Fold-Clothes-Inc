# Monitor registered machines for heartbeat timeouts.
# 监控已注册机器是否发生心跳超时。

import heapq

from collections.abc import Callable
from threading import Condition, Event, Lock, Thread
from time import monotonic_ns


# Configuration
# Reports normally arrive every 15 seconds; allow 16 seconds before timeout.
# 报告通常每15秒到达一次；等待16秒后判定超时。
HEARTBEAT_TIMEOUT_MILLISECONDS = 16_000


# Return monotonic process time as integer milliseconds.
# 以整数毫秒返回进程单调时间。
def monotonic_milliseconds() -> int:
    return monotonic_ns() // 1_000_000


class MachineMonitor:
    # A queue to hold the machines being monitored.
    # (deadline_milliseconds, machine_id)
    is_working: bool = False
    monitor_heapq: list[tuple[int, str]]
    stop_event: Event
    monitor_thread: Thread | None
    monitor_heap_lock: Lock
    monitor_condition: Condition
    on_timeout: Callable[[str], object]

    def __init__(self, on_timeout: Callable[[str], object]):
        self.stop_event = Event()
        self.monitor_thread = None
        self.monitor_heapq = []
        self.monitor_heap_lock = Lock()
        self.monitor_condition = Condition(self.monitor_heap_lock)
        self.on_timeout = on_timeout

    def add_machine(self, machine) -> None:
        with self.monitor_condition:
            deadline_milliseconds = (
                monotonic_milliseconds()
                + HEARTBEAT_TIMEOUT_MILLISECONDS
            )
            heapq.heappush(
                self.monitor_heapq,
                (deadline_milliseconds, machine.machine_id),
            )
            self.monitor_condition.notify()

    def remove_machine(self, machine_id_to_remove: str) -> None:
        with self.monitor_condition:
            for index, (_, machine_id) in enumerate(self.monitor_heapq):
                if machine_id != machine_id_to_remove:
                    continue

                del self.monitor_heapq[index]
                heapq.heapify(self.monitor_heapq)
                self.monitor_condition.notify()
                return

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

    # Refresh an existing deadline or reinsert a machine after timeout.
    # 刷新已有截止时间，或在机器超时后将其重新插入。
    def update_machine(self, machine_id_to_update: str) -> None:
        with self.monitor_condition:
            deadline_milliseconds = (
                monotonic_milliseconds()
                + HEARTBEAT_TIMEOUT_MILLISECONDS
            )

            for index, (_, machine_id) in enumerate(self.monitor_heapq):
                if machine_id != machine_id_to_update:
                    continue

                if index == 0:
                    heapq.heappop(self.monitor_heapq)
                    heapq.heappush(
                        self.monitor_heapq,
                        (deadline_milliseconds, machine_id),
                    )
                else:
                    self.monitor_heapq[index] = (
                        deadline_milliseconds,
                        machine_id,
                    )
                    heapq.heapify(self.monitor_heapq)

                self.monitor_condition.notify()
                return

            heapq.heappush(
                self.monitor_heapq,
                (deadline_milliseconds, machine_id_to_update),
            )
            self.monitor_condition.notify()

    def end_monitor(self) -> None:
        with self.monitor_condition:
            self.stop_event.set()
            self.monitor_condition.notify_all()

        if self.monitor_thread is not None:
            self.monitor_thread.join()
            self.monitor_thread = None

        self.is_working = False

    # Wait for the next deadline while remaining alive when the heap is empty.
    # 等待下一个截止时间，并在堆为空时保持线程存活。
    def monitor_machines(self) -> None:
        try:
            while not self.stop_event.is_set():
                timeout_machine_id = None

                with self.monitor_condition:
                    while (
                        not self.monitor_heapq
                        and not self.stop_event.is_set()
                    ):
                        self.monitor_condition.wait()

                    if self.stop_event.is_set():
                        break

                    next_deadline, _ = self.monitor_heapq[0]
                    remaining_milliseconds = (
                        next_deadline - monotonic_milliseconds()
                    )

                    if remaining_milliseconds > 0:
                        self.monitor_condition.wait(
                            timeout=remaining_milliseconds / 1_000
                        )
                        continue

                    _, timeout_machine_id = heapq.heappop(
                        self.monitor_heapq
                    )

                # Notify the service only after releasing the heap lock.
                # 仅在释放监控堆锁后通知服务。
                if timeout_machine_id is not None:
                    self.on_timeout(timeout_machine_id)
        finally:
            self.is_working = False
