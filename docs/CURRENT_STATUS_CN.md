# 当前开发状态

## Windows 小白安装与自动切片启动（2026-08-12）
- Windows 安装包现在内置 `slicer-api/docker-compose.yml`、`service/setup-slicer.ps1` 和可见的 `service/install-slicer.bat` 安装通道；主程序安装不再等待 Docker 或大体积镜像下载，避免进度条卡在 100%。
- 安装完成后从开始菜单运行“Install Docker and Slicer Services”，会在可见窗口显示 Docker、镜像下载和健康检查过程，失败后可以重复运行；仍会优先通过 winget 安装 Docker Desktop，失败时回退到 Docker 官方安装程序。
- 安装脚本会启动 Docker Desktop，使用 `docker compose --profile bambu up -d` 拉取并启动 OrcaSlicer（3003）与 BambuStudio（3001）sidecar，并轮询 `/health`；后端 Windows 服务显式使用 `SLICER_API_URL=http://127.0.0.1:3003` 与 `BAMBU_STUDIO_API_URL=http://127.0.0.1:3001`。
- Docker/WSL2 首次安装若要求重启，脚本会写入 `C:\ProgramData\Bambuddy\slicer\setup-status.txt` 并注册 RunOnce，用户重启登录后自动继续；开始菜单提供“Install Docker and Slicer Services”用于安全重试。切片容器停止但不删除镜像和数据。
- 本次仅改变安装与部署，不携带虚拟打印机或开发数据库；正式安装仍从空数据目录开始。完整 staging、PowerShell 脚本错误路径、compose 配置、前端构建、ESLint 和 Inno Setup 全流程已验证。
- 最新安装包：`installers/windows/build/output/bambuddy-0.2.4.9-windows-x64-setup.exe`，大小 197,087,381 字节，SHA-256：`48CAFA99B24AC6509534AB5148C4D663324B099C9F5B9C44834BDABE252551E1`。

## 打印机详情二维码与手机扫码刷新（2026-08-12）
- 每台打印机的详情弹窗现在直接显示“手机换料扫码二维码”，可下载对应的 SVG 标签；二维码绑定当前真实打印机 ID，避免在耗材中心列表中找错设备。
- 手机 App 扫描打印机二维码时，如果设备列表仍在加载，会等待服务器返回后再匹配，不再因查询尚未完成而立即显示“服务器找不到设备”。
- 前端构建与 ESLint 已通过；本地 HTTPS 开发服务已重启（8019）。

## 正式空白生产版打包（2026-08-12）
- 已生成 Windows x64 自包含安装包：`installers/windows/build/output/bambuddy-0.2.4.9-windows-x64-setup.exe`（Inno Setup 6.7.3，约 188 MB）。安装包包含嵌入式 Python、后端、正式生产前端、NSSM 服务、ffmpeg 和首次启动脚本。
- 正式前端构建使用 `VITE_PRODUCTION_BUILD=1`：隐藏虚拟打印机测试入口；服务使用 `BAMBUDDY_PRODUCTION_BUILD=1`。代码中的虚拟打印机实现仅保留用于开发兼容，不会创建或带入虚拟设备数据。
- 首次安装会在 `C:\ProgramData\Bambuddy` 创建空数据目录；若检测到旧数据，会移动到带时间戳的 `previous-data-*` 隔离目录，新的安装不会读取旧账号、产品、库存或打印机。初始化标记写入 `.fresh-install-complete`，后续升级保留用户正式数据。
- 设置页新增“手机 App 连接”二维码（不包含账号密码），Android App 首次连接页支持扫描该二维码；调试 APK 已生成：`frontend/android/app/build/outputs/apk/debug/app-debug.apk`。
- 打包校验：连接二维码测试 3/3、API 客户端回归 24/24、TypeScript/Vite 构建通过、Android `assembleDebug` 通过、Inno Setup 编译通过。npm 仍报告现有依赖审计告警，未在本次打包中强制升级依赖。
- 自动切片仍复用现有 Bambu Studio/OrcaSlicer sidecar 配置；本次 Windows 安装包已内置独立的 Docker Desktop 检测、sidecar 启动和健康检查通道，不再要求小白手工配置。第三方镜像仍在目标机首次安装时从官方/配置的 GHCR 地址拉取，不嵌入安装包。

## 备份与导入按钮可见性（2026-08-12）

- 设置 → 备份与恢复 → 本地备份区域现在明确显示“下载备份”和“恢复备份”按钮。
- 按钮复用现有完整 ZIP 备份与恢复接口，不改变数据库、上传文件或恢复流程；恢复前仍会弹出覆盖确认。
- 8019 HTTPS 服务已重启，前端构建与本地备份组件定向测试通过。

## 耗材二维码批次 PDF 与已入库视图（2026-08-12）

- 材料类型页生成二维码时，数量会作为一个批次保存；下载区按生成时间从新到旧显示一行批次记录，不再逐卷显示或下载 SVG。
- 每个批次可下载一个 PDF；PDF 每页为 40mm × 40mm，按卷顺序排列，适合连续标签打印机直接输出。
- 未扫码入库的卷只保留为二维码批次的内部解析数据，不计入耗材库、库存分组或材料类型的已入库数量；扫码入库后才进入库存记录。
- 下载接口：`GET /api/v1/production/consumable-library/batches/{batch_id}/pdf`；批次列表：`GET /api/v1/production/consumable-library/batches`。
- 本次重启验证：8019 HTTPS 服务正常；已有批次 PDF 返回 `application/pdf`，页面尺寸为 40mm × 40mm；阶段 12 耗材回归 11 项通过。

