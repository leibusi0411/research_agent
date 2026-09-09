# Default to Tavily through a Search Provider interface

> 演进注记（2026-09-09，R-253）：接口级可替换性仍然成立——`SearchProvider` Protocol 存在，`TavilySearchProvider` 通过依赖注入传入 `ToolRunner`（core/service.py:95-96）。但 "configuration must allow replacing it later" 只落地了一半：`config.search.provider` 字段会被解析（core/config.py:199，默认 `"tavily"`），却从未用于选择实现——CoreService 无条件构造 `TavilySearchProvider`。该配置项目前是惰性字段，切换到其他搜索 Provider 仍需改代码。

Web Research will use a Search Provider interface through the Tool Gateway so Web Research code does not depend directly on a specific search SDK. The v1 default provider is Tavily because it fits AI research workflows, while configuration must allow replacing it later; if no search API key is configured, Web Research is unavailable but Local RAG results remain usable when indexes exist.
