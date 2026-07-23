# Diagnostic Code Definitions

本文档定义设备和后端共同使用的诊断代码。代码需要能够直接显示在设备面板上，同时必须区分设备警告、设备故障、服务器状态和数据审计事件。

## Identifiers

- `code`：设备或控制台显示的固定诊断代码，例如 `F3102`。
- `key`：代码对应的稳定语义名称，例如 `dryer_overtemperature_trip`。
- `error_id`：一次设备警告、设备故障或系统状态实例的唯一标识。
- `record_id`：数据库记录编号；当前故障表使用 `fault_event_id`，未来数据事件表应使用独立的 `data_event_id`。
- `detection_authority`：有权确认该异常的主体，当前使用 `device` 或 `server`。
- `source_component`：实际产生记录的组件，例如 `analytics` 或 `heartbeat_monitor`。

同一个 `code` 可以在不同机器或不同时间发生多次，每次实例或审计事件都拥有独立的记录标识。

## Code Format

代码格式为：

```text
PCNNN
```

- `P`：记录类型前缀。
- `C`：一位设备或系统分类。
- `NNN`：分类内的三位顺序号。
- 完整代码必须匹配 `^[WFSD][0-9]{4}$`。

类型前缀：

| Prefix | Kind | Meaning |
|---|---|---|
| `W` | `warning` | 设备仍可运行，但存在需要关注的异常条件 |
| `F` | `fault` | 设备功能异常，可能需要停止、维修或复位 |
| `S` | `system_condition` | 通信、服务器或监控状态异常 |
| `D` | `data_event` | 数据缺失、不一致或顺序异常，只进入审计历史 |

设备或系统分类：

| Category | Meaning |
|---|---|
| `1` | 洗衣机和烘干机共用 |
| `2` | 洗衣机专用 |
| `3` | 烘干机专用 |
| `8` | 通信和服务器监控 |
| `9` | 数据链路和状态一致性 |

`trip` 不是独立的代码类型，而是设备执行的保护动作。故障通过 `equipment_action`、`latched` 和 `reset_required` 描述是否停机、锁存和需要复位。

代码一旦投入使用，不得改变原有含义，也不得重新分配。严重程度、机器编号、时间和随机值不能编码在代码中。

## Definition Fields

每个正式代码定义至少应包含：

```text
code
kind
severity
detection_authority
source_component
applicable_machine_type
applicable_states
activation_rule
activation_delay
clear_rule
clear_delay
equipment_action
latched
ack_required
reset_required
operator_action
probable_causes
rule_version
```

规则定义与异常实例必须分开。定义保存稳定规则和操作说明；实例只保存实际机器、时间、读数和生命周期状态。

## Code Catalog

| Code | Kind | Severity | Authority | Equipment action | Latched |
|---|---|---|---|---|---|
| `W1001` | `warning` | medium | `server` | `none` | no |
| `F1101` | `fault` | critical | `device` | `controlled_stop` | yes |
| `W2101` | `warning` | medium | `server` | `none` | no |
| `W3101` | `warning` | high | `server` | `none` | no |
| `W3201` | `warning` | medium | `server` | `none` | no |
| `F3102` | `fault` | critical | `device` | `heating_off_and_stop` | yes |
| `S8001` | `system_condition` | high | `server` | `none` | no |
| `D9001` | `data_event` | low | `server` | `none` | no |
| `D9002` | `data_event` | medium | `server` | `none` | no |

## Rule Definitions

### `W1001 excessive_vibration`

- 仅在适用的运行阶段评价。
- 使用时间窗口、触发延迟和迟滞，不能根据单个越限读数立即反复触发和解除。
- 条件稳定恢复后由服务器自动清除。

### `F1101 door_interlock_lost`

- 由设备本地控制器检测。
- 运行期间失去门联锁时，设备立即关闭驱动输出并执行受控停止。
- 故障保持锁存；安全条件恢复后仍需要人工复位。
- 服务器只负责记录并检查设备是否正确报告和执行保护，不能承担第一道安全保护。

### `W2101 washer_water_temperature_high`

- 阈值由洗衣机型号和洗涤程序决定。
- 使用触发延迟、解除延迟和迟滞。
- 条件稳定恢复后由服务器自动清除。

### `W3101 dryer_air_temperature_high`

