from __future__ import annotations

import io

import httpx
from pypdf import PdfWriter

from research_agent.core.config import WebToolsConfig
from research_agent.web.tools import (
    AggregatedScholarProvider,
    ArxivSearchProvider,
    GdeltNewsProvider,
    GithubSearchProvider,
    YouTubeTranscriptProvider,
    FetchResponse,
    HttpxHttpClient,
    PythonSandbox,
    SearchProvider,
    ToolGateway,
    ToolRegistry,
    ToolResult,
    ToolRunner,
    _parse_arxiv_atom,
    create_default_web_tool_registry,
)
from research_agent.web.prompt_builders import _format_tool_result


class _InMemoryHttpClient:
    def __init__(self, responses: dict[str, FetchResponse]) -> None:
        self._responses = responses

    def get(self, url: str, *, timeout_seconds: int, max_bytes: int | None = None) -> FetchResponse:
        resp = self._responses.get(url)
        if resp is None:
            return FetchResponse(url=url, status_code=404, headers={"content-type": "text/plain"}, content=b"not found")
        if max_bytes is not None and len(resp.content) > max_bytes:
            return FetchResponse(
                url=resp.url, status_code=resp.status_code,
                headers=resp.headers, content=resp.content[: max_bytes + 1], truncated=True,
            )
        return resp


def web_tools_config(**overrides: int) -> WebToolsConfig:
    values = {
        "request_timeout_seconds": 45,
        "pdf_timeout_seconds": 90,
        "max_response_bytes": 20_971_520,
        "max_pdf_bytes": 104_857_600,
        "search_top_k": 10,
        "search_top_k_max": 20,
        "tool_retries": 2,
        "python_timeout_seconds": 20,
    }
    values.update(overrides)
    return WebToolsConfig(**values)


class FakeSearchProvider(SearchProvider):
    def search(self, query: str, max_results: int) -> list[dict]:
        return [
            {
                "title": f"Result for {query}",
                "url": "https://example.com/result",
                "content": f"content top {max_results}",
            }
        ]


def test_tool_registry_records_web_tools_permissions_and_input_schemas():
    registry = create_default_web_tool_registry()

    search_spec = registry.get("web.search")

    assert sorted(registry.names()) == [
        "code.run_python",
        "data.fetch_table",
        "github.search",
        "media.youtube_transcript",
        "news.search",
        "scholar.search",
        "web.crawl_site",
        "web.download_pdf",
        "web.fetch_extract",
        "web.search",
    ]
    assert search_spec.allowed_workflows == {"web_research"}
    assert search_spec.input_schema["query"]["type"] == "string"
    assert search_spec.input_schema["max_results"]["required"] is False
    scholar_spec = registry.get("scholar.search")
    assert scholar_spec.allowed_workflows == {"web_research"}
    assert scholar_spec.input_schema["query"]["type"] == "string"
    assert scholar_spec.input_schema["max_results"]["required"] is False
    python_spec = registry.get("code.run_python")
    assert python_spec.allowed_workflows == {"web_research"}
    assert python_spec.input_schema["code"]["type"] == "string"
    assert python_spec.input_schema["code"]["required"] is True


class FakeScholarProvider:
    """Records queries and returns a fixed paper list."""

    def __init__(self) -> None:
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, max_results: int) -> list[dict]:
        self.queries.append((query, max_results))
        return [
            {
                "title": "State Machines for Agents",
                "url": "https://arxiv.org/abs/2601.00001",
                "authors": "A. Author, B. Author",
                "summary": "We model agents as state machines.",
                "published": "2026-01-01",
            }
        ]


def test_scholar_search_uses_provider_and_result_limits():
    provider = FakeScholarProvider()
    runner = ToolRunner(config=web_tools_config(search_top_k=7), scholar_provider=provider)

    result = runner.run("scholar.search", {"query": "agent state machines"})

    assert result.status == "ok"
    assert provider.queries == [("agent state machines", 7)]
    paper = result.data["results"][0]
    assert paper["title"] == "State Machines for Agents"
    assert paper["url"].startswith("https://arxiv.org/abs/")
    assert result.metadata["max_results"] == 7


def test_scholar_search_without_provider_is_a_permanent_error():
    runner = ToolRunner(config=web_tools_config())

    result = gateway_call(runner, {"name": "scholar.search", "arguments": {"query": "agents"}})

    assert result.status == "error"
    assert result.error == "permanent_error"
    assert "Scholar" in result.message


