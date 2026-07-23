# Fluff and Fold Clothes Inc

一个面向洗衣店本地办公室电脑的设备监控后端原型。系统使用 FastAPI 接收洗衣机和烘干机报告，使用 SQLite 保存当前状态与历史数据，并通过心跳监控和传感器规则发现、确认和解除设备故障。

原始任务说明见 [project_prompt.md](project_prompt.md)。原始任务不要求图形界面；当前项目提供完整 REST API、Swagger 文档、设备模拟器控制台和自动刷新的操作员终端前端。

## 当前功能

- 注册、重新启用和注销洗衣机与烘干机
- 接收周期报告、状态变化报告、设备故障报告和故障解除报告
- 使用 Pydantic 校验机型分支、传感器结构、枚举、数值范围和带时区时间
- 使用 `report_id` 识别重复报告，重复请求返回成功但不重复产生副作用
- 使用 SQLite 保存机器快照、传感器读数、状态事件和故障生命周期
- 设备超过16秒没有报告时标记离线并记录心跳故障
- 设备重新发送有效报告后恢复在线并解除心跳故障
- 根据周期报告和故障解除报告分析或解除传感器故障
- 查询机器当前状态、内存中的最新读数、历史读数和故障事件
- 支持操作员确认故障和手动解除故障
- 首次接收设备故障报告时自动保存故障前5分钟的 JSON 历史快照
- 使用命令式 ASCII 操作员前端自动刷新机器状态、最新读数和活动故障
- 使用一个后台模拟线程顺序模拟20台洗衣机和16台烘干机
- 支持烘干机出风口堵塞、保护停机和维修恢复流程
- FastAPI 关闭时主动停止并等待心跳监控线程

## 系统结构

```text
洗衣机、烘干机或模拟器
        │ HTTP POST
        ▼
FastAPI Routes
        │ Pydantic结构校验
        ▼
MachineService
   ├── Machine                  内存中的当前运行状态
   ├── MachineMonitor           心跳截止时间与离线通知
   ├── sensor_fault_analyzer    传感器规则判断
   └── DatabaseOperation        SQLAlchemy数据库操作
                │
                ▼
              SQLite
                ▲
                │ HTTP GET / POST
      Textual操作员前端或Swagger
```

设备报告的处理顺序为：

```text
JSON请求
→ Pydantic结构校验
→ Service检查注册状态
→ SQLite事务写入
→ 更新内存状态和心跳截止时间
→ 返回接收结果
```

`MachineService` 持有业务流程和互斥锁；`MachineMonitor` 只负责心跳调度；`sensor_fault_analyzer` 只负责纯规则判断；`DatabaseOperation` 只负责持久化和查询。

## 项目结构

```text
app/
├── api/
│   ├── routes/
│   │   ├── health.py           # 健康检查
│   │   ├── register.py         # 注册与注销
│   │   ├── reports.py          # 四类设备报告
│   │   ├── machines.py         # 当前机器状态查询
│   │   ├── readings.py         # 历史读数查询
│   │   ├── data_events.py      # 数据事件查询
│   │   └── faults.py           # 故障查询、确认与手动解除
│   └── router.py               # 集中注册API路由
├── core/
│   └── config.py               # 环境变量与应用配置
├── database/
│   ├── base.py                 # SQLAlchemy声明基类
│   ├── models.py               # SQLite表模型
│   ├── operation.py            # 数据库读写与查询
│   └── session.py              # Engine、SessionFactory与建表入口
├── machines/
│   ├── machines.py             # 内存机器状态
│   └── machine_monitor.py      # 心跳监控线程
├── services/
│   ├── machine_service.py      # 业务流程协调
│   ├── fault_snapshot.py       # 故障历史快照文件
│   └── sensor_fault_analyzer.py # 传感器故障规则
└── main.py                     # FastAPI入口与应用生命周期
laundry_contracts/
└── contracts.py                # 请求、响应、枚举和校验模型
simulator/
├── main.py                     # 模拟循环与控制台
├── machine.py                  # 设备公共行为
├── washer.py                   # 洗衣机工作流程
├── dryer.py                    # 烘干机工作流程
└── faults.py                   # 模拟故障行为
operator_console/
├── main.py                     # 命令输入、自动刷新与应用生命周期
├── api_client.py               # 异步前端API客户端
└── views.py                    # ASCII表格与视图文本生成
tests/                          # Contracts、API、数据库、服务、心跳和模拟器测试
```

## 数据契约

所有设备报告都包含以下公共字段：

| 字段 | 说明 |
|---|---|
| `machine_id` | 设备标识 |
| `machine_type` | `washer` 或 `dryer` |
| `report_id` | 当前报告的幂等标识 |
| `recorded_at` | 设备记录事件的带时区时间，进入系统后归一化为 UTC |

