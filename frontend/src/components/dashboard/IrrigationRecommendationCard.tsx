"use client";



import {
  Droplets, CheckCircle2, CloudRain, Loader2, Leaf, Waves,
  Thermometer, CloudDrizzle, ShieldAlert,
} from "lucide-react";
import type { Farm, FarmSatellite } from "@/lib/stores/farmStore";
import type { FarmDetailedWeather, DayForecastItem } from "@/components/satellite/FarmWeatherReport";
import type { SatelliteObservation, EnvironmentReport } from "@/lib/api/satellite-client";
import type { SatelliteStatus } from "@/lib/hooks/useFarmSatelliteAnalysis";
import type { FarmWeather } from "@/lib/api/weather-client";
import type { IrrigationPlan } from "@/lib/api/irrigation-client";
import SourceBadge, { formatPassDate } from "@/components/SourceBadge";
import SatelliteStatusState from "@/components/satellite/SatelliteStatusState";

type Props = {
  farm: Farm;
  isRealFarm: boolean;
  satelliteStatus: SatelliteStatus;
  satelliteObservation: SatelliteObservation | null;
  satelliteError: string | null;
  retrySatellite: () => void;
  environment: EnvironmentReport | null;
  environmentLoading: boolean;
  environmentError: boolean;
  retryEnvironment: () => void;
  liveWeather: FarmWeather | null;
  weatherLoading: boolean;
  weatherError: boolean;
  retryWeather: () => void;
  irrigationPlan: IrrigationPlan | null;
  irrigationLoading: boolean;
  irrigationError: boolean;
  retryIrrigation: () => void;
  currentSatellite: FarmSatellite;
  currentWeather: FarmDetailedWeather;
};

type DayPlan = {
  label: string;
  willIrrigate: boolean;
  depthMm: number | null;
  rainfallMm: number | null;
  rainChancePct: number | null;
  note?: string;
};

function isoDatePlusDays(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
}

function stressLabel(pct: number): { label: string; color: string; bg: string } {
  if (pct >= 65) return { label: "High", color: "text-red-700", bg: "bg-red-100" };
  if (pct >= 35) return { label: "Moderate", color: "text-amber-700", bg: "bg-amber-100" };
  return { label: "Low", color: "text-emerald-700", bg: "bg-emerald-100" };
}

function StatChip({
  icon, label, value, sub, badge,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  badge?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-farm-border-color p-3 flex flex-col gap-1">
      <div className="flex items-center gap-1.5 text-farm-muted">
        {icon}
        <span className="text-[11px] font-semibold uppercase tracking-wide">{label}</span>
      </div>
      <span className="text-lg font-extrabold text-farm-dark leading-tight">{value}</span>
      {sub && <span className="text-[11px] text-farm-muted">{sub}</span>}
      {badge && <div className="mt-0.5">{badge}</div>}
    </div>
  );
}

function DayCard({ day }: { day: DayPlan }) {
  return (
    <div
      className={`rounded-xl border p-3 text-center flex flex-col items-center gap-1 ${
        day.willIrrigate ? "border-sky-300 bg-sky-50" : "border-farm-border-color"
      }`}
    >
      <span className="text-xs font-bold text-farm-dark">{day.label}</span>
      {day.willIrrigate ? (
        <Droplets className="w-5 h-5 text-sky-600" />
      ) : (
        <CheckCircle2 className="w-5 h-5 text-emerald-600" />
      )}
      <span className={`text-xs font-bold ${day.willIrrigate ? "text-sky-800" : "text-emerald-700"}`}>
        {day.note ?? (day.willIrrigate
          ? day.depthMm !== null
            ? `Irrigate · ${day.depthMm.toFixed(0)}mm`
            : "Irrigate"
          : "No irrigation needed")}
      </span>
      {(day.rainfallMm !== null || day.rainChancePct !== null) && (
        <span className="text-[10px] text-farm-muted flex items-center gap-1">
          <CloudDrizzle className="w-3 h-3" />
          {day.rainfallMm !== null ? `${day.rainfallMm.toFixed(0)}mm` : "—"}
          {day.rainChancePct !== null && ` · ${day.rainChancePct.toFixed(0)}%`}
        </span>
      )}
    </div>
  );
}

