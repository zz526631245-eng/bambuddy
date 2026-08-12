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

## AD-018：阶段 12 直供耗材以扫码绑定为唯一当前记录

直供耗材使用独立的 production_printer_consumables 绑定表，不复用 AMS 槽位分配语义。每台真实或软件打印机最多一条有效直供耗材；扫描新耗材时原记录自动失效并保留替换时间和操作日志。扫描同步更新打印机的当前耗材快照，颜色和材料继续交给同一套生产能力匹配器。AMS 保持可选，阶段 12 不连接真实打印机、不读取硬件状态，也不发送打印。

## AD-019：耗材卷库与材料类型分层

材料类型是目录数据；实际拥有的每一卷耗材使用独立的 production_consumable_units 记录和唯一 unit_code。批量生成二维码只生成标签，不增加可用库存；扫码入库后才进入库存，扫码耗尽或报废后从可用库存移除。耗材卷状态变化通过操作编号幂等并保留审计记录；绑定打印机时引用耗材卷记录，耗尽会自动释放直供绑定。

## AD-020：手机摄像头测试使用本地 HTTPS

本地开发提供自签名 HTTPS 启动脚本和 30 天开发证书，证书只写入被忽略的数据目录。手机摄像头只能在 HTTPS 或 localhost 等安全上下文使用；正式部署应使用用户信任的局域网证书/反向代理证书，不把开发私钥打进安装包。
## AD-021：锁定打印机后的耗材扫码需要人工确认

在打印机目标已由二维码锁定后，耗材卷二维码只需读取唯一 unit_code；页面从耗材库数据填入材料和颜色并显示待确认状态，操作员点击确认后才调用后端创建直供绑定。后端仍使用 operation_id 幂等和旧绑定审计，不在前端计算库存或颜色。

## AD-022：阶段 13 使用独立的打印机状态快照契约

生产层使用 `production_printer_status` 保存实体打印机和虚拟打印机的统一状态快照、心跳时间、故障信息和当前盘任务。阶段 13 只开放模拟/适配器心跳接口，不在状态接口内连接 MQTT、FTP 或真实设备；阶段 14 的真实适配器复用同一接口。心跳超过 30 秒、状态为离线/故障/维修中的目标不能参与新的自动分配；尚未开始的生产盘任务会回到待分配并写入 `operation_logs`，正在打印的任务不由后台强制改写。

网页摄像头识别使用 ZXing 作为跨浏览器实现，避免把生产流程绑定到实验性的 BarcodeDetector。二维码生成地址可通过 VITE_PUBLIC_BASE_URL 配置，禁止把回环地址作为手机标签地址。

## AD-023：阶段 14 的真实打印只允许单机、显式确认和既有队列传输

阶段 14 不另建 MQTT 或 FTP 发送通道。用户必须在切片库中选择一个已启用的真实打印机，并明确确认一份已经真实切片、且关联生产盘任务的结果，系统才把该结果交给 Bambuddy 既有打印队列；调度器继续负责 FTP 上传与 MQTT 启动。系统不会自动挑选真实打印机，也不会把虚拟打印机任务发送到真实设备。

每次只允许同一台真实打印机执行一个未结束的生产盘任务。阶段 9 为真实机创建的受保护源文件队列项会保留审计记录并标记取消，再替换为经确认的真实切片文件。只有状态为“待打印”的第 14 阶段生产任务才可穿过队列发送保护；虚拟任务和未确认的真实任务仍被拒绝。

真实打印机状态只从 Bambuddy 已连接的 MQTT 状态快照读取，不允许在生产状态页手工伪造。MQTT 确认开始后盘任务进入“打印中”；打印完成或失败后进入“待质检”，合格/报废数量和清板仍须人工确认，数量始终由后端账本计算。访问码仅保留在用户本机数据库，禁止提交到仓库或打入测试数据。

## AD-024：直供耗材以扫码生产记录显示，以设备料型作安全校验

真实打印机页面的外部耗材显示只使用有效的 `production_printer_consumables` 扫码绑定记录；设备 MQTT 的 `vt_tray` 不能覆盖已扫码登记的颜色或材料。阶段 14 在确认真实打印机的直供耗材登记前，只读取既有 MQTT 快照中的外部料槽材料类型进行安全校验：设备料型与扫码料型不同、设备离线或未设置料型时拒绝登记，并给出可操作的中文提示。该校验不新建 MQTT 连接、不发送打印，也不自动向实体打印机写入耗材设置。
