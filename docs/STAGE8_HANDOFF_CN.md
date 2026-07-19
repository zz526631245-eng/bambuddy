# 阶段 8 交接说明

## 目标和边界

生产订单能根据产品零件清单生成需求和任务草稿，但不自动分配打印机、不进入原打印队列、不发送打印。

## 实际实现

- `backend/app/services/production_order_service.py`：订单创建、快照、状态变更、任务预览/确认、重复请求重放。
- `backend/app/services/production_accounting.py`：数量账本和订单状态转换规则。
- `backend/app/models/production.py`：订单与需求快照、零件和单套数量字段。
- `backend/app/core/database.py`：阶段 8 的 SQLite/PostgreSQL 兼容升级。
- `backend/app/api/routes/production.py`：订单详情、修改、状态、预览和确认接口。
- `frontend/src/pages/ProductionOrdersPage.tsx`：生产订单列表和创建。
- `frontend/src/pages/ProductionOrderDetailPage.tsx`：进度、预览、暂停/恢复/取消和时间线。
- `frontend/src/pages/ProductDetailPage.tsx`：为产品零件建立打印方案。

## 关键业务规则

1. 每个产品零件必须有一个启用的打印方案，才能创建订单。
2. 需求数量 = 订单套数 × 产品中该零件的每套数量。
3. 订单创建后只读快照不随产品主数据变化。
4. 计划数 = 已安排 + 合格 + 剩余；报废单独累计。
5. 确认草稿只创建 `PlateJob(status=draft)`，`queue_item_id` 为空。
6. 订单套数必须至少为 1；取消订单使用独立取消权限和独立接口。

## 2026-07-19 验收修复

- 分支：`codex/fix-stage8-acceptance`
- 代码提交：`1591a2c2`
- 并发确认草稿在 PostgreSQL 上锁定订单；两个不同操作编号同时确认时，任务总量不超过需求且账本与任务一致。
- 产品包往返保留打印方案对应的零件编号，导入后的产品仍可继续创建生产订单。
- 产品图片和产品包导出改为携带当前登录认证信息的请求，修复启用登录后的访问失败。
- 阶段 7/8 后端定向测试 46 项通过；PostgreSQL 16 测试 8 项通过；前端相关定向测试 6 项通过；构建、代码规范和多语言一致性通过。
- 前端全量 2306 项中 2305 项通过；唯一失败仍是中文 Windows 的原版 `PM/下午` 区域设置差异。
- 未连接打印机、未创建打印队列项、未发送打印；没有开始阶段 9。

## 接手者第一条提示词

```text
你正在接手 Bambuddy 二次开发。先只读完整阅读仓库根目录 AGENTS.md，以及 docs/PROJECT_OVERVIEW_CN.md、ARCHITECTURE_DECISIONS_CN.md、DEVELOPMENT_RULES_CN.md、TESTING_GUIDE_CN.md、ROADMAP_CN.md、CURRENT_STATUS_CN.md、STAGE8_HANDOFF_CN.md。然后检查 git status、当前分支和最近 5 个提交。先不要修改文件、安装依赖、连接打印机或发送打印。请复核阶段 8 的实现和测试记录，列出你对项目目标、不可突破边界、当前完成度和下一步的理解，等我确认后再行动。
```

## 下一位开发者必须先做

1. 拉取 `codex/fix-stage8-acceptance`，确认包含 `1591a2c2` 以及后续文档提交。
2. 查看 GitHub Actions 是否全绿；失败时只修与本分支有关的问题。
3. 按 `docs/TESTING_GUIDE_CN.md` 重跑阶段 8 和阶段 7 回归。
4. 人工测试创建订单、快照不变、数量守恒、草稿确认和暂停/取消。
5. 验收通过后更新 `CURRENT_STATUS_CN.md`，再决定合并或进入阶段 9。

## 禁止事项

- 不把草稿直接写入打印队列。
- 不在前端自行计算并回写数量。
- 不连接真实打印机测试阶段 8。
- 不跳过 PostgreSQL 并发和迁移测试。
- 不把阶段 9 自动调度混入阶段 8 修复提交。
