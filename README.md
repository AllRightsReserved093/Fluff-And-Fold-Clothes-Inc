# Fluff and Fold Clothes Inc

一个用于洗衣店设备状态监控和故障管理的本地后端原型。系统使用 FastAPI 接收洗衣机和烘干机报告，使用 SQLite 保存状态与历史数据，并通过心跳监控和传感器规则发现设备故障。

原始任务说明见 [project_prompt.md](project_prompt.md)。

## 当前功能

- 注册和注销洗衣机、烘干机
- 接收周期报告、状态变化报告、设备故障报告和故障解除报告
- 使用 Pydantic 校验设备类型、传感器结构、枚举、数值范围和带时区时间
- 使用 SQLite 保存机器快照、传感器读数、状态事件和故障历史
- 设备超过 16 秒没有报告时自动标记离线并记录心跳故障
- 设备重新报告后自动恢复在线，并解除活动的心跳故障
- 根据周期报告自动检测传感器故障
- 查询机器状态、历史读数和故障事件
- 支持操作员确认故障和手动解除故障
- 使用控制台模拟20台洗衣机和16台烘干机的正常工作与堵塞故障

## 系统结构

```text
设备或模拟器
    │ HTTP POST
    ▼
FastAPI routes
    ▼
MachineService
    ├── Machine / MachineMonitor
    ├── sensor_fault_analyzer
    └── DatabaseOperation
            ▼
          SQLite
```

`MachineService` 负责协调业务流程；`MachineMonitor` 负责心跳截止时间；`sensor_fault_analyzer` 负责纯传感器规则判断；`DatabaseOperation` 负责 SQLAlchemy 数据库操作。

## 项目结构

```text
app/
├── api/
│   ├── routes/                 # FastAPI 路由
│   └── router.py               # 集中注册 API 路由
├── core/
│   └── config.py               # 环境变量与应用配置
├── database/
│   ├── base.py                 # SQLAlchemy 声明基类
│   ├── models.py               # SQLite 表模型
│   ├── operation.py            # 数据库读写操作
│   └── session.py              # Engine、SessionFactory 与建表入口
├── machines/
│   ├── machines.py             # 内存机器状态
│   └── machine_monitor.py      # 心跳监控线程
├── services/
│   ├── machine_service.py      # 业务流程协调
│   └── sensor_fault_analyzer.py # 传感器故障规则
└── main.py                     # FastAPI 应用入口
laundry_contracts/
└── contracts.py                # 请求、响应、枚举和校验模型
simulator/
├── main.py
├── machine.py
├── washer.py
├── dryer.py
└── faults.py                   # 可扩展的模拟故障行为
tests/                          # 合约、API、数据库、服务、心跳和模拟器测试
```

## 数据库

默认连接地址为：

```text
sqlite:///./laundry.db
```

应用启动时会自动创建尚不存在的表，不需要单独启动 SQLite 服务。

| 表 | 用途 |
|---|---|
| `machines` | 保存每台机器当前的持久化快照 |
| `sensor_readings` | 保存周期报告和故障报告中的传感器历史 |
| `machine_state_events` | 保存机器状态变化历史 |
| `fault_events` | 保存设备、心跳和主机分析产生的故障生命周期 |

`Base.metadata.create_all()` 只能创建缺失的表，不能升级已有表结构。修改模型字段后，目前需要重建开发数据库或另行加入数据库迁移工具。

## 自动传感器故障

周期报告保存时会调用 `sensor_fault_analyzer.py`。当前原型规则如下：

| 故障代码 | 触发条件 |
|---|---|
| `excessive_vibration` | 振动大于 `10.0 m/s²` |
| `door_unlocked_while_running` | 机器运行时门未锁 |
| `washer_water_temperature_high` | 洗衣机水温大于 `80°C` |
| `dryer_air_temperature_high` | 烘干机气温大于 `90°C` |
| `dryer_air_flow_low` | 烘干机运行时气流低于 `0.5 m/s` |

同一种故障持续存在时不会每 15 秒重复创建记录。读数恢复正常后，活动故障会自动解除，但历史记录会继续保存在 `fault_events` 中。

这些阈值仅用于原型演示，正式使用前应替换为设备制造商提供的实际范围。

