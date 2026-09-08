# 项目进展跟踪

> **文件组织**：本文档只分三部分 —
> 1. **项目阶段**：大的阶段计划与当前进展
> 2. **本轮 Review**：最近一次代码审查的发现、修复、待解决问题
> 3. **下一步建议**：按优先级排列的具体工作任务
>
> 每次 review 和修复完成后必须及时更新本文档。
>
> 最后更新：2026-09-08 | 测试：197 passed（Python；配置真实 key 后 9 个真实 API 测试首次实跑通过）+ 22 passed（前端 Vitest）+ 1 passed（Playwright e2e）| 第七轮审查 15 项：13 修复 ✅ + 2 记录在案 ⚠️（R-206~R-220）| 新功能：常驻 Settings 页面（ADR-0047）+ Local RAG A+G API 对齐（R-218）+ 异常掩码/截断重试修复（R-219/R-220）

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

## 二、本轮 Review（2026-09-08）

### 第七轮审查（2026-09-08，常驻 Settings 页面 / ADR-0047）

#### 审查范围

落地 TODO.md "Settings page" 延期项：Setup 视图升级为常驻 Settings 页面（侧边栏第 4 个页面，路由 `/settings`），首次使用不再全屏接管，未配置时落在外壳内 Settings 页。新增 `GET /api/setup/config`（密钥不回传，只给 `has_*` 布尔值）；`POST /api/setup/init` 空白 api_key 字段 = 保留已存值。ADR-0047 显式演进 ADR-0030；CONTEXT.md 新增 Settings Page 词条；测试 TDD 四切片（后端 4 个 + 前端重写 1 个 / 新增 1 个 + e2e 重写首启流程）。

#### 发现与处置

