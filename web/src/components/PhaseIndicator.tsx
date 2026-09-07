const WEB_PHASES = ["web_local_context", "web_planning", "web_execution", "web_supervision", "web_revision", "web_curation"];
const LOCAL_PHASES = ["local_rag"];

// Strip the leading mode prefix and humanise (web_local_context → local context).
const phaseLabel = (phase: string) => phase.replace(/^(web|local)_/, "").replace(/_/g, " ");

export function PhaseIndicator({
  currentPhase,
  mode,
  running = false
}: {
  currentPhase: string | null;
  mode: "local" | "web";
  running?: boolean;
}) {
  const phases = mode === "local" ? LOCAL_PHASES : WEB_PHASES;
  return (
    <div className="phase-indicator">
      {phases.map((p) => (
        <span
          key={p}
          className={p === currentPhase ? `phase-dot active${running ? " running" : ""}` : "phase-dot"}
          title={phaseLabel(p)}
        >
          {phaseLabel(p)}
        </span>
      ))}
    </div>
  );
}
