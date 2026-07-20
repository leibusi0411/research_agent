import { type ProgressEvent, type ResearchResult, type TaskSummary } from "../api";
import { LocalResultView, WebResultView } from "../components/ResultView";

export function TasksPage({
  tasks,
  selectedResult,
  events,
  onOpen,
  onDelete,
  deletingTaskIds,
}: {
  tasks: TaskSummary[];
  selectedResult: ResearchResult | null;
  events: ProgressEvent[];
  onOpen: (task: TaskSummary) => void;
  onDelete: (task: TaskSummary) => void;
  deletingTaskIds: string[];
}) {
  return (
    <section>
      <h1>Tasks</h1>
      <div className="table">
        {tasks.map((task) => (
          <div className="task-row" key={task.task_id}>
            <button className="task-open" onClick={() => onOpen(task)}>
              <span>{task.task_id}</span>
              <span>{task.mode}</span>
              <span>{task.status}</span>
              <span>{task.title_or_question}</span>
              <span>{task.created_at}</span>
            </button>
            <button
              aria-label={`Delete task ${task.title_or_question || task.task_id}`}
              className="danger task-delete"
              onClick={() => onDelete(task)}
              disabled={deletingTaskIds.includes(task.task_id)}
            >
              {deletingTaskIds.includes(task.task_id) ? "Deleting" : "Delete"}
            </button>
          </div>
        ))}
      </div>
      {selectedResult?.mode === "local" && <LocalResultView result={selectedResult} events={events} />}
      {selectedResult?.mode === "web" && <WebResultView result={selectedResult} events={events} />}
    </section>
  );
}
