# 阶段 15 交接：耗材消耗与成本统计

## 分支

`codex/consumable-cost-tracking`

## 已完成

- `production_consumable_units` 增加每卷初始净重 `initial_weight_g` 和单卷价格 `unit_price`，批量生成二维码时从材料类型页面录入。
- 新增 `production_consumable_usage` 消耗事件表，使用 `operation_id` 做幂等保护。
- 真实打印完成回调会复用已有归档/切片耗材克数，按照当前打印机的直供耗材绑定自动记录消耗；同时扣减剩余克重、计算按卷比例的材料成本，剩余为零时自动标记耗尽并释放绑定。
- 新增 `/api/v1/production/consumable-library/consumption-summary`，支持 `period=1d|3d|7d|30d|3m|6m|1y`，也支持 `start_date` 与 `end_date` 自定义范围。
- 耗材库页面增加消耗克数、估算成本、按品牌/材料/颜色分组和事件明细。
- 没有可靠克数来源时不写入虚假记录；旧耗材卷可继续入库和绑定，但成本统计显示为零，直到新建带克重/价格的卷。

## 测试

- `pytest -q backend/tests/integration/test_stage12_consumable_library.py`：3 passed。
- `pytest -q backend/tests/integration/test_stage12_direct_consumable_scan.py backend/tests/unit/test_production_migrations.py`：14 passed。
- `npm.cmd run build`：通过。

## 风险与下一步

- 需要在真实打印机上完成一次“有直供耗材绑定 + 切片产物包含 filament_used_g + 打印完成”的人工验收，并检查耗材库剩余克重、成本和日期筛选。
- 失败/取消打印暂不自动扣减，因为当前回调不保证能提供可靠的部分耗材用量；如后续适配器能提供实际克数，可扩展 `source` 和记录入口。
- 本阶段没有生成安装包，也没有改变虚拟打印机测试链路。
