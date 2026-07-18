# 测试指南

所有命令从仓库根目录 `D:\Bambuddy\bambuddy-src` 执行，除非命令前明确切换目录。

## 阶段 8 后端定向测试

```powershell
python -m pytest backend/tests/unit/test_production_accounting.py backend/tests/unit/test_production_models.py backend/tests/unit/test_production_migrations.py backend/tests/integration/test_production_api.py backend/tests/integration/test_stage7_master_data.py backend/tests/integration/test_stage8_production_orders.py -q
```

预期：44 项通过。

## PostgreSQL 16

设置 `TEST_POSTGRES_URL` 指向专用测试库后运行：

```powershell
python -m pytest backend/tests/postgres/ -v --tb=short
```

预期：7 项通过，包括旧库升级和并发重复创建。

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

## 人工验收

1. 建产品和零件清单。
2. 为清单中的每个零件建立打印方案。
3. 创建生产订单，核对需求数等于“每套数量 × 订单套数”。
4. 修改产品零件清单，确认旧订单数字不变。
5. 预览并确认任务草稿，确认页面明确显示未选择打印机。
6. 重复点击或重发同一操作编号，确认不生成重复记录。
7. 暂停、恢复、取消订单，确认操作时间线完整。

