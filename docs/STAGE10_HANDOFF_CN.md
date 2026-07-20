# 阶段 10 交接：固定摆盘和自动摆盘切片

> 最新完整交接请先阅读 `docs/handoff/stage10/README_CN.md`、`NEXT_STAGE_PLAN_CN.md` 和 `TEST_REPORT_CN.md`；本文件保留为阶段 10 历史技术记录。

## 当前分支

`codex/feature-stage10-slicing`

## 已完成

- 新增确定性的阶段 10 切片规划服务：小产品按 3MF 网格边界和虚拟打印机尺寸自动计算网格摆盘；大产品按源文件固定摆盘策略保留布局，并按源盘数拆分多盘。
- `PlateJob` 保存切片状态、尝试次数、失败原因、切片时间和结果 JSON。结果包含源产品文件/文件库 ID、源文件 SHA-256、版本快照、打印机尺寸、实际一盘套数、盘数和摆盘坐标。
- 生产订单确认后会执行模拟切片规划；失败任务可通过 `POST /api/v1/production/plate-jobs/{plate_job_id}/slice` 重试。
- 前端生产订单详情显示切片状态、虚拟打印机、实际一盘产能、盘数和失败原因，并提供重试按钮。

## 验证结果

- 后端阶段 7/8/9/10 回归及阶段 10 单元测试：`35 passed`。
- 前端 `npm.cmd run build` 通过；`npm.cmd run lint` 通过。
- 手工虚拟验收数据：
  - 订单 2：测试产品 2 使用 A1，自动摆盘为 4 套/盘、1 盘。
  - 订单 3：同类文件使用 A2L，自动摆盘为 5 套/盘、2 盘，证明尺寸影响产能。
  - 订单 4：大产品固定摆盘，源文件 4 个源盘、订单 2 套，结果为 8 盘且 `rearranged=false`。
  - 无效 3MF 的失败和重试在集成测试中验证，失败原因可见且尝试次数递增。

## 安全边界和未完成项

- 本阶段只生成软件内的模拟切片规划结果，不运行真实切片器，不生成可打印 G-code，不连接 MQTT/FTP，不发送真实打印指令，也不启动打印队列。
- 虚拟打印机仅用于尺寸/能力计算和结果展示；真实打印机适配、设备遥测和发送打印仍受阶段 14 前的项目边界限制。
- 当前 3MF 检查读取模型顶点边界并识别常见源盘元数据；尚未处理所有 3MF 组件变换、复杂装配语义或真实切片器专有参数。

## 下一步

用户确认阶段 10 验收后，再决定是否进入真实切片器适配和后续阶段。任何进入真实打印机通信、发送打印或自动启动队列的工作都必须等到项目规定的阶段 14。

## 真实切片入口

- `POST /api/v1/production/plate-jobs/{id}/real-slice` 已接入现有 Bambu Studio/OrcaSlicer sidecar。
- 不传目标打印机时，完整使用源 3MF 的内嵌参数；自动摆盘策略只向切片器传 `arrange=true`。
- 传入 `target_printer_preset`/`target_printer_model` 时，只修改内嵌打印机身份字段，其他项目设置和 ZIP 内容保持不变。
- 成功结果写入文件库中的新 `.gcode.3mf`，`slice_result.real_slice=true`、`simulation_only=false`，并保留源文件 SHA-256 与输出文件 ID。
- 本机 sidecar 已在测试端口运行；真实测试确认产品 2 的旧多盘布局在保留旋转的前提下归零平移后可成功自动摆盘。对外安装时仍需随安装说明启动切片 sidecar。
# Slice library follow-up (2026-07-19)

- Real outputs are persisted in `slice_artifacts` and reused by source/settings fingerprint.
- `GET /api/v1/production/slice-artifacts` lists results and the download endpoint retrieves `.gcode.3mf`.
- Dispatch is intentionally blocked before Stage 14. Product 2 failed because the slicer sidecar was unavailable.

## Quantity-specific real slicing fix (2026-07-20)

- Auto-pack now expands each product set to the exact quantity for that plate and sends every plate separately to the sidecar.
- Plate quantity and index are part of the artifact fingerprint, so the final partial plate is not incorrectly reused from a full plate.
- `slice_result.plates` lists each output artifact; `plate_quantities` records the requested split. Download remains available and dispatch remains blocked.
- A geometry/out-of-printable-area error is now explained explicitly instead of being reported as an opaque real-slice failure. The source 3MF is never silently rewritten to disable auto-pack.
- Focused tests: `9 passed` for Stage 10 real slicing/cache/quantity behavior.
## Output filename clarification (2026-07-20)

- Each real sliced artifact now states its plate index and plate quantity in the filename: `源文件名.plate-1.qty-3.gcode.3mf`.
- Multi-plate output is immediately distinguishable (for example `.plate-1.qty-6` and `.plate-2.qty-4`), while file contents remain real sidecar-generated G-code 3MF.
- The cache key includes the naming convention version, forcing one regeneration after this naming-only change; later exact retries reuse the renamed artifact.
- Verification: focused Stage 7/8/9/10 suite `49 passed`; no real printer, MQTT/FTP or print dispatch is used.
## Z 高度保留修复 (2026-07-20)

- 根因是旧的布局归一化把 X/Y/Z 三个平移值都设置为 0，导致真实切片文件中的模型陷入打印板。
- 现在只设置 X/Y 为 0，保留 Z 平移、旋转矩阵和全部内嵌打印参数；缓存指纹已升级，旧错误结果不会复用。
- 已重新生成并验证 `111.plate-1.qty-3.gcode.3mf`、`111.plate-1.qty-6.gcode.3mf`、`111.plate-2.qty-4.gcode.3mf`，模型 Z 高度恢复为源文件的 `11.9565001`。
- 本阶段仍不连接真实打印机、不发送 MQTT/FTP 或打印指令。

## 多盘固定源文件规则（2026-07-20）

- 新增 `multi_plate_fixed` 产品源文件策略，上传时记录 3MF 源盘数量；每张源盘固定对应 1 份，不允许自动复制或自动排列。
- 订单数量表示完整产品套数。确认任务会按 `product_set_index × source_plate_index` 展开物理盘任务，并把源文件版本、源盘总数和盘/套编号保存到快照。
- 真实切片按 `source_plate_index` 选择源盘；切换打印机只改变目标打印机身份，不修改源文件的方向、支撑、填充、局部参数和固定布局。
- 回归验证：多盘产品文件、订单展开和阶段 9/10 切片测试共 `40 passed`；前端构建、Ruff、`git diff --check` 通过；后台已重启并确认 `/openapi.json` 返回 200。
- 当前未实现真实打印机连接、打印发送或跨源盘完成回写；这些仍受阶段 14 边界保护。

## 产品级多盘设置修订（2026-07-20）

- 多盘分类已上移到产品字段 `production_mode=multi_plate` 和 `source_plate_count`，不再由单个产品文件决定。
- 上传多盘产品源文件时，界面按源盘数量生成多个上传位置；每个位置对应一个独立 3MF，后端用 `source_set_id/source_plate_index` 组成一套。
- 订单只允许使用完整源文件组，并在快照中保存整组文件 ID；真实/模拟切片按源盘索引选对应文件，单盘和自动摆盘产品不受影响。
