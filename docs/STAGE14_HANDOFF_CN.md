# 阶段 14 交接：真实打印机自动匹配与既有队列发送

日期：2026-08-12

分支：`codex/feature-stage14-real-printer`

基础实现提交：`0ffa6ef feat(stage14): add controlled real-printer dispatch`。
前一项修复提交：`00d9735 fix(stage14): auto-pack single products and dispatch eligible jobs`。
本次修复提交：`df5b844 fix(stage10): preserve rotated 3mf geometry during auto-pack`。

## 已完成

- 在 `/slice-library` 为每份切片产物增加“发送到真实打印机”入口；操作者必须自己选择一台真实打印机并完成二次确认。
- 新增 `POST /api/v1/production/slice-artifacts/{artifact_id}/dispatch`。该接口只接受已关联非虚拟 `PlateJob` 的真实切片结果，要求打印机启用、MQTT 已连接且生产状态可用。
- 发送并不新建设备协议：确认后仅创建 Bambuddy 原有 `PrintQueueItem`，仍由既有调度器执行 FTP 上传和 MQTT 启动。
- 阶段 9 的受保护源文件队列项会被取消并保留原因；新队列使用切片产物的 `.gcode.3mf`。同一真实机同一时间只允许一个未结束生产盘任务。
- 生产队列路由与调度器均增加保护：虚拟任务和未确认的真实任务不得进入实际发送路径；只有阶段 14 已确认、状态为 `ready` 的真实盘任务可继续。
- 复用主程序 MQTT 回调：开始时任务进入 `printing`，完成/失败时进入 `waiting_cleanup`；质检、报废数量和清板仍走阶段 11 的人工工作流与后端账本。
- 真实机状态页从既有 `printer_manager` 状态快照读取；禁止对真实机写入阶段 13 模拟心跳。自动分配优先选符合条件的真实机，虚拟机仅是回退。

## 后续修复：真实打印机耗材二维码

- 修复提交：`c48d6fa fix(stage12): add real printer consumable QR labels`。
- `/printer-consumables` 现在在扫码登记前展示所有已启用真实打印机的独立二维码，并支持下载 SVG 标签；虚拟测试机不会出现在这个标签区。
- 标签编码的是手机可访问地址 `/printer-consumables?printer=printer:<id>`。扫码后前端已有解析逻辑会锁定对应打印机，随后扫描耗材卷并点击“确认登记”即可替换旧直供耗材。
- 二维码不含打印机 IP、序列号或访问码；手机页面依然遵守 HTTPS 与现有权限控制。
- 新增前端单元测试 `printerConsumableQr.test.ts`，覆盖地址与目标键的编码。

## 后续修复：扫码耗材显示与料型校验

- 打印机页面的“外部耗材”卡片现在只显示当前有效的扫码生产耗材记录，不再用 MQTT `vt_tray` 的颜色或料型覆盖该记录。
- 对真实打印机确认登记前，后端仅从已连接的 MQTT 状态快照读取外部料槽的材料类型做安全校验；颜色变化不会被拒绝，但 `PLA`、`PETG`、`TPU` 等料型不一致时会拒绝登记，并提示先在打印机或 Bambu Studio 中调整外部料型。
- 打印机离线或设备尚未设置外部耗材料型时同样拒绝登记；本次实现不会写入真实打印机、不会新建 MQTT 连接，也不会发送打印。
- 扫码页现在直接显示接口返回的中文错误，不再显示 `ApiError:` 前缀。

## 本地验证

已通过：

