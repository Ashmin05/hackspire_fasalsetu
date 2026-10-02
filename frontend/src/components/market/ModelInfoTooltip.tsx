"use client";



import { useId, useState } from "react";
import { Info } from "lucide-react";
import type { ForecastModelInfo } from "@/lib/api/market-client";
import { longDate, MODEL_LABELS } from "./format";

export default function ModelInfoTooltip({ models }: { models: ForecastModelInfo[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!models.length) return null;
  const sorted = [...models].sort((a, b) => a.horizon_days - b.horizon_days);

  return (
    <span className="relative inline-flex" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        aria-label="About the forecast model"
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        // Focus already opens it (a click focuses first), so a click must not toggle it shut.
        onClick={() => setOpen(true)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className="inline-flex items-center gap-1 text-[11px] font-semibold text-farm-muted hover:text-farm-dark rounded-full px-1.5 py-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-farm-green"
      >
        <Info className="w-3.5 h-3.5" /> Model
      </button>
      {open && (
        <div
          id={id}
          role="tooltip"
          className="absolute right-0 top-full mt-1.5 z-30 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-farm-border-color bg-white p-3 shadow-lg text-[11px] text-farm-dark space-y-2"
        >
          <p className="font-bold text-xs">Forecast model</p>
          <table className="w-full">
            <thead>
              <tr className="text-left text-farm-muted">
                <th className="font-semibold pb-1">Horizon</th>
                <th className="font-semibold pb-1">Version</th>
                <th className="font-semibold pb-1">Trained</th>
                <th className="font-semibold pb-1 text-right">MAPE</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((m) => (
                <tr key={m.horizon_days} className="align-top">
                  <td className="py-0.5 pr-2 whitespace-nowrap">{m.horizon_days} days</td>
                  <td className="py-0.5 pr-2 font-mono text-[10px] break-all">{m.model_version}</td>
                  <td className="py-0.5 pr-2 whitespace-nowrap">{longDate(m.trained_at)}</td>
                  <td className="py-0.5 text-right whitespace-nowrap">{m.validation.mape !== null ? `${m.validation.mape.toFixed(1)}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            <span className="text-farm-muted">Model:</span>{" "}
            {Array.from(new Set(sorted.map((m) => MODEL_LABELS[m.model_name] ?? m.model_name))).join(" / ")}
          </p>
          <p className="text-farm-muted">
            MAPE is the average % error when the model was tested on past prices it hadn&apos;t seen
            (training data {longDate(sorted[0].training_period.from)} – {longDate(sorted[0].training_period.to)}).
          </p>
        </div>
      )}
    </span>
  );
}
