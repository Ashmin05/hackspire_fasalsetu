"use client";



import { useState } from "react";
import {
  Cloud, CloudRain, CloudLightning, Sun, CloudSun, CloudDrizzle,
  Wind, Droplets, Thermometer,
  Calendar, SunMedium,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

export type WeatherSeverity = "critical" | "high" | "moderate" | "info";

export type FarmWeatherAlert = {
  id: string;
  type: string;
  severity: WeatherSeverity;
  timeframe: string;
  headline: string;
  actionAdvice: string;
};

export type DayForecastItem = {
  day: string;
  date: string;
  condition: string;
  iconType: "sun" | "cloud" | "rain" | "storm" | "cloud-sun" | "drizzle";
  hi: number;
  lo: number;
  rainChance: number;
  rainfallMm: number;
  windKmh: number;
  humidity: number;
  uvIndex: number;
  farmingAdvisory: string;
};

export type FarmDetailedWeather = {
  currentTemp: number;
  feelsLike: number;
  condition: string;
  iconType: "sun" | "cloud" | "rain" | "storm" | "cloud-sun" | "drizzle";
  humidity: number;
  windKmh: number;
  windDir: string;
  rainExpected: string;
  uvIndex: number;
  pressureHpa: number;
  alerts: FarmWeatherAlert[];
  forecast10Days: DayForecastItem[];
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function WeatherIcon({ type, className }: { type: string; className?: string }) {
  switch (type) {
    case "sun":
      return <Sun className={className || "w-6 h-6 text-amber-500"} />;
    case "cloud-sun":
      return <CloudSun className={className || "w-6 h-6 text-amber-500"} />;
    case "rain":
      return <CloudRain className={className || "w-6 h-6 text-sky-500"} />;
    case "storm":
      return <CloudLightning className={className || "w-6 h-6 text-purple-600"} />;
    case "drizzle":
      return <CloudDrizzle className={className || "w-6 h-6 text-sky-400"} />;
    case "cloud":
    default:
      return <Cloud className={className || "w-6 h-6 text-slate-400"} />;
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function FarmWeatherReport({
  farmName,
  location,
  crop,
  weather,
  isLive = false,
  fetchedAt = null,
}: {
  farmName: string;
  location: string;
  crop: string;
  weather: FarmDetailedWeather;
  /** True when `weather` came from a live backend forecast (Open-Meteo) rather than demo data. */
  isLive?: boolean;
  /** ISO datetime the live forecast was fetched -- ignored when isLive is false. */
  fetchedAt?: string | null;
}) {
  const [selectedDayIdx, setSelectedDayIdx] = useState(0);
  const activeDay = weather.forecast10Days[selectedDayIdx] || weather.forecast10Days[0];

  return (
    <div className="bg-white rounded-2xl border border-farm-border-color shadow-card overflow-hidden">
      {/* Header bar */}
      <div className="p-5 border-b border-farm-border-color bg-gradient-to-r from-sky-50/70 to-emerald-50/50 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-sky-500/10 flex items-center justify-center text-sky-600">
            <WeatherIcon type={weather.iconType} className="w-6 h-6 text-sky-600" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-bold text-farm-dark text-base">Weather & Forecast</h3>
              <span className="text-xs bg-sky-100 text-sky-800 font-semibold px-2 py-0.5 rounded-full">
                {weather.forecast10Days.length}-Day {isLive ? "Live" : "Demo"} Outlook
              </span>
            </div>
            <p className="text-xs text-farm-muted mt-0.5">
              Specific to <span className="font-medium text-farm-dark">{farmName}</span> ({location}) · Crop: {crop}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs text-farm-muted">
          <span className={`inline-block w-2 h-2 rounded-full ${isLive ? "bg-emerald-500 animate-pulse" : "bg-amber-400"}`} />
          <span>
            {isLive
              ? fetchedAt
                ? `Live · fetched ${new Date(fetchedAt).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`
                : "Live forecast"
              : "Demo data · sign in for a live forecast"}
          </span>
        </div>
      </div>

      <div className="p-5 space-y-6">
        {/* ── Current Conditions Stats Grid ── */}
        <div>
          <h4 className="text-xs font-bold text-farm-muted uppercase tracking-wider mb-3">
            Today at your farm
          </h4>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {/* Temp */}
            <div className="p-3 bg-farm-gray/70 hover:bg-farm-gray rounded-xl border border-farm-border-color/60 transition-colors">
              <div className="flex items-center justify-between text-orange-600 mb-1">
                <span className="text-xs font-medium text-farm-muted">High</span>
                <Thermometer className="w-4 h-4" />
              </div>
              <p className="text-xl font-bold text-farm-dark">{weather.currentTemp}°C</p>
            </div>

            {/* Condition */}
            <div className="p-3 bg-farm-gray/70 hover:bg-farm-gray rounded-xl border border-farm-border-color/60 transition-colors">
              <div className="flex items-center justify-between text-sky-600 mb-1">
                <span className="text-xs font-medium text-farm-muted">Sky</span>
                <WeatherIcon type={weather.iconType} className="w-4 h-4 text-sky-500" />
              </div>
              <p className="text-sm font-bold text-farm-dark truncate">{weather.condition}</p>
              <p className="text-[11px] text-farm-muted mt-0.5">Conditions</p>
            </div>

            {/* Humidity */}
            <div className="p-3 bg-farm-gray/70 hover:bg-farm-gray rounded-xl border border-farm-border-color/60 transition-colors">
              <div className="flex items-center justify-between text-blue-600 mb-1">
                <span className="text-xs font-medium text-farm-muted">Humidity</span>
                <Droplets className="w-4 h-4" />
              </div>
              <p className="text-xl font-bold text-farm-dark">{weather.humidity}%</p>
              <p className="text-[11px] text-farm-muted mt-0.5">
                {weather.humidity > 75 ? "High moisture" : weather.humidity > 45 ? "Optimal" : "Dry air"}
              </p>
            </div>

            {/* Wind */}
            <div className="p-3 bg-farm-gray/70 hover:bg-farm-gray rounded-xl border border-farm-border-color/60 transition-colors">
              <div className="flex items-center justify-between text-teal-600 mb-1">
                <span className="text-xs font-medium text-farm-muted">Wind</span>
                <Wind className="w-4 h-4" />
              </div>
              <p className="text-xl font-bold text-farm-dark">{weather.windKmh} <span className="text-xs font-normal">km/h</span></p>
              <p className="text-[11px] text-farm-muted mt-0.5">Max today</p>
            </div>

            {/* UV Index */}
            <div className="p-3 bg-farm-gray/70 hover:bg-farm-gray rounded-xl border border-farm-border-color/60 transition-colors">
              <div className="flex items-center justify-between text-amber-600 mb-1">
                <span className="text-xs font-medium text-farm-muted">UV Index</span>
                <SunMedium className="w-4 h-4" />
              </div>
              <p className="text-xl font-bold text-farm-dark">{weather.uvIndex}</p>
              <p className="text-[11px] text-farm-muted mt-0.5">
                {weather.uvIndex >= 8 ? "Very High" : weather.uvIndex >= 6 ? "High" : "Moderate"}
              </p>
            </div>

          </div>
        </div>

        {/* ── 10-Day Forecast ── */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-xs font-bold text-farm-muted uppercase tracking-wider flex items-center gap-1.5">
              <Calendar className="w-4 h-4 text-farm-green" />
              {weather.forecast10Days.length}-Day Precipitation & Thermal Forecast
            </h4>
            <span className="text-xs text-farm-muted">Click a day for details</span>
          </div>

          {/* Horizontal scrollable forecast strip */}
          <div className="flex gap-2.5 overflow-x-auto pb-3 pt-1 scrollbar-thin">
            {weather.forecast10Days.map((item, idx) => {
              const isSelected = idx === selectedDayIdx;
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => setSelectedDayIdx(idx)}
                  className={`flex flex-col items-center gap-2 p-3 min-w-[82px] rounded-xl border transition-all text-center flex-shrink-0 cursor-pointer ${
                    isSelected
                      ? "bg-farm-green-light border-farm-green shadow-xs ring-1 ring-farm-green"
                      : "bg-white border-farm-border-color hover:border-farm-green-mid hover:bg-farm-gray/50"
                  }`}
                >
                  <span className={`text-xs font-bold ${isSelected ? "text-farm-green" : "text-farm-dark"}`}>
                    {item.day}
                  </span>
                  <span className="text-[10px] text-farm-muted -mt-1 font-medium">{item.date}</span>

                  <div className="my-0.5">
                    <WeatherIcon type={item.iconType} className="w-6 h-6 mx-auto" />
                  </div>

                  <div>
                    <div className="text-xs font-bold text-farm-dark">
                      {item.hi}° <span className="text-farm-muted font-normal text-[11px]">{item.lo}°</span>
                    </div>
                  </div>

                  {/* Rain badge */}
                  <div
                    className={`flex items-center gap-1 text-[11px] font-semibold px-1.5 py-0.5 rounded-md ${
                      item.rainChance > 50
                        ? "bg-sky-100 text-sky-800"
                        : item.rainChance > 20
                        ? "bg-sky-50 text-sky-600"
                        : "text-slate-400"
                    }`}
                  >
                    <Droplets className="w-3 h-3" />
                    <span>{item.rainChance}%</span>
                  </div>
                </button>
              );
            })}
          </div>

          {/* ── Selected Day Detailed Agricultural Advisory ── */}
          {activeDay && (
            <div className="mt-3 p-4 rounded-xl bg-gradient-to-br from-farm-green-light/40 to-sky-50/40 border border-farm-green/30">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-farm-green/20">
                <div className="flex items-center gap-3">
                  <WeatherIcon type={activeDay.iconType} className="w-8 h-8" />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-farm-dark text-sm">
                        {activeDay.day}, {activeDay.date} — {activeDay.condition}
                      </span>
                      {selectedDayIdx === 0 && (
                        <span className="text-[10px] font-bold bg-farm-green text-white px-2 py-0.5 rounded-full">
                          Today
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-farm-muted mt-0.5">
                      Expected High: <strong className="text-farm-dark">{activeDay.hi}°C</strong> | Low: <strong className="text-farm-dark">{activeDay.lo}°C</strong> | Rain: <strong className="text-sky-600">{activeDay.rainfallMm} mm ({activeDay.rainChance}%)</strong>
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-4 text-xs">
                  <div className="flex items-center gap-1.5 text-farm-muted">
                    <Droplets className="w-4 h-4 text-blue-500" />
                    <span>Humidity: <strong className="text-farm-dark">{activeDay.humidity}%</strong></span>
                  </div>
                  <div className="flex items-center gap-1.5 text-farm-muted">
                    <Wind className="w-4 h-4 text-teal-500" />
                    <span>Wind: <strong className="text-farm-dark">{activeDay.windKmh} km/h</strong></span>
                  </div>
                  <div className="flex items-center gap-1.5 text-farm-muted">
                    <SunMedium className="w-4 h-4 text-amber-500" />
                    <span>UV: <strong className="text-farm-dark">{activeDay.uvIndex}</strong></span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
