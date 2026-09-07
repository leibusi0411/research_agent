# ADR-0045: Web 报告显式沉淀进知识库（Knowledge Deposit）

**日期**: 2026-09-06  
**状态**: ✅ 已实施  
**影响范围**: `core/deposit.py`（新增）, `core/service.py`, `core/errors.py`, `cli.py`, `api/app.py`

## 背景

V1 中 Local RAG 与 Web Research 完全独立（Research Workflow Boundary），TODO.md 将 "Automatic knowledge deposit into the Markdown Vault" 列为有意延期项，并注明设计意图是"用户显式保存选中的报告"。用户希望两条线产生联动，方向确定为：把 Web 调研结果沉淀到本地知识库，使其在后续 Local RAG 检索中可被命中，而不是生成一次性的合并报告。

## 决策

新增 **Knowledge Deposit**：对已完成的 Web Research 任务，用户通过 `research-agent task deposit <task_id>` 或 `POST /api/tasks/{task_id}/deposit` 显式将该任务的 Web Report File 复制到 `<vault>/web-research/`。

### 关键设计选择

- **显式动作，非自动**：沉淀由用户按需触发，不在 Web Research 流水线内自动发生。Research Workflow Boundary 保持不变——运行中的 Web 任务仍不接收 Local Results 或 Knowledge Base 上下文，deposit 只是事后把产物搬进 vault。
- **只增不改**：deposit 只在 vault 中新增笔记，绝不修改、移动或删除已有笔记。本 ADR 显式演进 ADR-0006 的适用范围：ADR-0006 约束的是 ingestion 对既有笔记只读，这条仍然成立；变化的是 vault 从"无人写入"变为"允许 deposit 追加新笔记"。
- **原样拷贝**：Web Report File 已含 frontmatter（title / task_id / created_at），原样拷贝即保留溯源信息；文件名沿用 Report Filename 约定（`{slug}-{date}.md`），重名冲突时追加 `-2` 等后缀。
- **幂等**：deposit 目录中已存在含该 `task_id` 的笔记时拒绝写入，报 `already_deposited`，防止重复沉淀污染知识库。
- **不自动重建索引**：沉淀后索引转为 stale，由用户显式运行 `kb rebuild`（CLI 输出中提示），与现有显式重建约定一致。

### 错误码

`VALID_ERROR_CODES` 新增 `task_not_found`、`invalid_task_mode`、`report_missing`、`already_deposited`。其中 `task_not_found` 同时补齐了 R-132 修复时遗漏的白名单注册——此前删除不存在的任务会因码表校验失败抛 `ValueError` 而非 `ResearchError`。

## 影响

- CLI 新增 `task deposit <task_id>` 子命令；Web API 新增 `POST /api/tasks/{task_id}/deposit`（`task_not_found`/`report_missing` → 404，`already_deposited` → 409，其余 → 400）。
- CONTEXT.md 更新：新增 Knowledge Deposit 词条，CLI / Web API / Core Service / Research Workflow Boundary 条目相应修订。
- TODO.md 移除 "Automatic knowledge deposit into the Markdown Vault" 延期项。
- Web UI 的沉淀按钮（调用该 API）留待后续切片。
