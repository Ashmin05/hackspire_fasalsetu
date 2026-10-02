"use client";



import Link from "next/link";
import { AlertTriangle, ArrowRight, Banknote, Clock, HelpCircle, Loader2 } from "lucide-react";
import { useFarmMarketForecast } from "@/lib/hooks/useMarketPrices";
import { isRealFarmId } from "@/lib/hooks/useFarmSatelliteAnalysis";
import { EstimateBadge, LiveBadge } from "@/components/market/Badges";
import { changeClass, pct, rupees, shortDate } from "@/components/market/format";

const ACTION_ICON = { hold: Clock, sell_now: Banknote, unavailable: HelpCircle } as const;

export default function MarketPriceCard({ farmId }: { farmId?: string }) {
  const isReal = isRealFarmId(farmId);
  const { data, isLoading, isError } = useFarmMarketForecast(farmId);
  const today = data?.today;
  const rec = data?.recommendation;
  const month = data?.forecast.available ? data.forecast.forecasts.find((f) => f.horizon_days === 30) : undefined;
  const ActionIcon = rec ? ACTION_ICON[rec.action] : HelpCircle;

  return (
    <div className="bg-white rounded-2xl border border-farm-border-color p-4 shadow-xs hover:shadow-card transition-all flex flex-col">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] uppercase font-bold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded">Market price</span>
        {today && <LiveBadge asOf={shortDate(today.as_of)} />}
      </div>

      {!isReal && (
        <p className="text-xs text-farm-muted mt-2 leading-relaxed flex-1">
          Sign in and register a farm to see today&apos;s mandi price for your crop, a 30-day estimate and whether to sell or hold.
        </p>
      )}
      {isReal && isLoading && (
        <p className="text-xs text-farm-muted mt-2 flex items-center gap-1.5 flex-1">
          <Loader2 className="w-3 h-3 animate-spin" /> Loading prices…
        </p>
      )}
      {isReal && isError && <p className="text-xs text-rose-700 mt-2 flex-1">Mandi prices can&apos;t be loaded right now.</p>}
      {isReal && data && !today && (
        <p className="text-xs text-farm-muted mt-2 flex-1">{data.message ?? "No recent mandi price is available near this farm."}</p>
      )}
      {isReal && data && today && (
        <div className="mt-2 flex-1 space-y-1.5">
          <h3 className="font-bold text-xs text-farm-dark">
            {data.selected_commodity?.name} · {today.market}
            {data.market?.distance_km !== null && data.market?.distance_km !== undefined && (
              <span className="font-normal text-farm-muted"> ({Math.round(data.market.distance_km)} km)</span>
            )}
          </h3>
          <p className="text-lg font-extrabold text-farm-dark">
            {rupees(today.modal_price)}
            <span className="text-xs font-normal text-farm-muted">/quintal modal</span>
          </p>
          {month && (
            <p className="text-[11px] text-farm-muted flex items-center gap-1.5 flex-wrap">
              <EstimateBadge /> {rupees(month.predicted_price)} in 30 days
              <span className={`font-semibold ${changeClass(month.change_pct)}`}>({pct(month.change_pct)})</span>
            </p>
          )}
          {rec && (
            <p className="text-xs text-farm-dark flex items-start gap-1.5">
              <ActionIcon className="w-3.5 h-3.5 text-farm-green flex-shrink-0 mt-px" />
              <span>
                <strong>{rec.headline}.</strong> <span className="text-farm-muted">{rec.reason}</span>
              </span>
            </p>
          )}
          {rec?.perishable && (
            <p className="text-[11px] text-amber-700 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" /> Perishable: holding may not be possible.
            </p>
          )}
        </div>
      )}
      <Link href="/market" className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-farm-green hover:underline">
        Open Market <ArrowRight className="w-3 h-3" />
      </Link>
    </div>
  );
}
