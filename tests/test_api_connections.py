"""Test real API connections: chat model, embedding model, and search API."""

import httpx


def test_chat_model():
    """Test DeepSeek chat model via OpenAI-compatible API."""
    from research_agent.core.config import load_user_config
    from research_agent.core.providers import OpenAICompatibleChatModel

    config = load_user_config()
    model = OpenAICompatibleChatModel.from_config(config.chat_model)
    result = model.complete("Say hello in one sentence.")
    print(f"[chat] {result}")
    assert len(result) > 0, "Chat model returned empty response"


def test_embedding_model():
    """Test SiliconFlow Qwen embedding model."""
    from research_agent.core.config import load_user_config
    from research_agent.core.providers import OpenAICompatibleEmbeddingModel

    config = load_user_config()
    model = OpenAICompatibleEmbeddingModel.from_config(config.embedding_model)
    vectors = model.embed(["hello world", "test embedding"])
    print(f"[embedding] Got {len(vectors)} vectors, dimension={len(vectors[0])}")
    assert len(vectors) == 2, "Expected 2 vectors"
    assert len(vectors[0]) > 0, "Embedding dimension is 0"


def test_search_api():
    """Test Tavily search API."""
    from research_agent.core.config import load_user_config

    config = load_user_config()
    api_key = config.search.api_key
    response = httpx.post(
        "https://api.tavily.com/search",
        json={"query": "What is LangGraph?", "max_results": 3},
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("results", [])
    print(f"[search] Got {len(results)} results")
    for r in results:
        print(f"  - {r.get('title', 'N/A')}")
    assert len(results) > 0, "Search returned no results"


if __name__ == "__main__":
    for name, fn in [("chat", test_chat_model), ("embedding", test_embedding_model), ("search", test_search_api)]:
        try:
            fn()
            print(f"  -> PASS\n")
        except Exception as e:
            print(f"  -> FAIL: {e}\n")
