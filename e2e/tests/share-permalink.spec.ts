import { expect, test } from "@playwright/test";
import { resultCards, searchUrl } from "./helpers";

test("share -> permalink roundtrip renders the same total", async ({ page }) => {
  await page.goto(searchUrl("BER", "ALC"));
  const first = resultCards(page).first();
  await expect(first).toBeVisible();
  const total = (await first.getByTestId("route-total").innerText()).trim();

  await first.getByTestId("share-button").click();
  let url = "";
  await expect
    .poll(async () => {
      url = await page.evaluate(() => navigator.clipboard.readText());
      return url;
    })
    .toMatch(/\/r\/[\w-]+/);

  await page.goto(url);
  const root = page.getByTestId("permalink-root");
  await expect(root).toBeVisible();
  await expect(root).toContainText(total);
  await expect(root.getByTestId("verified-badge")).toBeVisible();
});