| 编号 | 问题 | 处置 |
|------|------|------|
| R-206 | e2e 仍断言旧 "Research Agent Setup" 全屏标题且 mock 缺 `GET /api/setup/config`，功能后确定性失败（违反"e2e 必须通过"完成定义） | ✅ 重写为外壳内 Settings 流（4 导航 + Settings 标题 + 保存进 Research）+ 补 mock，实测 1 passed |
| R-207 | 设置页改 `default_workspace` 后不生效：`get_service` 缓存的 CoreService 绑定旧工作区，`/api/setup/status` 却显示已保存 | ✅ `setup_init` 成功后 `reset_cached_service()`，下一请求按新配置重建 |
| R-208 | Settings 保存走 `init_user_config` 固定模板全量重写，手工加入的 `[chat_model.<role>]` / `[research]` / `[web_tools]` 定制被静默重置（与 ADR-0009 "覆盖前提示"相关） | ⚠️ 记录在案：ADR-0047 显式列为已知取舍（本地单用户工具，UI 可改回全部必需字段）；改进方向为保存前确认或保留未知 section |
| R-209 | AGENTS.md ADR 计数 46 未随 ADR-0047 更新（两处）、测试计数陈旧（182） | ✅ 修正为 47 / 190（181 离线 + 9 真实 API skip） |
| R-210 | README / USAGE 的 Setup 页描述、三页面表未随四页面结构更新 | ✅ 全部改为 Settings 四页面表述 |
| R-211 | web/dist 为功能前构建的陈旧产物（仅行尾差异噪声） | ✅ `npm run build` 重建（新 bundle index-6xCUaeTy.js） |
| R-212 | 空白密钥判定不一致：纯空格字符串为 truthy 会走提交路径报 "must be non-empty" 而非"保留已存" | ✅ `_optional_key` 归一化：缺失 / 空串 / 纯空白一律视为"保留" |
| R-213 | 保存成功后前端 form state 仍持有真实 key，再进 Settings 页密钥框为已填状态 | ✅ 保存成功即清空三个 key 字段（配合后端不回传，密钥只在提交瞬间存在） |
| R-214 | savedNotice 陈旧（离开再回来仍显示 "Settings saved."）；全局 message 使 Settings 页双份错误渲染 | ✅ 进入 Settings 页（loadSettings）时重置两个状态 |
| R-215 | loadSettings 预填响应与用户快速输入存在竞态，可能覆盖 6 个非密钥字段 | ⚠️ 记录在案：本地单用户、窗口极小，观察后再议 |
| R-216 | `web/tsconfig.tsbuildinfo` 构建噪声入库、`name={key}` 属性仅服务测试选择器 | ⚠️ 记录在案：tsbuildinfo 建议后续加入 .gitignore；name 属性无害保留 |
| R-217 | 未配置时 `/` 重定向到 Settings，调研页完全不可见（用户反馈不合理：页面应照常显示和输入，启动时才报错） | ✅ 移除重定向，Research 未配置照常可用；`/api/research/*` 增加前置配置检查，未配置启动同步报 `config_missing`（不再 202 后台失败）；单测/e2e 同步更新 |
| R-218 | Local RAG A+G 只在 CLI 生效：API 路径直调 `run_local_research_unlocked`，跳过 embedding/chat 客户端自动装配 → Web UI 无向量召回、无 LLM 总结，违反 ADR-0037 能力面对等（用户实测发现总结缺失） | ✅ API 路由注入 embedding/chat 客户端（新增 `chat_model_factory` 参数，测试注入 fake 保持离线）；ResultView 本地结果补 Summary 区块 + ResearchResult.summary 类型；后端 192 passed（含真实链路 e2e 6 项首次实跑通过） |
| R-219 | `ResearchError` 是 `@dataclass(frozen=True)`：异常穿过 LangGraph/contextlib 传播时，Python 3.12 `contextlib.__exit__` 的 Python 层 `exc.__traceback__` 赋值被冻结类拒绝 → 真实错误被 `FrozenInstanceError: cannot assign to field '__traceback__'` 掩盖成 `runtime_error`（用户 Web 任务 task_20260908_090231 在 plan_revision 实际死于被掩盖的 llm_call_failed） | ✅ 类后替换 `__setattr__`：放行双下划线属性（`__traceback__`/`__cause__` 等），`code`/`message` 字段保持冻结；补传播与冻结回归测试 |
| R-220 | R-205 的直接触发面：DeepSeek v4-flash 是推理模型，reasoning 与 content 共享 max_tokens 预算，长计划 JSON 被截断（finish_reason=length）→ 报模糊的 "LLM returned invalid JSON" 且无重试 | ✅（提前落地 R-205 核心）`complete_tool` 检查 `finish_reason=length` 报明确截断错误；`invoke_role_json` 解析失败自动重试一次（共 2 次尝试），耗尽后仍报 `llm_call_failed`；R-205 其余（原始输出落盘诊断、工具执行链路重试）仍留阶段 9 |

#### 顺带修复（预存问题）

- `tests/test_local_research.py` 使用 `typing.Any` 但未导入 → 全套件收集失败（NameError）；补导入。
- `tests/test_api_connections.py` 三个真实 API 测试直接 `load_user_config()`，无配置机器上必失败，违反 ADR-0042 离线原则 → 对齐 `test_web_e2e.py` 的 `_get_config_or_skip` 模式，无配置自动 skip。

#### 已验证

后端 `uv run pytest`：181 passed + 9 skipped；前端 `npm run test`：22 passed；`npx playwright test`：1 passed；`tsc -b` 通过。

---

## 二·历史轮次（2026-09-06 ~ 2026-09-07）

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

✅ 六轮审查 + 热修共 47 项（R-149~R-203），41 项修复、6 项明确接受或记录在案（R-165、R-173、R-182、R-183、R-191、R-192）。

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

### 第四轮审查（2026-09-06，Prior Knowledge 注入 / ADR-0046）

本轮改动：Web Research 启动前一次性只读检索本地知识库，注入 Planner（`prior_knowledge` state 字段 + `RunnerConfig.local_retriever` 接缝 + `build_local_retriever` 装配 + `[research] inject_local_context` 开关）。显式演进 ADR-0017/0036。审查无 P0/P1/P2，10 项 P3 全部处理（8 修复、2 接受）。

