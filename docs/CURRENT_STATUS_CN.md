# 当前开发状态

更新时间：2026-08-10

## 本次交接结论

阶段 11 已完成；阶段 12 已在分支 codex/feature-stage12-direct-consumable-scan 完成直供耗材绑定、耗材卷库、批量唯一二维码、扫码入库/耗尽、库存统计、颜色匹配约束、摄像头/原生相机扫码入口和本地 HTTPS 测试脚本。第 11 阶段演示产品、虚拟打印机和本地数据库仅用于验收，不在代码或安装包中。仍未连接真实打印机、读取真实状态或发送打印。最新阶段 12 结论见 docs/STAGE12_HANDOFF_CN.md。

阶段 9 和阶段 10 的当前代码实现、本地回归和交接已完成。本文较早的“尚未完成”条目是历史记录，不能覆盖 `docs/handoff/stage10/README_CN.md` 中的最新结论；下一位维护者应以交接包、当前 Git 提交和 GitHub Actions 结果为准。阶段 14 前仍禁止真实打印机通信和发送打印。

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
