import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, Link, ListChecks, Search, Sparkles, Wrench } from "lucide-react";
import { type ProgressEvent } from "../api";

/**
 * The flowing activity feed (R-287): a fixed-height narrow strip where
 * research activity streams in bottom-up — subtask questions, tool calls,
 * findings, sources — each as a compact one-line chip. Clicking a chip
 * expands its full detail inline. When the run finishes the feed freezes
 * (no more auto-scroll) and the classic grouped ProcessView takes over.
 */

type FeedRow = {
  key: string;
  icon: "subtask" | "tool_call" | "finding" | "source" | "phase";
  label: string;
  detail?: string;
  href?: string;
};

function rowsFromEvents(events: ProgressEvent[]): FeedRow[] {
  const rows: FeedRow[] = [];
  let n = 0;
  for (const event of events) {
    const phaseLabel = String(event.phase ?? "").replace(/^web_/, "");
    const items = event.details?.items ?? [];
    if (event.event_type === "started" && items.length === 0) {
      rows.push({ key: `p${n++}`, icon: "phase", label: `${phaseLabel}: ${event.message}` });
      continue;
    }
    for (const item of items) {
      if (!item || typeof item !== "object") continue;
      const kind = String(item.kind ?? "");
      if (kind === "subtask") {
        rows.push({
          key: `s${n++}`,
          icon: "subtask",
          label: String(item.question ?? item.subtask_id ?? ""),
          detail: `subtask ${String(item.subtask_id ?? "")}`,
        });
      } else if (kind === "tool_call") {
        rows.push({
          key: `t${n++}`,
          icon: "tool_call",
          label: String(item.name ?? "tool"),
          detail: item.input ? String(item.input) : undefined,
        });
      } else if (kind === "finding") {
        rows.push({ key: `f${n++}`, icon: "finding", label: String(item.text ?? ""), detail: String(item.subtask_id ?? "") });
      } else if (kind === "source" && (item.url || item.path)) {
        const href = item.url ? String(item.url) : undefined;
        rows.push({
          key: `c${n++}`,
          icon: "source",
          label: String(item.title ?? item.path ?? item.url ?? ""),
          detail: item.path ? String(item.path) : undefined,
          href,
        });
      } else if (kind === "subtask_completed" || kind === "subtask_failed") {
        rows.push({
          key: `d${n++}`,
          icon: "subtask",
          label: `${kind === "subtask_failed" ? "✗" : "✓"} ${String(item.question ?? item.subtask_id ?? "")}`,
          detail: kind === "subtask_failed" ? String(item.error ?? "") : `${item.finding_count ?? 0} findings · ${item.source_count ?? 0} sources`,
        });
      }
    }
  }
  return rows;
}

const ICONS = {
  subtask: ListChecks,
  tool_call: Wrench,
  finding: Sparkles,
  source: Link,
  phase: ChevronRight,
} as const;

function iconTone(icon: FeedRow["icon"]): string {
  switch (icon) {
    case "subtask": return "tone-subtask";
    case "tool_call": return "tone-tool";
    case "finding": return "tone-finding";
    case "source": return "tone-source";
    default: return "tone-phase";
  }
}

export function FlowFeed({ events, running }: { events: ProgressEvent[]; running: boolean }) {
  const rows = useMemo(() => rowsFromEvents(events), [events]);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const stripRef = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  useEffect(() => {
    const el = stripRef.current;
    if (el && pinned.current && running) {
      el.scrollTo?.({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [rows.length, running]);

  function handleScroll() {
    const el = stripRef.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  return (
    <div className="flow-feed" onScroll={handleScroll} ref={stripRef} role="log" aria-live={running ? "polite" : "off"}>
      {rows.map((row) => {
        const Icon = ICONS[row.icon];
        const clickable = Boolean(row.detail || row.href);
        const open = openKey === row.key;
        return (
          <div key={row.key} className={`feed-row ${row.icon} ${clickable ? "clickable" : ""} ${open ? "open" : ""}`}>
            <button
              type="button"
              className="feed-chip"
              disabled={!clickable}
              onClick={() => setOpenKey(open ? null : row.key)}
              title={clickable ? "Click for detail" : undefined}
            >
              <Icon size={12} aria-hidden="true" />
              <span className={`feed-label ${iconTone(row.icon)}`}>{row.label.slice(0, 160)}</span>
              {row.href && (
                <a
                  href={row.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="feed-link"
                >
                  open
                </a>
              )}
            </button>
            {open && row.detail && <pre className="feed-detail">{row.detail}</pre>}
          </div>
        );
      })}
      {rows.length === 0 && <p className="feed-empty">Waiting for activity…</p>}
      {running && <div className="feed-pulse" aria-hidden="true" />}
    </div>
  );
}
