# Monitor registered machines for heartbeat timeouts.
# 监控已注册机器是否发生心跳超时。

import heapq

from collections.abc import Callable
from threading import Event, Lock, Thread
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
    # A queue to hold the machines being monitored
    # (deadline_milliseconds, machine_id)
    is_working: bool = False
    monitor_heapq: list[tuple[int, str]]

    stop_event: Event
    monitor_thread: Thread | None
    # Protect all reads and writes to the monitor heap.
    # 保护监控堆的所有读取和写入操作。
    monitor_heap_lock: Lock
    on_timeout: Callable[[str], object]

    def __init__(self, on_timeout: Callable[[str], object]):
        self.stop_event = Event()
        self.monitor_thread = None
        self.monitor_heapq = []
        self.monitor_heap_lock = Lock()
        self.on_timeout = on_timeout

    def add_machine(self, machine):
        # Add a machine to the monitor queue
        with self.monitor_heap_lock:
            deadline_milliseconds = (monotonic_milliseconds() + HEARTBEAT_TIMEOUT_MILLISECONDS)

            heapq.heappush(self.monitor_heapq, (deadline_milliseconds, machine.machine_id))
        
    def remove_machine(self, machine_id_to_remove):
        with self.monitor_heap_lock:
            for i, (_, machine_id) in enumerate(self.monitor_heapq):
                if machine_id == machine_id_to_remove:
                    del self.monitor_heapq[i]
                    heapq.heapify(self.monitor_heapq)
                    break
        
    def start_monitor(self):
        if (self.monitor_thread is not None and self.monitor_thread.is_alive()):
            return

        # monitor thread setup
        self.stop_event.clear()
        self.monitor_thread = Thread(target=self.monitor_machines, daemon=True)
        self.is_working = True
        self.monitor_thread.start()

    # Update the deadline for a specific machine
    # In the most of the cases, the machine that is being updated is at the top of the heap.
    # In those cases, the overall time complexity should be O(log n)
    def update_machine(self, machine_id_to_update: str):
        with self.monitor_heap_lock:
            deadline_milliseconds = (monotonic_milliseconds() + HEARTBEAT_TIMEOUT_MILLISECONDS)
            for i, (_, machine_id) in enumerate(self.monitor_heapq):
                if machine_id == machine_id_to_update:
                    # Update the machine's deadline
                    if i == 0:
                        # This machine is at the top of the heap
                        _ = heapq.heappop(self.monitor_heapq)
                        heapq.heappush(self.monitor_heapq, (deadline_milliseconds, machine_id))
                    else:
                        # This machine is not at the top of the heap
                        self.monitor_heapq[i] = (deadline_milliseconds, machine_id)
                        heapq.heapify(self.monitor_heapq)
                    break
        
    def end_monitor(self):
        self.stop_event.set()

        if self.monitor_thread is not None:
            self.monitor_thread.join()
            self.monitor_thread = None

        self.is_working = False

    # The main monitoring loop
    def monitor_machines(self):
        with self.monitor_heap_lock:
            if not self.monitor_heapq:
                self.is_working = False
                return
        
        while not self.stop_event.is_set():
            timeout_machine_id = None

            with self.monitor_heap_lock:
                if not self.monitor_heapq:
                    break

                # Check the status of each machine
                next_deadline, _ = self.monitor_heapq[0]
                remaining_milliseconds = (
                    next_deadline - monotonic_milliseconds()
                )

                if remaining_milliseconds <= 0:
                    # Machine is not responding
                    # 设置机器为离线状态
                    _, timeout_machine_id = heapq.heappop(self.monitor_heapq)

            # Notify the service only after releasing the monitor heap lock.
            # 仅在释放监控堆锁后通知服务。
            if timeout_machine_id is not None:
                self.on_timeout(timeout_machine_id)

            if remaining_milliseconds > 0:
                # Deadline not passed
                if self.stop_event.wait(
                    remaining_milliseconds / 1_000
                ):
                    break

                continue
            else:
                continue

        # The monitoring thread has stopped.
        # 监控线程已经停止。
        self.is_working = False
