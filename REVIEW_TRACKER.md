# 项目进展跟踪

> **文件组织**：本文档只分三部分 —
> 1. **项目阶段**：大的阶段计划与当前进展
> 2. **上次 Review**：最近一次代码审查的发现、修复、待解决问题
> 3. **下一步建议**：按优先级排列的具体工作任务
>
> 每次 review 和修复完成后必须及时更新本文档。
>
> 最后更新：2026-07-02 | 全部 28 项问题已修复（原始 P2/P3 17 项 + 代码审查 11 项）| 当前：阶段 7 ✅

---

## 一、项目阶段

| 阶段 | 目标 | 状态 |
|------|------|------|
| 阶段 1 | 基础设施（Config、Workspace、TaskStorage、KB Indexing） | ✅ |
| 阶段 2 | Local RAG（SQLite FTS5 检索、CLI） | ✅ |
| 阶段 3 | Web Research 骨架（Schemas、Context、ToolGateway、StateGraph、Report） | ✅ |
| 阶段 4 | Web Research 真实运行时（Prompt Builders、StateGraphRunner、ProviderRuntime） | ✅ |
| 阶段 5 | 端到端流程跑通（正确性、边界情况、锁恢复） | ✅ |
| 阶段 6 | 前端页面完善 + 统一 EventStream（SSE + 流式输出 + 路由 + 组件拆分） | ✅ |
| 阶段 7 | 移植 LangGraph（StateGraph → LangGraph + SqliteSaver checkpoint） | ✅ |
| 阶段 8 | 功能全部实现（execution_trace.md、产物持久化、工厂重构、死代码清理） | 📋 计划中 |
| 阶段 9 | 健壮性优化（错误处理、可观测性、类型安全、lint/type-check） | 📋 计划中 |

---

## 二、上次 Review（2026-07-02）

### 审查范围

全部 18 个 Python 源文件（core/、api/、web/、cli.py）的全面代码审查。

### 死代码清理（已删除 5 项）

| 文件 | 类型 | 描述 |
|------|------|------|
| web/provider_runtime.py | import | `ChatModelClient` 未使用 |
| web/provider_runtime.py | import | `TaskStore` 未使用 |
| web/provider_runtime.py | import | `Workspace` 未使用 |
| web/provider_runtime.py | import | `ToolGateway` 未使用 |
| web/executor.py | function | `_validate_synthesis_payload` 定义但从未调用 |

### 待解决问题（共 0 项）

所有 P1/P2/P3 项目已于 2026-07-02 修复完成。

### 安全审查

✅ **无 P1 安全问题**：
- 无硬编码密钥/密码
- 所有 SQL 查询已参数化，无注入风险
- 文件操作安全

### 已完成修复

| 项目 | 状态 |
|------|------|
| 删除 provider_runtime.py 4 个未使用 import | ✅ |
| 删除 executor.py 未使用函数 `_validate_synthesis_payload` | ✅ |
| R-100 提取 graph.py 节点函数为模块级函数 | ✅ 2026-07-02 |
| R-101 提取 state_graph.py Mermaid 和步骤渲染辅助函数 | ✅ 2026-07-02 |
| R-102 拆分 api/app.py create_app 路由注册到独立函数 | ✅ 2026-07-02 |
| R-103 拆分 executor.py `_execute_with_tools` 为三个方法 | ✅ 2026-07-02 |
| R-104 提取 kb.py `rebuild` 的 `_build_temp_index` 和 `_atomic_swap_index` | ✅ 2026-07-02 |
| R-105 提取 kb.py `_paragraph_chunks` 的 `_flush_pending` 和 `_split_long_paragraph` | ✅ 2026-07-02 |
| R-106 提取 prompt_builders.py `_format_tool_result` 辅助函数 | ✅ 2026-07-02 |
| R-107 提取共享 `read_lock_task_id` 到 workspace.py | ✅ 2026-07-02 |
| R-108 统一 URL 验证为共享 `is_valid_http_url` | ✅ 2026-07-02 |
| R-109 添加 `list_finished_tasks` 返回类型注解 | ✅ 2026-07-02 |
| R-110 添加 `_run_background` 类型注解 | ✅ 2026-07-02 |
| R-111 添加 `_cleanup_background` 类型注解 | ✅ 2026-07-02 |
| R-112 重命名 `_seq` → `seq`（公开字段） | ✅ 2026-07-02 |
| R-113 添加共享 `check_required_field` 验证辅助函数 | ✅ 2026-07-02 |
| R-114 添加 `_submit_background_task` 包装器管理锁生命周期 | ✅ 2026-07-02 |
| R-115 添加 chroma_store.py `_closed` 访问注释 | ✅ 2026-07-02 |
| R-116 用常规实例属性替代 `object.__setattr__` | ✅ 2026-07-02 |
| R-120 `_execute_node` 仅 route=="continue_execution" 时按白名单过滤 | ✅ 2026-07-02 |
| R-121 空执行不递增 `retrieval_round` | ✅ 2026-07-02 |
| R-122 添加 orphan subtask 日志警告 | ✅ 2026-07-02 |
| R-123 使用 `revision_subtask_ids` 替代 `[-3:]` 硬编码截断 | ✅ 2026-07-02 |
| R-124 research_gaps 使用专用 `"research_gap"` kind | ✅ 2026-07-02 |
| R-125 验证器增加列表元素类型检查 | ✅ 2026-07-02 |
| R-126 `_safe_future_result` 添加 `Future` 类型注解 | ✅ 2026-07-02 |
| R-127 plan 步骤仅统计初始规划创建的子任务 | ✅ 2026-07-02 |
| R-128 从 ToolRegistry 动态生成工具描述 | ✅ 2026-07-02 |
| R-129 添加 `_safe_int` 容错 int 转换 | ✅ 2026-07-02 |
| R-130 显式 route 检查消除 falsy 语义歧义（已在 R-120 中修复） | ✅ 2026-07-02 |

---

## 三、下一步建议

### 阶段 8（功能全部实现）

1. CLI `task show <id>` — 查看单个任务详情
2. Source 快照查看器（Web UI）

### 阶段 9（健壮性优化）

1. LLM 调用重试机制
2. 结构化日志 + LLM 耗时记录
3. mypy/pyright 类型检查
4. ruff lint 集成
5. API rate limit
6. SIGINT 优雅退出
