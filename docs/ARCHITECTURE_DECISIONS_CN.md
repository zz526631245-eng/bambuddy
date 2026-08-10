# 架构决策

## AD-001：保留 Bambuddy 原核心

不重做队列、打印协议、库存、虚拟打印机和切片流水线。生产模块通过现有主键和服务连接这些模块，降低升级和回归风险。

## AD-002：独立生产业务层

产品、零件、材料类型、打印机配置、打印方案、生产订单、生产需求、任务草稿和操作记录使用独立模型。原 Project 的零件清单语义不被修改。

## AD-003：订单保存只读快照

创建订单时保存产品、产品零件清单和打印方案快照。之后修改产品或方案不会改变历史订单的需求数量和含义。

## AD-004：数量账本只有一个权威来源

`backend/app/services/production_accounting.py` 是计划数、已安排、合格、报废和剩余数量的统一计算入口。守恒关系为：`计划数 = 已安排 + 合格 + 剩余`。报废数量单独记录，不错误抵扣需求。

## AD-005：所有可重试写操作具有操作编号

创建订单、状态变更和确认任务草稿使用唯一 `operation_id`。同一请求因网络重试再次到达时返回已有结果，不重复生成订单或草稿。

## AD-006：草稿确认后自动分配，打印仍受阶段边界保护

阶段 8 只生成 `PlateJob` 草稿。阶段 9 由独立的 `ProductionAllocator` 自动匹配已启用的生产配置和打印机，并复用现有 `PrintQueueItem` 建立双向关联。自动分配不能调用代理、FTP、MQTT 或 `start_print()`；生产来源队列项保持人工暂停，队列接口和调度器底层都禁止启动。PostgreSQL 使用跳过已锁定行的行锁防止重复分配；SQLite 仅支持单个 Bambuddy 进程运行分配器。

## AD-007：双数据库兼容

SQLite 用于小白友好的单机部署，PostgreSQL 用于更高并发。模型、约束、升级和重复迁移必须同时测试。

## AD-008：取消订单使用独立权限

暂停和恢复需要“修改生产订单”权限；取消走独立接口并需要“取消生产订单”权限。不能用一个宽泛的修改权限代替取消权限。
## AD-009: Shared material and colour capability contract

Product source 3MF requirements are stored per filament slot and copied into the order snapshot. Real and virtual printers expose the same static supported-material/colour capability and current loaded-filament state to one matcher. Stage 9 only performs software matching; a later real-printer adapter may populate current state from MQTT/device telemetry.
## AD-010: Product colour is a file variant, not a printer capability field

The product-level colour/combination identifies which source 3MF variant is being produced (for example a red-cover/white-button combination). Per-slot filament requirements remain separate for material loading checks. Replacing a colour variant creates a new active version and deactivates the previous row; historical orders retain their immutable snapshot and are never silently switched.

## AD-011: Stage 10 planning is deterministic and simulation-only

Stage 10 stores fixed-plate or auto-pack planning results on `PlateJob`, including source-file association, geometry, printer build volume, capacity, placements and retry state. The planner does not invoke a slicer binary or any printer transport. A later slicer adapter may consume this stable result, while MQTT, FTP and real print dispatch remain blocked by the project stage boundary.

## AD-012: Real slicing consumes embedded 3MF settings

The production real-slice path reuses the existing Bambu Studio/OrcaSlicer sidecar and sends the original product 3MF with `export_3mf=true`. The source project remains the authority for orientation, process, infill, support and object-level overrides; `auto_pack` only enables the slicer's arrange flag. A printer switch may patch only `printer_settings_id` and `printer_model`, leaving all other project settings and ZIP entries unchanged. The output is stored as a new library `.gcode.3mf`; no printer transport is invoked.

## AD-014: Product size class is a routing constraint

Products persist a user-declared `size_class` (`standard` or `large`) and copy it into order snapshots. The allocator uses `large` only to exclude A1/A1 Mini profiles; material/colour capability matching remains the primary compatibility check. Actual build-volume validation and fixed/auto packing are performed by the selected printer's slicer, and the assigned printer model is the default real-slice target when no explicit override is provided.

## AD-013: Real-slice outputs are reusable library artifacts

每次真实切片以源文件 SHA-256、源文件版本、摆盘策略、切片器和目标打印机身份生成唯一指纹，成功输出写入 `slice_artifacts` 并关联文件库中的 `.gcode.3mf`。相同指纹再次请求时直接复用，不重复调用切片器；源文件或关键参数变化会生成新结果。切片库允许查看和下载，阶段 14 前的发送接口明确拒绝，不创建打印队列也不连接打印机。

## AD-015：多盘固定源文件按“套次 × 源盘”建模

一个多盘 3MF 代表一套完整产品，而不是一盘可复制的单件产品。产品源文件保存源盘总数；订单数量表示完整产品套数，确认任务时为每个套次和每张源盘建立一个物理 `PlateJob`，每个物理盘计划数量固定为 1。`product_set_index` 和 `source_plate_index` 用于把完成事件重新归组为完整产品套数。该策略不进行自动复制或自动排列，真实切片按源盘编号调用切片器；切换打印机只改变目标机型配置并保留源文件的方向、支撑、填充和局部参数。

## AD-016：多盘分类归属于产品，源文件按源盘分组

产品保存 `production_mode` 和 `source_plate_count`。多盘产品上传一套源文件时，每张源盘是一个独立的 `ProductFile`，通过 `source_set_id` 和 `source_plate_index` 组成同一套；产品订单只选择该组的入口文件，后端快照保存整组文件 ID 并在切片时按源盘索引解析实际文件。文件本身不再决定产品是否多盘；旧的 `multi_plate_fixed` 文件策略仅作为迁移兼容。

## AD-017：阶段 11 以人工质检为数量入账依据

虚拟打印机报告完成或失败只表示打印流程结束，不能直接增加合格数量。盘任务按“已分配 → 待打印 → 打印中 → 待质检 → 待清板 → 已完成”推进；人工填写合格数量，后端计算报废数量并通过统一账本入账。清板确认前虚拟打印机保持占用。多盘产品只有同一套的全部源盘完成质检后才结算一套；失败补产使用新的套次编号。阶段 11 所有动作仅更新软件状态，不调用真实打印机、MQTT、FTP 或发送接口。
