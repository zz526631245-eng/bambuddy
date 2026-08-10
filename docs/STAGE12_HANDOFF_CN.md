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
- 直供耗材页面增加浏览器摄像头二维码入口；手机通过普通 HTTP 时浏览器可能拒绝摄像头权限，提供扫码枪/手动输入和原生相机打开二维码链接的降级路径。
- 材料类型页面创建后显示对应二维码并支持下载 SVG；二维码包含材料编码、材料和颜色，并可打开直供耗材登记页自动填充。
- 新增耗材卷库：批量生成唯一 unit_code 和二维码、扫码入库、扫码耗尽/报废、库存状态统计；耗尽会自动释放对应打印机直供绑定。
- 新增 scripts/start_stage12_https.ps1 和 scripts/generate_dev_https_cert.py，用于手机摄像头安全上下文测试；开发证书写入 data/dev_https，不提交、不进入安装包。
- 没有连接 MQTT、FTP、打印代理或任何真实设备；第 14 阶段前的发送保护保持不变。

## 接口

- GET /api/v1/production/printer-consumables/targets
- GET /api/v1/production/printer-consumables
- POST /api/v1/production/printer-consumables/scan

扫码请求必须提供 operation_id、scan_code、material、color_hex，并且只能选择 printer_id 或 virtual_printer_id 其中一个。

## 验证结果

- 阶段 12 后端：4 passed。
- 耗材库后端：2 passed。
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
7. 打开耗材库，选择材料类型生成 3 个唯一二维码；下载/打印标签后，用扫码入库动作入库，再用扫码耗尽动作确认库存减少并释放绑定。
8. 用 scripts/start_stage12_https.ps1 启动 HTTPS，手机在同一 Wi-Fi 下访问 HTTPS 地址，测试网页摄像头按钮。

手机摄像头说明：浏览器网页摄像头通常只允许 HTTPS（localhost 例外）。局域网 HTTP 地址打不开摄像头时，用手机系统相机扫描材料二维码，打开二维码中的登记链接，再选择打印机确认提交；或者使用扫码枪/手动输入。

## 测试数据边界

现有虚拟打印机和演示产品只存在于本机被 .gitignore 忽略的运行数据库中，不会被提交、打包或写入全新安装数据库。正式安装包只包含功能代码和空白数据库初始化。

## 下一步

阶段 13 再接真实打印机状态读取适配器和心跳/离线状态；阶段 14 才允许单台真实打印机受控发送。

## 自动登记与扫码兼容补充

- 扫描已入库的耗材卷二维码后，后端按 `unit_code` 自动读取材料类型、颜色和耗材卷身份；只要打印机目标已锁定，扫描成功就立即登记直供绑定，不再要求手动点击确认。
- `operation_id` 仍然幂等，重复识别不会重复创建绑定；旧直供耗材继续自动失效并保留审计记录。
- 网页扫码改用 `@zxing/browser`，不再只依赖浏览器实验性的 `BarcodeDetector`，覆盖 iOS Safari 和不支持原生识别器的移动浏览器。
- 二维码地址支持 `VITE_PUBLIC_BASE_URL`；不要在 `127.0.0.1` 页面生成给手机使用的二维码，应从手机可访问的 HTTPS 地址生成。
