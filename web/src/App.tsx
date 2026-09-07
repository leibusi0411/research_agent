import { FormEvent, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import {
  api,
  type KbStatus,
  type ProgressEvent,
  type ResearchResult,
  type SetupPayload,
  subscribeTaskEvents,
  type TaskSummary,
} from "./api";
import { Sidebar } from "./components/Sidebar";
import { emptySetup, SetupPage } from "./pages/SetupPage";
import { ResearchPage } from "./pages/ResearchPage";
import { TasksPage } from "./pages/TasksPage";
import { KbPage } from "./pages/KbPage";

export function App() {
  const [configured, setConfigured] = useState<boolean | null>(null);
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
  const [deletingTaskIds, setDeletingTaskIds] = useState<string[]>([]);
  const [localPhase, setLocalPhase] = useState<string | null>(null);
  const [webPhase, setWebPhase] = useState<string | null>(null);

  const navigate = useNavigate();

  const localEsCleanup = useRef<(() => void) | null>(null);
  const webEsCleanup = useRef<(() => void) | null>(null);

  // Clean up EventSource connections on unmount
  useEffect(() => {
    return () => {
      localEsCleanup.current?.();
      webEsCleanup.current?.();
    };
  }, []);

  /** Shared factory: creates onResult/onError callbacks for SSE task completion. */
  function createTaskFinisher(mode: "local" | "web") {
    const setResult = mode === "local" ? setLocalResult : setWebResult;
    const clearEvents = mode === "local" ? () => setLocalEvents([]) : () => setWebEvents([]);
    return async (taskId: string) => {
      try {
        const finalResult = await api.taskResult(taskId);
        setResult(finalResult);
        setSelectedResult(finalResult);
        await refreshTasks();
      } catch (error) {
        // Result fetch failed after the stream ended: clear events so the
        // lane's running state (events && !result) does not stick forever.
        clearEvents();
        setMessage(String(error));
      }
    };
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
    setLocalPhase(null);
    setLocalResult(null);
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
      const finishTask = createTaskFinisher("local");
      localEsCleanup.current?.();
      localEsCleanup.current = subscribeTaskEvents(
        started.task_id,
        (evt) => {
          collected.push(evt);
          setLocalEvents([...collected]);
          if (evt.phase) setLocalPhase(evt.phase);
        },
        () => finishTask(started.task_id),
        () => finishTask(started.task_id),
      );
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(null);
    }
  }

  async function runWeb(event: FormEvent) {
    event.preventDefault();
    setWebEvents([]);
    setWebPhase(null);
    setWebResult(null);
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
      const finishTask = createTaskFinisher("web");
      webEsCleanup.current?.();
      webEsCleanup.current = subscribeTaskEvents(
        started.task_id,
        (evt) => {
          collected.push(evt);
          setWebEvents([...collected]);
          if (evt.phase) setWebPhase(evt.phase);
        },
        () => finishTask(started.task_id),
        () => finishTask(started.task_id),
      );
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
      // Clear selected result and all result/events states when they reference
      // the deleted task so no page still displays removed data.
      if (selectedResult?.task_id === tid) {
        setSelectedResult(null);
        setSelectedEvents([]);
      }
      if (localResult?.task_id === tid) {
        setLocalResult(null);
        setLocalEvents([]);
      }
      if (webResult?.task_id === tid) {
        setWebResult(null);
        setWebEvents([]);
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

  if (!configured) {
    return (
      <SetupPage
        setup={setup}
        setSetup={setSetup}
        busy={busy === "setup"}
        message={message}
        onSubmit={submitSetup}
      />
    );
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
                localPhase={localPhase}
                webPhase={webPhase}
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
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
