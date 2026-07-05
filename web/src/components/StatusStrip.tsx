"use client";

import { Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import type { SearchPhase } from "@/lib/results";
import { STR } from "@/lib/strings";

interface Props {
  phase: SearchPhase;
  updatedNotice: boolean;
  crawlPending: boolean;
  startedAt: number | null;
  onReSearch: () => void;
}

function useElapsedSeconds(startedAt: number | null, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active || startedAt === null) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active, startedAt]);
  if (startedAt === null) return 0;
  return Math.max(0, Math.floor((now - startedAt) / 1000));
}

export default function StatusStrip({ phase, updatedNotice, crawlPending, startedAt, onReSearch }: Props) {
  const streamingPhase = phase === "searching" || phase === "verifying" || phase === "streaming";
  const elapsed = useElapsedSeconds(startedAt, streamingPhase);

  return (
    <div aria-live="polite" data-testid="status-strip" className="space-y-2 empty:hidden">
      {streamingPhase && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-2.5 text-sm text-slate-300">
          <Loader2 className="animate-spin text-emerald-400" size={15} />
          <span>
            {phase === "searching"
              ? STR.status.searchingCache
              : phase === "verifying"
                ? STR.status.verifying
                : STR.status.crawling}
          </span>
          {elapsed >= 5 && (
            <span className="ml-auto text-xs tabular-nums text-slate-500">
              {STR.status.elapsed(elapsed)}
            </span>
          )}
        </div>
      )}
      {updatedNotice && phase !== "error" && (
        <div
          data-testid="updated-notice"
          className="flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-300"
        >
          <Sparkles size={15} /> {STR.status.updated}
        </div>
      )}
      {phase === "done" && crawlPending && (
        <div
          data-testid="crawl-pending"
          className="flex flex-wrap items-center gap-3 rounded-xl border border-sky-500/30 bg-sky-500/10 px-4 py-2.5 text-sm text-sky-200"
        >
          <span>{STR.status.doneCrawlPending}</span>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            data-testid="re-search"
            onClick={onReSearch}
            className="ml-auto h-8 gap-1.5 text-xs"
          >
            <RefreshCw size={12} /> {STR.status.reSearch}
          </Button>
        </div>
      )}
      {phase === "error" && (
        <div
          data-testid="search-error"
          className="flex flex-wrap items-center gap-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300"
        >
          <span>
            <strong>{STR.status.errorTitle}</strong> {STR.status.errorBody}
          </span>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            data-testid="retry-search"
            onClick={onReSearch}
            className="ml-auto h-8 gap-1.5 text-xs"
          >
            <RefreshCw size={12} /> {STR.status.retry}
          </Button>
        </div>
      )}
    </div>
  );
}
