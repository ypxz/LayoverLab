"use client";

import { useEffect, useRef, useState } from "react";
import { autocompleteAirports, type AirportOut } from "@/lib/api";

interface Props {
  label: string;
  value: string;
  onChange: (iata: string) => void;
}

export default function AirportInput({ label, value, onChange }: Props) {
  const [query, setQuery] = useState(value);
  const [options, setOptions] = useState<AirportOut[]>([]);
  const [open, setOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (value && value !== query) setQuery(value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  useEffect(() => {
    if (query.length < 2 || query === value) {
      setOptions([]);
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const timer = setTimeout(() => {
      autocompleteAirports(query, controller.signal)
        .then((res) => {
          setOptions(res);
          setOpen(true);
        })
        .catch(() => undefined);
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, value]);

  return (
    <div className="relative">
      <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-slate-400">
        {label}
      </label>
      <input
        value={query}
        onChange={(e) => {
          const v = e.target.value.toUpperCase();
          setQuery(v);
          onChange(/^[A-Z]{3}$/.test(v) ? v : "");
        }}
        onFocus={() => options.length > 0 && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="City, airport or IATA"
        className="w-full rounded-xl border border-slate-700 bg-slate-900/80 px-3 py-2.5 text-sm outline-none ring-emerald-500/50 placeholder:text-slate-600 focus:ring-2"
      />
      {open && options.length > 0 && (
        <ul className="absolute z-20 mt-1 w-full overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-xl">
          {options.map((opt) => (
            <li key={opt.iata}>
              <button
                type="button"
                onMouseDown={() => {
                  onChange(opt.iata);
                  setQuery(opt.iata);
                  setOpen(false);
                }}
                className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-800"
              >
                <span>
                  <span className="font-semibold text-emerald-400">{opt.iata}</span>{" "}
                  <span className="text-slate-300">{opt.name}</span>
                </span>
                <span className="text-xs text-slate-500">
                  {opt.city} · {opt.country_code}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
