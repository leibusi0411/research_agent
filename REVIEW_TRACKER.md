# 项目进展跟踪

> **文件组织**：本文档只分三部分 —
> 1. **项目阶段**：大的阶段计划与当前进展
> 2. **本轮 Review**：最近一次代码审查的发现、修复、待解决问题
> 3. **下一步建议**：按优先级排列的具体工作任务
>
> 每次 review 和修复完成后必须及时更新本文档。
>
> 最后更新：2026-07-20 | 测试：150 passed（Python）+ 15 passed（前端 Vitest）| 本轮 18 项问题全部修复 ✅（R-131~R-148）| 当前：阶段 7 ✅ → 阶段 8 📋

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

## 二、本轮 Review（2026-07-17）

### 审查范围

当前**未提交的工作区改动**（git diff HEAD），内容为两大特性：

1. **原生 function calling 迁移** — `complete_tool` 替换 JSON-mode + schema repair（providers.py、role_invocation.py、executor.py、graph.py、prompt_builders.py 及对应测试）
2. **任务删除功能** — `DELETE /api/tasks/{task_id}` 端点 + 前端 Tasks 页删除按钮（service.py、workspace.py、app.py、App.tsx、TasksPage.tsx、api.ts 及对应测试）

审查文件：后端 9 个源文件 + 6 个测试文件，前端 4 个源文件 + 2 个测试文件（排除 styles.css、dist/ 构建产物）。另运行全量测试套件验证。

### 审查总结

改动方向正确、测试覆盖基本到位。值得肯定的方面：

- `workspace.delete_task_folder` 通过 `validate_task_id` + resolve 双重检查防路径遍历；`_delete_report_file` 对 report 路径做了 web_reports_dir 逃逸检查；SQL 全部参数化，无注入风险
- `_normalize_tool_call_payload` 对各类 provider 变体的归一化处理有对应测试覆盖
- 所有 `invoke_role_json` 调用点已同步迁移到新签名，`build_schema_repair_prompt` 已彻底移除无残留
- 前端无 XSS 风险（无 `dangerouslySetInnerHTML`）；TasksPage 消除了嵌套交互元素的可访问性问题
- 无硬编码密钥；executor 线程池异常路径完整

### 待解决问题（共 0 项）

✅ 全部 18 项已于 2026-07-17 修复完成。

<details>
<summary>已修复详情（点击展开）</summary>

#### P0（阻塞）
| 编号 | 描述 | 修复 |
|------|------|------|
| R-131 | 12 个测试离线确定性被 A+G 自动创建真实 client 破坏 | ✅ 添加 `RESEARCH_AGENT_OFFLINE` env var + 测试注入 fake client |

#### P1
| 编号 | 描述 | 修复 |
|------|------|------|
| R-132 | 用错误文案字符串匹配决定 404 | ✅ 改用 `code="task_not_found"` 专用错误码 |
| R-133 | 所有异常包装为 `schema_validation_failed` | ✅ 分离 LLM 调用异常（`llm_call_failed`）和校验异常 |
| R-141 | 删除任务无确认步骤 | ✅ 添加 `window.confirm` 确认对话框 |

#### P2
| 编号 | 描述 | 修复 |
|------|------|------|
| R-134 | 删除操作非事务化 | ✅ DB 记录先删（权威移除），文件清理降级为 best-effort + 日志警告 |
| R-135 | busy 检查 fail-open | ✅ 不可读锁按 busy 处理（fail-closed） |
| R-142 | 全局单槽 busy 并发竞态 | ✅ 改用 `deletingTaskIds: string[]` 数组跟踪多并发删除 |
| R-143 | openTask 无错误处理 | ✅ 添加 try/catch + 删除中任务守卫 |
| R-144 | 删除未清理 Research 页结果 | ✅ 同步清理 `localResult`/`webResult`/对应 events |

