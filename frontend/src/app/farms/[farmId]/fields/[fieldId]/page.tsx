"use client";
import { useState } from "react";
import Link from "next/link";
import AppLayout from "@/components/AppLayout";
import SourceBadge from "@/components/SourceBadge";
import MapView from "@/components/map/MapView";
import { useField } from "@/lib/hooks/useFields";
import { useSatelliteData } from "@/lib/hooks/useSatellite";
import { useWeatherData } from "@/lib/hooks/useWeather";
import { useIrrigationData } from "@/lib/hooks/useIrrigation";
import { useYieldData } from "@/lib/hooks/useYield";
import {
  Satellite, CloudRain, Droplets, TrendingUp, Brain,
  ChevronLeft, Bell, AlertTriangle, ChevronRight, ChevronUp, ChevronDown, Minus,
  Sun, Cloud, Zap, Droplet, Wind, ThumbsUp, Calendar
} from "lucide-react";

type Tab = "satellite" | "weather" | "irrigation" | "yield" | "assistant";

const TABS: { id: Tab; label: string; icon: typeof Satellite }[] = [
  { id: "satellite", label: "Satellite", icon: Satellite },
  { id: "weather", label: "Weather", icon: CloudRain },
  { id: "irrigation", label: "Soil & Water", icon: Droplets },
  { id: "yield", label: "Yield & Price", icon: TrendingUp },
  { id: "assistant", label: "AI Assistant", icon: Brain },
];

// ─── Sub-components ────────────────────────────────────────────────────────