`machine_type` 是 Pydantic 判别字段。洗衣机报告必须携带洗衣机读数，烘干机报告必须携带烘干机读数。

### 传感器读数

| 类型 | 字段 |
|---|---|
| 公共读数 | `vibration`、`door_locked` |
| 洗衣机读数 | `water_level`、`water_temperature` |
| 烘干机读数 | `air_temperature`、`air_flow_speed`、`moisture` |

### 报告类型

| 报告 | 内容 | 后端处理 |
|---|---|---|
| `PeriodicReport` | 当前状态、阶段和完整读数 | 保存读数、更新当前快照、分析传感器故障 |
| `ChangeOfStateReport` | 前后状态、前后阶段和原因 | 保存状态历史并更新当前快照 |
| `ErrorReport` | 故障信息、故障时读数和可选状态变化 | 保存读数与故障，必要时同时保存状态变化 |
| `ErrorResolutionReport` | `error_id`、恢复说明、当前状态和恢复后读数 | 保存恢复读数、解除设备故障并重新分析传感器故障 |

## 重复报告

四类设备报告都使用 `machine_id + report_id` 检查当前报告类型是否已经处理。

| 结果 | API行为 |
|---|---|
| 首次收到 | 返回 HTTP `200`，`is_duplicate=false` |
| 相同报告再次到达 | 返回 HTTP `200`，`is_duplicate=true` |
| 机器或目标故障不存在 | 返回 HTTP `404` |

重复报告不会再次写入数据库、修改内存状态、处理故障或刷新心跳截止时间。

示例响应：

```json
{
  "machine_id": "washer-01",
  "report_id": "periodic-001",
  "accepted_at": "2026-07-22T20:00:00Z",
  "is_duplicate": true
}
```

## 数据库

默认数据库地址：

```text
sqlite:///./laundry.db
```

SQLite 是嵌入式数据库，不需要单独启动服务。FastAPI 启动时会创建尚不存在的表。

| 表 | 用途 |
|---|---|
| `machines` | 每台机器的持久化当前快照与注册状态 |
| `sensor_readings` | 周期、设备故障和故障解除报告中的历史读数 |
| `machine_state_events` | 状态变化历史和缺失状态报告时的协调记录 |
| `data_events` | 数据缺失和状态顺序不一致等不可变审计事件 |
| `fault_events` | 设备、心跳监控和后端分析产生的活动与历史故障 |

数据库同时保存：

- `recorded_at`：设备记录事件的时间
- `received_at`：数据库收到历史记录的时间
- `last_online`：服务端最后观察到有效联系的时间

运行中的 `Machine` 还直接保存最后一份已接受报告的 `recorded_at`，以及最后一份包含传感器数据的 `latest_reading`。机器查询 API 和操作员总览直接返回这份内存读数，不会为了每次界面刷新再查询传感器历史表。状态变化报告只更新最后报告时间，不会覆盖已有的最新传感器读数。

注销设备不会删除历史数据。机器当前快照会标记为未注册，已有读数、状态和故障记录继续保留。

`Base.metadata.create_all()` 只能创建缺失的表，不能升级已有表结构。修改数据库模型后，目前需要重建开发数据库或以后加入迁移工具。

## 心跳监控

- 模拟器正常每15秒发送一次周期报告
- 后端使用16秒超时时间，提供1秒宽限
- `MachineMonitor` 使用基于单调毫秒时间的最小堆等待下一个截止时间
- 新报告会更新对应设备的截止时间
- 超时后设备被标记为离线，并写入 `S8001` 通信状态事件
- 心跳超时不会强制把设备运行状态改成 `FAULTED`
- 后续有效报告会恢复设备在线状态并解除活动的心跳故障
- 重复报告不会刷新心跳
- FastAPI 关闭时通过 `MachineService.shutdown()` 停止并 `join()` 心跳线程

Monitor 在堆为空时仍保持等待，因此注册列表暂时为空不会导致监控线程自行退出。

## 故障管理

故障来源包括：

| 来源 | 说明 |
|---|---|
| `device` | 设备主动报告的故障 |
| `heartbeat_monitor` | 后端检测到的报告超时 |
| `analytics` | 后端根据状态或传感器读数判断的故障 |

故障的确认和解除是两个不同操作：

- 确认 `acknowledge`：表示操作员已经看到故障，不代表问题已经解决
- 解除 `resolve`：设置解除时间和说明，但保留完整历史记录

设备可以通过 `ErrorResolutionReport` 主动解除故障；操作员也可以通过故障管理 API 手动解除。

### 故障历史快照

后端首次接受设备 `ErrorReport` 后，会立即把当时已经保存的故障前5分钟历史写入：

