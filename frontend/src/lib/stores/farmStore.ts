"use client";



import { useState, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { DayForecastItem, FarmDetailedWeather, FarmWeatherAlert } from "@/components/satellite/FarmWeatherReport";
import { getUserId } from "@/lib/auth/auth-client";
import { listFarms, createFarm, deleteFarm, type BackendFarm, type SoilReportInput } from "@/lib/api/farms-client";
import type { SatelliteObservation } from "@/lib/api/satellite-client";
import type { DailyWeather, FarmWeather } from "@/lib/api/weather-client";

// ── Types ─────────────────────────────────────────────────────────────────────

export type FarmYield = {
  estimatedQuintals: number;
  expectedPricePerQtl: number; // in ₹
  totalEstimatedValue: number; // in ₹
  harvestWindow: string;
  historicalYieldComparison: string; // e.g. "+12% vs last season"
};

export type FarmSoil = {
  ph: number;
  nitrogen: "Low" | "Medium" | "High";
  phosphorus: "Low" | "Medium" | "High";
  potassium: "Low" | "Medium" | "High";
  organicMatter: string;
  moisturePercent: number;
  healthRating: "Optimal" | "Moderate" | "Needs Attention";
};

export type FarmWater = {
  status: "Optimal" | "Moderate Stress" | "Excess Rain Risk";
  canopyMoisturePercent: number;
  soilMoisturePercent: number;
  lastIrrigationDaysAgo: number;
  nextRecommendedAction: string;
};

export type NdviHistoryPoint = {
  date: string; // e.g. "Jun 25", "Jul 10"
  ndvi: number;
  benchmark: number; // optimal curve benchmark
  stage: string; // "Germination", "Vegetative", "Bulbing / Tillering"
};

export type StressZone = {
  id: string;
  name: string;
  type: "Water Stress" | "Nutrient Deficit" | "Pest Vulnerability" | "Excess Water";
  areaAcres: number;
  severity: "high" | "moderate" | "low";
  description: string;
  actionRequired: string;
};

export type SatelliteImageMetadata = {
  satelliteMission: string; // e.g. "ESA Sentinel-2B L2A"
  acquisitionDate: string; // e.g. "2026-09-20 10:42 UTC"
  cloudCoveragePercent: number; // e.g. 0.3
  spatialResolution: string; // e.g. "10m Multispectral"
  dataQualityConfidence: number; // e.g. 98.4
  sunElevationAngle: string; // e.g. "54.2°"
};

export type FarmSatellite = {
  // Current statistics
  meanNdvi: number;
  minNdvi: number;
  maxNdvi: number;
  ndwi: number; // Water index (-1 to 1)
  canopyVigourLabel: "Excellent" | "Good" | "Fair" | "Poor";
  healthyCanopyPercent: number;
  moderateCanopyPercent: number;
  stressedCanopyPercent: number;
  
  // Historical timeline
  history: NdviHistoryPoint[];

  // Field stress zones
  stressZones: StressZone[];

  // Image quality & metadata
  metadata: SatelliteImageMetadata;
};

export type Farm = {
  id: string;
  name: string;
  address: string;
  district: string;
  state: string;
  crop: string;
  variety: string;
  plantingDate: string;
  areaAcres: number;
  center: [number, number]; // [lng, lat]
  polygonGeoJson?: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon> | null;
  
  // Core Domain Modules
  yield: FarmYield;
  soil: FarmSoil;
  water: FarmWater;
  weather: FarmDetailedWeather;
  satellite: FarmSatellite;
};

// The fields a farmer actually fills in when registering a farm — everything
// else on `Farm` (yield/soil/water/weather/satellite) is generated demo
// content layered on top (see enrichFarmDraft), since none of those modules
// have real backend data yet.
export type FarmDraft = {
  name: string;
  address: string;
  district: string;
  state: string;
  crop: string;
  variety: string;
  plantingDate: string; // ISO yyyy-mm-dd
  irrigationMethod?: string | null;
  center: [number, number]; // [lng, lat]
  polygonGeoJson: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon> | null;
  // Real soil report values from the registration wizard's "I have a Soil
  // Health Card / Lab Test Report" step. When present, this is the farm's
  // authoritative soil reading -- saved to the backend and used instead of
  // the generated defaults below and instead of the OpenLandMap satellite
  // estimate (see EnvironmentReportCard / GET /farms/{id}/environment).
  soilOverride?: Partial<Pick<FarmSoil, "ph" | "nitrogen" | "phosphorus" | "potassium" | "organicMatter">>;
};

// Fills in the demo/mock domain modules (yield, soil, water, weather,
// satellite) around a real farm's core fields. Used for every farm shown in
// the app today, guest or signed-in, since none of those modules are backed
// by a real service yet — only the core fields (this function's `id` and
// `draft`) come from somewhere real (the backend, for signed-in accounts).
export function enrichFarmDraft(id: string, draft: FarmDraft, areaAcres: number): Farm {
  const acres = areaAcres || 2.5;
  const estQuintals = Math.round(acres * 22);
  const estPrice = 2400;

  return {
    id,
    name: draft.name,
    address: draft.address,
    district: draft.district,
    state: draft.state,
    crop: draft.crop,
    variety: draft.variety,
    plantingDate: draft.plantingDate,
    areaAcres: acres,
    center: draft.center,
    polygonGeoJson: draft.polygonGeoJson,
    yield: {
      estimatedQuintals: estQuintals,
      expectedPricePerQtl: estPrice,
      totalEstimatedValue: estQuintals * estPrice,
      harvestWindow: "3–4 months post sowing",
      historicalYieldComparison: "New field benchmark",
    },
    soil: {
      ph: draft.soilOverride?.ph ?? 6.8,
      nitrogen: draft.soilOverride?.nitrogen ?? "Medium",
      phosphorus: draft.soilOverride?.phosphorus ?? "Medium",
      potassium: draft.soilOverride?.potassium ?? "Medium",
      organicMatter: draft.soilOverride?.organicMatter ?? "2.1%",
      moisturePercent: 30,
      healthRating: "Optimal",
    },
    water: {
      status: "Optimal",
      canopyMoisturePercent: 72,
      soilMoisturePercent: 30,
      lastIrrigationDaysAgo: 1,
      nextRecommendedAction: "Maintain standard crop watering schedule.",
    },
    weather: generateFarmWeather(draft.name, draft.address, draft.crop),
    satellite: {
      meanNdvi: 0.68,
      minNdvi: 0.42,
      maxNdvi: 0.81,
      ndwi: 0.42,
      canopyVigourLabel: "Good",
      healthyCanopyPercent: 80,
      moderateCanopyPercent: 16,
      stressedCanopyPercent: 4,
      history: [
        { date: "Planting", ndvi: 0.2, benchmark: 0.2, stage: "Sowing" },
        { date: "Current", ndvi: 0.68, benchmark: 0.65, stage: "Vegetative" },
      ],
      stressZones: [],
      metadata: {
        satelliteMission: "ESA Sentinel-2B L2A",
        acquisitionDate: "Recent Overpass",
        cloudCoveragePercent: 0.3,
        spatialResolution: "10m Multispectral",
        dataQualityConfidence: 98.2,
        sunElevationAngle: "58°",
      },
    },
  };
}

// Overlays a real Sentinel-2 SatelliteObservation (backend/app/schemas/satellite.py)
// onto a farm's synthetic FarmSatellite -- used wherever a real, signed-in
// farm has a live analysis available (see useFarmSatelliteAnalysis.ts).
// Only the "current stats" fields are real; `history` and `stressZones` stay
// synthetic since the backend doesn't compute those yet (see EXPLAIN.md §5.6/§9)
// -- callers should visibly label which parts of the panel are live vs. demo.
export function applyLiveSatellite(base: FarmSatellite, observation: SatelliteObservation): FarmSatellite {
  const missionLabel =
    observation.satellite === "S2A"
      ? "ESA Sentinel-2A L2A (Live)"
      : observation.satellite === "S2B"
        ? "ESA Sentinel-2B L2A (Live)"
        : "ESA Sentinel-2 L2A (Live)";
  const vigourLabel: FarmSatellite["canopyVigourLabel"] =
    observation.health_score >= 80
      ? "Excellent"
      : observation.health_score >= 60
        ? "Good"
        : observation.health_score >= 40
          ? "Fair"
          : "Poor";

  return {
    ...base,
    meanNdvi: observation.ndvi.mean,
    minNdvi: observation.ndvi.min,
    maxNdvi: observation.ndvi.max,
    ndwi: observation.ndwi.mean,
    canopyVigourLabel: vigourLabel,
    healthyCanopyPercent: observation.healthy_pct,
    moderateCanopyPercent: observation.moderate_pct,
    stressedCanopyPercent: observation.stressed_pct,
    metadata: {
      satelliteMission: missionLabel,
      acquisitionDate: observation.image_date,
      cloudCoveragePercent: observation.cloud_pct,
      spatialResolution: "10m Multispectral",
      dataQualityConfidence: Math.round((100 - observation.cloud_pct) * 10) / 10,
      sunElevationAngle: "—",
    },
  };
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Hand-rolled, like SourceBadge.formatPassDate -- reading the ISO date's
// own y/m/d via Date.UTC (rather than `new Date(isoString).getDay()`, which
// reads back in the browser's *local* timezone) never shifts a day.
function _dayLabel(isoDate: string, index: number): string {
  if (index === 0) return "Today";
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  return WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
}

function _shortDate(isoDate: string): string {
  const [, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  return `${MONTHS[m - 1]} ${String(d).padStart(2, "0")}`;
}

// No cloud-cover field is fetched from Open-Meteo (see DAILY_PARAMS in
// backend/app/integrations/open_meteo_client.py) -- condition/icon are
// approximated from precipitation sum/probability instead.
function _conditionFromDay(day: DailyWeather): { condition: string; iconType: FarmDetailedWeather["iconType"] } {
  if (day.precipitation_sum_mm > 25) return { condition: "Heavy Rain", iconType: "storm" };
  if (day.precipitation_sum_mm > 2 || (day.precipitation_probability_pct ?? 0) >= 50) {
    return { condition: "Rain", iconType: "rain" };
  }
  if ((day.precipitation_probability_pct ?? 0) >= 20) {
    return { condition: "Partly Cloudy", iconType: "cloud-sun" };
  }
  return { condition: "Sunny", iconType: "sun" };
}

function _advisoryFromFlags(flags: DailyWeather["flags"]): string {
  if (flags.heavy_rain) return "Heavy rain expected — postpone spray operations and check drainage.";
  if (flags.heat_stress) return "High heat stress risk — irrigate early morning or evening, avoid midday work.";
  if (flags.good_spray_window) return "Good spray window — low rain risk and calm winds.";
  return "Normal conditions — follow standard crop schedule.";
}

// Overlays a real Open-Meteo forecast (backend/app/schemas/weather.py) onto
// a farm's synthetic FarmDetailedWeather -- used wherever a real, signed-in
// farm has a live forecast available (see useFarmWeather.ts). `daily[0]` is
// treated as "today"/current conditions, since Open-Meteo has no separate
// current-weather call wired up here. feelsLike/windDir/pressureHpa have no
// real source (not in DAILY_PARAMS) and stay as the base/demo value.
export function applyLiveWeather(base: FarmDetailedWeather, weather: FarmWeather): FarmDetailedWeather {
  const days = weather.daily;
  if (days.length === 0) return base;
  const today = days[0];
  const { condition, iconType } = _conditionFromDay(today);
  const currentTemp = Math.round(today.temp_max_c);

  const forecast10Days: DayForecastItem[] = days.map((day, i) => {
    const dayCondition = _conditionFromDay(day);
    return {
      day: _dayLabel(day.date, i),
      date: _shortDate(day.date),
      condition: dayCondition.condition,
      iconType: dayCondition.iconType,
      hi: Math.round(day.temp_max_c),
      lo: Math.round(day.temp_min_c),
      rainChance: day.precipitation_probability_pct ?? 0,
      rainfallMm: day.precipitation_sum_mm,
      windKmh: Math.round(day.wind_speed_max_kmh),
      humidity: day.relative_humidity_pct !== null ? Math.round(day.relative_humidity_pct) : 0,
      uvIndex: day.uv_index_max !== null ? Math.round(day.uv_index_max) : 0,
      farmingAdvisory: _advisoryFromFlags(day.flags),
    };
  });

  const alerts: FarmWeatherAlert[] = [];
  if (today.flags.heat_stress) {
    alerts.push({
      id: "live-heat-stress",
      type: "Heat Stress",
      severity: "critical",
      timeframe: "Today",
      headline: `High heat stress risk (${currentTemp}°C)`,
      actionAdvice: "Irrigate early morning or evening to reduce crop heat stress; avoid midday field work.",
    });
  }
  if (today.flags.heavy_rain) {
    alerts.push({
      id: "live-heavy-rain",
      type: "Heavy Rain",
      severity: "high",
      timeframe: "Today",
      headline: `Heavy rain expected (${today.precipitation_sum_mm.toFixed(0)}mm)`,
      actionAdvice: "Postpone spraying and check field drainage before the rain arrives.",
    });
  }
  if (today.flags.good_spray_window) {
    alerts.push({
      id: "live-good-spray",
      type: "Spray Window",
      severity: "info",
      timeframe: "Today",
      headline: "Good spray window today",
      actionAdvice: "Low rain chance and calm winds — a good window for spraying.",
    });
  }

  const rain3d = days.slice(0, 3).reduce((sum, d) => sum + d.precipitation_sum_mm, 0);

  return {
    ...base,
    currentTemp,
    feelsLike: currentTemp,
    condition,
    iconType,
    humidity: today.relative_humidity_pct !== null ? Math.round(today.relative_humidity_pct) : base.humidity,
    windKmh: Math.round(today.wind_speed_max_kmh),
    rainExpected: `${rain3d.toFixed(1)}mm in next 3 days`,
    uvIndex: today.uv_index_max !== null ? Math.round(today.uv_index_max) : base.uvIndex,
    alerts: alerts.length > 0 ? alerts : base.alerts,
    forecast10Days,
  };
}

// Maps a real farm row from the backend into the same enriched Farm shape
// used everywhere in the UI. area_ha/centroid are server-computed (see
// backend/app/core/geometry.py) — never trust client-side area math for a
// farm that's actually persisted.
function backendFarmToFarm(b: BackendFarm): Farm {
  const draft: FarmDraft = {
    name: b.name,
    address: b.address ?? [b.district, b.state].filter(Boolean).join(", "),
    district: b.district ?? "",
    state: b.state ?? "",
    crop: b.crop,
    variety: b.variety ?? "",
    plantingDate: b.sowing_date,
    irrigationMethod: b.irrigation_method,
    center: [b.centroid_lng, b.centroid_lat],
    polygonGeoJson: { type: "Feature", properties: {}, geometry: b.polygon_geojson },
    soilOverride: b.soil_report
      ? {
          ph: b.soil_report.ph ?? undefined,
          nitrogen: b.soil_report.nitrogen ?? undefined,
          phosphorus: b.soil_report.phosphorus ?? undefined,
          potassium: b.soil_report.potassium ?? undefined,
          organicMatter:
            b.soil_report.organic_matter_pct !== null ? `${b.soil_report.organic_matter_pct}%` : undefined,
        }
      : undefined,
  };
  const areaAcres = Math.round(b.area_ha * 2.47105 * 100) / 100;
  return enrichFarmDraft(b.id, draft, areaAcres);
}

// ── Default 2 Canonical Farms ─────────────────────────────────────────────────

export const DEFAULT_FARMS: Farm[] = [
  {
    id: "farm-1",
    name: "North Onion Field",
    address: "Dindori Road, Nashik, Maharashtra",
    district: "Nashik",
    state: "Maharashtra",
    crop: "Onion",
    variety: "Bhima Super (Red)",
    plantingDate: "2026-06-10",
    areaAcres: 3.2,
    center: [73.7898, 19.9975],
    yield: {
      estimatedQuintals: 72,
      expectedPricePerQtl: 2400,
      totalEstimatedValue: 172800,
      harvestWindow: "Mid-October 2026",
      historicalYieldComparison: "+8% above Nashik average",
    },
    soil: {
      ph: 6.8,
      nitrogen: "Medium",
      phosphorus: "High",
      potassium: "Medium",
      organicMatter: "2.1%",
      moisturePercent: 28,
      healthRating: "Optimal",
    },
    water: {
      status: "Optimal",
      canopyMoisturePercent: 74,
      soilMoisturePercent: 28,
      lastIrrigationDaysAgo: 3,
      nextRecommendedAction: "Light drip irrigation cycle in 2 days during evening hours.",
    },
    weather: {
      currentTemp: 29,
      feelsLike: 31,
      condition: "Partly Cloudy",
      iconType: "cloud-sun",
      humidity: 64,
      windKmh: 14,
      windDir: "NE",
      rainExpected: "12mm in 3 days",
      uvIndex: 6,
      pressureHpa: 1012,
      alerts: [
        {
          id: "alert-nsh-1",
          type: "Thermal Advisory",
          severity: "moderate",
          timeframe: "Next 48–72h",
          headline: "Afternoon Heat Peak (+33°C) Forecasted",
          actionAdvice: "Irrigate onion crop in early morning or evening to prevent heat shock and bulb cracking.",
        },
      ],
      forecast10Days: [
        { day: "Today", date: "Sep 22", condition: "Partly Cloudy", iconType: "cloud-sun", hi: 31, lo: 21, rainChance: 10, rainfallMm: 0, windKmh: 14, humidity: 64, uvIndex: 6, farmingAdvisory: "Ideal day for foliar micronutrient spray. Low wind drift risk." },
        { day: "Wed", date: "Sep 23", condition: "Sunny & Warm", iconType: "sun", hi: 32, lo: 22, rainChance: 5, rainfallMm: 0, windKmh: 12, humidity: 58, uvIndex: 7, farmingAdvisory: "Good conditions for general weeding and drip line maintenance." },
        { day: "Thu", date: "Sep 24", condition: "Overcast", iconType: "cloud", hi: 29, lo: 20, rainChance: 25, rainfallMm: 2.1, windKmh: 16, humidity: 70, uvIndex: 5, farmingAdvisory: "Cloud cover increasing. Monitor onion leaf margins for thrips." },
        { day: "Fri", date: "Sep 25", condition: "Light Rain", iconType: "rain", hi: 28, lo: 20, rainChance: 65, rainfallMm: 8.5, windKmh: 18, humidity: 80, uvIndex: 4, farmingAdvisory: "Hold off on applying urea or water-soluble fertilizer ahead of rain." },
        { day: "Sat", date: "Sep 26", condition: "Scattered Rain", iconType: "rain", hi: 27, lo: 19, rainChance: 55, rainfallMm: 4.0, windKmh: 15, humidity: 82, uvIndex: 4, farmingAdvisory: "Check furrows and ensure no standing water around bulb root zones." },
        { day: "Sun", date: "Sep 27", condition: "Clearing Sky", iconType: "cloud-sun", hi: 29, lo: 19, rainChance: 20, rainfallMm: 0.5, windKmh: 11, humidity: 68, uvIndex: 6, farmingAdvisory: "Favorable root aeration. Soil moisture will remain high." },
        { day: "Mon", date: "Sep 28", condition: "Sunny", iconType: "sun", hi: 31, lo: 20, rainChance: 5, rainfallMm: 0, windKmh: 10, humidity: 60, uvIndex: 7, farmingAdvisory: "Excellent sunny window to apply preventive bio-fungicide for purple blotch." },
        { day: "Tue", date: "Sep 29", condition: "Sunny", iconType: "sun", hi: 32, lo: 21, rainChance: 5, rainfallMm: 0, windKmh: 9, humidity: 55, uvIndex: 7, farmingAdvisory: "Standard watering schedule; soil moisture retention remains healthy." },
        { day: "Wed", date: "Sep 30", condition: "Clear Skies", iconType: "sun", hi: 33, lo: 22, rainChance: 0, rainfallMm: 0, windKmh: 12, humidity: 52, uvIndex: 8, farmingAdvisory: "High solar radiation; ensure mulch coverage is intact." },
        { day: "Thu", date: "Oct 01", condition: "Partly Cloudy", iconType: "cloud-sun", hi: 30, lo: 21, rainChance: 15, rainfallMm: 0.2, windKmh: 13, humidity: 62, uvIndex: 6, farmingAdvisory: "Stable weather conditions across Nashik valley." },
      ],
    },
    satellite: {
      meanNdvi: 0.72,
      minNdvi: 0.48,
      maxNdvi: 0.84,
      ndwi: 0.45,
      canopyVigourLabel: "Good",
      healthyCanopyPercent: 82,
      moderateCanopyPercent: 14,
      stressedCanopyPercent: 4,
      history: [
        { date: "Jun 20", ndvi: 0.22, benchmark: 0.20, stage: "Transplanting" },
        { date: "Jul 05", ndvi: 0.38, benchmark: 0.35, stage: "Root Establishment" },
        { date: "Jul 20", ndvi: 0.52, benchmark: 0.50, stage: "Active Foliage" },
        { date: "Aug 10", ndvi: 0.65, benchmark: 0.62, stage: "Canopy Expansion" },
        { date: "Aug 28", ndvi: 0.74, benchmark: 0.70, stage: "Bulb Initiation" },
        { date: "Sep 15", ndvi: 0.72, benchmark: 0.71, stage: "Bulb Development" },
      ],
      stressZones: [
        {
          id: "sz-1",
          name: "South-West Furrow Edge",
          type: "Excess Water",
          areaAcres: 0.25,
          severity: "low",
          description: "Slight water stagnation detected after last irrigation flush.",
          actionRequired: "Clean out runoff furrow drainage outlet.",
        },
      ],
      metadata: {
        satelliteMission: "ESA Sentinel-2B L2A (BOA Reflectance)",
        acquisitionDate: "2026-09-20 10:42 UTC",
        cloudCoveragePercent: 0.2,
        spatialResolution: "10m Multispectral GSD",
        dataQualityConfidence: 98.8,
        sunElevationAngle: "58.4°",
      },
    },
  },
  {
    id: "farm-2",
    name: "South Wheat Block",
    address: "Hadapsar Rural, Pune, Maharashtra",
    district: "Pune",
    state: "Maharashtra",
    crop: "Wheat",
    variety: "GW 322 (Sharbati)",
    plantingDate: "2026-07-01",
    areaAcres: 5.5,
    center: [73.8567, 18.5204],
    yield: {
      estimatedQuintals: 123,
      expectedPricePerQtl: 2275,
      totalEstimatedValue: 279825,
      harvestWindow: "Late November 2026",
      historicalYieldComparison: "+5% vs regional baseline",
    },
    soil: {
      ph: 7.2,
      nitrogen: "Low",
      phosphorus: "Medium",
      potassium: "High",
      organicMatter: "1.8%",
      moisturePercent: 38,
      healthRating: "Moderate",
    },
    water: {
      status: "Excess Rain Risk",
      canopyMoisturePercent: 88,
      soilMoisturePercent: 38,
      lastIrrigationDaysAgo: 7,
      nextRecommendedAction: "Pause all artificial irrigation. Heavy monsoon rain forecast in 48 hours.",
    },
    weather: {
      currentTemp: 25,
      feelsLike: 27,
      condition: "Overcast & Humid",
      iconType: "cloud",
      humidity: 82,
      windKmh: 24,
      windDir: "SW",
      rainExpected: "38mm in next 48h",
      uvIndex: 4,
      pressureHpa: 1007,
      alerts: [
        {
          id: "alert-pune-1",
          type: "Heavy Rain Warning",
          severity: "critical",
          timeframe: "Next 24–48 hours",
          headline: "Heavy Rainfall Expected (65–85 mm)",
          actionAdvice: "Clear drainage trenches immediately. Prevent water stagnation around wheat seedlings to avoid damping-off and root rot.",
        },
        {
          id: "alert-pune-2",
          type: "High Wind Alert",
          severity: "high",
          timeframe: "Thursday Evening",
          headline: "Squall Winds up to 42 km/h",
          actionAdvice: "Postpone chemical spraying and secure nursery sheets or lightweight farm equipment.",
        },
      ],
      forecast10Days: [
        { day: "Today", date: "Sep 22", condition: "Overcast", iconType: "cloud", hi: 26, lo: 19, rainChance: 40, rainfallMm: 3.2, windKmh: 22, humidity: 82, uvIndex: 4, farmingAdvisory: "Inspect seed beds and prepare secondary outflow canals before heavy rain starts." },
        { day: "Wed", date: "Sep 23", condition: "Thunderstorms", iconType: "storm", hi: 24, lo: 18, rainChance: 85, rainfallMm: 38.0, windKmh: 35, humidity: 92, uvIndex: 3, farmingAdvisory: "Cease all field machinery operations to prevent soil compaction and rutting." },
        { day: "Thu", date: "Sep 24", condition: "Heavy Rain", iconType: "rain", hi: 23, lo: 17, rainChance: 90, rainfallMm: 45.0, windKmh: 42, humidity: 95, uvIndex: 2, farmingAdvisory: "Strictly avoid fertilizer broadcast. Monitor field boundary ridges for overflow." },
        { day: "Fri", date: "Sep 25", condition: "Moderate Showers", iconType: "rain", hi: 25, lo: 18, rainChance: 60, rainfallMm: 12.0, windKmh: 24, humidity: 88, uvIndex: 4, farmingAdvisory: "Showers tapering off. Drain standing water from furrow ends." },
        { day: "Sat", date: "Sep 26", condition: "Passing Showers", iconType: "drizzle", hi: 27, lo: 19, rainChance: 35, rainfallMm: 3.5, windKmh: 18, humidity: 79, uvIndex: 5, farmingAdvisory: "Drying cycle begins. Check emerged seedlings for silt crusting." },
        { day: "Sun", date: "Sep 27", condition: "Partly Cloudy", iconType: "cloud-sun", hi: 28, lo: 18, rainChance: 20, rainfallMm: 0, windKmh: 14, humidity: 72, uvIndex: 6, farmingAdvisory: "Sunlight returns. Allow topsoil to aerate naturally before field entry." },
        { day: "Mon", date: "Sep 28", condition: "Sunny", iconType: "sun", hi: 30, lo: 19, rainChance: 10, rainfallMm: 0, windKmh: 12, humidity: 65, uvIndex: 7, farmingAdvisory: "Favorable weather window for prophylactic wheat rust inspection." },
        { day: "Tue", date: "Sep 29", condition: "Sunny", iconType: "sun", hi: 31, lo: 20, rainChance: 5, rainfallMm: 0, windKmh: 10, humidity: 62, uvIndex: 7, farmingAdvisory: "Ample soil moisture from recent rain; pause irrigation pumps." },
        { day: "Wed", date: "Sep 30", condition: "Clear & Bright", iconType: "sun", hi: 32, lo: 20, rainChance: 5, rainfallMm: 0, windKmh: 11, humidity: 58, uvIndex: 8, farmingAdvisory: "Strong photosynthetic conditions for young wheat tillering." },
        { day: "Thu", date: "Oct 01", condition: "Sunny", iconType: "sun", hi: 31, lo: 21, rainChance: 10, rainfallMm: 0, windKmh: 13, humidity: 60, uvIndex: 7, farmingAdvisory: "Stable weather conditions across the Pune agricultural zone." },
      ],
    },
    satellite: {
      meanNdvi: 0.54,
      minNdvi: 0.32,
      maxNdvi: 0.69,
      ndwi: 0.62,
      canopyVigourLabel: "Fair",
      healthyCanopyPercent: 64,
      moderateCanopyPercent: 24,
      stressedCanopyPercent: 12,
      history: [
        { date: "Jul 05", ndvi: 0.18, benchmark: 0.19, stage: "Emergence" },
        { date: "Jul 20", ndvi: 0.30, benchmark: 0.32, stage: "Crown Rooting" },
        { date: "Aug 05", ndvi: 0.44, benchmark: 0.48, stage: "Early Tillering" },
        { date: "Aug 25", ndvi: 0.51, benchmark: 0.56, stage: "Active Tillering" },
        { date: "Sep 15", ndvi: 0.54, benchmark: 0.60, stage: "Stem Elongation" },
      ],
      stressZones: [
        {
          id: "sz-2",
          name: "Eastern Plot Lowland",
          type: "Nutrient Deficit",
          areaAcres: 0.6,
          severity: "moderate",
          description: "Pale green canopy signature (NDVI < 0.38) indicating localized Nitrogen leaching.",
          actionRequired: "Apply targeted top-dress nitrogen booster once field soil drains.",
        },
        {
          id: "sz-3",
          name: "Northern Slope Margin",
          type: "Water Stress",
          areaAcres: 0.3,
          severity: "low",
          description: "Rapid runoff area with slightly depressed vegetative index.",
          actionRequired: "Reinforce contour bund to improve percolation.",
        },
      ],
      metadata: {
        satelliteMission: "ESA Sentinel-2A L2A (BOA Reflectance)",
        acquisitionDate: "2026-09-19 05:18 UTC",
        cloudCoveragePercent: 0.6,
        spatialResolution: "10m Multispectral GSD",
        dataQualityConfidence: 97.5,
        sunElevationAngle: "61.2°",
      },
    },
  },
];

const STORAGE_KEY_BASE = "fasalsetu_farms_v2";
const USER_KEY_BASE = "fasalsetu_user_v2";

// Namespaces local data by the logged-in user's id, so switching accounts on
// the same browser never shows one user's farms/profile to another. Signed-out
// visitors (no account) share a "guest" namespace that carries the demo data —
// real accounts always start from a clean, empty slate.
function scopedKey(base: string): string {
  return `${base}:${getUserId() ?? "guest"}`;
}

export function getStoredFarms(): Farm[] {
  if (typeof window === "undefined") return DEFAULT_FARMS;
  const isGuest = getUserId() === null;
  try {
    const raw = localStorage.getItem(scopedKey(STORAGE_KEY_BASE));
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed;
    }
  } catch (e) {
    console.error("Error reading farms from localStorage", e);
  }
  // First visit for this identity: guests browsing without an account get
  // the canonical demo dataset to explore. A real, signed-in account never
  // sees fabricated farm data — it starts empty until they register a real
  // farm of their own.
  return isGuest ? DEFAULT_FARMS : [];
}

export function saveFarms(farms: Farm[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(scopedKey(STORAGE_KEY_BASE), JSON.stringify(farms));
    window.dispatchEvent(new Event("fasalsetu_farms_updated"));
  } catch (e) {
    console.error("Error saving farms", e);
  }
}

export function useFarmStore() {
  // `mounted` starts false on both the server and the client's first render
  // (getUserId()/getStoredFarms() depend on localStorage, which doesn't
  // exist server-side) — resolving who's signed in inside an effect, rather
  // than during render, avoids a React hydration mismatch. Consumers should
  // treat `farms` as not-yet-authoritative until `mounted` is true.
  const [mounted, setMounted] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const [guestFarms, setGuestFarms] = useState<Farm[]>(DEFAULT_FARMS);
  const queryClient = useQueryClient();

  // Guest (signed-out) until we've actually checked — matches the "isGuest"
  // default every other part of this store already assumes before mount.
  const isGuest = mounted ? userId === null : true;

  useEffect(() => {
    const uid = getUserId();
    setUserId(uid);
    setMounted(true);
    if (uid === null) {
      setGuestFarms(getStoredFarms());
    }
  }, []);

  useEffect(() => {
    if (!mounted || userId !== null) return;
    const handleUpdate = () => setGuestFarms(getStoredFarms());
    window.addEventListener("fasalsetu_farms_updated", handleUpdate);
    return () => window.removeEventListener("fasalsetu_farms_updated", handleUpdate);
  }, [mounted, userId]);

  // Signed-in accounts: farms live in the database, fetched through the real
  // backend. Guests never hit this (query stays disabled) and keep using
  // the local demo dataset above.
  const farmsQuery = useQuery({
    queryKey: ["farms", userId],
    queryFn: async () => (await listFarms()).map(backendFarmToFarm),
    enabled: mounted && userId !== null,
  });

  const farms = isGuest ? guestFarms : farmsQuery.data ?? [];
  // Ready only once the load has actually settled. Not `!isLoading`: while
  // TanStack Query waits to retry (it pauses retries in a background tab)
  // the query is neither loading nor errored, and `farms` would read as an
  // empty account.
  const ready = mounted && (isGuest || farmsQuery.isSuccess || farmsQuery.isError);
  // A failed load must never read as "this account has no farms" -- pages
  // show an error + retry instead of the empty "Register a farm" state.
  const loadError =
    !isGuest && farmsQuery.isError && !farmsQuery.data
      ? farmsQuery.error instanceof Error
        ? farmsQuery.error.message
        : "Couldn't load your farms."
      : null;
  const retryLoad = farmsQuery.refetch;

  const addFarm = useCallback(
    async (draft: FarmDraft, clientAreaAcres: number): Promise<Farm> => {
      if (isGuest) {
        const farm = enrichFarmDraft(`farm-${Date.now()}`, draft, clientAreaAcres);
        const updated = [...getStoredFarms(), farm];
        saveFarms(updated);
        setGuestFarms(updated);
        return farm;
      }

      const geometry = draft.polygonGeoJson?.geometry;
      if (!geometry) throw new Error("Draw a field boundary before saving.");

      const soil = draft.soilOverride;
      const soilReport: SoilReportInput | undefined = soil
        ? {
            ph: soil.ph ?? null,
            nitrogen: soil.nitrogen ?? null,
            phosphorus: soil.phosphorus ?? null,
            potassium: soil.potassium ?? null,
            organic_matter_pct: soil.organicMatter ? parseFloat(soil.organicMatter) || null : null,
          }
        : undefined;

      const backendFarm = await createFarm({
        name: draft.name,
        crop: draft.crop,
        variety: draft.variety || null,
        sowing_date: draft.plantingDate,
        irrigation_method: draft.irrigationMethod ?? null,
        polygon_geojson: geometry as GeoJSON.Polygon,
        state: draft.state || null,
        district: draft.district || null,
        address: draft.address || null,
        soil_report: soilReport,
      });
      await queryClient.invalidateQueries({ queryKey: ["farms", userId] });
      return backendFarmToFarm(backendFarm);
    },
    [isGuest, queryClient, userId]
  );

  const removeFarm = useCallback(
    async (farmId: string): Promise<void> => {
      if (isGuest) {
        const updated = getStoredFarms().filter((f) => f.id !== farmId);
        saveFarms(updated);
        setGuestFarms(updated);
        return;
      }
      await deleteFarm(farmId);
      await queryClient.invalidateQueries({ queryKey: ["farms", userId] });
    },
    [isGuest, queryClient, userId]
  );

  const resetToDefault = useCallback(() => {
    if (!isGuest) return;
    setGuestFarms(DEFAULT_FARMS);
    saveFarms(DEFAULT_FARMS);
  }, [isGuest]);

  return { farms, addFarm, removeFarm, resetToDefault, mounted: ready, loadError, retryLoad };
}

// ── Farmer Profile Store ──────────────────────────────────────────────────────

export type FarmerProfile = {
  name: string;
  phone: string;
  state: string;
  location: string;
  preferredLanguage: string;
};

const DEFAULT_PROFILE: FarmerProfile = {
  name: "Farmer",
  phone: "",
  state: "Maharashtra",
  location: "",
  preferredLanguage: "en",
};

export function getStoredProfile(): FarmerProfile {
  if (typeof window === "undefined") return DEFAULT_PROFILE;
  try {
    const raw = localStorage.getItem(scopedKey(USER_KEY_BASE));
    if (raw) return { ...DEFAULT_PROFILE, ...JSON.parse(raw) };
  } catch {
    // localStorage unavailable (private mode, quota) — fall back silently
  }
  return DEFAULT_PROFILE;
}

export function saveProfile(profile: FarmerProfile): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(scopedKey(USER_KEY_BASE), JSON.stringify(profile));
    window.dispatchEvent(new Event("fasalsetu_user_updated"));
  } catch {
    // localStorage unavailable (private mode, quota) — fall back silently
  }
}