```powershell
python -m pytest backend/tests/integration/test_stage14_real_printer_dispatch.py -q
# 3 passed

python -m pytest backend/tests/integration/test_stage9_production_allocation.py backend/tests/integration/test_stage10_slicing.py backend/tests/integration/test_stage11_quality_loop.py backend/tests/integration/test_stage12_direct_consumable_scan.py backend/tests/integration/test_stage12_consumable_library.py backend/tests/integration/test_stage13_printer_status.py backend/tests/integration/test_stage14_real_printer_dispatch.py -q
# 30 passed

ruff check backend/app/api/routes/production.py backend/app/api/routes/print_queue.py backend/app/main.py backend/app/schemas/production.py backend/app/services/print_scheduler.py backend/app/services/production_eligibility.py backend/app/services/production_order_service.py backend/app/services/production_printer_status.py backend/app/services/production_real_dispatch.py
# All checks passed

Set-Location frontend
npm.cmd run build
npm.cmd run lint
```

前端构建和 lint 均通过。测试使用替身连接谓词，不会打开 MQTT/FTP，也不会接触真实设备。

本次补充验证：

```powershell
python -m pytest backend/tests/integration/test_stage12_direct_consumable_scan.py backend/tests/integration/test_stage12_consumable_library.py backend/tests/integration/test_stage13_printer_status.py backend/tests/integration/test_stage14_real_printer_dispatch.py -q
# 14 passed

ruff check backend/app/services/production_consumable_service.py backend/tests/integration/test_stage12_direct_consumable_scan.py
# All checks passed

Set-Location frontend
npm.cmd test -- --run src/__tests__/pages/PrintersPage.test.tsx
# 61 passed
npm.cmd run build
# passed
```

## 本次真实生产修复（2026-08-12）

- 自动分配会刷新真实 A1 的 MQTT 状态，并以扫码耗材快照作为材料/颜色匹配依据；直供槽位 254 与产品槽位 0 的单槽需求可以正确匹配，旧阶段 11 虚拟配置不会再错误阻塞真实 PETG/白色打印机。
- 当同型号真实打印机已配置但离线、忙碌或耗材不匹配时，任务保持待分配，不会静默回退到虚拟测试机；虚拟回退仅保留给没有同型号真实设备的显式软件测试场景。
- 订单确认和后台分配都已接入真实切片；固定盘数量拆分时，重复调用单盘 3MF 始终传入源盘 `plate=0`，不再把第 2 个成品误当作源盘 2。
- Windows 原生切片 sidecar 的 `localhost` 已统一转为 IPv4 回环地址；重排队后的分配日志使用唯一事件 ID，避免 SQLite 唯一键冲突导致分配回滚。
- 当前实测订单 3 已自动分配到真实 `A1-1`，PETG/白色匹配，真实切片成功生成 6 个 `.gcode.3mf` 产物并保持在待打印队列；本次未发送打印命令。

## 本次自动摆盘与自动入队修复（2026-08-12）

- 单盘产品的新文件上传默认使用 `auto_pack`。用户只需上传一份源 3MF；切片器会根据模型尺寸和打印机规格在一盘内安排尽可能多的套数。多盘产品仍要求每张源盘分别上传，不做跨源盘复制。
- 真实生产订单在真实打印机在线、空闲、型号和扫码耗材匹配、切片成功后，后台会自动调用同一套真实切片发送服务，取消源文件占位队列并创建非 `manual_start` 的真实产物队列项。既有调度器继续负责上传与启动。
- `auto_dispatch_real_slice_job` 对多个切片产物保持安全等待，因为当前 `PlateJob.queue_item_id` 只能关联一个队列项；在多盘队列模型完成前不会只发送第一盘。现有已保存为 `fixed_plate` 的历史源文件不会被静默改写，需要重新上传或选择 `auto_pack` 后新建订单。

## 本次旋转模型自动摆盘修复（2026-08-12）

