import { FormEvent, useEffect } from "react";
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

const SAVED_KEY_PLACEHOLDER = "Saved — leave blank to keep";

function SetupFields({
  setup,
  setSetup,
  savedKeys
}: {
  setup: SetupPayload;
  setSetup: (value: SetupPayload) => void;
  savedKeys: { chat: boolean; embedding: boolean; search: boolean };
}) {
  const savedByKey: Record<string, boolean> = {
    chat_api_key: savedKeys.chat,
    embedding_api_key: savedKeys.embedding,
    search_api_key: savedKeys.search
  };
  return (
    <div className="setup-grid">
      {Object.keys(setup).map((key) => {
        const saved = savedByKey[key];
        return (
          <label key={key}>
            <span>{key}</span>
            <input
              name={key}
              value={setup[key as keyof SetupPayload]}
              onChange={(event) => setSetup({ ...setup, [key]: event.target.value })}
              type={key.includes("api_key") ? "password" : "text"}
              required={!saved}
              placeholder={saved ? SAVED_KEY_PLACEHOLDER : ""}
            />
          </label>
        );
      })}
    </div>
  );
}

export function SettingsPage({
  setup,
  setSetup,
  savedKeys,
  savedNotice,
  loadSettings,
  busy,
  message,
  onSubmit
}: {
  setup: SetupPayload;
  setSetup: (value: SetupPayload) => void;
  savedKeys: { chat: boolean; embedding: boolean; search: boolean };
  savedNotice: boolean;
  loadSettings: () => Promise<void>;
  busy: boolean;
  message: string;
  onSubmit: (event: FormEvent) => void;
}) {
  useEffect(() => {
    loadSettings();
    // Prefill once when the page opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section className="page">
      <form className="setup-panel" onSubmit={onSubmit}>
        <div className="panel-title">
          <Settings size={22} />
          <h1>Settings</h1>
        </div>
        <SetupFields setup={setup} setSetup={setSetup} savedKeys={savedKeys} />
        <button type="submit" disabled={busy}>
          Save Config
        </button>
        {savedNotice && <p className="saved">Settings saved.</p>}
        {message && <p className="error">{message}</p>}
      </form>
    </section>
  );
}
