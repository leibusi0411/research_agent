"""Query rewrite (ADR-0052) and rerank (ADR-0053) retrieval enhancements.

All tests are offline and deterministic: LLM and rerank endpoints are fakes.
"""

from typing import Any

from research_agent.core.local_research import rewrite_question


class _RewriteChatModel:
    """Fake chat model returning a canned rewrite response (or raising)."""

    def __init__(self, response: str | Exception) -> None:
        self._response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str, json_mode: bool = False) -> str:
        self.prompts.append(prompt)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    def complete_tool(self, prompt: str, *, tool_name: str, tool_schema: dict[str, Any]) -> Any:
        raise AssertionError("rewrite_question must use plain complete(), not tool calling")


def test_rewrite_question_parses_numbered_lines():
    model = _RewriteChatModel(
        "1. reduce cost keyword\n2. What are effective ways for a team to reduce its costs"
    )

    variants = rewrite_question("How to Reduce Costs", model)

    assert variants == [
        "reduce cost keyword",
        "What are effective ways for a team to reduce its costs",
    ]


def test_rewrite_question_strips_bullets_and_quotes():
    model = _RewriteChatModel('- "cost optimization"\n• Cost Optimization\n" saving money tips "')

    variants = rewrite_question("How to Reduce Costs", model)

    assert variants == ["cost optimization", "saving money tips"]


def test_rewrite_question_drops_empty_duplicate_and_original():
    model = _RewriteChatModel(
        "\nhow to reduce costs\ncost saving methods\ncost saving methods\n3. budget planning"
    )

    variants = rewrite_question("How to Reduce Costs", model)

    # Numbered prefix of the last line is stripped; blanks/dup/original dropped.
    assert variants == ["cost saving methods", "budget planning"]


def test_rewrite_question_caps_at_max_variants():
    model = _RewriteChatModel("a\nb\nc\nd")

    variants = rewrite_question("q", model, max_variants=2)

    assert variants == ["a", "b"]


def test_rewrite_question_returns_empty_on_llm_error():
    model = _RewriteChatModel(RuntimeError("provider down"))

    assert rewrite_question("q", model) == []


def test_rewrite_question_prompts_once_with_original_question():
    model = _RewriteChatModel("variant one")

    rewrite_question("original question", model)

    assert len(model.prompts) == 1
    assert "original question" in model.prompts[0]


# ---------------------------------------------------------------------------
# RRF multi-list fusion (ADR-0052)
# ---------------------------------------------------------------------------

from pathlib import Path

from research_agent.core.local_research import rrf_fuse


def _item(source: str, start: int) -> dict[str, Any]:
    return {
        "source_path": source,
        "start_offset": start,
        "end_offset": start + 5,
        "text": f"{source}:{start}",
    }


def test_rrf_fuse_merges_ranked_lists_by_reciprocal_rank():
    list_a = [_item("a.md", 0), _item("a.md", 10), _item("a.md", 20)]
    list_b = [_item("a.md", 0), _item("a.md", 10), _item("b.md", 0)]

    fused = rrf_fuse([list_a, list_b], top_k=3)

    # a.md:0 → 2/61, a.md:10 → 2/62, a.md:20 → 1/63 (ties with b.md:0 at 1/63,
    # first-seen wins) — hand-computed expected order.
    assert [item["text"] for item in fused] == ["a.md:0", "a.md:10", "a.md:20"]


def test_rrf_fuse_dedups_same_chunk_across_lists():
    duplicate = _item("a.md", 0)

    fused = rrf_fuse([[duplicate], [dict(duplicate)]], top_k=5)

    assert len(fused) == 1
    assert fused[0]["text"] == "a.md:0"


def test_rrf_fuse_handles_empty_and_single_lists():
    assert rrf_fuse([[], []], top_k=3) == []
    fused = rrf_fuse([[_item("a.md", 0)]], top_k=3)
    assert [item["text"] for item in fused] == ["a.md:0"]


# ---------------------------------------------------------------------------
# Multi-Query wiring in run_local_research (ADR-0052)
# ---------------------------------------------------------------------------

from research_agent.core.config import InitConfigRequest
from research_agent.core.ids import generate_task_id
from research_agent.core.service import CoreService

_REWRITE_PROMPT_MARKER = "查询变体"


class _RewriteSummaryChatModel:
    """First call (rewrite prompt) answers with variants; later calls summarize."""

    def __init__(self, variants: str, *, fail_rewrite: bool = False) -> None:
        self._variants = variants
        self._fail_rewrite = fail_rewrite
        self.prompts: list[str] = []

    def complete(self, prompt: str, json_mode: bool = False) -> str:
        self.prompts.append(prompt)
        if _REWRITE_PROMPT_MARKER in prompt:
            if self._fail_rewrite:
                raise RuntimeError("rewrite provider down")
            return self._variants
        return "Summarized answer."

    def complete_tool(self, prompt: str, *, tool_name: str, tool_schema: dict[str, Any]) -> Any:
        raise AssertionError("local research must not use tool calling")