function SatelliteTab({
  fieldId,
  field,
}: {
  fieldId: string;
  field?: {
    name: string;
    coordinates?: { lat: number; lng: number }[];
  } | null;
}) {
  const { data, isLoading } = useSatelliteData(fieldId);
  const [activeMonth, setActiveMonth] = useState<number | null>(null);

  if (isLoading) return <LoadingSkeleton rows={4} />;
  if (!data) return <ErrorBox />;

  const fieldPolygon: GeoJSON.Feature<GeoJSON.Polygon> | null =
    field?.coordinates && field.coordinates.length >= 3
      ? {
          type: "Feature",
          properties: { name: field.name },
          geometry: {
            type: "Polygon",
            coordinates: [
              [
                ...field.coordinates.map((c) => [c.lng, c.lat] as [number, number]),
                [field.coordinates[0].lng, field.coordinates[0].lat] as [number, number],
              ],
            ],
          },
        }
      : null;

  const initialCenter: [number, number] =
    field?.coordinates && field.coordinates.length > 0
      ? [field.coordinates[0].lng, field.coordinates[0].lat]
      : [73.795, 20.005];

  const history = data.ndvi_history;
  const selected = activeMonth !== null ? activeMonth : history.length - 1;
  const current = history[selected];
  const prev = history[Math.max(0, selected - 1)];
  const delta = current.ndvi - prev.ndvi;

  const ndviColor = (v: number) =>
    v >= 0.7 ? "#2d7a3a" : v >= 0.5 ? "#84cc16" : v >= 0.35 ? "#f59e0b" : "#ef4444";

  const severityStyle: Record<string, string> = {
    critical: "border-red-200 bg-red-50 text-red-700",
    medium: "border-amber-200 bg-amber-50 text-amber-700",
    low: "border-emerald-200 bg-emerald-50 text-emerald-700",
  };

  return (
    <div className="space-y-6">
      {/* Live MapView */}
      <div className="rounded-2xl overflow-hidden border border-farm-border-color shadow-card">
        <div className="bg-farm-dark px-4 py-2.5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-white text-xs font-semibold">Live Satellite Imagery & Field Boundary</span>
          </div>
          <span className="text-white/60 text-xs font-mono">Mapbox Satellite-Streets</span>
        </div>
        <MapView
          height="380px"
          initialCenter={initialCenter}
          initialZoom={16}
          initialPolygon={fieldPolygon}
          showDrawControls={false}
        />
      </div>

      {/* NDVI summary */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white rounded-2xl border border-farm-border-color p-5 text-center">
          <p className="text-xs text-farm-muted mb-1">Latest NDVI</p>
          <p className="text-4xl font-bold" style={{ color: ndviColor(data.latest_ndvi) }}>
            {data.latest_ndvi.toFixed(2)}
          </p>
          <div className="flex items-center justify-center gap-1 mt-1 text-xs">
            {data.ndvi_change_30d < 0 ? (
              <ChevronDown className="w-3.5 h-3.5 text-red-500" />
            ) : (
              <ChevronUp className="w-3.5 h-3.5 text-emerald-500" />
            )}
            <span className={data.ndvi_change_30d < 0 ? "text-red-500" : "text-emerald-500"}>
              {Math.abs(data.ndvi_change_30d * 100).toFixed(0)}% vs 30d ago
            </span>
          </div>
          <div className="mt-2"><SourceBadge provenance={data.provenance} /></div>
        </div>
        <div className="sm:col-span-2 bg-white rounded-2xl border border-farm-border-color p-5">
          <p className="text-xs text-farm-muted mb-3">Field Health Zones · Scan: {data.scan_date}</p>
          <div className="space-y-2">
            {data.health_zones.map(({ label, color, percentage }) => (
              <div key={label} className="flex items-center gap-3">
                <span className="w-20 text-xs text-farm-dark text-right">{label}</span>
                <div className="flex-1 h-4 bg-farm-gray rounded-full overflow-hidden">
                  <div className="h-full rounded-full transition-all" style={{ width: `${percentage}%`, background: color }} />
                </div>
                <span className="text-xs font-mono text-farm-muted w-8">{percentage}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* NDVI history bar chart */}
      <div className="bg-white rounded-2xl border border-farm-border-color p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold text-farm-dark text-sm">NDVI History</h3>
          <div className="text-center">
            <p className="text-lg font-bold" style={{ color: ndviColor(current.ndvi) }}>{current.ndvi.toFixed(2)}</p>
            <p className="text-xs text-farm-muted">{current.date.slice(0, 7)}</p>
            <div className="flex items-center justify-center gap-0.5 text-xs">
              {delta > 0 ? <ChevronUp className="w-3 h-3 text-emerald-500" /> : delta < 0 ? <ChevronDown className="w-3 h-3 text-red-500" /> : <Minus className="w-3 h-3 text-farm-muted" />}
              <span className={delta > 0 ? "text-emerald-500" : delta < 0 ? "text-red-500" : "text-farm-muted"}>
                {delta > 0 ? "+" : ""}{(delta * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-end gap-1.5 h-32">
          {history.map((pt, i) => (
            <button
              key={pt.date}
              onClick={() => setActiveMonth(i)}
              className="flex-1 flex flex-col items-center gap-0.5 group"
            >
              <div
                className={`w-full rounded-t-sm transition-all duration-200 ${i === selected ? "ring-2 ring-farm-green ring-offset-1" : "opacity-70 group-hover:opacity-100"}`}
                style={{
                  height: `${pt.ndvi * 120}px`,
                  background: ndviColor(pt.ndvi),
                }}
              />
              <span className={`text-[9px] ${i === selected ? "font-bold text-farm-green" : "text-farm-muted"}`}>
                {new Date(pt.date).toLocaleString("en-IN", { month: "short" })}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Stress alerts */}
      <div>
        <h3 className="font-bold text-farm-dark text-sm mb-3">Crop Stress Alerts</h3>
        <div className="space-y-3">
          {data.stress_alerts.map((alert) => (
            <div key={alert.id} className={`flex gap-3 p-4 rounded-xl border ${severityStyle[alert.severity]}`}>
              <Bell className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <div>
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className="font-semibold text-sm">{alert.type}</span>
                  <span className="capitalize text-xs px-2 py-0.5 rounded-full bg-black/10 font-medium">{alert.severity}</span>
                  <span className="text-xs opacity-60 ml-auto">{alert.date}</span>
                </div>
                <p className="text-xs mb-1 opacity-80">{alert.message}</p>
                <p className="text-xs font-medium">👉 {alert.recommended_action}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const weatherIcons: Record<string, typeof Sun> = { sun: Sun, cloud: Cloud, rain: CloudRain, storm: Zap, fog: Wind };

function WeatherTab({ fieldId }: { fieldId: string }) {
  const { data, isLoading } = useWeatherData(fieldId);
  const [selected, setSelected] = useState(0);

  if (isLoading) return <LoadingSkeleton rows={4} />;
  if (!data) return <ErrorBox />;

  const day = data.forecast[selected];

  const alertStyle: Record<string, string> = {
    warning: "border-red-200 bg-red-50 text-red-700",
    watch: "border-amber-200 bg-amber-50 text-amber-700",
    advisory: "border-sky-200 bg-sky-50 text-sky-700",
  };

  return (
    <div className="space-y-6">
      {/* Current */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="bg-gradient-to-br from-sky-500 to-sky-700 rounded-2xl p-6 text-white">
          <div className="flex items-center gap-3 mb-3">
            <SourceBadge provenance={data.provenance} />
          </div>
          <div className="flex items-center gap-4">
            <Sun className="w-14 h-14 text-white" />
            <div>
              <p className="text-5xl font-bold">{data.current.temp}°</p>
              <p className="text-white/70 text-sm">{data.current.condition}</p>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3 mt-4 text-center text-sm">
            <div><p className="font-bold">{data.current.humidity}%</p><p className="text-white/60 text-xs">Humidity</p></div>
            <div><p className="font-bold">{data.current.wind_kmh} km</p><p className="text-white/60 text-xs">Wind</p></div>
            <div><p className="font-bold">{data.current.feels_like}°</p><p className="text-white/60 text-xs">Feels</p></div>
          </div>
        </div>

        {/* Irrigation advice */}
        <div className="bg-farm-green-light border border-farm-border-color rounded-2xl p-5 flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Droplet className="w-5 h-5 text-farm-green" />
            <h3 className="font-bold text-farm-dark text-sm">Smart Irrigation Advice</h3>
          </div>
          <p className="text-farm-dark text-sm leading-relaxed">{data.irrigation_advice}</p>
        </div>
      </div>

      {/* 10-day strip */}
      <div className="bg-white rounded-2xl border border-farm-border-color p-5">
        <h3 className="font-bold text-farm-dark text-sm mb-4">10-Day Forecast</h3>
        <div className="flex gap-2 overflow-x-auto pb-2">
          {data.forecast.map((d, i) => {
            const Icon = weatherIcons[d.icon] ?? Sun;
            return (
              <button
                key={d.date}
                onClick={() => setSelected(i)}
                className={`flex flex-col items-center gap-1.5 min-w-[68px] p-3 rounded-xl border-2 transition-all flex-shrink-0 ${
                  selected === i
                    ? "border-farm-green bg-farm-green-light"
                    : "border-farm-border-color bg-white hover:border-sky-300"
                }`}
              >
                <span className={`text-xs font-semibold ${selected === i ? "text-farm-green" : "text-farm-muted"}`}>{d.day_label}</span>
                <Icon className={`w-5 h-5 ${selected === i ? "text-farm-green" : "text-sky-500"}`} />
                <span className="text-xs font-bold text-farm-dark">{d.temp_hi}°</span>
                <div className="flex items-center gap-0.5 text-sky-500">
                  <Droplet className="w-2.5 h-2.5" />
                  <span className="text-xs">{d.rain_chance}%</span>
                </div>
              </button>
            );
          })}
        </div>

        {/* Selected day stats */}
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Rain chance", value: `${day.rain_chance}%` },
            { label: "Rainfall", value: `${day.rain_mm}mm` },
            { label: "Wind", value: `${day.wind_kmh} km/h` },
            { label: "Humidity", value: `${day.humidity}%` },
          ].map(({ label, value }) => (
            <div key={label} className="bg-farm-gray rounded-xl p-3 text-center">
              <p className="text-xs text-farm-muted">{label}</p>
              <p className="font-bold text-farm-dark text-sm mt-0.5">{value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Alerts */}
      {data.alerts.length > 0 && (
        <div className="space-y-3">
          <h3 className="font-bold text-farm-dark text-sm">Weather Alerts</h3>
          {data.alerts.map((alert) => (
            <div key={alert.id} className={`p-4 rounded-xl border ${alertStyle[alert.severity]}`}>
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <AlertTriangle className="w-4 h-4" />
                <span className="font-semibold text-sm">{alert.type}</span>
                <span className="capitalize text-xs bg-black/10 px-2 py-0.5 rounded-full">{alert.severity}</span>
                <span className="text-xs opacity-60 ml-auto">{alert.valid_from} – {alert.valid_to}</span>
              </div>
              <p className="text-xs mb-1">{alert.message}</p>
              <p className="text-xs font-medium opacity-80">🌾 {alert.crop_impact}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function IrrigationTab({ fieldId }: { fieldId: string }) {
  const { data, isLoading } = useIrrigationData(fieldId);

  if (isLoading) return <LoadingSkeleton rows={3} />;
  if (!data) return <ErrorBox />;

  const moistureColor =
    data.moisture_status === "optimal" ? "text-emerald-600"
    : data.moisture_status === "dry" ? "text-red-500"
    : "text-sky-600";

  const npkBadge = (level: "low" | "medium" | "high") =>
    level === "high" ? "bg-emerald-100 text-emerald-700" :
    level === "medium" ? "bg-amber-100 text-amber-700" :
    "bg-red-100 text-red-700";

  return (
    <div className="space-y-6">
      {/* Moisture */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="bg-white rounded-2xl border border-farm-border-color p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-bold text-farm-dark text-sm">Soil Moisture</h3>
            <SourceBadge provenance={data.provenance} />
          </div>
          <div className="flex items-center gap-4">
            <div className="relative w-24 h-24 flex-shrink-0">
              <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                <circle cx="50" cy="50" r="38" fill="none" stroke="#e8f5e9" strokeWidth="10" />
                <circle
                  cx="50" cy="50" r="38"
                  fill="none"
                  stroke={data.moisture_status === "optimal" ? "#2d7a3a" : data.moisture_status === "dry" ? "#ef4444" : "#0ea5e9"}
                  strokeWidth="10"
                  strokeDasharray={`${data.soil_moisture_pct * 2.39} 239`}
                  strokeLinecap="round"
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <p className={`text-xl font-bold ${moistureColor}`}>{data.soil_moisture_pct}%</p>
                <p className="text-xs text-farm-muted capitalize">{data.moisture_status}</p>
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-xs text-farm-muted">Soil type: <strong className="text-farm-dark">{data.soil_info.type}</strong></p>
              <p className="text-xs text-farm-muted">pH: <strong className="text-farm-dark">{data.soil_info.ph}</strong></p>
              <p className="text-xs text-farm-muted">Water saved: <strong className="text-emerald-600">{data.water_saved_pct}%</strong></p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-farm-border-color p-5">
          <h3 className="font-bold text-farm-dark text-sm mb-4">Nutrient Levels (N-P-K)</h3>
          <div className="space-y-2.5">
            {[
              { label: "Nitrogen (N)", level: data.soil_info.nitrogen },
              { label: "Phosphorus (P)", level: data.soil_info.phosphorus },
              { label: "Potassium (K)", level: data.soil_info.potassium },
            ].map(({ label, level }) => (
              <div key={label} className="flex items-center justify-between">
                <span className="text-sm text-farm-muted">{label}</span>
                <span className={`text-xs font-bold px-2.5 py-0.5 rounded-full capitalize ${npkBadge(level)}`}>{level}</span>
              </div>
            ))}
            <div className="flex items-center justify-between">
              <span className="text-sm text-farm-muted">Organic Carbon</span>
              <span className="text-sm font-bold text-farm-dark">{data.soil_info.organic_carbon}%</span>
            </div>
          </div>
        </div>
      </div>

      {/* Next irrigation schedule */}
      <div className="bg-farm-green-light border border-farm-border-color rounded-2xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <Calendar className="w-5 h-5 text-farm-green" />
          <h3 className="font-bold text-farm-dark text-sm">Next Irrigation Schedule</h3>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
          {[
            { label: "Next Date", value: data.schedule.next_irrigation },
            { label: "Duration", value: `${data.schedule.duration_hours}h` },
            { label: "Method", value: data.schedule.method },
            { label: "Volume", value: `${data.schedule.water_liters_per_acre.toLocaleString()} L/acre` },
          ].map(({ label, value }) => (
            <div key={label} className="bg-white rounded-xl p-3 text-center border border-farm-border-color">
              <p className="text-xs text-farm-muted">{label}</p>
              <p className="font-bold text-farm-dark text-xs mt-0.5">{value}</p>
            </div>
          ))}
        </div>
        {data.schedule.skip_reason && (
          <p className="text-farm-green text-xs flex items-center gap-1.5">
            <ThumbsUp className="w-3.5 h-3.5" /> {data.schedule.skip_reason}
          </p>
        )}
      </div>

      {/* Fertiliser recommendation */}
      <div className="bg-white rounded-2xl border border-farm-border-color p-5">
        <h3 className="font-bold text-farm-dark text-sm mb-2">Fertiliser Recommendation</h3>
        <p className="text-farm-muted text-sm leading-relaxed">{data.fertiliser_recommendation}</p>
      </div>
    </div>
  );
}

function YieldTab({ fieldId }: { fieldId: string }) {
  const { data, isLoading } = useYieldData(fieldId);

  if (isLoading) return <LoadingSkeleton rows={4} />;
  if (!data) return <ErrorBox />;

  const maxPrice = Math.max(...data.price_trend_30d.map((p) => p.price_per_quintal));
  const minPrice = Math.min(...data.price_trend_30d.map((p) => p.price_per_quintal));
  const range = maxPrice - minPrice;

  return (
    <div className="space-y-6">
      {/* Yield summary */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white rounded-2xl border border-farm-border-color p-5 text-center">
          <div className="mb-1 flex justify-center"><SourceBadge provenance={data.provenance} /></div>
          <p className="text-4xl font-bold text-farm-green">{data.estimated_yield_quintal_per_acre}</p>
          <p className="text-xs text-farm-muted">qtl/acre (estimated)</p>
          <p className="text-xs text-farm-muted mt-1">Range: {data.yield_range.low}–{data.yield_range.high} qtl</p>
          <div className="mt-2 h-2 bg-farm-gray rounded-full overflow-hidden">
            <div
              className="h-full bg-farm-green rounded-full"
              style={{ width: `${data.confidence * 100}%` }}
            />
          </div>
          <p className="text-xs text-farm-muted mt-1">{Math.round(data.confidence * 100)}% confidence</p>
        </div>

        <div className="sm:col-span-2 grid grid-cols-2 gap-4">
          {[
            { label: "Input Cost/acre", value: `₹${data.input_cost_per_acre.toLocaleString()}`, color: "text-red-500" },
            { label: "Revenue/acre", value: `₹${data.expected_revenue_per_acre.toLocaleString()}`, color: "text-emerald-600" },
            { label: "Profit/acre", value: `₹${data.profit_per_acre.toLocaleString()}`, color: "text-farm-green" },
            { label: "Harvest Date", value: data.harvest_date, color: "text-farm-dark" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-white rounded-2xl border border-farm-border-color p-4">
              <p className="text-xs text-farm-muted mb-1">{label}</p>
              <p className={`font-bold ${color} text-lg`}>{value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Price chart */}
      <div className="bg-white rounded-2xl border border-farm-border-color p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold text-farm-dark text-sm">30-Day Price Trend</h3>
          <span className="text-xs text-farm-muted">₹/quintal · {data.price_trend_30d[0]?.mandi}</span>
        </div>
        <div className="flex items-end gap-0.5 h-24">
          {data.price_trend_30d.map((pt, i) => {
            const h = range > 0 ? ((pt.price_per_quintal - minPrice) / range) * 80 + 10 : 50;
            const isLast = i === data.price_trend_30d.length - 1;
            return (
              <div key={pt.date} className="flex-1 flex flex-col items-center justify-end h-full">
                <div
                  className={`w-full rounded-sm transition-all ${isLast ? "bg-farm-green" : "bg-farm-green/40"}`}
                  style={{ height: `${h}px` }}
                />
              </div>
            );
          })}
        </div>
        <div className="flex justify-between text-xs text-farm-muted mt-1">
          <span>30 days ago</span>
          <span>Today ₹{data.price_trend_30d[data.price_trend_30d.length - 1]?.price_per_quintal}</span>
        </div>
      </div>

      {/* Top mandis */}
      <div className="bg-white rounded-2xl border border-farm-border-color p-5">
        <h3 className="font-bold text-farm-dark text-sm mb-3">Top Mandis Today</h3>
        <div className="space-y-2">
          {data.top_mandis.map((m, i) => (
            <div key={m.mandi} className="flex items-center gap-3 py-2 border-b border-farm-border-color last:border-0">
              <span className="w-5 h-5 rounded-full bg-farm-green-light text-farm-green text-xs font-bold flex items-center justify-center flex-shrink-0">
                {i + 1}
              </span>
              <div className="flex-1">
                <p className="text-sm font-semibold text-farm-dark">{m.mandi}</p>
                <p className="text-xs text-farm-muted">{m.district}</p>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold text-farm-dark">₹{m.price_per_quintal}</p>
                <p className={`text-xs font-medium ${m.change_pct >= 0 ? "text-emerald-600" : "text-red-500"}`}>
                  {m.change_pct >= 0 ? "+" : ""}{m.change_pct}%
                </p>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 p-3 bg-farm-green-light rounded-xl border border-farm-border-color">
          <p className="text-farm-green text-xs font-medium">🎯 Best sell window: {data.best_sell_window}</p>
        </div>
      </div>
    </div>
  );
}

function AssistantTab({ fieldId }: { fieldId: string }) {
  // The AI chat tab links to the full AI chat page with context
  return (
    <div className="space-y-4">
      <div className="bg-purple-50 border border-purple-200 rounded-2xl p-5 text-center">
        <Brain className="w-10 h-10 text-purple-500 mx-auto mb-3" />
        <h3 className="font-bold text-farm-dark text-lg mb-2">KrishiBot AI Assistant</h3>
        <p className="text-farm-muted text-sm mb-4 max-w-sm mx-auto">
          Ask anything about this field — pests, diseases, fertilisers, weather impact, government schemes.
          KrishiBot knows your crop, growth stage, and soil data.
        </p>
        <Link
          href={`/ai-chat?fieldId=${fieldId}`}
          className="inline-flex items-center gap-2 bg-farm-green text-white px-6 py-3 rounded-xl font-semibold hover:bg-farm-green-dark transition-all group"
        >
          Open KrishiBot Chat
          <ChevronRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
        </Link>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {[
          "How do I treat water stress?",
          "Best time to apply fertiliser?",
          "What are pest warning signs?",
          "Should I irrigate this week?",
        ].map((q) => (
          <Link
            key={q}
            href={`/ai-chat?q=${encodeURIComponent(q)}&fieldId=${fieldId}`}
            className="p-3 bg-white border border-farm-border-color rounded-xl text-sm text-farm-dark hover:border-farm-green hover:text-farm-green transition-all flex items-center justify-between gap-2 group"
          >
            <span>{q}</span>
            <ChevronRight className="w-3 h-3 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
          </Link>
        ))}
      </div>
    </div>
  );
}

// ─── Utility components ────────────────────────────────────────────────────
function LoadingSkeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-20 bg-white rounded-2xl border border-farm-border-color animate-pulse" />
      ))}
    </div>
  );
}
function ErrorBox() {
  return <div className="text-center py-12 text-farm-muted">Failed to load data. Please try again.</div>;
}

// ─── Main page ─────────────────────────────────────────────────────────────
export default function FieldDetailPage({
  params,
}: {
  params: { farmId: string; fieldId: string };
}) {
  const { farmId, fieldId } = params;
  const [activeTab, setActiveTab] = useState<Tab>("satellite");
  const { data: field, isLoading } = useField(farmId, fieldId);

  return (
    <AppLayout>
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-farm-muted flex-wrap">
          <Link href="/farms" className="hover:text-farm-green">My Farms</Link>
          <span>/</span>
          <Link href={`/farms/${farmId}`} className="hover:text-farm-green flex items-center gap-1">
            <ChevronLeft className="w-3.5 h-3.5" /> Farm
          </Link>
          <span>/</span>
          <span className="text-farm-dark font-medium">{field?.name ?? "Field"}</span>
        </div>

        {/* Field header */}
        {isLoading ? (
          <div className="h-28 bg-white rounded-2xl border border-farm-border-color animate-pulse" />
        ) : field ? (
          <div className="bg-white rounded-2xl border border-farm-border-color p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-bold text-farm-dark">{field.name}</h1>
                <div className="flex items-center gap-3 mt-1 flex-wrap text-sm text-farm-muted">
                  <span>{field.crop} · {field.variety}</span>
                  <span className="w-1 h-1 rounded-full bg-farm-border-color" />
                  <span>{field.area_acres} acres</span>
                  <span className="w-1 h-1 rounded-full bg-farm-border-color" />
                  <span>{field.growth_stage}</span>
                </div>
              </div>
              <div className="flex items-center gap-3 flex-wrap">
                <SourceBadge provenance={field.provenance} size="md" />
                <div className="text-center">
                  <p className={`text-2xl font-bold ${field.health_score >= 80 ? "text-emerald-600" : field.health_score >= 60 ? "text-amber-500" : "text-red-500"}`}>
                    {field.health_score}
                  </p>
                  <p className="text-xs text-farm-muted">Health</p>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {/* Tabs */}
        <div className="bg-white rounded-2xl border border-farm-border-color overflow-hidden">
          {/* Tab bar */}
          <div className="flex border-b border-farm-border-color overflow-x-auto">
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`flex items-center gap-2 px-4 py-3.5 text-sm font-medium whitespace-nowrap border-b-2 transition-all flex-shrink-0 ${
                  activeTab === id
                    ? "border-farm-green text-farm-green bg-farm-green-light/50"
                    : "border-transparent text-farm-muted hover:text-farm-dark hover:border-farm-border-color"
                }`}
              >
                <Icon className="w-4 h-4" />
                {label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="p-5 sm:p-6">
            {activeTab === "satellite" && <SatelliteTab fieldId={fieldId} field={field} />}
            {activeTab === "weather" && <WeatherTab fieldId={fieldId} />}
            {activeTab === "irrigation" && <IrrigationTab fieldId={fieldId} />}
            {activeTab === "yield" && <YieldTab fieldId={fieldId} />}
            {activeTab === "assistant" && <AssistantTab fieldId={fieldId} />}
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
