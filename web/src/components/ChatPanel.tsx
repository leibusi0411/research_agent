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
export function ChatPanel({ result }: { result: ResearchResult }) {
  const sources = result.curator_output?.sources ?? [];
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(sources.map((s) => s.source_id)));
  const streamRef = useRef<HTMLDivElement>(null);

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

  function toggleSource(sourceId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(sourceId)) next.delete(sourceId);
      else next.add(sourceId);
      return next;
    });
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    const message = input.trim();
    if (!message || sending) return;
    setSending(true);
    setError(null);
    setInput("");
    try {
      const response = await api.sendChat(result.task_id, message, [...selected]);
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
                Ask a follow-up question about this research — answers are grounded in its findings and sources.
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
              placeholder="Ask about this research…"
              disabled={sending}
            />
            <button type="submit" disabled={sending || !input.trim()}>
              <Send size={15} aria-hidden="true" />
              {sending ? "Thinking…" : "Send"}
            </button>
          </form>
        </article>
        {sources.length > 0 && (
          <aside className="card chat-sources">
            <h2>References</h2>
            <p className="card-note">Checked references ground the chat. Uncheck to narrow; leave all checked (or none) for the full set.</p>
            <ul>
              {sources.map((source) => (
                <li key={source.source_id}>
                  <label>
                    <input
                      type="checkbox"
                      checked={selected.has(source.source_id)}
                      onChange={() => toggleSource(source.source_id)}
                    />
                    <span>{source.title}</span>
                  </label>
                  <a href={source.url} target="_blank" rel="noopener noreferrer">
                    {source.url}
                  </a>
                </li>
              ))}
            </ul>
          </aside>
        )}
      </div>
    </section>
  );
}
