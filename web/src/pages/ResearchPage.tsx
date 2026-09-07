import { FormEvent } from "react";
import { Search } from "lucide-react";
import { type ProgressEvent, type ResearchResult } from "../api";
import { ResultCards, TraceCard } from "../components/ResultView";

export function ResearchPage({
  question,
  setQuestion,
  runResearch,
  busy,
  result,
  events,
  phase,
}: {
  question: string;
  setQuestion: (value: string) => void;
  runResearch: (event: FormEvent) => void;
  busy: string | null;
  result: ResearchResult | null;
  events: ProgressEvent[];
  phase: string | null;
}) {
  // Running = request in flight, or events streaming in with no result yet.
  const running = busy === "web" || (events.length > 0 && !result);
  const hasContent = events.length > 0 || result !== null;

  return (
    <section className={hasContent ? "research-page has-content" : "research-page"}>
      <header className="hero">
        <h1 className="hero-title">Inkwell</h1>
        <p className="hero-sub">
          Ask once — the agent checks your notes, plans, searches the web, and writes the report.
        </p>
      </header>
      <form className="search-bar" onSubmit={runResearch}>
        <Search size={18} aria-hidden="true" />
        <input
          aria-label="Research question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="What do you want to research?"
          disabled={running}
          required
        />
        <button type="submit" disabled={running}>
          {running ? "Researching…" : "Research"}
        </button>
      </form>
      {events.length > 0 && <TraceCard events={events} phase={phase} running={running} />}
      {result && <ResultCards result={result} events={events} />}
    </section>
  );
}
