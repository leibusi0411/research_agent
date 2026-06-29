from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
import trafilatura
from pypdf import PdfReader

from research_agent.core.config import WebToolsConfig


ToolStatus = str
ToolError = str


@dataclass(frozen=True)
class ToolResult:
    status: ToolStatus
    data: dict[str, Any] = field(default_factory=dict)
    error: ToolError | None = None
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    allowed_workflows: set[str]
    input_schema: dict[str, dict[str, Any]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return list(self._tools)


class SearchProvider(Protocol):
    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        ...


class TavilySearchProvider:
    def __init__(self, api_key: str, *, endpoint: str = "https://api.tavily.com/search") -> None:
        self.api_key = api_key
        self.endpoint = endpoint

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        response = httpx.post(
            self.endpoint,
            json={"api_key": self.api_key, "query": query, "max_results": max_results},
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        return list(payload.get("results", []))


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    truncated: bool = False


class HttpClient(Protocol):
    def get(self, url: str, *, timeout_seconds: int, max_bytes: int | None = None) -> FetchResponse:
        ...


class HttpxHttpClient:
    def __init__(self, client_factory: Any | None = None) -> None:
        self.client_factory = client_factory or httpx.Client

    def get(self, url: str, *, timeout_seconds: int, max_bytes: int | None = None) -> FetchResponse:
        with self.client_factory(follow_redirects=True, timeout=timeout_seconds) as client:
            with client.stream("GET", url) as response:
                chunks: list[bytes] = []
                total = 0
                truncated = False
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if max_bytes is not None and total > max_bytes:
                        truncated = True
                        remaining = max_bytes + 1 - sum(len(item) for item in chunks)
                        if remaining > 0:
                            chunks.append(chunk[:remaining])
                        break
                    chunks.append(chunk)
        return FetchResponse(
            url=str(response.url),
            status_code=response.status_code,
            headers={key.lower(): value for key, value in response.headers.items()},
            content=b"".join(chunks),
            truncated=truncated,
        )


class ToolRunner:
    def __init__(
        self,
        *,
        config: WebToolsConfig,
        search_provider: SearchProvider | None = None,
        http_client: HttpClient | None = None,
    ) -> None:
        self.config = config
        self.search_provider = search_provider
        self.http_client = http_client or HttpxHttpClient()

    def run(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        try:
            if tool_name == "web.search":
                return self._run_search(arguments)
            if tool_name == "web.fetch_extract":
                return self._run_fetch_extract(arguments)
            if tool_name == "web.download_pdf":
                return self._run_download_pdf(arguments)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return ToolResult(status="error", error="transient_error", message=str(exc))
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {408, 425, 429} or status_code >= 500:
                return ToolResult(status="error", error="transient_error", message=f"HTTP status {status_code}")
            return ToolResult(status="error", error="permanent_error", message=f"HTTP status {status_code}")
        except Exception as exc:
            return ToolResult(status="error", error="permanent_error", message=str(exc))
        return ToolResult(status="error", error="validation_error", message=f"Unknown tool: {tool_name}")

    def _run_search(self, arguments: dict[str, Any]) -> ToolResult:
        if self.search_provider is None:
            return ToolResult(status="error", error="permanent_error", message="Search provider is not configured.")
        max_results = int(arguments.get("max_results") or self.config.search_top_k)
        if max_results <= 0:
            return ToolResult(status="error", error="validation_error", message="max_results must be positive.")
        max_results = min(max_results, self.config.search_top_k_max)
        results = self.search_provider.search(str(arguments["query"]), max_results)
        return ToolResult(status="ok", data={"results": results}, metadata={"max_results": max_results})

    def _run_fetch_extract(self, arguments: dict[str, Any]) -> ToolResult:
        url = str(arguments["url"])
        if not _is_http_url(url):
            return ToolResult(status="error", error="validation_error", message="url must be http or https.")
        response = self.http_client.get(
            url,
            timeout_seconds=self.config.request_timeout_seconds,
            max_bytes=self.config.max_response_bytes,
        )
        status_error = _http_status_error(response.status_code)
        if status_error is not None:
            return status_error
        if response.truncated or len(response.content) > self.config.max_response_bytes:
            return ToolResult(
                status="error",
                error="permanent_error",
                message="Response is larger than max_response_bytes.",
                metadata={"response_bytes": len(response.content)},
            )
        content_type_header = _content_type_header(response.headers)
        media_type = _media_type(content_type_header)
        if not _is_supported_text_content_type(media_type):
            return ToolResult(status="error", error="permanent_error", message=f"Unsupported content type: {media_type}")
        raw_text = response.content.decode(_encoding_from_content_type(content_type_header), errors="replace")
        text = _extract_html_text(raw_text) if _is_html_content_type(media_type) else raw_text
        return ToolResult(
            status="ok",
            data={"url": response.url, "text": text.strip()},
            metadata={"content_type": media_type, "response_bytes": len(response.content)},
        )

    def _run_download_pdf(self, arguments: dict[str, Any]) -> ToolResult:
        url = str(arguments["url"])
        if not _is_http_url(url):
            return ToolResult(status="error", error="validation_error", message="url must be http or https.")
        response = self.http_client.get(
            url,
            timeout_seconds=self.config.pdf_timeout_seconds,
            max_bytes=self.config.max_pdf_bytes,
        )
        status_error = _http_status_error(response.status_code)
        if status_error is not None:
            return status_error
        if response.truncated or len(response.content) > self.config.max_pdf_bytes:
            return ToolResult(
                status="error",
                error="permanent_error",
                message="PDF is larger than max_pdf_bytes.",
                metadata={"pdf_bytes": len(response.content)},
            )
        media_type = _media_type(_content_type_header(response.headers))
        if media_type != "application/pdf" and not urlparse(response.url).path.lower().endswith(".pdf"):
            return ToolResult(status="error", error="permanent_error", message=f"Unsupported PDF content type: {media_type}")
        reader = PdfReader(io.BytesIO(response.content))
        pages = [page.extract_text() or "" for page in reader.pages]
        return ToolResult(
            status="ok",
            data={"url": response.url, "text": "\n".join(pages).strip(), "page_count": len(reader.pages)},
            metadata={"content_type": media_type, "pdf_bytes": len(response.content)},
        )


class ToolGateway:
    def __init__(self, *, registry: ToolRegistry, runner: ToolRunner, tool_retries: int | None = None) -> None:
        self.registry = registry
        self.runner = runner
        self.tool_retries = tool_retries if tool_retries is not None else getattr(runner.config, "tool_retries", 0)

    def call(self, workflow: str, function_call: dict[str, Any]) -> ToolResult:
        tool_name = function_call.get("name")
        arguments = function_call.get("arguments", {})
        if not isinstance(tool_name, str) or not self.registry.has(tool_name):
            return ToolResult(status="error", error="validation_error", message=f"Unknown tool: {tool_name}")
        spec = self.registry.get(tool_name)
        if workflow not in spec.allowed_workflows:
            return ToolResult(status="error", error="validation_error", message=f"Tool {tool_name} is not allowed for workflow {workflow}.")
        if not isinstance(arguments, dict):
            return ToolResult(status="error", error="validation_error", message="Tool arguments must be an object.")
        schema_error = _validate_arguments(arguments, spec.input_schema)
        if schema_error is not None:
            return ToolResult(status="error", error="validation_error", message=schema_error)

        result = self.runner.run(tool_name, arguments)
        attempts = 0
        while result.status == "error" and result.error == "transient_error" and attempts < self.tool_retries:
            attempts += 1
            result = self.runner.run(tool_name, arguments)
        return result


def create_default_web_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="web.search",
            allowed_workflows={"web_research"},
            input_schema={
                "query": {"type": "string", "required": True},
                "max_results": {"type": "integer", "required": False},
            },
        )
    )
    registry.register(
        ToolSpec(
            name="web.fetch_extract",
            allowed_workflows={"web_research"},
            input_schema={"url": {"type": "string", "required": True}},
        )
    )
    registry.register(
        ToolSpec(
            name="web.download_pdf",
            allowed_workflows={"web_research"},
            input_schema={"url": {"type": "string", "required": True}},
        )
    )
    return registry


def _validate_arguments(arguments: dict[str, Any], schema: dict[str, dict[str, Any]]) -> str | None:
    for field_name, field_schema in schema.items():
        required = bool(field_schema.get("required"))
        if required and field_name not in arguments:
            return f"Missing required argument: {field_name}"
        if field_name not in arguments:
            continue
        expected_type = field_schema.get("type")
        if expected_type == "string" and not isinstance(arguments[field_name], str):
            return f"Argument {field_name} must be a string."
        if expected_type == "integer" and not isinstance(arguments[field_name], int):
            return f"Argument {field_name} must be an integer."
    return None


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _http_status_error(status_code: int) -> ToolResult | None:
    if status_code in {408, 425, 429} or status_code >= 500:
        return ToolResult(status="error", error="transient_error", message=f"HTTP status {status_code}")
    if status_code >= 400:
        return ToolResult(status="error", error="permanent_error", message=f"HTTP status {status_code}")
    return None


def _content_type_header(headers: dict[str, str]) -> str:
    value = headers.get("content-type") or headers.get("Content-Type") or "application/octet-stream"
    return value.strip()


def _media_type(content_type_header: str) -> str:
    return content_type_header.split(";", 1)[0].strip().lower()


def _encoding_from_content_type(content_type: str) -> str:
    lowered = content_type.lower()
    if "charset=" not in lowered:
        return "utf-8"
    start = lowered.rfind("charset=") + len("charset=")
    end = content_type.find(";", start)
    if end == -1:
        end = len(content_type)
    return content_type[start:end].strip() or "utf-8"


def _is_html_content_type(content_type: str) -> bool:
    return content_type in {"text/html", "application/xhtml+xml"}


def _is_supported_text_content_type(content_type: str) -> bool:
    return (
        _is_html_content_type(content_type)
        or content_type.startswith("text/")
        or content_type in {"application/json", "application/xml", "application/rss+xml"}
    )


def _extract_html_text(raw_html: str) -> str:
    extracted = trafilatura.extract(raw_html)
    if extracted:
        return extracted
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw_html)
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return unescape(re.sub(r"\s+", " ", without_tags))
