# ADR-0055: 移除 CLI 界面，Web UI 为唯一交互面

- 日期：2026-09-21（R-284）
- 状态：已接受
- 关联：ADR-0011（CLI 无 daemon 流式进度，本 ADR 移除其载体）、ADR-0012（分层包与独立 Web 前端）、ADR-0038（最小 FastAPI 面）、ADR-0047（常驻 Settings 页）

## 背景

v1 的设计是 CLI + Web UI 双界面共享 CoreService。实际演进中交互能力全部
落在 Web UI：任务行内详情、调研后接地对话、References 显式导入、Settings
读写双态、折叠卡片等均无 CLI 对应物；CLI 侧反而持续产生维护成本——
`both` 命令的错误处理、进度打印函数（`_print_web_event`/`_first_item`）、
子进程测试、文档双份使用说明。用户决定移除 CLI，收敛为单一交互面。

## 决策

1. **删除 `research_agent.cli` 模块与 `research-agent` 入口点**
   （pyproject `[project.scripts]` 同步移除）。
2. **删除仅服务 CLI 的能力面**：`CoreService.run_both`、`_run_family_result`、
   `_safe_future_result`（`both` 双跑语义随之移除；两工作流仍可通过 Web UI
   或 API 并行发起）。
3. **`CoreService.run_web_research` / `run_local_research` 保留**——它们是
   测试与脚本复用的应用层便捷入口，不是 CLI 专属。
4. **`config_missing` 文案改为 Web 引导**："User config is missing.
   Configure in the Settings page first."（原 "Run research-agent init first."）。
5. **文档同步**：AGENTS/README/USAGE 移除 CLI 章节；CONTEXT.md 各词条中
   的 CLI 措辞修订；USAGE 的初始化与使用说明以 Web UI 为准。

## 后果

- 初始化改走 Web UI 常驻 Settings 页（ADR-0047）；未配置时 Research 页
  仍可用，发起调研报 `config_missing` 引导到 Settings。
- 事件流的 CLI 消费路径消失；SSE/Bus/events.jsonl 分层不变。
- `research_agent.cli` 相关测试（子进程、both 错误矩阵、进度打印格式）
  一并移除；deposit/task 管理保留 API 缝测试。
- `both` 场景（同问题双跑）如需恢复，应由 Web UI 提供而不是 CLI。

## 演进注记

- 2026-09-21（R-284）：初版落地。