## API

所有业务路由默认使用 `/api/v1` 前缀。

### 系统状态

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/v1/health` | 健康检查 |

### 机器管理与查询

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/v1/machines/register` | 注册或重新启用机器 |
| `POST` | `/api/v1/machines/deregister` | 注销机器 |
| `GET` | `/api/v1/machines` | 查询全部机器状态 |
| `GET` | `/api/v1/machines/{machine_id}` | 查询一台机器状态 |

### 设备报告

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/v1/reports/periodic` | 接收周期传感器报告 |
| `POST` | `/api/v1/reports/change-of-state` | 接收状态变化报告 |
| `POST` | `/api/v1/reports/error` | 接收设备故障报告 |
| `POST` | `/api/v1/reports/error-resolution` | 接收设备故障解除报告 |

### 读数与故障

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/v1/machines/{machine_id}/readings` | 查询机器传感器读数 |
| `GET` | `/api/v1/faults` | 查询全部机器故障 |
| `GET` | `/api/v1/machines/{machine_id}/faults` | 查询一台机器的故障 |
| `POST` | `/api/v1/machines/{machine_id}/faults/{error_id}/acknowledge` | 确认故障，但不解除 |
| `POST` | `/api/v1/machines/{machine_id}/faults/{error_id}/resolve` | 手动解除故障 |

请求和响应的完整结构可在服务启动后通过 Swagger UI 查看：<http://127.0.0.1:8000/docs>。

## 查询示例

查询当前机器状态：

```text
GET /api/v1/machines
GET /api/v1/machines/washer-01
```

查询一台机器最近 20 条运行状态读数：

```text
GET /api/v1/machines/washer-01/readings?operation_state=running&limit=20
```

查询所有尚未解除且尚未确认的故障：

```text
GET /api/v1/faults?active=true&acknowledged=false
```

读数接口还支持 `start_time`、`end_time`、`operation_state` 和 `limit`；故障接口支持 `active`、`acknowledged` 和 `limit`。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

启动后可访问：

- Swagger API 文档：<http://127.0.0.1:8000/docs>
- OpenAPI JSON：<http://127.0.0.1:8000/openapi.json>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>

保持后端运行，然后在第二个终端启动模拟器：

```powershell
.\.venv\Scripts\Activate.ps1
python -m simulator.main
```

模拟器会错峰注册20台洗衣机和16台烘干机，使用一个后台线程顺序推进全部机器，并将15秒周期报告错峰发送到后端。

控制台支持以下命令：

```text
list
select dryer-01
status
fault blocked-vent
repair
help
quit
```

`blocked-vent` 只能注入到处于加热或烘干阶段的运行中烘干机。注入后当前阶段会冻结，气流逐渐下降、温度逐渐升高；达到设备保护温度后设备报告故障并进入 `FAULTED`。执行 `repair` 后，传感器逐步恢复，设备解除故障并回到 `IDLE`。正常执行 `quit` 会逐台注销模拟设备。

项目不要求 `.env` 才能启动。需要覆盖默认配置时，可以在项目根目录创建 `.env`：

```dotenv
FFC_APP_NAME=Fluff and Fold Clothes Inc API
FFC_APP_VERSION=0.1.0
FFC_API_V1_PREFIX=/api/v1
FFC_DEBUG=false
FFC_DATABASE_URL=sqlite:///./laundry.db
```

## 测试

当前安全测试集使用内存 SQLite，不会修改项目数据库：

```powershell
python -m pytest -q -p no:cacheprovider --ignore=tests/test_machine_service.py
```

当前验证结果为 `43 passed`。

`tests/test_machine_service.py` 尚未完全隔离默认 `SessionFactory`，因此暂时不应直接运行完整的 `pytest` 命令。

## 当前限制

- 模拟器目前只实现烘干机 `blocked-vent` 一种可注入故障
- 应用重启后尚未从 SQLite 恢复内存机器注册表和心跳队列
- FastAPI 生命周期尚未主动停止心跳监控线程
- 自动故障阈值仍是原型值，不是制造商规格
- 尚未加入认证、权限控制和数据库迁移工具
- 当前实现面向单机原型，不是多进程生产部署方案
