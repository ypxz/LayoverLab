import { expect, test } from "@playwright/test";
import { resultCards, searchUrl } from "./helpers";

test("filters narrow the result list", async ({ page }) => {
  await page.goto(searchUrl("BER", "BKK"));
  const cards = resultCards(page);
  await expect(cards.first()).toBeVisible();
  await expect(page.getByTestId("filters-bar")).toBeVisible();

  const before = await cards.count();
  expect(before).toBeGreaterThanOrEqual(2);

  // max stops -> 0: only the direct BER->BKK card should remain
  const maxStops = page.getByTestId("filters-bar").getByRole("slider").first();
  await maxStops.click();
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowLeft");

  await expect.poll(() => cards.count()).toBeLessThan(before);
  const after = await cards.count();
  for (let i = 0; i < after; i++) {
    await expect(cards.nth(i)).not.toContainText("DXB");
  }

  // relax again: full list returns
  await maxStops.click();
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowRight");
  await expect.poll(() => cards.count()).toBe(before);
});
