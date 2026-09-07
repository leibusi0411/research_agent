# 项目进展跟踪

> **文件组织**：本文档只分三部分 —
> 1. **项目阶段**：大的阶段计划与当前进展
> 2. **本轮 Review**：最近一次代码审查的发现、修复、待解决问题
> 3. **下一步建议**：按优先级排列的具体工作任务
>
> 每次 review 和修复完成后必须及时更新本文档。
>
> 最后更新：2026-09-06 | 测试：169 passed（Python，含 6 个 e2e）+ 20 passed（前端 Vitest）+ 1 passed（Playwright e2e）| 本轮三轮审查共 24 项问题处理完毕 ✅（R-149~R-173）| 新功能：Knowledge Deposit（ADR-0045）+ Web UI 沉淀按钮

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

## 二、本轮 Review（2026-09-06）

### 审查范围

**Knowledge Deposit（知识沉淀）** 新功能（git diff HEAD）：把已完成 Web Research 任务的 Web Report File 显式复制进知识库 vault 的 `web-research/` 子目录，打通 Web → Local 的单向联动（两条线的执行边界不变）。

- 新增 `core/deposit.py` + `CoreService.deposit_web_report`；CLI `task deposit <task_id>`；API `POST /api/tasks/{task_id}/deposit`
- 新增 ADR-0045（显式演进 ADR-0006 的适用范围：vault 允许 deposit 追加新笔记，ingestion 对既有笔记仍只读）
- 附带修复 R-132 遗留：`task_not_found` 此前未注册进 `VALID_ERROR_CODES`，删除不存在任务会抛 `ValueError` 而非 404
- 测试：`tests/test_kb_deposit.py` 18 个（service 11 + CLI 子进程 3 + API 4，含 DELETE 404 回归），全部离线确定
- 文档：CONTEXT.md（新词条 + 4 处条目修订）、TODO.md（移除对应延期项）、USAGE.md、README.md、AGENTS.md

审查方式：subagent 独立审查 + 全量测试验证。

### 审查总结

设计约束（显式动作、只增不改、幂等、统一错误码）落实正确，无 P0 问题。发现 8 项（P1×2、P2×2、P3×4），全部当日修复。

### 待解决问题（共 0 项）

✅ 三轮审查共 24 项（R-149~R-173），22 项修复、2 项明确接受或记录在案（R-165、R-173），均于 2026-09-06 处理完毕。

### 第二轮复审（2026-09-06，修复后终审）

验证 R-149~R-156 修复全部成立，另确认 API 路由无匹配冲突。新发现 8 项（P2×1、P3×7），7 项当日修复，1 项明确接受。

#### P2
| 编号 | 描述 | 修复 |
|------|------|------|
| R-157 | 并发 deposit 同名报告的 TOCTOU + tmp 文件撞名 | ✅ `_claim_deposit_path` 用 `O_CREAT\|O_EXCL` 原子占位，tmp 名混入 task_id |

#### P3
| 编号 | 描述 | 修复 |
|------|------|------|
| R-158 | deposit docstring 漏 `config_invalid` 错误码 | ✅ 补齐 |
| R-159 | 报告文件读取的 UnicodeDecodeError 未包装 | ✅ 包装为 `file_write_error`（对称 R-149） |
| R-160 | 幂等 marker 全文件子串匹配，正文误提 task_id 会误判 | ✅ 只扫 frontmatter 区（`_frontmatter_block`） |
| R-161 | 幂等机制与 report.py frontmatter 格式隐式耦合 | ✅ 两模块互加指向注释 |
| R-162 | 崩溃遗留 `{stem}.tmp` + 注释误称 "same pattern as kb.py" | ✅ 失败路径清理 tmp/占位文件；注释改为如实描述 |
| R-163 | 文件名后缀逻辑硬编码 `.md` | ✅ 改用 `Path.suffix`（并入 `_claim_deposit_path`） |
| R-164 | README 历史错行：报告位置误写为 `tasks/<task_id>/` | ✅ 改为 `reports/web/`（本轮顺带发现的历史问题） |
| R-165 | 测试假设 "init_config 不写 vault"（`vault.rmdir()`） | ⚠️ 接受：若假设打破会以 OSError 大声自暴露 |

### 第三轮审查（2026-09-06，Web UI 沉淀按钮 + deposit 引导重建）

本轮改动：`api.ts` 新增 `depositTask`；`ResultView.tsx` 新增 `DepositPanel`（deposit → 成功后引导 Rebuild Index）；闭环集成测试（deposit → rebuild → Local RAG 命中沉淀笔记）；e2e 增加 deposit 流程。审查发现 7 项（P1×1、P2×2、P3×4），全部修复；另修复 2 项既存 e2e 红线（该套件此前整体失败但未被发现）。

