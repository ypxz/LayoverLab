"use client";

import {
  BadgeCheck,
  Clock,
  ExternalLink,
  Moon,
  Plane,
  Share2,
  ShieldAlert,
  TrainFront,
} from "lucide-react";
import { useState } from "react";
import { saveItinerary, type Itinerary, type Leg } from "@/lib/api";
import { formatDate, formatMoney, freshness } from "@/lib/format";

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

export default function RouteCard({ itin, rank }: { itin: Itinerary; rank: number }) {
  const [expanded, setExpanded] = useState(false);
  const [shareState, setShareState] = useState<"idle" | "copied" | "error">("idle");
  const nights = itin.stopovers.reduce((acc, s) => acc + s.nights, 0);

  async function share() {
    try {
      const id = itin.id ?? (await saveItinerary(itin));
      const url = `${window.location.origin}/r/${id}`;
      await navigator.clipboard.writeText(url);
      setShareState("copied");
      setTimeout(() => setShareState("idle"), 2000);
    } catch {
      setShareState("error");
    }
  }

  const oldestFetch = itin.legs.reduce(
    (min, leg) => (leg.fetched_at < min ? leg.fetched_at : min),
    itin.legs[0]?.fetched_at ?? "",
  );

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 transition hover:border-slate-700">
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
            <span className="flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-1 text-[11px] font-medium text-emerald-300">
              <BadgeCheck size={12} /> verified now
            </span>
          ) : (
            <span
              className="flex items-center gap-1 rounded-full bg-slate-700/40 px-2 py-1 text-[11px] font-medium text-slate-400"
              title="Prices from the fare cache — verify before booking"
            >
              <Clock size={12} /> cached {oldestFetch ? freshness(oldestFetch) : ""}
            </span>
          )}
          <span className="text-xl font-bold text-emerald-400">
            {formatMoney(itin.total_cents, itin.currency)}
          </span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span>
          {itin.legs.length} leg{itin.legs.length > 1 ? "s" : ""}
          {nights > 0 ? ` · ${nights} stopover night${nights > 1 ? "s" : ""}` : " · direct-ish"}
        </span>
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-800"
        >
          <ShieldAlert size={12} />
          {itin.warnings.length} note{itin.warnings.length !== 1 ? "s" : ""}
        </button>
        <button
          onClick={share}
          className="flex items-center gap-1 rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-800"
        >
          <Share2 size={12} />
          {shareState === "copied" ? "link copied!" : shareState === "error" ? "failed" : "share"}
        </button>
        <div className="ml-auto flex gap-2">
          {itin.legs
            .filter((leg) => leg.deep_link)
            .map((leg, i) => (
              <a
                key={i}
                href={leg.deep_link!}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 rounded-lg bg-slate-800 px-2.5 py-1.5 text-[11px] font-medium text-slate-200 hover:bg-slate-700"
              >
                book {leg.origin}→{leg.dest} <ExternalLink size={10} />
              </a>
            ))}
        </div>
      </div>

      {expanded && (
        <ul className="mt-3 space-y-1.5 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
          {itin.warnings.map((w, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-amber-200/90">
              <ShieldAlert size={12} className="mt-0.5 shrink-0 text-amber-400" />
              {w}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
