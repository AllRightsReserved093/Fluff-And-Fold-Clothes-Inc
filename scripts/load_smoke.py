# Run a short concurrent load smoke test against a real Uvicorn process and temporary SQLite database.
# Run from the repository root with: python scripts/load_smoke.py

import math
import os
import socket
import sqlite3
import subprocess
import sys

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, perf_counter, sleep
from uuid import uuid4

import httpx


HOST = "127.0.0.1"
MACHINE_COUNT = 36
WASHER_COUNT = 20
REPORT_ROUNDS = 5
WORKER_COUNT = 36
STARTUP_TIMEOUT_SECONDS = 10.0
REQUEST_TIMEOUT_SECONDS = 10.0


# --------- Backend Process Helpers ---------

# Reserve an unused local TCP port for the temporary backend process.
def find_available_port() -> int:
    with socket.socket() as server_socket:
        server_socket.bind((HOST, 0))
        return int(server_socket.getsockname()[1])


# Wait until the temporary backend passes its health check.
def wait_for_backend(client: httpx.Client, server_process: subprocess.Popen[str]) -> None:
    deadline = monotonic() + STARTUP_TIMEOUT_SECONDS
    while monotonic() < deadline:
        if server_process.poll() is not None:
            server_output = server_process.stdout.read() if server_process.stdout is not None else ""
            raise RuntimeError(f"Backend stopped during startup.\n{server_output}")

        try:
            response = client.get("/api/v1/health")
            if response.status_code == 200:
                return
        except httpx.RequestError:
            pass

        sleep(0.1)

    raise RuntimeError("Backend did not become ready before the startup timeout")


# --------- Test Payloads ---------

# Build the complete washer and dryer inventory used by the load test.
def build_inventory() -> list[tuple[str, str]]:
    machines = [(f"washer-{number:02d}", "washer") for number in range(1, WASHER_COUNT + 1)]
    machines.extend(
        (f"dryer-{number:02d}", "dryer")
        for number in range(1, MACHINE_COUNT - WASHER_COUNT + 1)
    )
    return machines


# Build one periodic report payload for the selected machine type.
def build_periodic_report(machine_id: str, machine_type: str, round_number: int, recorded_at: datetime) -> dict[str, object]:
    report: dict[str, object] = {
        "machine_id": machine_id,
        "machine_type": machine_type,
        "report_id": f"load-{round_number:02d}-{machine_id}",
        "recorded_at": recorded_at.isoformat(),
        "operation_state": "idle",
        "cycle_stage": None,
        "general_sensor_readings": {"vibration": 0.1, "door_locked": False},
    }

    if machine_type == "washer":
        report["special_sensor_readings"] = {
            "water_level": 0.0,
            "water_temperature": 20.0,
        }
    else:
        report["special_sensor_readings"] = {
            "air_temperature": 25.0,
            "air_flow_speed": 0.0,
            "moisture": 70.0,
        }

    return report


# --------- Request Execution ---------

# Send one periodic report and return its request latency.
def send_periodic_report(client: httpx.Client, payload: dict[str, object]) -> float:
    started_at = perf_counter()
    response = client.post("/api/v1/reports/periodic", json=payload)
    elapsed_seconds = perf_counter() - started_at

    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text}")
    if response.json()["is_duplicate"]:
        raise RuntimeError(f"Unexpected duplicate report: {payload['report_id']}")

    return elapsed_seconds


# --------- Database Audit ---------

