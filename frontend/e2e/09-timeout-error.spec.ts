/**
 * E2E 9 — Provider timeout is shown as an error state.
 *
 * Uses a Playwright route-intercept to point a specific request to an
 * unreachable host with a short timeout. The frontend's ApiError
 * conversion should surface a "请求超时" or "网络不可达" error.
 */
import { test, expect } from "./fixtures";

test("9. provider timeout surfaces error state", async ({ page, api }) => {
  // Intercept the knowledge search endpoint and force a timeout by
  // using a route that hangs (delay 20s, exceeding the 12s client
  // timeout).
  await page.route("**/api/knowledge/search**", async (route) => {
    // Never fulfill the request — the client will time out.
    await new Promise((r) => setTimeout(r, 20_000));
    await route.fulfill({ status: 200, body: "{}" });
  });

  await page.goto("/knowledge");
  const wsFirst = page.locator('[data-testid^="ws-"]').first();
  await wsFirst.waitFor({ state: "visible", timeout: 8_000 });
  await wsFirst.click();

  // Trigger the search.
  await page.getByTestId("knowledge-search-input").fill("OSPF");
  await page.getByTestId("btn-knowledge-search").click();

  // Wait for the error to render (client timeout 12s + a bit).
  const err = page.getByTestId("knowledge-search-error");
  await expect(err).toBeVisible({ timeout: 20_000 });
});
