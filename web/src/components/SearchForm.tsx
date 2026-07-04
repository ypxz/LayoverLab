"use client";

import { ArrowLeftRight, Search } from "lucide-react";
import { useEffect, useState } from "react";
import AirportInput from "@/components/AirportInput";
import type { SearchParams } from "@/lib/api";

interface Props {
  onSearch: (params: SearchParams) => void;
  busy: boolean;
}

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

export default function SearchForm({ onSearch, busy }: Props) {
  const [origin, setOrigin] = useState("");
  const [dest, setDest] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    const now = new Date();
    setDateFrom(isoDate(new Date(now.getFullYear(), now.getMonth() + 1, 1)));
    setDateTo(isoDate(new Date(now.getFullYear(), now.getMonth() + 2, 0)));
  }, []);
  const [roundTrip, setRoundTrip] = useState(false);
  const [tripMinDays, setTripMinDays] = useState(7);
  const [tripMaxDays, setTripMaxDays] = useState(21);
  const [stopMaxDays, setStopMaxDays] = useState(7);
  const [maxStops, setMaxStops] = useState(3);

  const valid =
    origin.length === 3 && dest.length === 3 && !!dateFrom && !!dateTo && dateFrom <= dateTo;
  const missing = [
    origin.length !== 3 && "origin",
    dest.length !== 3 && "destination",
    (!dateFrom || !dateTo) && "dates",
    dateFrom && dateTo && dateFrom > dateTo && "dates (from is after to)",
  ]
    .filter(Boolean)
    .join(", ");

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
      stop_min_hours: 4,
      stop_max_days: stopMaxDays,
      max_stops: maxStops,
      top_k: 10,
    });
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 shadow-2xl backdrop-blur"
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-[1fr_auto_1fr]">
        <AirportInput label="From" value={origin} onChange={setOrigin} />
        <button
          type="button"
          onClick={() => {
            setOrigin(dest);
            setDest(origin);
          }}
          className="mt-6 hidden h-10 w-10 items-center justify-center self-start rounded-full border border-slate-700 text-slate-400 hover:bg-slate-800 sm:flex"
          title="Swap"
        >
          <ArrowLeftRight size={16} />
        </button>
        <AirportInput label="To" value={dest} onChange={setDest} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div>
          <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-slate-400">
            Earliest departure
          </label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="w-full rounded-xl border border-slate-700 bg-slate-900/80 px-3 py-2.5 text-sm outline-none ring-emerald-500/50 focus:ring-2 [color-scheme:dark]"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-slate-400">
            Latest departure
          </label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="w-full rounded-xl border border-slate-700 bg-slate-900/80 px-3 py-2.5 text-sm outline-none ring-emerald-500/50 focus:ring-2 [color-scheme:dark]"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-slate-400">
            Max stopover nights: {stopMaxDays}
          </label>
          <input
            type="range"
            min={0}
            max={14}
            value={stopMaxDays}
            onChange={(e) => setStopMaxDays(Number(e.target.value))}
            className="w-full accent-emerald-500"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-slate-400">
            Max stops: {maxStops}
          </label>
          <input
            type="range"
            min={0}
            max={4}
            value={maxStops}
            onChange={(e) => setMaxStops(Number(e.target.value))}
            className="w-full accent-emerald-500"
          />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4">
        <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={roundTrip}
            onChange={(e) => setRoundTrip(e.target.checked)}
            className="h-4 w-4 accent-emerald-500"
          />
          Round trip
        </label>
        {roundTrip && (
          <div className="flex items-center gap-2 text-sm text-slate-300">
            Stay
            <input
              type="number"
              min={1}
              max={60}
              value={tripMinDays}
              onChange={(e) => setTripMinDays(Number(e.target.value))}
              className="w-16 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-center"
            />
            to
            <input
              type="number"
              min={1}
              max={90}
              value={tripMaxDays}
              onChange={(e) => setTripMaxDays(Number(e.target.value))}
              className="w-16 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-center"
            />
            days
          </div>
        )}
        <div className="ml-auto flex items-center gap-3">
          {!valid && !busy && missing && (
            <span className="text-xs text-slate-500">Missing: {missing}</span>
          )}
          <button
            type="submit"
            disabled={!valid || busy}
            className="flex items-center gap-2 rounded-xl bg-emerald-500 px-6 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Search size={16} />
            {busy ? "Searching…" : "Find weird cheap routes"}
          </button>
        </div>
      </div>
    </form>
  );
}