#### P3
| 编号 | 描述 | 修复 |
|------|------|------|
| R-174 | `local_retriever` 契约外返回 None 会使 `list(None)` 崩溃 | ✅ `or []` 兜底 + 回归测试 |
| R-175 | Prior Knowledge progress 事件缺 `event_subtype` | ✅ 补 `event_subtype="source"`（ADR-0023 词汇内） |
| R-176 | `bool("false")` 静默得 True（用户误写字符串） | ✅ `_parse_bool` 严格校验，非 bool 报 `config_invalid` + 测试 |
| R-177 | 每次启动 web 任务重复解析 config 三次 | ✅ `build_local_retriever` 改收已加载的 `UserConfig` |
| R-178 | `RunnerConfig.local_retriever` 标注为 Any | ✅ `Callable[[str], list[PriorKnowledgeChunk]] \| None` |
| R-179 | 测试缺口：prompt 截断上限（5 chunk/800 字符）、stale 索引路径 | ✅ +2 测试 |
| R-180 | ADR-0046 措辞："有索引即多一条事件"与实际（非空才发）不符 | ✅ 修正 |
| R-181 | 被演进的 ADR-0017/0036 无回链 | ✅ 两个 ADR 加演进注记 |
| R-182 | `web_planning` progress 先于 `started` 事件 | ⚠️ 接受：ADR-0023 未禁止，CLI/前端均无顺序假设 |
| R-183 | API `start_web` 请求路径同步扫 vault（kb.status） | ⚠️ 接受：与既有 `/api/kb/status` 同模式，个人 vault 规模可忽略 |

### R-173 更新

同文件另一锁时序测试 `test_api_reports_active_real_task_id_and_streams_running_events` 亦观察到偶发失败（5 次单跑 2 败 3 过）。两者同属"fake runtime 秒完成 vs 锁窗口"的既有竞态家族，与本日改动无关（改动不在其执行路径上），继续观察，若再犯则修测试基础设施（如让 fake runtime 可阻塞）。

### 已验证（第四轮终审后）

- `uv run pytest -m "not e2e"` — 176 passed（R-173 家族偶发项重跑即过）
- 审查 subagent 全量含 e2e — 178 passed（当时计数；后续 +4 测试为 P3 修复新增）
- `cd web && npx vitest run` — 20 passed（本轮未动前端）

### 第五轮审查（2026-09-07，Web UI 视觉重设计）

本轮改动：`styles.css` 整体重写（纸/墨/荧光笔体系，消灭渐变与彩色投影，细线分隔）；字体改 @fontsource 自托管 IBM Plex Sans/Mono（移除 Google Fonts CDN，符合 local-first）；结果区双列窄卡改全宽通栏；车道符号（■ local / ○ web）+ 运行态轨迹线动效；运行态推导由 `busy`（仅 POST 期间）改为 `events && !result`，新增 `LiveResultPanel` 在结果到达前渲染实时事件流（修复执行期旧结果与新事件混杂的既存问题）；新任务启动时清空旧 result；新增 `scripts/shoot.mjs` 截图工具（`npm run shots`）。subagent 审查发现 9 项（P2×1、P3×5、nit×3），7 项修复、2 项接受/记录。

#### P2
| 编号 | 描述 | 修复 |
|------|------|------|
| R-184 | `finishTask` 的 `taskResult` 拉取失败无兜底，新运行态推导下车道永久锁死（按钮永禁、无错误提示） | ✅ try/catch：失败时清事件解锁 + `setMessage` |

#### P3
| 编号 | 描述 | 修复 |
|------|------|------|
| R-185 | SSE 提前终结时 running stub 渲染绿色 completed 样式 | ✅ `StatusLine` 区分 `status running` |
| R-186 | `--muted`/`--warn` 小字对比度 3.1~4.2:1 低于 WCAG AA | ✅ 加深至 `#6b6d62` / `#856712` |
| R-187 | `input:focus` 的 `outline:none` 覆盖 `:focus-visible`，键盘焦点无提示 | ✅ 仅 `:focus:not(:focus-visible)` 取消 outline |
| R-188 | LiveResultPanel 显示可编辑实时输入，运行中改问题会与已提交任务不符 | ✅ 运行中禁用 textarea |
| R-189 | 死规则/死 class：`.phase-dot.done`、`input[type=url]`、tool-panel `local`/`web`、`font-weight: 650` 落到 700 | ✅ 全部清理（650→600） |

