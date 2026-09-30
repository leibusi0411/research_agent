from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
import trafilatura
from pypdf import PdfReader

from research_agent.core.config import WebToolsConfig, is_valid_http_url


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


# R-112: Workflow name constant — used by ToolGateway.call() and registry.
WEB_RESEARCH_WORKFLOW = "web_research"


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


class ScholarSearchProvider(Protocol):
    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        ...


class ArxivSearchProvider:
    """Academic search against the public arXiv Atom API (no API key)."""

    def __init__(
        self,
        *,
        endpoint: str = "https://export.arxiv.org/api/query",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.transport = transport

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        with httpx.Client(transport=self.transport, timeout=45) as client:
            response = client.get(
                self.endpoint,
                params={"search_query": f"all:{query}", "max_results": max_results},
            )
            response.raise_for_status()
            return _parse_arxiv_atom(response.text)


class SemanticScholarProvider:
    """Semantic Scholar Graph API (keyless 100 req/5min; optional key raises)."""

    def __init__(self, api_key: str = "", *, transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key
        self.transport = transport

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        headers = {"User-Agent": "research-agent/0.1"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        with httpx.Client(transport=self.transport, timeout=45, headers=headers) as client:
            response = client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": query, "limit": min(max_results, 20), "fields": "title,abstract,year,authors,url,externalIds"},
            )
            response.raise_for_status()
            return _parse_semantic_scholar(response.json())


def _parse_semantic_scholar(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for paper in payload.get("data", []) or []:
        authors = ", ".join(a.get("name", "") for a in paper.get("authors", []) or [])
        results.append({
            "title": paper.get("title", ""),
            "url": paper.get("url", "") or (paper.get("externalIds") or {}).get("DOI", ""),
            "authors": authors,
            "summary": paper.get("abstract") or "",
            "published": str(paper.get("year") or ""),
        })
    return results


class CrossrefProvider:
    """Crossref works API — DOI/venue metadata, keyless with polite UA."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        with httpx.Client(transport=self.transport, timeout=45, headers={"User-Agent": "research-agent/0.1 (mailto:unset)"}) as client:
            response = client.get(
                "https://api.crossref.org/works",
                params={"query": query, "rows": max_results, "select": "title,author,URL,issued,abstract"},
            )
            response.raise_for_status()
            return _parse_crossref(response.json())


def _parse_crossref(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in ((payload.get("message") or {}).get("items", []) or []):
        titles = item.get("title") or []
        authors = ", ".join(
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in item.get("author", []) or []
        )
        issued = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
        results.append({
            "title": " ".join(titles[:1]),
            "url": item.get("URL", ""),
            "authors": authors,
            "summary": (item.get("abstract") or "")[:500],
            "published": "-".join(str(p) for p in issued) if issued and issued[0] else "",
        })
    return results


class AggregatedScholarProvider:
    """Round-robin merge of the enabled scholar sources (R-290).

    One failing source degrades to the others — a scholar backend outage
    must not fail the tool call."""

    def __init__(self, sources: list[ScholarSearchProvider]) -> None:
        self.sources = sources
        self.sources_queried = 0

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        per_source = max(3, max_results // max(1, len(self.sources)))
        lists: list[list[dict[str, Any]]] = []
        for source in self.sources:
            try:
                lists.append(source.search(query, per_source))
                self.sources_queried += 1
            except Exception:
                logger.warning("scholar source failed; continuing with the rest", exc_info=True)
        merged: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        index = 0
        while len(merged) < max_results and any(lists):
            for i, chunk in enumerate(lists):
                if index < len(chunk):
                    item = chunk[index]
                    key = " ".join(item.get("title", "").lower().split())
                    if key and key not in seen_titles:
                        seen_titles.add(key)
                        merged.append(item)
                        if len(merged) >= max_results:
                            break
            index += 1
            if index > 200:
                break
        return merged


class GithubSearchProvider:
    """GitHub repository search — keyless 60 req/h, optional key raises to 5k."""

    def __init__(self, api_key: str = "", *, transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key
        self.transport = transport

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        headers = {"User-Agent": "research-agent/0.1", "Accept": "application/vnd.github+json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        with httpx.Client(transport=self.transport, timeout=45, headers=headers) as client:
            response = client.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "per_page": min(max_results, 30)},
            )
            response.raise_for_status()
            return [
                {
                    "title": item.get("full_name", ""),
                    "url": item.get("html_url", ""),
                    "description": item.get("description") or "",
                    "stars": item.get("stargazers_count", 0),
                    "language": item.get("language") or "",
                }
                for item in response.json().get("items", []) or []
            ]


class GdeltNewsProvider:
    """GDELT DOC 2.0 article list — keyless global news timeline."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        with httpx.Client(transport=self.transport, timeout=45) as client:
            response = client.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={"query": query, "mode": "artlist", "maxrecords": min(max_results, 75), "format": "json", "sort": "datedesc"},
            )
            response.raise_for_status()
            return _parse_gdelt(response.json())


class YouTubeTranscriptProvider:
    """Fetch a YouTube video transcript (keyless via youtube-transcript-api)."""

    def __init__(self, *, transcript_fetch=None) -> None:
        if transcript_fetch is None:
            from youtube_transcript_api import YouTubeTranscriptApi

            api = YouTubeTranscriptApi()
            transcript_fetch = lambda video_id, languages: api.fetch(  # noqa: E731
                video_id, languages=languages
            )
        self._fetch = transcript_fetch

    def fetch(self, video_id: str) -> str:
        fetched = self._fetch(video_id, languages=["en", "zh-Hans", "zh"])
        return " ".join(segment.text.strip() for segment in fetched if segment.text)


def _youtube_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        return parsed.path.lstrip("/").split("/")[0]
    if host in {"youtube.com", "youtube-nocookie.com"}:
        if parsed.path.startswith("/watch"):
            for pair in parsed.query.split("&"):
                if pair.startswith("v="):
                    return pair[2:]
        for prefix in ("/shorts/", "/embed/", "/live/"):
            if parsed.path.startswith(prefix):
                return parsed.path[len(prefix):].split("/")[0]
    return ""


def _parse_gdelt(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for article in payload.get("articles", []) or []:
        seen = str(article.get("seendate", ""))
        published = f"{seen[0:4]}-{seen[4:6]}-{seen[6:8]}" if len(seen) >= 8 else ""
        results.append({
            "title": article.get("title", ""),
            "url": article.get("url", ""),
            "domain": article.get("domain", ""),
            "published": published,
            "summary": "",
        })
    return results


def _parse_arxiv_atom(xml_text: str) -> list[dict[str, Any]]:
    """Parse an arXiv Atom feed into the generic search-result shape."""
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ElementTree.fromstring(xml_text)
    results: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        url = ""
        for link in entry.findall("atom:link", ns):
            if link.get("type") == "application/pdf":
                url = link.get("href") or ""
                break
        if not url:
            url = entry.findtext("atom:id", default="", namespaces=ns) or ""
        authors = ", ".join(
            (author.findtext("atom:name", default="", namespaces=ns) or "").strip()
            for author in entry.findall("atom:author", ns)
        )
        results.append(
            {
                "title": " ".join(title.split()),
                "url": url.strip(),
                "authors": authors,
                "summary": " ".join(
                    (entry.findtext("atom:summary", default="", namespaces=ns) or "").split()
                ),
                "published": (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()[:10],
            }
        )
    return results


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    truncated: bool = False


class PythonSandboxClient(Protocol):
    def run(self, code: str, *, timeout_seconds: int) -> dict[str, Any]:
        ...


class PythonSandbox:
    """Run a short Python snippet in an isolated subprocess (ADR-0051).

    v1 trust boundary: local trusted execution — the code comes from the
    Executor role of this very agent, not from an untrusted user upload.
    Isolation is *process-level only*: fresh temp working directory,
    ``-I -X utf8`` interpreter mode (no user site / env overrides, UTF-8
    stdio so Chinese output survives non-UTF8 ANSI codepages), stdin
    closed, wall-clock timeout that kills the whole process *tree*
    (a grandchild holding the output pipe must not hang the executor).
    There is no network or filesystem confinement — that would need a
    container jail.
    """

    def __init__(self, *, python_executable: str | None = None, max_output_chars: int = 16_000) -> None:
        self.python_executable = python_executable or sys.executable
        self.max_output_chars = max_output_chars

    def run(self, code: str, *, timeout_seconds: int) -> dict[str, Any]:
        workdir = tempfile.mkdtemp(prefix="ra_sandbox_")
        try:
            script = Path(workdir) / "snippet.py"
            script.write_text(code, encoding="utf-8")
            process = subprocess.Popen(
                [self.python_executable, "-I", "-X", "utf8", str(script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                cwd=workdir,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=sys.platform != "win32",
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                _kill_process_tree(process)
                # Reap what is left of the pipes after the tree kill; if even
                # that stalls, give up on the output rather than blocking.
                try:
                    stdout, stderr = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    stdout, stderr = "", ""
                raise TimeoutError(f"Python snippet timed out after {timeout_seconds}s") from exc
        finally:
            # ignore_errors: a surviving grandchild may still hold the dir.
            shutil.rmtree(workdir, ignore_errors=True)
        stdout = stdout or ""
        stderr = stderr or ""
        bounded_stdout, bounded_stderr, truncated = _bound_text(stdout, stderr, self.max_output_chars)
        return {
            "stdout": bounded_stdout,
            "stderr": bounded_stderr,
            "exit_code": process.returncode,
            "output_truncated": truncated,
        }


def _kill_process_tree(process: subprocess.Popen[Any]) -> None:
    """Kill the sandbox process and everything it spawned.

    ``Popen.kill`` only reaps the direct child; a grandchild holding the
    inherited stdout pipe keeps ``communicate`` blocked on Windows, so the
    timeout would not actually be enforced.
    """
    with contextlib.suppress(Exception):
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)


def _bound_text(stdout: str, stderr: str, max_chars: int) -> tuple[str, str, bool]:
    """Clip each stream independently to *max_chars* with an ellipsis marker."""
    truncated = len(stdout) > max_chars or len(stderr) > max_chars
    bounded_stdout = stdout[:max_chars] + ("…" if len(stdout) > max_chars else "")
    bounded_stderr = stderr[:max_chars] + ("…" if len(stderr) > max_chars else "")
    return bounded_stdout, bounded_stderr, truncated


class HttpClient(Protocol):
    def get(self, url: str, *, timeout_seconds: int, max_bytes: int | None = None) -> FetchResponse:
        ...


# Present as a mainstream browser: a bare httpx UA is insta-403'd by many
# news and docs sites, which used to turn fetch_extract into dead ends.
_BROWSER_REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}


class HttpxHttpClient:
    def __init__(self, client_factory: Any | None = None) -> None:
        self.client_factory = client_factory or httpx.Client

    def get(self, url: str, *, timeout_seconds: int, max_bytes: int | None = None) -> FetchResponse:
        with self.client_factory(follow_redirects=True, timeout=timeout_seconds) as client:
            with client.stream("GET", url, headers=_BROWSER_REQUEST_HEADERS) as response:
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
        scholar_provider: ScholarSearchProvider | None = None,
        python_sandbox: PythonSandboxClient | None = None,
        youtube_provider: YouTubeTranscriptProvider | None = None,
        github_provider: Any | None = None,
        news_provider: Any | None = None,
    ) -> None:
        self.config = config
        self.search_provider = search_provider
        self.http_client = http_client or HttpxHttpClient()
        self.scholar_provider = scholar_provider
        self.python_sandbox = python_sandbox
        self.youtube_provider = youtube_provider
        self.github_provider = github_provider
        self.news_provider = news_provider

    def run(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        try:
            if tool_name == "web.search":
                return self._run_search(arguments)
            if tool_name == "github.search":
                return self._run_provider_search("GitHub", self.github_provider, arguments)
            if tool_name == "news.search":
                return self._run_provider_search("news", self.news_provider, arguments)
            if tool_name == "scholar.search":
                return self._run_scholar_search(arguments)
            if tool_name == "code.run_python":
                return self._run_run_python(arguments)
            if tool_name == "web.fetch_extract":
                return self._run_fetch_extract(arguments)
            if tool_name == "web.download_pdf":
                return self._run_download_pdf(arguments)
            if tool_name == "web.crawl_site":
                return self._run_crawl_site(arguments)
            if tool_name == "media.youtube_transcript":
                return self._run_youtube_transcript(arguments)
            if tool_name == "data.fetch_table":
                return self._run_fetch_table(arguments)
        except TimeoutError as exc:
            # A killed snippet may just have raced the wall clock; let the
            # gateway's transient retry policy decide whether to re-run it.
            return ToolResult(status="error", error="transient_error", message=str(exc))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return ToolResult(status="error", error="transient_error", message=str(exc))
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            # Surface the provider's own detail (e.g. Tavily quota exhaustion
            # on 432) so the failure reason reaches the model and the UI
            # instead of a bare status code.
            detail = ""
            with contextlib.suppress(Exception):
                detail = (exc.response.text or "").strip().replace("\n", " ")[:200]
            suffix = f": {detail}" if detail else ""
            if status_code in {408, 425, 429} or status_code >= 500:
                return ToolResult(status="error", error="transient_error", message=f"HTTP status {status_code}{suffix}")
            return ToolResult(status="error", error="permanent_error", message=f"HTTP status {status_code}{suffix}")
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

    def _run_scholar_search(self, arguments: dict[str, Any]) -> ToolResult:
        if self.scholar_provider is None:
            return ToolResult(status="error", error="permanent_error", message="Scholar search provider is not configured.")
        max_results = int(arguments.get("max_results") or self.config.search_top_k)
        if max_results <= 0:
            return ToolResult(status="error", error="validation_error", message="max_results must be positive.")
        max_results = min(max_results, self.config.search_top_k_max)
        results = self.scholar_provider.search(str(arguments["query"]), max_results)
        return ToolResult(status="ok", data={"results": results}, metadata={"max_results": max_results})

    def _run_provider_search(self, label: str, provider: Any, arguments: dict[str, Any]) -> ToolResult:
        if provider is None:
            return ToolResult(status="error", error="permanent_error", message=f"{label} search provider is not configured.")
        max_results = int(arguments.get("max_results") or self.config.search_top_k)
        if max_results <= 0:
            return ToolResult(status="error", error="validation_error", message="max_results must be positive.")
        max_results = min(max_results, self.config.search_top_k_max)
        results = provider.search(str(arguments["query"]), max_results)
        return ToolResult(status="ok", data={"results": results}, metadata={"max_results": max_results})

    def _run_crawl_site(self, arguments: dict[str, Any]) -> ToolResult:
        seed_url = str(arguments["url"])
        if not is_valid_http_url(seed_url):
            return ToolResult(status="error", error="validation_error", message="url must be http or https.")
        max_pages = min(int(arguments.get("max_pages", 5) or 5), _CRAWL_MAX_PAGES)
        if max_pages <= 0:
            return ToolResult(status="error", error="validation_error", message="max_pages must be positive.")
        seed = urlparse(seed_url)
        candidates: list[str] = []
        # 1) try the seed's own sitemap.xml
        sitemap_url = f"{seed.scheme}://{seed.netloc}/sitemap.xml"
        try:
            sitemap = self.http_client.get(
                sitemap_url, timeout_seconds=self.config.request_timeout_seconds,
                max_bytes=self.config.max_response_bytes,
            )
            if sitemap.status_code == 200:
                candidates = _extract_sitemap_urls(seed_url, sitemap.content.decode("utf-8", errors="replace"))
        except Exception:
            candidates = []
        # 2) fall back to same-domain links from the seed page
        if not candidates:
            page = self.http_client.get(
                seed_url, timeout_seconds=self.config.request_timeout_seconds,
                max_bytes=self.config.max_response_bytes,
            )
            if page.status_code != 200:
                return ToolResult(status="error", error="permanent_error", message=f"Seed page returned HTTP {page.status_code}")
            raw = page.content.decode(_encoding_from_content_type(_content_type_header(page.headers)), errors="replace")
            candidates = _extract_page_links(seed_url, raw)
        pages: list[dict[str, Any]] = []
        seen: set[str] = {seed_url}
        for url in candidates:
            if len(pages) >= max_pages:
                break
            if url in seen:
                continue
            seen.add(url)
            response = self.http_client.get(
                url, timeout_seconds=self.config.request_timeout_seconds,
                max_bytes=self.config.max_response_bytes,
            )
            if response.status_code != 200:
                continue
            media_type = _media_type(_content_type_header(response.headers))
            if not _is_html_content_type(media_type):
                continue
            raw_text = response.content.decode(_encoding_from_content_type(_content_type_header(response.headers)), errors="replace")
            text = _extract_html_text(raw_text)[:_CRAWL_PAGE_TEXT_CHARS]
            if text.strip():
                pages.append({"url": url, "text": text})
        return ToolResult(status="ok", data={"pages": pages, "count": len(pages)}, metadata={"crawled": len(pages)})

    def _run_youtube_transcript(self, arguments: dict[str, Any]) -> ToolResult:
        if self.youtube_provider is None:
            return ToolResult(status="error", error="permanent_error", message="YouTube transcript provider is not configured.")
        url = str(arguments["url"])
        video_id = _youtube_video_id(url)
        if not video_id:
            return ToolResult(status="error", error="validation_error", message="url must be a YouTube video link.")
        try:
            text = self.youtube_provider.fetch(video_id)
        except Exception as exc:
            return ToolResult(status="error", error="permanent_error", message=f"YouTube transcript fetch failed: {exc}")
        return ToolResult(status="ok", data={"video_id": video_id, "text": text[:16_000]})

    def _run_fetch_table(self, arguments: dict[str, Any]) -> ToolResult:
        import csv
        import io as _io

        url = str(arguments["url"])
        if not is_valid_http_url(url):
            return ToolResult(status="error", error="validation_error", message="url must be http or https.")
        response = self.http_client.get(
            url, timeout_seconds=self.config.request_timeout_seconds,
            max_bytes=self.config.max_response_bytes,
        )
        status_error = _http_status_error(response.status_code)
        if status_error is not None:
            return status_error
        media_type = _media_type(_content_type_header(response.headers))
        rows: list[list[str]] = []
        if media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" or urlparse(response.url).path.lower().endswith((".xlsx", ".xlsm")):
            from openpyxl import load_workbook

            workbook = load_workbook(_io.BytesIO(response.content), read_only=True)
            sheet = workbook.active
            for row in sheet.iter_rows(values_only=True):
                rows.append(["" if cell is None else str(cell) for cell in row])
        else:
            text = response.content.decode("utf-8-sig", errors="replace")
            rows = [[cell for cell in row] for row in csv.reader(text.splitlines()) if row]
        rows = [row for row in rows if any(cell.strip() for cell in row)]
        if not rows:
            return ToolResult(status="error", error="permanent_error", message="Table is empty or unreadable.")
        cols = max(len(row) for row in rows)

        def cell(value: str) -> str:
            value = value.replace("|", "/").replace("\n", " ").strip()
            return value[:40]

        preview_rows = rows[:31]
        lines = ["| " + " | ".join(cell(c) for c in row + [""] * (cols - len(row))) + " |" for row in preview_rows]
        lines.insert(1, "|" + "---|" * cols)
        preview = "\n".join(lines)
        return ToolResult(
            status="ok",
            data={"rows": max(0, len(rows) - 1), "cols": cols, "preview": preview},
            metadata={"content_type": media_type},
        )

    def _run_run_python(self, arguments: dict[str, Any]) -> ToolResult:
        if self.python_sandbox is None:
            return ToolResult(status="error", error="permanent_error", message="Python sandbox is not configured.")
        outcome = self.python_sandbox.run(str(arguments["code"]), timeout_seconds=self.config.python_timeout_seconds)
        return ToolResult(
            status="ok",
            data=outcome,
            metadata={"python_timeout_seconds": self.config.python_timeout_seconds},
        )

    def _run_fetch_extract(self, arguments: dict[str, Any]) -> ToolResult:
        url = str(arguments["url"])
        if not is_valid_http_url(url):
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
        if not is_valid_http_url(url):
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
        # R-31: Validate MIME type first; only fall back to URL suffix for
        # ambiguous content types (e.g. servers that serve PDF as octet-stream).
        if media_type == "application/octet-stream":
            if not urlparse(response.url).path.lower().endswith(".pdf"):
                return ToolResult(status="error", error="permanent_error", message=f"Unsupported PDF content type: {media_type}")
        elif media_type != "application/pdf":
            return ToolResult(status="error", error="permanent_error", message=f"Unsupported PDF content type: {media_type}")
        reader = PdfReader(io.BytesIO(response.content))
        pages = [page.extract_text() or "" for page in reader.pages]
        return ToolResult(
            status="ok",
            data={"url": response.url, "text": "\n".join(pages).strip(), "page_count": len(reader.pages)},
            metadata={"content_type": media_type, "pdf_bytes": len(response.content)},
        )


_CRAWL_MAX_PAGES = 10
_CRAWL_PAGE_TEXT_CHARS = 4_000


class SiteCrawlMixin:
    """Shared crawl helpers used by ToolRunner (R-290)."""


def _extract_sitemap_urls(seed_url: str, body: str) -> list[str]:
    root = ElementTree.fromstring(body)
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [loc.text or "" for loc in root.findall(".//sm:loc", namespace)]
    if not locs:  # sitemap without namespace binding
        locs = [m.group(1) for m in re.finditer(r"<loc>([^<]+)</loc>", body)]
    seed_host = urlparse(seed_url).netloc
    return [u.strip() for u in locs if urlparse(u).netloc == seed_host]


def _extract_page_links(base_url: str, raw_html: str) -> list[str]:
    seed = urlparse(base_url)
    links: list[str] = []
    for match in re.finditer(r"""href=["']([^"'#]+)["']""", raw_html):
        candidate = match.group(1)
        if candidate.startswith("http") and urlparse(candidate).netloc == seed.netloc:
            links.append(candidate.split("#")[0])
    return links


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
        retries = 0
        while result.status == "error" and result.error == "transient_error" and retries < self.tool_retries:
            retries += 1
            result = self.runner.run(tool_name, arguments)
        return result


def create_default_web_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="web.search",
            allowed_workflows={WEB_RESEARCH_WORKFLOW},
            input_schema={
                "query": {"type": "string", "required": True},
                "max_results": {"type": "integer", "required": False},
            },
        )
    )
    registry.register(
        ToolSpec(
            name="scholar.search",
            allowed_workflows={WEB_RESEARCH_WORKFLOW},
            input_schema={
                "query": {"type": "string", "required": True},
                "max_results": {"type": "integer", "required": False},
            },
        )
    )
    registry.register(
        ToolSpec(
            name="github.search",
            allowed_workflows={WEB_RESEARCH_WORKFLOW},
            input_schema={
                "query": {"type": "string", "required": True},
                "max_results": {"type": "integer", "required": False},
            },
        )
    )
    registry.register(
        ToolSpec(
            name="news.search",
            allowed_workflows={WEB_RESEARCH_WORKFLOW},
            input_schema={
                "query": {"type": "string", "required": True},
                "max_results": {"type": "integer", "required": False},
            },
        )
    )
    registry.register(
        ToolSpec(
            name="web.crawl_site",
            allowed_workflows={WEB_RESEARCH_WORKFLOW},
            input_schema={
                "url": {"type": "string", "required": True},
                "max_pages": {"type": "integer", "required": False},
            },
        )
    )
    registry.register(
        ToolSpec(
            name="media.youtube_transcript",
            allowed_workflows={WEB_RESEARCH_WORKFLOW},
            input_schema={"url": {"type": "string", "required": True}},
        )
    )
    registry.register(
        ToolSpec(
            name="data.fetch_table",
            allowed_workflows={WEB_RESEARCH_WORKFLOW},
            input_schema={"url": {"type": "string", "required": True}},
        )
    )
    registry.register(
        ToolSpec(
            name="code.run_python",
            allowed_workflows={WEB_RESEARCH_WORKFLOW},
            input_schema={"code": {"type": "string", "required": True}},
        )
    )
    registry.register(
        ToolSpec(
            name="web.fetch_extract",
            allowed_workflows={WEB_RESEARCH_WORKFLOW},
            input_schema={"url": {"type": "string", "required": True}},
        )
    )
    registry.register(
        ToolSpec(
            name="web.download_pdf",
            allowed_workflows={WEB_RESEARCH_WORKFLOW},
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
