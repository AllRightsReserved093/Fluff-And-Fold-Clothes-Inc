# Save a fault and its preceding machine history as a readable JSON file.

from pathlib import Path

from laundry_contracts.contracts import FaultContextResponse


DEFAULT_FAULT_SNAPSHOT_DIRECTORY = Path("fault_snapshots")
FAULT_SNAPSHOT_WINDOW_MINUTES = 5


# Write one fault snapshot using the database fault ID as a path-safe filename.
def save_fault_snapshot(fault_context: FaultContextResponse, snapshot_directory: Path) -> Path:
    snapshot_directory.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_directory / f"fault-{fault_context.fault.fault_event_id}.json"
    snapshot_path.write_text(fault_context.model_dump_json(indent=2), encoding="utf-8")
    return snapshot_path
