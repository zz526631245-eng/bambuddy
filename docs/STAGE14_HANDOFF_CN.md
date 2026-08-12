# 阶段 14 交接：单台真实打印机受控发送

日期：2026-08-12

分支：`codex/feature-stage14-real-printer`

实现提交：`0ffa6ef feat(stage14): add controlled real-printer dispatch`。

## 已完成

- 在 `/slice-library` 为每份切片产物增加“发送到真实打印机”入口；操作者必须自己选择一台真实打印机并完成二次确认。
- 新增 `POST /api/v1/production/slice-artifacts/{artifact_id}/dispatch`。该接口只接受已关联非虚拟 `PlateJob` 的真实切片结果，要求打印机启用、MQTT 已连接且生产状态可用。
- 发送并不新建设备协议：确认后仅创建 Bambuddy 原有 `PrintQueueItem`，仍由既有调度器执行 FTP 上传和 MQTT 启动。
- 阶段 9 的受保护源文件队列项会被取消并保留原因；新队列使用切片产物的 `.gcode.3mf`。同一真实机同一时间只允许一个未结束生产盘任务。
- 生产队列路由与调度器均增加保护：虚拟任务和未确认的真实任务不得进入实际发送路径；只有阶段 14 已确认、状态为 `ready` 的真实盘任务可继续。
- 复用主程序 MQTT 回调：开始时任务进入 `printing`，完成/失败时进入 `waiting_cleanup`；质检、报废数量和清板仍走阶段 11 的人工工作流与后端账本。
- 真实机状态页从既有 `printer_manager` 状态快照读取；禁止对真实机写入阶段 13 模拟心跳。自动分配优先选符合条件的真实机，虚拟机仅是回退。

## 后续修复：真实打印机耗材二维码

- `/printer-consumables` 现在在扫码登记前展示所有已启用真实打印机的独立二维码，并支持下载 SVG 标签；虚拟测试机不会出现在这个标签区。
- 标签编码的是手机可访问地址 `/printer-consumables?printer=printer:<id>`。扫码后前端已有解析逻辑会锁定对应打印机，随后扫描耗材卷并点击“确认登记”即可替换旧直供耗材。
- 二维码不含打印机 IP、序列号或访问码；手机页面依然遵守 HTTPS 与现有权限控制。
- 新增前端单元测试 `printerConsumableQr.test.ts`，覆盖地址与目标键的编码。

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

## 未完成、风险与下一步

- 尚未进行一台真实打印机的人工验收；首次验收必须使用无关紧要的测试模型并有人在机器旁。
- 真实机访问码只应保存在用户本机数据库，不能进入 Git、文档、截图或安装包配置。
- 如果真实机未连接、状态离线、耗材/颜色不匹配或任务来自虚拟机，接口会拒绝发送；这是预期保护，不应通过手改数据库绕过。
- 完成人工验收后，记录成功与失败两条流程的结果；若无问题，再讨论多机扩展和发布标签。未经全部测试通过的 GitHub Actions 标签，不构建 Windows 安装包。