#### P1
| 编号 | 描述 | 修复 |
|------|------|------|
| R-168 | DepositPanel 无 key，Tasks 页 web→web 切换时 deposit 状态残留（实证复现） | ✅ `key={result.task_id}` + 双 web 任务切换回归测试 |

#### P2
| 编号 | 描述 | 修复 |
|------|------|------|
| R-166 | e2e 既存红线①：events mock 返回 JSON，EventSource 因 MIME 不符拒绝连接，phase 文本从不出现（HEAD 可复现） | ✅ `fulfillEvents` 按 Accept 头分流：EventSource 给 SSE body，普通 fetch 给 JSON |
| R-167 | e2e 既存红线②：Playwright 默认 dismiss 对话框，delete 的 `window.confirm` 静默中止 | ✅ `page.on("dialog", d => d.accept())` |
| R-169 | USAGE.md API 表缺 deposit / delete 端点 | ✅ 补齐 |

#### P3
| 编号 | 描述 | 修复 |
|------|------|------|
| R-170 | `[already_deposited]` 前缀字符串匹配脆弱 | ✅ `api.ts` 抛 `ApiError`（带 `code` 属性），按码分支 |
| R-171 | rebuild 失败吞掉错误详情 | ✅ 展示 `[code] message`，按钮转为 retry |
| R-172 | `web/test-results/.last-run.json` 被 git 跟踪 | ✅ 加入 .gitignore（取消跟踪留待提交时 `git rm --cached`） |
| R-173 | `test_api_second_same_family_start_returns_busy_without_fake_task` 全量运行时偶发失败（重跑全绿） | ⚠️ 记录在案：疑为并发时序敏感，与本改动无关，待观察 |

### 已验证（终审后）

- `uv run pytest -m "not e2e"` — 163 passed
- `uv run pytest tests/test_web_e2e_simple.py -m e2e`（真实 LLM）— 通过
- `cd web && npx vitest run` — 20 passed
- `cd web && npx playwright test` — 1 passed（含 deposit→rebuild e2e 流程）

<details>
<summary>已修复详情（点击展开）</summary>

#### P1（应修）
| 编号 | 描述 | 修复 |
|------|------|------|
| R-149 | `_already_deposited` 遇非 UTF-8 笔记抛 UnicodeDecodeError 逃逸 | ✅ `except (OSError, UnicodeDecodeError)` 跳过 |
| R-150 | REVIEW_TRACKER.md 未按维护规则更新 | ✅ 本次更新补齐 |

#### P2
| 编号 | 描述 | 修复 |
|------|------|------|
| R-151 | AGENTS.md 测试/ADR 计数过时 | ✅ 166 测试 / 45 ADR |
| R-152 | 测试缺口：已删报告、同名冲突 -2、API 409、DELETE 404 回归 | ✅ 补 7 个测试（9→16） |

#### P3
| 编号 | 描述 | 修复 |
|------|------|------|
| R-153 | CLI 非法 task_id 兜底为 runtime_error，与 API 不一致 | ✅ 入口先 `validate_task_id` 转 `config_invalid` |
| R-154 | deposit 写入非原子 + vault 目录缺失时静默创建整棵目录树 | ✅ tmp+rename 原子写入；vault 缺失报 `config_invalid` |
| R-155 | `_resolve_report_path` 无逃逸检查 | ✅ 注释说明：写入端只取 basename，落点严格在 `<vault>/web-research/` 内 |
| R-156 | README.md 未提及 deposit 功能 | ✅ 补 Knowledge Deposit 小节 |

</details>

### 安全审查

✅ 无新增风险面：写入端只取报告文件 basename，落点严格限制在 `<vault>/web-research/`；task_id 经 `validate_task_id` 校验；vault 目录缺失时显式报错而非静默创建；无密钥、无注入面。

### 已验证

- `uv run pytest -m "not e2e"` — 162 passed（终审后）
- `uv run pytest tests/test_web_e2e_simple.py -m e2e`（真实 LLM）— 重跑通过（首轮失败为线上模型输出抖动，与本改动无关）
- `cd web && npm run test` — 15 passed

---

## 附：上一轮 Review（2026-07-17）存档

### 审查范围（2026-07-17）

当时**未提交的工作区改动**（git diff HEAD），内容为两大特性：

