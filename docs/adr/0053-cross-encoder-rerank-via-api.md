# ADR-0053: Cross-Encoder 精排（/rerank API 路线）

**日期**: 2026-09-15
**状态**: ✅ 已实施
**影响范围**: `core/providers.py`, `core/local_research.py`, `core/service.py`, `core/config.py`, `api/app.py`, Web Settings 页

## 背景

混合检索的 RRF 融合是**纯排名**融合：FTS5 路无分数（R-63），向量路的余弦距离与 BM25 分数量纲不可比，融合后顺序即最终顺序，没有"用更重模型精排"的层。召回是粗排——尤其两路各取 2 倍候选时，真正最相关的块可能被 RRF 排在展示预算之外。

方案比较（讨论记录于 TODO.md）：LLM listwise 重排（RankGPT 式，零新增基础设施，曾为推荐备选）、ColBERT 晚期交互（需更换整个向量索引范式）、本地 torch 部署 bge-reranker（2GB+ 依赖 + HF 权重下载链路，与单用户本地优先假设冲突）。**用户选定 Cross-Encoder + 独立 rerank API**（SiliconFlow / Jina / Cohere 形态）：精度天花板最高，且不引入本地推理栈。

## 决策

### 1. 第三种模型客户端

`core/providers.py` 新增 `RerankClient` Protocol 与 `RerankApiModel` 实现：

- `rerank(query, documents) -> list[tuple[int, float]]`：`(索引, 相关性分数)` 对，按分数降序
- `POST {base_url}/rerank`，入参 `model + query + documents`，出参 `results: [{index, relevance_score}]`——SiliconFlow / Jina / Cohere 三家形态相近，单客户端覆盖，`provider` 字段保留适配余量
- **不复用** OpenAI 兼容 chat/embedding 的请求体（非同一协议），仅共享 HTTP 辅助函数与 `PostJson` 注入缝；依赖仅 httpx，零新增重量级依赖

### 2. 配置

- 新 `[rerank_model]` 节（`base_url` / `api_key` / `model`，provider 默认 `rerank_api`）；节缺失 → `UserConfig.rerank_model = None`（无论开关如何都不可用）。设置页保存时 rerank 三个字段全空 = **删除**已存节（显式语义，非静默丢失）；`[research]` 的 query_rewrite/rerank 开关不随设置保存重置（API 层从已存配置透传）
- **开关** `[research] rerank`（默认 `false`）；未配置节、开关关闭或离线模式时整层跳过，检索行为与现状完全一致
- Settings 页新增第三个模型配置卡片；setup API（`/api/setup/config`、`/api/setup/init`）透出 rerank 字段，空白 key = 保留已存值（与 chat/embedding/search 键同一语义）；init 渲染 TOML 时仅在 `rerank_base_url` 非空时写出该节

### 3. 集成缝与降级

`retrieve_local_chunks` 内 **RRF 融合排序之后、`[:top_k]` 截断之前**：

- 仅当配置了 rerank 客户端**且候选数超过 `top_k`** 时调用（整表返回时重排无增益，省一次 API 调用）
- 对全部融合候选（`fetch_k` 不变）打分重排；重排结果必须为完整排列，否则保持 RRF 顺序
- **rerank API 调用失败降级回 RRF 顺序**（log warning，不报错不中断任务）——对称既有的"Chroma 失败 → FTS5-only"降级模式
- 三个调用方自动受益：Local RAG、Prior Knowledge 注入、`local_kb_search`（同一公共接口）。Prior Knowledge 路径**只接 rerank 不接 query rewrite**（ADR-0052），Web 任务启动延迟至多多一次 API 调用
- 与 Multi-Query 叠加时：每个查询的融合列表各自重排（N 次调用，每次至多 2×top_k 个候选——Local RAG 路径 fetch_k=20、融合去重后至多 40，Prior Knowledge 路径 top_k=5 即至多 10；成本可接受）；两者独立开关

## 演进注记（2026-09-16，用户决策）

原决策中的 `[research] rerank` 开关**已移除**：rerank 的启用条件改为 **`[rerank_model]` 节存在即启用、不配即回退**（不配节 = 无 rerank 层，保持 RRF 顺序）。"开关 + 配置"双层机制收敛为"配置即开关"，与 ADR-0052 的改写同步调整。

## 影响

- 一次开启 rerank 的检索多 1 次（多查询时 N 次）HTTP 调用；`build_rerank_client(config, offline)` 为唯一构建缝，service 与 Prior Knowledge 装配共用
- 全部离线确定性测试：`FakeRerankClient` 模式（`tests/test_retrieval_enhancements.py`），真实 API 仅 e2e 手动验证
- 已知取舍：三家 API 字段漂移风险（`relevance_score` vs `score` 已双读，其余留 per-provider 适配层待实测差异再拆）；rerank 失败静默降级不进 `ResearchError` 错误模型（与 Chroma 降级一致，日志可观测）；显式注入 `rerank_client` 参数时绕过开关（程序化 seam，测试与高级用法）