# Real-shape arXiv Atom feed (structure copied from the public API; used so
# parsing stays covered even when the network is rate-limited).
_ARXIV_ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query</title>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <updated>2026-01-02T00:00:00Z</updated>
    <published>2026-01-01T12:00:00Z</published>
    <title>A Study of\n   Agent Orchestration</title>
    <summary>  We model agents as state machines
      and measure latency.  </summary>
    <author><name>Alice Author</name></author>
    <author><name>Bob Author</name></author>
    <link href="http://arxiv.org/abs/2401.00001v1" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2401.00001v1" rel="related" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <published>2026-02-01T00:00:00Z</published>
    <title>Checkpoints Everywhere</title>
    <summary>Persistence patterns for graphs.</summary>
    <author><name>Carol Author</name></author>
    <link href="http://arxiv.org/abs/2401.00002v1" rel="alternate" type="text/html"/>
  </entry>
</feed>
"""


def test_parse_arxiv_atom_extracts_pdf_link_authors_and_clean_text():
    results = _parse_arxiv_atom(_ARXIV_ATOM_SAMPLE)

    assert len(results) == 2
    first = results[0]
    assert first["title"] == "A Study of Agent Orchestration"  # whitespace normalized
    assert first["url"] == "http://arxiv.org/pdf/2401.00001v1"  # PDF link preferred
    assert first["authors"] == "Alice Author, Bob Author"
    assert first["summary"] == "We model agents as state machines and measure latency."
    assert first["published"] == "2026-01-01"
    # No PDF link: falls back to the entry id.
    assert results[1]["url"] == "http://arxiv.org/abs/2401.00002v1"
    assert results[1]["published"] == "2026-02-01"


class FakeScholarSource:
    """Second scholar source for aggregation tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, query: str, max_results: int) -> list[dict]:
        self.calls.append(query)
        return [{"title": "Crossref paper", "url": "https://doi.org/10.1/x", "authors": "C. Author", "summary": "s", "published": "2025-01-01"}]


def test_scholar_aggregation_merges_sources_with_round_robin(tmp_path):
    from research_agent.web.tools import AggregatedScholarProvider

    fake = FakeScholarSource()
    arxiv_like = FakeScholarSource()
    arxiv_like.search = lambda query, max_results: [
        {"title": "arXiv paper", "url": "https://arxiv.org/abs/1", "authors": "A", "summary": "s", "published": "2025-02-02"}
    ]
    provider = AggregatedScholarProvider([arxiv_like, fake])

    results = provider.search("agents", 4)

    titles = [r["title"] for r in results]
    assert titles == ["arXiv paper", "Crossref paper"]  # interleaved, not appended
    assert provider.sources_queried == 2


def test_github_search_sends_user_agent_and_parses_items():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["ua"] = request.headers.get("user-agent", "")
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"items": [
            {"full_name": "langchain-ai/langgraph", "description": "Build agents", "stargazers_count": 12000, "html_url": "https://github.com/langchain-ai/langgraph", "language": "Python"},
        ]}, request=request)

    provider = GithubSearchProvider(transport=httpx.MockTransport(handler))
    results = provider.search("langgraph agents", 5)

    assert "research-agent" in captured["ua"]  # GitHub API requires a UA
    assert "search/repositories" in captured["url"]
    assert results[0]["title"] == "langchain-ai/langgraph"
    assert results[0]["stars"] == 12000
    assert results[0]["url"].startswith("https://github.com/")


def test_news_search_uses_gdelt_doc_api():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"articles": [
            {"title": "A2A protocol launched", "url": "https://news.example/a2a", "seendate": "20260920T120000Z", "domain": "news.example"},
        ]}, request=request)

    provider = GdeltNewsProvider(transport=httpx.MockTransport(handler))
    results = provider.search("A2A protocol", 5)

    assert "gdeltproject.org" in captured["url"]
    assert "mode=artlist" in captured["url"]
    assert results[0]["title"] == "A2A protocol launched"
    assert results[0]["published"] == "2026-09-20"


def test_arxiv_provider_encodes_query_params_and_parses_response():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, text=_ARXIV_ATOM_SAMPLE, request=request)

    provider = ArxivSearchProvider(transport=httpx.MockTransport(handler))

    results = provider.search("retrieval augmented generation", 5)

    assert "search_query=all%3Aretrieval+augmented+generation" in captured["url"]
    assert "max_results=5" in captured["url"]
    assert results[0]["title"] == "A Study of Agent Orchestration"


