# 阶段 10：真实切片文件元数据修复交接

日期：2026-07-20

## 本次修复

真实切片服务已经生成完整 G-code，但输出 3MF 的 `Metadata/slice_info.config` 中原先没有绑定目标打印机型号。Bambu Studio 因此把文件当成可编辑工程，要求再次切片。

现在切片结果落盘前会根据被分配的虚拟打印机补写 `printer_model_id`（A1 使用 `N2S`），只修改这一项元数据；模型、支撑、摆盘坐标、打印参数和 G-code 内容不改。切片指纹已升级，旧的无型号缓存不会复用。

## 本次验收

- 创建测试产品 3，上传桌面 `333.3mf`。
- 创建生产订单，数量 3。
- 自动分配到虚拟 A1，真实切片结果为 1 盘、3 个产品。
- 输出：`C:\Users\zz\Desktop\333.plate-1.qty-3.gcode.3mf`。
- 包内只有 `Metadata/plate_1.gcode` 作为打印盘 G-code，G-code 共 233 层。
- `slice_info.config` 已写入 `printer_model_id="N2S"`。
- 未连接真实打印机，未发送 MQTT、FTP 或打印指令。

## 自动化验证

`backend/tests/unit/test_stage10_real_slicing.py` 与 `backend/tests/integration/test_stage10_slicing.py`：15 passed；相关 Ruff 检查通过。

## 用户验收方式

在 Bambu Studio 打开上述文件，确认进入已切片的预览/发送流程，不再出现要求重新切片的 Prepare 状态。若仍要求切片，应保留提示截图并停止发送。

## 后续修复

仅写入 `printer_model_id` 不足以让 Bambu Studio 进入发送流程。现在输出包还会移除 `3D/Objects/*`、3D build item 以及 `model_settings.config` 中的对象/装配记录，仅保留打印盘与 G-code 关联。这样输出包与 Bambu Studio 正常导出的发送用 G-code 3MF 结构一致。
