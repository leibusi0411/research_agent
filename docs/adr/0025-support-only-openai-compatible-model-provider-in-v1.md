# Support only OpenAI-compatible model provider in v1

V1 model calls will implement only an `openai_compatible` provider for both chat and embedding models, configured with provider, model, base URL, and API key. The provider field remains in config so future releases can add other model backends without changing the configuration shape.
