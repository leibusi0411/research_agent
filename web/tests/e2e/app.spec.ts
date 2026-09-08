import { expect, test, type Route } from "@playwright/test";

const webTaskId = "task_20260624_000001_bbbbbb";
const localTaskId = "task_20260624_000000_aaaaaa";

// EventSource requires a real text/event-stream body; plain fetch
// (api.taskEvents on the Tasks page) expects a JSON array. Serve by Accept.
async function fulfillEvents(route: Route, events: Record<string, unknown>[]) {
  const accept = route.request().headers()["accept"] ?? "";
  if (accept.includes("text/event-stream")) {
    const body = events.map((event) => `data: ${JSON.stringify(event)}`).join("\n\n") + "\n\n";
    await route.fulfill({ contentType: "text/event-stream", body });
    return;
  }
  await route.fulfill({ json: events });
}

test("setup, research, task navigation, and kb flows", async ({ page }) => {
  let configured = false;
  let finishedTasks = [
    { task_id: webTaskId, mode: "web", status: "completed", title_or_question: "web question", created_at: "2026-06-24T00:00:01Z" },
    { task_id: localTaskId, mode: "local", status: "completed", title_or_question: "local question", created_at: "2026-06-24T00:00:00Z" }
  ];
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (url.endsWith("/api/setup/status")) {
      await route.fulfill({ json: { configured } });
      return;
    }
    if (url.endsWith("/api/setup/config")) {
      if (!configured) {
        await route.fulfill({ status: 404, json: { error: { code: "config_missing", message: "User Config not found." } } });
      } else {
        await route.fulfill({
          json: {
            default_workspace: "D:/runtime",
            knowledge_base_path: "D:/vault",
            chat_base_url: "https://models.example/v1",
            chat_model: "chat-model",
            embedding_base_url: "https://embeddings.example/v1",
            embedding_model: "embedding-model",
            chat_api_key: "",
            embedding_api_key: "",
            search_api_key: "",
            has_chat_api_key: true,
            has_embedding_api_key: true,
            has_search_api_key: true
          }
        });
      }
      return;
    }
    if (url.endsWith("/api/setup/init")) {
      configured = true;
      await route.fulfill({ json: { configured: true, config_path: "C:/config.toml" } });
      return;
    }
    if (url.endsWith("/api/tasks/active")) {
      await route.fulfill({ json: { active: [] } });
      return;
    }
    if (url.endsWith("/api/tasks/finished")) {
      await route.fulfill({
        json: {
          tasks: finishedTasks
        }
      });
      return;
    }
    if (url.endsWith("/api/kb/status") || url.endsWith("/api/kb/rebuild")) {
      await route.fulfill({ json: { status: "ready", vault_path: "D:/vault", file_count: 2, chunk_count: 4, last_indexed_at: "now" } });
      return;
    }
    if (url.endsWith("/api/research/local") && method === "POST") {
      await route.fulfill({ json: localResult("running") });
      return;
    }
    if (url.endsWith("/api/research/web") && method === "POST") {
      await route.fulfill({ json: webResult("running") });
      return;
    }
    if (url.endsWith(`/api/tasks/${localTaskId}/result`)) {
      await route.fulfill({ json: localResult("completed") });
      return;
    }
    if (url.endsWith(`/api/tasks/${localTaskId}/events`)) {
      await fulfillEvents(route, [
        { task_id: localTaskId, mode: "local", phase: "local_rag", event_type: "completed", created_at: "now", message: "Local RAG completed.", details: { items: [] } },
        { task_id: localTaskId, mode: "local", phase: "local_rag", event_type: "task_result", created_at: "now", message: "Task completed.", details: { items: [] } },
      ]);
      return;
    }
    if (url.endsWith(`/api/tasks/${webTaskId}/result`)) {
      await route.fulfill({ json: webResult("completed") });
      return;
    }
    if (url.endsWith(`/api/tasks/${webTaskId}/events`)) {
      await fulfillEvents(route, [
        { task_id: webTaskId, mode: "web", phase: "web_planning", event_type: "completed", created_at: "now", message: "Initial plan created.", details: { items: [] } },
        { task_id: webTaskId, mode: "web", phase: "web_curation", event_type: "task_result", created_at: "now", message: "Task completed.", details: { items: [] } },
      ]);
      return;
    }
    if (url.endsWith(`/api/tasks/${webTaskId}/deposit`) && method === "POST") {
      await route.fulfill({ json: { task_id: webTaskId, vault_path: "D:/vault/web-research/report.md" } });
      return;
    }
    if (url.endsWith(`/api/tasks/${webTaskId}`) && method === "DELETE") {
      finishedTasks = finishedTasks.filter((task) => task.task_id !== webTaskId);
      await route.fulfill({ json: { task_id: webTaskId, deleted: true } });
      return;
    }
    if (url.endsWith(`/api/tasks/${localTaskId}`) && method === "DELETE") {
      finishedTasks = finishedTasks.filter((task) => task.task_id !== localTaskId);
      await route.fulfill({ json: { task_id: localTaskId, deleted: true } });
      return;
    }
    await route.fulfill({ status: 404, json: {} });
  });

  // Playwright auto-dismisses dialogs by default; the delete flow needs an accept.
  page.on("dialog", (dialog) => dialog.accept());

  await page.goto("/");
  // The shell with all four pages is always visible; Research works even
  // without config, and the resident Settings page is one click away.
  await expect(page.getByRole("heading", { name: "Inkwell" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Settings" })).toBeVisible();
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  for (const input of await page.locator("input").all()) {
    await input.fill("x");
  }
  await page.getByRole("button", { name: "Save Config" }).click();
  await expect(page.getByRole("heading", { name: "Inkwell" })).toBeVisible();

  await page.getByRole("textbox", { name: "Research question" }).fill("web question");
  await page.getByRole("button", { name: "Research" }).click();
  await expect(page.getByText("Web summary")).toBeVisible();
  await expect(page.getByText("web_planning")).toBeVisible();

  await page.getByRole("link", { name: "Tasks" }).click();
  await page.getByRole("button", { name: new RegExp(webTaskId) }).click();
  await expect(page.getByRole("heading", { name: "Web Report" })).toBeVisible();

  // Knowledge Deposit: deposit the finished report, then rebuild the index.
  await page.getByRole("button", { name: "Deposit to Knowledge Base" }).click();
  await expect(page.getByText("Deposited to Knowledge Base.")).toBeVisible();
  await expect(page.getByText("D:/vault/web-research/report.md")).toBeVisible();
  await page.getByRole("button", { name: "Rebuild Index" }).click();
  await expect(page.getByText(/Index rebuilt/)).toBeVisible();

  await page.getByRole("button", { name: new RegExp(localTaskId) }).click();
  await expect(page.getByRole("heading", { name: "Local Result" })).toBeVisible();
  await expect(page.getByText("local_rag")).toBeVisible();
  await expect(page.getByRole("button", { name: "Deposit to Knowledge Base" })).toHaveCount(0);
  await page.getByRole("button", { name: "Delete task web question" }).click();
  await expect(page.getByText("web question")).toHaveCount(0);

  await page.getByRole("link", { name: "Knowledge Base" }).click();
  await expect(page.getByRole("heading", { name: "Knowledge Base Index" })).toBeVisible();
  await expect(page.getByText("D:/vault")).toBeVisible();
  await page.getByRole("button", { name: "Rebuild" }).click();
  await expect(page.getByText("ready")).toBeVisible();
});

function localResult(status: "running" | "completed") {
  return {
    task_id: localTaskId,
    mode: "local",
    question: "local question",
    status,
    local_results: status === "completed" ? [{ text: "Local content", source_path: "D:/vault/note.md", heading_path: ["API"] }] : []
  };
}

function webResult(status: "running" | "completed") {
  return {
    task_id: webTaskId,
    mode: "web",
    question: "web question",
    status,
    curator_output:
      status === "completed"
        ? {
            title: "Web",
            summary: "Web summary",
            findings: [{ finding_id: "f_1", subtask_id: "st_1", text: "Finding", source_ids: ["src_1"] }],
            sources: [{ source_id: "src_1", title: "Source", url: "https://example.com", fetched_at: "now" }]
          }
        : undefined,
    report_path: status === "completed" ? "D:/reports/web/report.md" : undefined
  };
}
