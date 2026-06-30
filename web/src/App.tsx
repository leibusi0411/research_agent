import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, Database, FileText, Link, RefreshCw, Search, Settings, Wifi, Wrench } from "lucide-react";
import { api, KbStatus, ProgressEvent, ResearchResult, SetupPayload, subscribeTaskEvents, TaskSummary } from "./api";

type Page = "research" | "tasks" | "kb";

const emptySetup: SetupPayload = {
  default_workspace: "",
  knowledge_base_path: "",
  chat_base_url: "",
  chat_api_key: "",
  chat_model: "",
  embedding_base_url: "",
  embedding_api_key: "",
  embedding_model: "",
  search_api_key: ""
};

export function App() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [page, setPage] = useState<Page>("research");
  const [setup, setSetup] = useState<SetupPayload>(emptySetup);
  const [localQuestion, setLocalQuestion] = useState("");
  const [webQuestion, setWebQuestion] = useState("");
  const [localResult, setLocalResult] = useState<ResearchResult | null>(null);
  const [webResult, setWebResult] = useState<ResearchResult | null>(null);
  const [localEvents, setLocalEvents] = useState<ProgressEvent[]>([]);
  const [webEvents, setWebEvents] = useState<ProgressEvent[]>([]);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [kbStatus, setKbStatus] = useState<KbStatus | null>(null);
  const [selectedResult, setSelectedResult] = useState<ResearchResult | null>(null);
  const [selectedEvents, setSelectedEvents] = useState<ProgressEvent[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api
      .setupStatus()
      .then((status) => setConfigured(status.configured))
      .catch(() => setConfigured(false));
  }, []);

  useEffect(() => {
    if (configured) {
      refreshTasks();
      refreshKb();
    }
  }, [configured]);

  async function submitSetup(event: FormEvent) {
    event.preventDefault();
    setBusy("setup");
    try {
      await api.setupInit(setup);
      setConfigured(true);
      setMessage("");
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(null);
    }
  }

  async function runLocal(event: FormEvent) {
    event.preventDefault();
    setLocalEvents([]);
    setBusy("local");
    try {
      const started = await api.runLocal(localQuestion);
      if (started.status !== "running") {
        setLocalResult(started);
        setSelectedResult(started);
        await refreshTasks();
        return;
      }
      const collected: ProgressEvent[] = [];
      const unsubscribe = subscribeTaskEvents(
        started.task_id,
        (evt) => {
          collected.push(evt);
          setLocalEvents([...collected]);
        },
        async () => {
          // SSE stream ended — fetch final result immediately
          const finalResult = await api.taskResult(started.task_id);
          setLocalResult(finalResult);
          setSelectedResult(finalResult);
        }
      );
      // Fallback polling (SSE-matched timeout window; local RAG returns in seconds)
      const result = await waitForTerminalResult(started.task_id);
      unsubscribe();
      setLocalResult(result);
      setSelectedResult(result);
      await refreshTasks();
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(null);
    }
  }

  async function runWeb(event: FormEvent) {
    event.preventDefault();
    setWebEvents([]);
    setBusy("web");
    try {
      const started = await api.runWeb(webQuestion);
      if (started.status !== "running") {
        setWebResult(started);
        setSelectedResult(started);
        await refreshTasks();
        return;
      }
      const collected: ProgressEvent[] = [];
      const unsubscribe = subscribeTaskEvents(
        started.task_id,
        (evt) => {
          collected.push(evt);
          setWebEvents([...collected]);
        },
        async () => {
          // SSE stream ended — fetch final result immediately
          const finalResult = await api.taskResult(started.task_id);
          setWebResult(finalResult);
          setSelectedResult(finalResult);
        }
      );
      // Fallback polling (SSE-matched timeout window; web research may take 5-30 min)
      const result = await waitForTerminalResult(started.task_id);
      unsubscribe();
      setWebResult(result);
      setSelectedResult(result);
      await refreshTasks();
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(null);
    }
  }

  async function refreshTasks() {
    const response = await api.finishedTasks();
    setTasks(response.tasks);
  }

  async function refreshKb() {
    setKbStatus(await api.kbStatus());
  }

  async function rebuildKb() {
    setBusy("kb");
    try {
      setKbStatus(await api.kbRebuild());
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(null);
    }
  }

  async function openTask(task: TaskSummary) {
    const result = await api.taskResult(task.task_id);
    const events = await api.taskEvents(task.task_id);
    setSelectedResult(result);
    setSelectedEvents(events);
    setPage("tasks");
  }

  if (configured === null) {
    return <main className="boot">Loading</main>;
  }

  if (!configured) {
    return (
      <main className="setup-shell">
        <form className="setup-panel" onSubmit={submitSetup}>
          <div className="panel-title">
            <Settings size={22} />
            <h1>Research Agent Setup</h1>
          </div>
          <SetupFields setup={setup} setSetup={setSetup} />
          <button type="submit" disabled={busy === "setup"}>
            Save Config
          </button>
          {message && <p className="error">{message}</p>}
        </form>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">Research Agent</div>
        <button className={page === "research" ? "active" : ""} onClick={() => setPage("research")}>
          <Search size={18} />
          Research
        </button>
        <button className={page === "tasks" ? "active" : ""} onClick={() => setPage("tasks")}>
          <FileText size={18} />
          Tasks
        </button>
        <button className={page === "kb" ? "active" : ""} onClick={() => setPage("kb")}>
          <Database size={18} />
          Knowledge Base
        </button>
      </aside>
      <main className="workspace">
        {message && <div className="error banner">{message}</div>}
        {page === "research" && (
          <ResearchPage
            localQuestion={localQuestion}
            webQuestion={webQuestion}
            setLocalQuestion={setLocalQuestion}
            setWebQuestion={setWebQuestion}
            runLocal={runLocal}
            runWeb={runWeb}
            busy={busy}
            localResult={localResult}
            webResult={webResult}
            localEvents={localEvents}
            webEvents={webEvents}
          />
        )}
        {page === "tasks" && <TasksPage tasks={tasks} selectedResult={selectedResult} events={selectedEvents} onOpen={openTask} />}
        {page === "kb" && <KbPage status={kbStatus} busy={busy === "kb"} onRefresh={refreshKb} onRebuild={rebuildKb} />}
      </main>
    </div>
  );
}

