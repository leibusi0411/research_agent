# Use a Web Research Markdown report template

Web Research will use one Markdown report structure in v1 with frontmatter fields `title`, `task_id`, and `created_at`, followed by `Summary`, `Findings`, and `Sources` sections. Findings use source-number references, Sources lists only Web Sources, and Local RAG uses a Local Result display rather than a Web Report File template. Workflow-internal research gaps are not rendered in the Web Report File.

## 演进注记

- 2026-09-18（R-277，ADR-0054）：模板在 `Summary` 与 `Findings` 之间插入
  **按子任务分章的报告正文**（`## 章节标题`，来自 CuratorOutput.sections）；
  无 sections 的旧任务保持原三段模板。本 ADR "不渲染 research gaps" 的
  约定不变——ADR-0054 的 "Gaps & open questions" 章是**子任务证据覆盖
  缺口**（该子任务无 findings 时的诚实声明），不是 Supervisor 的
  workflow-internal `research_gaps`，后者仍不进入报告文件。
