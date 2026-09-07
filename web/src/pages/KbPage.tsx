import { RefreshCw } from "lucide-react";
import { type KbStatus } from "../api";

export function KbPage({
  status,
  busy,
  onRefresh,
  onRebuild,
}: {
  status: KbStatus | null;
  busy: boolean;
  onRefresh: () => void;
  onRebuild: () => void;
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
    </section>
  );
}
