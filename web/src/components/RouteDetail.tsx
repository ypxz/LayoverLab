"use client";

import { AlertTriangle, ExternalLink, Info, Moon, Plane, ShieldAlert, TrainFront } from "lucide-react";
import { useAirport } from "@/lib/airports";
import type { Itinerary, Leg } from "@/lib/api";
import { formatDate, formatMoney, freshness } from "@/lib/format";
import { flagEmoji, groupWarnings, tripDays, type WarningSeverity } from "@/lib/results";
import { STR } from "@/lib/strings";
import { cn } from "@/lib/utils";

const SOURCE_COLORS: Record<string, string> = {
  ryanair: "bg-sky-500/20 text-sky-300",
  wizzair: "bg-fuchsia-500/20 text-fuchsia-300",
  easyjet: "bg-orange-500/20 text-orange-300",
  travelpayouts: "bg-teal-500/20 text-teal-300",
  kiwi_tequila: "bg-lime-500/20 text-lime-300",
  amadeus: "bg-indigo-500/20 text-indigo-300",
  google_flights: "bg-red-500/20 text-red-300",
};

function SourceBadge({ source }: { source: string }) {
  const initials = source.replace(/_/g, " ").split(" ").map((w) => w[0]?.toUpperCase()).join("").slice(0, 2);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold",
        SOURCE_COLORS[source] ?? "bg-slate-700/40 text-slate-300",
      )}
      title={source}
    >
      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-white/10 text-[8px]">
        {initials}
      </span>
      {source.replace(/_/g, " ")}
    </span>
  );
}

function StopoverBlock({ iata, nights }: { iata: string; nights: number }) {
  const airport = useAirport(iata);
  const place = airport?.city || iata;
  const flag = airport ? flagEmoji(airport.country_code) : "";
  return (
    <div className="flex min-w-[7.5rem] flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-indigo-400/30 bg-indigo-500/10 px-3 py-2 text-center">
      <Moon size={14} className="text-indigo-300" />
      <span className="text-xs font-medium text-indigo-200">
        {STR.card.nightsIn(nights, place)} {flag}
      </span>
    </div>
  );
}

function LegCard({ leg }: { leg: Leg }) {
  const Icon = leg.mode === "flight" ? Plane : TrainFront;
  return (
    <div className="flex min-w-[13rem] flex-col gap-2 rounded-xl border border-slate-700/70 bg-slate-900/80 p-3">
      <div className="flex items-center justify-between gap-2">
        <SourceBadge source={leg.source} />
        <span className="text-sm font-bold text-emerald-400">
          {formatMoney(leg.price_cents, leg.currency)}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex flex-col">
          <span className="text-lg font-bold leading-tight">{leg.origin}</span>
          {leg.dep_time && <span className="text-xs text-slate-400">{leg.dep_time}</span>}
        </div>
        <div className="flex flex-1 flex-col items-center px-1">
          <Icon size={14} className="text-emerald-400" />
          <span className="mt-0.5 h-px w-full bg-gradient-to-r from-transparent via-slate-600 to-transparent" />
          <span className="text-[10px] text-slate-500">{formatDate(leg.dep_date)}</span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-lg font-bold leading-tight">{leg.dest}</span>
          {leg.arr_time && <span className="text-xs text-slate-400">{leg.arr_time}</span>}
        </div>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-slate-500">
          {STR.card.freshness} {freshness(leg.fetched_at)}
        </span>
        {leg.deep_link && (
          <a
            href={leg.deep_link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-lg bg-emerald-500/90 px-2.5 py-1 text-[11px] font-semibold text-slate-950 transition hover:bg-emerald-400"
          >
            {STR.card.book} <ExternalLink size={10} />
          </a>
        )}
      </div>
    </div>
  );
}

const SEVERITY_META: Record<WarningSeverity, { label: string; icon: typeof Info; className: string }> = {
  danger: { label: STR.card.warnings.danger, icon: ShieldAlert, className: "border-red-500/25 bg-red-500/10 text-red-200" },
  caution: { label: STR.card.warnings.caution, icon: AlertTriangle, className: "border-amber-500/25 bg-amber-500/5 text-amber-200/90" },
  info: { label: STR.card.warnings.info, icon: Info, className: "border-sky-500/25 bg-sky-500/5 text-sky-200/90" },
};

export default function RouteDetail({ itin }: { itin: Itinerary }) {
  const groups = groupWarnings(itin.warnings);
  const days = tripDays(itin);

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto pb-1" role="list" aria-label="Trip timeline">
        <div className="flex min-w-max items-stretch gap-2">
          {itin.legs.map((leg, i) => {
            const stop = i < itin.legs.length - 1 ? itin.stopovers.find((s) => s.iata === leg.dest) : undefined;
            return (
              <div key={i} role="listitem" className="flex items-stretch gap-2">
                <LegCard leg={leg} />
                {stop && (
                  <div
                    className="flex items-stretch"
                    style={{ minWidth: `${Math.min(stop.nights, 7) * 1.25 + 6}rem` }}
                  >
                    <StopoverBlock iata={stop.iata} nights={stop.nights} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
        <span className="text-xs text-slate-400">
          {STR.card.legs(itin.legs.length)}
          {days > 0 ? ` · ${days} day trip` : ""}
        </span>
        <span className="text-sm text-slate-300">
          {STR.card.total}{" "}
          <span className="text-xl font-bold text-emerald-400">
            {formatMoney(itin.total_cents, itin.currency)}
          </span>
        </span>
      </div>

      {(["danger", "caution", "info"] as const).map((severity) => {
        const warnings = groups[severity];
        if (warnings.length === 0) return null;
        const meta = SEVERITY_META[severity];
        const MetaIcon = meta.icon;
        return (
          <div key={severity} className={cn("rounded-xl border p-3", meta.className)}>
            <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider">
              <MetaIcon size={12} /> {meta.label}
            </p>
            <ul className="space-y-1">
              {warnings.map((w, i) => (
                <li key={i} className="flex items-start gap-2 text-xs">
                  <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-current" />
                  {w}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
