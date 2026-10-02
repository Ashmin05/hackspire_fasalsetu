"use client";


import { AlertTriangle, Banknote, Clock, HelpCircle, MapPin, Store } from "lucide-react";
import type { PriceRecommendation } from "@/lib/api/market-client";
import { EstimateBadge } from "./Badges";
import { longDate, pct, rupees } from "./format";

const ACTION_META = {
  hold: { Icon: Clock, className: "text-sky-800 bg-sky-50 border-sky-200" },
  sell_now: { Icon: Banknote, className: "text-emerald-800 bg-emerald-50 border-emerald-200" },
  unavailable: { Icon: HelpCircle, className: "text-farm-muted bg-farm-gray border-farm-border-color" },
} as const;

function signedRupees(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${rupees(Math.abs(value))}`;
}

function Fact({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-farm-border-color p-2.5">
      <p className="text-[10px] uppercase tracking-wide text-farm-muted font-semibold">{label}</p>
      <p className="text-sm font-extrabold text-farm-dark mt-0.5">{value}</p>
      {sub && <p className="text-[10px] text-farm-muted leading-snug">{sub}</p>}
    </div>
  );
}

export default function RecommendationCard({
  rec,
  onSelectMarket,
}: {
  rec: PriceRecommendation;
  onSelectMarket?: (marketId: number) => void;
}) {
  const meta = ACTION_META[rec.action];
  const gain = rec.expected_gain;
  const err = rec.error_range;
  const cost = rec.holding_cost;
  const best = rec.best_nearby;

  return (
    <div className="space-y-3">
      <div className={`flex items-start gap-3 rounded-xl border p-3.5 ${meta.className}`}>
        <meta.Icon className="w-6 h-6 flex-shrink-0 mt-0.5" />
        <div className="min-w-0">
          <p className="text-lg font-extrabold leading-tight">{rec.headline}</p>
          <p className="text-sm mt-1 text-farm-dark">{rec.reason}</p>
          {rec.base_price !== null && rec.market && (
            <p className="text-[11px] text-farm-muted mt-1">
              Compared with {rec.market}&apos;s latest modal price, {rupees(rec.base_price)} on {longDate(rec.base_date)}.
            </p>
          )}
        </div>
      </div>

      {rec.warning && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800" role="note">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-px" />
          <span>{rec.warning}</span>
        </div>
      )}

      {gain && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <Fact
            label={`Expected gain · ${gain.horizon_days} days`}
            value={`${signedRupees(gain.per_quintal)}/q`}
            sub={`${pct(gain.pct)} by ${longDate(gain.by_date)}`}
          />
          <Fact
            label="Error range"
            value={err?.typical_error !== null && err?.typical_error !== undefined ? `± ${rupees(err.typical_error)}` : "—"}
            sub={
              err && err.low !== null && err.high !== null
                ? `${Math.round(err.level * 100)}% range: ${signedRupees(err.low)} to ${signedRupees(err.high)}`
                : "typical error in testing"
            }
          />
          <Fact
            label="Holding cost"
            value={cost?.per_quintal !== null && cost?.per_quintal !== undefined ? `~${rupees(cost.per_quintal)}/q` : "—"}
            sub={cost ? `assumed ${cost.pct_per_30_days}% of value per month${cost.configured ? "" : " (default)"}` : undefined}
          />
        </div>
      )}

      {best && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-farm-border-color px-3 py-2.5">
          <div className="flex items-start gap-2 min-w-0">
            <Store className="w-4 h-4 text-farm-green flex-shrink-0 mt-0.5" />
            <div className="min-w-0 text-xs">
              <p className="text-[10px] uppercase tracking-wide text-farm-muted font-semibold">Best mandi nearby today</p>
              <p className="font-bold text-farm-dark">
                {best.market}
                {best.distance_km !== null && (
                  <span className="font-normal text-farm-muted">
                    {" "}· <MapPin className="w-3 h-3 inline -mt-0.5" /> {best.coordinate_precision === "district" ? "~" : ""}
                    {Math.round(best.distance_km)} km
                  </span>
                )}
              </p>
              <p className="text-farm-muted">
                <strong className="text-farm-dark">{rupees(best.modal_price)}</strong> on {longDate(best.as_of)}
                {best.is_selected
                  ? " · this mandi"
                  : best.difference_vs_selected !== null && ` · ${signedRupees(best.difference_vs_selected)}/q vs selected`}
                {" "}· {best.note}
              </p>
            </div>
          </div>
          {!best.is_selected && onSelectMarket && (
            <button
              type="button"
              onClick={() => onSelectMarket(best.market_id)}
              className="text-xs font-semibold text-farm-green hover:underline"
            >
              View this mandi
            </button>
          )}
        </div>
      )}

      {rec.horizons.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-farm-muted hover:text-farm-dark font-semibold">How this was worked out</summary>
          <div className="overflow-x-auto mt-2">
            <table className="w-full min-w-[420px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-farm-muted border-b border-farm-border-color">
                  <th className="py-1.5 pr-2 font-semibold">Hold</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Estimate</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Gain</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">− Holding</th>
                  <th className="py-1.5 pr-2 font-semibold text-right">Error ±</th>
                  <th className="py-1.5 font-semibold">Worth it?</th>
                </tr>
              </thead>
              <tbody>
                {rec.horizons.map((o) => (
                  <tr key={o.horizon_days} className="border-b border-farm-border-color last:border-0">
                    <td className="py-1.5 pr-2">{o.horizon_days} days</td>
                    <td className="py-1.5 pr-2 text-right">{rupees(o.predicted_price)}</td>
                    <td className="py-1.5 pr-2 text-right">{signedRupees(o.expected_gain)}</td>
                    <td className="py-1.5 pr-2 text-right">{rupees(o.holding_cost)}</td>
                    <td className="py-1.5 pr-2 text-right">{rupees(o.typical_error)}</td>
                    <td className="py-1.5 font-semibold">{o.worth_holding ? "Yes" : "No"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-farm-muted mt-1.5">
            Hold only when Gain is more than Holding + Error. Error is the model&apos;s average % error in testing, applied to today&apos;s price.
          </p>
        </details>
      )}

      <p className="flex items-center gap-1.5 text-[11px] text-farm-muted">
        <EstimateBadge /> {rec.disclaimer}
      </p>
    </div>
  );
}
