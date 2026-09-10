export type SetupStatus = {
  configured: boolean;
  config_path?: string;
  workspace?: string;
};

export type SetupPayload = {
  default_workspace: string;
  knowledge_base_path: string;
  chat_base_url: string;
  chat_api_key: string;
  chat_model: string;
  embedding_base_url: string;
  embedding_api_key: string;
  embedding_model: string;
  search_api_key: string;
};

// GET /api/setup/config — current settings with key values withheld;
// has_* flags tell the settings UI whether a key is already saved.
export type SetupConfig = Omit<SetupPayload, "chat_api_key" | "embedding_api_key" | "search_api_key"> & {
  has_chat_api_key: boolean;
  has_embedding_api_key: boolean;
  has_search_api_key: boolean;
};

export type TaskSummary = {
  task_id: string;
  mode: "local" | "web";
  status: "completed" | "failed";
  title_or_question: string;
  created_at: string;
};

export type LocalResult = {
  text: string;
  source_path: string;
  heading_path?: string[];
};

export type Source = {
  source_id: string;
  title: string;
  url: string;
  fetched_at: string;
};

export type Finding = {
  finding_id: string;
  subtask_id: string;
  text: string;
  source_ids: string[];
};

export type ResearchResult = {
  task_id: string;
  mode: "local" | "web";
  question: string;
  status: "running" | "completed" | "failed";
  summary?: string;
  local_results?: LocalResult[];
  curator_output?: {
    title: string;
    summary: string;
    findings: Finding[];
    sources: Source[];
  };
  report_path?: string;
  error?: { code: string; message: string };
};

export type ProgressEvent = {
  task_id: string;
  mode: "local" | "web";
  phase: string;
  event_type: string;
  message: string;
  created_at: string;
  details: { items: Array<Record<string, unknown>> };
  seq?: number;
  event_subtype?: string | null;
};

export type KbStatus = {
  status: string;
  vault_path: string;
  file_count: number;
  chunk_count: number;
  last_indexed_at: string | null;
  error?: string;
};

export type DepositResult = {
  task_id: string;
  vault_path: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const err = data.error;
    if (typeof err === "string") {
      throw new Error(err);
    }
    const code = err?.code ?? "runtime_error";
    const message = err?.message ?? "Request failed.";
    throw new ApiError(code, message);
  }
  return data as T;
}

// Carries the backend ResearchError code so callers can branch on it
// (e.g. already_deposited) without parsing the message string.
export class ApiError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(`[${code}] ${message}`);
    this.code = code;
  }
}

