# Default to Tavily through a Search Provider interface

Web Research will use a Search Provider interface through the Tool Gateway so Web Research code does not depend directly on a specific search SDK. The v1 default provider is Tavily because it fits AI research workflows, while configuration must allow replacing it later; if no search API key is configured, Web Research is unavailable but Local RAG results remain usable when indexes exist.
