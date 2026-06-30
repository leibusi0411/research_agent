import { useEffect, useRef, useState } from "react";
import { type ProgressEvent } from "../api";
import { DetailItem } from "./DetailItem";

export function ProcessView({ groupedEvents, newestSeq }: { groupedEvents: Record<string, ProgressEvent[]>; newestSeq?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const userScrolledUp = useRef(false);
  const [seenSeqs, setSeenSeqs] = useState<Set<number>>(new Set());

  // Track which _seq values have been seen, mark new ones for animation
  const getSeqClass = (event: ProgressEvent): string => {
    if (event._seq === undefined) return "";
    if (seenSeqs.has(event._seq)) return "";
    return "event-enter";
  };

  // Mark current _seq values as seen after render
  useEffect(() => {
    const seqs = new Set<number>();
    for (const phaseEvents of Object.values(groupedEvents)) {
      for (const event of phaseEvents) {
        if (event._seq !== undefined) seqs.add(event._seq);
      }
    }
    setSeenSeqs(seqs);
  }, [newestSeq]);

  // Auto-scroll to bottom on new events, unless user scrolled up
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    if (!userScrolledUp.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [newestSeq]);

  function handleScroll() {
    const el = containerRef.current;
    if (!el) return;
    // If user is within 40px of bottom, consider them "at bottom"
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    userScrolledUp.current = !atBottom;
  }

  if (Object.keys(groupedEvents).length === 0) {
    return null;
  }
  return (
    <div className="process" ref={containerRef} onScroll={handleScroll}>
      {Object.entries(groupedEvents).map(([phase, phaseEvents]) => (
        <section key={phase}>
          <h3>{phase}</h3>
          {phaseEvents.map((event, idx) => (
            <div key={event._seq ?? `${event.created_at}-${idx}`} className={getSeqClass(event)}>
              <p className="event-message">{event.message}</p>
              {event.details?.items?.length > 0 && (
                <ul className="event-items">
                  {event.details.items.map((item, idx) => (
                    <DetailItem key={idx} item={item} />
                  ))}
                </ul>
              )}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

export function groupEvents(events: ProgressEvent[]) {
  return events.reduce<Record<string, ProgressEvent[]>>((groups, event) => {
    groups[event.phase] = [...(groups[event.phase] ?? []), event];
    return groups;
  }, {});
}
