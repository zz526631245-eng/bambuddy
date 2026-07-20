# Bambuddy 阶段 10 完成交接包

更新时间：2026-07-20  
当前分支：`codex/feature-stage10-real-slicing`

## 1. 项目目标

Bambuddy 的生产管理层以“产品 → 产品源 3MF → 生产订单 → 自动分配 → 摆盘/切片 → 后续受控打印”为主线。产品源文件保存打印所需的材料、颜色、摆盘策略、版本和多盘关系；订单必须基于活动产品源文件创建，不能回退到旧 BOM 生产。

## 2. 本轮已完成

- 阶段 9 产品源文件、版本失效、材料/颜色要求、虚拟打印机能力匹配和自动分配。
- 阶段 10 固定摆盘、自动摆盘、按目标数量拆分盘数、真实 Bambu Studio/OrcaSlicer sidecar 切片、切片缓存和切片库。
- 小产品使用模型轮廓/3MF 网格边界计算摆盘；允许围绕 Z 轴旋转；保留源文件 Z 高度、旋转矩阵、支撑、填充和局部参数。
- 大产品/多盘产品在产品层级配置源盘数量，每个源盘使用独立 3MF；不自动复制、不重新排列，订单数量表示完整产品套数。
- 真实切片结果保存为 `.gcode.3mf`，带 `plate-N.qty-M` 文件名、源文件指纹和输出文件关联，可在切片库下载和复用。
- 生产订单详情页可查看每个盘的切片/队列/打印机状态，取消单盘、删除未执行单盘、取消整单和删除整单。
- 新订单没有活动产品源文件时，后端拒绝创建，前端提示“请先上传产品源文件”并禁用创建按钮。
- 修复订单确认盘任务接口缺少返回值的问题。

## 3. 重要安全边界

- 阶段 14 前禁止连接真实打印机、MQTT、FTP、发送打印指令或自动启动真实队列。
- 虚拟打印机只用于能力、材料、颜色、尺寸和流程验证；它不是网络设备。
- 真实切片 sidecar 可以运行，但切片结果只进入文件库/切片库，不发送打印。
- 不要把打印机序列号、访问码、IP、数据库、用户图片或本地备份提交到 Git。

## 4. 当前本地数据状态

本轮已清理旧测试生产订单：15 条订单、15 条需求、15 条盘任务及订单日志。以下数据保留：

- 产品：9 条
- 产品源文件：10 条
- 切片产物：18 条
- 虚拟打印机：5 条
- 打印机配置：5 条
- 打印队列：0 条

清理前备份文件为仓库根目录的 `bambuddy.db.before-production-order-cleanup.bak`，该文件只在本机保留，禁止提交。

## 5. 关键入口

- `POST /api/v1/products/{product_id}/files`：上传产品源 3MF。
- `POST /api/v1/production/orders`：创建订单，必须提供活动源文件。
- `GET /api/v1/production/orders/{order_id}`：订单详情。
- `POST /api/v1/production/orders/{order_id}/plate-jobs/confirm`：确认并自动分配盘任务。
- `POST /api/v1/production/plate-jobs/{id}/real-slice`：真实 sidecar 切片，不发送打印。
- `POST /api/v1/production/plate-jobs/{id}/cancel`：取消单盘。
- `DELETE /api/v1/production/plate-jobs/{id}`：删除未执行单盘。
- `DELETE /api/v1/production/orders/{id}`：删除整张订单及其生产任务。
- `GET /api/v1/production/slice-artifacts`：切片库。
- `GET /api/v1/production/slice-artifacts/{id}/download`：下载切片结果。

## 6. 已验证结果

- 新增订单控制测试：2 项通过。
- 阶段 8/9/产品尺寸路由/产品文件回归：30 项通过。
- 前端订单测试：6 项通过。
- 前端 `npm.cmd run build`、`npm.cmd run lint`：通过。
- 后端 Ruff 和 `git diff --check`：通过。
- 后端重启后 `http://127.0.0.1:8019/openapi.json` 返回 200，订单列表返回 `[]`。

## 7. 接手规则

接手者先阅读本文件、`docs/CURRENT_STATUS_CN.md`、`docs/DEVELOPMENT_RULES_CN.md`、`docs/TESTING_GUIDE_CN.md` 和 `AGENTS.md`，再执行 `git status --short` 与 `git branch --show-current`。不要在当前分支直接继续开发；应从交接提交创建新的 `codex/` 功能分支，先写测试再改代码。
