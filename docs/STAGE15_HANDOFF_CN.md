# 阶段 15 交接：耗材消耗与成本统计

## 分支

`codex/consumable-cost-tracking`

## 已完成

- 二维码批量打印改为批次 PDF：一次生成的所有耗材卷只对应一个下载记录，记录按生成时间倒序显示；PDF 每页物理尺寸为 40mm × 40mm，按卷顺序排列，适配连续标签打印机。
- 新增二维码批次历史与 PDF 下载接口；批次记录同时显示总张数和已入库张数，便于核对打印和入库进度。
- 库存接口和耗材库页面默认排除未扫码入库的 `generated` 卷；只有扫描“入库”后才出现在库存分组和已入库数量中。为兼容旧客户端，后端仍支持显式 `include_pending=true` 查询。
- `production_consumable_units` 增加每卷初始净重 `initial_weight_g` 和单卷价格 `unit_price`，批量生成二维码时从材料类型页面录入。
- 新增 `production_consumable_usage` 消耗事件表，使用 `operation_id` 做幂等保护。
- 真实打印完成回调会复用已有归档/切片耗材克数，按照当前打印机的直供耗材绑定自动记录消耗；同时扣减剩余克重、计算按卷比例的材料成本，剩余为零时自动标记耗尽并释放绑定。
- 新增 `/api/v1/production/consumable-library/consumption-summary`，支持 `period=1d|3d|7d|30d|3m|6m|1y`，也支持 `start_date` 与 `end_date` 自定义范围。
- 耗材库页面增加消耗克数、估算成本、按品牌/材料/颜色分组和事件明细。
- 没有可靠克数来源时不写入虚假记录；旧耗材卷可继续入库和绑定，但成本统计显示为零，直到新建带克重/价格的卷。

## 测试

- `pytest -q backend/tests/integration/test_stage12_consumable_library.py`：3 passed。
- `pytest -q backend/tests/integration/test_stage12_consumable_library.py backend/tests/integration/test_stage12_direct_consumable_scan.py`：11 passed（含批次 PDF、40mm 页面尺寸和未入库过滤）。
- `pytest -q backend/tests/integration/test_stage12_direct_consumable_scan.py backend/tests/unit/test_production_migrations.py`：14 passed。
- `npm.cmd run lint`：通过；`npm.cmd run build`：通过。
- 前端全量 `npm.cmd run test:run` 有 6 个既有环境/基线失败（德语 locale 缺 4 个键、中文 Windows 的 PM 格式、Stage 7/AMS 页面异步断言），与本次二维码改动无关。

## 风险与下一步

- 需要在真实打印机上完成一次“有直供耗材绑定 + 切片产物包含 filament_used_g + 打印完成”的人工验收，并检查耗材库剩余克重、成本和日期筛选。
- 失败/取消打印暂不自动扣减，因为当前回调不保证能提供可靠的部分耗材用量；如后续适配器能提供实际克数，可扩展 `source` 和记录入口。
- 本阶段没有生成安装包，也没有改变虚拟打印机测试链路。
- 8019 已用 HTTPS 重启，当前页面静态资源和后端批次 PDF 接口均为本次版本；未连接或发送真实打印任务。
