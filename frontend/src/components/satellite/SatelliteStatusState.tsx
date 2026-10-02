"use client";

import { AlertTriangle, CloudOff, Loader2, RefreshCw, Satellite } from "lucide-react";
import type { SatelliteStatus } from "@/lib/hooks/useFarmSatelliteAnalysis";

/**
 * The non-"ready" states of a real farm's satellite analysis: checking the
 * cache, the first live analysis running, no clear image yet, or an error
 * with a retry. Renders nothing for "ready"/"guest" -- the caller shows data.
 */
export default function SatelliteStatusState({
  status,
  error,
  onRetry,
  compact = false,
}: {
  status: SatelliteStatus;
  error?: string | null;
  onRetry?: () => void;
  compact?: boolean;
}) {
  if (status === "ready" || status === "guest") return null;

  const box = compact
    ? "flex items-start gap-2.5 text-xs"
    : "rounded-2xl border p-6 flex flex-col items-center text-center gap-2";

  if (status === "checking") {
    return (
      <div className={`${box} ${compact ? "" : "bg-white border-farm-border-color"}`}>
        <Loader2 className={`${compact ? "w-4 h-4" : "w-6 h-6"} text-farm-muted animate-spin flex-shrink-0`} />
        <p className="text-farm-muted font-medium">Checking for your latest satellite analysis…</p>
      </div>
    );
  }

  if (status === "analysing") {
    return (
      <div className={`${box} ${compact ? "" : "bg-emerald-50 border-emerald-200"}`} role="status" aria-live="polite">
        <span className={`relative flex-shrink-0 ${compact ? "" : "mb-1"}`}>
          <Satellite className={`${compact ? "w-4 h-4" : "w-8 h-8"} text-farm-green animate-pulse`} />
        </span>
        <div>
          <p className="font-bold text-farm-dark">Analysing your field from space… ~30 s</p>
          <p className="text-farm-muted mt-0.5">
            Finding the clearest recent Sentinel-2 image of your field and measuring crop health.
          </p>
        </div>
      </div>
    );
  }

  if (status === "no-imagery") {
    return (
      <div className={`${box} ${compact ? "" : "bg-amber-50 border-amber-200"}`}>
        <CloudOff className={`${compact ? "w-4 h-4" : "w-8 h-8"} text-amber-600 flex-shrink-0`} />
        <div>
          <p className="font-bold text-amber-950">No clear satellite image yet</p>
          <p className="text-amber-900 mt-0.5">
            Sentinel-2 hasn&apos;t captured a usable image of this field recently. New passes are checked every
            night — try again in a few days.
          </p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-amber-900 hover:underline"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Check again
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={`${box} ${compact ? "" : "bg-red-50 border-red-200"}`} role="alert">
      <AlertTriangle className={`${compact ? "w-4 h-4" : "w-8 h-8"} text-red-600 flex-shrink-0`} />
      <div>
        <p className="font-bold text-red-900">Couldn&apos;t load satellite analysis</p>
        {error && <p className="text-red-800 mt-0.5">{error}</p>}
        {onRetry && (
          <button
            onClick={onRetry}
            className={`mt-2 inline-flex items-center gap-1.5 font-semibold rounded-lg border border-red-300 bg-white text-red-800 hover:bg-red-100 transition-colors ${
              compact ? "px-2 py-1 text-[11px]" : "px-3 py-1.5 text-xs"
            }`}
          >
            <RefreshCw className="w-3.5 h-3.5" /> Retry
          </button>
        )}
      </div>
    </div>
  );
}
