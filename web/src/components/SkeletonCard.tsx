import { Skeleton } from "@/components/ui/skeleton";

export default function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4" aria-hidden>
      <div className="flex items-center gap-3">
        <Skeleton className="h-4 w-6 bg-slate-800" />
        <Skeleton className="h-10 w-48 bg-slate-800" />
        <Skeleton className="h-10 w-40 bg-slate-800" />
        <div className="ml-auto flex items-center gap-3">
          <Skeleton className="h-5 w-20 rounded-full bg-slate-800" />
          <Skeleton className="h-7 w-16 bg-slate-800" />
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Skeleton className="h-4 w-32 bg-slate-800" />
        <Skeleton className="h-4 w-16 bg-slate-800" />
      </div>
    </div>
  );
}
