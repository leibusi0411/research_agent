import { useMemo, useState } from "react";
import { api, ApiError, type ProgressEvent, type ResearchResult } from "../api";
import { groupEvents, ProcessView } from "./ProcessView";
import { ConnectionBadge } from "./ConnectionBadge";
import { PhaseIndicator } from "./PhaseIndicator";

function useGroupedEvents(events: ProgressEvent[]) {
  const groupedEvents = useMemo(() => groupEvents(events), [events]);
  const newestSeq = useMemo(() => {
    let max = 0;
    for (const e of events) if (e.seq !== undefined && e.seq > max) max = e.seq;
    return max;
  }, [events]);
  return { groupedEvents, newestSeq };
}

/** Live counters derived from the event stream: searches / sources / findings. */
function traceStats(events: ProgressEvent[]) {
  let searches = 0;
  let sources = 0;
  let findings = 0;
  for (const event of events) {
    for (const item of event.details?.items ?? []) {
      if (!item || typeof item !== "object") continue;
      if (item.kind === "tool_call") searches += 1;
      else if (item.kind === "source" && item.url) sources += 1;
      else if (item.kind === "finding") findings += 1;
    }
  }
  return { searches, sources, findings };
}

/** Prior-knowledge note paths injected before planning (ADR-0046), deduped. */
function usePriorKnowledgePaths(events: ProgressEvent[]): string[] {
  return useMemo(() => {
    const seen = new Set<string>();
    const paths: string[] = [];
    for (const event of events) {
      if (event.phase !== "web_planning") continue;
      for (const item of event.details?.items ?? []) {
        if (!item || typeof item !== "object") continue;
        if (item.kind === "source" && item.path) {
          const path = String(item.path);
          if (!seen.has(path)) {
            seen.add(path);
            paths.push(path);
          }
        }
      }
    }
    return paths;
  }, [events]);
}

/** The live research trace: stats, phase rail, and the streaming event log. */
export function TraceCard({
  events,
  phase,
  running,
}: {
  events: ProgressEvent[];
  phase: string | null;
  running: boolean;
}) {
  const { groupedEvents, newestSeq } = useGroupedEvents(events);
  const stats = useMemo(() => traceStats(events), [events]);
  if (events.length === 0) return null;
  const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;
  return (
    <article className={running ? "card trace-card running" : "card trace-card"}>
      <div className="trace-head">
        <h2>Research Trace</h2>
        {running && <ConnectionBadge status="connected" />}
        <span className="trace-stats">
          {plural(stats.searches, "search")} · {plural(stats.sources, "source")} · {plural(stats.findings, "finding")}
        </span>
      </div>
      {phase && <PhaseIndicator currentPhase={phase} mode="web" />}
      <ProcessView groupedEvents={groupedEvents} newestSeq={newestSeq} />
    </article>
  );
}

export function StatusLine({ result }: { result: ResearchResult }) {
  const statusClass =
    result.status === "failed" ? "status failed" : result.status === "running" ? "status running" : "status completed";
  return (
    <p className={statusClass}>
      {result.status}
      {result.error ? ` [${result.error.code}] ${result.error.message}` : ""}
    </p>
  );
}

