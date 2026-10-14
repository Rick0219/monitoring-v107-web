# 原始水准数据导入实施计划

## 背景与边界

实现已批准的 [原始水准数据导入与平差设计](../specs/2026-10-14-level-adjust-import-design.md)。工作在当前 `main` checkout 进行，限定修改 `V1.07-Web` 的后端、前端、测试和文档；不执行上传文件或桌面 EXE，不迁移桌面报表模板、仪器驱动或串口服务。

## 任务 1：先建立失败测试

**文件：** `backend/tests/test_level_adjustment.py`、`backend/tests/fixtures/level_adjustment/`。

新增最小安全夹具，保留用户样例的格式特征但不提交完整工程资料：GB18030 `.DAT` 的 `KD1/Rb/Rf/Z` 行、`.BM1` 已知点、`.hdf` 测站行、`.in1` 测段行、`.gco`/`.ou1`/`.our` 结果片段。

先写并运行这些测试，确认因生产模块不存在而失败：

- `test_parse_level_adjustment_group_reads_encoding_and_source_lines`：得到编码、文件摘要、闭合回点 `Z2`、`Z2=-16.8744`，每条观测保留文件和行号。
- `test_parse_rejects_missing_known_point_or_malformed_measurement`：缺少 `.BM1`、坏数值、重复点号和未闭合路线分别返回带文件/行号的错误。
- `test_solve_level_network_distance_weight_matches_reference`：按距离定权得到有限高程，固定点不变，关键点与 `.our` 在允许误差内一致。
- `test_solve_level_network_station_weight_is_distinct_and_finite`：按测站定权得到有限结果，权重模式被记录且结果有可解释差异。
- `test_cross_check_reports_gco_ou1_our_mismatch_without_silent_write`：修改核验文件后，预览状态为 blocked。

## 任务 2：实现解析器和加权最小二乘

**文件：** `backend/app/level_adjustment.py`。

定义 `KnownPoint`、`LevelObservation`、`StationObservation`、`ParsedLevelAdjustment`、`AdjustmentPointResult`、`AdjustmentObservationResult`、`CrossCheck` 和 `LevelAdjustmentResult`，所有数值入口统一转成有限 `float`。

实现公开函数：

- `parse_level_adjustment_files(files: Mapping[str, bytes]) -> ParsedLevelAdjustment`
- `solve_level_network(parsed: ParsedLevelAdjustment, weight_mode: Literal["distance", "station"]) -> LevelAdjustmentResult`
- `cross_check_level_outputs(parsed: ParsedLevelAdjustment, result: LevelAdjustmentResult) -> list[CrossCheck]`

解析按 GB18030、UTF-8 尝试；`.DAT` 解析测站块和 `Rb/Rf/Z`，`.BM1`/`.in1` 解析逗号行，`.hdf` 解析前后视/距离/高差列，`.gco` 解析闭合差/路线长度/限差，`.ou1`/`.our` 解析平差段和最终点高程。错误必须带文件名和 1-based 行号。

求解器固定 `.BM1` 点，对每条 `from -> to` 观测建立 `H_to - H_from = delta_h` 行，使用纯 Python 正规方程和带主元高斯消元，避免新增科学计算依赖。距离模式使用测段长度作为方差依据，测站模式使用测站数或 `.in1` 回退字段；输出点高程、改正数、残差、闭合差、单位权中误差、自由度和限差状态。拒绝断点、零/负权重、无已知点、重复边和秩不足矩阵。

运行任务 1 测试，确认解析、两种定权和核验测试变绿。

## 任务 3：添加项目模型、存储和 API

**文件：** `backend/app/project_models.py`、`backend/app/api/routes/workspace.py`、`backend/app/monitoring.py`、`backend/tests/test_level_adjustment_api.py`。

新增严格的 `LevelAdjustmentPreviewRequest`、`LevelAdjustmentApplyRequest`、`LevelAdjustmentMapping` 模型，限制文件大小/数量、日期格式、`weight_mode`、`revision` 和映射内容。

