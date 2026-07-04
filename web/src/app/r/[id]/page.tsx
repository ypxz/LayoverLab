"use client";

import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import RouteCard from "@/components/RouteCard";
import { fetchItinerary, type Itinerary } from "@/lib/api";

export default function SharedItinerary({ params }: { params: { id: string } }) {
  const [itin, setItin] = useState<Itinerary | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetchItinerary(params.id)
      .then(setItin)
      .catch(() => setError(true));
  }, [params.id]);

  return (
    <main>
      <Link
        href="/"
        className="mb-6 inline-flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200"
      >
        <ArrowLeft size={14} /> New search
      </Link>
      <h1 className="mb-4 text-2xl font-bold">Shared itinerary</h1>
      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          This itinerary does not exist (or the API is unreachable).
        </div>
      )}
      {!itin && !error && (
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="animate-spin" size={16} /> Loading and re-verifying prices…
        </div>
      )}
      {itin && <RouteCard itin={itin} rank={1} />}
      {itin && (
        <p className="mt-4 text-xs text-slate-500">
          Prices were re-checked when you opened this link. The original snapshot may have differed.
        </p>
      )}
    </main>
  );
}
