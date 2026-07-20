import { FormEvent } from "react";
import { BookOpen, Sparkles, Wifi } from "lucide-react";
import { type ProgressEvent, type ResearchResult } from "../api";
import { ConnectionBadge } from "../components/ConnectionBadge";
import { PhaseIndicator } from "../components/PhaseIndicator";
import { LocalResultView, WebResultView } from "../components/ResultView";

export function ResearchPage({
  localQuestion,
  webQuestion,
  setLocalQuestion,
  setWebQuestion,
  runLocal,
  runWeb,
  busy,
  localResult,
  webResult,
  localEvents,
  webEvents,
  localPhase,
  webPhase,
}: {
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
  localPhase: string | null;
  webPhase: string | null;
}) {
  const localRunning = busy === "local";
  const webRunning = busy === "web";

  return (
    <section className="research-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Research workspace</p>
          <h1>Research</h1>
          <p className="page-summary">Run local knowledge-base retrieval or web research, then watch the agent trace its work in real time.</p>
        </div>
        <span className="header-pill">
          <Sparkles size={14} />
          Agent ready
        </span>
      </header>
      <div className="research-grid">
        <form className="tool-panel local" onSubmit={runLocal}>
          <h2>
            <BookOpen size={18} />
            Local RAG
            {localRunning && (
              <span className="tool-status">
                <ConnectionBadge status="connected" />
              </span>
            )}
          </h2>
          {localRunning && localPhase && <PhaseIndicator currentPhase={localPhase} mode="local" />}
          <textarea
            aria-label="Local RAG question"
            value={localQuestion}
            onChange={(event) => setLocalQuestion(event.target.value)}
            placeholder="Ask against your indexed notes..."
            required
          />
          <button disabled={localRunning}>Run Local</button>
        </form>
        <form className="tool-panel web" onSubmit={runWeb}>
          <h2>
            <Wifi size={18} />
            Web Research
            {webRunning && (
              <span className="tool-status">
                <ConnectionBadge status="connected" />
              </span>
            )}
          </h2>
          {webRunning && webPhase && <PhaseIndicator currentPhase={webPhase} mode="web" />}
          <textarea
            aria-label="Web research question"
            value={webQuestion}
            onChange={(event) => setWebQuestion(event.target.value)}
            placeholder="Ask for a current web-backed report..."
            required
          />
          <button disabled={webRunning}>Run Web</button>
        </form>
      </div>
      <div className="result-grid">
        {localResult && <LocalResultView result={localResult} events={localEvents} />}
        {webResult && <WebResultView result={webResult} events={webEvents} />}
      </div>
    </section>
  );
}
