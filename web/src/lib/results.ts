import type { DoneMeta, Itinerary } from "@/lib/api";

/** Stable identity for an itinerary: its route shape (legs), independent of price. */
export function itineraryKey(itin: Itinerary): string {
  return itin.legs.map((l) => `${l.mode}:${l.origin}-${l.dest}@${l.dep_date}`).join("|");
}

export interface MergeResult {
  list: Itinerary[];
  /** Keys of entries that are new or got cheaper/verified — used for flash animation. */
  changed: string[];
}

/**
 * Merges an `update` payload into the visible list.
 * A new cheaper itinerary replaces its duplicate; a worse duplicate is ignored;
 * unknown itineraries are appended. Existing order is preserved.
 */
export function mergeUpdate(current: Itinerary[], incoming: Itinerary[]): MergeResult {
  const byKey = new Map(current.map((it) => [itineraryKey(it), it]));
  const changed: string[] = [];
  const appended: Itinerary[] = [];
  const replaced = new Map<string, Itinerary>();
  for (const item of incoming) {
    const key = itineraryKey(item);
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, item);
      appended.push(item);
      changed.push(key);
    } else if (
      item.total_cents < existing.total_cents ||
      (item.total_cents === existing.total_cents && item.verified && !existing.verified)
    ) {
      replaced.set(key, item);
      if (item.total_cents < existing.total_cents) changed.push(key);
    }
  }
  const list = current.map((it) => replaced.get(itineraryKey(it)) ?? it).concat(appended);
  return { list, changed };
}

/** Keys whose price changed (or that are new) between two full lists — for the verified flash. */
export function diffPrices(prev: Itinerary[], next: Itinerary[]): string[] {
  const prevByKey = new Map(prev.map((it) => [itineraryKey(it), it]));
  const changed: string[] = [];
  for (const item of next) {
    const key = itineraryKey(item);
    const old = prevByKey.get(key);
    if (!old || old.total_cents !== item.total_cents) changed.push(key);
  }
  return changed;
}

export interface ResultFilters {
  maxStops: number | null;
  maxStopoverNights: number | null;
  verifiedOnly: boolean;
}

export const DEFAULT_FILTERS: ResultFilters = {
  maxStops: null,
  maxStopoverNights: null,
  verifiedOnly: false,
};

export function applyFilters(list: Itinerary[], filters: ResultFilters): Itinerary[] {
  return list.filter((it) => {
    const stops = it.legs.length - 1;
    const nights = it.stopovers.reduce((acc, s) => acc + s.nights, 0);
    if (filters.maxStops !== null && stops > filters.maxStops) return false;
    if (filters.maxStopoverNights !== null && nights > filters.maxStopoverNights) return false;
    if (filters.verifiedOnly && !it.verified) return false;
    return true;
  });
}

export type SortMode = "cheapest" | "fewest_stops" | "shortest";

/** Trip length in days from first departure to last departure (times not always known). */
export function tripDays(itin: Itinerary): number {
  if (itin.legs.length === 0) return 0;
  const first = Date.parse(`${itin.legs[0].dep_date}T00:00:00Z`);
  const last = Date.parse(`${itin.legs[itin.legs.length - 1].dep_date}T00:00:00Z`);
  return Math.round((last - first) / 86_400_000);
}

export function hasTimes(list: Itinerary[]): boolean {
  return list.some((it) => it.legs.some((l) => l.dep_time || l.arr_time));
}

export function sortItineraries(list: Itinerary[], mode: SortMode): Itinerary[] {
  const sorted = [...list];
  if (mode === "cheapest") {
    sorted.sort((a, b) => a.total_cents - b.total_cents);
  } else if (mode === "fewest_stops") {
    sorted.sort((a, b) => a.legs.length - b.legs.length || a.total_cents - b.total_cents);
  } else {
    sorted.sort((a, b) => tripDays(a) - tripDays(b) || a.total_cents - b.total_cents);
  }
  return sorted;
}

/** Cents saved by the best multi-leg route vs the best direct flight in the set (null if n/a). */
export function savingsVsDirect(list: Itinerary[]): number | null {
  const directs = list.filter((it) => it.legs.length === 1);
  const creative = list.filter((it) => it.legs.length > 1);
  if (directs.length === 0 || creative.length === 0) return null;
  const bestDirect = Math.min(...directs.map((it) => it.total_cents));
  const bestCreative = Math.min(...creative.map((it) => it.total_cents));
  const saved = bestDirect - bestCreative;
  return saved > 0 ? saved : null;
}

export type WarningSeverity = "danger" | "caution" | "info";

export function warningSeverity(warning: string): WarningSeverity {
  const w = warning.toLowerCase();
  if (w.includes("self-transfer") || w.includes("missed connection") || w.includes("separate ticket"))
    return "danger";
  if (w.includes("visa") || w.includes("baggage") || w.includes("passport") || w.includes("layover under"))
    return "caution";
  return "info";
}

export function groupWarnings(warnings: string[]): Record<WarningSeverity, string[]> {
  const groups: Record<WarningSeverity, string[]> = { danger: [], caution: [], info: [] };
  for (const w of warnings) groups[warningSeverity(w)].push(w);
  return groups;
}

export function flagEmoji(countryCode: string): string {
  if (!/^[A-Za-z]{2}$/.test(countryCode)) return "";
  return String.fromCodePoint(
    ...countryCode.toUpperCase().split("").map((c) => 0x1f1e6 + c.charCodeAt(0) - 65),
  );
}

export type SearchPhase = "idle" | "searching" | "verifying" | "streaming" | "done" | "error";

export interface SearchState {
  phase: SearchPhase;
  results: Itinerary[];
  /** Itinerary keys that should flash (new/changed price) — cleared after animation. */
  flashKeys: string[];
  /** True right after an `update` event improved the visible results. */
  updatedNotice: boolean;
  crawlPending: boolean;
}

export const INITIAL_SEARCH_STATE: SearchState = {
  phase: "idle",
  results: [],
  flashKeys: [],
  updatedNotice: false,
  crawlPending: false,
};

export type SearchAction =
  | { type: "start" }
  | { type: "candidates"; payload: Itinerary[] }
  | { type: "verified"; payload: Itinerary[] }
  | { type: "update"; payload: Itinerary[] }
  | { type: "done"; meta: DoneMeta | null }
  | { type: "error" }
  | { type: "clearFlash" };

export function searchReducer(state: SearchState, action: SearchAction): SearchState {
  switch (action.type) {
    case "start":
      return { ...INITIAL_SEARCH_STATE, phase: "searching" };
    case "candidates":
      return { ...state, results: action.payload, phase: "verifying" };
    case "verified":
      return {
        ...state,
        results: action.payload,
        flashKeys: diffPrices(state.results, action.payload),
        phase: "streaming",
      };
    case "update": {
      const { list, changed } = mergeUpdate(state.results, action.payload);
      return {
        ...state,
        results: list,
        flashKeys: changed,
        updatedNotice: state.updatedNotice || changed.length > 0,
        phase: state.phase === "searching" ? "verifying" : state.phase,
      };
    }
    case "done":
      return {
        ...state,
        phase: state.phase === "error" ? state.phase : "done",
        crawlPending: action.meta?.crawl_pending ?? false,
      };
    case "error":
      return { ...state, phase: "error" };
    case "clearFlash":
      return state.flashKeys.length === 0 ? state : { ...state, flashKeys: [] };
    default:
      return state;
  }
}
