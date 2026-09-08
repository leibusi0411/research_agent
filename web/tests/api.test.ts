import { describe, expect, it, vi } from "vitest";
import { api, parseSseEvents } from "../src/api";

describe("api client helpers", () => {
  it("parses SSE data blocks into progress events", () => {
    const events = parseSseEvents(
      'data: {"task_id":"task_20260624_000000_abcdef","mode":"web","phase":"web_planning","event_type":"completed","created_at":"now","message":"done","details":{"items":[]}}\n\n'
    );

    expect(events).toHaveLength(1);
    expect(events[0].phase).toBe("web_planning");
  });

  it("depositTask posts to the deposit endpoint and returns the vault path", async () => {
    const calls: Array<{ url: string; method?: string }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), method: init?.method });
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ task_id: "task_20260624_000000_abcdef", vault_path: "D:/vault/web-research/report.md" })
      };
    }));

    const result = await api.depositTask("task_20260624_000000_abcdef");

    expect(calls).toEqual([{ url: "/api/tasks/task_20260624_000000_abcdef/deposit", method: "POST" }]);
    expect(result.vault_path).toBe("D:/vault/web-research/report.md");
  });

  it("depositTask surfaces the backend error code", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 409,
      text: async () => JSON.stringify({ error: { code: "already_deposited", message: "Already deposited." } })
    })));

    await expect(api.depositTask("task_20260624_000000_abcdef")).rejects.toThrow("[already_deposited] Already deposited.");
  });
});

describe("subscribeTaskEvents", () => {
  class StubEventSource {
    static instances: StubEventSource[] = [];
    onmessage: ((msg: { data: string }) => void) | null = null;
    onerror: (() => void) | null = null;
    readyState = 1; // OPEN
    closed = false;
    constructor() {
      StubEventSource.instances.push(this);
    }
    close() {
      this.closed = true;
    }
  }

  function installStub() {
    StubEventSource.instances = [];
    vi.stubGlobal("EventSource", StubEventSource as unknown as typeof EventSource);
    const globals = EventSource as unknown as Record<string, number>;
    globals.CONNECTING = 0;
    globals.OPEN = 1;
    globals.CLOSED = 2;
  }

  function frame(seq: number | null, message: string) {
    const event: Record<string, unknown> = { task_id: "task_x", mode: "web", phase: "web_planning", event_type: "progress", message, created_at: "now", details: { items: [] } };
    if (seq !== null) event.seq = seq;
    return { data: JSON.stringify(event) };
  }

  it("reconnects after a stalled stream and dedupes replayed frames", async () => {
    vi.useFakeTimers();
    try {
      installStub();
      const { subscribeTaskEvents } = await import("../src/api");
      const seen: Array<number | null> = [];
      const stop = subscribeTaskEvents(
        "task_20260908_000000_stallxx",
        (event) => seen.push(event.seq ?? null),
        () => {},
        () => {}
      );

      const first = StubEventSource.instances[0];
      first.onmessage!(frame(1, "first"));
      first.onmessage!(frame(2, "second"));
      expect(seen).toEqual([1, 2]);

      // Stream stalls: after the watchdog timeout the stream is reconnected.
      await vi.advanceTimersByTimeAsync(45_001);
      expect(StubEventSource.instances.length).toBe(2);
      expect(first.closed).toBe(true);

      // The fresh stream replays history: duplicates are skipped, new frames pass.
      const second = StubEventSource.instances[1];
      second.onmessage!(frame(null, "Task started."));
      second.onmessage!(frame(1, "first replay"));
      second.onmessage!(frame(2, "second replay"));
      second.onmessage!(frame(3, "third"));
      expect(seen).toEqual([1, 2, 3]);

      stop();
      expect(StubEventSource.instances[1].closed).toBe(true);
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });
});
