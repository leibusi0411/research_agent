# Execute Local RAG and Web Research as separate task modes

Local RAG and Web Research are separate task modes in v1 rather than two flows inside the same Research Task. `research-agent local "question"` presents relevant existing local content linked to source files, while `research-agent web "question"` runs the recoverable Web Research state graph and writes a local Markdown Web Report File; neither mode cross-calls the other's tools or shares intermediate context.

`research-agent both "question"` is a CLI convenience command that starts one Local RAG task and one Web Research task for the same question as two independent tasks. It does not create a combined workflow, does not merge intermediate context, does not feed Local Results into Web Research, and does not create a combined report.
