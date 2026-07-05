"use client";

import { BadgeCheck, ChevronDown, Clock, Moon, Plane, Share2, TrainFront } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import RouteDetail from "@/components/RouteDetail";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { saveItinerary, type Itinerary, type Leg } from "@/lib/api";
import { formatDate, formatMoney, freshness } from "@/lib/format";
import { STR } from "@/lib/strings";
import { cn } from "@/lib/utils";

function LegSegment({ leg }: { leg: Leg }) {
  const Icon = leg.mode === "flight" ? Plane : TrainFront;
  return (
    <div className="flex items-center gap-2">
      <div className="flex flex-col items-center">
        <span className="text-sm font-bold">{leg.origin}</span>
        <span className="text-[10px] text-slate-500">{formatDate(leg.dep_date)}</span>
      </div>
      <div className="flex flex-col items-center px-1">
        <Icon size={14} className="text-emerald-400" />
        <span className="text-[10px] text-slate-400">{formatMoney(leg.price_cents, leg.currency)}</span>
        <span className="text-[9px] uppercase tracking-wide text-slate-600">{leg.source}</span>
      </div>
      <span className="text-sm font-bold">{leg.dest}</span>
    </div>
  );
}

interface Props {
  itin: Itinerary;
  rank: number;
  flash?: boolean;
}

export default function RouteCard({ itin, rank, flash = false }: Props) {
  const [expanded, setExpanded] = useState(false);
  const nights = itin.stopovers.reduce((acc, s) => acc + s.nights, 0);

  async function share() {
    try {
      const id = itin.id ?? (await saveItinerary(itin));
      const url = `${window.location.origin}/r/${id}`;
      await navigator.clipboard.writeText(url);
      toast.success(STR.card.shareCopied);
    } catch {
      toast.error(STR.card.shareError);
    }
  }

  const oldestFetch = itin.legs.reduce(
    (min, leg) => (leg.fetched_at < min ? leg.fetched_at : min),
    itin.legs[0]?.fetched_at ?? "",
  );

  return (
    <div
      data-testid="result-card"
      className={cn(
        "rounded-2xl border border-slate-800 bg-slate-900/60 p-4 transition hover:border-slate-700",
        flash && "animate-price-flash",
      )}
    >
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs font-semibold text-slate-500">#{rank}</span>
        <div className="flex flex-wrap items-center gap-4">
          {itin.legs.map((leg, i) => (
            <div key={i} className="flex items-center gap-4">
              <LegSegment leg={leg} />
              {i < itin.legs.length - 1 &&
                (() => {
                  const stop = itin.stopovers.find((s) => s.iata === leg.dest);
                  return stop ? (
                    <span className="flex items-center gap-1 rounded-full bg-indigo-500/15 px-2 py-0.5 text-[10px] font-medium text-indigo-300">
                      <Moon size={10} />
                      {stop.nights}n {stop.iata}
                    </span>
                  ) : null;
                })()}
            </div>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-3">
          {itin.verified ? (
            <span
              data-testid="verified-badge"
              className="flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-1 text-[11px] font-medium text-emerald-300"
            >
              <BadgeCheck size={12} /> {STR.card.verifiedNow}
            </span>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="flex cursor-default items-center gap-1 rounded-full bg-slate-700/40 px-2 py-1 text-[11px] font-medium text-slate-400">
                  <Clock size={12} /> {STR.card.cached} {oldestFetch ? freshness(oldestFetch) : ""}
                </span>
              </TooltipTrigger>
              <TooltipContent>{STR.card.cachedTooltip}</TooltipContent>
            </Tooltip>
          )}
          <span data-testid="route-total" className="text-xl font-bold text-emerald-400">
            {formatMoney(itin.total_cents, itin.currency)}
          </span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span>
          {STR.card.legs(itin.legs.length)}
          {nights > 0 ? ` · ${STR.card.stopoverNights(nights)}` : ` · ${STR.card.directIsh}`}
          {itin.warnings.length > 0 ? ` · ${STR.card.notes(itin.warnings.length)}` : ""}
        </span>
        <button
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          className="flex items-center gap-1 rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ChevronDown size={12} className={cn("transition-transform", expanded && "rotate-180")} />
          {expanded ? STR.card.hideDetails : STR.card.details}
        </button>
        <button
          data-testid="share-button"
          onClick={share}
          className="flex items-center gap-1 rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Share2 size={12} />
          {STR.card.share}
        </button>
      </div>

      {expanded && (
        <div className="mt-4 border-t border-slate-800 pt-4">
          <RouteDetail itin={itin} />
        </div>
      )}
    </div>
  );
}
