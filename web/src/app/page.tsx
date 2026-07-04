"use client";

import { FlaskConical, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import RouteCard from "@/components/RouteCard";
import SearchForm from "@/components/SearchForm";
import { searchStream, type Itinerary, type SearchParams } from "@/lib/api";

type Phase = "idle" | "searching" | "verifying" | "done" | "error";

export default function Home() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [results, setResults] = useState<Itinerary[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  async function runSearch(params: SearchParams) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setResults([]);
    setPhase("searching");
    try {
      await searchStream(
        params,
        (event, payload) => {
          if (event === "candidates") {
            setResults(payload as Itinerary[]);
            setPhase("verifying");
          } else if (event === "verified") {
            setResults(payload as Itinerary[]);
          } else if (event === "error") {
            setPhase("error");
          } else if (event === "done") {
            setPhase((p) => (p === "error" ? p : "done"));
          }
        },
        controller.signal,
      );
    } catch {
      if (!controller.signal.aborted) setPhase("error");
    }
  }

  return (
    <main>
      <header className="mb-8">
        <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
          <FlaskConical className="text-emerald-400" />
          Layover<span className="text-emerald-400">Lab</span>
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          The cheapest way from A to B is sometimes three days in a country you have never heard of.
          Self-transfer combos, multi-day stopovers, nearby airports, ground corridors.
        </p>
      </header>

      <SearchForm onSearch={runSearch} busy={phase === "searching" || phase === "verifying"} />

      <section className="mt-8 space-y-3">
        {phase === "searching" && (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="animate-spin" size={16} /> Searching the fare cache…
          </div>
        )}
        {phase === "verifying" && (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="animate-spin" size={16} /> Live-verifying the best candidates…
          </div>
        )}
        {phase === "error" && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
            Search failed. Is the API running? If the fare cache is empty, the crawler may still be
            collecting prices for this route — try again in a few minutes.
          </div>
        )}
        {phase === "done" && results.length === 0 && (
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400">
            No routes in the cache for this search yet. The crawler has been notified and is
            fetching fares for this route now — try again in a few minutes.
          </div>
        )}
        {results.map((itin, i) => (
          <RouteCard key={i} itin={itin} rank={i + 1} />
        ))}
      </section>

      <footer className="mt-12 border-t border-slate-800/60 pt-4 text-xs text-slate-600">
        Prices are estimates from cached public data until marked verified. Self-transfer trips are
        separate tickets: missed connections are your risk. Always confirm the final price on the
        booking site.
      </footer>
    </main>
  );
}
