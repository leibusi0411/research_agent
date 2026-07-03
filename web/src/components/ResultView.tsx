import { useMemo } from "react";
import { type ProgressEvent, type ResearchResult } from "../api";
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
    </article>
  );
}