1. **原生 function calling 迁移** — `complete_tool` 替换 JSON-mode + schema repair（providers.py、role_invocation.py、executor.py、graph.py、prompt_builders.py 及对应测试）
2. **任务删除功能** — `DELETE /api/tasks/{task_id}` 端点 + 前端 Tasks 页删除按钮（service.py、workspace.py、app.py、App.tsx、TasksPage.tsx、api.ts 及对应测试）

### 审查总结（2026-07-17）

改动方向正确、测试覆盖基本到位。值得肯定的方面：

- `workspace.delete_task_folder` 通过 `validate_task_id` + resolve 双重检查防路径遍历；`_delete_report_file` 对 report 路径做了 web_reports_dir 逃逸检查；SQL 全部参数化，无注入风险
- `_normalize_tool_call_payload` 对各类 provider 变体的归一化处理有对应测试覆盖
- 所有 `invoke_role_json` 调用点已同步迁移到新签名，`build_schema_repair_prompt` 已彻底移除无残留
- 前端无 XSS 风险（无 `dangerouslySetInnerHTML`）；TasksPage 消除了嵌套交互元素的可访问性问题
- 无硬编码密钥；executor 线程池异常路径完整

✅ 全部 18 项（R-131~R-148）已于 2026-07-17 修复完成。

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
| R-149 `_already_deposited` 跳过非 UTF-8 笔记（UnicodeDecodeError 逃逸） | ✅ 2026-09-06 |
| R-150 REVIEW_TRACKER 随本轮更新 | ✅ 2026-09-06 |
| R-151 AGENTS.md 计数更新（测试数 / ADR 数） | ✅ 2026-09-06 |
| R-152 deposit 补 7 个覆盖测试（含 DELETE 404 回归） | ✅ 2026-09-06 |
| R-153 CLI deposit 非法 task_id 报 `config_invalid` | ✅ 2026-09-06 |
| R-154 deposit 原子写入 + vault 缺失守卫 | ✅ 2026-09-06 |
| R-155 `_resolve_report_path` 逃逸检查说明注释 | ✅ 2026-09-06 |
| R-156 README 补 Knowledge Deposit 小节 | ✅ 2026-09-06 |
| R-157 deposit 并发 TOCTOU：`O_EXCL` 原子占位 + task-unique tmp 名 | ✅ 2026-09-06 |
| R-158 deposit docstring 补 `config_invalid` | ✅ 2026-09-06 |
| R-159 报告读取 UnicodeDecodeError 包装为 `file_write_error` | ✅ 2026-09-06 |
| R-160 幂等检查限定 frontmatter 区 | ✅ 2026-09-06 |
| R-161 deposit ↔ report.py frontmatter 格式双向注释 | ✅ 2026-09-06 |
| R-162 deposit 失败路径清理 tmp/占位文件 + 注释失实修正 | ✅ 2026-09-06 |
| R-163 deposit 文件名后缀改用 `Path.suffix` | ✅ 2026-09-06 |
| R-164 README 报告位置错行修正（`reports/web/`） | ✅ 2026-09-06 |
| R-165 接受：`vault.rmdir()` 测试假设脆弱（自暴露） | ⚠️ 2026-09-06 |
| R-166 e2e 既存红线：events mock JSON MIME 导致 EventSource 拒连 | ✅ 2026-09-06 |
| R-167 e2e 既存红线：Playwright 默认 dismiss confirm 对话框 | ✅ 2026-09-06 |
| R-168 DepositPanel 加 `key={task_id}` 消除跨任务状态残留 | ✅ 2026-09-06 |
| R-169 USAGE.md API 表补 deposit/delete 端点 | ✅ 2026-09-06 |
| R-170 `ApiError` 携带错误码，替代字符串前缀匹配 | ✅ 2026-09-06 |
| R-171 rebuild 失败展示错误详情 | ✅ 2026-09-06 |
| R-172 `web/test-results/` 加入 .gitignore | ✅ 2026-09-06 |
| R-173 记录：`test_api_second_same_family_start_returns_busy_without_fake_task` 全量运行偶发失败 | ⚠️ 2026-09-06 |

---

## 三、下一步建议

### 立即

1. **提交本日改动** — Knowledge Deposit 后端 + Web UI 沉淀按钮 + e2e 修复 + R-149~R-173 全部处理完毕；提交时顺带 `git rm --cached web/test-results/.last-run.json`（R-172）
2. **下一大步：Local 知识注入 Web Planner**（方案 2）— deposit 打通 Web→Local 后，反向让 Planner 看到本地已有知识，形成"调研→沉淀→复用"回路；需新 ADR 显式演进 Research Workflow Boundary

### 阶段 8（功能全部实现）

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
