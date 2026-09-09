import { Fragment } from "react";
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
          <Fragment key={task.task_id}>
            <div className="task-row">
              <button className="task-open" onClick={() => onOpen(task)}>
                <span>{task.task_id}</span>
                <span className="mode-cell">
                  <span className={`lane-glyph lane-${task.mode}`} aria-hidden="true" />
                  {task.mode}
                </span>
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
            {/* Detail box expands inline, directly under the clicked row. */}
            {selectedResult?.task_id === task.task_id && (
              <div className="task-detail">
                {selectedResult.mode === "local" ? (
                  <LocalResultView result={selectedResult} events={events} />
                ) : (
                  <WebResultView result={selectedResult} events={events} />
                )}
              </div>
            )}
          </Fragment>
        ))}
      </div>
    </section>
  );
}
