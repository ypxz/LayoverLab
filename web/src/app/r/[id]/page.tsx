"use client";

import { ArrowLeft, BadgeCheck, Clock, Link2, Loader2, Share2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import RouteDetail from "@/components/RouteDetail";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchItinerary, type Itinerary } from "@/lib/api";
import { freshness } from "@/lib/format";
import { STR } from "@/lib/strings";

export default function SharedItinerary({ params }: { params: { id: string } }) {
  const [itin, setItin] = useState<Itinerary | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetchItinerary(params.id)
      .then(setItin)
      .catch(() => setError(true));
  }, [params.id]);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      toast.success(STR.permalink.copied);
    } catch {
      toast.error(STR.card.shareError);
    }
  }

  async function nativeShare() {
    try {
      await navigator.share({ title: STR.permalink.title, url: window.location.href });
    } catch {
      // user cancelled or share unsupported — no-op
    }
  }

  const oldestFetch = itin
    ? itin.legs.reduce(
        (min, leg) => (leg.fetched_at < min ? leg.fetched_at : min),
        itin.legs[0]?.fetched_at ?? "",
      )
    : "";

  return (
    <main data-testid="permalink-root">
      <Link
        href="/"
        className="mb-6 inline-flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200"
      >
        <ArrowLeft size={14} /> {STR.permalink.back}
      </Link>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">{STR.permalink.title}</h1>
        {itin && (
          <div className="ml-auto flex items-center gap-2">
            {itin.verified ? (
              <span
                data-testid="verified-badge"
                className="flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-1 text-[11px] font-medium text-emerald-300"
              >
                <BadgeCheck size={12} /> {STR.card.verifiedNow}
              </span>
            ) : (
              <span className="flex items-center gap-1 rounded-full bg-slate-700/40 px-2 py-1 text-[11px] font-medium text-slate-400">
                <Clock size={12} /> {STR.card.cached}{" "}
                {oldestFetch ? freshness(oldestFetch) : ""}
              </span>
            )}
            <Button
              type="button"
              size="sm"
              variant="secondary"
              data-testid="share-button"
              onClick={copyLink}
              className="h-8 gap-1.5 text-xs"
            >
              <Link2 size={12} /> {STR.permalink.copyLink}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={nativeShare}
              className="h-8 gap-1.5 text-xs"
            >
              <Share2 size={12} /> {STR.permalink.nativeShare}
            </Button>
          </div>
        )}
      </div>
      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {STR.permalink.notFound}
        </div>
      )}
      {!itin && !error && (
        <div className="space-y-3" aria-live="polite">
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="animate-spin" size={16} /> {STR.permalink.loading}
          </div>
          <Skeleton className="h-40 w-full rounded-2xl bg-slate-800/60" />
          <Skeleton className="h-12 w-full rounded-xl bg-slate-800/60" />
        </div>
      )}
      {itin && <RouteDetail itin={itin} />}
      {itin && <p className="mt-4 text-xs text-slate-500">{STR.permalink.reverified}</p>}
    </main>
  );
}