export default function IrrigationRecommendationCard({
  farm, isRealFarm,
  satelliteStatus, satelliteObservation, satelliteError, retrySatellite,
  environment, environmentLoading, environmentError, retryEnvironment,
  liveWeather, weatherLoading, weatherError, retryWeather,
  irrigationPlan, irrigationLoading, irrigationError, retryIrrigation,
  currentSatellite, currentWeather,
}: Props) {

  const header = (
    <div className="flex items-center gap-2 mb-4">
      <span className="w-9 h-9 rounded-xl bg-sky-100 text-sky-600 flex items-center justify-center flex-shrink-0">
        <Droplets className="w-5 h-5" />
      </span>
      <div>
        <h2 className="text-sm font-bold text-farm-dark">Irrigation Recommendation</h2>
        <p className="text-xs text-farm-muted">{farm.crop} · next 3 days</p>
      </div>
    </div>
  );

  // ── Real farm ──────────────────────────────────────────────────────────
  if (isRealFarm) {
    if (!satelliteObservation) {
      return (
        <div className="bg-white rounded-2xl border border-farm-border-color p-5 sm:p-6 shadow-xs">
          {header}
          <div className="py-6 flex items-center justify-center">
            <SatelliteStatusState compact status={satelliteStatus} error={satelliteError} onRetry={retrySatellite} />
          </div>
        </div>
      );
    }

    const days = [0, 1, 2].map((offset) => isoDatePlusDays(offset));
    const dailyByDate = new Map((liveWeather?.daily ?? []).map((d) => [d.date, d]));
    const irrigateDayIndex = irrigationPlan?.next_irrigation_date
      ? days.findIndex((iso) => iso >= irrigationPlan.next_irrigation_date!)
      : -1;

    const dayPlans: DayPlan[] = days.map((iso, i) => {
      const w = dailyByDate.get(iso);
      return {
        label: i === 0 ? "Today" : i === 1 ? "Tomorrow" : formatPassDate(iso),
        willIrrigate: i === irrigateDayIndex,
        depthMm: i === irrigateDayIndex ? irrigationPlan?.next_irrigation_depth_mm ?? null : null,
        rainfallMm: w?.precipitation_sum_mm ?? null,
        rainChancePct: w?.precipitation_probability_pct ?? null,
      };
    });

    const next3dRainfall = liveWeather
      ? days.reduce((sum, iso) => sum + (dailyByDate.get(iso)?.precipitation_sum_mm ?? 0), 0)
      : null;
    const next3dTemps = days.map((iso) => dailyByDate.get(iso)?.temp_max_c).filter((t): t is number => t != null);
    const next3dAvgTemp = next3dTemps.length ? next3dTemps.reduce((a, b) => a + b, 0) / next3dTemps.length : null;

    const stressPct = irrigationPlan ? Math.round(Math.min(1, Math.max(0, irrigationPlan.depletion_fraction)) * 100) : null;
    const stress = stressPct !== null ? stressLabel(stressPct) : null;

    return (
      <div className="bg-white rounded-2xl border border-farm-border-color p-5 sm:p-6 shadow-xs">
        {header}

        {irrigationLoading ? (
          <div className="py-8 flex items-center justify-center gap-2 text-sm text-farm-muted">
            <Loader2 className="w-4 h-4 animate-spin" /> Calculating irrigation plan…
          </div>
        ) : irrigationError ? (
          <div className="py-8 flex items-center justify-center">
            <p className="text-xs text-red-700 text-center">
              Couldn&apos;t load the irrigation plan.{" "}
              <button onClick={() => retryIrrigation()} className="font-semibold underline">
                Retry
              </button>
            </p>
          </div>
        ) : irrigationPlan ? (
          <>
            <div className="grid grid-cols-3 gap-3 mb-5">
              {dayPlans.map((day) => (
                <DayCard key={day.label} day={day} />
              ))}
            </div>

            <div className="pt-4 border-t border-farm-border-color">
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-farm-muted mb-3">Why this recommendation</h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <StatChip
                  icon={<Leaf className="w-3.5 h-3.5" />}
                  label="NDVI"
                  value={satelliteObservation.ndvi.mean.toFixed(2)}
                  sub="Crop health"
                />
                <StatChip
                  icon={<Waves className="w-3.5 h-3.5" />}
                  label="NDWI"
                  value={satelliteObservation.ndwi.mean.toFixed(2)}
                  sub="Canopy moisture"
                />
                <StatChip
                  icon={<Droplets className="w-3.5 h-3.5" />}
                  label="Soil moisture"
                  value={
                    environmentLoading
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : environment?.soil_moisture.surface_moisture != null
                        ? `${environment.soil_moisture.surface_moisture.toFixed(2)} m³/m³`
                        : "—"
                  }
                  sub={
                    environmentError ? (
                      <button onClick={() => retryEnvironment()} className="font-semibold underline">
                        Couldn&apos;t load · Retry
                      </button>
                    ) : (
                      "Surface, regional"
                    )
                  }
                />
                <StatChip
                  icon={<CloudRain className="w-3.5 h-3.5" />}
                  label="Rainfall"
                  value={
                    weatherLoading
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : next3dRainfall !== null
                        ? `${next3dRainfall.toFixed(0)}mm`
                        : "—"
                  }
                  sub={
                    weatherError ? (
                      <button onClick={() => retryWeather()} className="font-semibold underline">
                        Couldn&apos;t load · Retry
                      </button>
                    ) : (
                      "Next 3 days"
                    )
                  }
                />
                <StatChip
                  icon={<Thermometer className="w-3.5 h-3.5" />}
                  label="Temperature"
                  value={
                    weatherLoading
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : next3dAvgTemp !== null
                        ? `${next3dAvgTemp.toFixed(0)}°C`
                        : "—"
                  }
                  sub={weatherError ? "Couldn't load" : "Avg high, next 3d"}
                />
                <StatChip
                  icon={<ShieldAlert className="w-3.5 h-3.5" />}
                  label="Water stress"
                  value={stressPct !== null ? `${stressPct}%` : "—"}
                  sub={
                    stress && (
                      <span className={`inline-block mt-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded ${stress.bg} ${stress.color}`}>
                        {stress.label} · soil water used
                      </span>
                    )
                  }
                />
              </div>
            </div>
          </>
        ) : null}
      </div>
    );
  }

  // ── Guest / demo farm ─────────────────────────────────────────────────
  const willIrrigateToday = farm.water.status === "Moderate Stress";
  const holdForRain = farm.water.status === "Excess Rain Risk";
  const forecast = currentWeather.forecast10Days.slice(0, 3);

  const dayPlans: DayPlan[] = [0, 1, 2].map((i) => {
    const f = forecast[i];
    return {
      label: i === 0 ? "Today" : i === 1 ? "Tomorrow" : "Day 3",
      willIrrigate: i === 0 && willIrrigateToday,
      depthMm: null,
      rainfallMm: f?.rainfallMm ?? null,
      rainChancePct: f?.rainChance ?? null,
      note: i === 0 && holdForRain ? "Hold — excess rain" : undefined,
    };
  });

  const next3dRainfall = forecast.reduce((sum: number, f: DayForecastItem) => sum + (f?.rainfallMm ?? 0), 0);
  const next3dAvgTemp = forecast.length
    ? forecast.reduce((sum: number, f: DayForecastItem) => sum + f.hi, 0) / forecast.length
    : null;
  const demoStressPct = willIrrigateToday ? 70 : holdForRain ? 5 : 15;
  const demoStress = stressLabel(demoStressPct);

  return (
    <div className="bg-white rounded-2xl border border-farm-border-color p-5 sm:p-6 shadow-xs">
      {header}

      <div className="grid grid-cols-3 gap-3 mb-5">
        {dayPlans.map((day) => (
          <DayCard key={day.label} day={day} />
        ))}
      </div>

      <div className="pt-4 border-t border-farm-border-color">
        <h3 className="text-[11px] font-bold uppercase tracking-wider text-farm-muted mb-3">Why this recommendation</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <StatChip
            icon={<Leaf className="w-3.5 h-3.5" />}
            label="NDVI"
            value={currentSatellite.meanNdvi.toFixed(2)}
            sub="Crop health"
            badge={<SourceBadge demo />}
          />
          <StatChip
            icon={<Waves className="w-3.5 h-3.5" />}
            label="NDWI"
            value={currentSatellite.ndwi.toFixed(2)}
            sub="Canopy moisture"
            badge={<SourceBadge demo />}
          />
          <StatChip
            icon={<Droplets className="w-3.5 h-3.5" />}
            label="Soil moisture"
            value={`${farm.water.soilMoisturePercent}%`}
            sub="Root zone"
            badge={<SourceBadge demo />}
          />
          <StatChip
            icon={<CloudRain className="w-3.5 h-3.5" />}
            label="Rainfall"
            value={`${next3dRainfall.toFixed(0)}mm`}
            sub="Next 3 days"
            badge={<SourceBadge demo />}
          />
          <StatChip
            icon={<Thermometer className="w-3.5 h-3.5" />}
            label="Temperature"
            value={next3dAvgTemp !== null ? `${next3dAvgTemp.toFixed(0)}°C` : "—"}
            sub="Avg high, next 3d"
            badge={<SourceBadge demo />}
          />
          <StatChip
            icon={<ShieldAlert className="w-3.5 h-3.5" />}
            label="Water stress"
            value={`${demoStressPct}%`}
            sub={
              <span className={`inline-block mt-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded ${demoStress.bg} ${demoStress.color}`}>
                {demoStress.label} · soil water used
              </span>
            }
            badge={<SourceBadge demo />}
          />
        </div>
      </div>
    </div>
  );
}
