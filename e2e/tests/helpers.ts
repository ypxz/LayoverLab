import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import * as path from "node:path";
import type { Locator, Page } from "@playwright/test";

const ROOT = path.resolve(__dirname, "..", "..");

/** First day of the E2E search month (matches scripts/seed_stack.py). */
export function e2eMonth(): Date {
  const raw = process.env.E2E_MONTH;
  if (raw) {
    const [y, m] = raw.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, 1));
  }
  const today = new Date();
  const shifted = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1 + 62));
  return new Date(Date.UTC(shifted.getUTCFullYear(), shifted.getUTCMonth(), 1));
}

export function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function isoMonth(d: Date): string {
  return d.toISOString().slice(0, 7);
}

/** Shareable search URL for a window starting at the E2E month. */
export function searchUrl(origin: string, dest: string, windowDays = 6): string {
  const from = e2eMonth();
  const to = new Date(from.getTime() + windowDays * 86_400_000);
  const q = new URLSearchParams({
    from: origin,
    to: dest,
    depart: isoDate(from),
    return: isoDate(to),
  });
  return `/?${q.toString()}`;
}

/** Parses a formatted money string (e.g. "€330" or "€29.25") into cents. */
export function moneyToCents(text: string): number {
  const match = text.replace(/,/g, "").match(/([\d]+(?:\.\d+)?)/);
  if (!match) throw new Error(`no money value in: ${text}`);
  return Math.round(parseFloat(match[1]) * 100);
}

export async function cardTotalCents(card: Locator): Promise<number> {
  const text = await card.getByTestId("route-total").innerText();
  return moneyToCents(text);
}

export function resultCards(page: Page): Locator {
  return page.getByTestId("result-card");
}

function pythonBin(): string {
  if (process.env.E2E_PYTHON) return process.env.E2E_PYTHON;
  const venv = path.join(ROOT, "server", ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python";
}

/** Runs a python helper from e2e/scripts against the stack's SQLite DB. */
export function runStackScript(script: string, args: string[]): void {
  const dbPath = path.join(ROOT, "e2e", ".stack", "layoverlab-e2e.sqlite3");
  execFileSync(pythonBin(), [path.join(ROOT, "e2e", "scripts", script), ...args], {
    env: { ...process.env, DATABASE_URL: `sqlite:///${dbPath}` },
    cwd: path.join(ROOT, "server"),
    stdio: "inherit",
  });
}
