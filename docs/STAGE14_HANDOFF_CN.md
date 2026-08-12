# 阶段 14 交接：真实打印机自动匹配与既有队列发送

日期：2026-08-12

分支：`codex/feature-stage14-real-printer`

基础实现提交：`0ffa6ef feat(stage14): add controlled real-printer dispatch`。
本次修复提交：`85bc004 fix(stage14): auto-pack single products and dispatch eligible jobs`。

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

本次验证：

```powershell
python -m pytest backend/tests/unit/test_production_printer_capabilities.py backend/tests/unit/test_stage10_slicer.py backend/tests/integration/test_stage9_production_allocation.py backend/tests/integration/test_stage10_slicing.py backend/tests/integration/test_stage14_real_printer_dispatch.py -q
# 26 passed

ruff check backend/app/services/production_allocator.py backend/app/services/production_eligibility.py backend/app/services/production_printer_capabilities.py backend/app/services/production_printer_status.py backend/app/services/production_slicer.py backend/app/services/slicer_api.py
# All checks passed
```

## 未完成、风险与下一步

- 尚未进行一台真实打印机的人工验收；首次验收必须使用无关紧要的测试模型并有人在机器旁。
- 真实机访问码只应保存在用户本机数据库，不能进入 Git、文档、截图或安装包配置。
- 如果真实机未连接、状态离线、耗材/颜色不匹配或任务来自虚拟机，接口会拒绝发送；这是预期保护，不应通过手改数据库绕过。
- 完成人工验收后，记录成功与失败两条流程的结果；若无问题，再讨论多机扩展和发布标签。未经全部测试通过的 GitHub Actions 标签，不构建 Windows 安装包。