export function useUserStore() {
  const [profile, setProfile] = useState<FarmerProfile>(DEFAULT_PROFILE);

  useEffect(() => {
    setProfile(getStoredProfile());
    const handleUpdate = () => setProfile(getStoredProfile());
    window.addEventListener("fasalsetu_user_updated", handleUpdate);
    return () => window.removeEventListener("fasalsetu_user_updated", handleUpdate);
  }, []);

  return { profile, saveProfile };
}

// ── Helper to generate dynamic weather for newly registered farms ─────────────
export function generateFarmWeather(farmName: string, address: string, crop: string): FarmDetailedWeather {
  return {
    currentTemp: 28,
    feelsLike: 30,
    condition: "Partly Cloudy",
    iconType: "cloud-sun",
    humidity: 66,
    windKmh: 15,
    windDir: "NW",
    rainExpected: "5mm in next 3 days",
    uvIndex: 6,
    pressureHpa: 1011,
    alerts: [],
    forecast10Days: [
      { day: "Today", date: "Sep 22", condition: "Partly Cloudy", iconType: "cloud-sun", hi: 30, lo: 21, rainChance: 15, rainfallMm: 0.5, windKmh: 14, humidity: 66, uvIndex: 6, farmingAdvisory: `Optimal day for foliar feed or scouting ${crop} for pests.` },
      { day: "Wed", date: "Sep 23", condition: "Sunny", iconType: "sun", hi: 31, lo: 22, rainChance: 10, rainfallMm: 0, windKmh: 12, humidity: 60, uvIndex: 7, farmingAdvisory: "Mild winds and warm sunshine. Good for tractor operations." },
      { day: "Thu", date: "Sep 24", condition: "Cloudy", iconType: "cloud", hi: 29, lo: 20, rainChance: 30, rainfallMm: 2.0, windKmh: 16, humidity: 72, uvIndex: 5, farmingAdvisory: "Cloud cover increasing. Monitor soil moisture levels." },
      { day: "Fri", date: "Sep 25", condition: "Light Rain", iconType: "rain", hi: 27, lo: 19, rainChance: 60, rainfallMm: 7.5, windKmh: 18, humidity: 82, uvIndex: 4, farmingAdvisory: "Postpone spray operations due to rain wash-off risk." },
      { day: "Sat", date: "Sep 26", condition: "Scattered Showers", iconType: "rain", hi: 26, lo: 19, rainChance: 50, rainfallMm: 5.0, windKmh: 15, humidity: 80, uvIndex: 4, farmingAdvisory: "Ensure open furrows allow excess water to drain freely." },
      { day: "Sun", date: "Sep 27", condition: "Partly Cloudy", iconType: "cloud-sun", hi: 28, lo: 19, rainChance: 20, rainfallMm: 0, windKmh: 11, humidity: 70, uvIndex: 6, farmingAdvisory: "Clearing weather. High soil moisture beneficial for root zones." },
      { day: "Mon", date: "Sep 28", condition: "Sunny", iconType: "sun", hi: 30, lo: 20, rainChance: 5, rainfallMm: 0, windKmh: 10, humidity: 62, uvIndex: 7, farmingAdvisory: "Sunny conditions return. Resume fertilization plan." },
      { day: "Tue", date: "Sep 29", condition: "Sunny", iconType: "sun", hi: 31, lo: 21, rainChance: 5, rainfallMm: 0, windKmh: 9, humidity: 58, uvIndex: 7, farmingAdvisory: "Normal irrigation schedule; monitor soil tensiometers." },
      { day: "Wed", date: "Sep 30", condition: "Clear Skies", iconType: "sun", hi: 32, lo: 21, rainChance: 0, rainfallMm: 0, windKmh: 11, humidity: 55, uvIndex: 8, farmingAdvisory: "Warm dry spell. Adequate hydration recommended." },
      { day: "Thu", date: "Oct 01", condition: "Sunny", iconType: "sun", hi: 31, lo: 20, rainChance: 10, rainfallMm: 0, windKmh: 12, humidity: 60, uvIndex: 7, farmingAdvisory: "Stable conditions across the farm." },
    ],
  };
}