- 旧实现只读取网格顶点的原始 X/Y；用户的 A1 源文件通过 build-item 矩阵把模型绕 X 轴旋转后，真实底面是约 `36.4 × 42.8mm`，旧算法误判为 `36.4 × 7.8mm`，写入的 Y 坐标导致模型越界，Bambu Studio 报空盘。
- 新实现解析 3MF 根对象、组件路径和 build-item 变换后再计算投影；自动摆盘写回时只改变 XY 平移与 Z 轴朝向，不改变缩放、Z 高度、X/Y 倾斜或项目内嵌切片参数。
- 用户本次失败的源文件已通过修复后的真实 sidecar 验证：6 套自动摆盘生成单盘 `.gcode.3mf` 成功；验证只调用切片器，没有向打印机发送。

本次验证：

```powershell
python -m pytest backend/tests/unit/test_production_printer_capabilities.py backend/tests/unit/test_stage10_slicer.py backend/tests/integration/test_stage9_production_allocation.py backend/tests/integration/test_stage10_slicing.py backend/tests/integration/test_stage14_real_printer_dispatch.py -q
# 26 passed

ruff check backend/app/services/production_allocator.py backend/app/services/production_eligibility.py backend/app/services/production_printer_capabilities.py backend/app/services/production_printer_status.py backend/app/services/production_slicer.py backend/app/services/slicer_api.py
# All checks passed
```

## 本次整套产品路由与长盘审核修复（2026-08-12）

- `PrinterProfile` 增加可选的打印宽度、深度、高度；三个值都大于 0 时按配置判断，否则按已知机型默认打印体积。生产分配会解析完整 3MF 的 build-item/组件变换，保留整套零件的相对间距，按整套的真实投影判断能否放入目标机。
- `compatible_printer_models` 只作为优先级提示，不再阻止实际尺寸兼容的其他机型；所有可用真实机按每盘可容纳的完整产品套数择优。若某型号的真实设备忙碌、离线或料型不匹配，不会把生产任务静默回退到虚拟测试机。
- 自动摆盘复制的是完整 build-item 组：一个源 3MF 中的多个零件始终作为一套同步平移和绕 Z 轴旋转；不会缩放、不会改 Z 高度、不会改源文件的切片参数。`product_set_index` 与每盘数量仍由后端记录。
- 真实切片超过 30 小时会把 `PlateJob.slice_time_review_status` 置为 `pending`，自动入队逻辑会暂停。订单详情可“确认仍然分配”；选择“拒绝并重新摆盘”后按完整产品套数递减并重新切片，直到低于限制；单套仍超时则返回人工确认/换机提示。
- 新增 `/api/v1/production/plate-jobs/{id}/slice-time-review`，使用幂等 `operation_id`；新增 Stage 14 可重复迁移，补齐打印配置尺寸、盘任务审核状态/时限/每盘上限。同步修复生产模型注册和生产表集合，确保旧 SQLite 升级测试可重复执行。

本次验证：

```powershell
python -m pytest backend/tests/unit/test_production_migrations.py backend/tests/unit/test_stage10_real_slicing.py backend/tests/unit/test_stage10_slicer.py backend/tests/integration/test_stage9_production_allocation.py backend/tests/integration/test_stage10_slicing.py backend/tests/integration/test_product_size_routing.py backend/tests/integration/test_stage14_real_printer_dispatch.py backend/tests/integration/test_production_order_controls.py -q
# 50 passed

ruff check backend/app/api/routes/production.py backend/app/core/database.py backend/app/models/__init__.py backend/app/models/printer_profile.py backend/app/models/production.py backend/app/schemas/production.py backend/app/services/production_eligibility.py backend/app/services/production_order_service.py backend/app/services/production_real_dispatch.py backend/app/services/production_slicer.py backend/tests/integration/test_stage14_real_printer_dispatch.py backend/tests/unit/test_stage10_real_slicing.py
# All checks passed

Set-Location frontend
npm.cmd run build
npm.cmd run lint
```

`backend/tests/integration/test_production_api.py` 仍有 1 个旧断言失败：测试要求无源文件时返回“零件清单”，现行阶段 8 合同返回“请先上传产品源文件”。该失败与本次几何/审核改动无关，未改变现行产品源文件必填规则。

