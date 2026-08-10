# 阶段 12 交接：直供耗材扫码绑定

日期：2026-08-10

分支：codex/feature-stage12-direct-consumable-scan

## 已完成

- 新增独立 production_printer_consumables 表，真实打印机和虚拟打印机共用同一绑定契约。
- 每台目标最多一条有效直供耗材；新扫码自动失效旧记录，旧记录保留替换时间用于审计。
- operation_id 幂等；重复扫码请求不会重复建档或重复替换。
- 扫码后同步目标的 loaded_filaments 快照，使用外置直供槽位 254；不修改 AMS 槽位。
- 生产能力匹配继续以材料和颜色为准；颜色不匹配时不会被分配。
- 新增页面 /printer-consumables，用于软件扫码测试和查看当前直供耗材。
- 没有连接 MQTT、FTP、打印代理或任何真实设备；第 14 阶段前的发送保护保持不变。

## 接口

- GET /api/v1/production/printer-consumables/targets
- GET /api/v1/production/printer-consumables
- POST /api/v1/production/printer-consumables/scan

扫码请求必须提供 operation_id、scan_code、material、color_hex，并且只能选择 printer_id 或 virtual_printer_id 其中一个。

## 验证结果

- 阶段 12 后端：4 passed。
- 后端 Ruff：通过。
- 前端构建：通过。
- 前端 lint：通过。

## 人工验收

1. 打开 http://127.0.0.1:8019/printer-consumables。
2. 选择“阶段 11 虚拟打印机”或其他软件测试打印机。
3. 扫描 TAG-RED-001，材料填 PLA，颜色填红色。
4. 再扫描 TAG-BLUE-002，确认列表只显示蓝色新记录，并提示旧耗材已替换。
5. 用需要红色的生产源文件确认任务，任务应因颜色不匹配而等待。
6. 扫回红色耗材后，任务恢复匹配。

## 测试数据边界

现有虚拟打印机和演示产品只存在于本机被 .gitignore 忽略的运行数据库中，不会被提交、打包或写入全新安装数据库。正式安装包只包含功能代码和空白数据库初始化。

## 下一步

阶段 13 再接真实打印机状态读取适配器和心跳/离线状态；阶段 14 才允许单台真实打印机受控发送。
