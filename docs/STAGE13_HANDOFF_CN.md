# 阶段 13 交接：打印机状态心跳与故障重排

日期：2026-08-10

分支：`codex/feature-stage13-printer-status`

## 已完成

- 新增 `production_printer_status` 独立状态快照表，实体打印机和虚拟打印机使用同一 `target_type + target_id` 契约。
- 新增 `GET /api/v1/production/printer-status`，返回当前状态、有效状态、最后心跳、超时秒数、故障说明、耗材快照和是否可参与分配。
- 新增 `POST /api/v1/production/printer-status/heartbeat`，使用 `operation_id` 幂等记录模拟/未来适配器心跳。
- 默认心跳超时为 30 秒；过期心跳自动显示为离线。
- 离线、故障、维修中的目标不会被新的生产自动分配选中。
- 尚未开始的已分配盘任务在目标不可用后回到草稿/待分配；实体队列项会先标记取消并保留原因；正在打印的任务不被后台改写。
- 新增 `/production-printer-status` 页面，可每 3 秒查看状态并发送模拟心跳，明确提示当前不连接真实打印机、不发送打印。

## 验证结果

- 阶段 13 定向测试：2 passed。
- 阶段 9、阶段 12 相关回归：15 passed。
- Ruff、前端 build、前端 lint：通过。
- HTTPS 服务器已重启，`GET /api/v1/production/printer-status` 返回 200。

## 边界与下一步

- 当前 `source=stage13_simulation` 是虚拟测试入口；`source=adapter` 只定义数据契约，不会自动连接设备。
- 真实打印机 MQTT/FTP 状态读取、真实状态回写和受控发送仍必须等阶段 14 单机验收，不得把真实访问码或设备配置提交到仓库。