## 下一步与风险

- 需要在真实打印机旁用低风险测试模型人工验证：尺寸匹配、超 30 小时确认/拒绝、真实切片产物和打印完成后的质检/清板流程。
- 多切片产物仍不会只发送第一盘，因为现有 `PlateJob.queue_item_id` 只能关联一个队列项；需后续扩展多盘队列关系后再支持整组自动发送。
- 本次没有构建安装包，也没有提交任何真实打印机访问码或生产数据。

## 未完成、风险与下一步

- 尚未进行一台真实打印机的人工验收；首次验收必须使用无关紧要的测试模型并有人在机器旁。
- 真实机访问码只应保存在用户本机数据库，不能进入 Git、文档、截图或安装包配置。
- 如果真实机未连接、状态离线、耗材/颜色不匹配或任务来自虚拟机，接口会拒绝发送；这是预期保护，不应通过手改数据库绕过。
- 完成人工验收后，记录成功与失败两条流程的结果；若无问题，再讨论多机扩展和发布标签。未经全部测试通过的 GitHub Actions 标签，不构建 Windows 安装包。

## UI 导航精简补充（2026-08-12）

- 分支：`codex/ui-navigation-cleanup`。
- 只调整前端导航入口、中文名称和低频菜单显示；没有删除任何生产、耗材、打印机或文件路由。
- 主侧边栏入口为打印机、生产中心、耗材中心、产品、打印记录、设置。相关低频页面通过生产中心、耗材中心、打印机和产品页的“相关功能”入口访问。
- 验证：`npm.cmd run lint`、`npm.cmd test -- --run src/__tests__/components/Layout.test.tsx src/__tests__/pages/Stage8ProductionOrders.test.tsx`（31 passed）、`npm.cmd run build` 均通过。
- 下一步：用户刷新 8019 页面检查导航是否符合日常操作；确认后再决定是否继续调整分组或制作安装包。

## 分组入口页面内展开补充（2026-08-12）

- 生产中心、耗材中心、打印机、产品资料的 HubNav 已改为页面内选择器；点击相关功能会在当前页面下方直接替换为原完整页面组件，不再自动滚动，入口保持吸顶可切换。
- 产品资料分组移除“项目”入口；Projects 路由及数据保留。
- 新增 HubNav 交互回归，验证带 `onSelect` 时阻止路由跳转并返回目标分组。
- 验证：`npm.cmd run build`、`npm.cmd run lint`、Layout/生产订单/设置定向测试 `78 passed`，HubNav 测试通过。

## 清理料盘强制互锁补充（2026-08-12）

- 分支：`codex/plate-clear-enforcement`。
- 打印完成或失败后，未点击“确认清理料盘”时，调度器、自动分配、真实切片派发和指定打印机队列入口均拒绝新任务；清理确认后才恢复可用。
- `require_plate_clear` 已改为强制开启。启动迁移会把旧的 `false` 设置改为 `true`，设置 API 也不允许关闭该安全规则。
- 回归测试：调度器清板测试 `32 passed`；Stage 14 真实派发测试 `9 passed`；普通打印队列测试 `88 passed`；设置接口测试 `5 passed`。
- 前端设置页将清板规则显示为始终开启且不可关闭，避免操作员误以为可以绕过确认。
# Cleanup state synchronization (2026-08-12)
- Branch: `codex/sync-plate-clear`.
- The production order, printer page, and QR scanner all write the same `printer_manager.awaiting_plate_clear` state.
- Real production cleanup commits the order before releasing its linked printer. Virtual printers are unchanged.
- The QR consumables page displays the shared state and reuses `POST /printers/{printer_id}/clear-plate`, refreshing related query caches after success.
- Verification: Stage 11/14 `15 passed`; frontend lint/build passed.
- Next: after restarting port 8019, verify on one real printer that new allocation stays blocked until cleanup is confirmed from either page.