#### P3
| 编号 | 描述 | 修复 |
|------|------|------|
| R-136 | `_parse_llm_json` 单引号替换损坏撇号 | ✅ 添加 `ast.literal_eval` 优先尝试 |
| R-137 | docstring 声称保证 schema 匹配 | ✅ 修正为 "caller MUST validate" |
| R-138 | 删除任务后 SSE 轮询空转 30 分钟 | ✅ 检测 task 目录消失时主动 break |
| R-139 | prompt_builders.py 末尾无换行 | ✅ 添加文件末尾换行 |
| R-140 | executor e2e 测试无断言 | ✅ 添加 `tool_calls` 结构断言 |
| R-145 | api.ts deleteTask 未 encodeURIComponent | ✅ 添加 `encodeURIComponent(taskId)` |
| R-146 | 删除测试只覆盖成功路径 | ✅ 添加 409 busy 失败路径测试 |
| R-147 | e2e toBeHidden 不精确 | ✅ 改为 `toHaveCount(0)` |
| R-148 | EventSource 清理函数从未调用 | ✅ 添加 `useRef` cleanup 保存并在启动新任务/卸载时调用 |

</details>

### 安全审查

✅ **无 P1 安全问题**：
- 无硬编码密钥/密码
- SQL 全部参数化，无注入风险
- 删除路径有遍历防护（validate_task_id + resolve + reports_dir 逃逸检查）
- 前端无 XSS 风险

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
| R-131 修复 12 个 test_local_research.py 失败测试（A+G 离线确定性） | ✅ 2026-07-17 |
| R-132 用 `code="task_not_found"` 替换字符串匹配 404 | ✅ 2026-07-17 |
| R-133 `invoke_role_json` 分离 LLM 异常与校验异常 | ✅ 2026-07-17 |
| R-134 删除操作事务化（DB 先行，文件清理 best-effort） | ✅ 2026-07-17 |
| R-135 busy 检查 fail-closed（不可读锁按 busy 处理） | ✅ 2026-07-17 |
| R-136 `_parse_llm_json` 添加 `ast.literal_eval` 安全 fallback | ✅ 2026-07-17 |
| R-137 修正 `complete_tool` docstring 虚假保证声明 | ✅ 2026-07-17 |
| R-138 SSE 轮询检测 task 目录消失主动终止 | ✅ 2026-07-17 |
| R-139 prompt_builders.py 末尾添加换行符 | ✅ 2026-07-17 |
| R-140 executor e2e 测试添加结构断言 | ✅ 2026-07-17 |
| R-141 删除任务添加 `window.confirm` 确认对话框 | ✅ 2026-07-17 |
| R-142 `busy` 改为 `deletingTaskIds[]` 消除并发竞态 | ✅ 2026-07-17 |
| R-143 `openTask` 添加 try/catch + 删除中守卫 | ✅ 2026-07-17 |
| R-144 `deleteTask` 同步清理 Research 页结果状态 | ✅ 2026-07-17 |
| R-145 api.ts `deleteTask` 添加 `encodeURIComponent` | ✅ 2026-07-17 |
| R-146 添加删除失败（409 busy）测试 | ✅ 2026-07-17 |
| R-147 e2e 断言 `toBeHidden` → `toHaveCount(0)` | ✅ 2026-07-17 |
| R-148 EventSource cleanup 保存到 ref 并正确清理 | ✅ 2026-07-17 |

---

## 三、下一步建议

### 立即

1. **提交当前工作区改动** — 29 个文件包含 function calling 迁移 + 任务删除 + R-131~R-148 全部修复，建议一次 squash commit

### 阶段 8（功能全部实现）← 当前

1. CLI `task show <id>` — 查看单个任务详情
2. Source 快照查看器（Web UI）
3. `execution_trace.md` 生成与持久化
4. 工厂重构 + 死代码清理

### 阶段 9（健壮性优化）

1. LLM 调用重试机制
2. 结构化日志 + LLM 耗时记录
3. mypy/pyright 类型检查
4. ruff lint 集成
5. API rate limit
6. SIGINT 优雅退出
