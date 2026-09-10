# ADR-0049: Chunking v2 —— 检索文本富化 + 1000 字符 / 10% 重叠分块

**日期**: 2026-09-09
**状态**: ✅ 已实施
**影响范围**: `core/kb.py`, `core/chroma_store.py`

## 背景

v1 分块（3000 字符目标 / 5000 硬切、无重叠）实测暴露四个检索质量缺口：

1. **heading_path 不参与匹配**：FTS5 只索引 chunk 正文、Chroma 只嵌入正文；章节标题（笔记里密度最高的语义概括）既进不了关键词路也进不了语义路——正文不含"部署"二字的一节 `## 部署` 无法被"部署"命中。
2. **tags / wikilinks 不可检索**：frontmatter tags 与 `[[wikilinks]]` 只躺在 manifest 里，用户刻意打上的检索信号没有进入任何索引。
3. **3000 字符对 embedding 偏大**：中文 3000 字符接近甚至超出部分 embedding 模型的有效窗口；跨十个段落的混合主题向量会稀释语义精度。
4. 两个小瑕疵：>5000 硬切无重叠（跨界概念丢上下文）；代码块内含空行会被段落切分拆散。

## 决策

### 1. search_text 与展示文本分离（覆盖 1、2）

`Chunk` 新增 `search_text` 字段：`text` 保持干净的展示正文（提示词、报告引用用它），`search_text = "[标题 > 子标题] #tag1 #tag2 [[wikilink]]\n" + text`。

- **FTS5** 的 `chunks_fts` 索引 `search_text`（标题/标签/wikilink 的 token 进入关键词匹配）
- **Chroma** 嵌入输入用 `search_text`，存储 document 仍为 `text`（展示干净）
- `retrieve_local_chunks` 与下游提示词/报告零改动——FTS JOIN chunks 的既有结构天然分离了匹配与展示

### 2. 1000 字符目标 + 10% 重叠（覆盖 3、4）

- 分块目标从 3000 降为 **1000 字符**：混合主题的大向量不再稀释语义；1000 中文字符对主流 embedding 模型是舒适区间
- **超长段落**（>1000 字符）：滑窗切分，窗口 1000、步进 900（10% 重叠）——跨界概念两侧保留上下文，取代旧的无重叠硬切
- **段落累积**超过 1000 时 flush，并把上一块**末尾 100 字符**作为 carry 前置进下一块（段落级重叠）

### 3. 已知取舍

- **carry 使块上限约 1100 字符**（目标 1000 + carry ≤100 + 分隔符）：flush 前置 carry 后不再复查大小，上限有界且远小于 embedding 窗口，接受
- **carry 破坏 text↔offset 的逐字对应**：carry 的 ~100 字符来自 start_offset 之前的区域，`text == source[start:end]` 不再严格成立；offset 目前仅作元数据/去重键，无按 offset 切源文件的消费方，未来高亮/溯源功能需注意
- **长段落滑窗与后续段落累积块之间无重叠**（carry 显式清空）：边界类不一致，接受

- search_text 的前缀会让 FTS 命中片段与向量 document 的展示略有噪声（提示词里能看到 `[标题]` 前缀）——换取可检索性，接受
- 代码块内空行仍会触发段落切分（v1 未做 fence 感知）；1000 字符 + 重叠缓解了截断影响，fence 感知切分留作后续
- **存量索引需手动重建一次**（`kb rebuild`）才能获得新分块与 search_text；增量更新只处理后续变更文件

## 影响

- 独立 Local RAG、Prior Knowledge 注入、`local_kb_search` 调研（ADR-0048）三处检索自动受益（同一 `retrieve_local_chunks` 公共接口）
- `ChromaStore` 新增 `add_chunks` / `delete_ids`（供 `update()` 增量更新），`build_index` 重构复用 `add_chunks`
- 存量索引需执行一次 `kb rebuild`
