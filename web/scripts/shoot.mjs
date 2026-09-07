// Screenshot tool for design iteration. Starts a vite dev server on a
// throwaway port, mocks the API (same shapes as tests/e2e/app.spec.ts),
// and captures the main pages into web/test-results/shots/.
//
// Usage: node scripts/shoot.mjs
import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const PORT = 5199;
const BASE = `http://127.0.0.1:${PORT}`;
const WEB_DIR = fileURLToPath(new URL("..", import.meta.url));
const OUT_DIR = fileURLToPath(new URL("../test-results/shots", import.meta.url));

const webTaskId = "task_20260624_000001_bbbbbb";
const localTaskId = "task_20260624_000000_aaaaaa";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function localResult(status) {
  return {
    task_id: localTaskId,
    mode: "local",
    question: "What does ADR-0036 say about running local and web independently?",
    status,
    local_results:
      status === "completed"
        ? [
            {
              text: "Local RAG and Web Research run as independent task families with separate locks; neither blocks the other, and each has its own history, events, and result views.",
              source_path: "D:/vault/docs/adr/0036-independent-workflows.md",
              heading_path: ["ADR-0036", "Decision"],
            },
            {
              text: "A `both` CLI command exists only as a convenience wrapper that creates one Local task and one Web task; there is no parent task.",
              source_path: "D:/vault/docs/adr/0036-independent-workflows.md",
              heading_path: ["ADR-0036", "Consequences"],
            },
          ]
        : [],
  };
}

function webResult(status) {
  return {
    task_id: webTaskId,
    mode: "web",
    question: "How do agent skill systems avoid generic-looking UI output?",
    status,
    curator_output:
      status === "completed"
        ? {
            title: "Skills",
            summary:
              "Current guidance skills push against three clustered default looks and require an explicit, per-brief token system before any code is written.",
            findings: [
              { finding_id: "f_1", subtask_id: "st_1", text: "Design skills frame the model as a design lead with a distinctive point of view, and ask for one justified aesthetic risk per brief.", source_ids: ["src_1"] },
              { finding_id: "f_2", subtask_id: "st_1", text: "Typography and copy are treated as design material: paired display/body faces, active voice, controls that say exactly what they do.", source_ids: ["src_2"] },
            ],
            sources: [
              { source_id: "src_1", title: "Frontend Design skill", url: "https://example.com/skills/frontend-design", fetched_at: "now" },
              { source_id: "src_2", title: "Writing in design", url: "https://example.com/writing", fetched_at: "now" },
            ],
          }
        : undefined,
    report_path: status === "completed" ? "D:/reports/web/agent-skills-ui.md" : undefined,
  };
}

const webEvents = [
  { task_id: webTaskId, mode: "web", phase: "web_planning", event_type: "progress", created_at: "now", message: "Prior knowledge: 2 local chunks injected into the planner.", details: { items: [{ kind: "source", path: "D:/vault/docs/adr/0046-prior-knowledge.md", title: "ADR-0046" }] } },
  { task_id: webTaskId, mode: "web", phase: "web_planning", event_type: "completed", created_at: "now", message: "Initial plan created: 3 subtasks.", details: { items: [] } },
  { task_id: webTaskId, mode: "web", phase: "web_execution", event_type: "progress", created_at: "now", message: "Subtask st_1 finished.", details: { items: [{ kind: "tool_call", name: "web_search", input: "agent skill design guidance" }, { kind: "source", url: "https://example.com/skills/frontend-design", title: "Frontend Design skill" }, { kind: "finding", text: "Design skills frame the model as a design lead with a distinctive point of view.", subtask_id: "st_1" }] } },
  { task_id: webTaskId, mode: "web", phase: "web_supervision", event_type: "completed", created_at: "now", message: "Supervisor: coverage sufficient, no revision needed.", details: { items: [] } },
  { task_id: webTaskId, mode: "web", phase: "web_curation", event_type: "task_result", created_at: "now", message: "Task completed.", details: { items: [] } },
];

const localEvents = [
  { task_id: localTaskId, mode: "local", phase: "local_rag", event_type: "completed", created_at: "now", message: "Local RAG completed: 2 chunks retrieved.", details: { items: [] } },
  { task_id: localTaskId, mode: "local", phase: "local_rag", event_type: "task_result", created_at: "now", message: "Task completed.", details: { items: [] } },
];