async function waitForTerminalResult(taskId: string): Promise<ResearchResult> {
  // 720 attempts × 2.5s = 1800s (30 min), matching backend SSE stream timeout.
  // Local RAG tasks return in seconds; web research may take 5-30 min.
  for (let attempt = 0; attempt < 720; attempt += 1) {
    const result = await api.taskResult(taskId);
    if (result.status !== "running") {
      return result;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 2500));
  }
  return api.taskResult(taskId);
}

function SetupFields({ setup, setSetup }: { setup: SetupPayload; setSetup: (value: SetupPayload) => void }) {
  return (
    <div className="setup-grid">
      {Object.keys(setup).map((key) => (
        <label key={key}>
          <span>{key}</span>
          <input
            value={setup[key as keyof SetupPayload]}
            onChange={(event) => setSetup({ ...setup, [key]: event.target.value })}
            type={key.includes("api_key") ? "password" : "text"}
            required
          />
        </label>
      ))}
    </div>
  );
}

function ResearchPage(props: {
  localQuestion: string;
  webQuestion: string;
  setLocalQuestion: (value: string) => void;
  setWebQuestion: (value: string) => void;
  runLocal: (event: FormEvent) => void;
  runWeb: (event: FormEvent) => void;
  busy: string | null;
  localResult: ResearchResult | null;
  webResult: ResearchResult | null;
  localEvents: ProgressEvent[];
  webEvents: ProgressEvent[];
}) {
  return (
    <section>
      <h1>Research</h1>
      <div className="research-grid">
        <form className="tool-panel" onSubmit={props.runLocal}>
          <h2>
            <BookOpen size={18} />
            Local RAG
          </h2>
          <textarea value={props.localQuestion} onChange={(event) => props.setLocalQuestion(event.target.value)} required />
          <button disabled={props.busy === "local"}>Run Local</button>
        </form>
        <form className="tool-panel" onSubmit={props.runWeb}>
          <h2>
            <Wifi size={18} />
            Web Research
          </h2>
          <textarea value={props.webQuestion} onChange={(event) => props.setWebQuestion(event.target.value)} required />
          <button disabled={props.busy === "web"}>Run Web</button>
        </form>
      </div>
      <div className="result-grid">
        {props.localResult && <LocalResultView result={props.localResult} events={props.localEvents} />}
        {props.webResult && <WebResultView result={props.webResult} events={props.webEvents} />}
      </div>
    </section>
  );
}

function TasksPage({
  tasks,
  selectedResult,
  events,
  onOpen
}: {
  tasks: TaskSummary[];
  selectedResult: ResearchResult | null;
  events: ProgressEvent[];
  onOpen: (task: TaskSummary) => void;
}) {
  return (
    <section>
      <h1>Tasks</h1>
      <div className="table">
        {tasks.map((task) => (
          <button className="task-row" key={task.task_id} onClick={() => onOpen(task)}>
            <span>{task.task_id}</span>
            <span>{task.mode}</span>
            <span>{task.status}</span>
            <span>{task.title_or_question}</span>
            <span>{task.created_at}</span>
          </button>
        ))}
      </div>
      {selectedResult?.mode === "local" && <LocalResultView result={selectedResult} events={events} />}
      {selectedResult?.mode === "web" && <WebResultView result={selectedResult} events={events} />}
    </section>
  );
}

