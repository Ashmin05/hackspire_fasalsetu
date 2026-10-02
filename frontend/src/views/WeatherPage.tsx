"use client";


import { useEffect, useState } from "react";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import Footer from "@/components/Footer";
import FarmWeatherReport from "@/components/satellite/FarmWeatherReport";
import { isAuthenticated } from "@/lib/auth/auth-client";
import { useFarmStore, applyLiveWeather } from "@/lib/stores/farmStore";
import { isRealFarmId } from "@/lib/hooks/useFarmSatelliteAnalysis";
import { useFarmWeather } from "@/lib/hooks/useFarmWeather";
import { Cloud, ArrowRight, Loader2, ChevronDown } from "lucide-react";

function Prompt({ title, body, href, cta }: { title: string; body: string; href: string; cta: string }) {
  return (
    <div className="max-w-xl mx-auto text-center py-10 space-y-3">
      <h2 className="text-2xl font-bold text-farm-dark">{title}</h2>
      <p className="text-farm-muted text-sm">{body}</p>
      <Link
        href={href}
        className="inline-flex items-center gap-2 bg-farm-green text-white px-7 py-3.5 rounded-xl font-bold hover:bg-farm-green-dark transition-all shadow-card group"
      >
        {cta} <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
      </Link>
    </div>
  );
}

export default function WeatherPage() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const { farms, mounted } = useFarmStore();
  const realFarms = farms.filter((f) => isRealFarmId(f.id));
  const [selectedFarmId, setSelectedFarmId] = useState<string | undefined>();
  const farm = realFarms.find((f) => f.id === selectedFarmId) ?? realFarms[0];
  const { weather, isLoading, isError, retry } = useFarmWeather(farm?.id);

  useEffect(() => {
    setAuthed(isAuthenticated());
  }, []);

  let body: React.ReactNode;
  if (authed === null || !mounted) {
    body = null;
  } else if (!authed) {
    body = (
      <Prompt
        title="See the forecast for your own field"
        body="Sign in and register your farm to get a live 10-day forecast for its exact location."
        href="/login"
        cta="Sign In"
      />
    );
  } else if (!farm) {
    body = (
      <Prompt
        title="Register a farm first"
        body="The forecast is fetched for your farm's exact location, so add a farm to see it."
        href="/farms"
        cta="Register a Farm"
      />
    );
  } else {
    body = (
      <div className="space-y-4">
        {realFarms.length > 1 && (
          <div className="relative inline-block">
            <select
              aria-label="Select farm"
              value={farm.id}
              onChange={(e) => setSelectedFarmId(e.target.value)}
              className="appearance-none bg-white border-2 border-farm-green/70 hover:border-farm-green text-farm-dark font-bold text-sm pl-4 pr-10 py-2.5 rounded-2xl cursor-pointer focus:outline-none"
            >
              {realFarms.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} · {f.crop}
                </option>
              ))}
            </select>
            <ChevronDown className="w-4 h-4 text-farm-green absolute right-3.5 top-3.5 pointer-events-none" />
          </div>
        )}

        {isLoading ? (
          <div className="bg-white rounded-2xl border border-farm-border-color p-6 flex items-center justify-center gap-2 text-sm text-farm-muted">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading forecast…
          </div>
        ) : isError || !weather ? (
          <div className="bg-white rounded-2xl border border-farm-border-color p-6 text-sm text-red-700 text-center">
            Couldn&apos;t load the forecast.{" "}
            <button onClick={() => retry()} className="font-semibold underline">
              Retry
            </button>
          </div>
        ) : (
          <FarmWeatherReport
            farmName={farm.name}
            location={farm.address}
            crop={farm.crop}
            weather={applyLiveWeather(farm.weather, weather)}
            isLive
            fetchedAt={weather.provenance.fetched_at}
          />
        )}
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white" data-theme="light">
      <Navbar />

      {/* Hero */}
      <div className="pt-24 pb-12 bg-gradient-to-br from-sky-50 to-blue-50 border-b border-farm-border-color">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <div className="inline-flex items-center gap-2 bg-sky-600 text-white text-sm px-4 py-1.5 rounded-full mb-4 font-medium">
            <Cloud className="w-4 h-4" /> Weather
          </div>
          <h1 className="text-4xl sm:text-5xl font-bold text-farm-dark mb-3">Weather for your field.</h1>
          <p className="text-farm-muted text-lg">
            10-day forecast for your farm&apos;s exact location, with heavy-rain and heat-stress flags.
          </p>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-12">{body}</div>

      <Footer />
    </div>
  );
}
