# 朋友接手时从这里开始

## 你正在使用的独立目录

`D:\Bambuddy\bambuddy-friend-src`

这个目录只给朋友和朋友自己的 Codex 使用。原目录 `D:\Bambuddy\bambuddy-src` 由项目所有者当前的 Codex 使用。双方不能直接复制文件互相覆盖，只通过 GitHub 分支和提交交接。

## 创建 Codex 新任务

1. 打开朋友自己的 Codex。
2. 创建新任务。
3. 工作文件夹必须选择 `D:\Bambuddy\bambuddy-friend-src`。
4. 把下面的“第一条提示词”完整发送给 Codex。

## 第一条提示词

```text
你正在接手我的 Bambuddy 二次开发项目。

当前项目文件夹是：
D:\Bambuddy\bambuddy-friend-src

开始前请完整阅读：
1. AGENTS.md
2. docs/FRIEND_START_HERE_CN.md
3. docs/PROJECT_OVERVIEW_CN.md
4. docs/ARCHITECTURE_DECISIONS_CN.md
5. docs/DEVELOPMENT_RULES_CN.md
6. docs/TESTING_GUIDE_CN.md
7. docs/ROADMAP_CN.md
8. docs/CURRENT_STATUS_CN.md
9. docs/STAGE8_HANDOFF_CN.md

然后只执行只读检查：
git status --short
git branch --show-current
git log --oneline -7
git remote -v

第一步禁止修改文件、安装或升级依赖、连接打印机、发送打印、合并分支、打标签或构建发布安装包。

请先用浅显中文告诉我：
1. 你对项目最终目标的理解；
2. 当前已经完成到哪个阶段；
3. 哪些原版 Bambuddy 模块禁止重做；
4. 阶段 8 的安全边界；
5. 当前分支、最新提交和工作区是否正确；
6. 当前测试和 GitHub CI 结果；
7. 下一步建议；
8. 是否发现交接信息不一致。

等我明确确认后，你才能修改代码。
```

## 正确检查结果

- 当前分支应为 `feature/production-stage8-orders`。
- 工作区应当干净，`git status --short` 不应有输出。
- 提交历史中应包含阶段 8 后端、前端、权限修正和交接文档。
- `origin` 应指向 `https://github.com/zz526631245-eng/bambuddy.git`。
- 阶段 8 只能生成未分配打印机的任务草稿，不能发送打印。
- 不重做打印队列、打印通信、库存、虚拟打印机和切片流水线。

任何一项不一致时，先停止修改，让项目所有者处理目录或 Git 同步问题。

## 开始下一项开发任务前

项目所有者需要明确告诉朋友：任务属于哪个阶段、允许修改什么、禁止修改什么、验收条件是什么。朋友的 Codex 应先从当前已验收分支创建新的功能分支，不直接在阶段 8 分支上混入下一阶段的大功能。

## 完成任务后的固定交接

1. 运行新功能测试和旧功能回归。
2. 更新 `docs/CURRENT_STATUS_CN.md` 和对应阶段交接文档。
3. 提交到朋友自己的功能分支并推送 GitHub。
4. 提供分支名、提交号、CI 链接、测试结果、已知问题和人工测试步骤。
5. 项目所有者的 Codex 通过 GitHub 拉取或审查提交，禁止用资源管理器覆盖源码。
