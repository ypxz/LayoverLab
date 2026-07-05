import { describe, expect, it } from "vitest";
import type { Itinerary, Leg } from "@/lib/api";
import {
  applyFilters,
  DEFAULT_FILTERS,
  diffPrices,
  flagEmoji,
  groupWarnings,
  INITIAL_SEARCH_STATE,
  itineraryKey,
  mergeUpdate,
  savingsVsDirect,
  searchReducer,
  sortItineraries,
  tripDays,
  warningSeverity,
  zeroResultsMessage,
} from "@/lib/results";
import { STR } from "@/lib/strings";

function leg(origin: string, dest: string, dep_date: string, price = 5000): Leg {
  return {
    origin,
    dest,
    dep_date,
    mode: "flight",
    price_cents: price,
    currency: "EUR",
    source: "ryanair",
    deep_link: null,
    fetched_at: "2026-07-01T00:00:00Z",
  };
}

function itin(legs: Leg[], total: number, extra: Partial<Itinerary> = {}): Itinerary {
  return {
    id: null,
    legs,
    total_cents: total,
    currency: "EUR",
    stopovers: [],
    warnings: [],
    verified: false,
    ...extra,
  };
}

const direct = itin([leg("BER", "BKK", "2026-08-12")], 60000);
const creative = itin(
  [leg("BER", "IST", "2026-08-10"), leg("IST", "BKK", "2026-08-13")],
  25000,
  { stopovers: [{ iata: "IST", nights: 3 }] },
);

describe("itineraryKey", () => {
  it("is identical for the same route regardless of price", () => {
    const cheaper = { ...creative, total_cents: 20000 };
    expect(itineraryKey(cheaper)).toBe(itineraryKey(creative));
  });
  it("differs when legs differ", () => {
    expect(itineraryKey(direct)).not.toBe(itineraryKey(creative));
  });
});

describe("mergeUpdate", () => {
  it("replaces an existing itinerary with a cheaper duplicate", () => {
    const cheaper = { ...creative, total_cents: 19000 };
    const { list, changed } = mergeUpdate([creative, direct], [cheaper]);
    expect(list).toHaveLength(2);
    expect(list[0].total_cents).toBe(19000);
    expect(changed).toEqual([itineraryKey(creative)]);
  });

  it("ignores a worse duplicate", () => {
    const worse = { ...creative, total_cents: 30000 };
    const { list, changed } = mergeUpdate([creative], [worse]);
    expect(list).toEqual([creative]);
    expect(changed).toEqual([]);
  });

  it("appends brand-new itineraries and marks them changed", () => {
    const fresh = itin([leg("BER", "KUL", "2026-08-11")], 30000);
    const { list, changed } = mergeUpdate([creative], [fresh]);
    expect(list).toEqual([creative, fresh]);
    expect(changed).toEqual([itineraryKey(fresh)]);
  });

  it("prefers a verified duplicate at the same price without flagging a flash", () => {
    const verified = { ...creative, verified: true };
    const { list, changed } = mergeUpdate([creative], [verified]);
    expect(list[0].verified).toBe(true);
    expect(changed).toEqual([]);
  });

  it("preserves existing order when replacing", () => {
    const cheaperDirect = { ...direct, total_cents: 55000 };
    const { list } = mergeUpdate([creative, direct], [cheaperDirect]);
    expect(list.map(itineraryKey)).toEqual([itineraryKey(creative), itineraryKey(direct)]);
  });
});

describe("diffPrices", () => {
  it("flags changed prices and new entries only", () => {
    const repriced = { ...creative, total_cents: 24000 };
    const fresh = itin([leg("BER", "KUL", "2026-08-11")], 30000);
    const changed = diffPrices([creative, direct], [repriced, direct, fresh]);
    expect(changed).toEqual([itineraryKey(creative), itineraryKey(fresh)]);
  });
});

describe("applyFilters", () => {
  const list = [direct, creative];
  it("passes everything with defaults", () => {
    expect(applyFilters(list, DEFAULT_FILTERS)).toEqual(list);
  });
  it("filters by max stops", () => {
    expect(applyFilters(list, { ...DEFAULT_FILTERS, maxStops: 0 })).toEqual([direct]);
  });
  it("filters by max stopover nights", () => {
    expect(applyFilters(list, { ...DEFAULT_FILTERS, maxStopoverNights: 2 })).toEqual([direct]);
  });
  it("filters by verified only", () => {
    const verified = { ...direct, verified: true };
    expect(applyFilters([verified, creative], { ...DEFAULT_FILTERS, verifiedOnly: true })).toEqual([
      verified,
    ]);
  });
});

describe("sortItineraries", () => {
  it("sorts by price", () => {
    expect(sortItineraries([direct, creative], "cheapest")[0]).toBe(creative);
  });
  it("sorts by fewest stops", () => {
    expect(sortItineraries([creative, direct], "fewest_stops")[0]).toBe(direct);
  });
  it("sorts by shortest trip", () => {
    expect(tripDays(creative)).toBe(3);
    expect(sortItineraries([creative, direct], "shortest")[0]).toBe(direct);
  });
});

describe("savingsVsDirect", () => {
  it("computes savings of best creative vs best direct", () => {
    expect(savingsVsDirect([direct, creative])).toBe(35000);
  });
  it("returns null without a direct or creative option", () => {
    expect(savingsVsDirect([creative])).toBeNull();
    expect(savingsVsDirect([direct])).toBeNull();
  });
  it("returns null when direct is cheaper", () => {
    expect(savingsVsDirect([{ ...direct, total_cents: 10000 }, creative])).toBeNull();
  });
});

