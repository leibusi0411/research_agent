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
export function subscribeTaskEvents(
  taskId: string,
  onEvent: (event: ProgressEvent) => void,
  onError: () => void,
  onResult: (event: ProgressEvent) => void,
): () => void {
  let eventSource: EventSource;
  try {
    eventSource = new EventSource(`/api/tasks/${taskId}/events`);
  } catch {
    // EventSource constructor may throw (e.g. network unavailable).
    // Treat as permanent error — no reconnection possible.
    onError();
    return () => {};
  }

  eventSource.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data) as ProgressEvent;
      // S2: task_result event signals task completion — fetch result once, stop stream.
      if (event.event_type === "task_result") {
        eventSource.close();
        onResult(event);
        return;
      }
      if (event.event_type === "stream_timeout") {
        eventSource.close();
        onError();
        return;
      }
      onEvent(event);
    } catch {
      // Skip unparseable events
    }
  };

  eventSource.onerror = () => {
    // R-72: Distinguish transient from permanent errors.
    // EventSource.CONNECTING (0) means the browser will auto-retry — do NOT close.
    // EventSource.CLOSED (2) means the connection is permanently dead.
    if (eventSource.readyState === EventSource.CLOSED) {
      eventSource.close();
      onError();
    }
    // Otherwise (CONNECTING), the browser will auto-reconnect; let it retry.
  };

  return () => eventSource.close();
}