function KbPage({
  status,
  busy,
  onRefresh,
  onRebuild
}: {
  status: KbStatus | null;
  busy: boolean;
  onRefresh: () => void;
  onRebuild: () => void;
}) {
  return (
    <section>
      <h1>Knowledge Base Index</h1>
      <div className="kb-actions">
        <button onClick={onRefresh}>
          <RefreshCw size={16} />
          Refresh
        </button>
        <button onClick={onRebuild} disabled={busy}>
          Rebuild
        </button>
      </div>
      {status && (
        <dl className="kv">
          <dt>vault_path</dt>
          <dd>{status.vault_path}</dd>
          <dt>status</dt>
          <dd>{status.status}</dd>
          <dt>file_count</dt>
          <dd>{status.file_count}</dd>
          <dt>chunk_count</dt>
          <dd>{status.chunk_count}</dd>
          <dt>last_indexed_at</dt>
          <dd>{status.last_indexed_at ?? "none"}</dd>
        </dl>
      )}
    </section>
  );
}

function LocalResultView({ result, events }: { result: ResearchResult; events: ProgressEvent[] }) {
  const groupedEvents = useMemo(() => groupEvents(events), [events]);
  return (
    <article className="result-panel">
      <h2>Local Result</h2>
      <p>{result.question}</p>
      <StatusLine result={result} />
      <ProcessView groupedEvents={groupedEvents} />
      {result.local_results?.map((item, index) => (
        <div className="result-item" key={`${item.source_path}-${index}`}>
          <p>{item.text}</p>
          <code>{item.source_path}</code>
          {item.heading_path?.length ? <small>{item.heading_path.join(" > ")}</small> : null}
        </div>
      ))}
    </article>
  );
}

function WebResultView({ result, events }: { result: ResearchResult; events: ProgressEvent[] }) {
  const groupedEvents = useMemo(() => groupEvents(events), [events]);
  return (
    <article className="result-panel">
      <h2>Web Report</h2>
      <p>{result.question}</p>
      <StatusLine result={result} />
      <ProcessView groupedEvents={groupedEvents} />
      {result.curator_output && (
        <>
          <h3>Summary</h3>
          <p>{result.curator_output.summary}</p>
          <h3>Findings</h3>
          <ul>{result.curator_output.findings.map((finding) => <li key={finding.finding_id}>{finding.text}</li>)}</ul>
          <h3>Sources</h3>
          <ul>{result.curator_output.sources.map((source) => <li key={source.source_id}>{source.title} - {source.url}</li>)}</ul>
        </>
      )}
      {result.report_path && <code>{result.report_path}</code>}
    </article>
  );
}

function ProcessView({ groupedEvents }: { groupedEvents: Record<string, ProgressEvent[]> }) {
  if (Object.keys(groupedEvents).length === 0) {
    return null;
  }
  return (
    <div className="process">
      {Object.entries(groupedEvents).map(([phase, phaseEvents]) => (
        <section key={phase}>
          <h3>{phase}</h3>
          {phaseEvents.map((event) => (
            <div key={`${event.created_at}-${event.message}`}>
              <p className="event-message">{event.message}</p>
              {event.details?.items?.length > 0 && (
                <ul className="event-items">
                  {event.details.items.map((item, idx) => (
                    <DetailItem key={idx} item={item} />
                  ))}
                </ul>
              )}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

function DetailItem({ item }: { item: Record<string, unknown> }) {
  const kind = String(item.kind ?? "");
  switch (kind) {
    case "tool_call":
      return (
        <li className="detail-tool-call">
          <Wrench size={12} />
          <span className="tool-name">{String(item.name ?? "")}</span>
          {item.input ? <code>{String(item.input).slice(0, 120)}</code> : null}
        </li>
      );
    case "source": {
      const url = item.url ? String(item.url) : null;
      const path = item.path ? String(item.path) : null;
      const title = String(item.title ?? item.path ?? "");
      return (
        <li className="detail-source">
          <Link size={12} />
          {url ? (
            <a href={url} target="_blank" rel="noopener noreferrer">{title || url}</a>
          ) : (
            <code>{path || title}</code>
          )}
        </li>
      );
    }
    case "finding":
      return (
        <li className="detail-finding">
          <span className="finding-text">{String(item.text ?? "").slice(0, 200)}</span>
          {item.subtask_id ? <small>{String(item.subtask_id)}</small> : null}
        </li>
      );
    case "subtask_completed":
      return (
        <li className="detail-subtask">
          <span>{String(item.question ?? item.subtask_id ?? "")}</span>
          <small>{item.status ? String(item.status) : ""} · {item.finding_count ? `${item.finding_count} findings` : ""}{item.source_count ? `, ${item.source_count} sources` : ""}</small>
        </li>
      );
    case "subtask_failed":
      return (
        <li className="detail-subtask failed">
          <span>{String(item.question ?? item.subtask_id ?? "")}</span>
          <small>failed: {String(item.error ?? "").slice(0, 100)}</small>
        </li>
      );
    default:
      return null;
  }
}

function StatusLine({ result }: { result: ResearchResult }) {
  return (
    <p className={result.status === "failed" ? "status failed" : "status completed"}>
      {result.status}
      {result.error ? ` [${result.error.code}] ${result.error.message}` : ""}
    </p>
  );
}

function groupEvents(events: ProgressEvent[]) {
  return events.reduce<Record<string, ProgressEvent[]>>((groups, event) => {
    groups[event.phase] = [...(groups[event.phase] ?? []), event];
    return groups;
  }, {});
}