## 耗材消耗与成本（阶段 15，2026-08-12）

- 每卷耗材二维码生成时可记录净重（g）和单卷价格；旧二维码仍可继续使用，只是没有成本基准。
- 真实打印完成回调会从打印归档、切片产物或文件元数据读取耗材克数，按当前直供耗材卷自动记账，并用操作编号保证 MQTT 重复回调不会重复扣减。
- 新增耗材消耗记录表、剩余克重扣减和耗尽自动释放绑定；无法取得克数时不会虚构消耗记录。
- 耗材库新增按品牌/材料/颜色的消耗克数、估算成本和打印记录统计，支持近 1 年、半年、3 个月、30 天、7 天、3 天、1 天以及自定义日期范围。
- 本分支：`codex/consumable-cost-tracking`。下一步需要在真实打印机上完成一次切片克数、耗材绑定、打印完成和成本统计的人工验收。

更新时间：2026-08-12

## 本次交接结论

阶段 11 已完成；阶段 12 已在分支 codex/feature-stage12-direct-consumable-scan 完成直供耗材绑定、耗材卷库、批量唯一二维码、扫码入库/耗尽、库存统计、颜色匹配约束、摄像头/原生相机扫码入口和本地 HTTPS 测试脚本。第 11 阶段演示产品、虚拟打印机和本地数据库仅用于验收，不在代码或安装包中。仍未连接真实打印机、读取真实状态或发送打印。最新阶段 12 结论见 docs/STAGE12_HANDOFF_CN.md。

阶段 9 和阶段 10 的当前代码实现、本地回归和交接已完成。本文较早的“尚未完成”条目是历史记录，不能覆盖 `docs/handoff/stage10/README_CN.md` 中的最新结论；下一位维护者应以交接包、当前 Git 提交和 GitHub Actions 结果为准。阶段 14 的单机受控发送实现以本次交接结论为准。

阶段 14 已在分支 `codex/feature-stage14-real-printer` 完成真实打印机自动匹配、切片和既有队列发送实现：真实状态由已有 MQTT 连接自动读取；满足型号、扫码耗材、在线、空闲和切片成功条件后，生产订单会自动把真实切片结果交给既有队列。切片库仍保留手动发送独立切片结果的入口。队列负责 FTP/MQTT 传输，MQTT 开始/完成事件会分别回写“打印中”和“待质检”，质检、报废数量与清板继续人工确认。虚拟任务、未匹配任务和未连接/不可用真实机均不会发送。尚待用户在一台真实机器上完成手工验收；未打标签，未构建安装包。

## Git 状态

