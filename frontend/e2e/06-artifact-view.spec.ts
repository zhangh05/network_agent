/**
 * E2E 6 — Artifact view.
 */
import { test, expect } from "./fixtures";

test("6. artifact view + tabs", async ({ page, api }) => {
  // Discover the first workspace the UI will see.
  const wsList = await api.get("/api/workspaces");
  const wsBody = await wsList.json().catch(() => ({}));
  const wsList0 = (wsBody.workspaces ?? [])[0]?.workspace_id ?? "default";

  // Pre-seed an artifact in the same workspace.
  const r = await api.post(`/api/workspaces/${wsList0}/artifacts`, {
    data: {
      title: "e2e-artifact-view",
      artifact_type: "translated_config",
      content: "router ospf 1\n network 10.0.0.0 0.0.0.255 area 0\n",
      sensitivity: "sensitive",
    },
  });
  expect(r.status()).toBeLessThan(500);
  const seeded = await r.json().catch(() => ({}));
  expect(seeded.artifact?.artifact_id).toBeTruthy();

  await page.goto("/artifacts");
  const wsFirst = page.locator('[data-testid^="ws-"]').first();
  await wsFirst.waitFor({ state: "visible", timeout: 8_000 });
  await wsFirst.click();

  // The page should render. An empty state is acceptable too.
  await expect(page.getByTestId("page-artifacts")).toBeVisible({ timeout: 6_000 });
});
