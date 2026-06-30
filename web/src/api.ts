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
  _seq?: number;
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const error = data.error ?? { code: "runtime_error", message: "Request failed." };
    throw new Error(`[${error.code}] ${error.message}`);
  }
  return data as T;
}

export const api = {
  setupStatus: () => request<SetupStatus>("/api/setup/status"),
  setupInit: (payload: SetupPayload) =>
    request<SetupStatus>("/api/setup/init", { method: "POST", body: JSON.stringify(payload) }),
  runLocal: (question: string) =>
    request<ResearchResult>("/api/research/local", { method: "POST", body: JSON.stringify({ question }) }),
  runWeb: (question: string) =>
    request<ResearchResult>("/api/research/web", { method: "POST", body: JSON.stringify({ question }) }),
  finishedTasks: () => request<{ tasks: TaskSummary[] }>("/api/tasks/finished"),
  taskResult: (taskId: string) => request<ResearchResult>(`/api/tasks/${taskId}/result`),
  taskEvents: async (taskId: string) => parseSseEvents(await requestText(`/api/tasks/${taskId}/events`)),
  kbStatus: () => request<KbStatus>("/api/kb/status"),
  kbRebuild: () => request<KbStatus>("/api/kb/rebuild", { method: "POST" })
};

async function requestText(path: string): Promise<string> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error("Request failed.");
  }
  return response.text();
}

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

export function subscribeTaskEvents(
  taskId: string,
  onEvent: (event: ProgressEvent) => void,
  onResult: (event: ProgressEvent) => void,
  onError: () => void
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
