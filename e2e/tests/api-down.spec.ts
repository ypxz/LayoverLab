import { expect, test } from "@playwright/test";
import { searchUrl } from "./helpers";

test("API down: search shows a friendly error with retry", async ({ page }) => {
  await page.route("**/api/search", (route) => route.abort("connectionrefused"));
  await page.goto(searchUrl("BER", "ALC"));

  await expect(page.getByTestId("search-error")).toBeVisible();
  await expect(page.getByTestId("retry-search")).toBeVisible();

  // restoring the API and retrying recovers
  await page.unroute("**/api/search");
  await page.getByTestId("retry-search").click();
  await expect(page.getByTestId("result-card").first()).toBeVisible();
});
