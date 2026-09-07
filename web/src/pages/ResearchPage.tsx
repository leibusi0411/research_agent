import { FormEvent } from "react";
import { type ProgressEvent, type ResearchResult } from "../api";
import { ConnectionBadge } from "../components/ConnectionBadge";
import { PhaseIndicator } from "../components/PhaseIndicator";
import { LocalResultView, LiveResultPanel, WebResultView } from "../components/ResultView";

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
  // Running = request in flight, or events streaming in with no result yet.
  // (busy only covers the POST; the trace should stay alive for the whole run.)
  const localRunning = busy === "local" || (localEvents.length > 0 && !localResult);
  const webRunning = busy === "web" || (webEvents.length > 0 && !webResult);

  return (
    <section className="research-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Research workspace</p>
          <h1>Research</h1>
          <p className="page-summary">Run local knowledge-base retrieval or web research, then watch the agent trace its work in real time.</p>
        </div>
      </header>
      <div className="research-grid">
        <form className={localRunning ? "tool-panel running" : "tool-panel"} onSubmit={runLocal}>
          <h2>
            <span className="lane-glyph lane-local" aria-hidden="true" />
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
            disabled={localRunning}
            required
          />
          <button disabled={localRunning}>Run Local</button>
        </form>
        <form className={webRunning ? "tool-panel running" : "tool-panel"} onSubmit={runWeb}>
          <h2>
            <span className="lane-glyph lane-web" aria-hidden="true" />
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
            disabled={webRunning}
            required
          />
          <button disabled={webRunning}>Run Web</button>
        </form>
      </div>
      <div className="result-grid">
        {localRunning && !localResult && <LiveResultPanel mode="local" question={localQuestion} events={localEvents} />}
        {localResult && <LocalResultView result={localResult} events={localEvents} />}
        {webRunning && !webResult && <LiveResultPanel mode="web" question={webQuestion} events={webEvents} />}
        {webResult && <WebResultView result={webResult} events={webEvents} />}
      </div>
    </section>
  );
}
