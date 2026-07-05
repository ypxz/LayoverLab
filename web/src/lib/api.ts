export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api";

export interface AirportOut {
  iata: string;
  name: string;
  city: string;
  country_code: string;
}

export interface Leg {
  origin: string;
  dest: string;
  dep_date: string;
  mode: "flight" | "ground";
  price_cents: number;
  currency: string;
  source: string;
  deep_link: string | null;
  fetched_at: string;
  dep_time?: string | null;
  arr_time?: string | null;
}

export interface Stopover {
  iata: string;
  nights: number;
}

export interface Itinerary {
  id: string | null;
  legs: Leg[];
  total_cents: number;
  currency: string;
  stopovers: Stopover[];
  warnings: string[];
  verified: boolean;
}

export interface SearchParams {
  origin: string;
  dest: string;
  date_from: string;
  date_to: string;
  round_trip: boolean;
  trip_min_days?: number | null;
  trip_max_days?: number | null;
  stop_min_hours: number;
  stop_max_days: number;
  max_stops: number;
  top_k: number;
}

export type ZeroResultsReason =
  | "no_coverage"
  | "crawl_pending"
  | "crawl_disabled"
  | "worker_down"
  | "sources_erroring";

export interface DoneMeta {
  crawl_pending: boolean;
  searched_pairs_covered: boolean;
  worker_alive?: boolean | null;
  zero_results_reason?: ZeroResultsReason | null;
}

export interface SSEEvent {
  event: string;
  data: string;
}

/** Parses complete SSE blocks out of a buffer; returns events + leftover partial buffer. */
export function parseSSE(buffer: string): { events: SSEEvent[]; rest: string } {
  const events: SSEEvent[] = [];
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length > 0) events.push({ event, data: dataLines.join("\n") });
  }
  return { events, rest };
}

/** Client-side watchdog: the server caps streams at SEARCH_STREAM_MAX_S (60s default),
 * so a healthy stream always ends well before this. Guards against a stalled
 * connection leaving the UI spinning forever. */
export const STREAM_WATCHDOG_MS = 90_000;

export async function searchStream(
  params: SearchParams,
  onEvent: (event: string, payload: unknown) => void,
  signal?: AbortSignal,
  watchdogMs: number = STREAM_WATCHDOG_MS,
): Promise<void> {
  const resp = await fetch(`${API_BASE}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
    signal,
  });
  if (!resp.ok || !resp.body) throw new Error(`search failed: ${resp.status}`);
  const reader = resp.body.getReader();
  const watchdog = setTimeout(() => {
    void reader.cancel().catch(() => undefined);
  }, watchdogMs);
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { events, rest } = parseSSE(buffer);
      buffer = rest;
      for (const evt of events) {
        let payload: unknown = null;
        try {
          payload = JSON.parse(evt.data);
        } catch {
          payload = evt.data;
        }
        onEvent(evt.event, payload);
      }
    }
  } finally {
    clearTimeout(watchdog);
  }
}

export async function autocompleteAirports(q: string, signal?: AbortSignal): Promise<AirportOut[]> {
  if (q.trim().length < 2) return [];
  const resp = await fetch(`${API_BASE}/airports?q=${encodeURIComponent(q)}`, { signal });
  if (!resp.ok) return [];
  return resp.json();
}

export async function saveItinerary(itin: Itinerary): Promise<string> {
  const resp = await fetch(`${API_BASE}/itineraries`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(itin),
  });
  if (!resp.ok) throw new Error("could not save itinerary");
  const body = await resp.json();
  return body.id as string;
}

export async function fetchItinerary(id: string): Promise<Itinerary> {
  const resp = await fetch(`${API_BASE}/r/${id}`, { cache: "no-store" });
  if (!resp.ok) throw new Error(`itinerary not found (${resp.status})`);
  return resp.json();
}
