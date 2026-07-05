"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { FlaskConical, PiggyBank, Sparkles } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useReducer, useRef, useState } from "react";
import FiltersBar from "@/components/FiltersBar";
import RouteCard from "@/components/RouteCard";
import SearchForm from "@/components/SearchForm";
import SkeletonCard from "@/components/SkeletonCard";
import StatusStrip from "@/components/StatusStrip";
import { searchStream, type DoneMeta, type Itinerary, type SearchParams } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import {
  applyFilters,
  DEFAULT_FILTERS,
  hasTimes,
  INITIAL_SEARCH_STATE,
  itineraryKey,
  savingsVsDirect,
  searchReducer,
  sortItineraries,
  type SortMode,
  zeroResultsMessage,
} from "@/lib/results";
import { paramsToQuery, queryToParams } from "@/lib/searchState";
import { STR } from "@/lib/strings";

interface ExampleRoute {
  label: string;
  origin: string;
  dest: string;
}

const EXAMPLE_ROUTES: ExampleRoute[] = [
  { label: "Berlin → Bangkok via a weekend in Istanbul", origin: "BER", dest: "BKK" },
  { label: "London → Milan the long way round", origin: "LON", dest: "MIL" },
  { label: "Berlin → Alicante with a free stopover", origin: "BER", dest: "ALC" },
];

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function exampleParams(route: ExampleRoute): SearchParams {
  const now = new Date();
  return {
    origin: route.origin,
    dest: route.dest,
    date_from: isoDate(new Date(now.getFullYear(), now.getMonth() + 1, 1)),
    date_to: isoDate(new Date(now.getFullYear(), now.getMonth() + 2, 0)),
    round_trip: false,
    trip_min_days: null,
    trip_max_days: null,
    stop_min_hours: 4,
    stop_max_days: 7,
    max_stops: 3,
    top_k: 10,
  };
}

function HomeInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [state, dispatch] = useReducer(searchReducer, INITIAL_SEARCH_STATE);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [sort, setSort] = useState<SortMode>("cheapest");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const lastRunRef = useRef<string | null>(null);
  const lastParamsRef = useRef<SearchParams | null>(null);
  const reducedMotion = useReducedMotion();

  const urlParams = useMemo(
    () => queryToParams(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  async function runSearch(params: SearchParams) {
    lastParamsRef.current = params;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    dispatch({ type: "start" });
    setStartedAt(Date.now());
    let doneReceived = false;
    try {
      await searchStream(
        params,
        (event, payload) => {
          if (event === "candidates") {
            dispatch({ type: "candidates", payload: payload as Itinerary[] });
          } else if (event === "verified") {
            dispatch({ type: "verified", payload: payload as Itinerary[] });
          } else if (event === "update") {
            dispatch({ type: "update", payload: payload as Itinerary[] });
          } else if (event === "error") {
            dispatch({ type: "error" });
          } else if (event === "done") {
            doneReceived = true;
            const meta = (payload as { meta?: DoneMeta } | null)?.meta ?? null;
            dispatch({ type: "done", meta });
          }
        },
        controller.signal,
      );
      if (!doneReceived && !controller.signal.aborted) dispatch({ type: "error" });
    } catch {
      if (!controller.signal.aborted) dispatch({ type: "error" });
    }
  }

  function submitSearch(params: SearchParams) {
    const query = paramsToQuery(params).toString();
    lastRunRef.current = query;
    router.push(`/?${query}`, { scroll: false });
    void runSearch(params);
  }

  useEffect(() => {
    if (!urlParams) return;
    const query = paramsToQuery(urlParams).toString();
    if (lastRunRef.current === query) return;
    lastRunRef.current = query;
    void runSearch(urlParams);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlParams]);

  useEffect(() => {
    if (state.flashKeys.length === 0) return;
    const timer = setTimeout(() => dispatch({ type: "clearFlash" }), 1400);
    return () => clearTimeout(timer);
  }, [state.flashKeys]);

  const busy =
    state.phase === "searching" || state.phase === "verifying" || state.phase === "streaming";
  const flashSet = useMemo(() => new Set(state.flashKeys), [state.flashKeys]);
  const visible = useMemo(
    () => sortItineraries(applyFilters(state.results, filters), sort),
    [state.results, filters, sort],
  );
  const savings = savingsVsDirect(state.results);
  const showLanding = state.phase === "idle";
  const showShortest = hasTimes(state.results);

  useEffect(() => {
    if (!showShortest && sort === "shortest") setSort("cheapest");
  }, [showShortest, sort]);

  function reSearch() {
    const params = lastParamsRef.current ?? urlParams;
    if (params) void runSearch(params);
  }

  return (
    <main>
      <header className="mb-8">
        <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
          <FlaskConical className="text-emerald-400" aria-hidden />
          Layover<span className="text-emerald-400">Lab</span>
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-400">
          {STR.tagline} {STR.heroSub}
        </p>
      </header>

      <SearchForm onSearch={submitSearch} busy={busy} initial={urlParams} />

      {showLanding && (
        <>
          <section className="mt-6" aria-label={STR.tryExample}>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
              {STR.tryExample}
            </p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLE_ROUTES.map((route) => (
                <button
                  key={route.label}
                  type="button"
                  onClick={() => submitSearch(exampleParams(route))}
                  className="rounded-full border border-slate-700 bg-slate-900/60 px-3.5 py-1.5 text-xs text-slate-300 transition hover:border-emerald-500/50 hover:text-emerald-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Sparkles size={11} className="mr-1.5 inline text-emerald-400" aria-hidden />
                  {route.label}
                </button>
              ))}
            </div>
          </section>

          <section className="mt-10" aria-labelledby="how-it-works">
            <h2
              id="how-it-works"
              className="mb-4 text-xs font-semibold uppercase tracking-wider text-slate-500"
            >
              {STR.howItWorksTitle}
            </h2>
            <ol className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {STR.howItWorks.map((step, i) => (
                <li
                  key={step.title}
                  className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4"
                >
                  <span className="mb-2 flex h-7 w-7 items-center justify-center rounded-full bg-emerald-500/15 text-sm font-bold text-emerald-400">
                    {i + 1}
                  </span>
                  <h3 className="text-sm font-semibold text-slate-200">{step.title}</h3>
                  <p className="mt-1 text-xs leading-relaxed text-slate-400">{step.body}</p>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}

      <section className="mt-6 space-y-3" aria-label={STR.status.ariaResults} aria-live="polite">
        <StatusStrip
          phase={state.phase}
          updatedNotice={state.updatedNotice}
          crawlPending={state.crawlPending}
          startedAt={startedAt}
          onReSearch={reSearch}
        />

        {state.phase === "searching" && state.results.length === 0 && (
          <>
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </>
        )}

        {state.phase === "done" && state.results.length === 0 && (
          <div
            data-testid="zero-results"
            className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400"
          >
            {zeroResultsMessage(state.zeroReason)}
          </div>
        )}

        {state.results.length > 0 && (
          <FiltersBar
            filters={filters}
            onFiltersChange={setFilters}
            sort={sort}
            onSortChange={setSort}
            showShortest={showShortest}
          />
        )}

        {savings !== null && (
          <div
            data-testid="savings-banner"
            className="flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm font-medium text-emerald-300"
          >
            <PiggyBank size={16} aria-hidden />
            {STR.savings(formatMoney(savings, state.results[0]?.currency ?? "EUR"))}
          </div>
        )}

        {state.results.length > 0 && visible.length === 0 && (
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400">
            {STR.filters.noneMatch}
          </div>
        )}

        <AnimatePresence initial={false}>
          {visible.map((itin, i) => {
            const key = itineraryKey(itin);
            return (
              <motion.div
                key={key}
                layout={!reducedMotion}
                initial={reducedMotion ? false : { opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reducedMotion ? undefined : { opacity: 0, scale: 0.98 }}
                transition={{ type: "spring", stiffness: 350, damping: 30 }}
              >
                <RouteCard itin={itin} rank={i + 1} flash={flashSet.has(key)} />
              </motion.div>
            );
          })}
        </AnimatePresence>
      </section>

      <footer className="mt-12 border-t border-slate-800/60 pt-4 text-xs text-slate-600">
        {STR.footer}
      </footer>
    </main>
  );
}

export default function Home() {
  return (
    <Suspense>
      <HomeInner />
    </Suspense>
  );
}
