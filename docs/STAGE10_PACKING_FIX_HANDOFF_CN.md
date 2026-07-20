# 阶段 10 摆盘修复交接

日期：2026-07-20

## 本次完成

- 自动摆盘不再只使用矩形长宽网格；新增 3MF 的 XY 投影轮廓和凸包碰撞检查。
- 允许自动摆盘写入绕 Z 轴旋转，同时保留原始 Z 高度、模型方向和嵌入式打印参数。
- 明确写入每个 build item 的 XY 坐标后关闭切片器二次自动摆盘，避免切片器把已经验证的布局重新拆盘。
- 真实切片返回结果会检查实际 `Metadata/plate_N.gcode` 数量；多盘结果不会再被标记为一盘成功。
- G-code 校验只统计真实层内的挤出刀路，排除清料、擦嘴和结束移动造成的板外坐标误报；支撑刀路也包含在真实刀路检查中。

## 真实验证

- 桌面 `111.3mf`（无支撑）：真实切片成功，1 盘 6 套，输出只有 `Metadata/plate_1.gcode`。
- 桌面 `222.3mf`（带支撑）：真实切片成功，1 盘 3 套，输出只有 `Metadata/plate_1.gcode`，且 G-code 含支撑相关刀路。
- 可检查文件：桌面 `111.plate-1.qty-6.gcode.3mf`、`222.plate-1.qty-3.gcode.3mf`。
- 没有连接真实打印机，没有发送 MQTT、FTP 或打印指令。

## 测试

- `backend/tests/unit/test_stage10_real_slicing.py` 与 `backend/tests/integration/test_stage10_slicing.py`：14 passed。
- `git diff --check`：通过。

## 后续风险

当前投影使用纯 Python 凸包，属于保守的几何外轮廓；产品源文件若要把组合对象中的小零件独立塞入环形空隙，还需要在产品文件模型中明确组件可独立移动，并继续增加组件级碰撞测试。支撑、Brim、Raft 的最终占用仍以真实切片刀路为准。
