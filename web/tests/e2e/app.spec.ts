import { expect, test } from "@playwright/test";

const webTaskId = "task_20260624_000001_bbbbbb";
const localTaskId = "task_20260624_000000_aaaaaa";

test("setup, research, task navigation, and kb flows", async ({ page }) => {
  let configured = false;
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (url.endsWith("/api/setup/status")) {
      await route.fulfill({ json: { configured } });
      return;
    }
    if (url.endsWith("/api/setup/init")) {
      configured = true;
      await route.fulfill({ json: { configured: true, config_path: "C:/config.toml" } });
      return;
    }
    if (url.endsWith("/api/tasks/finished")) {
      await route.fulfill({
        json: {
          tasks: [
            { task_id: webTaskId, mode: "web", status: "completed", title_or_question: "web question", created_at: "2026-06-24T00:00:01Z" },
            { task_id: localTaskId, mode: "local", status: "completed", title_or_question: "local question", created_at: "2026-06-24T00:00:00Z" }
          ]
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
      await route.fulfill({
        contentType: "text/event-stream",
        body: 'data: {"task_id":"task_20260624_000000_aaaaaa","mode":"local","phase":"local_rag","event_type":"completed","created_at":"now","message":"Local RAG completed.","details":{"items":[]}}\n\n'
      });
      return;
    }
    if (url.endsWith(`/api/tasks/${webTaskId}/result`)) {
      await route.fulfill({ json: webResult("completed") });
      return;
    }
    if (url.endsWith(`/api/tasks/${webTaskId}/events`)) {
      await route.fulfill({
        contentType: "text/event-stream",
        body: 'data: {"task_id":"task_20260624_000001_bbbbbb","mode":"web","phase":"web_planning","event_type":"completed","created_at":"now","message":"Initial plan created.","details":{"items":[]}}\n\n'
      });
      return;
    }
    await route.fulfill({ status: 404, json: {} });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Research Agent Setup" })).toBeVisible();
  for (const input of await page.locator("input").all()) {
    await input.fill("x");
  }
  await page.getByRole("button", { name: "Save Config" }).click();
  await expect(page.getByRole("heading", { name: "Research", exact: true })).toBeVisible();

  await page.locator("textarea").first().fill("local question");
  await page.getByRole("button", { name: "Run Local" }).click();
  await expect(page.getByText("Local content")).toBeVisible();

  await page.locator("textarea").nth(1).fill("web question");
  await page.getByRole("button", { name: "Run Web" }).click();
  await expect(page.getByText("Web summary")).toBeVisible();
  await expect(page.getByText("web_planning")).toBeVisible();

  await page.getByRole("button", { name: "Tasks" }).click();
  await page.getByRole("button", { name: new RegExp(webTaskId) }).click();
  await expect(page.getByRole("heading", { name: "Web Report" })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(localTaskId) }).click();
  await expect(page.getByRole("heading", { name: "Local Result" })).toBeVisible();
  await expect(page.getByText("local_rag")).toBeVisible();

  await page.getByRole("button", { name: "Knowledge Base" }).click();
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
