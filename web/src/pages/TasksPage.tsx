import { type ProgressEvent, type ResearchResult, type TaskSummary } from "../api";
import { LocalResultView, WebResultView } from "../components/ResultView";

export function TasksPage({
  tasks,
  selectedResult,
  events,
  onOpen,
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
