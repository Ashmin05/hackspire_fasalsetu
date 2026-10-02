"use client";



import { useEffect, useState } from "react";
import { FarmSatellite } from "@/lib/stores/farmStore";
import SeasonCurveChart, { SeasonCurvePoint } from "@/components/charts/SeasonCurveChart";
import {
  Leaf, TrendingDown, TrendingUp, Droplets, AlertTriangle,
  CheckCircle2, Activity, MoonStar, RefreshCw, ChevronDown, ChevronUp
} from "lucide-react";

const MAX_VISIBLE_STRESS_ZONES = 3;

export type SatelliteMapLayer = "rgb" | "ndvi" | "ndwi" | "evi" | "stress";

function CanopyDonut({ satellite }: { satellite: FarmSatellite }) {
  const radius = 46;
  const strokeWidth = 16;
  const circumference = 2 * Math.PI * radius;

  const segments = [
    { pct: satellite.healthyCanopyPercent, color: "#10b981" }, // emerald-500
    { pct: satellite.moderateCanopyPercent, color: "#fbbf24" }, // amber-400
    { pct: satellite.stressedCanopyPercent, color: "#ef4444" }, // red-500
  ];

  let cumulativePct = 0;

  return (
    <div className="flex items-center justify-center gap-6">
      <div className="relative w-32 h-32 flex-shrink-0">
        <svg viewBox="0 0 120 120" className="w-32 h-32 -rotate-90">
          <circle cx="60" cy="60" r={radius} fill="none" stroke="#f1f5f4" strokeWidth={strokeWidth} />
          {segments.map((seg, idx) => {
            if (seg.pct <= 0) return null;
            const segLength = (seg.pct / 100) * circumference;
            const offset = -((cumulativePct / 100) * circumference);
            cumulativePct += seg.pct;
            return (
              <circle
                key={idx}
                cx="60"
                cy="60"
                r={radius}
                fill="none"
                stroke={seg.color}
                strokeWidth={strokeWidth}
                strokeDasharray={`${segLength} ${circumference - segLength}`}
                strokeDashoffset={offset}
                strokeLinecap="butt"
              />
            );
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-2xl font-extrabold text-farm-dark">{satellite.healthyCanopyPercent}%</span>
          <span className="text-[11px] text-farm-muted font-medium">Healthy</span>
        </div>
      </div>

      <div className="space-y-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: "#10b981" }} />
          <span className="text-farm-muted">Healthy</span>
          <span className="font-bold text-farm-dark ml-auto">{satellite.healthyCanopyPercent}%</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: "#fbbf24" }} />
          <span className="text-farm-muted">Moderate</span>
          <span className="font-bold text-farm-dark ml-auto">{satellite.moderateCanopyPercent}%</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: "#ef4444" }} />
          <span className="text-farm-muted">Stressed</span>
          <span className="font-bold text-farm-dark ml-auto">{satellite.stressedCanopyPercent}%</span>
        </div>
      </div>
    </div>
  );
}

function LoadError({
  message,
  onRetry,
  className = "",
}: {
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={`p-6 flex flex-col items-center justify-center gap-2 text-center text-xs text-red-900 bg-red-50 border border-red-200 rounded-xl ${className}`}
    >
      <AlertTriangle className="w-5 h-5 text-red-600" />
      <p>{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-red-300 bg-white font-semibold hover:bg-red-100"
        >
          <RefreshCw className="w-3.5 h-3.5" /> Retry
        </button>
      )}
    </div>
  );
}

export interface PanelStressZone {
  id: string;
  name: string;
  typeLabel: string;
  areaAcres: number;
  description?: string;
  action: string;
}

