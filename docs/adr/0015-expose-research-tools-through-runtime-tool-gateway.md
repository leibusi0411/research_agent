# Expose Web Research tools through a runtime Tool Gateway

Web Research will call Web Search, Web Fetch Extract, Web PDF Download, and related agent tools through a Tool Gateway rather than embedding those implementations directly. The Tool Gateway centralizes tool registration, workflow permission checks, call recording, same-parameter low-level retries, and structured tool results; Local RAG and Knowledge Base Indexing remain fixed Core Service flows and are not registered as agent tools.
