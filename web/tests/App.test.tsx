import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { App } from "../src/App";
import { ResearchResult } from "../src/api";

const localResult: ResearchResult = {
  task_id: "task_20260624_000000_aaaaaa",
  mode: "local",
  question: "local question",
  status: "completed",
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
});

describe("App", () => {
  it("shows setup view when config is missing and creates config", async () => {
    mockFetch([
      { configured: false },
      { configured: true, config_path: "C:/config.toml" },
      { tasks: [] },
      { status: "missing", vault_path: "D:/vault", file_count: 0, chunk_count: 0, last_indexed_at: null }
    ]);

    render(<MemoryRouter><App /></MemoryRouter>);

    expect(await screen.findByText("Research Agent Setup")).toBeInTheDocument();
    for (const input of screen.getAllByRole("textbox")) {
      await userEvent.type(input, "x");
    }
    for (const input of document.querySelectorAll("input[type='password']")) {
      await userEvent.type(input, "x");
    }
    await userEvent.click(screen.getByRole("button", { name: "Save Config" }));

    expect(await screen.findByRole("heading", { name: "Research" })).toBeInTheDocument();
  });

  it("runs local and web research and renders results", async () => {
    mockConfiguredFetch();
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Research" });
    await userEvent.type(screen.getAllByRole("textbox")[0], "local question");
    await userEvent.click(screen.getByRole("button", { name: "Run Local" }));
    await waitFor(() => expect(screen.getByText("Local content")).toBeInTheDocument());
    expect(screen.getByText("local_rag")).toBeInTheDocument();

    await userEvent.type(screen.getAllByRole("textbox")[1], "web question");
    await userEvent.click(screen.getByRole("button", { name: "Run Web" }));
    await waitFor(() => expect(screen.getByText("Web summary")).toBeInTheDocument());
    expect(screen.getByText("web_planning")).toBeInTheDocument();
  });

  it("lists tasks and opens the mode-specific result view", async () => {
    mockConfiguredFetch();
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Research" });
    await userEvent.click(screen.getByRole("link", { name: "Tasks" }));
    await userEvent.click(await screen.findByText("web question"));

    expect(await screen.findByText("Web Report")).toBeInTheDocument();
    expect(screen.getByText("Web summary")).toBeInTheDocument();

    await userEvent.click(screen.getByText("local question"));
    expect(await screen.findByText("Local Result")).toBeInTheDocument();
    expect(screen.getByText("local_rag")).toBeInTheDocument();
  });

  it("shows knowledge base status and rebuild action", async () => {
    mockConfiguredFetch();
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Research" });
    await userEvent.click(screen.getByRole("link", { name: "Knowledge Base" }));

    expect(await screen.findByText("Knowledge Base Index")).toBeInTheDocument();
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rebuild" })).toBeInTheDocument();
  });

  it("closes previous EventSource when starting a new task (P2 fix)", async () => {
    mockConfiguredFetch();
    render(<MemoryRouter><App /></MemoryRouter>);

    await screen.findByRole("heading", { name: "Research" });

    // Start local research — creates one EventSource
    await userEvent.type(screen.getAllByRole("textbox")[0], "local q1");
    await userEvent.click(screen.getByRole("button", { name: "Run Local" }));
    await waitFor(() => expect(screen.getByText("Local content")).toBeInTheDocument());

    const firstEsCount = _esInstances.length;
    expect(firstEsCount).toBeGreaterThanOrEqual(1);

    // Start another local research — should close the previous EventSource
    await userEvent.type(screen.getAllByRole("textbox")[0], "local q2");
    await userEvent.click(screen.getByRole("button", { name: "Run Local" }));
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

    await screen.findByRole("heading", { name: "Research" });
    await userEvent.type(screen.getAllByRole("textbox")[1], "web question");
    await userEvent.click(screen.getByRole("button", { name: "Run Web" }));

    expect(await screen.findByText(/file_write_error/)).toBeInTheDocument();
    expect(screen.getByText(/Failed to write Web Report File/)).toBeInTheDocument();
  });
});

function mockConfiguredFetch(options: { webResultOverride?: ResearchResult } = {}) {
  const resolvedWebResult = options.webResultOverride ?? webResult;
  const webStatus: "completed" | "failed" = resolvedWebResult.status === "failed" ? "failed" : "completed";

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
      } else if (url.endsWith("/api/tasks/finished")) {
        body = {
          tasks: [
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
          ]
        };
      } else if (url.endsWith("/api/kb/status") || url.endsWith("/api/kb/rebuild")) {
        body = { status: "ready", vault_path: "D:/vault", file_count: 2, chunk_count: 4, last_indexed_at: "now" };
      } else if (url.endsWith("/api/research/local") && init?.method === "POST") {
        body = { ...localResult, status: "running" };
      } else if (url.endsWith("/api/research/web") && init?.method === "POST") {
        body = { ...resolvedWebResult, status: "running" };
      } else if (url.endsWith(`/api/tasks/${localResult.task_id}/events`)) {
        body = localEvents;
      } else if (url.endsWith(`/api/tasks/${webResult.task_id}/events`)) {
        body = webEvents;
      } else if (url.endsWith(`/api/tasks/${webResult.task_id}/result`)) {
        body = resolvedWebResult;
      } else if (url.endsWith(`/api/tasks/${localResult.task_id}/result`)) {
        body = localResult;
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