async function mockApi(page, { configured = true, delayWebResult = false } = {}) {
  const finishedTasks = [
    { task_id: webTaskId, mode: "web", status: "completed", title_or_question: "How do agent skill systems avoid generic-looking UI output?", created_at: "2026-06-24T00:00:01Z" },
    { task_id: localTaskId, mode: "local", status: "completed", title_or_question: "What does ADR-0036 say about running local and web independently?", created_at: "2026-06-24T00:00:00Z" },
  ];
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (url.endsWith("/api/setup/status")) return route.fulfill({ json: { configured } });
    if (url.endsWith("/api/tasks/finished")) return route.fulfill({ json: { tasks: finishedTasks } });
    if (url.endsWith("/api/kb/status") || url.endsWith("/api/kb/rebuild")) {
      return route.fulfill({ json: { status: "ready", vault_path: "D:/vault", file_count: 42, chunk_count: 317, last_indexed_at: "2026-09-07T08:30:00Z" } });
    }
    if (url.endsWith("/api/research/local") && method === "POST") return route.fulfill({ json: localResult("completed") });
    if (url.endsWith("/api/research/web") && method === "POST") return route.fulfill({ json: webResult("running") });
    if (url.endsWith(`/api/tasks/${localTaskId}/result`)) return route.fulfill({ json: localResult("completed") });
    if (url.endsWith(`/api/tasks/${localTaskId}/events`)) return route.fulfill({ json: localEvents });
    if (url.endsWith(`/api/tasks/${webTaskId}/result`)) {
      if (delayWebResult) await sleep(6000);
      return route.fulfill({ json: webResult("completed") });
    }
    if (url.endsWith(`/api/tasks/${webTaskId}/events`)) {
      const accept = route.request().headers()["accept"] ?? "";
      if (accept.includes("text/event-stream")) {
        const body = webEvents.map((event) => `data: ${JSON.stringify(event)}`).join("\n\n") + "\n\n";
        return route.fulfill({ contentType: "text/event-stream", body });
      }
      return route.fulfill({ json: webEvents });
    }
    if (url.endsWith(`/api/tasks/${webTaskId}/deposit`) && method === "POST") {
      return route.fulfill({ json: { task_id: webTaskId, vault_path: "D:/vault/web-research/agent-skills-ui.md" } });
    }
    return route.fulfill({ status: 404, json: {} });
  });
}

async function waitForServer() {
  for (let i = 0; i < 60; i += 1) {
    try {
      const res = await fetch(BASE);
      if (res.ok) return;
    } catch {
      // not up yet
    }
    await sleep(500);
  }
  throw new Error("vite dev server did not start");
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const server = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--port", String(PORT), "--strictPort", "--host", "127.0.0.1"], {
    cwd: WEB_DIR,
    stdio: "ignore",
  });
  let browser;
  try {
    await waitForServer();
    browser = await chromium.launch({ channel: "chrome" });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
    page.on("dialog", (dialog) => dialog.accept());

    // 1. Setup page
    await mockApi(page, { configured: false });
    await page.goto(BASE, { waitUntil: "networkidle" });
    await page.screenshot({ path: `${OUT_DIR}/01-setup.png` });

    // 2. Research page, empty
    await mockApi(page);
    await page.reload({ waitUntil: "networkidle" });
    await page.screenshot({ path: `${OUT_DIR}/02-research.png` });

    // 3. Research page with both results
    await page.getByRole("textbox", { name: "Local RAG question" }).fill("What does ADR-0036 say about running local and web independently?");
    await page.getByRole("button", { name: "Run Local" }).click();
    await page.getByRole("textbox", { name: "Web research question" }).fill("How do agent skill systems avoid generic-looking UI output?");
    await page.getByRole("button", { name: "Run Web" }).click();
    await page.getByText("Current guidance skills push against").waitFor();
    await page.screenshot({ path: `${OUT_DIR}/03-research-results.png`, fullPage: true });

    // 4. Running state: fresh page (no prior result), web result endpoint
    // delayed so events stream while the task is still running.
    await mockApi(page, { delayWebResult: true });
    await page.goto(BASE, { waitUntil: "networkidle" });
    await page.getByRole("textbox", { name: "Web research question" }).fill("What is new in agent tooling this week?");
    await page.getByRole("button", { name: "Run Web" }).click();
    await page.locator(".phase-indicator").waitFor();
    await page.getByText("Initial plan created").waitFor();
    await sleep(500);
    await page.screenshot({ path: `${OUT_DIR}/04-research-running.png`, fullPage: true });

    // 5. Tasks page with a web result open (process trace + deposit)
    await mockApi(page);
    await page.getByRole("link", { name: "Tasks" }).click();
    await page.getByRole("button", { name: new RegExp(webTaskId) }).click();
    await page.getByRole("heading", { name: "Web Report" }).waitFor();
    await page.screenshot({ path: `${OUT_DIR}/05-tasks-web.png`, fullPage: true });

    // 6. Tasks page with a local result open
    await page.getByRole("button", { name: new RegExp(localTaskId) }).click();
    await page.getByRole("heading", { name: "Local Result" }).waitFor();
    await page.screenshot({ path: `${OUT_DIR}/06-tasks-local.png`, fullPage: true });

    // 7. KB page
    await page.getByRole("link", { name: "Knowledge Base" }).click();
    await page.getByRole("heading", { name: "Knowledge Base Index" }).waitFor();
    await page.screenshot({ path: `${OUT_DIR}/07-kb.png` });

    console.log(`shots written to ${OUT_DIR}`);
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
