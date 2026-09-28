# ADR-0057: 对话接地的任务级来源索引

- 日期：2026-09-21（R-285）
- 状态：已接受
- 关联：ADR-0050（对话接地）、ADR-0054（分章报告）、ADR-0022（KB 索引语义）、ADR-0033（deposit）

## 背景

对话接地此前只注入来源**元数据**（标题+URL）与调研提炼层（findings/sections）——
用户显式导入某来源后，模型仍答不了"这篇文档第 3 节说了什么"这类溯源细节，
因为 Executor 抓取的网页全文根本没落盘。用户要求 NotebookLM 式的
"导入来源 = 来源实际内容可对话"，并确认了任务级隔离索引的设计。

## 决策

1. **原文落盘（新持久化）**：Executor 的 `web.fetch_extract` / `web.download_pdf`
   成功后，经注入的 `source_text_sink` 把提取文本写入
   `tasks/{task_id}/artifacts/source_texts/{sha1(url)[:16]}.txt`。executor
   保持无 workspace 依赖（回调注入）；写入失败降级为"无原文"，与
   executor output log 同契约。

2. **任务级隔离索引**：`tasks/{task_id}/chat_index/`（FTS5 + Chroma 独立
   持久化路径），由 `core/chat_index.TaskChatIndex` 管理。与全局 KB 索引
   （`indexes/`）**物理隔离、零共享**：vault 语义不被网络内容污染，删任务
   即连带删除索引。网络内容进 vault 的唯一通道仍是 deposit。

3. **显式导入 + 幂等增量**：`chat.jsonl` 之外的 `imports.json` 记录已建
   索引的 source_id；导入集合非空时 build_imports 只切块+嵌入**新增**来源
   （重复导入 no-op），随后对问题做混合检索（FTS5 + 向量，RRF，top-6）
   取回原文块注入 prompt 的 `[Imported sources — retrieved excerpts]` 块。
   无原文的来源回退为元数据注入（现状），不阻塞。

4. **成本结构**：索引路径零 chat-model 调用——切块是纯代码，embedding 走
   embedding API（每来源一次、几分钱级）；每问 +1 次查询向量。切块
   1200/200 滑窗；向量写失败降级 FTS5-only（ADR-0022 降级语义）。

5. **导入上限 50**（R-283）不变：它现在约束的是"进入任务索引 + 检索
   候选范围"的来源集合。

## 后果

- 调研任务新增磁盘占用（原文 + 任务级索引），随任务删除清理。
- 提问延迟 +1 次本地混合检索（毫秒级）+ 1 次查询 embedding（网络 RTT）。
- 检索有遗漏风险（块没被召回就不在上下文）——但 findings/sections 提炼层
  始终在场兜底，两级互补。
- 前端零改动：导入按钮已发送 `selected_sources`，语义从"过滤注入"升级为
  "驱动索引与检索"。

## 演进注记

- 2026-09-21（R-285）：初版落地。
