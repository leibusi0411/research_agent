import { FormEvent } from "react";
import { RefreshCw, Search } from "lucide-react";
import { type KbStatus, type ProgressEvent, type ResearchResult } from "../api";
import { LocalResultView, TraceCard } from "../components/ResultView";

export function KbPage({
  status,
  busy,
  onRefresh,
  onRebuild,
  localQuestion,
  setLocalQuestion,
  localResult,
  localEvents,
  localRunning,
  onLocalSearch,
}: {
  status: KbStatus | null;
  busy: boolean;
  onRefresh: () => void;
  onRebuild: () => void;
  localQuestion: string;
  setLocalQuestion: (value: string) => void;
  localResult: ResearchResult | null;
  localEvents: ProgressEvent[];
  localRunning: boolean;
  onLocalSearch: (event: FormEvent) => void;
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
      <form className="kb-local" onSubmit={onLocalSearch}>
        <h2>Local RAG</h2>
        <div className="kb-local-row">
          <input
            aria-label="Local RAG question"
            placeholder="Ask your local knowledge base…"
            value={localQuestion}
            onChange={(event) => setLocalQuestion(event.target.value)}
          />
          <button type="submit" disabled={localRunning || busy}>
            <Search size={16} />
            Search
          </button>
        </div>
      </form>
      {status && (
        <dl className="kv">
          <dt>vault_path</dt>
          <dd>{status.vault_path}</dd>
          <dt>status</dt>
          <dd>{status.status}</dd>
          <dt>file_count</dt>
          <dd className="num">{status.file_count}</dd>
          <dt>chunk_count</dt>
          <dd className="num">{status.chunk_count}</dd>
          <dt>last_indexed_at</dt>
          <dd>{status.last_indexed_at ?? "none"}</dd>
        </dl>
      )}
      {localEvents.length > 0 && (
        <TraceCard events={localEvents} phase={null} running={localRunning} />
      )}
      {localResult && <LocalResultView result={localResult} events={localEvents} />}
    </section>
  );
}