def test_run_python_executes_code_and_captures_stdout_and_exit_code():
    runner = ToolRunner(config=web_tools_config(python_timeout_seconds=20), python_sandbox=PythonSandbox())

    ok = runner.run("code.run_python", {"code": "print(2 + 3)"})
    failed = runner.run("code.run_python", {"code": "print('before')\nraise ValueError('boom')"})

    assert ok.status == "ok"
    assert ok.data["stdout"] == "5\n"
    assert ok.data["exit_code"] == 0
    # A crashing program is still a successful tool run: the model sees the
    # traceback in stderr and can fix its code instead of hitting an opaque error.
    assert failed.status == "ok"
    assert failed.data["exit_code"] == 1
    assert "before" in failed.data["stdout"]
    assert "ValueError" in failed.data["stderr"]


def test_run_python_times_out_and_reports_transient_error():
    runner = ToolRunner(config=web_tools_config(python_timeout_seconds=1), python_sandbox=PythonSandbox())

    result = runner.run("code.run_python", {"code": "import time\ntime.sleep(30)"})

    assert result.status == "error"
    assert result.error == "transient_error"
    assert "timed out" in result.message


def test_run_python_output_is_truncated_to_a_bounded_size():
    runner = ToolRunner(config=web_tools_config(), python_sandbox=PythonSandbox())

    result = runner.run("code.run_python", {"code": "print('x' * 50000)"})

    assert result.status == "ok"
    assert len(result.data["stdout"]) <= 16_400
    assert result.data["output_truncated"] is True


def test_run_python_round_trips_chinese_output_on_ansi_codepages():
    # R-263 review P0: `-I` ignores PYTHONUTF8, so on Chinese Windows the
    # child's stdio defaults to GBK and naive decoding blows up. The sandbox
    # forces `-X utf8` on the child and decodes as UTF-8 with replacement.
    runner = ToolRunner(config=web_tools_config(), python_sandbox=PythonSandbox())

    result = runner.run("code.run_python", {"code": "print('你好，世界')"})

    assert result.status == "ok"
    assert result.data["stdout"] == "你好，世界\n"


def test_run_python_timeout_kills_grandchildren_holding_the_pipe():
    # R-263 review P1: a grandchild holding the inherited stdout pipe keeps
    # communicate() blocked after the direct child is killed on Windows.
    # The tree kill must enforce the wall clock anyway.
    import time

    runner = ToolRunner(config=web_tools_config(python_timeout_seconds=2), python_sandbox=PythonSandbox())
    spawn_grandchild = (
        "import subprocess, time\n"
        "subprocess.Popen(['ping', '-n', '30', '127.0.0.1'])\n"
        "time.sleep(60)\n"
    )

    started = time.monotonic()
    result = runner.run("code.run_python", {"code": spawn_grandchild})
    elapsed = time.monotonic() - started

    assert result.status == "error"
    assert result.error == "transient_error"
    assert elapsed < 15, f"tree kill did not enforce the timeout (took {elapsed:.1f}s)"


def test_format_tool_result_renders_scholar_and_python_results():
    scholar_block = _format_tool_result(
        1,
        {
            "tool": "scholar.search",
            "status": "ok",
            "data": {"results": [{"title": "Paper", "url": "https://arxiv.org/abs/1", "authors": "A. Author", "summary": "Abstract text"}]},
        },
    )
    python_block = _format_tool_result(
        2,
        {"tool": "code.run_python", "status": "ok", "data": {"stdout": "42\n", "stderr": "", "exit_code": 0, "output_truncated": False}},
    )
    crashed_block = _format_tool_result(
        3,
        {"tool": "code.run_python", "status": "ok", "data": {"stdout": "", "stderr": "ValueError: boom", "exit_code": 1, "output_truncated": True}},
    )

    assert "scholar.search" in scholar_block
    assert "Authors: A. Author" in scholar_block
    assert "Abstract text" in scholar_block
    assert "Exit code: 0" in python_block
    assert "Stdout:\n42" in python_block
    assert "Exit code: 1" in crashed_block
    assert "ValueError: boom" in crashed_block
    assert "(Output was truncated.)" in crashed_block


def gateway_call(runner: ToolRunner, function_call: dict) -> ToolResult:
    return ToolGateway(registry=create_default_web_tool_registry(), runner=runner).call("web_research", function_call)


