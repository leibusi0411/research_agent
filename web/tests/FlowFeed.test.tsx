import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FlowFeed } from "../src/components/FlowFeed";
import type { ProgressEvent } from "../src/api";

function ev(partial: Partial<ProgressEvent>): ProgressEvent {
  return {
    task_id: "t",
    mode: "web",
    phase: "web_execution",
    event_type: "progress",
    message: "",
    created_at: "now",
    details: { items: [] },
    ...partial,
  } as ProgressEvent;
}

describe("FlowFeed", () => {
  it("streams rows for subtasks, tool calls, findings, and sources", () => {
    const events = [
      ev({ phase: "web_planning", event_type: "completed", details: { items: [
        { kind: "subtask", subtask_id: "st_1", question: "What is A2A?" },
      ] } }),
      ev({ details: { items: [
        { kind: "tool_call", name: "web.search", input: "a2a protocol" },
        { kind: "source", title: "A2A docs", url: "https://a2a-protocol.org" },
        { kind: "finding", text: "A2A is an open protocol.", subtask_id: "st_1" },
      ] } }),
    ];

    render(<FlowFeed events={events} running={true} />);

    expect(screen.getByText("What is A2A?")).toBeInTheDocument();
    expect(screen.getByText("web.search")).toBeInTheDocument();
    expect(screen.getByText("A2A docs")).toBeInTheDocument();
    expect(screen.getByText("A2A is an open protocol.")).toBeInTheDocument();
  });

  it("expands tool call detail on chip click and collapses on second click", async () => {
    const events = [
      ev({ details: { items: [{ kind: "tool_call", name: "web.fetch_extract", input: "https://example.com/page" }] } }),
    ];
    render(<FlowFeed events={events} running={true} />);

    const chip = screen.getByRole("button", { name: /web\.fetch_extract/i });
    expect(screen.queryByText("https://example.com/page")).not.toBeInTheDocument();

    await userEvent.click(chip);
    expect(screen.getByText("https://example.com/page")).toBeInTheDocument();

    await userEvent.click(chip);
    expect(screen.queryByText("https://example.com/page")).not.toBeInTheDocument();
  });

  it("shows subtask completion rows with outcome summary", () => {
    const events = [
      ev({ details: { items: [{ kind: "subtask_completed", question: "What is A2A?", status: "completed", finding_count: 3, source_count: 2 }] } }),
    ];
    render(<FlowFeed events={events} running={true} />);

    expect(screen.getByText("✓ What is A2A?")).toBeInTheDocument();
  });

  it("renders an empty state while waiting for activity", () => {
    render(<FlowFeed events={[]} running={true} />);
    expect(screen.getByText(/waiting for activity/i)).toBeInTheDocument();
  });
});
