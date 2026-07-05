import type { SearchParams } from "@/lib/api";

export const SEARCH_DEFAULTS = {
  stop_min_hours: 4,
  stop_max_days: 7,
  max_stops: 3,
  top_k: 10,
  trip_min_days: 7,
  trip_max_days: 21,
} as const;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const IATA = /^[A-Z]{3}$/;

export function paramsToQuery(params: SearchParams): URLSearchParams {
  const q = new URLSearchParams();
  q.set("from", params.origin);
  q.set("to", params.dest);
  q.set("depart", params.date_from);
  q.set("return", params.date_to);
  if (params.round_trip) {
    q.set("rt", "1");
    if (params.trip_min_days != null) q.set("stay_min", String(params.trip_min_days));
    if (params.trip_max_days != null) q.set("stay_max", String(params.trip_max_days));
  }
  if (params.stop_max_days !== SEARCH_DEFAULTS.stop_max_days)
    q.set("nights", String(params.stop_max_days));
  if (params.max_stops !== SEARCH_DEFAULTS.max_stops) q.set("stops", String(params.max_stops));
  return q;
}

function intParam(q: URLSearchParams, key: string, min: number, max: number): number | null {
  const raw = q.get(key);
  if (raw === null) return null;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < min || n > max) return null;
  return n;
}

/** Parses a shareable search URL back into SearchParams; null unless origin/dest/dates are valid. */
export function queryToParams(q: URLSearchParams): SearchParams | null {
  const origin = (q.get("from") ?? "").toUpperCase();
  const dest = (q.get("to") ?? "").toUpperCase();
  const dateFrom = q.get("depart") ?? "";
  const dateTo = q.get("return") ?? "";
  if (!IATA.test(origin) || !IATA.test(dest)) return null;
  if (!ISO_DATE.test(dateFrom) || !ISO_DATE.test(dateTo) || dateFrom > dateTo) return null;
  const roundTrip = q.get("rt") === "1";
  return {
    origin,
    dest,
    date_from: dateFrom,
    date_to: dateTo,
    round_trip: roundTrip,
    trip_min_days: roundTrip
      ? intParam(q, "stay_min", 1, 90) ?? SEARCH_DEFAULTS.trip_min_days
      : null,
    trip_max_days: roundTrip
      ? intParam(q, "stay_max", 1, 120) ?? SEARCH_DEFAULTS.trip_max_days
      : null,
    stop_min_hours: SEARCH_DEFAULTS.stop_min_hours,
    stop_max_days: intParam(q, "nights", 0, 14) ?? SEARCH_DEFAULTS.stop_max_days,
    max_stops: intParam(q, "stops", 0, 4) ?? SEARCH_DEFAULTS.max_stops,
    top_k: SEARCH_DEFAULTS.top_k,
  };
}
