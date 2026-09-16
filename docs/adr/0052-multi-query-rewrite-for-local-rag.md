# ADR-0052: Local RAG Multi-Query 查询改写

**日期**: 2026-09-15
**状态**: ✅ 已实施
**影响范围**: `core/local_research.py`, `core/service.py`, `core/config.py`, `core/providers.py`（仅类型复用）

## 背景

Local RAG 的混合检索（FTS5 + 向量，RRF 融合）接收**原始问题原样**进入两路召回。用户提问的措辞与笔记措辞不一致时（"怎么省钱" vs 笔记写"降低成本"），单一查询的两路都召回不到目标块。CONTEXT.md `Hybrid Retrieval` 词条的 v1 边界明确写着 "does not require … agentic query rewriting"；本 ADR 显式演进该边界（原 TODO 延期清单中的 `agentic query rewriting` 条目随之落地）。

备选方案比较（讨论记录于 TODO.md）：HyDE（只利于向量路、有幻觉牵引风险）、查询分解/Step-back（面向复杂复合问题，当前场景收益重叠）、PRF 伪相关反馈（错误传播、中文分词敏感）。选定 **Multi-Query**：与既有 RRF 融合天然契合、对两路都有效、侵入最小。

## 决策

### 1. 改写层

`core/local_research.py` 新增 `rewrite_question(question, chat_model, *, max_variants=2) -> list[str]`：

- **一次 LLM 调用**生成 2 个变体：一个关键词式（核心检索词，喂 BM25 路）、一个语义式（完整陈述句换说法，喂向量路）
- 逐行解析，清洗编号/项目符号/引号；丢弃空行、重复项、与原问题相同的复述（大小写不敏感）；上限 `max_variants`
- **任何 LLM 失败降级为 `[]`**：调用方回退为仅原始查询，改写永不阻塞 Local RAG（对称 Prior Knowledge 的"永不阻塞"哲学）
- 采用普通 `complete()` + 行解析而非 function calling：local 域既有风格（`local_summarizer` 同为 plain complete），输出格式简单（每行一个查询），解析健壮性由清洗规则保证

### 2. 多查询检索与融合

- 提取 `rrf_fuse(result_lists, *, top_k, k=60)` 模块级纯函数；`retrieve_local_chunks` 内部改用它（行为不变）
- `run_local_research`：`queries = [原问题, *变体]`，每个查询独立走**完整两路混合检索**（不做变体定向路由——交叉覆盖有真实收益，本地检索开销毫秒级），N 个结果列表经 `rrf_fuse` 统一融合取 top 10
- 去重键 `source_path:start:end` 不变，跨查询命中的同一块 RRF 分数自然累加

### 3. 配置与模型槽位

- **开关** `[research] query_rewrite`（默认 `false`）：关闭或未配置 chat model 时改写层整体透明跳过
- **模型槽位**：使用 `[chat_model.local_summarizer]` 角色槽位（改写与总结同属 local 检索域）。本 ADR 同时接线该槽位：`_parse_role_chat_models` 角色解析列表加入 `local_summarizer`（此前写入不生效、静默回退全局，见 ADR-0009 演进注记 R-226，现已兑现）
- 改写**仅作用于 Local RAG**：Prior Knowledge 注入与 `local_kb_search` 不改写，控制 Web 任务启动延迟

## 演进注记（2026-09-16，用户决策）

原决策中的 `[research] query_rewrite` 开关**已移除**：改写的启用条件改为 **`[chat_model.local_summarizer]` 槽位节存在即启用、不配即回退**（不配槽位 = 不改写，总结回退全局 chat model）。设置页新增槽位卡片（summarizer_base_url / summarizer_api_key / summarizer_model，空字段省略并继承全局对应值）。"开关 + 配置"双层机制收敛为"配置即开关"，与 ADR-0053 的 rerank 同步调整。

## 影响

- 一次开启改写的 Local RAG 任务多 1 次 LLM 调用 + 每变体 1 次 embedding 调用
- `rewrite_question` / `rrf_fuse` 为纯函数，全部离线确定性测试（`tests/test_retrieval_enhancements.py`）
- 已知取舍：行解析对"模型把多个变体挤在一行"无能为力（视为 1 个变体，可接受）；改写提示词为代码常量（与项目约定一致）