export function LocalResultView({ result, events }: { result: ResearchResult; events: ProgressEvent[] }) {
  const { groupedEvents, newestSeq } = useGroupedEvents(events);
  return (
    <article className="card result-panel">
      <h2>
        <span className="lane-glyph lane-local" aria-hidden="true" />
        Local Result
      </h2>
      <p>{result.question}</p>
      <StatusLine result={result} />
      <ProcessView groupedEvents={groupedEvents} newestSeq={newestSeq} />
      {result.summary ? (
        <div className="result-item">
          <h3>Summary</h3>
          <p>{result.summary}</p>
        </div>
      ) : null}
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

/** The finished-research cards: report, local knowledge used, all sources. */
export function ResultCards({ result, events }: { result: ResearchResult; events: ProgressEvent[] }) {
  const notePaths = usePriorKnowledgePaths(events);
  const sources = result.curator_output?.sources ?? [];
  return (
    <div className="result-cards">
      <article className="card report-card">
        <h2>
          <span className="lane-glyph lane-web" aria-hidden="true" />
          Web Report
        </h2>
        <p className="report-question">{result.question}</p>
        <StatusLine result={result} />
        {result.curator_output && (
          <>
            <h3>Summary</h3>
            <p>{result.curator_output.summary}</p>
            <h3>Findings</h3>
            <ul>
              {result.curator_output.findings.map((finding) => (
                <li key={finding.finding_id}>{finding.text}</li>
              ))}
            </ul>
          </>
        )}
        {result.report_path && <code>{result.report_path}</code>}
        {result.status === "completed" && result.report_path && (
          <DepositPanel key={result.task_id} taskId={result.task_id} />
        )}
      </article>
      {notePaths.length > 0 && (
        <article className="card notes-card">
          <h2>
            <span className="lane-glyph lane-local" aria-hidden="true" />
            From Your Notes
          </h2>
          <p className="card-note">These local notes were injected into the planner before the web run.</p>
          <ul>
            {notePaths.map((path) => (
              <li key={path}>
                <code>{path}</code>
              </li>
            ))}
          </ul>
        </article>
      )}
      {sources.length > 0 && (
        <article className="card sources-card">
          <h2>Sources</h2>
          <ul>
            {sources.map((source) => (
              <li key={source.source_id}>
                <a href={source.url} target="_blank" rel="noopener noreferrer">
                  {source.title}
                </a>
                <code>{source.url}</code>
              </li>
            ))}
          </ul>
        </article>
      )}
    </div>
  );
}

export function WebResultView({ result, events }: { result: ResearchResult; events: ProgressEvent[] }) {
  return (
    <div className="result-stack">
      <TraceCard events={events} phase={null} running={false} />
      <ResultCards result={result} events={events} />
    </div>
  );
}

type DepositPhase = "idle" | "depositing" | "deposited";
type RebuildPhase = "idle" | "rebuilding" | "rebuilt" | "failed";

// Knowledge Deposit: explicitly save the finished Web Report File into the
// Markdown Vault, then offer to rebuild the index so the note is searchable.
export function DepositPanel({ taskId }: { taskId: string }) {
  const [phase, setPhase] = useState<DepositPhase>("idle");
  const [vaultPath, setVaultPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rebuild, setRebuild] = useState<RebuildPhase>("idle");
  const [rebuildError, setRebuildError] = useState<string | null>(null);

  async function deposit() {
    setPhase("depositing");
    setError(null);
    try {
      const result = await api.depositTask(taskId);
      setVaultPath(result.vault_path);
      setPhase("deposited");
    } catch (err) {
      if (err instanceof ApiError && err.code === "already_deposited") {
        setVaultPath(null);
        setPhase("deposited");
      } else {
        setError(err instanceof Error ? err.message : String(err));
        setPhase("idle");
      }
    }
  }

  async function rebuildIndex() {
    setRebuild("rebuilding");
    setRebuildError(null);
    try {
      await api.kbRebuild();
      setRebuild("rebuilt");
    } catch (err) {
      setRebuildError(err instanceof Error ? err.message : String(err));
      setRebuild("failed");
    }
  }

  if (phase === "deposited") {
    return (
      <div className="deposit-panel">
        <p className="status completed">
          {vaultPath ? "Deposited to Knowledge Base." : "Already deposited to Knowledge Base."}
        </p>
        {vaultPath && <code>{vaultPath}</code>}
        {rebuild === "rebuilt" ? (
          <p>Index rebuilt — the deposited note is now searchable.</p>
        ) : (
          <>
            <button type="button" onClick={rebuildIndex} disabled={rebuild === "rebuilding"}>
              {rebuild === "rebuilding" ? "Rebuilding…" : rebuild === "failed" ? "Rebuild failed — retry" : "Rebuild Index"}
            </button>
            {rebuild === "failed" && rebuildError && <p className="status failed">{rebuildError}</p>}
          </>
        )}
      </div>
    );
  }
  return (
    <div className="deposit-panel">
      <button type="button" onClick={deposit} disabled={phase === "depositing"}>
        {phase === "depositing" ? "Depositing…" : "Deposit to Knowledge Base"}
      </button>
      {error && <p className="status failed">{error}</p>}
    </div>
  );
}
