# ADR-0044: 为 Local RAG 添加 LLM 总结（Augmentation + Generation）

**日期**: 2026-07-03  
**状态**: ✅ 已实施  
**影响范围**: `core/local_research.py`, `core/service.py`, `cli.py`, `core/kb.py`, `core/chroma_store.py`

> 演进注记（2026-09-09，R-226）：下文"配置"一节中的 `[chat_model.local_summarizer]` 在 v1 实际未接线——`_parse_role_chat_models`（core/config.py）的角色解析列表只有 `planner`/`executor`/`supervisor`/`curator` 四个 Web 角色，该节即使写入 TOML 也不会被解析；`CoreService.run_local_research` 与 Web API 通过 `build_role_chat_model_config(config, "local_summarizer")` 取配置时永远静默回退到全局 `[chat_model]`，无报错。因此"为 Local RAG 总结指定专用模型"目前不可用（槽位保留，恢复只需在解析列表中增加一项；与 ADR-0009 的 R-226 注记为同一已知取舍）。本 ADR 其余内容（A+G 各环节、向后兼容、批量 32、stale 放宽、FTS5 独立部署、CLI 自动挂载 embedding_client）均已兑现，不受影响。

## 背景

Local RAG 最初设计为纯检索（Retrieval-only），不使用 LLM。CLAUDE.md 中明确写道 "No LLM summarization"。用户输入问题后，系统仅返回匹配的 raw chunk 列表。

这导致两个问题：
1. 用户面对 10 个零散 chunk，需要手动拼凑答案
2. 不符合标准 RAG 的 R-A-G（Retrieval-Augmentation-Generation）三阶段模型

## 决策

在 Local RAG 中增加 **Augmentation + Generation** 步骤，同时保留原始 chunk 输出：

1. **检索**：保持不变（FTS5 + ChromaDB + RRF 混合检索）
2. **增强**：将检索到的 chunk 格式化注入 prompt 模板（`_build_augmented_prompt`）
3. **生成**：通过 `local_summarizer` 角色调用 LLM 生成自然语言答案（`_generate_summary`）

### 关键设计选择

- **向后兼容**：`chat_model` 参数默认 `None`，不传时完全保持现有纯检索行为
- **结果并存**：`result["summary"]` 存 LLM 答案，`result["local_results"]` 保留原始 chunk
- **独立角色**：使用 `local_summarizer` 角色名，与 Web Research 的 4 个角色（planner/executor/supervisor/curator）区分
- **自动创建**：`CoreService.run_local_research` 在未传入 chat_model 时从 config 自动构建

### 同时修复的工程问题

1. **ChromaDB embedding 批量化**：2788 chunks 一次性发送导致 SiliconFlow API 400 错误，改为每批 32 条
2. **KB 状态放宽**：`stale` 状态（FTS5 可用但 ChromaDB 过期）允许搜索，之前仅 `ready` 可搜
3. **FTS5 独立部署**：ChromaDB 构建失败时 FTS5 索引仍部署，不整体回滚
4. **CLI 自动挂载 embedding_client**：之前需手动注入导致语义搜索不可用

## 配置

```toml
# 默认：未配置 local_summarizer 时使用 chat_model
[chat_model]
model = "deepseek-chat"

# 可选：为 Local RAG 总结指定专用模型
[chat_model.local_summarizer]
model = "deepseek-chat"
```

## 影响

- CLI 输出格式变化：新增 `Summary` 段（LLM 答案），`Local Results` 改名为 `Sources`
- 纯检索模式可通过不传 chat_model 保留（测试中仍使用）
- Web UI 的 Local Result 页通过 `result.json` 自动读取 summary 字段
