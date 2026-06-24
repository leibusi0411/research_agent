import { describe, expect, it } from "vitest";
import { parseSseEvents } from "../src/api";

describe("api client helpers", () => {
  it("parses SSE data blocks into progress events", () => {
    const events = parseSseEvents(
      'data: {"task_id":"task_20260624_000000_abcdef","mode":"web","phase":"web_planning","event_type":"completed","created_at":"now","message":"done","details":{"items":[]}}\n\n'
    );

    expect(events).toHaveLength(1);
    expect(events[0].phase).toBe("web_planning");
  });
});