class _FixedEmbeddingClient:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _text in texts]


def _configured_service(tmp_path: Path, *, query_rewrite: bool) -> tuple[CoreService, Path]:
    config_path = tmp_path / "config.toml"
    workspace = tmp_path / "runtime"
    vault = tmp_path / "vault"
    vault.mkdir()
    service = CoreService(default_workspace=workspace, config_path=config_path)
    service.init_config(
        InitConfigRequest(
            default_workspace=workspace,
            knowledge_base_path=vault,
            chat_base_url="https://models.example/v1",
            chat_api_key="chat-key",
            chat_model="chat-model",
            embedding_base_url="https://embeddings.example/v1",
            embedding_api_key="embedding-key",
            embedding_model="embedding-model",
            search_api_key="search-key",
        )
    )
    if query_rewrite:
        # ADR-0052 evolution (2026-09-16): the [research] toggle is gone —
        # the local_summarizer slot section is the switch.
        content = config_path.read_text(encoding="utf-8") + (
            "\n[chat_model.local_summarizer]\n"
            'model = "rewrite-model"\n'
        )
        config_path.write_text(content, encoding="utf-8")
    return service, config_path


def _seed_vault(vault: Path) -> None:
    (vault / "tomato.md").write_text(
        "# Tomato\n\nWatering tomato plants keeps the soil moist.", encoding="utf-8"
    )
    (vault / "greenhouse.md").write_text(
        "# Greenhouse\n\nGreenhouse humidity control prevents plant mold.", encoding="utf-8"
    )


def test_query_rewrite_reaches_notes_only_matching_a_variant(tmp_path):
    service, _config_path = _configured_service(tmp_path, query_rewrite=True)
    _seed_vault(tmp_path / "vault")
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())
    # The variant mentions greenhouse terms that the original question lacks.
    model = _RewriteSummaryChatModel("greenhouse humidity control")

    result = service.run_local_research_unlocked(
        "watering tomato plants",
        task_id=generate_task_id(),
        embedding_client=None,  # FTS5-only: the greenhouse note is unreachable
        chat_model=model,       # without the rewritten query
    )

    assert result["status"] == "completed"
    texts = " ".join(item["text"] for item in result["local_results"])
    assert "Watering tomato plants" in texts
    assert "Greenhouse humidity control" in texts


def test_query_rewrite_disabled_keeps_original_question_only(tmp_path):
    service, _config_path = _configured_service(tmp_path, query_rewrite=False)
    _seed_vault(tmp_path / "vault")
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())
    model = _RewriteSummaryChatModel("greenhouse humidity control")

    result = service.run_local_research_unlocked(
        "watering tomato plants",
        task_id=generate_task_id(),
        embedding_client=None,
        chat_model=model,
    )

    assert result["status"] == "completed"
    texts = " ".join(item["text"] for item in result["local_results"])
    assert "Watering tomato plants" in texts
    assert "Greenhouse humidity control" not in texts
    # No rewrite prompt was ever sent.
    assert not any(_REWRITE_PROMPT_MARKER in prompt for prompt in model.prompts)


def test_query_rewrite_llm_failure_degrades_to_original_question(tmp_path):
    service, _config_path = _configured_service(tmp_path, query_rewrite=True)
    _seed_vault(tmp_path / "vault")
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())
    model = _RewriteSummaryChatModel("ignored", fail_rewrite=True)

    result = service.run_local_research_unlocked(
        "watering tomato plants",
        task_id=generate_task_id(),
        embedding_client=None,
        chat_model=model,
    )

    assert result["status"] == "completed"
    texts = " ".join(item["text"] for item in result["local_results"])
    assert "Watering tomato plants" in texts


# ---------------------------------------------------------------------------
# RerankClient protocol + /rerank API model (ADR-0053)
# ---------------------------------------------------------------------------

from research_agent.core.config import ModelConfig
from research_agent.core.providers import RerankApiModel