```text
fault_snapshots/fault-<fault_event_id>.json
```

文件包含故障记录、传感器读数、状态事件和数据事件，使用 UTF-8 JSON，可以直接用文本编辑器查看。文件名只使用数据库生成的数字故障编号；重复错误报告不会重复生成快照。`fault_snapshots/` 是运行时数据目录，不提交到 Git。

当前自动文件快照只由设备 `ErrorReport` 触发。服务器分析警告、心跳异常和数据事件仍保存在 SQLite 中，并可以通过诊断接口查询。

### 自动传感器规则

周期报告和故障解除报告会调用 `sensor_fault_analyzer.py`。当前原型规则如下：

| 故障代码 | 触发条件 |
|---|---|
| `W1001` | 振动大于 `10.0 m/s²` |
| `W2101` | 洗衣机水温大于 `80°C` |
| `W3101` | 烘干机气温大于 `90°C` |
| `W3201` | 烘干机运行时气流低于 `0.5 m/s` |

同一种分析故障持续存在时不会每15秒重复创建记录。读数恢复正常后，活动故障自动解除，但历史记录继续保留。

运行期间门锁丢失属于设备本地保护，不由服务器传感器分析器生成故障。模拟器注入出风口堵塞后达到保护温度时，由模拟设备发送 `F3102` 过温保护停机报告。

这些阈值只用于原型演示，正式使用前必须替换为设备制造商提供的实际范围。

## API

所有业务路由默认使用 `/api/v1` 前缀。

### 系统状态

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/v1/health` | 健康检查 |

### 机器管理与查询

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/v1/machines/register` | 注册新机器或重新启用历史机器 |
| `POST` | `/api/v1/machines/deregister` | 注销机器但保留历史 |
| `GET` | `/api/v1/machines` | 查询全部机器状态 |
| `GET` | `/api/v1/machines/{machine_id}` | 查询一台机器状态 |

### 设备报告

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/v1/reports/periodic` | 接收周期状态与传感器报告 |
| `POST` | `/api/v1/reports/change-of-state` | 接收状态变化报告 |
| `POST` | `/api/v1/reports/error` | 接收设备故障与故障时读数 |
| `POST` | `/api/v1/reports/error-resolution` | 接收故障解除与恢复后读数 |

### 读数、数据事件与故障

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/v1/machines/{machine_id}/readings` | 查询机器历史读数 |
| `GET` | `/api/v1/data-events` | 查询不可变的数据一致性事件 |
| `GET` | `/api/v1/faults` | 查询全部机器故障 |
| `GET` | `/api/v1/faults/{fault_event_id}/context` | 查询故障及其发生前的设备历史 |
| `GET` | `/api/v1/machines/{machine_id}/faults` | 查询一台机器的故障 |
| `POST` | `/api/v1/machines/{machine_id}/faults/{error_id}/acknowledge` | 确认故障但不解除 |
| `POST` | `/api/v1/machines/{machine_id}/faults/{error_id}/resolve` | 手动解除故障 |

完整请求和响应结构可以在服务启动后通过 Swagger UI 查看：

<http://127.0.0.1:8000/docs>

## 查询示例

查询当前机器状态：

```text
GET /api/v1/machines
GET /api/v1/machines/washer-01
```

查询一台机器最近20条运行状态读数：

```text
GET /api/v1/machines/washer-01/readings?operation_state=running&limit=20
```

读数接口支持：

- `start_time`
- `end_time`
- `operation_state`
- `limit`，范围为1到1000，默认100

查询一台机器最近20条状态报告缺失事件：

```text
GET /api/v1/data-events?machine_id=washer-01&event_code=D9001&limit=20
```

数据事件接口支持 `machine_id`、`event_code` 和 `limit`。

查询所有尚未解除且尚未确认的故障：

```text
GET /api/v1/faults?active=true&acknowledged=false
```

故障接口支持：

- `active`
- `acknowledged`
- `limit`，范围为1到1000，默认100

查询故障编号1及其发生前5分钟的持久化历史：

```text
GET /api/v1/faults/1/context?minutes=5
```

该接口返回故障记录，以及时间窗口内的传感器读数、状态事件和数据事件。`minutes` 范围为1到60，默认5。

## 本地运行

创建环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

启动 FastAPI：

```powershell
python -m uvicorn app.main:app --reload
```

启动后可访问：

- Swagger API 文档：<http://127.0.0.1:8000/docs>
- OpenAPI JSON：<http://127.0.0.1:8000/openapi.json>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>

保持后端运行，在第二个终端启动模拟器：

```powershell
.\.venv\Scripts\Activate.ps1
python -m simulator.main
```

在另一个终端启动操作员前端：

