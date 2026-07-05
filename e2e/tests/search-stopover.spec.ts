import { expect, test } from "@playwright/test";
import { cardTotalCents, resultCards, searchUrl } from "./helpers";

test("BER->BKK: stopover route beats direct and is verified", async ({ page }) => {
  await page.goto(searchUrl("BER", "BKK"));
  const cards = resultCards(page);
  await expect(cards.first()).toBeVisible();

  const best = cards.first();
  await expect(best).toContainText("DXB"); // cheapest is the BER->DXB->BKK combo
  await expect(best.getByTestId("verified-badge")).toBeVisible();

  const direct = cards.filter({ hasNotText: "DXB" }).first();
  await expect(direct).toBeVisible();
  expect(await cardTotalCents(best)).toBeLessThan(await cardTotalCents(direct));

  await expect(page.getByTestId("savings-banner")).toBeVisible();
});
