# 阶段 10 交接测试报告

## 已执行命令

```powershell
python -m pytest backend/tests/integration/test_production_order_controls.py -q
python -m pytest backend/tests/integration/test_stage8_production_orders.py backend/tests/integration/test_stage9_production_allocation.py backend/tests/integration/test_stage9_product_files.py backend/tests/integration/test_product_size_routing.py -q
Set-Location frontend
npm.cmd test -- --run src/__tests__/pages/Stage8ProductionOrders.test.tsx
npm.cmd run build
npm.cmd run lint
```

## 结果

- 订单/盘任务控制测试：`2 passed`。
- 阶段 8/9/尺寸路由/产品文件回归：`30 passed`。
- 前端订单测试：`6 passed`。
- 前端构建、lint：通过。
- 后端 Ruff、`git diff --check`：通过。

## 运行状态

- 后端：`http://127.0.0.1:8019`。
- OpenAPI：HTTP 200。
- 生产订单列表：空数组。
- 没有真实打印机连接和打印发送。
