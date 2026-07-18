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

## 接手者第一条提示词

```text
你正在接手 Bambuddy 二次开发。先只读完整阅读仓库根目录 AGENTS.md，以及 docs/PROJECT_OVERVIEW_CN.md、ARCHITECTURE_DECISIONS_CN.md、DEVELOPMENT_RULES_CN.md、TESTING_GUIDE_CN.md、ROADMAP_CN.md、CURRENT_STATUS_CN.md、STAGE8_HANDOFF_CN.md。然后检查 git status、当前分支和最近 5 个提交。先不要修改文件、安装依赖、连接打印机或发送打印。请复核阶段 8 的实现和测试记录，列出你对项目目标、不可突破边界、当前完成度和下一步的理解，等我确认后再行动。
```

## 下一位开发者必须先做

1. 拉取 `feature/production-stage8-orders`，确认包含 `82145a48` 和 `95a81b2b` 以及后续文档提交。
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