def test_gateway_validates_tool_existence_schema_and_workflow_permission():
    gateway = ToolGateway(
        registry=create_default_web_tool_registry(),
        runner=ToolRunner(config=web_tools_config(), search_provider=FakeSearchProvider()),
    )

    missing = gateway.call("web_research", {"name": "web.missing", "arguments": {}})
    bad_schema = gateway.call("web_research", {"name": "web.search", "arguments": {"query": 12}})
    bad_workflow = gateway.call("local_rag", {"name": "web.search", "arguments": {"query": "LangGraph"}})

    assert missing.status == "error"
    assert missing.error == "validation_error"
    assert "Unknown tool" in missing.message
    assert bad_schema.status == "error"
    assert bad_schema.error == "validation_error"
    assert "query" in bad_schema.message
    assert bad_workflow.status == "error"
    assert bad_workflow.error == "validation_error"
    assert "not allowed" in bad_workflow.message


def test_gateway_retries_transient_failures_without_budget_validation():
    class FlakyRunner(ToolRunner):
        def __init__(self) -> None:
            self.calls = 0

        def run(self, tool_name: str, arguments: dict) -> ToolResult:
            self.calls += 1
            if self.calls < 3:
                return ToolResult(status="error", error="transient_error", message="temporary")
            return ToolResult(status="ok", data={"done": True})

    runner = FlakyRunner()
    gateway = ToolGateway(
        registry=create_default_web_tool_registry(),
        runner=runner,
        tool_retries=2,
    )

    result = gateway.call(
        "web_research",
        {
            "name": "web.search",
            "arguments": {"query": "LangGraph", "max_results": 10, "max_tool_calls": 999999, "budget": 999999},
        },
    )

    assert result.status == "ok"
    assert result.data == {"done": True}
    assert runner.calls == 3


def test_gateway_retries_transient_search_provider_http_status_failures():
    class TransientSearchProvider(SearchProvider):
        def __init__(self) -> None:
            self.calls = 0

        def search(self, query: str, max_results: int) -> list[dict]:
            self.calls += 1
            if self.calls == 1:
                request = httpx.Request("POST", "https://api.tavily.com/search")
                response = httpx.Response(429, request=request)
                raise httpx.HTTPStatusError("too many requests", request=request, response=response)
            return [{"title": query, "url": "https://example.com", "content": "ok"}]

    provider = TransientSearchProvider()
    gateway = ToolGateway(
        registry=create_default_web_tool_registry(),
        runner=ToolRunner(config=web_tools_config(tool_retries=1), search_provider=provider),
    )

    result = gateway.call("web_research", {"name": "web.search", "arguments": {"query": "LangGraph"}})

    assert result.status == "ok"
    assert provider.calls == 2


def test_http_status_error_message_carries_provider_detail():
    """R-280: Tavily quota exhaustion (432) must surface its detail text so
    the supervisor/model/user can see WHY, not just a bare status code."""
    class QuotaExhaustedProvider(SearchProvider):
        def search(self, query: str, max_results: int) -> list[dict]:
            request = httpx.Request("POST", "https://api.tavily.com/search")
            response = httpx.Response(
                432,
                text="{\"detail\":{\"error\":\"This request exceeds your plan's set usage limit.\"}}",
                request=request,
            )
            raise httpx.HTTPStatusError("432", request=request, response=response)

    gateway = ToolGateway(
        registry=create_default_web_tool_registry(),
        runner=ToolRunner(config=web_tools_config(), search_provider=QuotaExhaustedProvider()),
    )

    result = gateway.call("web_research", {"name": "web.search", "arguments": {"query": "robots"}})

    assert result.status == "error"
    assert result.error == "permanent_error"
    assert "HTTP status 432" in result.message
    assert "usage limit" in result.message


def test_web_search_uses_search_provider_and_result_limit_defaults():
    gateway = ToolGateway(
        registry=create_default_web_tool_registry(),
        runner=ToolRunner(config=web_tools_config(search_top_k=7), search_provider=FakeSearchProvider()),
    )

    result = gateway.call("web_research", {"name": "web.search", "arguments": {"query": "LangGraph"}})

    assert result.status == "ok"
    assert result.data["results"][0]["title"] == "Result for LangGraph"
    assert result.data["results"][0]["content"] == "content top 7"


