# Bambuddy 二次开发协作说明

## 开始任何任务前

1. 先阅读 `docs/PROJECT_OVERVIEW_CN.md`、`docs/ARCHITECTURE_DECISIONS_CN.md`、`docs/DEVELOPMENT_RULES_CN.md`、`docs/TESTING_GUIDE_CN.md`、`docs/ROADMAP_CN.md`、`docs/CURRENT_STATUS_CN.md`。
2. 如果处理阶段 8，再阅读 `docs/STAGE8_HANDOFF_CN.md`。
3. 先执行 `git status --short` 和 `git branch --show-current`。不得覆盖用户未提交的修改。
4. 开始新阶段时从当前已验收分支创建独立功能分支。

## 不可突破的边界

- 阶段 14 前不连接真实打印机，不发送打印，不自动选择打印机。
- 复用 Bambuddy 现有打印队列、打印通信、库存、虚拟打印机和切片流水线，不另造一套。
- 生产业务通过独立模型、服务和外键连接原模块，避免改变原功能语义。
- 数量只在后端服务中计算；前端只显示结果，不能计算后写回。
- 数据库只能用可重复执行的迁移升级，禁止手工删表修复。
- 先写测试，再实现；一个阶段拆成小提交。测试失败时不发布 EXE。
- 不提交密码、打印机访问码、VPN 配置、正式数据库或用户隐私数据。

## 完成任务时

1. 运行本阶段测试和相关旧功能回归，记录真实结果。
2. 更新 `docs/CURRENT_STATUS_CN.md`；改变架构才更新架构决策，改变长期范围才更新路线图。
3. 为下一位维护者更新本阶段交接文档；写清分支、提交、已完成、未完成、测试、风险和下一步。
4. 提交前运行 `git diff --check`，提交后确认 `git status --short` 为空。
5. 只有 GitHub Actions 全绿的已测试标签才允许构建对外安装包。

