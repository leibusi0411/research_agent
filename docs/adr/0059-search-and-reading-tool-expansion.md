# ADR-0059: 检索与阅读工具扩展（学术聚合 / GitHub / 新闻 / 站点爬取 / YouTube / 表格）

- 日期：2026-09-30（R-290）
- 状态：已接受
- 关联：ADR-0051（工具面扩展与信任边界）、ADR-0006（Tool Gateway 工程边界）、CONTEXT.md「Tool Registry」

## 背景

对照 NotebookLM 的输入面与业界调研 agent 工具面（用户选定六项）：scholar.search
数据源单一（仅 arXiv）、缺代码生态检索（GitHub）、缺新闻时间线（GDELT）、
fetch_extract 只能逐页抓（缺站点级）、无视频输入（YouTube 字幕）、无数据集
入口（CSV/XLSX）。六项全部落地，工具面从 5 个增至 10 个。

## 决策

**检索类（对齐既有 provider 模式）**
1. `scholar.search` 扩源不改工具面：`AggregatedScholarProvider` 轮流合并
   arXiv + Crossref（+ Semantic Scholar，仅当 `[search].semantic_scholar_api_key`
   配置时启用——免 key 模式 100 req/5min 不稳，可选增强）。按标题去重、
   轮转交错；单源失败降级其余源。Crossref/GDELT/GitHub 免 key
   （GitHub 60 req/h，可选 `[search].github_api_key` 提至 5k，强制 UA 头）。
2. `github.search` / `news.search`：与 web.search 同形 results（title/url/
   详情字段），走 ToolRunner 注入的 provider，结果上限沿用 search_top_k(_max)。

**阅读类**
3. `web.crawl_site` {url, max_pages≤10}：先拉同域 `/sitemap.xml`（含无
   namespace 的正则回退），无 sitemap 则抓种子页提取同域链接；逐页复用
   fetch_extract 的抽取链路（浏览器头 + trafilatura），每页文本截 4k。
   跨域一律剪枝。
4. `media.youtube_transcript` {url}：youtube-transcript-api 免 key 取字幕
   （en/zh-Hans/zh），video id 解析覆盖 watch/youtu.be/shorts/embed/live；
   段落拼接截 16k。
5. `data.fetch_table` {url}：下载 CSV（csv 模块）/XLSX（openpyxl，新依赖），
   返回行列数 + markdown 预览（≤31 行、单元格截 40 字符）；大小限制沿用
   max_response_bytes。新依赖 youtube-transcript-api、openpyxl。

**提示词与渲染**：执行器策略句为每个新工具给出使用时机（库生态→github、
事件时间线→news、整站文档→crawl、视频→youtube、数据集→table）；
_format_tool_result 的 results 渲染泛化到 .search 家族，表格走专属预览块。

## 后果

- 免 key 工具受共享 IP 限流（GDELT/arXiv 间歇 429/406）——429 归 transient
  由 ToolGateway 重试，406/403 归 permanent 直接换路，均不杀任务。
- crawl_site 单次调用最多 10 页 × 4k ≈ 40k 字符进上下文，由 executor 的
  工具结果预算约束（5 条/子任务惯例）。
- Executor 可见工具翻倍（5→10），提示词工具清单自动跟随 registry（R-128），
  策略句约束误用。

## 演进注记

- 2026-09-30（R-290）：初版落地。