def test_fetch_extract_accepts_http_html_and_respects_response_size_limit():
    http_client = _InMemoryHttpClient(
        {
            "https://example.com/page": FetchResponse(
                url="https://example.com/page",
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=b"<html><body><main><h1>Title</h1><p>Useful page text.</p></main></body></html>",
            ),
            "https://example.com/too-large": FetchResponse(
                url="https://example.com/too-large",
                status_code=200,
                headers={"content-type": "text/plain"},
                content=b"x" * 128,
            ),
        }
    )
    gateway = ToolGateway(
        registry=create_default_web_tool_registry(),
        runner=ToolRunner(config=web_tools_config(max_response_bytes=100), http_client=http_client),
    )

    ok = gateway.call("web_research", {"name": "web.fetch_extract", "arguments": {"url": "https://example.com/page"}})
    too_large = gateway.call(
        "web_research", {"name": "web.fetch_extract", "arguments": {"url": "https://example.com/too-large"}}
    )

    assert ok.status == "ok"
    assert "Useful page text" in ok.data["text"]
    assert ok.metadata["content_type"].startswith("text/html")
    assert too_large.status == "error"
    assert too_large.error == "permanent_error"
    assert "larger than max_response_bytes" in too_large.message


def test_fetch_extract_uses_declared_charset():
    http_client = _InMemoryHttpClient(
        {
            "https://example.com/latin1": FetchResponse(
                url="https://example.com/latin1",
                status_code=200,
                headers={"content-type": "text/plain; Charset=iso-8859-1"},
                content="café".encode("iso-8859-1"),
            )
        }
    )
    gateway = ToolGateway(
        registry=create_default_web_tool_registry(),
        runner=ToolRunner(config=web_tools_config(), http_client=http_client),
    )

    result = gateway.call("web_research", {"name": "web.fetch_extract", "arguments": {"url": "https://example.com/latin1"}})

    assert result.status == "ok"
    assert result.data["text"] == "café"


def test_httpx_client_stops_reading_after_configured_byte_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            stream=httpx.ByteStream(b"abcdef"),
            request=request,
        )

    transport = httpx.MockTransport(handler)
    client = HttpxHttpClient(client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs))

    fetched = client.get("https://example.com/large", timeout_seconds=1, max_bytes=3)

    assert fetched.truncated is True
    assert fetched.content == b"abcd"


def test_crawl_site_walks_same_domain_pages():
    pages = {
        "https://docs.example.com/sitemap.xml": """<?xml version="1.0"?><urlset>
        <url><loc>https://docs.example.com/guide</loc></url>
        <url><loc>https://docs.example.com/api</loc></url>
        <url><loc>https://other.example.net/x</loc></url>
        </urlset>""",
        "https://docs.example.com/guide": "<html><body><p>Guide page content.</p></body></html>",
        "https://docs.example.com/api": "<html><body><p>API page content.</p></body></html>",
    }
    http_client = _InMemoryHttpClient(
        {url: FetchResponse(url=url, status_code=200, headers={"content-type": "application/xml" if url.endswith(".xml") else "text/html"}, content=text.encode("utf-8")) for url, text in pages.items()}
    )
    runner = ToolRunner(config=web_tools_config(), http_client=http_client)

    result = runner.run("web.crawl_site", {"url": "https://docs.example.com/", "max_pages": 5})

    assert result.status == "ok"
    urls = [p["url"] for p in result.data["pages"]]
    assert "https://docs.example.com/guide" in urls
    assert "https://docs.example.com/api" in urls
    assert not any("other.example.net" in u for u in urls)  # cross-domain pruned
    texts = " ".join(p["text"] for p in result.data["pages"])
    assert "Guide page content." in texts


def test_crawl_site_caps_max_pages():
    entries = "".join(f"<url><loc>https://docs.example.com/p{i}</loc></url>" for i in range(12))
    pages = {"https://docs.example.com/sitemap.xml": f'<?xml version="1.0"?><urlset>{entries}</urlset>'}
    for i in range(12):
        pages[f"https://docs.example.com/p{i}"] = f"<html><body><p>page {i}</p></body></html>"
    http_client = _InMemoryHttpClient(
        {url: FetchResponse(url=url, status_code=200, headers={"content-type": "application/xml" if url.endswith(".xml") else "text/html"}, content=body.encode("utf-8")) for url, body in pages.items()}
    )
    runner = ToolRunner(config=web_tools_config(), http_client=http_client)

    result = runner.run("web.crawl_site", {"url": "https://docs.example.com/", "max_pages": 99})

    assert result.status == "ok"
    assert len(result.data["pages"]) == 10  # hard cap
    assert result.data["pages"][0]["url"] == "https://docs.example.com/p0"


