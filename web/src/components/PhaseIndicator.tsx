const WEB_PHASES = ["web_planning", "web_execution", "web_supervision", "web_revision", "web_curation"];
const LOCAL_PHASES = ["local_rag"];

const phaseLabel = (phase: string) => phase.replace("web_", "").replace("local_", "");

export function PhaseIndicator({ currentPhase, mode }: { currentPhase: string | null; mode: "local" | "web" }) {
  const phases = mode === "local" ? LOCAL_PHASES : WEB_PHASES;
  return (
    <div className="phase-indicator">
      {phases.map((p) => (
        <span key={p} className={p === currentPhase ? "phase-dot active" : "phase-dot"} title={phaseLabel(p)}>
          {phaseLabel(p)}
        </span>
      ))}
    </div>
  );
}
