"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, MapPin } from "lucide-react";
import type { NearbyMarket } from "@/lib/api/market-client";
import { changeClass, longDate, pct, rupees, TREND_META } from "./format";

type SortKey = "distance" | "price" | "change";

const SCOPE_LABEL: Record<NearbyMarket["scope"], string> = {
  radius: "",
  district: "Same district",
  state: "Same state",
};

function distanceText(m: NearbyMarket): string {
  if (m.distance_km === null) return SCOPE_LABEL[m.scope] || "—";
  const approx = m.coordinate_precision === "district" ? "~" : "";
  return `${approx}${m.distance_km < 10 ? m.distance_km.toFixed(1) : Math.round(m.distance_km)} km`;
}

export default function NearbyMandisTable({
  markets,
  selectedMarketId,
  onSelect,
  staleAfterDays = 7,
  today,
  bestMarketId,
}: {
  markets: NearbyMarket[];
  selectedMarketId?: number;
  /** Highest recent modal price nearby -- tagged "Best today". */
  bestMarketId?: number;
  onSelect?: (marketId: number) => void;
  staleAfterDays?: number;
  today: string;
}) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "distance", dir: 1 });
  const [showAll, setShowAll] = useState(false);
  useEffect(() => setShowAll(false), [markets]);

  const rows = useMemo(() => {
    const value = (m: NearbyMarket): number | null => {
      if (sort.key === "price") return m.modal_price;
      if (sort.key === "change") return m.change_7d_pct;
      // Markets without a known distance sort after those with one, keeping
      // the backend's district-then-state order among themselves.
      return m.distance_km ?? (m.scope === "district" ? 100_000 : 200_000);
    };
    return [...markets].sort((a, b) => {
      const va = value(a);
      const vb = value(b);
      if (va === null && vb === null) return 0;
      if (va === null) return 1;
      if (vb === null) return -1;
      return (va - vb) * sort.dir;
    });
  }, [markets, sort]);

  const toggle = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: key === "distance" ? 1 : -1 }));

  const LIMIT = 3;
  const displayRows = useMemo(() => {
    if (showAll || rows.length <= LIMIT) return rows;
    const bestRow = rows.find((m) => m.market_id === bestMarketId);
    const rest = bestRow ? rows.filter((m) => m.market_id !== bestMarketId) : rows;
    return bestRow ? [bestRow, ...rest.slice(0, LIMIT - 1)] : rows.slice(0, LIMIT);
  }, [rows, showAll, bestMarketId]);
  const hiddenCount = rows.length - displayRows.length;

  const SortButton = ({ k, label }: { k: SortKey; label: string }) => {
    const active = sort.key === k;
    const Icon = !active ? ArrowUpDown : sort.dir === 1 ? ArrowUp : ArrowDown;
    return (
      <button
        type="button"
        onClick={() => toggle(k)}
        className={`inline-flex items-center gap-1 font-semibold ${active ? "text-farm-green" : "text-farm-muted hover:text-farm-dark"}`}
        aria-label={`Sort by ${label}`}
      >
        {label}
        <Icon className="w-3 h-3" />
      </button>
    );
  };

  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-sm min-w-[640px]">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-farm-muted border-b border-farm-border-color">
            <th className="py-2 px-2 font-semibold">Mandi</th>
            <th className="py-2 px-2"><SortButton k="distance" label="Distance" /></th>
            <th className="py-2 px-2 text-right"><SortButton k="price" label="Modal price" /></th>
            <th className="py-2 px-2 text-right font-semibold">7-day avg</th>
            <th className="py-2 px-2 text-right"><SortButton k="change" label="7-day change" /></th>
            <th className="py-2 px-2 font-semibold">Trend</th>
            <th className="py-2 px-2 font-semibold">Last updated</th>
          </tr>
        </thead>
        <tbody>
          {displayRows.map((m) => {
            const trend = TREND_META[m.trend];
            const stale = (Date.parse(today) - Date.parse(m.as_of)) / 86_400_000 > staleAfterDays;
            const selected = m.market_id === selectedMarketId;
            return (
              <tr
                key={m.market_id}
                onClick={() => onSelect?.(m.market_id)}
                className={`border-b border-farm-border-color last:border-0 ${onSelect ? "cursor-pointer hover:bg-farm-green-light/50" : ""} ${selected ? "bg-farm-green-light/60" : ""}`}
              >
                <td className="py-2.5 px-2">
                  <p className="font-semibold text-farm-dark">
                    {m.market}
                    {m.market_id === bestMarketId && (
                      <span className="ml-1.5 align-middle text-[10px] font-bold uppercase text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-1 py-px">Best today</span>
                    )}
                    {m.model_ready && (
                      <span className="ml-1.5 align-middle text-[10px] font-bold uppercase text-sky-700 bg-sky-50 border border-dashed border-sky-200 rounded px-1 py-px">Estimate</span>
                    )}
                  </p>
                  <p className="text-[11px] text-farm-muted">{m.district ?? m.state}</p>
                </td>
                <td className="py-2.5 px-2 text-farm-dark whitespace-nowrap">
                  <span className="inline-flex items-center gap-1">
                    {m.distance_km !== null && <MapPin className="w-3 h-3 text-farm-muted" />}
                    {distanceText(m)}
                  </span>
                </td>
                <td className="py-2.5 px-2 text-right font-bold text-farm-dark whitespace-nowrap">{rupees(m.modal_price)}</td>
                <td className="py-2.5 px-2 text-right text-farm-dark whitespace-nowrap">{rupees(m.avg_7d)}</td>
                <td className={`py-2.5 px-2 text-right font-semibold whitespace-nowrap ${changeClass(m.change_7d_pct)}`}>{pct(m.change_7d_pct)}</td>
                <td className="py-2.5 px-2">
                  <span className={`inline-flex items-center gap-1 border rounded-full px-2 py-0.5 text-[11px] font-semibold ${trend.className}`}>
                    <trend.Icon className="w-3 h-3" />
                    {trend.label}
                  </span>
                </td>
                <td className="py-2.5 px-2 whitespace-nowrap">
                  <span className={stale ? "text-amber-700 font-semibold" : "text-farm-muted"}>{longDate(m.as_of)}</span>
                  {stale && <span className="block text-[10px] text-amber-700">Not recent</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {rows.length > LIMIT && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-2 text-xs font-semibold text-farm-green hover:text-farm-green-dark"
        >
          {showAll ? "Show less" : `See ${hiddenCount} more mandi${hiddenCount === 1 ? "" : "s"}`}
        </button>
      )}
    </div>
  );
}
