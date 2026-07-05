import { expect, test } from "@playwright/test";
import { resultCards, searchUrl } from "./helpers";

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test("mobile viewport smoke: landing renders and search works", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("search-form")).toBeVisible();
  await expect(page.getByTestId("search-submit")).toBeVisible();

  await page.goto(searchUrl("BER", "ALC"));
  await expect(resultCards(page).first()).toBeVisible();

  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(390 + 1); // no horizontal overflow
});
