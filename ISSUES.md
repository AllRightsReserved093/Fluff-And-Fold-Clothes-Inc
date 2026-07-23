# Project Issues

本文档记录项目专业审查中发现的问题。问题按优先级排列，完成修复后可勾选对应条目。

## High Priority

### ISSUE-001：心跳超时存在边界竞态

- [ ] 未解决
- 严重程度：High
- 相关代码：[machine_monitor.py](app/machines/machine_monitor.py#L154)、[machine_service.py](app/services/machine_service.py#L319)

Monitor 弹出过期任务并释放锁后才调用 Service。在这个间隔内，如果新报告已经更新了机器和下一次截止时间，旧的超时回调仍可能把机器错误地标记为离线并产生 `S8001`。

验收标准：

- 超时回调能够确认自己处理的仍是机器的最新截止时间。
- 截止时间边界上收到的有效报告不会被旧回调覆盖。
- 增加报告与超时回调并发执行的测试。

### ISSUE-002：Monitor 回调异常会终止整个心跳线程

- [ ] 未解决
- 严重程度：High
- 相关代码：[machine_monitor.py](app/machines/machine_monitor.py#L128)、[machine_service.py](app/services/machine_service.py#L326)

数据库写入或超时回调中的其他异常会从 `on_timeout()` 传播到监控线程，使线程永久退出。已有设备后续只会更新堆，不会自动重新启动 Monitor。同时，当前逻辑先修改内存再写数据库，写入失败会造成内存与数据库不一致。

验收标准：

- 单次回调失败不会终止整个监控循环。
- 回调异常被明确记录。
- 数据库写入失败时不会留下无法解释的半更新内存状态。
- 增加回调异常后的线程存活测试。

### ISSUE-003：注册机型与报告机型缺少一致性校验

- [ ] 未解决
- 严重程度：High
- 相关代码：[machine_service.py](app/services/machine_service.py#L124)、[operation.py](app/database/operation.py#L60)

已注册的 Washer 可以提交结构合法的 Dryer 报告。同一机器 ID 注销后，也可以用另一种机型重新注册，导致数据库机型、内存机型、阶段和传感器数据互相矛盾。

验收标准：

- 报告的 `machine_type` 必须与已注册机型一致。
- 历史机器重新注册时不得静默改变机型。
- 机型冲突返回明确的客户端错误。
- 增加跨机型报告和跨机型重新注册测试。

### ISSUE-004：锁存故障生命周期没有落地

- [ ] 未解决
- 严重程度：High
- 相关代码：[fault_codes.md](laundry_contracts/docs/fault_codes.md#L154)、[models.py](app/database/models.py#L300)、[operation.py](app/database/operation.py#L389)、[faults.py](app/api/routes/faults.py#L77)

故障定义要求区分 `active`、`acknowledged`、`condition_cleared` 和 `reset`，但数据库目前只有 `is_acknowledged` 与 `resolved_at`。操作员可以直接解除仍需设备复位的 `F1101`、`F3102` 等锁存故障。

验收标准：

- 能够表示“触发条件已消失，但设备尚未复位”。
- 锁存故障不能通过普通手动解除绕过复位要求。
- Warning、系统状态和锁存故障采用符合各自语义的关闭流程。
- 生命周期变化能够持久化并查询。

### ISSUE-005：ErrorResolutionReport 没有更新机器当前状态

- [ ] 未解决
- 严重程度：High
- 相关代码：[contracts.py](laundry_contracts/contracts.py#L207)、[operation.py](app/database/operation.py#L356)、[machine_service.py](app/services/machine_service.py#L240)

解除报告包含 `operation_state` 和 `cycle_stage`，但当前处理只保存恢复读数并解除故障，没有更新数据库快照或内存机器状态。因此报告声明 `IDLE` 后，机器仍可能显示为 `FAULTED`。

验收标准：

- 接受解除报告后，数据库与内存状态都与报告一致。
- 数据库、内存和恢复读数之间不存在状态矛盾。
- 测试同时断言故障、读数和机器当前状态。

### ISSUE-006：模拟器会在 HTTP 失败后丢失故障报告

- [ ] 未解决
- 严重程度：High
- 相关代码：[faults.py](simulator/faults.py#L66)、[dryer.py](simulator/dryer.py#L38)、[dryer.py](simulator/dryer.py#L190)

堵塞故障只在进入 `TRIPPED` 的一次状态转换中发送 ErrorReport。如果该请求超时或返回错误，模拟器仍进入 `FAULTED`，但不会再次报告该故障。

验收标准：

- ErrorReport 未被后端接受时，模拟器保留待报告状态。
- 后续循环能够重新尝试或明确保持未同步状态。
- 后端最终能够收到故障事实并生成故障快照。

### ISSUE-007：故障解除请求失败后模拟器仍恢复运行

- [ ] 未解决
- 严重程度：High
- 相关代码：[dryer.py](simulator/dryer.py#L201)

模拟器没有检查 ErrorResolutionReport 的请求结果，发送失败后仍会清除 `active_fault` 并转换到 `IDLE`，造成设备与后端故障状态永久分叉。

验收标准：

- 只有后端接受解除报告后才清除本地活动故障。
- 解除失败时机器保持可重试状态。
- 增加解除请求超时、500 和 404 的测试。

### ISSUE-008：应用重启后不会恢复机器注册表和心跳队列

- [ ] 未解决
- 严重程度：High
- 相关代码：[main.py](app/main.py#L17)、[machine_service.py](app/services/machine_service.py#L45)

FastAPI 启动时只创建数据库表，没有从 SQLite 恢复已注册机器。重启后数据库仍显示机器已注册，但内存注册表为空，设备报告会返回 404。当前结构也不支持多 worker。

验收标准：

- 明确选择并实现以下一种策略：
  - 启动时从数据库恢复已注册机器和心跳监控；或
  - 明确要求设备在服务重启后重新注册，并正确处理持久记录。
- 部署配置明确限制为单进程，或消除进程内状态依赖。
- 增加服务重启测试。

## Medium Priority

### ISSUE-009：旧报告可以回滚机器当前快照

- [ ] 未解决
- 严重程度：Medium
- 相关代码：[operation.py](app/database/operation.py#L166)、[operation.py](app/database/operation.py#L234)

系统只根据 `report_id` 去重，没有比较 `recorded_at`。较旧但 ID 不同的报告会覆盖较新的机器状态和阶段。

验收标准：

- 旧报告可以保留在历史中，但不能回滚当前快照。
- 过期报告产生明确的数据质量事件或处理结果。
- 增加跨路由乱序和并发报告测试。

### ISSUE-010：故障码目录没有成为输入约束

- [ ] 未解决
- 严重程度：Medium
- 相关代码：[contracts.py](laundry_contracts/contracts.py#L23)、[contracts.py](laundry_contracts/contracts.py#L178)、[operation.py](app/database/operation.py#L293)

`error_code` 仍可接受任意字符串，系统没有校验代码是否存在，也没有校验代码的 `detection_authority` 是否与 `error_source` 匹配。设备可以把服务器代码或数据事件代码写入故障表。

验收标准：

- 正式报告只能使用目录中允许的代码。
- 代码类型、来源和检测权限保持一致。
- 未知代码或来源冲突返回明确的客户端错误。

### ISSUE-011：传感器分析缺少延迟、迟滞和适用阶段

- [ ] 未解决
- 严重程度：Medium
- 相关代码：[sensor_fault_analyzer.py](app/services/sensor_fault_analyzer.py#L33)、[fault_codes.md](laundry_contracts/docs/fault_codes.md#L95)

当前分析器根据单份读数立即触发，并在下一份正常读数后立即解除，与故障文档中定义的触发延迟、解除延迟、迟滞和适用运行阶段不一致。

验收标准：

- 规则实现与故障码文档保持一致。
- 阈值附近波动不会反复建立和解除故障。
- 非适用状态或阶段不会产生误报。

### ISSUE-012：注册和注销请求中的审计信息被丢弃

- [ ] 未解决
- 严重程度：Medium
- 相关代码：[register.py](app/api/routes/register.py#L25)、[register.py](app/api/routes/register.py#L46)、[operation.py](app/database/operation.py#L68)

API 接收 `registered_at`、`deregistered_at` 和注销原因，但 Service 没有使用这些值。注销还会直接清空当前状态，没有保存注销前状态或注册生命周期历史。

验收标准：

- 明确决定这些字段是正式数据还是从契约中移除。
- 如果保留，必须持久化设备时间和注销原因。
- 注销与重新注册历史可以被重建。

### ISSUE-013：时间查询可因时区混用返回 500

- [ ] 未解决
- 严重程度：Medium
- 相关代码：[readings.py](app/api/routes/readings.py#L19)

`start_time` 和 `end_time` 使用普通 `datetime`。一个参数带时区、另一个不带时区时，Python 比较会抛出 `TypeError`。

验收标准：

- 查询时间必须包含时区并统一转换为 UTC。
- 非法时间组合返回 4xx，而不是 500。
- 增加 naive/aware 混合输入测试。

### ISSUE-014：SQLite 时间没有统一的时区往返策略

- [ ] 未解决
- 严重程度：Medium
- 相关代码：[models.py](app/database/models.py#L53)、[contracts.py](laundry_contracts/contracts.py#L313)

SQLite 不会真正保存时区偏移，读取后的时间通常不带 `tzinfo`。当前只有个别逻辑手工补 UTC，可能导致 API 返回和内部比较不一致。

验收标准：

- 所有数据库时间采用统一的 UTC 存取策略。
- 查询响应中的时间语义明确且一致。
- 增加 SQLite 时间写入、读取和 API 序列化测试。

### ISSUE-015：数据库缺少迁移机制

- [ ] 未解决
- 严重程度：Medium
- 相关代码：[session.py](app/database/session.py#L55)

`Base.metadata.create_all()` 只能创建缺失表，不能升级已有表。模型新增字段、约束或枚举后，现有 `laundry.db` 可能与代码不兼容。

验收标准：

- 为已有数据库定义明确的升级方式。
- 数据库版本与应用版本可以被识别。
- 至少测试一次旧结构到新结构的升级流程。

### ISSUE-016：全局互斥锁覆盖数据库和文件 I/O

- [ ] 未解决
- 严重程度：Medium
- 相关代码：[machine_service.py](app/services/machine_service.py#L125)、[machine_service.py](app/services/machine_service.py#L189)、[machine_service.py](app/services/machine_service.py#L230)

所有机器共享一把锁，数据库事务和故障快照文件写入也在锁内。慢磁盘、数据库锁等待或长查询会阻塞全部报告、查询和心跳回调。

验收标准：

- 明确锁保护的共享内存范围。
- 避免在没有必要时持锁执行数据库查询和文件写入。
- 增加慢 I/O 下报告和心跳处理的并发测试。

### ISSUE-017：操作员控制台自动刷新可能持续取消慢请求

- [ ] 未解决
- 严重程度：Medium
- 相关代码：[main.py](operator_console/main.py#L103)、[main.py](operator_console/main.py#L115)、[api_client.py](operator_console/api_client.py#L20)

控制台每2秒刷新一次，但 HTTP 超时为5秒。`exclusive=True` 可能在慢请求完成前启动下一次刷新并取消前一次工作。

验收标准：

- 同一时刻最多存在一次刷新请求。
- 慢请求能够正常完成或到达超时。
- 增加2至5秒响应延迟的控制台测试。

### ISSUE-018：模拟器把注册冲突当作注册成功

- [ ] 未解决
- 严重程度：Medium
- 相关代码：[machine.py](simulator/machine.py#L44)

模拟器把 HTTP 409 视为注册成功。第二个模拟器实例因此可以接管相同机器 ID，并在退出时注销另一个实例仍在使用的机器。

验收标准：

- 明确区分“当前实例成功注册”和“该 ID 已被其他实例占用”。
- 第二个模拟器实例不会静默与第一个实例共享设备身份。

## Deployment and Maintenance

### ISSUE-019：变更接口没有认证和授权

- [ ] 未解决
- 严重程度：部署前评估
- 相关代码：[register.py](app/api/routes/register.py#L20)、[reports.py](app/api/routes/reports.py#L25)、[faults.py](app/api/routes/faults.py#L55)

在受信任的本地原型环境中可以暂时接受；如果服务可被其他主机访问，任何客户端都可以注册、伪造报告、确认或解除故障，并通过大量故障快照消耗磁盘。

验收标准：

- 部署文档明确网络信任边界。
- 进入真实环境前，为设备写入接口和操作员管理接口建立身份与权限区分。

### ISSUE-020：健康检查不能反映关键依赖状态

- [ ] 未解决
- 严重程度：Low
- 相关代码：[health.py](app/api/routes/health.py#L16)

当前 `/health` 始终返回 `ok`，即使数据库不可用或心跳线程已经死亡。

验收标准：

- 明确当前接口只是进程存活检查；或
- 新增能够检查数据库和 Monitor 状态的 readiness 接口。

### ISSUE-021：README 存在少量过时或缺失信息

- [ ] 未解决
- 严重程度：Low
- 相关代码：[README.md](README.md#L338)、[README.md](README.md#L490)

- 没有说明项目要求 Python 3.11 或更高版本。
- “前端尚未显示已解除故障”的限制与当前 diagnostics 实现不一致。
- 模拟器 API 地址固定，无法跟随自定义 `FFC_API_V1_PREFIX`。

验收标准：

- 文档与当前运行行为保持一致。
- 明确 Python 最低版本和模拟器地址配置限制。

## Test Gaps

- [ ] 心跳截止时间弹出与新报告同时发生的竞态测试。
- [ ] Monitor 回调异常后的线程存活和恢复测试。
- [ ] 跨机型报告与跨机型重新注册测试。
- [ ] 旧时间报告、跨路由乱序和并发请求测试。
- [ ] 锁存、条件恢复、确认和复位生命周期测试。
- [ ] 模拟器 ErrorReport 和 ErrorResolutionReport 失败测试。
- [ ] 服务重启、已有 SQLite 数据库和数据库升级测试。
- [ ] 时区混合查询与 SQLite 时间往返测试。
- [ ] 传感器触发延迟、解除延迟、迟滞和适用阶段测试。
- [ ] 慢 HTTP 响应下的操作员控制台自动刷新测试。

## Review Baseline

审查时的验证结果：

- 完整测试：`61 passed`
- 依赖检查：`pip check` 通过
- 差异检查：`git diff --check` 无空白错误