在 `workspace.py` 增加受 `EntryProject` 保护的：

- `POST /projects/{project_id}/level-adjustment/preview`：接收 `files[]`、`weight_mode`、`observed_date`，返回 `import_id`、文件摘要、解析诊断、平差结果、交叉核验、映射候选和 revision。
- `PUT /projects/{project_id}/level-adjustment/apply`：接收 revision、目标水准测项、日期、映射、权重模式和超限确认，原子写入目标日期的 `点号/测量值`。

预览使用现有 20 MB `bounded_upload` 限制，原始文件落盘到 `data/projects/<project_id>/level-adjustments/<import_id>/`。项目 payload 只保存清单、摘要、计算参数、质量状态和结果引用。应用接口重新校验 mapping、测项、点号和 revision，保留其他日期、备注和未选点，任何错误在提交前返回 422。

API 测试覆盖预览成功、坏文件、闭合超限、目标日期只更新、重复点号、未知数据库点号、权限拒绝和旧 revision 冲突，并确认失败不改变 payload。

## 任务 4：实现 React 三步导入向导

**文件：** `frontend/src/components/LevelAdjustmentImport.tsx`、`frontend/src/pages/DataEntry.tsx`、`frontend/src/index.css`、必要时 `frontend/src/api.ts`。

`LevelAdjustmentImport` 接收 `project`、`data` 和 `onApplied`。在 `DataEntry` 标题区域左侧增加“原始数据导入”按钮；按钮只在 `data_entry` 工作区可见。

向导固定为 `files -> settings -> mapping`：

1. 文件步骤将 DAT 设为必选、BM1 设为可选，其余后缀可选；只有 DAT 时直接进入映射，DAT+BM1 时进入平差设置。
2. 设置步骤提交 preview，展示已知点、起终点、测段数、总长度、闭合差、限差、交叉核验和两种定权单选；平差模式预览后提供五类生成文件下载。
3. 映射步骤选择目标水准测项和数据库点号；精确匹配自动勾选，模糊匹配只显示候选；冲突、未匹配、质量失败和超限写入开关必须可见。

应用成功后刷新 `project`、`project-data`、当前 entry、database table/chart 和 projects 查询，显示写入、跳过和未匹配数量。样式只增加 `.level-adjustment-*` 命名空间并遵循现有响应式 panel/modal/table 规则。

## 任务 5：前端和样例验收测试

在现有 Playwright 配置中添加隔离测试工程：无 `data_entry` 权限时按钮不存在；文件自动分组；预览显示两种定权和闭合差；映射冲突阻止写入；应用成功刷新表格。

用用户提供的 7 个文件做一次不提交原始资料的 API 手工验收：识别 `Z2=-16.8744`、闭合回点 `Z2`、约 `1.5510 km`；映射 `Z2`、`Z1`、`Z1.1` 等点到测试工程水准测项，并写入 `2026-10-12` 日期。

## 任务 6：完整验证与收尾

运行：

- `cd C:\Users\HP\Documents\日报\V1.07-Web; .\.venv\Scripts\python.exe -m pytest`
- `cd C:\Users\HP\Documents\日报\V1.07-Web\frontend; npm test`
- `cd C:\Users\HP\Documents\日报\V1.07-Web\frontend; npm run build`
- `git diff --check` 和 `git status --short`

确认没有用户原始文件、临时上传目录、`.env` 或 `data` 被提交；更新 `docs/progress.md` 或 README 的后缀、权限、日期写回和限制说明；最后提交实现并记录测试数量、构建结果和样例验收结果。

## Review Focus

- `.DAT` 的定长字段和 GB18030 解码必须由夹具验证。
- 两种定权必须真正进入矩阵权重，并在结果中记录来源。
- `.our` 只作交叉核验，不能无条件覆盖重新计算结果。
- revision、权限和映射失败必须保证无部分提交。
- 只更新选定日期和映射点，其他期次、备注和未选点保持不变。
