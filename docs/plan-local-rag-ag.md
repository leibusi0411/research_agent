# Local RAG Augmentation + Generation 实现计划

## Context

当前 Local RAG 仅做 Retrieval（检索），缺少标准 RAG 的 Augmentation（增强）和 Generation（生成）。检索结果直接以原始 chunk 形式输出，用户需手动拼凑答案。需接入已有 LLM 基础设施（DeepSeek API）补全 A+G。

## 设计原则

1. **向后兼容**：不传 chat_model 时保持现有行为（纯检索输出）
2. **复用现有接口**：LLM 调用使用 `ChatModelClient.complete()` 同一协议
3. **结果并存**：summary 和 local_results 同时保留，互不替代
4. **最小改动**：不改检索逻辑、不改 prompt_builders、不改 web UI

## 涉及文件（共 3 个）

### 1. `src/research_agent/core/local_research.py`

- 新增 import: `ChatModelClient`
- 新增 `_build_augmented_prompt(question, chunks, top_n=10) -> str`：将 chunk 注入 prompt 模板
- 新增 `_generate_summary(question, chunks, chat_model) -> str`：调用 LLM 生成答案
- 修改 `run_local_research`：参数新增 `chat_model`；retrieval 后若有 chat_model 则调用 `_generate_summary`，result 中新增 `summary` 字段保留 `local_results`

### 2. `src/research_agent/core/service.py`

- `run_local_research`、`run_local_research_unlocked` 参数新增 `chat_model`
- 当 `chat_model is None` 时自动从 config 创建（与 embedding_client 相同模式）

### 3. `src/research_agent/cli.py`

- `_print_local_result`：有 summary 时先打印 LLM 答案，再打印原始 chunk 引用

## 数据流

```
用户问题
  │
  ▼
FTS5 + ChromaDB 检索 → 10 chunks
  │
  ├── 有 chat_model? ──→ _build_augmented_prompt()
  │                          │
  │                          ▼
  │                     LLM complete()
  │                          │
  │                          ▼
  │                     summary 文本
  ▼
result = { summary: "...", local_results: [...] }
```

## CLI 输出示例

```
Summary
Agent 三大基础推理范式是：
1. ReAct — 推理与行动交替循环 [1][2]
2. Plan-and-Solve — 先制定计划再执行 [1]
3. Reflection — 执行后自我检查并修正 [1]
...

Sources
1. [text...]
   source_path: F:\Obisidian\AGENT\Agent Fundamentals.md
   heading_path: Agent 三大范式
```

## 验证

```bash
# 单元测试
uv run pytest tests/test_local_research.py -v

# 端到端测试
uv run research-agent local "Agent 三大范式分别是什么"
# 预期：先输出 LLM 生成的自然语言答案（带引用编号），再输出原始 chunk
```
