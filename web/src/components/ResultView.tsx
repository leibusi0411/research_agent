import { useMemo, useState } from "react";
import { api, ApiError, type ProgressEvent, type ResearchResult } from "../api";
import { groupEvents, ProcessView } from "./ProcessView";

export function StatusLine({ result }: { result: ResearchResult }) {
  return (
    <p className={result.status === "failed" ? "status failed" : "status completed"}>
      {result.status}
      {result.error ? ` [${result.error.code}] ${result.error.message}` : ""}
    </p>
  );
}

export function LocalResultView({ result, events }: { result: ResearchResult; events: ProgressEvent[] }) {
  const groupedEvents = useMemo(() => groupEvents(events), [events]);
  const newestSeq = useMemo(() => {
    let max = 0;
    for (const e of events) if (e.seq !== undefined && e.seq > max) max = e.seq;
    return max;
  }, [events]);
  return (
    <article className="result-panel">
      <h2>Local Result</h2>
      <p>{result.question}</p>
      <StatusLine result={result} />
      <ProcessView groupedEvents={groupedEvents} newestSeq={newestSeq} />
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

export function WebResultView({ result, events }: { result: ResearchResult; events: ProgressEvent[] }) {
  const groupedEvents = useMemo(() => groupEvents(events), [events]);
  const newestSeq = useMemo(() => {
    let max = 0;
    for (const e of events) if (e.seq !== undefined && e.seq > max) max = e.seq;
    return max;
  }, [events]);
  return (
    <article className="result-panel">
      <h2>Web Report</h2>
      <p>{result.question}</p>
      <StatusLine result={result} />
      <ProcessView groupedEvents={groupedEvents} newestSeq={newestSeq} />
      {result.curator_output && (
        <>
          <h3>Summary</h3>
          <p>{result.curator_output.summary}</p>
          <h3>Findings</h3>
          <ul>{result.curator_output.findings.map((finding) => <li key={finding.finding_id}>{finding.text}</li>)}</ul>
          <h3>Sources</h3>
          <ul>{result.curator_output.sources.map((source) => <li key={source.source_id}>{source.title} - {source.url}</li>)}</ul>
        </>
      )}
      {result.report_path && <code>{result.report_path}</code>}
      {result.status === "completed" && result.report_path && <DepositPanel key={result.task_id} taskId={result.task_id} />}
    </article>
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
