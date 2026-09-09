import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { App } from "../src/App";
import { PhaseIndicator } from "../src/components/PhaseIndicator";
import { ResearchResult } from "../src/api";

const localResult: ResearchResult = {
  task_id: "task_20260624_000000_aaaaaa",
  mode: "local",
  question: "local question",
  status: "completed",
  summary: "Local summary from retrieved chunks",
  local_results: [{ text: "Local content", source_path: "D:/vault/note.md", heading_path: ["API"] }]
};

const webResult: ResearchResult = {
  task_id: "task_20260624_000001_bbbbbb",
  mode: "web",
  question: "web question",
  status: "completed",
  curator_output: {
    title: "Web",
    summary: "Web summary",
    findings: [{ finding_id: "f_1", subtask_id: "st_1", text: "Finding", source_ids: ["src_1"] }],
    sources: [{ source_id: "src_1", title: "Source", url: "https://example.com", fetched_at: "now" }]
  },
  report_path: "D:/reports/web/report.md"
};

const webResult2: ResearchResult = {
  task_id: "task_20260624_000002_cccccc",
  mode: "web",
  question: "second web question",
  status: "completed",
  curator_output: {
    title: "Web2",
    summary: "Second summary",
    findings: [{ finding_id: "f_2", subtask_id: "st_1", text: "Finding 2", source_ids: ["src_2"] }],
    sources: [{ source_id: "src_2", title: "Source 2", url: "https://example.com/2", fetched_at: "now" }]
  },
  report_path: "D:/reports/web/report2.md"
};

const webEvents =
  'data: {"task_id":"task_20260624_000001_bbbbbb","mode":"web","phase":"web_planning","event_type":"completed","created_at":"now","message":"Initial plan created.","details":{"items":[]}}\n\n';
const localEvents =
  'data: {"task_id":"task_20260624_000000_aaaaaa","mode":"local","phase":"local_rag","event_type":"completed","created_at":"now","message":"Local RAG completed.","details":{"items":[]}}\n\n';

// Helper: parse SSE text into JSON event objects
function parseSseText(text: string): Record<string, unknown>[] {
  return text
    .split("\n\n")
    .filter((b) => b.trim())
    .map((b) => JSON.parse(b.trim().replace(/^data:\s*/, "")));
}

// Stub EventSource: emits events based on the task_id in the URL.
// The events map is populated by mockConfiguredFetch.
let _sseEventMap: Record<string, Record<string, unknown>[]> = {};
// Collect all EventSource instances so tests can inspect close() calls.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let _esInstances: any[] = [];

function stubEventSource() {
  _esInstances = [];
  const MockES = vi.fn(function (this: { readyState: number; close: () => void; onmessage: ((msg: { data: string }) => void) | null; onerror: (() => void) | null }, url: string) {
    this.readyState = 1; // OPEN
    this.close = vi.fn();
    this.onmessage = null;
    this.onerror = null;
    _esInstances.push(this);
    // Find which task's events to emit
    const events = Object.entries(_sseEventMap).find(([tid]) => url.includes(tid))?.[1] ?? [];
    queueMicrotask(() => {
      if (this.onmessage) {
        for (const evt of events) {
          this.onmessage({ data: JSON.stringify(evt) });
        }
      }
    });
  });
  (MockES as unknown as Record<string, unknown>).CONNECTING = 0;
  (MockES as unknown as Record<string, unknown>).CLOSED = 2;
  (MockES as unknown as Record<string, unknown>).OPEN = 1;
  vi.stubGlobal("EventSource", MockES as unknown as typeof EventSource);
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.stubGlobal("confirm", () => true);
});

describe("PhaseIndicator", () => {
  it("carries the running underline marker only while the task is running", () => {
    const { rerender } = render(<PhaseIndicator currentPhase="web_planning" mode="web" running={true} />);
    expect(screen.getByText("planning")).toHaveClass("active", "running");

    rerender(<PhaseIndicator currentPhase="web_curation" mode="web" running={false} />);
    expect(screen.getByText("curation")).toHaveClass("active");
    expect(screen.getByText("curation")).not.toHaveClass("running");
    expect(screen.getByText("planning")).not.toHaveClass("running");
  });
});