- 表示确认检测到烘干温度偏高，不代表已经确认具体机械原因。
- 使用警告阈值、触发延迟、较低的解除阈值和解除延迟。
- 条件稳定恢复后由服务器自动清除。

### `W3201 dryer_air_flow_low`

- 只在风机或加热命令有效且启动延时结束后评价。
- 使用触发延迟、解除延迟和迟滞。
- 条件稳定恢复后由服务器自动清除。

### `F3102 dryer_overtemperature_trip`

- 由设备本地控制器使用高频采样和保护阈值检测。
- 触发后关闭加热并停止当前循环。
- 温度和气流恢复只表示异常条件已经消失，故障仍保持锁存。
- 完成检查和人工复位后，设备才允许重新运行。
- 可能原因包括气流受限、风机故障、温度传感器错误和加热控制故障。
- 模拟器中的 `blocked-vent` 是测试注入原因，不作为设备已经确认的故障事实。

### `S8001 device_communication_lost`

- 服务器超过允许的报告间隔后建立该系统状态。
- 收到后续有效报告后自动恢复。
- 不把设备运行状态强制改成 `faulted`，因为服务器无法确认设备当前的物理状态。
- 在操作员界面中与设备警告和设备故障分开显示。

### `D9001 state_report_gap_detected`

- 周期报告状态与数据库快照不一致时追加一条不可修改的数据事件。
- 保存数据库旧状态、设备新状态和数据质量说明，然后同步当前快照。
- 该事件没有 `active` 或 `resolved` 生命周期。

### `D9002 state_sequence_mismatch`

- 状态变化报告中的先前状态与数据库快照不一致时追加审计事件。
- 保存期望状态、报告状态和 `data_quality=uncertain`。
- 原始事件永久保留；后续只能关闭调查事项，不能删除或“解除”历史事件。

## Lifecycle

设备警告、设备故障和系统状态分别记录：

```text
active
acknowledged
condition_cleared
reset
```

- `active=false`：当前触发条件已经消失。
- `acknowledged=true`：操作员已经看到该异常。
- `condition_cleared=true`：传感器或通信条件已经恢复。
- `reset=true`：锁存故障已经完成检查并明确复位。

对于非锁存警告，条件稳定恢复后可以自动结束。对于锁存故障，即使 `condition_cleared=true`，在 `reset=true` 前设备仍不能重新投入运行。

`data_event` 是不可修改的历史事实，不使用上述活动、确认、解除或复位生命周期。

## Device and Server Responsibilities

设备本地控制器负责：

- 高频采样和滤波；
- 安全联锁；
- 警告与故障阈值；
- 关闭加热、受控停止或跳闸；
- 锁存和复位条件。

服务器负责：

- 接收并保存设备报告；
- 显示当前警告、故障和系统状态；
- 根据低频周期报告执行补充分析；
- 检查设备是否漏报应有的保护动作；
- 保存数据质量和状态一致性审计事件。

服务器不能依赖15秒周期报告执行需要在数秒内完成的安全保护。

## Operator Display

操作员界面应分区显示：

```text
DEVICE WARNINGS
DEVICE FAULTS
SYSTEM CONDITIONS
DATA EVENTS / AUDIT LOG
```

设备面板可以只显示短代码：

```text
F3102
```

操作员控制台应同时显示代码、说明、状态和建议操作：

```text
F3102  Dryer overtemperature trip  RESET REQUIRED
```

## Implementation Status

`laundry_contracts/fault_codes.py` 已经提供可导入的诊断代码枚举和核心定义目录。传感器分析器已经使用 `W1001`、`W2101`、`W3101` 和 `W3201`，模拟器过温保护已经使用 `F3102`，心跳监控已经使用 `S8001`。`D9001` 和 `D9002` 已经单独写入不可变的 `data_events`，并可通过只读查询 API 和控制台诊断视图获取。控制台也可以按故障编号查看故障发生前5分钟的传感器、状态和数据事件历史；首次接收设备 `ErrorReport` 时，同一时间窗口还会写入 `fault_snapshots/` 下的 JSON 文件。已有数据库中的旧代码记录仍按 `legacy` 显示。

## Prototype Limits

当前阈值和严重程度只用于项目模拟与功能验证，不是设备制造商规格。连接真实设备前，必须根据具体机型重新确认阈值、滤波时间、迟滞、设备动作、复位条件和操作建议。
