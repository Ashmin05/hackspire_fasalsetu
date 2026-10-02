"use client";

import { CalendarRange } from "lucide-react";
import { formatCloudPct, formatPassDate } from "@/components/SourceBadge";

export interface SatellitePass {
  date: string; // ISO date
  cloudPct: number | null;
}

/**
 * Steps through every available clear Sentinel-2 pass (oldest → newest);
 * the parent swaps the map's tile layers to the selected pass's date.
 */
export default function PassDateSlider({
  passes,
  value,
  onChange,
  isLoading = false,
}: {
  passes: SatellitePass[];
  value: string;
  onChange: (date: string) => void;
  isLoading?: boolean;
}) {
  if (passes.length < 2) return null;

  const index = Math.max(0, passes.findIndex((p) => p.date === value));
  const current = passes[index];

  return (
    <div className="bg-white rounded-2xl border border-farm-border-color px-4 py-3 shadow-xs">
      <div className="flex items-center justify-between gap-3 mb-2">
        <label htmlFor="pass-date-slider" className="text-xs font-bold text-farm-dark flex items-center gap-1.5">
          <CalendarRange className="w-3.5 h-3.5 text-farm-green" />
          Satellite pass
        </label>
        <span className="text-xs text-farm-muted">
          <strong className="text-farm-dark">{formatPassDate(current.date)}</strong>
          {current.cloudPct !== null && <> · cloud {formatCloudPct(current.cloudPct)}</>}
          {" "}· {index + 1} of {passes.length}
          {isLoading && " · loading…"}
        </span>
      </div>
      <input
        id="pass-date-slider"
        type="range"
        min={0}
        max={passes.length - 1}
        step={1}
        value={index}
        onChange={(e) => onChange(passes[Number(e.target.value)].date)}
        className="w-full accent-farm-green cursor-pointer"
        aria-valuetext={formatPassDate(current.date)}
      />
      <div className="flex justify-between text-[10px] text-farm-muted mt-0.5">
        <span>{formatPassDate(passes[0].date)}</span>
        <span>{formatPassDate(passes[passes.length - 1].date)}</span>
      </div>
    </div>
  );
}
