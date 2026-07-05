import type { AirportOut } from "@/lib/api";

const KEY = "layoverlab.recentAirports";
const MAX = 5;

export function getRecentAirports(): AirportOut[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (a): a is AirportOut =>
        typeof a === "object" && a !== null && typeof (a as AirportOut).iata === "string",
    );
  } catch {
    return [];
  }
}

export function addRecentAirport(airport: AirportOut): void {
  if (typeof window === "undefined") return;
  try {
    const next = [airport, ...getRecentAirports().filter((a) => a.iata !== airport.iata)].slice(
      0,
      MAX,
    );
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // localStorage unavailable (private mode) — recents are best-effort
  }
}
