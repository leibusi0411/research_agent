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
    <section className="kb-page">
      <header className="kb-hero">
        <h1>Knowledge Base Index</h1>
        <p className="kb-subtitle">Local retrieval over your Markdown vault</p>
      </header>

      <form className="kb-search" onSubmit={onLocalSearch}>
        <Search className="kb-search-icon" size={18} aria-hidden />
        <input
          aria-label="Local RAG question"
          placeholder="Ask your local knowledge base…"
          value={localQuestion}
          onChange={(event) => setLocalQuestion(event.target.value)}
        />
        <button type="submit" disabled={localRunning || busy} aria-label="Search">
          <span>Search</span>
        </button>
      </form>

      {status && (
        <section className="kb-panel" aria-label="Knowledge Base Index">
          <div className="kb-panel-head">
            <span className={`kb-status kb-status-${status.status}`}>
              <span className="kb-status-dot" aria-hidden />
              {status.status}
            </span>
            <span className="kb-vault" title={status.vault_path}>
              {status.vault_path}
            </span>
          </div>
          <div className="kb-stats">
            <div className="kb-stat">
              <span className="kb-stat-value">{status.file_count}</span>
              <span className="kb-stat-label">files</span>
            </div>
            <div className="kb-stat">
              <span className="kb-stat-value">{status.chunk_count}</span>
              <span className="kb-stat-label">chunks</span>
            </div>
            <div className="kb-stat">
              <span className="kb-stat-value kb-stat-time">
                {status.last_indexed_at ?? "—"}
              </span>
              <span className="kb-stat-label">last indexed</span>
            </div>
          </div>
          <div className="kb-actions">
            <button onClick={onRefresh}>
              <RefreshCw size={14} aria-hidden />
              Refresh
            </button>
            <button onClick={onRebuild} disabled={busy}>
              Rebuild
            </button>
          </div>
        </section>
      )}

      {localEvents.length > 0 && (
        <TraceCard events={localEvents} phase={null} running={localRunning} />
      )}
      {localResult && <LocalResultView result={localResult} events={localEvents} />}
    </section>
  );
}
