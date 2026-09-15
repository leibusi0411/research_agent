# Future Upgrades

（延期功能清单已于 2026-09-09 清空。新的延期决策请按"决策 + 触发条件 + 重新评估时机"的格式追加到此处。）

## Query 改写（Multi-Query，Local RAG 检索层）

**决策**（2026-09-15 敲定，✅ 已实施为 ADR-0052）：在 `retrieve_local_chunks` 检索缝之上增加 Multi-Query 改写层。

- LLM 一次调用生成 2~3 个查询变体（引导生成一个偏关键词提取、一个偏语义描述的变体）
- 每个查询（原问题 + 变体）都走**完整两路混合检索**（FTS5 + 向量），不做变体定向路由——交叉覆盖有真实收益；本地检索是毫秒级，真正开销只是每变体一次 embedding 调用 + 改写一次 LLM 调用
- 全部结果列表（2N 个排名列表）进入现有 RRF 统一融合，去重键 `path:start:end` 不变，融合器本身不动，只在检索外套一层循环
- 开关 `[research] query_rewrite`（默认关）；未配置 chat model 或开关关闭时透明回退原始查询——离线确定性测试建立在这条回退上
- 模型槽位：接上保留未接线的 `[chat_model.local_summarizer]` 槽位（改写与总结同属 local 检索域，顺手解决 ADR-0009 遗留注记）
- 实施前置：写新 ADR 显式演进 CONTEXT.md `Hybrid Retrieval` 词条（其 v1 注明 "does not require … agentic query rewriting"）；`local_summarizer` 槽位接线需同步修订 ADR-0009 演进注记
- 测试缝（TDD，全部离线 fake model）：`rewrite_query` 纯函数行为、配置解析与回退路径、RRF 多列表融合正确性

**明确不做**（收益重叠/成本叠加）：HyDE、查询分解/Step-back、PRF 伪相关反馈、变体定向路由（如关键词变体只喂 FTS5）。

**另行评估**：对话式改写（指代/省略消解）留给 TaskChatService 场景单独考虑——追问是最容易检索失手的输入形态。

**触发条件与重评时机**： vault 经 deposit 增长或用户反馈"本地检索漏了明显相关的笔记"时优先实施；变体定向路由仅在实测两路全量检索成为可感知延迟时重评。

## Rerank（Cross-Encoder，/rerank API 路线）

**决策**（2026-09-15 敲定，✅ 已实施为 ADR-0053）：为 Local RAG 混合检索增加 Cross-Encoder 精排层，走独立 rerank API（SiliconFlow / Jina / Cohere 形态），不做本地模型部署。

- 路线：`providers.py` 新增第三种客户端 `RerankClient`——`POST {base_url}/rerank`，入参 `query + documents`，出参 relevance 分数数组。三家 API 形态相近（均为 query+documents→scores），单客户端可覆盖，per-provider 字段差异留适配余量；协议与 OpenAI 兼容 chat/embedding 不同，不复用现有客户端代码
- 依赖：仅 httpx，**零新增重量级依赖**；明确拒绝本地部署路线（torch + sentence-transformers + bge-reranker 权重下载/HF 镜像链路），与单用户本地优先假设冲突
- 配置：新 `[rerank_model]` 节（base_url / model / api_key）；未配置或 `[research] rerank = false` 时整层跳过，检索行为与现状完全一致
- 集成缝：`retrieve_local_chunks` 内 RRF 融合排序之后、`[:top_k]` 截断之前——对 top 20 候选（fetch_k 不变）打分重排取 top 10
- 失败语义：rerank API 调用失败**降级回 RRF 顺序**（对称既有"Chroma 失败→FTS5-only"模式），log warning，不报错不中断任务；错误码归 `model_error` 家族还是新 `rerank_error`，实施时随 ADR 定
- 界面/文档配套：Settings 页新增第三个模型配置卡片（现有 chat/embedding 旁）；新 ADR + CONTEXT.md 词条（Reranker / Rerank）
- 测试缝（TDD，离线确定性）：`FakeRerankClient` 返回固定分数（照 `FakeEmbeddingClient` 模式）；覆盖降级路径、配置回退、重排后顺序正确性；真实 API 只走 e2e
- 与 Query 改写的叠加：两者独立开关；Prior Knowledge / `local_kb_search` 路径建议默认只开 rerank 不开 rewrite，控制 web 任务启动延迟

**明确不做**：本地 torch 部署（bge-reranker 权重 + HF 镜像下载链路）、ColBERT 晚期交互（换向量索引范式，非外挂精排）、LLM listwise 重排（RankGPT 式；曾为"零新增基础设施"备选，选定 API 路线后弃用——若 rerank API 供应商不可用可重评作应急方案）、pairwise/pointwise LLM 打分。

**触发条件与重评时机**：与 Query 改写条目同源——deposit 使 vault 增长或 RRF 顺序精度不足的反馈；若三家 API 形态实测差异过大，重评是否拆分 per-provider 适配层。
