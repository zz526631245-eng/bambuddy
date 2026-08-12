# 阶段 16 交接：生产中心订单工作台

## 分支与范围

- 分支：`codex/production-center-workspace`
- 目标：把生产中心整理为深色桌面工作台，并补齐订单批次、交期、优先级、历史和审计能力。
- 保留：现有切片缓存、真实切片/打印队列、打印机状态、耗材绑定和料盘清理链路；本阶段没有新建打印通信通道。

## 已完成

- 后端订单列表支持 active/history 视图、产品/订单搜索、创建日期范围、逾期状态、进度字段和优先级文字标签。
- 同产品、同源文件快照、同明确交期的未完成订单自动合并；追加数量和重新排期均有幂等操作日志。
- 订单明细新增目标/完成/打印中/待质检/待清板/剩余摘要，支持追加数量与交期/优先级重排。
- 删除订单：未开始订单物理删除；已开始订单软删除并保留生产、质检、清板、耗材审计，不发送停止打印命令；分配器排除软删除订单。
- 生产中心页面内切换交付总览、排产队列、打印机安排、历史订单和切片库；产品选择器支持名称/SKU 搜索，历史订单支持日期筛选。
- `production_orders.deleted_at` 与 `completed_at` 通过 Stage 16 可重复迁移加入。

## 验证

- `pytest -q backend/tests/integration/test_stage8_production_orders.py backend/tests/integration/test_production_order_controls.py backend/tests/integration/test_stage9_production_allocation.py`：18 passed。
- `npm.cmd --prefix frontend run test -- --run src/__tests__/pages/Stage8ProductionOrders.test.tsx`：7 passed。
- `npm.cmd --prefix frontend run build`：通过。
- 尚未构建安装包；需在用户确认 UI 后再进行真实打印人工验收。

## 下一步

1. 运行服务并用明确相同交期创建两笔同产品订单，确认后端合并为一个订单号。
2. 创建不同交期订单，确认它们保持独立；将交期设为过去时间，确认工作台显示逾期并可重新排期。
3. 对已开始的订单执行删除，确认打印不会被停止，订单从当前视图移入历史视图。
4. 如需调整筛选入口或卡片密度，优先修改 `frontend/src/pages/ProductionOrdersPage.tsx`，不要在前端自行计算订单数量。

## 风险

- 未填写交期的旧订单不会自动合并，避免把没有明确交付批次的历史数据错误合并；新生产流程建议要求填写交期。
- 产品名/SKU 在订单快照中搜索，若历史数据快照缺失只能按订单号/产品 ID 搜索。
- 真实打印机仍按阶段 14 的现有发送保护运行，本阶段没有扩大真实打印权限。

## 产品维度看板修正（2026-08-12）

- 生产中心当前主视图按产品聚合，不再按订单批次逐行显示打印数量。
- `/api/v1/production/product-workbench` 只汇总未完成产品，数量由后端统一计算；产品行可展开查看具体批次。
- `product-summaries` 旧接口保持原响应结构，兼容既有调用方。
- 新增回归覆盖：19 个后端定向测试、32 个前端定向测试，Ruff/Lint/Build 均通过。

## 菜单和产品库视觉修正（2026-08-12）

- 移除了“低频菜单自动隐藏”判断，恢复完整主菜单文字入口；权限和用户自己设置的隐藏项不变。
- 产品库根容器改为 `max-w-[1500px]`，与生产中心工作台保持相同桌面宽度。