export default function SatelliteAnalyticsPanel({
  areaAcres,
  satellite,
  seasonCurve,
  stressZones,
}: {
  areaAcres: number;
  /** Current stats (NDVI/NDWI/canopy %) — live or demo, as the page decides. */
  satellite: FarmSatellite;
  seasonCurve: {
    points: SeasonCurvePoint[];
    /** Shown instead of the chart when there are no points yet. */
    emptyMessage?: string;
    selectedKey?: string;
    onSelectPoint?: (point: SeasonCurvePoint) => void;
    /** Set when the timeseries failed to load -- shown instead of the empty message. */
    error?: string | null;
    onRetry?: () => void;
  };
  stressZones: {
    items: PanelStressZone[];
    isLoading?: boolean;
    /** Set when the zones failed to load -- never shown as "no zones detected". */
    error?: string | null;
    onRetry?: () => void;
  };
}) {
  const curve = seasonCurve.points;
  const latest = curve[curve.length - 1];

  const [showAllZones, setShowAllZones] = useState(false);
  const zoneIdsKey = stressZones.items.map((z) => z.id).join(",");
  useEffect(() => {
    setShowAllZones(false);
  }, [zoneIdsKey]);
  const visibleZones = showAllZones ? stressZones.items : stressZones.items.slice(0, MAX_VISIBLE_STRESS_ZONES);
  const hiddenZoneCount = stressZones.items.length - MAX_VISIBLE_STRESS_ZONES;

  return (
    <div className="space-y-6">
      {/* ── Current Statistics ── */}
      <div className="bg-white rounded-2xl border border-farm-border-color p-5 shadow-xs">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div>
            <h3 className="font-bold text-farm-dark text-sm flex items-center gap-2">
              <Activity className="w-4 h-4 text-farm-green" />
              Current NDVI & Canopy Statistics
            </h3>
            <p className="text-xs text-farm-muted">Quantitative remote sensing metrics calculated across {areaAcres} acres</p>
          </div>
          <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-emerald-100 text-emerald-800">
            Health vs. crop stage: {satellite.canopyVigourLabel}
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="p-3.5 bg-farm-gray rounded-xl text-center">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center mx-auto mb-1.5">
              <Leaf className="w-4 h-4" />
            </div>
            <p className="text-xs text-farm-muted">Mean NDVI</p>
            <p className="text-xl font-bold text-farm-dark">{satellite.meanNdvi.toFixed(2)}</p>
          </div>

          <div className="p-3.5 bg-farm-gray rounded-xl text-center">
            <div className="w-8 h-8 rounded-lg bg-red-100 text-red-600 flex items-center justify-center mx-auto mb-1.5">
              <TrendingDown className="w-4 h-4" />
            </div>
            <p className="text-xs text-farm-muted">Min NDVI</p>
            <p className="text-xl font-bold text-farm-dark">{satellite.minNdvi.toFixed(2)}</p>
          </div>

          <div className="p-3.5 bg-farm-gray rounded-xl text-center">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center mx-auto mb-1.5">
              <TrendingUp className="w-4 h-4" />
            </div>
            <p className="text-xs text-farm-muted">Max NDVI</p>
            <p className="text-xl font-bold text-farm-dark">{satellite.maxNdvi.toFixed(2)}</p>
          </div>

          <div className="p-3.5 bg-sky-50 rounded-xl text-center border border-sky-200/60">
            <div className="w-8 h-8 rounded-lg bg-sky-100 text-sky-700 flex items-center justify-center mx-auto mb-1.5">
              <Droplets className="w-4 h-4" />
            </div>
            <p className="text-xs text-sky-700">Mean NDWI</p>
            <p className="text-xl font-bold text-sky-900">{satellite.ndwi.toFixed(2)}</p>
            <span className="text-[10px] text-sky-600 font-semibold">{satellite.ndwi < 0 ? "Dry" : "Optimal"}</span>
          </div>
        </div>
      </div>

      {/* ── Season Curve + Canopy Health Distribution, side by side ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-2xl border border-farm-border-color p-5 shadow-xs">
          <div className="flex flex-wrap items-start justify-between gap-2 mb-3">
            <div>
              <h3 className="font-bold text-farm-dark text-sm flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-emerald-600" />
                NDVI Season Curve
              </h3>
              <p className="text-[11px] text-farm-muted">One dot per clear satellite pass</p>
            </div>
          </div>

          {seasonCurve.error ? (
            <LoadError message={seasonCurve.error} onRetry={seasonCurve.onRetry} className="h-[220px]" />
          ) : curve.length > 0 ? (
            <>
              <SeasonCurveChart
                points={curve}
                selectedKey={seasonCurve.selectedKey}
                onSelectPoint={seasonCurve.onSelectPoint}
              />
              <div className="flex items-center gap-4 text-[11px] mt-2">
                <span className="flex items-center gap-1.5 font-semibold text-farm-dark">
                  <span className="w-3 h-1 bg-emerald-600 rounded-full" /> Your field
                </span>
                <span className="flex items-center gap-1.5 text-farm-muted">
                  <span className="w-3 border-t-2 border-dashed border-slate-400" /> Crop-stage benchmark
                </span>
              </div>
              {latest && (
                <div className="mt-3 p-2.5 bg-emerald-50/60 rounded-xl border border-emerald-200/60 text-[11px] flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                  <span>
                    Latest: <strong>{latest.label}</strong>
                    {latest.stage && <> · {latest.stage}</>}
                  </span>
                  <span>
                    NDVI <strong className="text-emerald-800">{latest.ndvi.toFixed(2)}</strong>{" "}
                    <span className="text-farm-muted">vs. benchmark {latest.benchmark.toFixed(2)}</span>
                  </span>
                </div>
              )}
            </>
          ) : (
            <div className="h-[220px] flex flex-col items-center justify-center gap-2 text-center text-xs text-farm-muted bg-farm-gray rounded-xl px-6">
              <MoonStar className="w-5 h-5" />
              {seasonCurve.emptyMessage ?? "No clear satellite passes yet."}
            </div>
          )}
        </div>

        <div className="bg-white rounded-2xl border border-farm-border-color p-5 shadow-xs flex flex-col">
          <div className="flex flex-wrap items-start justify-between gap-2 mb-4">
            <h3 className="font-bold text-farm-dark text-sm flex items-center gap-2">
              <Leaf className="w-4 h-4 text-farm-green" />
              Canopy Health Distribution
            </h3>
          </div>
          <div className="flex-1 flex items-center justify-center py-2">
            <CanopyDonut satellite={satellite} />
          </div>
        </div>
      </div>

      {/* ── Stress Zones Diagnostics ── */}
      <div className="bg-white rounded-2xl border border-farm-border-color p-5 shadow-xs">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div>
            <h3 className="font-bold text-farm-dark text-sm flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-500" />
              Detected Field Stress Zones
            </h3>
            <p className="text-xs text-farm-muted">Automated satellite anomaly classification per field segment</p>
          </div>
          {!stressZones.isLoading && !stressZones.error && (
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800">
            {stressZones.items.length} {stressZones.items.length === 1 ? "Zone" : "Zones"} Detected
          </span>
          )}
        </div>

        {stressZones.error ? (
          <LoadError message={stressZones.error} onRetry={stressZones.onRetry} />
        ) : stressZones.isLoading ? (
          <div className="p-6 text-center text-xs text-farm-muted bg-farm-gray rounded-xl">
            Loading stress zones for this pass…
          </div>
        ) : stressZones.items.length > 0 ? (
          <div className="space-y-3">
            {visibleZones.map((zone) => (
              <div key={zone.id} className="p-4 rounded-xl border border-amber-200 bg-amber-50/50 space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm text-farm-dark">{zone.name}</span>
                    <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-amber-200 text-amber-900">
                      {zone.typeLabel}
                    </span>
                  </div>
                  <span className="text-xs text-farm-muted font-medium">{zone.areaAcres} acres</span>
                </div>
                {zone.description && <p className="text-xs text-amber-950 font-medium">{zone.description}</p>}
                <p className="text-xs text-emerald-800 font-semibold flex items-center gap-1.5 pt-1">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Action: {zone.action}
                </p>
              </div>
            ))}
            {hiddenZoneCount > 0 && (
              <button
                onClick={() => setShowAllZones((v) => !v)}
                className="w-full flex items-center justify-center gap-1.5 text-xs font-semibold text-farm-green hover:text-farm-green-dark py-2 rounded-xl border border-dashed border-farm-border-color hover:border-farm-green transition-colors"
              >
                {showAllZones ? (
                  <>
                    <ChevronUp className="w-3.5 h-3.5" /> Show less
                  </>
                ) : (
                  <>
                    <ChevronDown className="w-3.5 h-3.5" /> See {hiddenZoneCount} more {hiddenZoneCount === 1 ? "zone" : "zones"}
                  </>
                )}
              </button>
            )}
          </div>
        ) : (
          <div className="p-6 text-center text-xs text-farm-muted bg-farm-gray rounded-xl">
            No severe vegetation anomalies detected across this farm.
          </div>
        )}
      </div>
    </div>
  );
}
