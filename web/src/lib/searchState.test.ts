import { describe, expect, it } from "vitest";
import type { SearchParams } from "@/lib/api";
import { paramsToQuery, queryToParams, SEARCH_DEFAULTS } from "@/lib/searchState";

const base: SearchParams = {
  origin: "BER",
  dest: "BKK",
  date_from: "2026-08-01",
  date_to: "2026-08-31",
  round_trip: false,
  trip_min_days: null,
  trip_max_days: null,
  stop_min_hours: 4,
  stop_max_days: 7,
  max_stops: 3,
  top_k: 10,
};

describe("search URL state", () => {
  it("round-trips one-way params", () => {
    expect(queryToParams(paramsToQuery(base))).toEqual(base);
  });

  it("round-trips round-trip params with stay bounds and custom sliders", () => {
    const params: SearchParams = {
      ...base,
      round_trip: true,
      trip_min_days: 10,
      trip_max_days: 30,
      stop_max_days: 2,
      max_stops: 1,
    };
    expect(queryToParams(paramsToQuery(params))).toEqual(params);
  });

  it("omits default slider values from the URL", () => {
    const q = paramsToQuery(base);
    expect(q.get("nights")).toBeNull();
    expect(q.get("stops")).toBeNull();
  });

  it("rejects incomplete or invalid queries", () => {
    expect(queryToParams(new URLSearchParams(""))).toBeNull();
    expect(queryToParams(new URLSearchParams("from=BER&to=BKK"))).toBeNull();
    expect(
      queryToParams(new URLSearchParams("from=BER&to=BKK&depart=2026-09-01&return=2026-08-01")),
    ).toBeNull();
    expect(
      queryToParams(new URLSearchParams("from=BERL&to=BKK&depart=2026-08-01&return=2026-08-31")),
    ).toBeNull();
  });

  it("falls back to defaults for out-of-range values", () => {
    const parsed = queryToParams(
      new URLSearchParams("from=BER&to=BKK&depart=2026-08-01&return=2026-08-31&nights=99&stops=-1"),
    );
    expect(parsed?.stop_max_days).toBe(SEARCH_DEFAULTS.stop_max_days);
    expect(parsed?.max_stops).toBe(SEARCH_DEFAULTS.max_stops);
  });
});
