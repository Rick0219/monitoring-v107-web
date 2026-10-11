# 网页分类型录入 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for inline implementation. This is a scoped update to the existing web workspace.

**Goal:** 数据录入先选择六类监测类型，再进入对应测项、参数和单期表格，按钮与设置区清晰区分。

**Architecture:** 保持现有单期录入 API 和桌面计算服务。DataEntry 增加类型选择状态和按类型过滤的测项；独立 EntryTypePicker 复用桌面 SVG。样式只调整录入页及共用录入表格。

**Tech Stack:** React、TypeScript、现有 CSS、FastAPI、Playwright。

**Spec:** 本轮用户三项要求及六个监测类型截图；`docs/desktop-entry.md` 定义现有计算规则。

## Constraints and review focus

- 仅修改 V1.07-Web，不改桌面计算或账号权限。
- 初始页即使已有数据也显示类型选择，不请求单期录入表。
- 类型中只能选择本类型测项；水位/水平位移直接进入固定测项。
- 未保存草稿切换类型需确认，取消保留草稿；切换不写数据库。
- 倾斜缺少水准源时提示先录入水准，并提供入口。
- 桌面六列、窄屏自适应；录入表内部滚动，页面不横向溢出。

## Task 1: 分类型流程和视觉区分

**Files:** `frontend/src/pages/DataEntry.tsx`、新增 `frontend/src/components/EntryTypePicker.tsx`、`frontend/src/assets/monitoring-icons/*.svg`、`frontend/src/index.css`、`frontend/src/vite-env.d.ts`。

- [x] 在 `frontend/tests/entry.spec.ts` 增加真实浏览器回归：初始类型选择、按类型筛选、缺少水准源、未保存切换；更新旧流程入口。
- [x] 运行新增测试，确认失败来自缺失类型选择页。
- [x] 实现类型入口及返回流程，复用现有参数、导入和保存。
- [x] 增强设置区、参数按钮、编辑单元格、保存按钮对比。
- [x] 类型检查、构建，运行所有浏览器测试，检查桌面和手机截图。
- [x] 更新操作说明、验证记录，并检查实际服务健康及新静态资源。