describe("App", () => {
  it("lets unconfigured users use the Research page; submitting reports the config error", async () => {
    stubEventSource();
    _sseEventMap = {};
    function jsonResponse(body: unknown, ok = true, status = 200) {
      return { ok, status, text: async () => JSON.stringify(body) };
    }
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/setup/status")) return jsonResponse({ configured: false });
        if (url.endsWith("/api/research/web") && init?.method === "POST") {
          return jsonResponse(
            { error: { code: "config_missing", message: "User config is missing. Run research-agent init first." } },
            false,
            404
          );
        }
        return jsonResponse({});
      })
    );

    render(<MemoryRouter><App /></MemoryRouter>);

    // Research is the landing page even without config — the shell with all
    // four pages renders and the question input works normally.
    expect(await screen.findByRole("heading", { name: "Inkwell" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Research" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Knowledge Base" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
    const question = await screen.findByRole("textbox", { name: "Research question" });
    await userEvent.type(question, "my question");

    // Submitting without config reports the error instead of starting a task.
    await userEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(await screen.findByText(/config_missing/)).toBeInTheDocument();
  });

  it("prefills the Settings page from saved config and keeps saved keys blank", async () => {
    stubEventSource();
    _sseEventMap = {};
    function jsonResponse(body: unknown, ok = true, status = 200) {
      return { ok, status, text: async () => JSON.stringify(body) };
    }
    const initBodies: Record<string, unknown>[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/setup/status")) return jsonResponse({ configured: true });
        if (url.endsWith("/api/setup/config")) {
          return jsonResponse({
            default_workspace: "D:/runtime",
            knowledge_base_path: "D:/vault",
            chat_base_url: "https://models.example/v1",
            chat_model: "chat-model",
            embedding_base_url: "https://embeddings.example/v1",
            embedding_model: "embedding-model",
            chat_api_key: "",
            embedding_api_key: "",
            search_api_key: "",
            has_chat_api_key: true,
            has_embedding_api_key: true,
            has_search_api_key: true
          });
        }
        if (url.endsWith("/api/setup/init") && init?.method === "POST") {
          initBodies.push(JSON.parse(String(init.body)));
          return jsonResponse({ configured: true, config_path: "C:/config.toml" });
        }
        return jsonResponse({});
      })
    );

    render(<MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter>);

    // Non-secret fields are prefilled from the saved config.
    const chatUrl = await screen.findByRole("textbox", { name: "chat_base_url" });
    await waitFor(() => expect(chatUrl).toHaveValue("https://models.example/v1"));
    expect(screen.getByRole("textbox", { name: "chat_model" })).toHaveValue("chat-model");

    // Saved keys stay blank, are optional, and say so in the placeholder.
    const chatKey = document.querySelector("input[name='chat_api_key']") as HTMLInputElement;
    expect(chatKey).toHaveValue("");
    expect(chatKey).not.toBeRequired();
    expect(chatKey).toHaveAttribute("placeholder", "Saved — leave blank to keep");

    // Editing and saving stays on the Settings page with a confirmation,
    // submitting blank key fields so the backend keeps the saved keys.
    await userEvent.clear(chatUrl);
    await userEvent.type(chatUrl, "u");
    await userEvent.click(screen.getByRole("button", { name: "Save Config" }));

    expect(await screen.findByText("Settings saved.")).toBeInTheDocument();
    expect(initBodies[0]).toMatchObject({ chat_base_url: "u", chat_api_key: "" });
  });

  it("runs web research and renders the trace and result cards", async () => {
    mockConfiguredFetch();
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Inkwell" });
    await userEvent.type(screen.getByRole("textbox", { name: "Research question" }), "web question");
    await userEvent.click(screen.getByRole("button", { name: "Research" }));
    expect(await screen.findByText("web_planning")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Web summary")).toBeInTheDocument());
    expect(screen.getByText("web_planning")).toBeInTheDocument();
    // After completion the animated underline marker is gone.
    expect(screen.getByText("curation")).not.toHaveClass("running");
    expect(screen.getByRole("heading", { name: "Web Report" })).toBeInTheDocument();
  });

  it("shows the curation phase as active when the final task_result completes the run", async () => {
    mockConfiguredFetch();
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("textbox", { name: "Research question" });
    // The live stream stalls after supervision: the last onEvent is a
    // web_supervision frame, then the task_result (web_curation) arrives.
    _sseEventMap[webResult.task_id] = [
      { task_id: webResult.task_id, mode: "web", phase: "web_supervision", event_type: "completed", created_at: "now", message: "All subtasks completed.", details: { items: [] } },
      { task_id: webResult.task_id, mode: "web", phase: "web_curation", event_type: "task_result", created_at: "now", message: "Task completed.", details: { items: [{ kind: "status", task_id: webResult.task_id, status: "completed", mode: "web" }] } },
    ];

    await userEvent.type(screen.getByRole("textbox", { name: "Research question" }), "web question");
    await userEvent.click(screen.getByRole("button", { name: "Research" }));

    await waitFor(() => expect(screen.getByText("Web summary")).toBeInTheDocument());
    expect(screen.getByText("curation")).toHaveClass("active");
    expect(screen.getByText("curation")).not.toHaveClass("running");
    expect(screen.getByText("supervision")).not.toHaveClass("active");
  });

  it("lists tasks and opens the mode-specific result view", async () => {
    mockConfiguredFetch();
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Inkwell" });
    await userEvent.click(screen.getByRole("link", { name: "Tasks" }));
    await userEvent.click(await screen.findByText("web question"));

    expect(await screen.findByText("Web Report")).toBeInTheDocument();
    expect(screen.getByText("Web summary")).toBeInTheDocument();

    await userEvent.click(screen.getByText("local question"));
    expect(await screen.findByText("Local Result")).toBeInTheDocument();
    expect(screen.getByText("local_rag")).toBeInTheDocument();
    expect(screen.getByText("Local summary from retrieved chunks")).toBeInTheDocument();
  });

  it("reattaches to a running web task on load", async () => {
    mockConfiguredFetch({ activeWeb: true });
    render(<MemoryRouter><App /></MemoryRouter>);

    // No click: the running task's trace appears, then its result arrives.
    expect(await screen.findByText("Research Trace")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Web summary")).toBeInTheDocument());
    expect(screen.getByRole("textbox", { name: "Research question" })).toHaveValue("web question");
  });

  it("deletes a finished task from task history and clears selected details", async () => {
    mockConfiguredFetch();
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Inkwell" });
    await userEvent.click(screen.getByRole("link", { name: "Tasks" }));
    await userEvent.click(await screen.findByText("web question"));
    expect(await screen.findByText("Web Report")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Delete task web question" }));

    await waitFor(() => expect(screen.queryByText("web question")).not.toBeInTheDocument());
    expect(screen.queryByText("Web Report")).not.toBeInTheDocument();
    expect(screen.getByText("local question")).toBeInTheDocument();
  });

  it("deposits a finished web report into the knowledge base and rebuilds the index", async () => {
    mockConfiguredFetch();
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Inkwell" });
    await userEvent.click(screen.getByRole("link", { name: "Tasks" }));
    await userEvent.click(await screen.findByText("web question"));
    expect(await screen.findByText("Web Report")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Deposit to Knowledge Base" }));

    expect(await screen.findByText("Deposited to Knowledge Base.")).toBeInTheDocument();
    expect(screen.getByText("D:/vault/web-research/report.md")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Rebuild Index" }));

    expect(await screen.findByText(/Index rebuilt/)).toBeInTheDocument();

    // Local results have no deposit affordance.
    await userEvent.click(screen.getByText("local question"));
    expect(await screen.findByText("Local Result")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deposit to Knowledge Base" })).not.toBeInTheDocument();
  });

  it("shows already-deposited state when the task was deposited before", async () => {
    mockConfiguredFetch({ depositStatus: 409 });
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Inkwell" });
    await userEvent.click(screen.getByRole("link", { name: "Tasks" }));
    await userEvent.click(await screen.findByText("web question"));
    expect(await screen.findByText("Web Report")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Deposit to Knowledge Base" }));

    expect(await screen.findByText("Already deposited to Knowledge Base.")).toBeInTheDocument();
  });

  it("resets the deposit panel when switching between two web tasks", async () => {
    mockConfiguredFetch({ secondWebTask: true });
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Inkwell" });
    await userEvent.click(screen.getByRole("link", { name: "Tasks" }));
    await userEvent.click(await screen.findByText("web question"));
    expect(await screen.findByText("Web summary")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Deposit to Knowledge Base" }));
    expect(await screen.findByText("Deposited to Knowledge Base.")).toBeInTheDocument();

    await userEvent.click(screen.getByText("second web question"));

    expect(await screen.findByText("Second summary")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deposit to Knowledge Base" })).toBeInTheDocument();
    expect(screen.queryByText("Deposited to Knowledge Base.")).not.toBeInTheDocument();
  });

  it("shows knowledge base status and rebuild action", async () => {
    mockConfiguredFetch();
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Inkwell" });
    await userEvent.click(screen.getByRole("link", { name: "Knowledge Base" }));

    expect(await screen.findByText("Knowledge Base Index")).toBeInTheDocument();
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rebuild" })).toBeInTheDocument();
  });

  it("shows error banner when delete task fails with 409 busy", async () => {
    // Override mockConfiguredFetch to make DELETE return 409 for web task
    stubEventSource();
    const finishedTasks = [
      { task_id: webResult.task_id, mode: "web", status: "completed", title_or_question: "web question", created_at: "2026-06-24T00:00:01Z" },
      { task_id: localResult.task_id, mode: "local", status: "completed", title_or_question: "local question", created_at: "2026-06-24T00:00:00Z" },
    ];
    _sseEventMap = {};
    function jsonResponse(body: unknown, ok = true, status = 200) {
      return { ok, status, text: async () => JSON.stringify(body) };
    }
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/setup/status")) return jsonResponse({ configured: true });
        if (url.endsWith("/api/tasks/finished")) return jsonResponse({ tasks: finishedTasks });
        if (url.endsWith("/api/kb/status")) return jsonResponse({ status: "ready", vault_path: "D:/vault", file_count: 2, chunk_count: 4, last_indexed_at: "now" });
        if (url.endsWith(`/api/tasks/${webResult.task_id}`) && init?.method === "DELETE") {
          return jsonResponse({ error: { code: "busy", message: "Task is still running" } }, false, 409);
        }
        return jsonResponse({});
      })
    );

    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Inkwell" });
    await userEvent.click(screen.getByRole("link", { name: "Tasks" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete task web question" }));

    expect(await screen.findByText(/busy/)).toBeInTheDocument();
    // Task row should still be present (delete failed)
    expect(screen.getByText("web question")).toBeInTheDocument();
  });

  it("closes previous EventSource when starting a new task (P2 fix)", async () => {
    mockConfiguredFetch();
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Inkwell" });

    // Start a research run — creates one EventSource
    await userEvent.type(screen.getByRole("textbox", { name: "Research question" }), "q1");
    await userEvent.click(screen.getByRole("button", { name: "Research" }));
    await waitFor(() => expect(screen.getByText("Web summary")).toBeInTheDocument());

    const firstEsCount = _esInstances.length;
    expect(firstEsCount).toBeGreaterThanOrEqual(1);

    // Start another research run — should close the previous EventSource
    await userEvent.clear(screen.getByRole("textbox", { name: "Research question" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Research question" }), "q2");
    await userEvent.click(screen.getByRole("button", { name: "Research" }));
    await waitFor(() => expect(_esInstances.length).toBeGreaterThan(firstEsCount));

    // First EventSource should have been closed
    expect(_esInstances[0].close).toHaveBeenCalled();
  });

  it("renders web report write failures as failed with file_write_error", async () => {
    mockConfiguredFetch({
      webResultOverride: {
        ...webResult,
        status: "failed",
        curator_output: undefined,
        report_path: undefined,
        error: { code: "file_write_error", message: "Failed to write Web Report File." }
      }
    });
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Inkwell" });
    await userEvent.type(screen.getByRole("textbox", { name: "Research question" }), "web question");
    await userEvent.click(screen.getByRole("button", { name: "Research" }));

    expect(await screen.findByText(/file_write_error/)).toBeInTheDocument();
    expect(screen.getByText(/Failed to write Web Report File/)).toBeInTheDocument();
  });
});

function mockConfiguredFetch(options: { webResultOverride?: ResearchResult; depositStatus?: number; secondWebTask?: boolean; activeWeb?: boolean } = {}) {
  const resolvedWebResult = options.webResultOverride ?? webResult;
  const webStatus: "completed" | "failed" = resolvedWebResult.status === "failed" ? "failed" : "completed";
  let finishedTasks = [
    {
      task_id: webResult.task_id,
      mode: "web",
      status: "completed",
      title_or_question: "web question",
      created_at: "2026-06-24T00:00:01Z"
    },
    {
      task_id: localResult.task_id,
      mode: "local",
      status: "completed",
      title_or_question: "local question",
      created_at: "2026-06-24T00:00:00Z"
    }
  ];
  if (options.secondWebTask) {
    finishedTasks = [
      {
        task_id: webResult2.task_id,
        mode: "web",
        status: "completed",
        title_or_question: "second web question",
        created_at: "2026-06-24T00:00:02Z"
      },
      ...finishedTasks
    ];
  }

  // Build SSE event map for EventSource mock
  _sseEventMap = {};
  _sseEventMap[localResult.task_id] = [
    ...parseSseText(localEvents),
    {
      task_id: localResult.task_id,
      mode: "local",
      phase: "local_rag",
      event_type: "task_result",
      created_at: "now",
      message: "Task completed.",
      details: { items: [{ kind: "status", task_id: localResult.task_id, status: "completed", mode: "local" }] },
    },
  ];
  _sseEventMap[webResult.task_id] = [
    ...parseSseText(webEvents),
    {
      task_id: webResult.task_id,
      mode: "web",
      phase: "web_curation",
      event_type: "task_result",
      created_at: "now",
      message: `Task ${webStatus}.`,
      details: { items: [{ kind: "status", task_id: webResult.task_id, status: webStatus, mode: "web" }] },
    },
  ];
  stubEventSource();

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      let body: unknown = {};
      if (url.endsWith("/api/setup/status")) {
        body = { configured: true };
      } else if (url.endsWith("/api/tasks/active")) {
        body = { active: options.activeWeb ? [{ mode: "web", task_id: resolvedWebResult.task_id }] : [] };
      } else if (url.endsWith("/api/tasks/finished")) {
        body = {
          tasks: finishedTasks
        };
      } else if (url.endsWith("/api/kb/status") || url.endsWith("/api/kb/rebuild")) {
        body = { status: "ready", vault_path: "D:/vault", file_count: 2, chunk_count: 4, last_indexed_at: "now" };
      } else if (url.endsWith("/api/research/local") && init?.method === "POST") {
        body = { ...localResult, status: "running" };
      } else if (url.endsWith("/api/research/web") && init?.method === "POST") {
        body = { ...resolvedWebResult, status: "running" };
      } else if (url.endsWith(`/api/tasks/${localResult.task_id}/events`)) {
        body = _sseEventMap[localResult.task_id] ?? [];
      } else if (url.endsWith(`/api/tasks/${webResult.task_id}/events`)) {
        body = _sseEventMap[webResult.task_id] ?? [];
      } else if (url.endsWith(`/api/tasks/${webResult.task_id}/result`)) {
        body = resolvedWebResult;
      } else if (url.endsWith(`/api/tasks/${webResult2.task_id}/result`)) {
        body = webResult2;
      } else if (url.endsWith(`/api/tasks/${webResult2.task_id}/events`)) {
        body = [
          {
            task_id: webResult2.task_id,
            mode: "web",
            phase: "web_curation",
            event_type: "completed",
            created_at: "now",
            message: "Task completed.",
            details: { items: [] },
          },
        ];
      } else if (url.endsWith(`/api/tasks/${webResult2.task_id}/deposit`) && init?.method === "POST") {
        body = { task_id: webResult2.task_id, vault_path: "D:/vault/web-research/report2.md" };
      } else if (url.endsWith(`/api/tasks/${localResult.task_id}/result`)) {
        body = localResult;
      } else if (url.endsWith(`/api/tasks/${webResult.task_id}/deposit`) && init?.method === "POST") {
        if (options.depositStatus === 409) {
          return {
            ok: false,
            status: 409,
            text: async () => JSON.stringify({ error: { code: "already_deposited", message: "This task's report is already deposited in the Knowledge Base." } })
          };
        }
        body = { task_id: webResult.task_id, vault_path: "D:/vault/web-research/report.md" };
      } else if (url.endsWith(`/api/tasks/${webResult.task_id}`) && init?.method === "DELETE") {
        finishedTasks = finishedTasks.filter((task) => task.task_id !== webResult.task_id);
        body = { task_id: webResult.task_id, deleted: true };
      } else if (url.endsWith(`/api/tasks/${localResult.task_id}`) && init?.method === "DELETE") {
        finishedTasks = finishedTasks.filter((task) => task.task_id !== localResult.task_id);
        body = { task_id: localResult.task_id, deleted: true };
      }
      return {
        ok: true,
        status: 200,
        text: async () => (typeof body === "string" ? body : JSON.stringify(body))
      };
    })
  );
}

function mockFetch(responses: unknown[]) {
  const queue = [...responses];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      const body = queue.shift() ?? {};
      return {
        ok: true,
        status: 200,
        text: async () => (typeof body === "string" ? body : JSON.stringify(body))
      };
    })
  );
}
