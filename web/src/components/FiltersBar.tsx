"use client";

import { ArrowUpDown, SlidersHorizontal } from "lucide-react";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import type { ResultFilters, SortMode } from "@/lib/results";
import { STR } from "@/lib/strings";
import { cn } from "@/lib/utils";

interface Props {
  filters: ResultFilters;
  onFiltersChange: (filters: ResultFilters) => void;
  sort: SortMode;
  onSortChange: (sort: SortMode) => void;
  showShortest: boolean;
}

const SORT_OPTIONS: { mode: SortMode; label: string }[] = [
  { mode: "cheapest", label: STR.filters.sortCheapest },
  { mode: "fewest_stops", label: STR.filters.sortFewestStops },
  { mode: "shortest", label: STR.filters.sortShortest },
];

export default function FiltersBar({ filters, onFiltersChange, sort, onSortChange, showShortest }: Props) {
  return (
    <div
      data-testid="filters-bar"
      className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3"
    >
      <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        <SlidersHorizontal size={12} /> {STR.filters.title}
      </span>
      <div className="flex w-36 flex-col gap-1">
        <Label className="text-[10px] uppercase tracking-wider text-slate-400">
          {STR.filters.maxStops}: {filters.maxStops ?? "any"}
        </Label>
        <Slider
          aria-label={STR.filters.maxStops}
          min={0}
          max={4}
          step={1}
          value={[filters.maxStops ?? 4]}
          onValueChange={([v]) => onFiltersChange({ ...filters, maxStops: v >= 4 ? null : v })}
        />
      </div>
      <div className="flex w-36 flex-col gap-1">
        <Label className="text-[10px] uppercase tracking-wider text-slate-400">
          {STR.filters.maxStopoverNights}: {filters.maxStopoverNights ?? "any"}
        </Label>
        <Slider
          aria-label={STR.filters.maxStopoverNights}
          min={0}
          max={14}
          step={1}
          value={[filters.maxStopoverNights ?? 14]}
          onValueChange={([v]) =>
            onFiltersChange({ ...filters, maxStopoverNights: v >= 14 ? null : v })
          }
        />
      </div>
      <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-300">
        <Switch
          checked={filters.verifiedOnly}
          onCheckedChange={(v) => onFiltersChange({ ...filters, verifiedOnly: v })}
          aria-label={STR.filters.verifiedOnly}
        />
        {STR.filters.verifiedOnly}
      </label>
      <div className="ml-auto flex items-center gap-1.5" role="group" aria-label={STR.filters.sort}>
        <ArrowUpDown size={12} className="text-slate-500" />
        {SORT_OPTIONS.filter((o) => o.mode !== "shortest" || showShortest).map((o) => (
          <button
            key={o.mode}
            type="button"
            aria-pressed={sort === o.mode}
            onClick={() => onSortChange(o.mode)}
            className={cn(
              "rounded-lg px-2.5 py-1 text-xs transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              sort === o.mode
                ? "bg-emerald-500/20 font-semibold text-emerald-300"
                : "text-slate-400 hover:bg-slate-800",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