export const api = {
  setupStatus: () => request<SetupStatus>("/api/setup/status"),
  setupConfig: () => request<SetupConfig>("/api/setup/config"),
  setupInit: (payload: SetupPayload) =>
    request<SetupStatus>("/api/setup/init", { method: "POST", body: JSON.stringify(payload) }),
  runWeb: (question: string) =>
    request<ResearchResult>("/api/research/web", { method: "POST", body: JSON.stringify({ question }) }),
  runLocal: (question: string) =>
    request<ResearchResult>("/api/research/local", { method: "POST", body: JSON.stringify({ question }) }),
  finishedTasks: () => request<{ tasks: TaskSummary[] }>("/api/tasks/finished"),
  deleteTask: (taskId: string) => request<{ task_id: string; deleted: boolean }>(`/api/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" }),
  depositTask: (taskId: string) => request<DepositResult>(`/api/tasks/${encodeURIComponent(taskId)}/deposit`, { method: "POST" }),
  taskResult: (taskId: string) => request<ResearchResult>(`/api/tasks/${encodeURIComponent(taskId)}/result`),
  taskEvents: (taskId: string) => request<ProgressEvent[]>(`/api/tasks/${encodeURIComponent(taskId)}/events`),
  activeTasks: () => request<{ active: Array<{ mode: string; task_id: string }> }>("/api/tasks/active"),
  kbStatus: () => request<KbStatus>("/api/kb/status"),
  kbRebuild: () => request<KbStatus>("/api/kb/rebuild", { method: "POST" })
};

export function parseSseEvents(text: string): ProgressEvent[] {
  const events: ProgressEvent[] = [];
  const blocks = text.split("\n\n");
  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed) continue;
    const line = trimmed.replace(/^data:\s*/, "");
    try {
      events.push(JSON.parse(line) as ProgressEvent);
    } catch {
      // R-73: Skip unparseable lines instead of discarding all events.
      // A malformed line should not invalidate the entire stream.
      console.warn("Failed to parse SSE event line:", line.slice(0, 120));
    }
  }
  return events;
}

// R-101: onError before onResult is a more natural parameter order
// (error handler typically precedes success/result handler).
//
// Stall watchdog: a live SSE connection can silently stop delivering frames
// (proxy hiccup, dead generator) while the backend keeps writing events.
// When no frame arrives within SSE_STALL_TIMEOUT_MS the stream is closed and
// reconnected; the server replays the full history on reconnect and the seq
// dedup below keeps the trace free of duplicates. Events without a seq (only
// the initial "Task started." frame) are accepted until the first sequenced
// frame arrives, and treated as replay artifacts afterwards.
const SSE_STALL_TIMEOUT_MS = 45_000;

export function subscribeTaskEvents(
  taskId: string,
  onEvent: (event: ProgressEvent) => void,
  onError: () => void,
  onResult: (event: ProgressEvent) => void,
): () => void {
  let eventSource: EventSource | null = null;
  let disposed = false;
  let stallTimer: number | null = null;
  let lastSeq = -1;
  let sawSequencedEvent = false;

  const clearStallTimer = () => {
    if (stallTimer !== null) {
      window.clearTimeout(stallTimer);
      stallTimer = null;
    }
  };

  const dispose = () => {
    disposed = true;
    clearStallTimer();
    eventSource?.close();
    eventSource = null;
  };

  const armStallTimer = () => {
    clearStallTimer();
    if (disposed) return;
    stallTimer = window.setTimeout(() => {
      if (disposed) return;
      // Force a reconnect: the route re-runs and the fresh stream replays any
      // events the stalled connection missed.
      eventSource?.close();
      connect();
    }, SSE_STALL_TIMEOUT_MS);
  };

  const handleEvent = (event: ProgressEvent) => {
    // Any frame at all proves the link is alive — feed the watchdog before
    // deduping so a long replay cannot starve it into a reconnect loop.
    armStallTimer();
    if (typeof event.seq === "number") {
      if (sawSequencedEvent && event.seq <= lastSeq) return;
      lastSeq = Math.max(lastSeq, event.seq);
      sawSequencedEvent = true;
    } else if (sawSequencedEvent) {
      // No-seq frames only exist at the very start of the history; seeing one
      // after sequenced events means the stream replayed from the beginning.
      return;
    }
    onEvent(event);
  };

  const connect = () => {
    if (disposed) return;
    try {
      eventSource = new EventSource(`/api/tasks/${taskId}/events`);
    } catch {
      // EventSource constructor may throw (e.g. network unavailable).
      // Treat as permanent error — no reconnection possible.
      dispose();
      onError();
      return;
    }
    eventSource.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data) as ProgressEvent;
        // S2: task_result event signals task completion — fetch result once, stop stream.
        if (event.event_type === "task_result") {
          dispose();
          onResult(event);
          return;
        }
        if (event.event_type === "stream_timeout") {
          dispose();
          onError();
          return;
        }
        handleEvent(event);
      } catch {
        // Skip unparseable events
      }
    };
    eventSource.onerror = () => {
      // R-72: Distinguish transient from permanent errors.
      // EventSource.CONNECTING (0) means the browser will auto-retry — do NOT close.
      // EventSource.CLOSED (2) means the connection is permanently dead.
      if (eventSource && eventSource.readyState === EventSource.CLOSED) {
        dispose();
        onError();
        return;
      }
      // Otherwise (CONNECTING), the browser will auto-reconnect; let it retry.
      armStallTimer();
    };
    armStallTimer();
  };

  connect();
  return dispose;
}
