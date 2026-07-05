"use client";

import { History } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { autocompleteAirports, type AirportOut } from "@/lib/api";
import { addRecentAirport, getRecentAirports } from "@/lib/recent";
import { STR } from "@/lib/strings";
import { cn } from "@/lib/utils";

interface Props {
  label: string;
  value: string;
  onChange: (iata: string) => void;
  testId: string;
}

export default function AirportInput({ label, value, onChange, testId, ...rest }: Props) {
  const [query, setQuery] = useState(value);
  const [options, setOptions] = useState<AirportOut[]>([]);
  const [recents, setRecents] = useState<AirportOut[]>([]);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(-1);
  const abortRef = useRef<AbortController | null>(null);
  const listboxId = useId();
  const inputId = useId();

  useEffect(() => {
    if (value && value !== query) setQuery(value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  useEffect(() => {
    if (query.length < 2 || query === value) {
      setOptions([]);
      setHighlight(-1);
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const timer = setTimeout(() => {
      autocompleteAirports(query, controller.signal)
        .then((res) => {
          setOptions(res);
          setHighlight(res.length > 0 ? 0 : -1);
          setOpen(true);
        })
        .catch(() => undefined);
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, value]);

  const showRecents = query.length < 2 && recents.length > 0;
  const visible: AirportOut[] = showRecents ? recents : options;
  const listOpen = open && visible.length > 0;

  function select(opt: AirportOut) {
    onChange(opt.iata);
    setQuery(opt.iata);
    setOpen(false);
    setHighlight(-1);
    addRecentAirport(opt);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!listOpen) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => (h + 1) % visible.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => (h - 1 + visible.length) % visible.length);
    } else if (e.key === "Enter" && highlight >= 0) {
      e.preventDefault();
      select(visible[highlight]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="relative">
      <Label
        htmlFor={inputId}
        className="mb-1 block text-xs font-medium uppercase tracking-wider text-slate-400"
      >
        {label}
      </Label>
      <Input
        id={inputId}
        data-testid={testId}
        value={query}
        role="combobox"
        aria-expanded={listOpen}
        aria-controls={listboxId}
        aria-activedescendant={highlight >= 0 ? `${listboxId}-${highlight}` : undefined}
        aria-autocomplete="list"
        autoComplete="off"
        onChange={(e) => {
          const v = e.target.value.toUpperCase();
          setQuery(v);
          onChange(/^[A-Z]{3}$/.test(v) ? v : "");
        }}
        onKeyDown={onKeyDown}
        onFocus={() => {
          setRecents(getRecentAirports());
          setOpen(true);
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={STR.form.airportPlaceholder}
        className="h-11 rounded-xl border-slate-700 bg-slate-900/80 text-sm placeholder:text-slate-600"
        {...rest}
      />
      {listOpen && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label={label}
          className="absolute z-20 mt-1 w-full overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-xl"
        >
          {showRecents && (
            <li
              aria-hidden
              className="flex items-center gap-1.5 px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500"
            >
              <History size={11} /> {STR.form.recentSearches}
            </li>
          )}
          {visible.map((opt, i) => (
            <li
              key={opt.iata}
              id={`${listboxId}-${i}`}
              role="option"
              aria-selected={i === highlight}
            >
              <button
                type="button"
                tabIndex={-1}
                onMouseDown={() => select(opt)}
                onMouseEnter={() => setHighlight(i)}
                className={cn(
                  "flex w-full items-center justify-between px-3 py-2 text-left text-sm",
                  i === highlight ? "bg-slate-800" : "hover:bg-slate-800",
                )}
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
