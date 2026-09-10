import { FormEvent, useEffect, useState } from "react";
import { Pencil } from "lucide-react";
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
  configured,
  busy,
  message,
  onSubmit
}: {
  setup: SetupPayload;
  setSetup: (value: SetupPayload) => void;
  savedKeys: { chat: boolean; embedding: boolean; search: boolean };
  savedNotice: boolean;
  loadSettings: () => Promise<void>;
  configured: boolean;
  busy: boolean;
  message: string;
  onSubmit: (event: FormEvent) => void;
}) {
  // First run lands directly in the form; afterwards the page is read-only
  // until the user explicitly enters edit mode.
  const [editing, setEditing] = useState(!configured);

  useEffect(() => {
    setEditing(!configured);
  }, [configured]);

  useEffect(() => {
    loadSettings();
    // Prefill once when the page opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // A successful save returns the page to the read-only view.
    if (savedNotice) setEditing(false);
  }, [savedNotice]);

  function cancelEditing() {
    loadSettings();
    setEditing(false);
  }

  const rows: Array<{ label: string; value: string; masked?: boolean }> = [
    { label: "default_workspace", value: setup.default_workspace },
    { label: "knowledge_base_path", value: setup.knowledge_base_path },
    { label: "chat_base_url", value: setup.chat_base_url },
    { label: "chat_model", value: setup.chat_model },
    { label: "embedding_base_url", value: setup.embedding_base_url },
    { label: "embedding_model", value: setup.embedding_model },
    { label: "chat_api_key", value: savedKeys.chat ? "••••••••" : "(not set)", masked: true },
    { label: "embedding_api_key", value: savedKeys.embedding ? "••••••••" : "(not set)", masked: true },
    { label: "search_api_key", value: savedKeys.search ? "••••••••" : "(not set)", masked: true }
  ];

  return (
    <section className="settings-page">
      <header className="settings-hero">
        <div>
          <h1>Settings</h1>
          <p className="settings-subtitle">
            {editing
              ? "Update your configuration, then save."
              : "Current configuration of Research Agent."}
          </p>
        </div>
        {!editing && (
          <button className="settings-edit" onClick={() => setEditing(true)}>
            <Pencil size={14} aria-hidden />
            Edit
          </button>
        )}
      </header>

      {editing ? (
        <form className="settings-panel" onSubmit={onSubmit}>
          <SetupFields setup={setup} setSetup={setSetup} savedKeys={savedKeys} />
          <div className="settings-actions">
            <button type="submit" disabled={busy}>
              Save Config
            </button>
            {configured && (
              <button type="button" className="ghost" onClick={cancelEditing} disabled={busy}>
                Cancel
              </button>
            )}
          </div>
          {savedNotice && <p className="saved">Settings saved.</p>}
          {message && <p className="error">{message}</p>}
        </form>
      ) : (
        <section className="settings-panel">
          <div className="settings-view">
            {rows.map((row) => (
              <div className="settings-row" key={row.label}>
                <span className="settings-label">{row.label}</span>
                <span className="settings-value">
                  {row.value || <span className="settings-empty">(not set)</span>}
                </span>
              </div>
            ))}
          </div>
          {savedNotice && <p className="saved">Settings saved.</p>}
        </section>
      )}
    </section>
  );
}