def test_rerank_api_model_posts_query_and_documents_and_parses_scores():
    captured: dict[str, Any] = {}

    def fake_post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return {
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.2},
            ]
        }

    client = RerankApiModel.from_config(
        ModelConfig(
            provider="rerank_api",
            base_url="https://api.example/v1",
            api_key="rerank-key",
            model="bge-reranker-v2-m3",
        ),
        post_json=fake_post_json,
    )

    pairs = client.rerank("how to reduce costs", ["doc zero", "doc one"])

    assert captured["url"] == "https://api.example/v1/rerank"
    assert captured["payload"] == {
        "model": "bge-reranker-v2-m3",
        "query": "how to reduce costs",
        "documents": ["doc zero", "doc one"],
    }
    assert captured["headers"]["Authorization"] == "Bearer rerank-key"
    # Pairs come back sorted by relevance score, descending.
    assert pairs == [(1, 0.9), (0, 0.2)]


# ---------------------------------------------------------------------------
# Rerank integration in retrieve_local_chunks (ADR-0053)
# ---------------------------------------------------------------------------

from research_agent.core.local_research import retrieve_local_chunks


class _AlphabeticalRerankClient:
    """Deterministic reranker: sorts candidates alphabetically by text."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        self.calls.append((query, list(documents)))
        order = sorted(range(len(documents)), key=lambda i: documents[i])
        return [(i, float(len(documents) - position)) for position, i in enumerate(order)]


class _FailingRerankClient:
    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        raise RuntimeError("rerank endpoint unreachable")


def _service_with_common_notes(tmp_path: Path, note_count: int) -> CoreService:
    service, _config_path = _configured_service(tmp_path, query_rewrite=False)
    for i in range(note_count):
        (tmp_path / "vault" / f"note{i:02d}.md").write_text(
            f"# Note\n\ncommon unique{i:02d}", encoding="utf-8"
        )
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())
    return service


def test_retrieve_local_chunks_applies_rerank_before_truncation(tmp_path):
    service = _service_with_common_notes(tmp_path, note_count=12)
    reranker = _AlphabeticalRerankClient()

    results = retrieve_local_chunks(
        sqlite_path=service.workspace.local_index_dir / "fts.sqlite",
        chroma_path=service.workspace.local_index_dir.parent / "chroma",
        question="common",
        embedding_client=None,  # FTS5-only: 12 candidates, deterministic set
        rerank_client=reranker,
    )

    # 12 candidates fetched, reranked alphabetically, truncated to top 10.
    assert len(reranker.calls) == 1
    assert len(reranker.calls[0][1]) == 12
    assert [item["text"] for item in results] == [f"common unique{i:02d}" for i in range(10)]


def test_retrieve_local_chunks_skips_rerank_when_candidates_fit_top_k(tmp_path):
    service = _service_with_common_notes(tmp_path, note_count=2)
    reranker = _AlphabeticalRerankClient()

    retrieve_local_chunks(
        sqlite_path=service.workspace.local_index_dir / "fts.sqlite",
        chroma_path=service.workspace.local_index_dir.parent / "chroma",
        question="common",
        embedding_client=None,
        rerank_client=reranker,
    )

    assert reranker.calls == []


def test_retrieve_local_chunks_falls_back_to_rrf_order_when_rerank_fails(tmp_path):
    service = _service_with_common_notes(tmp_path, note_count=12)
    retrieve = lambda rerank_client: retrieve_local_chunks(  # noqa: E731
        sqlite_path=service.workspace.local_index_dir / "fts.sqlite",
        chroma_path=service.workspace.local_index_dir.parent / "chroma",
        question="common",
        embedding_client=None,
        rerank_client=rerank_client,
    )

    baseline = retrieve(None)
    degraded = retrieve(_FailingRerankClient())

    assert [item["text"] for item in degraded] == [item["text"] for item in baseline]
    assert len(degraded) == 10


# ---------------------------------------------------------------------------
# Service wiring: rerank client builder + pass-through + prior knowledge (ADR-0053)
# ---------------------------------------------------------------------------

import research_agent.core.service as service_module
from research_agent.core.config import load_user_config
from research_agent.core.service import build_local_retriever, build_rerank_client


class _SummaryChatModel:
    def complete(self, prompt: str, json_mode: bool = False) -> str:
        return "Summarized answer."

    def complete_tool(self, prompt: str, *, tool_name: str, tool_schema: dict[str, Any]) -> Any:
        raise AssertionError("not used")


def _enable_rerank(config_path: Path) -> None:
    content = (
        config_path.read_text(encoding="utf-8").replace("rerank = false", "rerank = true")
        + "\n[rerank_model]\n"
        + 'base_url = "https://rerank.example/v1"\n'
        + 'api_key = "rerank-key"\n'
        + 'model = "bge-reranker-v2-m3"\n'
    )
    config_path.write_text(content, encoding="utf-8")


def test_build_rerank_client_returns_none_when_section_absent(tmp_path):
    service, config_path = _configured_service(tmp_path, query_rewrite=False)

    client = build_rerank_client(load_user_config(config_path), offline=False)

    assert client is None


def test_build_rerank_client_returns_model_when_configured(tmp_path):
    service, config_path = _configured_service(tmp_path, query_rewrite=False)
    _enable_rerank(config_path)

    client = build_rerank_client(load_user_config(config_path), offline=False)

    assert isinstance(client, RerankApiModel)
    assert client.config.model == "bge-reranker-v2-m3"


def test_build_rerank_client_returns_none_when_offline(tmp_path):
    service, config_path = _configured_service(tmp_path, query_rewrite=False)
    _enable_rerank(config_path)

    client = build_rerank_client(load_user_config(config_path), offline=True)

    assert client is None


def test_local_rag_uses_injected_rerank_client_end_to_end(tmp_path):
    service = _service_with_common_notes(tmp_path, note_count=12)
    reranker = _AlphabeticalRerankClient()

    result = service.run_local_research(
        "common",
        embedding_client=_FixedEmbeddingClient(),
        chat_model=_SummaryChatModel(),
        rerank_client=reranker,
    )

    assert result["status"] == "completed"
    assert len(reranker.calls) == 1
    assert [item["text"] for item in result["local_results"]] == [
        f"common unique{i:02d}" for i in range(10)
    ]


def test_local_retriever_passes_rerank_client_for_prior_knowledge(tmp_path, monkeypatch):
    monkeypatch.delenv("RESEARCH_AGENT_OFFLINE", raising=False)
    service, config_path = _configured_service(tmp_path, query_rewrite=False)
    for i in range(8):
        (tmp_path / "vault" / f"note{i:02d}.md").write_text(
            f"# Note\n\nshared term variant{i:02d}", encoding="utf-8"
        )
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())
    _enable_rerank(config_path)

    recorded: dict[str, Any] = {}

    class _RecordingRerankModel:
        @classmethod
        def from_config(cls, config, *, post_json=None):
            return self_reranker

        def __init__(self) -> None:
            raise AssertionError("from_config is the construction seam")

    self_reranker = _AlphabeticalRerankClient()

    original_rerank = self_reranker.rerank

    def spying_rerank(query, documents):
        recorded["documents"] = list(documents)
        return original_rerank(query, documents)

    self_reranker.rerank = spying_rerank  # type: ignore[method-assign]
    monkeypatch.setattr(service_module, "RerankApiModel", _RecordingRerankModel)

    class _FakeEmbeddingModel:
        @classmethod
        def from_config(cls, config, *, post_json=None):
            return _FixedEmbeddingClient()

    monkeypatch.setattr(service_module, "OpenAICompatibleEmbeddingModel", _FakeEmbeddingModel)

    retriever = build_local_retriever(
        config=load_user_config(config_path),
        config_path=config_path,
        workspace=service.workspace,
    )

    assert retriever is not None
    chunks = retriever("shared term")
    assert len(recorded["documents"]) == 8
    assert len(chunks) == 5
    # Fake reranker sorted alphabetically → variant01 comes before variant07.
    assert chunks[0].text.endswith("variant00")


def test_retrieve_local_chunks_falls_back_when_rerank_returns_incomplete_ordering(tmp_path):
    """A reranker that drops candidates must not silently discard chunks."""
    service = _service_with_common_notes(tmp_path, note_count=12)

    class _PartialRerankClient:
        def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
            return [(0, 1.0)]  # incomplete: only one index of twelve

    baseline = retrieve_local_chunks(
        sqlite_path=service.workspace.local_index_dir / "fts.sqlite",
        chroma_path=service.workspace.local_index_dir.parent / "chroma",
        question="common",
        embedding_client=None,
    )
    degraded = retrieve_local_chunks(
        sqlite_path=service.workspace.local_index_dir / "fts.sqlite",
        chroma_path=service.workspace.local_index_dir.parent / "chroma",
        question="common",
        embedding_client=None,
        rerank_client=_PartialRerankClient(),
    )

    assert [item["text"] for item in degraded] == [item["text"] for item in baseline]


def test_rerank_api_model_accepts_score_field_fallback():
    """Provider drift: some rerank APIs answer with ``score`` instead of
    ``relevance_score`` — both must parse."""

    def fake_post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        return {"results": [{"index": 0, "score": 0.7}, {"index": 1, "score": 0.4}]}

    client = RerankApiModel.from_config(
        ModelConfig(
            provider="rerank_api",
            base_url="https://api.example/v1",
            api_key="rerank-key",
            model="bge-reranker-v2-m3",
        ),
        post_json=fake_post_json,
    )

    assert client.rerank("q", ["a", "b"]) == [(0, 0.7), (1, 0.4)]
