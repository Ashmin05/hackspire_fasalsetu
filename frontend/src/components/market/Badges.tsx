// Labels that say what kind of number is on screen: "Live" for prices mandis
// actually reported, "Estimate" for anything a model predicted.

export function LiveBadge({ asOf }: { asOf?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-[10px] uppercase font-bold tracking-wide text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-600" aria-hidden />
      Live{asOf ? ` · ${asOf}` : ""}
    </span>
  );
}

export function EstimateBadge() {
  return (
    <span className="inline-flex items-center text-[10px] uppercase font-bold tracking-wide text-sky-700 bg-sky-50 border border-sky-200 border-dashed rounded-full px-2 py-0.5">
      Estimate
    </span>
  );
}
