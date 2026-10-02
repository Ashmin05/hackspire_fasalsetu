"use client";



import { useState } from "react";
import Link from "next/link";
import AppLayout from "@/components/AppLayout";
import { useFarmStore, useUserStore, applyLiveSatellite, applyLiveWeather } from "@/lib/stores/farmStore";
import { useFarmSatelliteAnalysis } from "@/lib/hooks/useFarmSatelliteAnalysis";
import { useFarmEnvironment } from "@/lib/hooks/useFarmEnvironment";
import { useFarmWeather } from "@/lib/hooks/useFarmWeather";
import { useFarmIrrigation } from "@/lib/hooks/useFarmIrrigation";
import IrrigationRecommendationCard from "@/components/dashboard/IrrigationRecommendationCard";
import AlertsStrip from "@/components/dashboard/AlertsStrip";
import MarketPriceCard from "@/components/dashboard/MarketPriceCard";
import FarmsLoadError from "@/components/FarmsLoadError";
import FarmWeatherReport from "@/components/satellite/FarmWeatherReport";
import {
  TrendingUp, AlertTriangle, CheckCircle2,
  ChevronRight, ChevronDown, Sprout, CloudSun, Loader2
} from "lucide-react";

function useGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export default function DashboardPage() {
  const { farms, mounted, loadError, retryLoad } = useFarmStore();
  const { profile } = useUserStore();
  const [selectedFarmId, setSelectedFarmId] = useState<string>(farms[0]?.id || "farm-1");
  const greeting = useGreeting();

  const currentFarm = farms.find((f) => f.id === selectedFarmId) || farms[0];
  const {
    isRealFarm,
    status: satelliteStatus,
    observation: satelliteObservation,
    error: satelliteError,
    retry: retrySatellite,
  } = useFarmSatelliteAnalysis(currentFarm?.id);
  const { report: environment, isLoading: environmentLoading, isError: environmentError, retry: retryEnvironment } =
    useFarmEnvironment(currentFarm?.id);
  const { weather: liveWeather, isLoading: weatherLoading, isError: weatherError, retry: retryWeather } =
    useFarmWeather(currentFarm?.id);
  const { plan: irrigationPlan, isLoading: irrigationLoading, isError: irrigationError, retry: retryIrrigation } =
    useFarmIrrigation(currentFarm?.id);
  const currentSatellite = currentFarm && satelliteObservation
    ? applyLiveSatellite(currentFarm.satellite, satelliteObservation)
    : currentFarm?.satellite;
  const currentWeather = currentFarm && liveWeather
    ? applyLiveWeather(currentFarm.weather, liveWeather)
    : currentFarm?.weather;

  // Until the real (per-account) farm list has loaded client-side, `farms`
  // is still the SSR-safe placeholder — render an empty shell rather than
  // flash it (keep the sidebar so the layout doesn't jump).
  if (!mounted) {
    return <AppLayout>{null}</AppLayout>;
  }

  if (loadError) {
    return (
      <AppLayout>
        <FarmsLoadError message={loadError} onRetry={() => retryLoad()} />
      </AppLayout>
    );
  }

  if (!currentFarm) {
    return (
      <AppLayout>
        <div className="max-w-md mx-auto text-center py-20 space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-farm-green-light flex items-center justify-center mx-auto">
            <Sprout className="w-7 h-7 text-farm-green" />
          </div>
          <h2 className="text-xl font-bold text-farm-dark">No farms yet</h2>
          <p className="text-farm-muted text-sm">
            Register your first farm to see live satellite health, weather, irrigation and mandi prices here.
          </p>
          <Link
            href="/farms"
            className="inline-flex items-center gap-2 bg-farm-green text-white px-5 py-2.5 rounded-xl font-semibold hover:bg-farm-green-dark transition-all shadow-sm"
          >
            Register a Farm
            <ChevronRight className="w-4 h-4" />
          </Link>
        </div>
      </AppLayout>
    );
  }

  const primaryAlert = currentFarm.weather.alerts?.[0];

  return (
    <AppLayout>
      <div className="max-w-5xl mx-auto space-y-6 pb-16">
        {/* ── Greeting Hero + Farm Selector ── */}
        <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-farm-green-light via-white to-sky-50 border border-farm-border-color p-6 sm:p-7">
          <Sprout className="absolute -right-6 -bottom-8 w-40 h-40 text-farm-green/10 pointer-events-none" strokeWidth={1} />
          <div className="relative z-10 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <p className="text-farm-muted text-sm font-medium">{greeting},</p>
              <h1 className="text-2xl sm:text-3xl font-extrabold text-farm-dark tracking-tight mt-0.5">
                {profile.name && profile.name !== "Farmer" ? profile.name : "Kisan"} 👋
              </h1>
              <p className="text-farm-muted text-xs sm:text-sm mt-1">Here&apos;s the latest update on your farm</p>
            </div>

            <div className="self-start sm:self-auto relative flex-shrink-0">
              <select
                aria-label="Select Active Farm"
                value={selectedFarmId}
                onChange={(e) => setSelectedFarmId(e.target.value)}
                className="appearance-none bg-white border-2 border-farm-green/70 hover:border-farm-green text-farm-dark font-bold text-xs sm:text-sm pl-4 pr-10 py-2.5 rounded-2xl shadow-xs cursor-pointer focus:outline-none focus:ring-2 focus:ring-farm-green/20 transition-all"
              >
                {farms.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name} · {f.crop} · {f.district}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-4 h-4 text-farm-green absolute right-3.5 top-3 pointer-events-none" />
            </div>
          </div>
        </div>

        {/* ── Irrigation Recommendation Card ── */}
        <IrrigationRecommendationCard
          farm={currentFarm}
          isRealFarm={isRealFarm}
          satelliteStatus={satelliteStatus}
          satelliteObservation={satelliteObservation}
          satelliteError={satelliteError}
          retrySatellite={retrySatellite}
          environment={environment}
          environmentLoading={environmentLoading}
          environmentError={environmentError}
          retryEnvironment={retryEnvironment}
          liveWeather={liveWeather}
          weatherLoading={weatherLoading}
          weatherError={weatherError}
          retryWeather={retryWeather}
          irrigationPlan={irrigationPlan}
          irrigationLoading={irrigationLoading}
          irrigationError={irrigationError}
          retryIrrigation={retryIrrigation}
          currentSatellite={currentSatellite!}
          currentWeather={currentWeather!}
        />

        {/* ── Satellite alerts (real farms) / demo weather banner (guests) ── */}
        {isRealFarm ? (
          <AlertsStrip farmId={currentFarm.id} />
        ) : primaryAlert ? (
          <div className="rounded-2xl bg-amber-50 border border-amber-200 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-start gap-3">
              <span className="w-9 h-9 rounded-xl bg-amber-200/70 text-amber-800 flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="w-4 h-4" />
              </span>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-bold text-amber-950">{primaryAlert.headline}</h3>
                  <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-amber-200 text-amber-900">
                    {primaryAlert.severity}
                  </span>
                </div>
                <p className="text-xs text-amber-900 mt-0.5">{primaryAlert.actionAdvice}</p>
              </div>
            </div>
            <Link
              href={`/satellite?farm=${currentFarm.id}`}
              className="self-start sm:self-auto px-4 py-2 bg-white border border-amber-300 rounded-xl text-xs font-bold text-amber-900 hover:bg-amber-100 transition-all flex items-center gap-1 flex-shrink-0"
            >
              View Details <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        ) : (
          <div className="rounded-2xl bg-blue-50 border border-blue-200 p-4 flex items-center gap-3">
            <span className="w-9 h-9 rounded-xl bg-blue-100 text-blue-600 flex items-center justify-center flex-shrink-0">
              <CheckCircle2 className="w-4 h-4" />
            </span>
            <div>
              <h3 className="text-sm font-bold text-farm-dark">No Severe Weather Disruption Forecast</h3>
              <p className="text-xs text-farm-muted mt-0.5">
                Clear conditions prevailing over {currentFarm.district}. Routine farm activities can proceed normally.
              </p>
            </div>
          </div>
        )}

        {/* ── Mandi Price Pulse ── */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold uppercase tracking-wider text-farm-dark flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-farm-green" />
              Mandi Price Pulse
            </h2>
            <span className="text-xs text-farm-muted">Prices from Agmarknet</span>
          </div>

          <MarketPriceCard farmId={currentFarm?.id} />
        </div>

        {/* ── 7-Day Weather Forecast & Details (farmwise location) ── */}
        <div className="space-y-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-farm-dark flex items-center gap-2">
            <CloudSun className="w-4 h-4 text-sky-600" />
            7-Day Weather Forecast — {currentFarm.name}
          </h2>

          {isRealFarm && weatherLoading ? (
            <div className="bg-white rounded-2xl border border-farm-border-color p-6 flex items-center justify-center gap-2 text-sm text-farm-muted">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading forecast…
            </div>
          ) : isRealFarm && weatherError ? (
            <div className="bg-white rounded-2xl border border-farm-border-color p-6 text-sm text-red-700 text-center">
              Couldn&apos;t load the forecast.{" "}
              <button onClick={() => retryWeather()} className="font-semibold underline">
                Retry
              </button>
            </div>
          ) : (
            currentWeather && (
              <FarmWeatherReport
                farmName={currentFarm.name}
                location={currentFarm.address}
                crop={currentFarm.crop}
                weather={{ ...currentWeather, forecast10Days: currentWeather.forecast10Days.slice(0, 7) }}
                isLive={isRealFarm && !!liveWeather}
                fetchedAt={liveWeather?.provenance.fetched_at ?? null}
              />
            )
          )}
        </div>
      </div>
    </AppLayout>
  );
}
