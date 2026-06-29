from __future__ import annotations

import io

import httpx
from pypdf import PdfWriter

from research_agent.core.config import WebToolsConfig
from research_agent.web.tools import (
    FetchResponse,
    HttpxHttpClient,
    SearchProvider,
    ToolGateway,
    ToolRegistry,
    ToolResult,
    ToolRunner,
    create_default_web_tool_registry,
)


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

    assert sorted(registry.names()) == ["web.download_pdf", "web.fetch_extract", "web.search"]
    assert search_spec.allowed_workflows == {"web_research"}
    assert search_spec.input_schema["query"]["type"] == "string"
    assert search_spec.input_schema["max_results"]["required"] is False


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
