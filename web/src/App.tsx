import { FormEvent, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import {
  api,
  ApiError,
  type KbStatus,
  type ProgressEvent,
  type ResearchResult,
  type SetupPayload,
  subscribeTaskEvents,
  type TaskSummary,
} from "./api";
import { Sidebar } from "./components/Sidebar";
import { emptySetup, SettingsPage } from "./pages/SettingsPage";
import { ResearchPage } from "./pages/ResearchPage";
import { TasksPage } from "./pages/TasksPage";
import { KbPage } from "./pages/KbPage";

export function App() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [setup, setSetup] = useState<SetupPayload>(emptySetup);
  const [savedKeys, setSavedKeys] = useState({ chat: false, embedding: false, search: false });
  const [savedNotice, setSavedNotice] = useState(false);
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [kbStatus, setKbStatus] = useState<KbStatus | null>(null);
  const [selectedResult, setSelectedResult] = useState<ResearchResult | null>(null);
  const [selectedEvents, setSelectedEvents] = useState<ProgressEvent[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [deletingTaskIds, setDeletingTaskIds] = useState<string[]>([]);
  const [phase, setPhase] = useState<string | null>(null);

  const navigate = useNavigate();

  const esCleanup = useRef<(() => void) | null>(null);

  // Clean up the EventSource connection on unmount
  useEffect(() => {
    return () => {
      esCleanup.current?.();
    };
  }, []);

  /** Fetch the final result once the SSE stream reports completion. */
  async function finishTask(taskId: string) {
    try {
      const finalResult = await api.taskResult(taskId);
      setResult(finalResult);
      setSelectedResult(finalResult);
      try {
        // Backfill the full trace so a reattached session shows history too.
        // A still-running task serves SSE here (not JSON) — keep streamed events.
        setEvents(await api.taskEvents(taskId));
      } catch {
        // keep the streamed events
      }
      await refreshTasks();
    } catch (error) {
      // Result fetch failed after the stream ended: clear events so the
      // running state (events && !result) does not stick forever.
      setEvents([]);
      setMessage(String(error));
    }
  }

  /** Subscribe the research view to a task's live event stream. */
  function attachToTask(taskId: string) {
    setEvents([]);
    setPhase(null);
    setResult(null);
    const collected: ProgressEvent[] = [];
    esCleanup.current?.();
    esCleanup.current = subscribeTaskEvents(
      taskId,
      (evt) => {
        collected.push(evt);
        setEvents([...collected]);
        if (evt.phase) setPhase(evt.phase);
      },
      () => finishTask(taskId),
      () => finishTask(taskId),
    );
  }

  /** Reattach to a running web task (page reload mid-run, or 409 busy). */
  async function reattachToActiveWebTask(): Promise<boolean> {
    try {
      const { active } = await api.activeTasks();
      const webActive = (active ?? []).find((entry) => entry.mode === "web");
      if (!webActive) return false;
      try {
        const running = await api.taskResult(webActive.task_id);
        setQuestion(running.question);
      } catch {
        // Question stays as-is; the trace still attaches.
      }
      attachToTask(webActive.task_id);
      return true;
    } catch {
      return false;
    }
  }

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
      // A web task may still be running from before a page reload — reattach.
      reattachToActiveWebTask();
    }
  }, [configured]);

  async function submitSetup(event: FormEvent) {
    event.preventDefault();
    const wasConfigured = configured;
    setBusy("setup");
    try {
      await api.setupInit(setup);
      setConfigured(true);
      setSavedKeys({ chat: true, embedding: true, search: true });
      // Never keep real key values in form state after a successful save.
      setSetup((current) => ({ ...current, chat_api_key: "", embedding_api_key: "", search_api_key: "" }));
      setMessage("");
      if (wasConfigured) {
        setSavedNotice(true);
      } else {
        navigate("/");
      }
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(null);
    }
  }

  /** Prefill the settings form from the saved config (keys stay blank). */
  async function loadSettings() {
    setSavedNotice(false);
    setMessage("");
    try {
      const config = await api.setupConfig();
      setSetup((current) => ({
        ...current,
        default_workspace: config.default_workspace,
        knowledge_base_path: config.knowledge_base_path,
        chat_base_url: config.chat_base_url,
        chat_model: config.chat_model,
        embedding_base_url: config.embedding_base_url,
        embedding_model: config.embedding_model
      }));
      setSavedKeys({
        chat: config.has_chat_api_key,
        embedding: config.has_embedding_api_key,
        search: config.has_search_api_key
      });
    } catch {
      // No saved config yet — keep the blank form.
    }
  }

  function updateSetup(value: SetupPayload) {
    setSavedNotice(false);
    setSetup(value);
  }

  async function runResearch(event: FormEvent) {
    event.preventDefault();
    setEvents([]);
    setPhase(null);
    setResult(null);
    setBusy("web");
    try {
      const started = await api.runWeb(question);
      if (started.status !== "running") {
        setResult(started);
        setSelectedResult(started);
        await refreshTasks();
        return;
      }
      attachToTask(started.task_id);
    } catch (error) {
      // Another web task is already running: attach to it instead of
      // leaving the user staring at a bare error.
      if (error instanceof ApiError && error.code === "busy" && (await reattachToActiveWebTask())) {
        setMessage("");
        return;
      }
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
    if (deletingTaskIds.includes(task.task_id)) {
      return;
    }
    try {
      const result = await api.taskResult(task.task_id);
      const events = await api.taskEvents(task.task_id);
      setSelectedResult(result);
      setSelectedEvents(events);
      navigate("/tasks");
    } catch (error) {
      setMessage(String(error));
    }
  }

  async function deleteTask(task: TaskSummary) {
    if (
      !window.confirm(
        `Permanently delete task "${task.title_or_question || task.task_id}"? This cannot be undone.`,
      )
    ) {
      return;
    }
    const tid = task.task_id;
    setDeletingTaskIds((prev) => [...prev, tid]);
    try {
      await api.deleteTask(tid);
      setTasks((current) => current.filter((item) => item.task_id !== tid));
      // Clear selected result and the live result when they reference the
      // deleted task so no page still displays removed data.
      if (selectedResult?.task_id === tid) {
        setSelectedResult(null);
        setSelectedEvents([]);
      }
      if (result?.task_id === tid) {
        setResult(null);
        setEvents([]);
        setPhase(null);
      }
      setMessage("");
      await refreshTasks();
    } catch (error) {
      setMessage(String(error));
    } finally {
      setDeletingTaskIds((prev) => prev.filter((id) => id !== tid));
    }
  }

  if (configured === null) {
    return <main className="boot">Loading</main>;
  }

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="workspace">
        {message && <div className="error banner">{message}</div>}
        <Routes>
          <Route
            path="/"
            element={
              <ResearchPage
                question={question}
                setQuestion={setQuestion}
                runResearch={runResearch}
                busy={busy}
                result={result}
                events={events}
                phase={phase}
              />
            }
          />
          <Route
            path="/tasks"
            element={
              <TasksPage
                tasks={tasks}
                selectedResult={selectedResult}
                events={selectedEvents}
                onOpen={openTask}
                onDelete={deleteTask}
                deletingTaskIds={deletingTaskIds}
              />
            }
          />
          <Route
            path="/kb"
            element={
              <KbPage
                status={kbStatus}
                busy={busy === "kb"}
                onRefresh={refreshKb}
                onRebuild={rebuildKb}
              />
            }
          />
          <Route
            path="/settings"
            element={
              <SettingsPage
                setup={setup}
                setSetup={updateSetup}
                savedKeys={savedKeys}
                savedNotice={savedNotice}
                loadSettings={loadSettings}
                busy={busy === "setup"}
                message={message}
                onSubmit={submitSetup}
              />
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