def test_youtube_transcript_tool_fetches_and_joins_segments():
    def fake_fetch(video_id, languages=None):
        class Seg:
            def __init__(self, text):
                self.text = text
        class Fetched:
            def __init__(self):
                self.snippets = [Seg("Hello "), Seg("world."), Seg(" 你好世界")]
            def __iter__(self):
                return iter(self.snippets)
        return Fetched()

    provider = YouTubeTranscriptProvider(transcript_fetch=fake_fetch)
    runner = ToolRunner(config=web_tools_config(), youtube_provider=provider)

    result = runner.run("media.youtube_transcript", {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})

    assert result.status == "ok"
    assert result.data["video_id"] == "dQw4w9WgXcQ"
    assert "Hello world." in result.data["text"]
    assert "你好世界" in result.data["text"]


def test_fetch_table_parses_csv_preview():
    csv_body = "name,score\nalpha,1\nbeta,2\n".encode("utf-8")
    http_client = _InMemoryHttpClient({
        "https://data.example/scores.csv": FetchResponse(
            url="https://data.example/scores.csv", status_code=200,
            headers={"content-type": "text/csv"}, content=csv_body,
        )
    })
    runner = ToolRunner(config=web_tools_config(), http_client=http_client)

    result = runner.run("data.fetch_table", {"url": "https://data.example/scores.csv"})

    assert result.status == "ok"
    assert result.data["rows"] == 2
    assert result.data["cols"] == 2
    assert "| name" in result.data["preview"]
    assert "| alpha" in result.data["preview"]


def test_fetch_table_parses_xlsx():
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["tool", "stars"])
    ws.append(["langgraph", 12000])
    buf = BytesIO()
    wb.save(buf)
    http_client = _InMemoryHttpClient({
        "https://data.example/tools.xlsx": FetchResponse(
            url="https://data.example/tools.xlsx", status_code=200,
            headers={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            content=buf.getvalue(),
        )
    })
    runner = ToolRunner(config=web_tools_config(), http_client=http_client)

    result = runner.run("data.fetch_table", {"url": "https://data.example/tools.xlsx"})

    assert result.status == "ok"
    assert result.data["rows"] == 1
    assert result.data["cols"] == 2
    assert "langgraph" in result.data["preview"]


def test_httpx_client_sends_browser_style_headers():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["user-agent"] = request.headers.get("user-agent", "")
        captured["accept"] = request.headers.get("accept", "")
        captured["accept-language"] = request.headers.get("accept-language", "")
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="ok", request=request)

    transport = httpx.MockTransport(handler)
    client = HttpxHttpClient(client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs))

    client.get("https://example.com/page", timeout_seconds=5)

    # A plain httpx UA is insta-403'd by many news/docs sites; present as a
    # mainstream browser instead so fetch_extract survives basic bot filters.
    assert "Mozilla/5.0" in captured["user-agent"]
    assert "text/html" in captured["accept"]
    assert captured["accept-language"]


def test_download_pdf_accepts_pdf_and_extracts_text_with_size_limit():
    http_client = _InMemoryHttpClient(
        {
            "https://example.com/report.pdf": FetchResponse(
                url="https://example.com/report.pdf",
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=minimal_pdf_bytes(),
            ),
            "https://example.com/too-large.pdf": FetchResponse(
                url="https://example.com/too-large.pdf",
                status_code=200,
                headers={"content-type": "application/pdf"},
                content=minimal_pdf_bytes() + (b" " * 100),
            ),
        }
    )
    gateway = ToolGateway(
        registry=create_default_web_tool_registry(),
        runner=ToolRunner(config=web_tools_config(max_pdf_bytes=len(minimal_pdf_bytes()) + 1), http_client=http_client),
    )

    ok = gateway.call("web_research", {"name": "web.download_pdf", "arguments": {"url": "https://example.com/report.pdf"}})
    too_large = gateway.call(
        "web_research", {"name": "web.download_pdf", "arguments": {"url": "https://example.com/too-large.pdf"}}
    )

    assert ok.status == "ok"
    assert ok.data["page_count"] == 1
    assert too_large.status == "error"
    assert too_large.error == "permanent_error"
    assert "larger than max_pdf_bytes" in too_large.message


def minimal_pdf_bytes() -> bytes:
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)
    return buffer.getvalue()
