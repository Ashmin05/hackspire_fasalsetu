"use client";


import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";
import type { ForecastPoint, HistoryPoint } from "@/lib/api/market-client";
import { longDate, rupees, shortDate } from "@/components/market/format";

const DAY_MS = 86_400_000;
const LIVE = "#2d7a3a";
const ESTIMATE = "#0369a1";

interface Point {
  date: string;
  /** UTC ms. */
  t: number;
  live: number | null;
  estimate: number | null;
  band: [number, number] | null;
  horizon?: number;
}

function ChartTooltip({ active, payload }: TooltipContentProps<ValueType, NameType>) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as Point;
  return (
    <div className="rounded-xl border border-farm-border-color bg-white/95 px-3 py-2 shadow-md text-[11px] space-y-0.5">
      <p className="font-bold text-farm-dark">{longDate(p.date)}</p>
      {p.live !== null && (
        <p>
          <span className="font-semibold text-emerald-700">Live</span> modal price <strong className="text-farm-dark">{rupees(p.live)}</strong>
        </p>
      )}
      {p.horizon !== undefined && p.estimate !== null && (
        <>
          <p>
            <span className="font-semibold text-sky-700">Estimate</span> ({p.horizon} days) <strong className="text-farm-dark">{rupees(p.estimate)}</strong>
          </p>
          {p.band && (
            <p className="text-farm-muted">
              Expected range {rupees(p.band[0])} – {rupees(p.band[1])}
            </p>
          )}
        </>
      )}
    </div>
  );
}

export default function PriceForecastChart({
  history,
  forecasts,
  today,
  highlightHorizon,
  height = 280,
}: {
  history: HistoryPoint[];
  forecasts: ForecastPoint[];
  /** ISO date of today (the vertical marker). */
  today: string;
  /** The horizon the recommendation talks about, drawn with a bigger dot. */
  highlightHorizon?: number | null;
  height?: number;
}) {
  const todayT = Date.parse(today);
  const start = todayT - 90 * DAY_MS;
  const points: Point[] = history
    .filter((h) => Date.parse(h.date) >= start)
    .map((h) => ({ date: h.date, t: Date.parse(h.date), live: h.modal_price, estimate: null, band: null }));

  const base = forecasts[0];
  if (base) {
    const join = { estimate: base.base_price, band: [base.base_price, base.base_price] as [number, number] };
    const idx = points.findIndex((p) => p.date === base.base_date);
    if (idx >= 0) Object.assign(points[idx], join);
    else points.push({ date: base.base_date, t: Date.parse(base.base_date), live: base.base_price, ...join });
    for (const f of forecasts) {
      points.push({
        date: f.forecast_date,
        t: Date.parse(f.forecast_date),
        live: null,
        estimate: f.predicted_price,
        band: f.lower_bound !== null && f.upper_bound !== null ? [f.lower_bound, f.upper_bound] : null,
        horizon: f.horizon_days,
      });
    }
  }
  points.sort((a, b) => a.t - b.t);

  const end = Math.max(todayT + 30 * DAY_MS, ...points.map((p) => p.t));
  // Fixed date ticks every 15 days, so the axis reads the same however
  // sparse the data is (Recharts would otherwise tick only data points).
  const ticks: number[] = [];
  for (let t = start; t <= end; t += 15 * DAY_MS) ticks.push(t);
  const values = points.flatMap((p) => [p.live, p.estimate, ...(p.band ?? [])].filter((v): v is number => v !== null));
  const lo = values.length ? Math.min(...values) : 0;
  const hi = values.length ? Math.max(...values) : 100;
  const pad = Math.max(20, (hi - lo) * 0.1);

  return (
    <div className="w-full" style={{ height }} role="img" aria-label="Live mandi prices for the last 90 days and estimated prices for the next 30 days">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 16, right: 16, bottom: 0, left: 4 }}>
          <CartesianGrid stroke="#f1f5f9" strokeDasharray="4 4" vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={[start, end]}
            ticks={ticks}
            tickFormatter={(t: number) => shortDate(new Date(t).toISOString())}
            tick={{ fontSize: 10, fill: "#64748b" }}
            tickLine={false}
            axisLine={{ stroke: "#e2e8f0" }}
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
          <Tooltip content={ChartTooltip} cursor={{ stroke: "#cbd5e1", strokeDasharray: "3 3" }} />
          <ReferenceLine
            x={todayT}
            stroke="#475569"
            strokeWidth={1.25}
            label={{ value: "Today", position: "top", fontSize: 10, fontWeight: 600, fill: "#475569" }}
          />
          <Area dataKey="band" name="Expected range" stroke="none" fill="#0ea5e9" fillOpacity={0.15} isAnimationActive={false} connectNulls />
          <Line dataKey="live" name="Live" stroke={LIVE} strokeWidth={2.25} dot={false} isAnimationActive={false} />
          <Line
            dataKey="estimate"
            name="Estimate"
            stroke={ESTIMATE}
            strokeWidth={2}
            strokeDasharray="6 5"
            dot={(props: { cx?: number; cy?: number; payload?: Point; index?: number }) => {
              const { cx, cy, payload, index } = props;
              if (cx === undefined || cy === undefined || payload?.horizon === undefined) return <g key={`d-${index}`} />;
              const on = payload.horizon === highlightHorizon;
              return <circle key={`d-${index}`} cx={cx} cy={cy} r={on ? 5 : 3.5} fill={on ? ESTIMATE : "#ffffff"} stroke={ESTIMATE} strokeWidth={2} />;
            }}
            connectNulls
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Legend under the chart: text + line style, never colour alone. */
export function PriceForecastLegend({ withEstimate = true }: { withEstimate?: boolean }) {
  return (
    <div className="flex flex-wrap gap-4 text-[11px] text-farm-muted">
      <span className="inline-flex items-center gap-1.5"><span className="w-5 h-0.5 inline-block" style={{ background: LIVE }} /> Live · actual modal price</span>
      {withEstimate && (
        <>
          <span className="inline-flex items-center gap-1.5"><span className="w-5 border-t-2 border-dashed inline-block" style={{ borderColor: ESTIMATE }} /> Estimate</span>
          <span className="inline-flex items-center gap-1.5"><span className="w-4 h-3 bg-sky-500/20 inline-block rounded-sm" /> Expected range (80%)</span>
        </>
      )}
      <span className="inline-flex items-center gap-1.5"><span className="w-px h-3 bg-slate-600 inline-block" /> Today</span>
    </div>
  );
}