```powershell
.\.venv\Scripts\Activate.ps1
python -m operator_console.main
```

## 模拟器

模拟器会创建20台洗衣机和16台烘干机，以0.5秒间隔错峰注册。一个后台线程顺序推进全部设备，每台设备每15秒发送周期报告；主线程只处理控制台输入，并通过 `Queue` 把命令交给模拟线程。

正常工作阶段：

```text
Washer: FILLING → WASHING → DRAINING → SPINNING → COMPLETE → IDLE
Dryer:  HEATING → DRYING → COOLING → COMPLETE → IDLE
```

控制台命令：

```text
list
select <machine_id>
status
fault blocked-vent
repair
help
quit
```

`blocked-vent` 目前只支持运行在 `HEATING` 或 `DRYING` 阶段的烘干机。注入后：

```text
冻结当前阶段
→ 周期报告继续发送
→ 气流逐渐下降、温度逐渐升高
→ 达到保护阈值
→ 发送ErrorReport并进入FAULTED
```

执行 `repair` 后：

```text
传感器逐步恢复
→ 发送包含恢复读数的ErrorResolutionReport
→ 清除活动故障
→ 发送FAULTED到IDLE状态报告
```

Washer 暂时没有可注入故障。对 Washer 执行 `fault` 或 `repair` 只会返回不支持提示，不会终止模拟线程。

执行 `quit` 会停止模拟循环，并逐台注销已经注册的设备。HTTP 请求失败时只打印错误，当前不进行复杂重试、离线缓存或补发。

## 操作员控制台

操作员控制台默认连接 `http://127.0.0.1:8000/api/v1`，每2秒刷新当前视图。前端只通过 FastAPI 操作数据，不直接访问 `MachineService` 或 SQLite。界面使用一个自动刷新的 ASCII 信息区和一个文本命令输入框，不需要方向键选择表格。

控制台命令：

| 命令 | 操作 |
|---|---|
| `help` | 显示命令说明 |
| `refresh` | 立即刷新 |
| `diagnostics` | 查看所有机器的活动故障、已解除故障和数据事件 |
| `diagnostics machine <machine_id>` | 查看指定机器的诊断信息 |
| `diagnostics fault <fault_id>` | 查看一条故障及其发生前5分钟的历史 |
| `dashboard` | 返回机器总览 |
| `ack <fault_id>` | 按控制台显示的故障编号确认一条活动故障 |
| `resolve <fault_id> [message]` | 按控制台显示的故障编号手动解除一条故障 |
| `quit` | 退出前端 |

诊断视图会显示正式故障码的类型和严重程度。旧版故障码显示为 `legacy`，不会阻止其他记录正常显示。

使用其他后端地址时：

```powershell
python -m operator_console.main --api-base-url http://127.0.0.1:8000/api/v1
```

## 配置

项目不要求 `.env` 才能启动。默认配置已经能够运行：

```dotenv
FFC_APP_NAME=Fluff and Fold Clothes Inc API
FFC_APP_VERSION=0.1.0
FFC_API_V1_PREFIX=/api/v1
FFC_DEBUG=false
FFC_DATABASE_URL=sqlite:///./laundry.db
```

需要覆盖默认值时，可以在项目根目录创建 `.env`。所有环境变量使用 `FFC_` 前缀。

## 测试

所有测试都使用内存 SQLite 或模拟 HTTP 传输，不会修改项目的 `laundry.db`。

运行完整测试集：

```powershell
python -m pytest -q -p no:cacheprovider
```

当前验证结果：

```text
61 passed
```

测试覆盖：

- Pydantic Contracts 和机型判别
- FastAPI 路由和查询参数
- SQLite 表结构与完整业务生命周期
- MachineService 与 Monitor 协作
- 单调毫秒时间和心跳截止时间
- 传感器故障产生、去重和自动解除
- 设备故障确认与解除
- 重复报告幂等响应
- 模拟器正常流程、故障、维修和注销
- FastAPI 启动与心跳线程关闭
- 操作员 API 客户端、ASCII 命令输入和自动刷新

## 当前限制

- 模拟器只实现烘干机 `blocked-vent` 一种可注入故障
- 操作员前端目前只显示当前状态与活动故障，尚未显示历史读数和已解除故障
- 应用重启后尚未从 SQLite 恢复内存机器注册表和心跳队列
- 自动故障阈值是原型值，不是设备制造商规格
- 尚未加入数据库迁移工具；`create_all()` 不能升级已有表
- 尚未加入认证和权限控制
- 当前内存注册表和心跳监控面向单进程部署
- 自动测试没有启动真实网络服务器执行完整的后端与模拟器端到端流程

这些限制不阻塞原始本地后端作业，但在接入真实设备、多人操作或生产部署前需要重新评估。
