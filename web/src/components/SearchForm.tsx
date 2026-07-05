"use client";

import { motion } from "framer-motion";
import { ArrowLeftRight, CalendarDays, Search } from "lucide-react";
import { useEffect, useState } from "react";
import type { DateRange } from "react-day-picker";
import AirportInput from "@/components/AirportInput";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import type { SearchParams } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { SEARCH_DEFAULTS } from "@/lib/searchState";
import { STR } from "@/lib/strings";

interface Props {
  onSearch: (params: SearchParams) => void;
  busy: boolean;
  initial?: SearchParams | null;
}

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function parseIso(s: string): Date | undefined {
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? new Date(`${s}T00:00:00`) : undefined;
}

function nextMonthRange(now: Date): { from: string; to: string } {
  return {
    from: isoDate(new Date(now.getFullYear(), now.getMonth() + 1, 1)),
    to: isoDate(new Date(now.getFullYear(), now.getMonth() + 2, 0)),
  };
}

function summerRange(now: Date): { from: string; to: string } {
  const year = now.getMonth() >= 7 ? now.getFullYear() + 1 : now.getFullYear();
  return { from: isoDate(new Date(year, 5, 1)), to: isoDate(new Date(year, 7, 31)) };
}

export default function SearchForm({ onSearch, busy, initial }: Props) {
  const [origin, setOrigin] = useState(initial?.origin ?? "");
  const [dest, setDest] = useState(initial?.dest ?? "");
  const [dateFrom, setDateFrom] = useState(initial?.date_from ?? "");
  const [dateTo, setDateTo] = useState(initial?.date_to ?? "");
  const [roundTrip, setRoundTrip] = useState(initial?.round_trip ?? false);
  const [tripMinDays, setTripMinDays] = useState(
    initial?.trip_min_days ?? SEARCH_DEFAULTS.trip_min_days,
  );
  const [tripMaxDays, setTripMaxDays] = useState(
    initial?.trip_max_days ?? SEARCH_DEFAULTS.trip_max_days,
  );
  const [stopMaxDays, setStopMaxDays] = useState(
    initial?.stop_max_days ?? SEARCH_DEFAULTS.stop_max_days,
  );
  const [maxStops, setMaxStops] = useState(initial?.max_stops ?? SEARCH_DEFAULTS.max_stops);
  const [swapCount, setSwapCount] = useState(0);
  const [calendarOpen, setCalendarOpen] = useState(false);

  useEffect(() => {
    if (initial) return;
    const range = nextMonthRange(new Date());
    setDateFrom(range.from);
    setDateTo(range.to);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!initial) return;
    setOrigin(initial.origin);
    setDest(initial.dest);
    setDateFrom(initial.date_from);
    setDateTo(initial.date_to);
    setRoundTrip(initial.round_trip);
    if (initial.trip_min_days != null) setTripMinDays(initial.trip_min_days);
    if (initial.trip_max_days != null) setTripMaxDays(initial.trip_max_days);
    setStopMaxDays(initial.stop_max_days);
    setMaxStops(initial.max_stops);
  }, [initial]);

  const valid =
    origin.length === 3 && dest.length === 3 && !!dateFrom && !!dateTo && dateFrom <= dateTo;
  const missing = [
    origin.length !== 3 && STR.form.missingOrigin,
    dest.length !== 3 && STR.form.missingDest,
    (!dateFrom || !dateTo) && STR.form.missingDates,
    dateFrom && dateTo && dateFrom > dateTo && STR.form.missingDateOrder,
  ]
    .filter(Boolean)
    .join(", ");

  const range: DateRange | undefined = dateFrom
    ? { from: parseIso(dateFrom), to: parseIso(dateTo) }
    : undefined;

  function setRange(r: DateRange | undefined) {
    setDateFrom(r?.from ? isoDate(r.from) : "");
    setDateTo(r?.to ? isoDate(r.to) : r?.from ? isoDate(r.from) : "");
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid) return;
    onSearch({
      origin,
      dest,
      date_from: dateFrom,
      date_to: dateTo,
      round_trip: roundTrip,
      trip_min_days: roundTrip ? tripMinDays : null,
      trip_max_days: roundTrip ? tripMaxDays : null,
      stop_min_hours: SEARCH_DEFAULTS.stop_min_hours,
      stop_max_days: stopMaxDays,
      max_stops: maxStops,
      top_k: SEARCH_DEFAULTS.top_k,
    });
  }

  return (
    <form
      onSubmit={submit}
      data-testid="search-form"
      className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 shadow-2xl backdrop-blur"
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-[1fr_auto_1fr]">
        <AirportInput label={STR.form.from} value={origin} onChange={setOrigin} testId="search-origin" />
        <motion.button
          type="button"
          data-testid="search-swap"
          aria-label={STR.form.swap}
          animate={{ rotate: swapCount * 180 }}
          transition={{ type: "spring", stiffness: 260, damping: 20 }}
          onClick={() => {
            setSwapCount((c) => c + 1);
            setOrigin(dest);
            setDest(origin);
          }}
          className="mt-7 hidden h-10 w-10 items-center justify-center self-start rounded-full border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:flex"
        >
          <ArrowLeftRight size={16} />
        </motion.button>
        <AirportInput label={STR.form.to} value={dest} onChange={setDest} testId="search-dest" />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="sm:col-span-2">
          <Label className="mb-1 block text-xs font-medium uppercase tracking-wider text-slate-400">
            {STR.form.dates}
          </Label>
          <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
            <PopoverTrigger asChild>
              <Button
                type="button"
                variant="outline"
                data-testid="search-dates"
                className="h-11 w-full justify-start rounded-xl border-slate-700 bg-slate-900/80 text-sm font-normal hover:bg-slate-800"
              >
                <CalendarDays size={15} className="text-slate-400" />
                {dateFrom && dateTo ? (
                  <span>
                    {formatDate(dateFrom)} → {formatDate(dateTo)}
                  </span>
                ) : (
                  <span className="text-slate-500">{STR.form.pickDates}</span>
                )}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto border-slate-700 bg-slate-900 p-2">
              <div className="flex gap-2 px-1 pb-2 pt-1">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="text-xs"
                  onClick={() => {
                    const r = nextMonthRange(new Date());
                    setDateFrom(r.from);
                    setDateTo(r.to);
                  }}
                >
                  {STR.form.presetNextMonth}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="text-xs"
                  onClick={() => {
                    const r = summerRange(new Date());
                    setDateFrom(r.from);
                    setDateTo(r.to);
                  }}
                >
                  {STR.form.presetSummer}
                </Button>
              </div>
              <Calendar
                mode="range"
                numberOfMonths={2}
                selected={range}
                onSelect={setRange}
                defaultMonth={range?.from}
                disabled={{ before: new Date() }}
              />
            </PopoverContent>
          </Popover>
        </div>
        <div>
          <Label className="mb-1 block text-xs font-medium uppercase tracking-wider text-slate-400">
            {STR.form.maxStopoverNights}: {stopMaxDays}
          </Label>
          <Slider
            aria-label={STR.form.maxStopoverNights}
            min={0}
            max={14}
            step={1}
            value={[stopMaxDays]}
            onValueChange={([v]) => setStopMaxDays(v)}
            className="mt-4"
          />
        </div>
        <div>
          <Label className="mb-1 block text-xs font-medium uppercase tracking-wider text-slate-400">
            {STR.form.maxStops}: {maxStops}
          </Label>
          <Slider
            aria-label={STR.form.maxStops}
            min={0}
            max={4}
            step={1}
            value={[maxStops]}
            onValueChange={([v]) => setMaxStops(v)}
            className="mt-4"
          />
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-4">
        <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-300">
          <Switch checked={roundTrip} onCheckedChange={setRoundTrip} aria-label={STR.form.roundTrip} />
          {STR.form.roundTrip}
        </label>
        {roundTrip && (
          <div className="flex items-center gap-2 text-sm text-slate-300">
            {STR.form.stay}
            <Input
              type="number"
              aria-label="Minimum stay in days"
              min={1}
              max={60}
              value={tripMinDays}
              onChange={(e) => setTripMinDays(Number(e.target.value))}
              className="h-9 w-16 rounded-lg border-slate-700 bg-slate-900 text-center"
            />
            {STR.form.stayTo}
            <Input
              type="number"
              aria-label="Maximum stay in days"
              min={1}
              max={90}
              value={tripMaxDays}
              onChange={(e) => setTripMaxDays(Number(e.target.value))}
              className="h-9 w-16 rounded-lg border-slate-700 bg-slate-900 text-center"
            />
            {STR.form.stayDays}
          </div>
        )}
        <div className="ml-auto flex items-center gap-3">
          {!valid && !busy && missing && (
            <span className="text-xs text-slate-500">
              {STR.form.missing} {missing}
            </span>
          )}
          <Button
            type="submit"
            data-testid="search-submit"
            disabled={!valid || busy}
            className="h-11 rounded-xl bg-emerald-500 px-6 text-sm font-semibold text-slate-950 hover:bg-emerald-400"
          >
            <Search size={16} />
            {busy ? STR.form.submitBusy : STR.form.submit}
          </Button>
        </div>
      </div>
    </form>
  );
}
