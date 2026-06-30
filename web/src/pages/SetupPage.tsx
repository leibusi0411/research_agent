import { FormEvent } from "react";
import { Settings } from "lucide-react";
import { type SetupPayload } from "../api";

const emptySetup: SetupPayload = {
  default_workspace: "",
  knowledge_base_path: "",
  chat_base_url: "",
  chat_api_key: "",
  chat_model: "",
  embedding_base_url: "",
  embedding_api_key: "",
  embedding_model: "",
  search_api_key: ""
};

export { emptySetup };

function SetupFields({ setup, setSetup }: { setup: SetupPayload; setSetup: (value: SetupPayload) => void }) {
  return (
    <div className="setup-grid">
      {Object.keys(setup).map((key) => (
        <label key={key}>
          <span>{key}</span>
          <input
            value={setup[key as keyof SetupPayload]}
            onChange={(event) => setSetup({ ...setup, [key]: event.target.value })}
            type={key.includes("api_key") ? "password" : "text"}
            required
          />
        </label>
      ))}
    </div>
  );
}

export function SetupPage({
  setup,
  setSetup,
  busy,
  message,
  onSubmit,
}: {
  setup: SetupPayload;
  setSetup: (value: SetupPayload) => void;
  busy: boolean;
  message: string;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <main className="setup-shell">
      <form className="setup-panel" onSubmit={onSubmit}>
        <div className="panel-title">
          <Settings size={22} />
          <h1>Research Agent Setup</h1>
        </div>
        <SetupFields setup={setup} setSetup={setSetup} />
        <button type="submit" disabled={busy}>
          Save Config
        </button>
        {message && <p className="error">{message}</p>}
      </form>
    </main>
  );
}
