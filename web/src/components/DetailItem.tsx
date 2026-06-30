import { Link, Wrench } from "lucide-react";

export function DetailItem({ item }: { item: Record<string, unknown> }) {
  const kind = String(item.kind ?? "");
  switch (kind) {
    case "tool_call":
      return (
        <li className="detail-tool-call">
          <Wrench size={12} />
          <span className="tool-name">{String(item.name ?? "")}</span>
          {item.input ? <code>{String(item.input).slice(0, 120)}</code> : null}
        </li>
      );
    case "source": {
      const url = item.url ? String(item.url) : null;
      const path = item.path ? String(item.path) : null;
      const title = String(item.title ?? item.path ?? "");
      return (
        <li className="detail-source">
          <Link size={12} />
          {url ? (
            <a href={url} target="_blank" rel="noopener noreferrer">{title || url}</a>
          ) : (
            <code>{path || title}</code>
          )}
        </li>
      );
    }
    case "finding":
      return (
        <li className="detail-finding">
          <span className="finding-text">{String(item.text ?? "").slice(0, 200)}</span>
          {item.subtask_id ? <small>{String(item.subtask_id)}</small> : null}
        </li>
      );
    case "subtask_completed":
      return (
        <li className="detail-subtask">
          <span>{String(item.question ?? item.subtask_id ?? "")}</span>
          <small>{item.status ? String(item.status) : ""} · {item.finding_count ? `${item.finding_count} findings` : ""}{item.source_count ? `, ${item.source_count} sources` : ""}</small>
        </li>
      );
    case "subtask_failed":
      return (
        <li className="detail-subtask failed">
          <span>{String(item.question ?? item.subtask_id ?? "")}</span>
          <small>failed: {String(item.error ?? "").slice(0, 100)}</small>
        </li>
      );
    default:
      console.warn("DetailItem: unknown item kind", kind, item);
      return null;
  }
}
