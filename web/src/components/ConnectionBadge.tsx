import type { ConnectionState } from "../hooks/useSSE";

const config: Record<ConnectionState, { color: string; label: string }> = {
  connected: { color: "#27ae60", label: "connected" },
  reconnecting: { color: "#f39c12", label: "reconnecting" },
  disconnected: { color: "#e74c3c", label: "disconnected" },
};

export function ConnectionBadge({ status }: { status: ConnectionState }) {
  const { color, label } = config[status];
  return (
    <span className="connection-badge" title={label}>
      <span className="connection-dot" style={{ color }}>&#9679;</span>
      <span className="connection-label">{label}</span>
    </span>
  );
}
