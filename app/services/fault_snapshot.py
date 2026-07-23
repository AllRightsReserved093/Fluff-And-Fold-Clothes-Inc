# Save a fault and its preceding machine history as a readable JSON file.
# 将故障及其发生前的机器历史保存为便于查看的 JSON 文件。

from pathlib import Path

from laundry_contracts.contracts import FaultContextResponse


DEFAULT_FAULT_SNAPSHOT_DIRECTORY = Path("fault_snapshots")
FAULT_SNAPSHOT_WINDOW_MINUTES = 5


# Write one fault snapshot using the database fault ID as a path-safe filename.
# 使用数据库故障编号作为安全文件名，写入一份故障快照。
def save_fault_snapshot(fault_context: FaultContextResponse, snapshot_directory: Path) -> Path:
    snapshot_directory.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_directory / f"fault-{fault_context.fault.fault_event_id}.json"
    snapshot_path.write_text(fault_context.model_dump_json(indent=2), encoding="utf-8")
    return snapshot_path
