import { expect, test } from "@playwright/test";
import { cardTotalCents, e2eMonth, isoMonth, resultCards, runStackScript, searchUrl } from "./helpers";

const STALE_CENTS = 20000; // seeded by scripts/seed_stack.py
const FRESH_CENTS = 9000;

test("cold route: SSE update events improve the visible list", async ({ page }) => {
  await page.goto(searchUrl("MUC", "ALC"));
  const cards = resultCards(page);
  await expect(cards.first()).toBeVisible();
  expect(await cardTotalCents(cards.first())).toBe(STALE_CENTS);
  await expect(page.getByTestId("status-strip")).toBeVisible(); // stream still open, waiting on crawl

  // fresh, cheaper fares land mid-stream (as if the crawler just finished)
  runStackScript("inject_fares.py", ["MUC", "ALC", isoMonth(e2eMonth()), String(FRESH_CENTS)]);

  await expect(page.getByTestId("updated-notice")).toBeVisible({ timeout: 20_000 });
  await expect
    .poll(async () => cardTotalCents(cards.first()), { timeout: 20_000 })
    .toBe(FRESH_CENTS);
});