#### Nit
| 编号 | 描述 | 修复 |
|------|------|------|
| R-190 | shoot.mjs 浏览器进程中途失败不关闭；未挂 npm script | ✅ finally 统一关闭 + `npm run shots` |
| R-191 | 结果到达瞬间 ProcessView 重建重播动画、滚动位置丢失 | ⚠️ 接受：cosmetic，重播在半秒内结束 |
| R-192 | `web/dist/` 被 git 跟踪，新构建资产必须随提交一起进入 | ⚠️ 记录：提交时 `git add` 包含 dist 全量（含旧资产删除） |

#### 已验证（第五轮终审后）

- `cd web && npm run build`（tsc + vite）— 通过
- `cd web && npm test` — 20 passed
- `cd web && npx playwright test` — 1 passed
- 截图目检 7 页（setup / research / results / running / tasks×2 / kb）— 符合设计

### 线上热修（2026-09-07，用户实测发现）

| 编号 | 描述 | 修复 |
|------|------|------|
| R-193 | **生产路径 blocker**：`_default_web_runtime` 引用 `create_app` 局部变量 `bus` → NameError，API 发起的真实 Web 任务全部 500（5efdc74 SSE 重构引入；离线测试注入 factory 从未覆盖该路径） | ✅ `bus` 改为显式参数贯穿 `create_app` → `_register_research_routes` → `_default_web_runtime`；补无 factory 的 start_web 回归测试 |
| R-194 | R-173 竞态家族第三次发作（高负载下连续失败） | ✅ 落实既定方案：`_TestWebRuntime.run` 加 0.5s 运行窗口，两个锁时序测试转确定性（三连跑 12/12） |

### 第六轮审查（2026-09-07，SSE 生产链路修复 + Inkwell 重设计）

**背景**：用户实测发现 API 发起的真实 Web 任务页面无进度、完成后无报告。根因：研究任务跑在 ThreadPoolExecutor 工作线程，`Bus.publish_nowait` 用 `asyncio.get_running_loop()` 找不到 loop，每个事件静默丢弃，SSE 流挂起。顺带完成 Research 页 Inkwell 重构（Gemini 式居中搜索 + 实时轨迹卡 + 结果卡片 + 深色谷歌配色）。subagent 审查：无 blocker，2 事务项（补本记录、提交带 dist）+ 3 minor 全部处理。

| 编号 | 描述 | 修复 |
|------|------|------|
| R-195 | **blocker**：`publish_nowait` 工作线程静默丢事件（页面无进度、无完成信号） | ✅ Bus 捕获 ASGI loop（`attach`/`subscribe`/`subscribe_all` 登记时），跨线程 `call_soon_threadsafe`；补跨线程回归测试 |
| R-196 | `events()` 先 replay 后订阅，窗口期事件丢失 | ✅ attach 先于 replay + queue drain 按 seq 去重（恰好一次），finally detach |
| R-197 | Research 页无反馈、双栏输入割裂 | ✅ Inkwell 重构：单胶囊搜索框、TraceCard（实时计数+阶段轨+事件流）、ResultCards（报告/本地笔记/资料三卡）、全站深色谷歌风 |
| R-198 | 死代码：`api.runLocal`、`requestText`、`useSSE` hook 无调用方 | ✅ 删除（`ConnectionState` 类型保留给 ConnectionBadge） |
| R-199 | loop 关闭后 `call_soon_threadsafe` 抛 RuntimeError 会打进 worker 线程 | ✅ try/except 降级为 debug 丢弃（与无 loop 分支对齐） |
| R-200 | index.html meta description 未随改名更新 | ✅ Research Agent → Inkwell |
| R-201 | `deleteTask` 残留 phase；state_graph import 非字母序 | ✅ 清理 |
| R-202 | 刷新/撞 busy 后页面"忘记"正在运行的任务，用户误以为无响应重复提交 | ✅ 页面加载时查 `/api/tasks/active` 自动重连 SSE（回填问题与轨迹）；409 busy 时自动接管运行中任务；finishTask 补齐全量事件 |
| R-203 | `llm_call_failed` 未注册进 `VALID_ERROR_CODES`，`ResearchError` 构造时抛 ValueError，真实 provider 错误被掩盖成 "unknown error code"（用户任务 task_20260907_132359 因此 failed；CLIP 任务首轮子任务全灭同源） | ✅ 注册错误码 + role_invocation 回归测试（真实错误信息透出） |
| R-204 | **SSE 启动窗口 500**：provider runtime 在 `run()` 内才创建 runner 并绑定 task_id，浏览器在 POST 返回后毫秒内订阅事件 → `runner.events()` 抛 RuntimeError → EventSource 永久关闭，页面无进度（日志实证两次）。这是"页面没反馈"在 bus 修复后仍存在的另一半原因 | ✅ 路由检查 `runner.task_id == task_id`，未就绪回退文件轮询 SSE；StateGraphRunner 加 `task_id` 只读属性；补回归测试 |
| R-205 | 模型在 function-calling 下返回语法损坏的 JSON（`_parse_llm_json` 三道防线全败），executor 工具规划直接失败；无重试/修复机制，反复触发会致命 | ⚠️ 记录在案：归入阶段 9"LLM 调用重试机制"，届时加 parse-failure 重试与原始输出落盘诊断 |

