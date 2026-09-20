import { FormEvent, useEffect, useRef, useState } from "react";
import { MessagesSquare, Send } from "lucide-react";
import { api, type ChatMessage, type ResearchResult } from "../api";

/**
 * NotebookLM-style Q&A over one finished research task (ADR-0050).
 *
 * Layout: the conversation card in the middle (message stream above, input
 * bar at the bottom) with the reference sources card on the right. Sources
 * are checkboxes — the checked set is sent with every message and narrows
 * the grounding context server-side. History persists in the task folder,
 * so opening the chat again reloads the conversation.
 */
const MAX_IMPORTED_SOURCES = 50;

export function ChatPanel({ result }: { result: ResearchResult }) {
  const sources = result.curator_output?.sources ?? [];
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // R-283: references enter the grounding context only via explicit import —
  // nothing is grounded until the user picks sources and clicks Import.
  const [imported, setImported] = useState<Set<string>>(() => new Set());
  const [checked, setChecked] = useState<Set<string>>(() => new Set());
  const streamRef = useRef<HTMLDivElement>(null);

  const importable = checked.size + imported.size <= MAX_IMPORTED_SOURCES;
  const canSend = imported.size > 0;

  // Best-effort history reload: a failed fetch just starts a fresh chat.
  useEffect(() => {
    let cancelled = false;
    api
      .chatHistory(result.task_id)
      .then((response) => {
        if (!cancelled) setMessages(response.messages ?? []);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [result.task_id]);

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    streamRef.current?.scrollTo?.({ top: streamRef.current.scrollHeight });
  }, [messages, sending]);

  function toggleChecked(sourceId: string) {
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(sourceId)) next.delete(sourceId);
      else next.add(sourceId);
      return next;
    });
  }

  function importChecked() {
    if (!importable || checked.size === 0) return;
    setImported((current) => new Set([...current, ...checked]));
    setChecked(new Set());
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    const message = input.trim();
    if (!message || sending || !canSend) return;
    setSending(true);
    setError(null);
    setInput("");
    try {
      const response = await api.sendChat(result.task_id, message, [...imported]);
      setMessages((current) => [
        ...current,
        { role: "user", content: message },
        { role: "assistant", content: response.reply },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setInput(message); // restore the draft so nothing is lost
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="chat-section" aria-label="Chat with this research">
      <div className="chat-layout">
        <article className="card chat-panel">
          <h2>
            <MessagesSquare size={16} aria-hidden="true" />
            Chat with this research
          </h2>
          <div className="chat-stream" ref={streamRef}>
            {messages.length === 0 && !sending && (
              <p className="chat-empty">
                {canSend
                  ? "Ask a follow-up question about this research — answers are grounded in the imported references."
                  : "Import references on the right first — answers are grounded only in what you import."}
              </p>
            )}
            {messages.map((message, index) => (
              <div key={index} className={`chat-bubble ${message.role}`}>
                {message.content}
              </div>
            ))}
            {sending && <div className="chat-bubble assistant pending">Thinking…</div>}
          </div>
          {error && <p className="status failed">{error}</p>}
          <form className="chat-input" onSubmit={send}>
            <input
              aria-label="Chat message"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder={canSend ? "Ask about this research…" : "Import references first…"}
              disabled={sending}
            />
            <button type="submit" disabled={sending || !input.trim() || !canSend}>
              <Send size={15} aria-hidden="true" />
              {sending ? "Thinking…" : "Send"}
            </button>
          </form>
        </article>
        {sources.length > 0 && (
          <aside className="card chat-sources">
            <h2>References</h2>
            <p className="card-note">
              Select references and import them — the chat is grounded only in imported ones ({imported.size}/{MAX_IMPORTED_SOURCES} imported).
            </p>
            <button
              type="button"
              className="chat-import-btn"
              onClick={importChecked}
              disabled={checked.size === 0 || !importable}
            >
              {checked.size === 0
                ? "Import selected"
                : !importable
                  ? `Import limit (${MAX_IMPORTED_SOURCES - imported.size} left)`
                  : `Import ${checked.size} selected`}
            </button>
            <ul>
              {sources.map((source) => {
                const isImported = imported.has(source.source_id);
                return (
                  <li key={source.source_id} className={isImported ? "imported" : ""}>
                    <label>
                      <input
                        type="checkbox"
                        checked={isImported || checked.has(source.source_id)}
                        disabled={isImported}
                        onChange={() => toggleChecked(source.source_id)}
                      />
                      <span>{source.title}</span>
                    </label>
                    <a href={source.url} target="_blank" rel="noopener noreferrer">
                      {source.url}
                    </a>
                    {isImported && <span className="imported-badge">Imported</span>}
                  </li>
                );
              })}
            </ul>
          </aside>
        )}
      </div>
    </section>
  );
}
