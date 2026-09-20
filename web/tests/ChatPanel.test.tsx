import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatPanel } from "../src/components/ChatPanel";
import { ResultCards } from "../src/components/ResultView";
import { ResearchPage } from "../src/pages/ResearchPage";
import type { ResearchResult } from "../src/api";

// A finished web research task with two sources / two findings.
const webResult: ResearchResult = {
  task_id: "task_20260624_000001_bbbbbb",
  mode: "web",
  question: "web question",
  status: "completed",
  curator_output: {
    title: "Web",
    summary: "Web summary",
    findings: [
      { finding_id: "f_1", subtask_id: "st_1", text: "State machines finding", source_ids: ["src_1"] },
      { finding_id: "f_2", subtask_id: "st_2", text: "Checkpointing finding", source_ids: ["src_2"] }
    ],
    sources: [
      { source_id: "src_1", title: "LangGraph docs", url: "https://example.com/lg", fetched_at: "now" },
      { source_id: "src_2", title: "Checkpointing guide", url: "https://example.com/ckpt", fetched_at: "now" }
    ]
  },
  report_path: "D:/reports/web/report.md"
};

type Captured = { url: string; method?: string; body: Record<string, unknown> | null };

function stubChatFetch(reply: string, captures: Captured[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      captures.push({
        url,
        method: init?.method,
        body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
      });
      if (url.endsWith("/chat") && !init?.method) {
        return { ok: true, status: 200, text: async () => JSON.stringify({ task_id: webResult.task_id, messages: [] }) };
      }
      return { ok: true, status: 200, text: async () => JSON.stringify({ task_id: webResult.task_id, reply }) };
    })
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("ChatPanel", () => {
  it("renders the references card with all sources checked by default, and the chat area with input bar", async () => {
    const captures: Captured[] = [];
    stubChatFetch("reply", captures);

    render(<ChatPanel result={webResult} />);

    // References card lists every source with a checked checkbox.
    expect(await screen.findByText("LangGraph docs")).toBeInTheDocument();
    expect(screen.getByText("Checkpointing guide")).toBeInTheDocument();
    const checkboxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(checkboxes).toHaveLength(2);
    expect(checkboxes.every((box) => box.checked)).toBe(true);

    // Empty conversation hint and the input bar.
    expect(screen.getByText(/Ask a follow-up question/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/chat message/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("sends the message with the selected sources and shows the grounded reply", async () => {
    const captures: Captured[] = [];
    stubChatFetch("Checkpoints persist on disk.", captures);

    render(<ChatPanel result={webResult} />);
    await screen.findByText("LangGraph docs");

    // Narrow the grounding: uncheck the second source.
    await userEvent.click(screen.getAllByRole("checkbox")[1]);

    await userEvent.type(screen.getByLabelText(/chat message/i), "How does checkpointing work?");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("Checkpoints persist on disk.")).toBeInTheDocument();
    expect(screen.getByText("How does checkpointing work?")).toBeInTheDocument();

    const post = captures.find((c) => c.method === "POST");
    expect(post?.url).toContain(`/api/tasks/${webResult.task_id}/chat`);
    expect(post?.body?.message).toBe("How does checkpointing work?");
    expect(post?.body?.selected_sources).toEqual(["src_1"]);
  });

  it("reloads persisted conversation history on mount", async () => {
    const captures: Captured[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        captures.push({ url, method: init?.method, body: null });
        return {
          ok: true,
          status: 200,
          text: async () =>
            JSON.stringify({
              task_id: webResult.task_id,
              messages: [
                { role: "user", content: "Earlier question" },
                { role: "assistant", content: "Earlier answer" }
              ]
            })
        };
      })
    );

    render(<ChatPanel result={webResult} />);

    expect(await screen.findByText("Earlier question")).toBeInTheDocument();
    expect(screen.getByText("Earlier answer")).toBeInTheDocument();
    expect(captures[0]?.url).toContain(`/api/tasks/${webResult.task_id}/chat`);
  });
});

describe("ResearchPage chat entry", () => {
  const localOnly: ResearchResult = {
    task_id: "task_20260624_000000_aaaaaa",
    mode: "local",
    question: "local question",
    status: "completed",
    summary: "Local summary"
  };

  function renderResearch(result: ResearchResult) {
    return render(
      <ResearchPage
        question=""
        setQuestion={() => undefined}
        runResearch={() => undefined}
        busy={null}
        result={result}
        events={[]}
        phase={null}
        localContext={true}
        setLocalContext={() => undefined}
      />
    );
  }

  it("shows the chat panel after a completed web research run", async () => {
    stubChatFetch("reply", []);
    renderResearch(webResult);
    expect(await screen.findByRole("region", { name: /chat with this research/i })).toBeInTheDocument();
  });

  it("does not offer chat for local or failed tasks", () => {
    stubChatFetch("reply", []);
    const { rerender } = renderResearch(localOnly);
    expect(screen.queryByRole("region", { name: /chat with this research/i })).not.toBeInTheDocument();

    rerender(
      <ResearchPage
        question=""
        setQuestion={() => undefined}
        runResearch={() => undefined}
        busy={null}
        result={{ ...webResult, status: "failed", error: { code: "runtime_error", message: "boom" } }}
        events={[]}
        phase={null}
        localContext={true}
        setLocalContext={() => undefined}
      />
    );
    expect(screen.queryByRole("region", { name: /chat with this research/i })).not.toBeInTheDocument();
  });
});

describe("ResultCards sectioned report", () => {
  const sectionedResult: ResearchResult = {
    task_id: "task_20260624_000009_dddddd",
    mode: "web",
    question: "sectioned question",
    status: "completed",
    curator_output: {
      title: "Sectioned",
      summary: "Lead-in paragraph.",
      sections: [
        { heading: "Overview", text: "RAG retrieves then generates." },
        { heading: "Indexing", text: "Chunking quality drives recall." }
      ],
      findings: [{ finding_id: "f_1", subtask_id: "st_1", text: "Finding", source_ids: ["src_1"] }],
      sources: [{ source_id: "src_1", title: "Source", url: "https://example.com", fetched_at: "now" }]
    }
  };

  it("renders report chapters when sections exist (R-277)", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, text: async () => JSON.stringify({ messages: [] }) }))
    );
    render(<ResultCards result={sectionedResult} events={[]} />);
    expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByText("RAG retrieves then generates.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Indexing" })).toBeInTheDocument();
    expect(screen.getByText("Chunking quality drives recall.")).toBeInTheDocument();
  });

  it("renders rich Markdown section bodies NotebookLM-style (R-279)", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, text: async () => JSON.stringify({ messages: [] }) }))
    );
    const rich: ResearchResult = {
      ...sectionedResult,
      curator_output: {
        ...sectionedResult.curator_output!,
        sections: [
          {
            heading: "Mechanisms",
            text: "The **Agent Card** is discovered at well-known URLs.\n\n- task model\n- JSON-RPC 2.0 transport\n\nUses `artifact` identifiers [f_st_1] and [src_st_1].",
          },
        ],
      },
    };
    render(<ResultCards result={rich} events={[]} />);

    // Paragraphs split on blank lines; bold renders as emphasis (text nodes
    // around the <strong>), not literal asterisks.
    expect(screen.getByText("Agent Card")).toBeInTheDocument();
    expect(screen.getByText(/discovered at well-known URLs/)).toBeInTheDocument();
    // Inline code + citation chips.
    expect(screen.getByText("artifact")).toBeInTheDocument();
    expect(screen.getByText("f_st_1")).toBeInTheDocument();
    expect(screen.getByText("src_st_1")).toBeInTheDocument();
    // The list assertions are scoped to the rich body (Findings also renders a ul).
    const richBody = document.querySelector(".report-rich") as HTMLElement;
    const items = within(richBody).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toBe("task model");
  });

  it("keeps the legacy summary+findings shape when sections are absent", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, text: async () => JSON.stringify({ messages: [] }) }))
    );
    const legacy = { ...webResult }; // webResult has no sections
    render(<ResultCards result={legacy} events={[]} />);
    expect(screen.getByText("Web summary")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Overview" })).not.toBeInTheDocument();
  });
});
