# 测试指南

所有命令从仓库根目录 `D:\Bambuddy\bambuddy-friend-src` 执行，除非命令前明确切换目录。

## 阶段 9 自动分配定向测试

```powershell
python -m pytest backend/tests/integration/test_stage9_production_allocation.py -q
```

预期：5 项通过，覆盖确认后自动分配、队列安全暂停、并发不重复、取消释放、重启恢复和兼容方案回退。

## 阶段 11 虚拟质检闭环

```powershell
python -m pytest backend/tests/integration/test_stage11_quality_loop.py -q
```

预期：6 项通过，覆盖六阶段虚拟状态流转、部分成功、全部失败、幂等质检、执行历史保护、清板后释放虚拟打印机、多盘整套结算和失败补产套次编号。

前端人工操作定向测试：

```powershell
Set-Location frontend
npm.cmd test -- --run src/__tests__/pages/Stage8ProductionOrders.test.tsx
```

预期：7 项通过。

## 阶段 12 直供耗材扫码

```powershell
python -m pytest backend/tests/integration/test_stage12_direct_consumable_scan.py -q
```

预期：4 项通过，覆盖真实/虚拟目标、首次扫码、重复操作幂等、重新扫码自动替换和颜色不匹配。

耗材卷库定向测试：

```powershell
python -m pytest backend/tests/integration/test_stage12_consumable_library.py -q
```

预期：2 项通过，覆盖批量唯一编码、扫码入库幂等、库存统计、绑定后扫码耗尽和自动释放打印机。

人工验收入口：http://127.0.0.1:8019/printer-consumables

1. 选择软件测试打印机，录入扫码码、材料和颜色，点击“确认扫码登记”。
2. 再录入另一条扫码码；当前列表只保留新耗材，并提示旧耗材已自动替换。
3. 访问生产订单确认任务，颜色要求与当前直供耗材一致时才会匹配；颜色不一致时任务保持等待。
4. AMS 槽位不参与该页面，也不会被清除。
5. 该页面是扫码器协议的本地软件测试入口，阶段 14 前不会连接真实打印机或发送打印。
6. 在“材料类型”中创建材料；每个材料卡片会显示二维码并提供 SVG 下载。手机系统相机扫描后会打开直供耗材页面并自动填入编码、材料和颜色。
7. 网页摄像头按钮需要 HTTPS 或 localhost；普通局域网 HTTP 页面被浏览器拒绝摄像头权限时属于浏览器安全限制，不是后端扫码接口故障。

手机 HTTPS 测试：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_stage12_https.ps1
```

然后用手机访问 `https://电脑局域网IP:8019/consumable-library`。开发证书只用于私有测试网络，手机需要接受/安装该证书；正式安装包不能使用该开发私钥。

## 阶段 8 后端定向测试

```powershell
python -m pytest backend/tests/unit/test_production_accounting.py backend/tests/unit/test_production_models.py backend/tests/unit/test_production_migrations.py backend/tests/integration/test_production_api.py backend/tests/integration/test_stage7_master_data.py backend/tests/integration/test_stage8_production_orders.py -q
```

预期：45 项通过。

## PostgreSQL 16

设置 `TEST_POSTGRES_URL` 指向专用测试库后运行：

```powershell
python -m pytest backend/tests/postgres/ -v --tb=short
```

预期：8 项通过，包括旧库升级、并发重复创建和阶段 9 并发分配不重复。

## 后端代码规范

```powershell
python -m ruff check backend/app backend/tests
```

## 前端

```powershell
Set-Location frontend
npm.cmd run build
npm.cmd run lint -- --quiet
npm.cmd run test:run
```

本机中文 Windows 上，原版 `date.test.ts` 可能因返回“下午”而不是英文 `PM` 失败；这是区域设置差异。不能把它算作阶段 8 失败，最终以 GitHub Actions 英文 Linux 环境为准。

## 当前本机全量后端已知限制

当前 Python 3.13 环境收集原版全量测试时存在两个非阶段 8 问题：本机 `pyftpdlib` 缺少 `TLS_FTPHandler`，以及一个 SpoolBuddy 配置按 Windows GBK 读取失败。不要为阶段 8 擅自升级依赖；GitHub Actions 会在仓库规定的 Python/Linux 环境运行全量测试。

## 阶段 8 人工验收

1. 建产品和零件清单。
2. 为清单中的每个零件建立打印方案。
3. 创建生产订单，核对需求数等于“每套数量 × 订单套数”。
4. 修改产品零件清单，确认旧订单数字不变。
5. 预览并确认任务草稿，确认页面明确显示未选择打印机。
6. 重复点击或重发同一操作编号，确认不生成重复记录。
7. 暂停、恢复、取消订单，确认操作时间线完整。

## 阶段 9 人工验收

1. 只使用测试数据和未连接真实设备的打印机记录，启用对应生产配置。
2. 创建生产订单并确认任务，确认页面立即显示“已自动分配”，且任务关联一个现有打印队列项。
3. 在打印队列确认该任务标记为阶段 9 模拟任务，且没有启动、编辑或取消按钮。
4. 用接口尝试启动该生产队列项，应收到拒绝响应；确认没有 MQTT、FTP 或打印通信。
5. 制造无匹配打印机的任务，确认它保持等待；补充兼容配置后，确认恢复循环能够自动分配。
6. 取消订单，确认其待处理队列项被取消，释放的打印机可供另一个等待任务分配。
7. 并发确认或运行两个分配器，确认同一任务只有一个队列项，同一打印机不会同时分配两个待处理生产任务。
## 自动登记与 ZXing 扫码兼容验证

1. 使用手机可访问的 HTTPS 地址打开 /consumable-library，不要在 127.0.0.1 页面生成手机标签；如需固定地址，配置 VITE_PUBLIC_BASE_URL。
2. 扫描打印机二维码打开 /printer-consumables?printer=...，确认目标打印机已经自动锁定。
3. 点击网页摄像头扫码，使用耗材卷二维码；ZXing 会在不支持原生 BarcodeDetector 的浏览器中完成识别。
4. 识别成功后，页面按耗材卷 unit_code 填入材料和颜色并显示待确认状态；点击“确认登记”后才写入服务器。
5. 重复扫描同一操作不会重复创建绑定；扫描新耗材会自动替换旧直供耗材。
