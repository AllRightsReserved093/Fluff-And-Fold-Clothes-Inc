# Run the console interface and one shared sequential simulation thread.

import argparse

from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic

import httpx

from simulator.dryer import Dryer
from simulator.machine import Machine, REPORT_INTERVAL_SECONDS
from simulator.washer import Washer


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api/v1"
HTTP_TIMEOUT_SECONDS = 1.0
SIMULATION_LOOP_SECONDS = 0.5
SIMULATION_SPEED = 1.0
REGISTRATION_INTERVAL_SECONDS = 0.5
WASHER_COUNT = 20
DRYER_COUNT = 16


Command = tuple[str, str | None, str | None]


# --------- Machine Inventory ---------

# Create the complete simulated washer and dryer inventory.
def create_machines(http_client: httpx.Client, api_base_url: str = DEFAULT_API_BASE_URL) -> dict[str, Machine]:
    machines: dict[str, Machine] = {}

    for number in range(1, WASHER_COUNT + 1):
        machine_id = f"washer-{number:02d}"
        machines[machine_id] = Washer(machine_id, http_client, api_base_url)

    for number in range(1, DRYER_COUNT + 1):
        machine_id = f"dryer-{number:02d}"
        machines[machine_id] = Dryer(machine_id, http_client, api_base_url)

    return machines


# --------- Console Commands ---------

# Print every command supported by the simulator console.
def print_help() -> None:
    print("Commands:")
    print("  list")
    print("  select <machine_id>")
    print("  status")
    print("  fault <fault_name>")
    print("  repair")
    print("  offline")
    print("  online")
    print("  help")
    print("  quit")


# Parse one console line into a simulator command.
def parse_console_command(command_text: str, selected_machine_id: str | None, machine_ids: set[str]) -> tuple[Command | None, str | None]:
    parts = command_text.strip().split()
    if not parts:
        return None, selected_machine_id

    action = parts[0].lower()
    if action == "help":
        print_help()
        return None, selected_machine_id
    if action == "select":
        if len(parts) != 2 or parts[1] not in machine_ids:
            print("Usage: select <machine_id>")
            return None, selected_machine_id
        print(f"Selected {parts[1]}")
        return None, parts[1]
    if action == "list":
        return ("list", None, None), selected_machine_id
    if action == "status":
        return ("status", selected_machine_id, None), selected_machine_id
    if action == "fault":
        if len(parts) != 2:
            print("Usage: fault <fault_name>")
            return None, selected_machine_id
        return ("fault", selected_machine_id, parts[1]), selected_machine_id
    if action == "repair":
        return ("repair", selected_machine_id, None), selected_machine_id
    if action == "offline":
        return ("offline", selected_machine_id, None), selected_machine_id
    if action == "online":
        return ("online", selected_machine_id, None), selected_machine_id
    if action == "quit":
        return ("quit", None, None), selected_machine_id

    print(f"Unknown command: {action}")
    return None, selected_machine_id


# Apply one queued console command to the selected simulated machine.
def handle_command(command: Command, machines: dict[str, Machine]) -> bool:
    action, machine_id, argument = command
    if action == "quit":
        return False

    if action == "list":
        for machine in machines.values():
            print(machine.status_line())
        return True

    if machine_id is None:
        print("Select a machine first")
        return True

    machine = machines.get(machine_id)
    if machine is None:
        print(f"Machine {machine_id} does not exist")
        return True

    if action == "status":
        print(machine.status_line())
    elif action == "fault" and argument is not None:
        machine.inject_fault(argument)
    elif action == "repair":
        machine.repair()
    elif action == "offline":
        machine.is_communication_enabled = False
        print(f"[{machine.machine_id}] Communication stopped")
    elif action == "online":
        machine.is_communication_enabled = True
        print(f"[{machine.machine_id}] Communication restored")
    else:
        print(f"Unknown command: {action}")
    return True


# --------- Simulation Loop ---------

# Own every machine state update and HTTP request in one worker thread.
def run_simulation(command_queue: Queue[Command], stopped_event: Event, machines: dict[str, Machine]) -> None:
    try:
        machines_to_register = list(machines.values())
        registration_start = monotonic()
        registration_index = 0
        previous_time = registration_start
        keep_running = True
        while keep_running:
            current_time = monotonic()
            elapsed_seconds = (current_time - previous_time) * SIMULATION_SPEED
            previous_time = current_time

            while registration_index < len(machines_to_register):
                registration_time = registration_start + registration_index * REGISTRATION_INTERVAL_SECONDS
                if current_time < registration_time:
                    break

                machine = machines_to_register[registration_index]
                if machine.register():
                    machine.next_report_at = registration_time + REPORT_INTERVAL_SECONDS
                registration_index += 1

            while True:
                try:
                    command = command_queue.get_nowait()
                except Empty:
                    break
                keep_running = handle_command(command, machines)
                if not keep_running:
                    break

            if not keep_running:
                break

            for machine in machines.values():
                if not machine.is_communication_enabled:
                    continue
                machine.tick(elapsed_seconds)
                if machine.is_registered and current_time >= machine.next_report_at:
                    machine.send_periodic_report()
                    machine.next_report_at = current_time + REPORT_INTERVAL_SECONDS

            stopped_event.wait(SIMULATION_LOOP_SECONDS)
    finally:
        for machine in machines.values():
            machine.deregister()
        stopped_event.set()
        print("Simulator stopped")


# --------- Application Entry Point ---------

# Start the simulator worker and interactive command loop.
def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Fluff & Fold machine simulator")
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    arguments = parser.parse_args()

    command_queue: Queue[Command] = Queue()
    stopped_event = Event()
    http_client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
    machines = create_machines(http_client, arguments.api_base_url)
    machine_ids = set(machines)

    simulation_thread = Thread(target=run_simulation, args=(command_queue, stopped_event, machines), daemon=False)
    simulation_thread.start()

    selected_machine_id = None
    print_help()
    try:
        while not stopped_event.is_set():
            prompt = f"[{selected_machine_id}]> " if selected_machine_id is not None else "> "
            command_text = input(prompt)
            command, selected_machine_id = parse_console_command(command_text, selected_machine_id, machine_ids)
            if command is None:
                continue
            command_queue.put(command)
            if command[0] == "quit":
                break
    except (EOFError, KeyboardInterrupt):
        command_queue.put(("quit", None, None))
    finally:
        simulation_thread.join()
        http_client.close()


if __name__ == "__main__":
    main()
