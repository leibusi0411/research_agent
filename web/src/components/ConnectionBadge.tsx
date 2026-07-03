import type { ConnectionState } from "../hooks/useSSE";

const config: Record<ConnectionState, { className: string; label: string }> = {
  connected: { className: "connected", label: "connected" },
  reconnecting: { className: "reconnecting", label: "reconnecting" },
  disconnected: { className: "disconnected", label: "disconnected" },
};

export function ConnectionBadge({ status }: { status: ConnectionState }) {
  const { className, label } = config[status];
  return (
    <span className="connection-badge" title={label}>
      <span className={`connection-dot ${className}`} />
      <span className="connection-label">{label}</span>
    </span>
  );
}
