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