- 阶段 9 开发分支：`codex/feature-production-stage9-allocation`
- 阶段 9 基线：`43e7573a`
- 阶段 8 验收修复分支：`codex/fix-stage8-acceptance`
- 阶段 7 基线：`8642d142`
- 阶段 8 后端提交：`82145a48`
- 阶段 8 前端提交：`95a81b2b`
- 阶段 8 权限与数量边界修正：`2dc1a58b`
- 阶段 8 验收缺陷修复：`1591a2c2`
- 阶段 8 验收测试格式修正：`795ca9fe`
- 最终代码 CI：[GitHub Actions 29670982608](https://github.com/zz526631245-eng/bambuddy/actions/runs/29670982608)（全部通过）

## 已完成

- 阶段 9 新增独立 `ProductionAllocator`：确认任务后自动匹配启用的打印机配置，并复用现有打印队列建立双向关联。
- 生产队列项保持 `manual_start` 安全暂停；队列接口、界面和调度器底层均禁止启动，不会进入 FTP、MQTT 或打印代理路径。
- 自动匹配使用冻结的主方案与兼容方案、打印机型号和位置，并把材料要求交给现有队列字段。
- PostgreSQL 使用任务行锁和打印机行锁防止并发重复分配；SQLite 明确限制为单进程分配器。
- 支持无可用打印机时等待、后台恢复分配、订单取消释放待处理队列项，以及可审计的自动分配操作记录。

- 创建订单时冻结产品、零件清单和打印方案版本快照。
- 自动把订单套数拆成各零件需求数量。
- 统一计算计划、已安排、合格、报废、剩余数量。
- 支持订单暂停、恢复、取消、优先级、交期和操作时间线。
- 先预览、再确认打印任务草稿；不分配打印机、不创建打印队列项。
- 重复操作编号安全重放；SQLite 和 PostgreSQL 迁移可重复执行。
- 新增“生产订单”侧栏、订单列表、详情和打印方案配置界面。
- 前端生产界面使用浅显中文。
- PostgreSQL 并发确认任务草稿时锁定订单，防止不同操作编号造成超量任务或账本不一致。
- 产品包导出和导入保留打印方案与产品零件的关联。
- 产品图片和产品包导出在启用登录后使用带认证请求，不再依赖无法携带 Bearer Token 的普通图片/链接请求。

## 验证结果

- 阶段 9 定向后端：5 项通过。
- 阶段 7/8、生产模块、打印队列和阶段 9 本地回归：138 项通过，9 项 PostgreSQL 测试因本机未设置 `TEST_POSTGRES_URL` 跳过。
- 阶段 9 前端定向：3 项通过；前端构建和代码规范通过。

- 阶段 8 后端及阶段 7 回归：46 项通过。
- PostgreSQL 16 升级、约束和并发：8 项通过，包含并发确认草稿不超量。
- 前端构建、代码规范、多语言一致性：通过。
- 本次新增认证资源测试及阶段 7/8 页面定向前端：6 项通过。
- 前端全量：2306 项中 2305 项通过；剩余 1 个为中文 Windows 的 `PM/下午` 原版区域设置差异。
- 本机后端全量收集受原版依赖和 GBK 编码环境限制；详见测试指南，已由 GitHub Actions 标准环境完成全量确认。
- 最终代码提交 `795ca9fe` 的 GitHub Actions 全部通过：后端全量四分片、Docker 后端四分片、PostgreSQL 16、前端 2306 项测试、前端构建、前后端规范与安全检查、Docker 构建和 2299 项容器集成测试均为绿色。
- 隔离测试版已在 `http://127.0.0.1:8018` 完成人工冒烟检查：两个零件需求均为 5，草稿预览正确，页面明确提示不会选择打印机或发送打印。
- 阶段 8 人工验收已在隔离数据 `D:\Bambuddy\stage8-test-data` 完成：创建 3 套订单后外壳和盖子需求均为 3；修改产品零件清单后历史订单快照和需求不变；确认草稿后两条任务均未选择打印机且 `queue_item_id` 为空；重复提交同一操作编号未新增任务；暂停、恢复、取消及时间线正确；打印队列记录数始终为 0。验收用临时零件已清理。

## 尚未完成

### 阶段 9 新增进度（产品级文件）

- 已保留阶段 7/8 的产品、订单、数量和历史记录逻辑。
- 已新增产品源 3MF 管理与 `fixed_plate`/`auto_pack` 策略字段。
- 产品文件变更会设置订单 `recalculation_required`，分配器跳过旧版本任务。
- 隔离测试环境保留两台软件模拟打印机，未连接真实设备。
- 阶段 10 的真实切片、自动摆盘和重新计算交互仍未完成，不能宣称阶段 9/10 全部验收。

- 阶段 9 尚未推送，未触发 GitHub Actions；PostgreSQL 真实并发用例需由 CI 验证。
- 阶段 9 尚未执行人工验收，不能标记为最终完成，也不能构建对外安装包。
- 验收修复分支已推送到 `origin/codex/fix-stage8-acceptance`，代码 CI 与阶段 8 人工验收均已完成。
- 隔离演示数据已建立在 `D:\Bambuddy\stage8-test-data`，不得当作正式生产数据。
- 尚未合并到长期开发分支、打阶段标签或构建安装包。
- 未连接任何真实打印机，未发送任何打印。
- 尚未开始阶段 10；后续路线、是否合并及发布安排等待用户另行确认。
### 阶段 9 本轮界面修复（2026-07-19）

- 产品详情页已移除旧的“零件打印方案”卡片；阶段 7 必须保留的“产品零件清单”和“可用零件”仍保留。
- 源 3MF 上传改为明确的文件选择控件，增加文件类型、数量校验，以及上传中、成功和失败提示。
- “一盘预计生产套数”已增加说明：表示一盘产出几套完整产品，不是订单总数，不能为 0。
- 产品新建流程改为系统自动生成 `PRD-0001` 形式的产品编码，创建时必须上传 PNG/JPEG/WebP 图片；产品列表现在显示首张产品图片。
- 503 认证服务错误已转换为中文提示；后端新增“创建产品并上传首图”的原子接口。
### Stage 9 material and colour capability matching (2026-07-19)
- Product source 3MF files now persist per-slot material and colour requirements and order snapshots retain them.
- Real and virtual printers share static supported capabilities and current loaded-filament state through one allocator matcher.
- Tests: backend stage 9/material regression passed; frontend build and lint passed. The only frontend full-suite failure remains the known Chinese-Windows `PM/下午` locale assertion.
### Stage 9 product-colour variants and file lifecycle (2026-07-19)
- Product source files now carry a product-level colour variant separate from per-slot filament material/colour.
- Re-uploading the same product colour creates the next version and deactivates the previous active file; stopped files can be physically deleted while historical order snapshots remain intact.
- Product order selection lists active colour variants only; the detail page supports uploading a replacement and stopping/deleting a variant.
### Stage 9 upload/delete usability fix (2026-07-19)
- Clicking “上传源 3MF” now opens a metadata dialog first; material, filament colour, product colour variant, plate strategy and per-plate capacity are submitted together with the selected file.
- Active files have separate “停用” and “删除” actions. Unreferenced files can be physically deleted; files referenced by historical orders return a protected error and remain available for snapshot viewing.
- Empty-string legacy colour values are treated as the unlabelled variant when calculating replacement versions, so a new upload replaces old unlabelled active files too.
### Stage 10 slicing planner (2026-07-19)
- Branch: `codex/feature-stage10-slicing`.
- Added deterministic fixed-plate and auto-pack planning. Auto-pack reads 3MF mesh bounds and calculates grid capacity from virtual-printer build dimensions; fixed-plate preserves layout and splits requested quantity into source plates.
- Plate jobs persist `slice_status`, retry count, error reason, timestamp and a source-file SHA-256/result association. Failed plans can be retried through `POST /api/v1/production/plate-jobs/{id}/slice`.
- Production confirmation now creates simulation-only slice results after virtual allocation; no MQTT, FTP, real printer command or print dispatch is performed.
- Regression result: Stage 7/8/9 plus Stage 10 tests passed (35 tests); frontend build and lint passed.
- Manual virtual acceptance: test product 2 auto-packed on A1 at 4 sets/plate and A2L at 5 sets/plate; fixed-layout test produced 8 source plates with `rearranged=false`.
### Stage 10 real slicer adapter (2026-07-19)
- Added `POST /api/v1/production/plate-jobs/{id}/real-slice` using the existing Bambu Studio/OrcaSlicer sidecar.
- The original product 3MF is sent with embedded project settings; automatic packing only forwards `arrange=true`. An optional printer override changes only the embedded printer identity fields and preserves orientation, infill, supports and object settings.
- The real output is stored as a new `.gcode.3mf` library file and linked in `PlateJob.slice_result`; no MQTT, FTP or print dispatch is performed.
- Tests: real-slice integration and embedded-settings preservation tests pass. A slicer sidecar must be running/configured before a real local slice can execute; the local Bambu Studio sidecar is now healthy on port 3001 for acceptance testing.
### Stage 10 reusable slice library (2026-07-19)
- Branch: `codex/feature-stage10-real-slicing`.
- Successful real outputs are stored in `slice_artifacts` with a fingerprint of source SHA/version, strategy, slicer and target printer identity. Repeating the same request reuses the existing `.gcode.3mf` without invoking the sidecar again.
- Added `GET /api/v1/production/slice-artifacts`, authenticated download endpoint, and a frontend `/slice-library` page. Download is allowed; dispatch returns a protected Stage 14 boundary error.
- The reported test product 2 failure was first reproduced as a sidecar geometry error; after normalizing stale source translations, product 2 jobs #7/#8 both completed real slices on the local sidecar.
- Regression: Stage 7/8/9/10 backend tests `35 passed`; real-slice/cache tests now `6 passed`; frontend lint and build pass.

### Product source file required for new orders (2026-07-20)
- New production-order creation now requires an active product source 3MF. The backend returns HTTP 422 with an upload prompt instead of falling back to legacy BOM/component data.
- The production-order form shows “请先上传产品源文件” for products without an active source file and disables the create button.
- Legacy BOM models/routes remain read-only compatibility code for historical data and are not used by new orders.
- Regression: Stage 8 production-order tests `7 passed`, Stage 9 allocation tests `7 passed`, and the production-order frontend tests `6 passed`.

### Product size routing and assigned-printer slicing (2026-07-20)
- Products now have a persisted `size_class`: `standard` or `large`; existing products are upgraded to `standard` by the idempotent schema check.
- The size class is included in the product/order snapshot. `large` excludes A1/A1 Mini profiles during software allocation; material and colour matching remains the capability gate, while geometry and plate packing remain slicer responsibilities.
- Product detail exposes the size tag. Real slicing automatically patches only the embedded printer identity from the allocated virtual printer (A1/A1 Mini/A2L) when no explicit override is supplied.
- Added `backend/tests/integration/test_product_size_routing.py`: large/standard routing and assigned-printer model propagation both pass. Stage 9/10 regression: 20 tests passed; backend Ruff, frontend build and frontend lint passed.
- No real printer connection, MQTT/FTP, print dispatch or automatic physical printer selection was introduced.
- Manual real-sidecar verification after restart: temporary acceptance product #4 used desktop `111.3mf` twice. Order #9 auto-assigned virtual A1 (#3) and produced artifact #2 (`Bambu Lab A1`, `Metadata/plate_1.gcode`); order #10 auto-assigned virtual A2L (#4) and produced artifact #3 (`Bambu Lab A2L`, `Metadata/plate_1.gcode`).
- Existing product #2 jobs #7/#8 now succeed with `auto_pack/arrange=true` after the source build-item translations are normalized to zero while their rotation matrices remain unchanged; no process/object settings are rewritten.
- The focused Stage 9/10 suite is green (`23 passed`). The broader legacy Stage 7/8 command still has 5 pre-existing schema-test failures because `plate_jobs.virtual_printer_id` references `virtual_printers` before that model is imported in the isolated metadata fixture; this is outside the size-routing change and was not altered here.
- Auto-pack quantity verification (2026-07-20): the deterministic planner calculated A1 capacity 6 sets/plate, 10 sets → 2 plates and 3 sets → 1 plate. Live jobs #11 and #12 now produce distinct real artifacts (`[6,4]` and `[3]`) and exact retries reuse all matching plates.

### Stage 10 quantity-specific real slicing fix (2026-07-20)
- Auto-pack now calculates requested quantity into per-plate quantities (for example, capacity 4 produces `10 -> [4, 4, 2]` and `3 -> [3]`).
- Each plate is sent to the real Bambu Studio/OrcaSlicer sidecar with a duplicated 3MF build set; embedded process, orientation, infill, support and object settings are not rewritten.
- The cache fingerprint includes source product-file ID, plate index and plate quantity. Different plates produce distinct `.gcode.3mf` artifacts, while an exact retry reuses every valid plate artifact.
- `slice_result` exposes `requested_quantity`, `plate_count`, `plate_quantities` and a per-plate artifact list; existing top-level fields remain for compatibility.
- Sidecar geometry failures are surfaced as an actionable Chinese error explaining that the source layout/support/skirt is outside the target bed, with the original sidecar reason retained. The system does not silently fall back to simulation or disable auto-pack.
- Tests: Stage 10 real-slice/cache/quantity tests `9 passed`; Stage 7/8/9 routing and product-file regression `23 passed`; Ruff passed for changed slicing code.
### Real slice filename clarification (2026-07-20)
- Real output names now include both the plate number and the number of product sets on that plate, for example `111.plate-1.qty-3.gcode.3mf` and `111.plate-2.qty-4.gcode.3mf`.
- The output naming convention is part of the cache fingerprint, so an old ambiguously named artifact is not reused after this change; the source and slicer settings remain unchanged.
- Regression: focused Stage 7/8/9/10 suite `49 passed`; Ruff and `git diff --check` passed.
### Z 高度保留修复 (2026-07-20)
- 修复真实自动摆盘时将 3MF `<build><item transform>` 的 Z 平移误清零的问题；现在只归零旧布局的 X/Y，保留原始 Z 高度和旋转矩阵。
- 为布局归一化版本更新缓存指纹，旧的错误 G-code 3MF 不会被复用。
- 重新真实切片验证：`qty-3`、`qty-6`、`qty-4` 文件中的模型 Z 平移均为 `11.9565001`；未发送打印。
- 回归测试：阶段 7/8/9/10 聚焦套件 `49 passed`，Ruff 与 `git diff --check` 通过。

### 生产订单创建界面改进 (2026-07-20)
- 订单编码改由后端按日期和序号自动生成（`PO-YYYYMMDD-001`）；接口仍兼容显式编码，便于历史数据和内部测试。
- “选择产品”改为弹窗，展示首张产品图片、名称和编码，并支持名称/编码搜索。
- 数量字段改为“需要生产数量（套）”，避免把订单总量和摆盘产能混淆。
- 定向回归：后端阶段 9 分配测试 `7 passed`；前端订单页面 `5 passed`；前端构建、Ruff 和 `git diff --check` 通过。
- 后端已重启并确认 `http://127.0.0.1:8019/openapi.json` 返回 200；未连接真实打印机、未发送打印。

### 多盘固定源文件与订单展开（2026-07-20）
- 产品源文件增加“多盘固定（多盘完成一套）”策略，并自动记录 3MF 内的源盘数量；该模式每张源盘固定打印 1 份，不使用自动摆盘。
- 生产订单数量表示完整产品套数。订单确认时按“套次 × 源盘”展开物理盘任务，并保存 `product_set_index`、`source_plate_index`、源盘总数及文件版本快照。
- 多盘固定任务按源盘编号切片，切换打印机只切换目标机型参数；不会重排、复制或覆盖源文件中的模型方向、支撑、填充和局部设置。
- 单盘固定和自动摆盘流程保持原逻辑。阶段 14 前仍禁止真实打印机连接、MQTT/FTP 和打印发送。
- 验证结果：多盘文件/订单/切片回归测试 40 项通过；前端构建通过；Ruff 与 `git diff --check` 通过。

### 多盘产品结构上移到产品层（2026-07-20）
- 产品新增“单盘产品/多盘产品”和“一套源盘数量”；创建或编辑多盘产品时必须填写至少 2 盘。
- 多盘产品上传时按产品设置动态显示源盘 1、源盘 2……的独立 3MF 上传位置；这些文件通过同一组编号归组，订单只选择完整源文件组的入口。
- 订单创建前会校验源文件组是否完整；快照保存整组源文件 ID，切片按 `source_plate_index` 使用对应文件。旧的文件级 `multi_plate_fixed` 仍可读取，作为迁移兼容。
- 新增产品级多盘测试和不完整源文件组拒绝测试；阶段 9/10 聚焦回归共 44 项通过，前端构建和 Stage 8 页面测试通过。

### 生产订单详情控制与旧测试订单清理（2026-07-20）
- 生产订单详情页现在可查看每个盘任务的切片状态、盘数量、产物文件和关联队列编号，并提供切片结果下载入口。
- 支持取消单个盘任务、删除单个未执行盘任务、取消整张生产订单以及删除整张生产订单；正在打印的队列项会被保护，禁止删除或取消后篡改实际执行记录。
- 修复生产订单确认盘任务接口缺少返回值的问题，确认接口现在正常返回订单和盘任务列表。
- 已清理本地数据库中 15 条旧测试生产订单及其 15 条需求、15 条盘任务和相关订单操作日志；产品、产品源文件、切片库、打印机配置和打印队列均保留。清理前数据库备份为 `bambuddy.db.before-production-order-cleanup.bak`。
- 验证：新增后端控制测试 2 项通过；前端 Stage 8 测试 6 项通过；前端构建、lint、后端 Ruff 通过；后端重启后 `http://127.0.0.1:8019/openapi.json` 返回 200，订单列表返回空数组。
## 本次扫码确认与兼容更新

- 直供耗材扫码现在支持只提交耗材卷 unit_code；页面自动读取材料类型和颜色，目标打印机已锁定时填入待确认状态，点击确认后写入绑定。
- 前端摄像头扫码改用 ZXing 兼容识别，覆盖不支持 BarcodeDetector 的移动浏览器。
- 二维码生成支持 VITE_PUBLIC_BASE_URL，并在 127.0.0.1 页面显示手机不可访问提示。
- 本次相关后端测试 20 项通过，前端 build 和 lint 通过。

### 确认登记 503 修复（2026-08-10）

- 根因是旧数据库中的 `production_printer_consumables` 表缺少 Stage 12 新增的 `consumable_unit_id` 列；路由异常被外层认证中间件误显示为 `Authentication service temporarily unavailable`。
- 新增可重复执行的 Stage 12 迁移和索引，启动时自动升级旧数据库；认证探针同时增加 SQLite 短暂锁重试，并继续对持久/非锁错误 fail-closed。
- 重启后 `GET /api/v1/production/printer-consumables` 返回 200，确认登记接口使用幂等操作回放返回 201；数据库完整性检查为 `ok`。
- 未入库耗材绑定时的 422 提示已改为“该耗材未入库，无法绑定打印机”，避免把库存状态误解为扫码或认证故障。
- 材料类型页面现在负责生成耗材卷二维码，并按材料类型展示待入库、已入库、使用中、耗尽、报废和总卷数；每卷二维码按生成时间倒序显示。耗材库页面仅保留扫码入库/耗尽和总库存查看。

### 阶段 13 打印机状态与故障重排（2026-08-10）

- 新增独立的 `production_printer_status` 状态快照和统一心跳接口，实体打印机与虚拟打印机使用相同的数据契约。
- 新增 `/production-printer-status` 状态监控页，支持每 3 秒刷新和模拟空闲、打印中、暂停、离线、故障、维修状态。
- 心跳超过 30 秒自动判定离线；离线、故障、维修中的目标不再参与新的自动分配，尚未开始的已分配任务自动回到待分配并保留操作日志。
- 阶段 13 未连接真实打印机、未读取真实 MQTT/FTP 状态、未发送打印；第 14 阶段再接真实适配器和单机受控发送。
- 阶段 13 定向与阶段 9/12 回归共 17 项通过，前端 build、lint 和后端 Ruff 通过。

### 阶段 14 单台真实打印机受控发送（2026-08-12）

- 切片库现在允许操作员选择一台已连接的真实打印机，并在第二次确认后把已关联生产盘任务的真实 `.gcode.3mf` 交给 Bambuddy 原有打印队列；没有新增 MQTT/FTP 通道，也不会自动选择或自动发送真实打印机。
- 已确认的真实盘任务才可越过生产队列的发送保护；阶段 9 的源文件占位队列会保留审计记录并取消，由真实切片文件替换。虚拟盘任务、未确认任务、未关联盘任务和离线打印机均被拒绝。
- 真实机状态页从既有 MQTT 客户端快照自动读取，禁止在页面伪造真实机心跳。真实机与虚拟测试机同时可用时，自动分配优先选择真实机，虚拟机仅在没有真实可用机时回退。
- MQTT 回调确认开始后，盘任务转为“打印中”；完成或失败后均进入“待质检”，仍由人工录入合格/报废数量并确认清板，数量只由后端账本入账。
- 补齐真实打印机耗材登记二维码：`/printer-consumables` 顶部只展示已启用真实打印机的二维码和下载按钮。手机先扫该二维码即可自动锁定机器，再扫耗材卷并确认登记；二维码只含局域网 HTTPS 地址和 `printer:<id>`，不含访问码。
- 已完成本地定向与阶段 9～13 回归、Ruff、前端 build/lint。尚未在真实打印机执行人工验收；未创建 Git 标签，未构建安装包，也未向真实打印机发送文件或命令。

### 真实打印机扫码耗材显示与料型安全校验（2026-08-12）

- 打印机页面的外部耗材卡片改为只显示当前有效的生产扫码记录；真实打印机 MQTT 回传的 `vt_tray` 不再覆盖扫码登记的颜色或料型。
- 真实打印机确认登记前会读取已连接 MQTT 快照中的外部料槽料型作安全校验：扫描颜色不同但料型相同的耗材允许登记；扫描 `PLA`、`PETG`、`TPU` 等与设备料型不一致的耗材会拒绝登记，并提示先在打印机或 Bambu Studio 中调整设备料型。
- 打印机离线或未回传外部料型时拒绝登记；该检查不会建立新连接、不会自动写入实体打印机，也不会发送打印。扫码页面会直接显示中文错误原因。
- 回归：Stage 12/13/14 后端定向 `14 passed`；Ruff 通过；打印机页面前端定向 `61 passed`；前端生产构建通过。
### Real production allocation and slicing fix (2026-08-12)

- Real-printer allocation now refreshes the connected device status and matches model, scanned material/colour, and queue occupancy. Direct-feed slot 254 is accepted for a single-slot product requirement.
- Confirmed real jobs use the existing real print queue and real slicer; virtual jobs remain simulation-only. Both paths keep explicit human dispatch confirmation and never send a print command automatically.
- Fixed quantity splitting so every repeated one-plate 3MF is sent to the sidecar as source plate 0. Fixed Windows native sidecar access by normalizing localhost to IPv4 loopback, and made reallocation operation IDs unique.
- Live verification: order 3 auto-assigned to real printer A1-1 with PETG/white, produced six real `.gcode.3mf` plate artifacts, and remains held in the print queue. No print was dispatched.
- Focused backend regression: 26 passed; slicer endpoint/plate-index regression: 15 passed; Ruff, frontend build and lint passed. Existing unrelated frontend full-suite failures remain documented.

### 单盘自动摆盘与真实任务自动入队（2026-08-12）

- 产品源文件上传和产品详情页的新建默认策略改为 `auto_pack`；用户上传一份单盘 3MF 即可由切片器在同一盘内尽量复制摆放多套，不需要先生成多个相同文件。多盘产品仍按源盘文件组逐盘完成，不会复制源盘。
- 真实订单在型号、扫码耗材材料/颜色、在线状态、空闲状态和真实切片均满足后，后台自动复用第 14 阶段的发送逻辑：取消原始源文件占位队列，创建真实 `.gcode.3mf` 队列项并解除 `manual_start`，交由原有调度器执行 FTP/MQTT。
- 生产订单页已改为明确提示自动入队；切片库的手动发送入口仍保留，用于独立切片结果，不会发送虚拟打印机任务。
- 为避免多产物任务只发送第一盘造成少打，当前 `PlateJob` 单队列关联在检测到多个切片产物时保持占位等待；现有历史 `fixed_plate` 文件需要重新上传一次或在产品页选择自动摆盘后再建单。
- 回归新增：真实切片后自动替换占位队列、单盘上传默认 `auto_pack`；相关 Stage 9/10/14 测试和 Ruff 已通过。尚未构建安装包。

### 自动摆盘旋转 3MF 修复（2026-08-12）

- 根因是旧算法只读取网格原始 X/Y，忽略了 3MF build-item 的旋转；对绕 X 轴放置的模型会误判底面深度，把对象摆到打印板外，Bambu Studio 报“第 1 盘为空”。
- 现在容量和投影计算会先应用组件与实例变换；写回源 3MF 时只更新 XY 平移和 Z 轴朝向，保留源矩阵缩放、Z 高度以及全部切片参数。自动摆盘不再先清零用户源文件坐标。
- 已用用户本次失败的真实 A1/PETG 白色源文件复现：原文件切片成功，修复后的 6 套自动摆盘真实 sidecar 切片成功；没有发送打印命令。
- 新增旋转组件、缩放矩阵和自动摆盘回归测试；阶段 9/10/14 与相关单元测试共 52 项通过，Ruff 通过。

### 整套产品几何路由与 30 小时摆盘审核（2026-08-12）

- 一个上传的 3MF 被视为一套完整产品：文件内的多个 build item 会保留相互间的真实间距和姿态，复制摆盘时整套一起移动；只有整套全部完成才计为一个产品，不会把单个零件误算成成品。
- 打印机兼容性改为按实际变换后的 3MF 包围尺寸和打印配置的宽/深/高判断，不再用 A1/A2 的硬编码互斥表。打印配置页可填写机台尺寸；留空时使用已知机型默认尺寸。兼容机型列表现在是优先级提示，其他机型只要实际放得下也可参与分配。
- 自动分配会在所有可用真实机中比较整套产品的摆盘容量；当前机型忙碌或离线时会继续尝试其他真实机型，存在真实机目标时不会回退到虚拟测试机。
- 真实切片结果若任一盘预计超过 30 小时，任务进入“待人工确认”，不会自动入真实队列。确认后才允许继续分配；拒绝会自动减少每盘的完整产品套数并重新切片，直到不超过 30 小时，若单套仍超过 30 小时则保留人工确认/换机提示。
- 新增打印机尺寸和盘任务审核字段的可重复迁移，以及订单详情页的“确认仍然分配 / 拒绝并重新摆盘”操作。
- 验证：相关后端回归 `50 passed`；迁移、整套多零件摆盘、阶段 9/10/14 和订单控制均通过；后端 Ruff、前端 `npm.cmd run build` 与 `npm.cmd run lint` 通过。`test_production_api.py` 仍有 1 个旧断言期望“零件清单”，实际产品源文件校验返回“请先上传产品源文件”，与现行阶段 8 合同不一致，未改动该业务语义。
- 尚未构建安装包；真实打印仍需人工用测试模型验收。多产物盘任务仍受现有单 `PlateJob.queue_item_id` 关系保护，不会只发送第一盘。

### UI 导航入口精简（2026-08-12）

- 主侧边栏只保留六个日常入口：打印机、生产中心、耗材中心、产品、打印记录、设置。
- 生产中心页面内合并了生产订单、打印队列、打印机状态和切片库；耗材中心页面内合并了材料类型、扫码入库和打印机绑定；打印机和产品页面分别提供配置/维护、文件/项目/MakerWorld 等相关入口。
- 低频菜单仅从主侧边栏隐藏，原有路由和功能均保留，没有删除后端接口或业务数据。
- 中文菜单名称调整为“生产中心”“耗材中心”“打印记录”，料盘库存改为“料盘库存”。
- 验证：前端 lint、Layout/生产订单定向测试 `31 passed`、前端生产构建通过；本次未构建安装包。

### 分组入口改为页面内展开（2026-08-12）

- 生产中心、耗材中心、打印机和产品资料的相关功能入口现在由页面内选择器展开，不再点击后直接跳转到隐藏的低频路由；选择后直接替换当前页面下方内容区。
- 生产中心可在下方展开打印队列、打印机状态和切片库；耗材中心可展开扫码入库和打印机绑定；打印机可展开配置、维护和生产状态；产品资料可展开文件管理器和 MakerWorld。
- 产品资料中的“项目”入口已隐藏；项目路由仍保留，不影响历史数据或直接访问。
- 生产订单、耗材、打印机和产品的原有完整页面组件复用显示，未新增后端接口或改变业务逻辑。
- 验证：前端构建、lint、Layout/生产订单/设置测试 `78 passed`，HubNav 交互测试新增；本次未构建安装包。

## 清理料盘强制互锁（2026-08-12）

- 打印完成或失败后，打印机在操作员点击“确认清理料盘”之前保持锁定；调度器即使收到 `IDLE/FINISH` 也不会启动下一任务。
- 自动分配、真实切片派发、指定打印机队列入口和共享可用性检查均拒绝待清理打印机，避免新任务绑定或发送到未清理料盘。
- `require_plate_clear` 已迁移为强制开启；旧的 `false` 设置会在启动迁移时改为 `true`，API 也不允许再次关闭。
- 新增回归测试覆盖调度器、生产分配、真实派发、普通队列和设置接口；本次分支为 `codex/plate-clear-enforcement`。
# Cleanup state synchronization (2026-08-12)
- Production-order cleanup, printer-page cleanup, and QR scanner cleanup now share `printer_manager.awaiting_plate_clear`.
- Real production cleanup commits the order first, then releases the linked printer; duplicate cleanup remains idempotent.
- Consumable targets expose `awaiting_plate_clear`, and the QR page can call the existing clear-plate endpoint and refresh related queries.
- Regression: Stage 11/14 `15 passed`; frontend lint and build passed.
# Consumable inventory summary view (2026-08-12)
- Added a server-calculated inventory summary grouped by brand, material type/subtype, and colour.
- The consumable library now shows one compact card per specification with in-stock, bound, pending-receipt, depleted, scrapped, and total roll counts.
- QR-unit scan-in and depletion still use the existing lifecycle; successful scans invalidate the summary immediately.
- Verification: Stage 12 consumable tests `2 passed`; backend Ruff and frontend lint/build passed.

### 产品维度生产总览修正（2026-08-12）
- 生产中心主看板改为按产品聚合，每个产品只显示一行，不再把订单批次作为主表行。
- 新增 `/api/v1/production/product-workbench`，由后端汇总产品的总需求、已完成、剩余、打印中、已分配、待质检、待清盘、逾期批次数、最高优先级、最近交期和已分配打印机。
- 产品行可展开查看该产品下的具体生产批次，订单详情、追加数量和历史订单入口继续保留。
- 回归验证：Stage 8/控制/Stage 9 共 `19 passed`，前端定向测试 `32 passed`，Ruff、Lint 和前端构建通过；未构建安装包。


# 生产中心订单工作台（2026-08-12）

- 生产中心改为深色桌面工作台：交付总览、排产队列、打印机安排、历史订单和低频切片库在页面内切换，不再把用户带到另一个页面；当前订单以表格显示目标、已完成、剩余、打印中、待质检、打印机、优先级和交期。
- 订单创建支持产品名称/SKU 搜索、源文件选择、五级优先级（最高/高/中/低/极低）、交期和排产预检查；同一产品、同一源文件/材料颜色快照、同一明确交期的未完成订单会在后端合并，追加数量写入原订单并保留操作记录。
- 后端统一计算订单进度、逾期状态、打印机名称和历史批次数量；逾期未完成批次红色提示，可重新规划交期/优先级。历史订单支持订单号、产品、日期范围筛选，当前视图不会混入已完成或取消批次。
- 删除规则改为：尚未开始执行的订单物理删除；已经开始/完成的订单软删除并保留打印、质检、清板和耗材审计，不会向真实打印机发送停止命令。分配器排除软删除订单。
- 新增 `deleted_at`、`completed_at` 可重复迁移，保留现有切片、真实队列、耗材和料盘清理链路；未修改虚拟测试机的真实产品边界。
- 回归：Stage 8/订单控制/Stage 9 共 `18 passed`，前端生产订单定向测试 `7 passed`，前端 `npm.cmd run build` 通过。尚未构建安装包，真实打印仍需人工验收。

### Android 手机操作 App 第一版（2026-08-12）

- 新增 `/mobile` 手机工作台：入库、打印机换料、耗材用完、耗材报废、打印质检、清理料盘均采用大图标和分步向导，复用现有生产/耗材接口，不复制服务器数据到手机。
- 手机首次打开会填写 Bambuddy 服务器 HTTPS 地址并保存；换料流程强制先扫打印机二维码，再扫耗材二维码，提交前显示当前打印机和材料信息；相机由 ZXing 在 Android WebView 中调用，失败时保留扫码枪/手动输入入口。
- 已加入 Capacitor Android 工程：`frontend/android`，相机、局域网连接和用户安装证书权限已配置。调试 APK 已成功构建于 `frontend/android/app/build/outputs/apk/debug/app-debug.apk`。
- 验证：前端 TypeScript/Vite 构建通过；Android `assembleDebug` 成功。完整 Vitest 当前有 6 个既有失败（德语 locale 缺键、时间区域断言、产品导航重复链接、AMS 测试数据、产品创建参数），与本次移动端无关，未修改其业务行为。
- 当前 APK 是调试签名版本，首次测试需手机允许安装未知来源；正式发布前还需配置正式签名、应用图标、服务器证书和 Play/内部发布渠道。