describe("warnings", () => {
  it("classifies severity", () => {
    expect(warningSeverity("Self-transfer in IST: separate tickets")).toBe("danger");
    expect(warningSeverity("Check visa requirements for Turkey")).toBe("caution");
    expect(warningSeverity("Ground segment: bus BER to city")).toBe("info");
  });
  it("groups warnings", () => {
    const groups = groupWarnings(["Self-transfer risk", "visa needed", "something else"]);
    expect(groups.danger).toHaveLength(1);
    expect(groups.caution).toHaveLength(1);
    expect(groups.info).toHaveLength(1);
  });
});

describe("flagEmoji", () => {
  it("maps country codes to flags", () => {
    expect(flagEmoji("MY")).toBe("🇲🇾");
    expect(flagEmoji("")).toBe("");
  });
});

describe("searchReducer", () => {
  it("start resets state to searching", () => {
    const state = searchReducer(
      { ...INITIAL_SEARCH_STATE, results: [direct], phase: "done" },
      { type: "start" },
    );
    expect(state.phase).toBe("searching");
    expect(state.results).toEqual([]);
  });

  it("candidates -> verifying, verified -> streaming with flash on changed prices", () => {
    let state = searchReducer({ ...INITIAL_SEARCH_STATE, phase: "searching" }, {
      type: "candidates",
      payload: [creative, direct],
    });
    expect(state.phase).toBe("verifying");
    const repriced = { ...creative, total_cents: 25100, verified: true };
    state = searchReducer(state, { type: "verified", payload: [repriced, direct] });
    expect(state.phase).toBe("streaming");
    expect(state.flashKeys).toEqual([itineraryKey(creative)]);
  });

  it("update merges results and raises the updated notice only when improved", () => {
    let state: ReturnType<typeof searchReducer> = {
      ...INITIAL_SEARCH_STATE,
      phase: "streaming",
      results: [creative],
    };
    const worse = { ...creative, total_cents: 90000 };
    state = searchReducer(state, { type: "update", payload: [worse] });
    expect(state.updatedNotice).toBe(false);
    const cheaper = { ...creative, total_cents: 20000 };
    state = searchReducer(state, { type: "update", payload: [cheaper] });
    expect(state.updatedNotice).toBe(true);
    expect(state.results[0].total_cents).toBe(20000);
    expect(state.flashKeys).toEqual([itineraryKey(creative)]);
  });

  it("done records crawl_pending; error phase is sticky through done", () => {
    let state = searchReducer(
      { ...INITIAL_SEARCH_STATE, phase: "streaming" },
      { type: "done", meta: { crawl_pending: true, searched_pairs_covered: false } },
    );
    expect(state.phase).toBe("done");
    expect(state.crawlPending).toBe(true);
    state = searchReducer({ ...INITIAL_SEARCH_STATE, phase: "error" }, { type: "done", meta: null });
    expect(state.phase).toBe("error");
  });

  it("error sets error phase; clearFlash clears flash keys only", () => {
    let state = searchReducer({ ...INITIAL_SEARCH_STATE, phase: "verifying" }, { type: "error" });
    expect(state.phase).toBe("error");
    state = { ...state, flashKeys: ["x"], updatedNotice: true };
    state = searchReducer(state, { type: "clearFlash" });
    expect(state.flashKeys).toEqual([]);
    expect(state.updatedNotice).toBe(true);
  });
});

describe("zero-result reasons", () => {
  it("done records zero_results_reason and worker_alive from meta", () => {
    const state = searchReducer(
      { ...INITIAL_SEARCH_STATE, phase: "streaming" },
      {
        type: "done",
        meta: {
          crawl_pending: false,
          searched_pairs_covered: true,
          worker_alive: false,
          zero_results_reason: "worker_down",
        },
      },
    );
    expect(state.zeroReason).toBe("worker_down");
    expect(state.workerAlive).toBe(false);
  });

  it("done without the new meta fields defaults to null (backwards compatible)", () => {
    const state = searchReducer(
      { ...INITIAL_SEARCH_STATE, phase: "streaming" },
      { type: "done", meta: { crawl_pending: false, searched_pairs_covered: true } },
    );
    expect(state.zeroReason).toBeNull();
    expect(state.workerAlive).toBeNull();
  });

  it("zeroResultsMessage maps each reason to a distinct human message", () => {
    const reasons = [
      "no_coverage",
      "crawl_pending",
      "crawl_disabled",
      "worker_down",
      "sources_erroring",
    ] as const;
    const messages = reasons.map((r) => zeroResultsMessage(r));
    expect(new Set(messages).size).toBe(reasons.length);
  });

  it("zeroResultsMessage maps reasons to copy and falls back to the generic message", () => {
    expect(zeroResultsMessage(null)).toBe(STR.status.noResults);
    expect(zeroResultsMessage("no_coverage")).toBe(STR.status.noResults);
    expect(zeroResultsMessage("worker_down")).toBe(STR.status.zeroWorkerDown);
    expect(zeroResultsMessage("crawl_pending")).toBe(STR.status.zeroCrawlPending);
    expect(zeroResultsMessage("crawl_disabled")).toBe(STR.status.zeroCrawlDisabled);
    expect(zeroResultsMessage("sources_erroring")).toBe(STR.status.zeroSourcesErroring);
  });
});
