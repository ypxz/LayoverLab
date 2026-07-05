"use client";

import { useEffect, useState } from "react";
import { autocompleteAirports, type AirportOut } from "@/lib/api";

const cache = new Map<string, AirportOut | null>();
const pending = new Map<string, Promise<AirportOut | null>>();

async function lookup(iata: string): Promise<AirportOut | null> {
  if (cache.has(iata)) return cache.get(iata) ?? null;
  let promise = pending.get(iata);
  if (!promise) {
    promise = autocompleteAirports(iata)
      .then((res) => res.find((a) => a.iata === iata) ?? null)
      .catch(() => null)
      .then((found) => {
        cache.set(iata, found);
        pending.delete(iata);
        return found;
      });
    pending.set(iata, promise);
  }
  return promise;
}

/** Best-effort airport metadata (city, country) for display; null while loading/unknown. */
export function useAirport(iata: string): AirportOut | null {
  const [airport, setAirport] = useState<AirportOut | null>(cache.get(iata) ?? null);
  useEffect(() => {
    let alive = true;
    lookup(iata).then((found) => {
      if (alive) setAirport(found);
    });
    return () => {
      alive = false;
    };
  }, [iata]);
  return airport;
}