# Audit the temporary SQLite database for integrity and unexpected records.
def inspect_database(database_path: Path) -> tuple[dict[str, int | str], list[str]]:
    with closing(sqlite3.connect(database_path)) as database_connection:
        integrity_result = database_connection.execute("PRAGMA integrity_check").fetchone()
        integrity_status = str(integrity_result[0]) if integrity_result is not None else "missing"
        foreign_key_violations = len(database_connection.execute("PRAGMA foreign_key_check").fetchall())
        table_counts = {
            table_name: database_connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            for table_name in (
                "machines",
                "sensor_readings",
                "machine_state_events",
                "fault_events",
                "data_events",
            )
        }
        washer_count = database_connection.execute(
            "SELECT COUNT(*) FROM machines WHERE machine_type = 'washer'"
        ).fetchone()[0]
        dryer_count = database_connection.execute(
            "SELECT COUNT(*) FROM machines WHERE machine_type = 'dryer'"
        ).fetchone()[0]
        duplicate_report_groups = database_connection.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT machine_id, report_id
                FROM sensor_readings
                GROUP BY machine_id, report_id
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        machines_with_wrong_reading_count = database_connection.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT machines.machine_id
                FROM machines
                LEFT JOIN sensor_readings ON sensor_readings.machine_id = machines.machine_id
                GROUP BY machines.machine_id
                HAVING COUNT(sensor_readings.reading_id) != ?
            )
            """,
            (REPORT_ROUNDS,),
        ).fetchone()[0]
        stale_machine_snapshots = database_connection.execute(
            """
            SELECT COUNT(*)
            FROM machines
            JOIN (
                SELECT machine_id, MAX(recorded_at) AS latest_recorded_at
                FROM sensor_readings
                GROUP BY machine_id
            ) AS latest_readings ON latest_readings.machine_id = machines.machine_id
            WHERE machines.recorded_at != latest_readings.latest_recorded_at
            """
        ).fetchone()[0]
        future_dated_readings = database_connection.execute(
            """
            SELECT COUNT(*)
            FROM sensor_readings
            WHERE julianday(recorded_at) > julianday(received_at) + (2.0 / 86400.0)
            """
        ).fetchone()[0]

    audit = {
        "integrity": integrity_status,
        "foreign_key_violations": foreign_key_violations,
        "machines": table_counts["machines"],
        "washers": washer_count,
        "dryers": dryer_count,
        "sensor_readings": table_counts["sensor_readings"],
        "machine_state_events": table_counts["machine_state_events"],
        "fault_events": table_counts["fault_events"],
        "data_events": table_counts["data_events"],
        "duplicate_report_groups": duplicate_report_groups,
        "machines_with_wrong_reading_count": machines_with_wrong_reading_count,
        "stale_machine_snapshots": stale_machine_snapshots,
        "future_dated_readings": future_dated_readings,
    }
    suspicious_findings = []

    expected_reading_count = MACHINE_COUNT * REPORT_ROUNDS
    expected_values = {
        "integrity": "ok",
        "foreign_key_violations": 0,
        "machines": MACHINE_COUNT,
        "washers": WASHER_COUNT,
        "dryers": MACHINE_COUNT - WASHER_COUNT,
        "sensor_readings": expected_reading_count,
        "machine_state_events": 0,
        "fault_events": 0,
        "data_events": 0,
        "duplicate_report_groups": 0,
        "machines_with_wrong_reading_count": 0,
        "stale_machine_snapshots": 0,
        "future_dated_readings": 0,
    }
    for field_name, expected_value in expected_values.items():
        if audit[field_name] != expected_value:
            suspicious_findings.append(
                f"{field_name} was {audit[field_name]!r}; expected {expected_value!r}"
            )

    return audit, suspicious_findings


# --------- Load Scenario ---------

# Run the concurrent registration and periodic-report load scenario.
def run_load_smoke_test(client: httpx.Client) -> tuple[int, float, float, float]:
    inventory = build_inventory()
    registered_at = datetime.now(UTC)

    for machine_id, machine_type in inventory:
        response = client.post(
            "/api/v1/machines/register",
            json={
                "machine_id": machine_id,
                "machine_type": machine_type,
                "registered_at": registered_at.isoformat(),
            },
        )
        if response.status_code != 201:
            raise RuntimeError(f"Failed to register {machine_id}: HTTP {response.status_code} {response.text}")

    request_latencies: list[float] = []
    test_started_at = perf_counter()

    with ThreadPoolExecutor(max_workers=WORKER_COUNT) as executor:
        for round_number in range(1, REPORT_ROUNDS + 1):
            recorded_at = datetime.now(UTC)
            futures = [
                executor.submit(
                    send_periodic_report,
                    client,
                    build_periodic_report(machine_id, machine_type, round_number, recorded_at),
                )
                for machine_id, machine_type in inventory
            ]
            for future in as_completed(futures):
                request_latencies.append(future.result())

    elapsed_seconds = perf_counter() - test_started_at

    machine_response = client.get("/api/v1/machines")
    if machine_response.status_code != 200 or len(machine_response.json()) != MACHINE_COUNT:
        raise RuntimeError("Machine inventory did not contain all registered machines")

    for machine_id, _ in inventory:
        reading_response = client.get(f"/api/v1/machines/{machine_id}/readings?limit=100")
        if reading_response.status_code != 200 or len(reading_response.json()) != REPORT_ROUNDS:
            raise RuntimeError(f"Persisted reading count was incorrect for {machine_id}")

    sorted_latencies = sorted(request_latencies)
    percentile_index = math.ceil(len(sorted_latencies) * 0.95) - 1
    p95_seconds = sorted_latencies[percentile_index]
    throughput = len(request_latencies) / elapsed_seconds
    return len(request_latencies), elapsed_seconds, throughput, p95_seconds


# --------- Application Entry Point ---------

# Start the temporary backend, run the smoke test, and clean up its database.
def main() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    port = find_available_port()
    database_path = repository_root / "tests" / "artifacts" / f"load-smoke-{uuid4()}.sqlite"
    process_environment = os.environ.copy()
    process_environment["FFC_DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    server_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            HOST,
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--no-access-log",
        ],
        cwd=repository_root,
        env=process_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creation_flags,
    )

    failure: Exception | None = None
    try:
        with httpx.Client(
            base_url=f"http://{HOST}:{port}",
            timeout=REQUEST_TIMEOUT_SECONDS,
            trust_env=False,
        ) as client:
            wait_for_backend(client, server_process)
            report_count, elapsed_seconds, throughput, p95_seconds = run_load_smoke_test(client)
    except Exception as error:
        failure = error
    finally:
        if server_process.poll() is None:
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
                server_process.wait(timeout=5)

    server_output = server_process.stdout.read() if server_process.stdout is not None else ""
    database_audit: dict[str, int | str] = {}
    suspicious_findings: list[str] = []
    if database_path.exists():
        database_audit, suspicious_findings = inspect_database(database_path)
        print("Database audit before cleanup")
        for field_name, value in database_audit.items():
            print(f"{field_name}: {value}")
        print(f"suspicious_findings: {len(suspicious_findings)}")
        for finding in suspicious_findings:
            print(f"- {finding}")

    if failure is None and suspicious_findings:
        failure = RuntimeError("Database audit found suspicious data")

    cleanup_failures = []
    for temporary_file in (
        database_path,
        Path(f"{database_path}-journal"),
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ):
        for _ in range(50):
            try:
                temporary_file.unlink(missing_ok=True)
                break
            except PermissionError:
                sleep(0.1)
        if temporary_file.exists():
            cleanup_failures.append(str(temporary_file))

    if failure is None and cleanup_failures:
        failure = RuntimeError(
            f"Temporary database files could not be removed: {cleanup_failures}"
        )

    if failure is not None:
        raise RuntimeError(f"{failure}\nBackend output:\n{server_output}") from failure

    print("Load smoke test passed")
    print(f"Machines: {MACHINE_COUNT}")
    print(f"Reports: {report_count}")
    print(f"Elapsed: {elapsed_seconds:.2f} seconds")
    print(f"Throughput: {throughput:.1f} reports/second")
    print(f"P95 request latency: {p95_seconds * 1_000:.1f} milliseconds")


if __name__ == "__main__":
    main()
