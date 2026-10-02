"use client";


import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type DotItemDotProps,
  type TooltipContentProps,
} from "recharts";
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";
import { formatCloudPct } from "@/components/SourceBadge";

export interface SeasonCurvePoint {
  /** Stable key -- an ISO date for live passes, a label for demo points. */
  key: string;
  /** X-axis label, e.g. "20 Sep". */
  label: string;
  ndvi: number;
  benchmark: number;
  cloudPct?: number | null;
  stage?: string;
}

const FIELD_COLOR = "#059669"; // emerald-600
const BENCHMARK_COLOR = "#94a3b8"; // slate-400
// How many of the most recent passes get an NDVI value label directly on the
// chart -- the present pass plus its two prior readings.
const RECENT_LABEL_COUNT = 3;

function SeasonTooltip({ active, payload }: TooltipContentProps<ValueType, NameType>) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload as SeasonCurvePoint;
  return (
    <div className="rounded-xl border border-farm-border-color bg-white/95 px-3 py-2 shadow-md text-[11px] space-y-0.5">
      <p className="font-bold text-farm-dark">{point.label}</p>
      <p>
        NDVI <strong className="text-emerald-700">{point.ndvi.toFixed(2)}</strong>
        <span className="text-farm-muted"> · benchmark {point.benchmark.toFixed(2)}</span>
      </p>
      {point.cloudPct !== undefined && point.cloudPct !== null && (
        <p className="text-farm-muted">Cloud cover {formatCloudPct(point.cloudPct)}</p>
      )}
      {point.stage && <p className="text-farm-muted">{point.stage}</p>}
    </div>
  );
}

export default function SeasonCurveChart({
  points,
  height = 220,
  selectedKey,
  onSelectPoint,
}: {
  points: SeasonCurvePoint[];
  height?: number;
  /** Highlights one pass (e.g. the one shown on the map) with a vertical marker. */
  selectedKey?: string;
  onSelectPoint?: (point: SeasonCurvePoint) => void;
}) {
  const selected = points.find((p) => p.key === selectedKey);
  const latestIndex = points.length - 1;
  const recentLabelStartIndex = Math.max(0, points.length - RECENT_LABEL_COUNT);

  // Highlights the present (most recent) pass with a bigger "Now" marker, and
  // labels its NDVI value along with the last couple of prior passes.
  const renderFieldDot = (props: DotItemDotProps) => {
    const { cx, cy, index, payload } = props as DotItemDotProps & { payload: SeasonCurvePoint };
    if (cx == null || cy == null || index == null || !payload) return <g key={`dot-${index}`} />;
    const isLatest = index === latestIndex;
    const showLabel = index >= recentLabelStartIndex;
    return (
      <g key={`dot-${payload.key}`}>
        {isLatest ? (
          <>
            <circle cx={cx} cy={cy} r={9} fill={FIELD_COLOR} fillOpacity={0.18} />
            <circle cx={cx} cy={cy} r={5} fill={FIELD_COLOR} stroke="#ffffff" strokeWidth={2} />
          </>
        ) : (
          <circle cx={cx} cy={cy} r={4} fill="#ffffff" stroke={FIELD_COLOR} strokeWidth={2} />
        )}
        {showLabel && (
          <text
            x={cx}
            y={cy - (isLatest ? 16 : 10)}
            textAnchor="middle"
            fontSize={9}
            fontWeight={isLatest ? 700 : 600}
            fill={isLatest ? FIELD_COLOR : "#64748b"}
          >
            {isLatest ? `Now · ${payload.ndvi.toFixed(2)}` : payload.ndvi.toFixed(2)}
          </text>
        )}
      </g>
    );
  };

  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={points}
          margin={{ top: 8, right: 12, bottom: 0, left: -18 }}
          onClick={(state) => {
            const idx = state?.activeTooltipIndex;
            if (onSelectPoint && idx !== undefined && idx !== null) {
              const point = points[Number(idx)];
              if (point) onSelectPoint(point);
            }
          }}
        >
          <CartesianGrid stroke="#f1f5f9" strokeDasharray="4 4" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10, fill: "#64748b" }}
            tickLine={false}
            axisLine={{ stroke: "#e2e8f0" }}
            interval="preserveStartEnd"
            minTickGap={16}
          />
          <YAxis
            domain={[0, 1]}
            ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]}
            tick={{ fontSize: 10, fill: "#94a3b8" }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={SeasonTooltip} cursor={{ stroke: "#cbd5e1", strokeDasharray: "3 3" }} />
          {selected && <ReferenceLine x={selected.label} stroke={FIELD_COLOR} strokeOpacity={0.35} strokeWidth={6} />}
          <Line
            type="monotone"
            dataKey="benchmark"
            name="Benchmark"
            stroke={BENCHMARK_COLOR}
            strokeWidth={2}
            strokeDasharray="6 5"
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="ndvi"
            name="Field NDVI"
            stroke={FIELD_COLOR}
            strokeWidth={3}
            dot={renderFieldDot}
            activeDot={{ r: 7, fill: FIELD_COLOR, stroke: "#ffffff", strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
