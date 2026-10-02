"use client";

// Historical modal price (line) with the day's min–max range (shaded band).
// One point per trading day; gaps are days the market didn't report.

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";
import type { HistoryPoint } from "@/lib/api/market-client";
import { longDate, rupees, shortDate } from "./format";

interface ChartPoint {
  date: string;
  label: string;
  modal: number;
  range: [number, number] | null;
  arrivals: number | null;
}

const MODAL_COLOR = "#2d7a3a"; // farm-green
const RANGE_COLOR = "#86b98f";

function PriceTooltip({ active, payload }: TooltipContentProps<ValueType, NameType>) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as ChartPoint;
  return (
    <div className="rounded-xl border border-farm-border-color bg-white/95 px-3 py-2 shadow-md text-[11px] space-y-0.5">
      <p className="font-bold text-farm-dark">{longDate(p.date)}</p>
      <p>
        Modal <strong className="text-farm-green">{rupees(p.modal)}</strong>
      </p>
      {p.range && (
        <p className="text-farm-muted">
          Range {rupees(p.range[0])} – {rupees(p.range[1])}
        </p>
      )}
      {p.arrivals !== null && <p className="text-farm-muted">Arrivals {p.arrivals.toLocaleString("en-IN")} t</p>}
    </div>
  );
}

export default function PriceTrendChart({
  series,
  showRange = true,
  height = 280,
}: {
  series: HistoryPoint[];
  showRange?: boolean;
  height?: number;
}) {
  const data: ChartPoint[] = series.map((p) => ({
    date: p.date,
    label: shortDate(p.date),
    modal: p.modal_price,
    range: p.min_price !== null && p.max_price !== null ? [p.min_price, p.max_price] : null,
    arrivals: p.arrival_quantity,
  }));
  const values = data.flatMap((d) => (showRange && d.range ? [d.range[0], d.range[1], d.modal] : [d.modal]));
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = Math.max(20, (hi - lo) * 0.08);

  return (
    <div className="w-full" style={{ height }} role="img" aria-label="Modal price history chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
          <CartesianGrid stroke="#f1f5f9" strokeDasharray="4 4" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10, fill: "#64748b" }}
            tickLine={false}
            axisLine={{ stroke: "#e2e8f0" }}
            interval="preserveStartEnd"
            minTickGap={28}
          />
          <YAxis
            domain={[Math.max(0, Math.floor((lo - pad) / 50) * 50), Math.ceil((hi + pad) / 50) * 50]}
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            tickFormatter={(v: number) => `₹${v.toLocaleString("en-IN")}`}
            tickLine={false}
            axisLine={false}
            width={64}
          />
          <Tooltip content={PriceTooltip} cursor={{ stroke: "#cbd5e1", strokeDasharray: "3 3" }} />
          {showRange && (
            <Area
              dataKey="range"
              name="Min–max range"
              stroke="none"
              fill={RANGE_COLOR}
              fillOpacity={0.25}
              isAnimationActive={false}
              connectNulls
            />
          )}
          <Line
            type="monotone"
            dataKey="modal"
            name="Modal price"
            stroke={MODAL_COLOR}
            strokeWidth={2.25}
            dot={data.length <= 45 ? { r: 2.5, fill: MODAL_COLOR, strokeWidth: 0 } : false}
            activeDot={{ r: 4 }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
