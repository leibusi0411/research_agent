import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Helpers for creating a mock EventSource
// ---------------------------------------------------------------------------

function createMockEventSourceClass() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mockClass: any = vi.fn((url: string) => {
    const opts: MockEventSourceOptions = mockClass._mockOpts || {};
    const { events = [], readyState = 1, fireErrorImmediately = false } = opts;
    let onmessage: ((msg: { data: string }) => void) | null = null;
    let onerror: (() => void) | null = null;

    const instance: {
      readyState: number;
      close: ReturnType<typeof vi.fn>;
      addEventListener: ReturnType<typeof vi.fn>;
      removeEventListener: ReturnType<typeof vi.fn>;
      onmessage: ((msg: { data: string }) => void) | null;
      onerror: (() => void) | null;
    } = {
      readyState,
      close: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      get onmessage() {
        return onmessage;
      },
      set onmessage(handler: ((msg: { data: string }) => void) | null) {
        onmessage = handler;
        if (handler && events.length > 0 && !fireErrorImmediately) {
          queueMicrotask(() => {
            for (const evt of events) {
              handler({ data: JSON.stringify(evt) });
            }
          });
        }
      },
      get onerror() {
        return onerror;
      },
      set onerror(handler: (() => void) | null) {
        onerror = handler;
        if (handler && fireErrorImmediately) {
          queueMicrotask(() => handler());
        }
      },
    };

    return instance;
  });

  // Static EventSource constants
  mockClass.CONNECTING = 0;
  mockClass.CLOSED = 2;
  mockClass.OPEN = 1;

  return mockClass;
}

type MockEventSourceOptions = {
  events?: Array<Record<string, unknown>>;
  readyState?: number;
  fireErrorImmediately?: boolean;
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("subscribeTaskEvents — SSE-first architecture (S2)", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function stubEventSource(opts: MockEventSourceOptions = {}) {
    const MockES = createMockEventSourceClass();
    MockES._mockOpts = opts;
    vi.stubGlobal("EventSource", MockES);
    return MockES;
  }

  it("calls onResult when task_result event is received", async () => {
    const MockES = stubEventSource({
      events: [
        {
          task_id: "t1",
          mode: "web",
          phase: "web_planning",
          event_type: "started",
          created_at: "2026-01-01T00:00:00Z",
          message: "Planning started.",
          details: { items: [] },
        },
        {
          task_id: "t1",
          mode: "web",
          phase: "web_curation",
          event_type: "task_result",
          created_at: "2026-01-01T00:01:00Z",
          message: "Task completed.",
          details: {
            items: [{ kind: "status", task_id: "t1", status: "completed", mode: "web" }],
          },
        },
      ],
    });

    const { subscribeTaskEvents } = await import("../src/api");

    const onEvent = vi.fn();
    const onResult = vi.fn();
    const onError = vi.fn();

    subscribeTaskEvents("t1", onEvent, onResult, onError);

    // Wait for microtasks to flush
    await vi.waitFor(() => expect(onResult).toHaveBeenCalledTimes(1));

    // onResult should be called with the task_result event
    const resultArg = onResult.mock.calls[0][0];
    expect(resultArg.event_type).toBe("task_result");
    expect(resultArg.details.items[0].status).toBe("completed");

    // onEvent should have been called for the first event
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent.mock.calls[0][0].event_type).toBe("started");

    // onError should NOT be called
    expect(onError).not.toHaveBeenCalled();

    // EventSource should be closed after task_result
    const instances = (MockES as unknown as ReturnType<typeof vi.fn>).mock.results;
    expect(instances.length).toBeGreaterThan(0);
    expect(instances[0].value.close).toHaveBeenCalled();
  });

  it("calls onError only on permanent close (readyState === CLOSED)", async () => {
    stubEventSource({
      readyState: 2, // CLOSED
      fireErrorImmediately: true,
    });

    const { subscribeTaskEvents } = await import("../src/api");

    const onEvent = vi.fn();
    const onResult = vi.fn();
    const onError = vi.fn();

    subscribeTaskEvents("t1", onEvent, onResult, onError);

    await vi.waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onEvent).not.toHaveBeenCalled();
    expect(onResult).not.toHaveBeenCalled();
  });

  it("does NOT call onError when readyState is CONNECTING (auto-retry)", async () => {
    stubEventSource({
      readyState: 0, // CONNECTING
      fireErrorImmediately: true,
    });

    const { subscribeTaskEvents } = await import("../src/api");

    const onEvent = vi.fn();
    const onResult = vi.fn();
    const onError = vi.fn();

    subscribeTaskEvents("t1", onEvent, onResult, onError);

    // Wait a tick to ensure any async handlers have fired
    await new Promise((resolve) => setTimeout(resolve, 10));

    // onError should NOT be called for CONNECTING state
    expect(onError).not.toHaveBeenCalled();
  });

  it("handles stream_timeout event by calling onError", async () => {
    const MockES = stubEventSource({
      events: [
        {
          task_id: "t1",
          mode: "web",
          phase: "web_execution",
          event_type: "stream_timeout",
          created_at: "2026-01-01T00:30:00Z",
          message: "Stream timed out after 30 minutes.",
          details: { items: [] },
        },
      ],
    });

    const { subscribeTaskEvents } = await import("../src/api");

    const onEvent = vi.fn();
    const onResult = vi.fn();
    const onError = vi.fn();

    subscribeTaskEvents("t1", onEvent, onResult, onError);

    await vi.waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onResult).not.toHaveBeenCalled();
  });

  it("unsubscribe function closes the EventSource", async () => {
    const MockES = stubEventSource({ events: [] });

    const { subscribeTaskEvents } = await import("../src/api");

    const unsubscribe = subscribeTaskEvents("t1", vi.fn(), vi.fn(), vi.fn());
    unsubscribe();

    const instances = (MockES as unknown as ReturnType<typeof vi.fn>).mock.results;
    expect(instances.length).toBeGreaterThan(0);
    expect(instances[0].value.close).toHaveBeenCalled();
  });

  it("returns a working unsubscribe function even when EventSource constructor throws", async () => {
    // Simulate EventSource constructor failure (e.g., network unavailable)
    vi.stubGlobal(
      "EventSource",
      vi.fn(() => {
        throw new Error("Network error");
      }) as unknown as typeof EventSource,
    );

    const { subscribeTaskEvents } = await import("../src/api");

    const onError = vi.fn();
    // Should not throw — errors are caught internally
    const unsubscribe = subscribeTaskEvents("t1", vi.fn(), vi.fn(), onError);

    // unsubscribe should be a no-op function that doesn't throw
    expect(() => unsubscribe()).not.toThrow();
    // onError should have been called since construction failed
    expect(onError).toHaveBeenCalled();
  });
});