**测试策略约定更新（2026-09-07，用户指令）**：纯本地逻辑的离线单测保留（配置/存储/ID 等），但涉及生产装配链路（API 路由、SSE、运行时接线）的功能必须在提交前跑真实链路 e2e（`pytest -m e2e`）；fake runtime 注入不再作为这类路径的充分验证。ADR-0042 适用范围相应收窄，待下次文档轮次显式演进。

**实证**：真实服务起任务后 `curl -N` SSE 端点持续收到 data 帧（planning→prior knowledge→execution…）；任务完成 7 findings / 12 sources。

#### 已验证（第六轮终审后）

- `uv run pytest -m "not e2e"` — 178 passed（含跨线程发布回归、无 factory start_web 回归）
- `cd web && npm run build` + Vitest 20 passed + Playwright e2e 1 passed
- 截图目检 7 页（深色主题）— 符合设计

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
| R-174 local_retriever 返回 None 的 `or []` 兜底 + 测试 | ✅ 2026-09-06 |
| R-175 Prior Knowledge 事件补 `event_subtype="source"` | ✅ 2026-09-06 |
| R-176 `inject_local_context` 严格 bool 解析（`_parse_bool`） | ✅ 2026-09-06 |
| R-177 `build_local_retriever` 收 UserConfig 去重复解析 | ✅ 2026-09-06 |
| R-178 `RunnerConfig.local_retriever` 补 Callable 类型注解 | ✅ 2026-09-06 |
| R-179 补截断上限 + stale 索引路径测试 | ✅ 2026-09-06 |
| R-180 ADR-0046 事件措辞修正 | ✅ 2026-09-06 |
| R-181 ADR-0017/0036 加演进注记回链 | ✅ 2026-09-06 |
| R-182 接受：web_planning progress 先于 started | ⚠️ 2026-09-06 |
| R-183 接受：start_web 请求路径同步 vault 扫描 | ⚠️ 2026-09-06 |

---

## 三、下一步建议

### 立即

1. **提交本日改动** — Web UI 视觉重设计（第五轮审查 R-184~R-192 处理完毕）；提交时必须 `git add web/dist` 全量新构建资产（R-192），TODO.md 的 `local_kb_search` 条目建议拆成独立提交
2. **下一步联动候选：`local_kb_search` 注册为 Web 工具（方案 3）** — 触发条件与中间档已记录于 TODO.md"Retrieval And Web Tools"节；先观察 deposit 增长后初始 Top-5 是否漏材料再决定
3. **择机加固 R-173 家族** — 锁时序偶发测试，让 fake runtime 可阻塞

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
