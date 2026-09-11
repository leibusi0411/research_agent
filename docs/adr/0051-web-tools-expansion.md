# ADR-0051: Web Research 工具面扩展（学术搜索 / 代码沙箱 / 浏览器头）

- 日期：2026-09-11（R-263）
- 状态：已接受
- 关联：ADR-0048（local_kb_search 归 Planner）、CONTEXT.md「Tool Registry」「Tool Gateway」

## 背景

对照业界 Deep Research 类 agent 的通行工具面（检索 / 阅读 / 数据处理 / 知识管理 /
作业管理 / 导出六类），本项目缺三项：学术搜索源、数据处理（code interpreter）、
fetch 的反爬健壮性。用户要求全部补齐。

## 决策

**1. `scholar.search`：arXiv 学术搜索，无 key。**
新增 `ArxivSearchProvider`（公共 Atom API，`export.arxiv.org/api/query`），
解析为与 `web.search` 同形的 results（title/url/authors/summary/published，
PDF 链接优先于 abs id）。结果上限沿用 `search_top_k(_max)` 配置。
通过 `ScholarSearchProvider` Protocol 注入 `ToolRunner`，注册进
`create_default_web_tool_registry()`（allowed web_research），Executor 的工具
清单从 registry 动态生成（R-128），无需改提示词装配；`_format_tool_result`
对 `.search` 类工具统一结构化渲染（论文多显示一行作者）。
arXiv 的 429 沿用既有 transient 分类，由 ToolGateway 按 `tool_retries` 重试。
选择 arXiv 而非 Semantic Scholar：免 key、免注册，覆盖 CS/主流量文场景。

**2. `code.run_python`：进程级 Python 沙箱。**
新增 `PythonSandbox`：代码写入临时目录的 `snippet.py`，
`subprocess.run([python, "-I", script])`——隔离模式（忽略用户 site 与
PYTHON* 环境变量）、独立 cwd、stdin 关闭、墙钟超时杀进程
（`python_timeout_seconds`，默认 20s，新增进 `[web_tools]` 配置段）。
stdout/stderr 各自截断至 16k 字符（省略号标记，`output_truncated` 置位）。
**语义**：程序崩溃（exit_code != 0）仍是工具 `ok`——stderr 里的 traceback
交给模型自行修代码；超时归 `transient_error` 走网关重试。
**v1 信任边界**：代码来自本系统 Executor 角色的模型输出（受信链路），
隔离是进程级的，无网络/文件系统监禁——容器级隔离（Docker jail）留作演进。

**3. fetch 浏览器风格请求头。**
`HttpxHttpClient` 所有 GET 附主流浏览器 UA + Accept + Accept-Language。
裸 httpx UA 会被大量新闻/文档站直接 403，这曾是 fetch_extract 的常见死因。
请求头是常量（代码内），不做配置化。JS 渲染站点的真实浏览器降级不做，
留作演进（无头浏览器成本高）。

## 后果

- Executor 可见工具从 3 个变 5 个，提示词里的工具清单自动跟随 registry。
- 调研链路新增两个外部依赖点：arXiv API（限流时降级为可重试错误）、
  本机 Python 解释器（沙箱代码有完整本机权限——单用户本地工具的既有
  信任模型，与 CLI 直接执行任意研究代码一致）。
- `WebToolsConfig` 新增 `python_timeout_seconds`；存量 config.toml 无该键时
  取默认 20（DEFAULT_WEB_TOOLS 合并语义）。

## 演进注记

- 2026-09-11（R-263）：初版落地。当日出口 IP 被 arXiv 限流（429），
  真实链路待网络恢复后复验；解析行为以真实结构 Atom fixture 单测锁定。
- 2026-09-11（R-263 复审处置）：subagent 复审 6 项发现全部处置——
  P0：中文 Windows 下 `-I` 忽略 `PYTHONUTF8` 导致子进程 stdio 用 GBK、
  父进程 UTF-8 解码崩溃，已加 `-X utf8` + `encoding="utf-8", errors="replace"`
  修复并有中文输出回归测试；P1：孙进程持有管道时 `Popen.kill` 只杀直接
  子进程、超时实际不生效（复现 2s 配置跑了 29.8s），已改为进程树击杀
  （Windows `taskkill /T /F`，POSIX `killpg`）+ `mkdtemp/rmtree(ignore_errors)`
  容忍占目录的残留进程，并有孙进程超时回归测试；P2/P3：ArxivSearchProvider
  支持 transport 注入补 HTTP 层测试、`_format_tool_result` 新分支测试、
  注入缝改用 `PythonSandboxClient` Protocol、删除未配置 linter 的 noqa。
