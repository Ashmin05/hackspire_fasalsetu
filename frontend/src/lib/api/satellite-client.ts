
import { authorizedFetch, getAccessToken } from "@/lib/auth/auth-client";

const API_ROOT = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(
  /\/api\/v1\/?$/,
  ""
);

export class SatelliteApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export interface IndexStats {
  mean: number;
  min: number;
  max: number;
}

export interface SatelliteProvenance {
  source: string;
  is_live: boolean;
  as_of: string; // ISO date
  cloud_pct: number;
}

export interface SatelliteObservation {
  id: string;
  farm_id: string;
  image_date: string; // ISO date
  satellite: string; // "S2A" / "S2B"
  cloud_pct: number;
  is_fallback: boolean;
  ndvi: IndexStats;
  ndwi: IndexStats;
  evi: IndexStats;
  ndmi: IndexStats;
  healthy_pct: number;
  moderate_pct: number;
  stressed_pct: number;
  health_score: number;
  provenance: SatelliteProvenance;
  created_at: string;
}

function extractErrorMessage(payload: unknown, status: number): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  return `Request failed (${status})`;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (!getAccessToken()) throw new SatelliteApiError("Not signed in.", 401);

  const res = await authorizedFetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers as Record<string, string> | undefined),
    },
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new SatelliteApiError(extractErrorMessage(payload, res.status), res.status);
  }
  return res.json() as Promise<T>;
}

function satelliteFetch<T>(farmId: string, path: string, init?: RequestInit): Promise<T> {
  return apiFetch<T>(`/farms/${farmId}/satellite${path}`, init);
}

/** The backend reports "no scene covers this field" as a 503 with this
 * message prefix (NoSentinelImageryAvailableError) -- an expected empty
 * state for a brand-new farm, not a failure worth a retry button. */
export function isNoImageryError(err: unknown): boolean {
  return err instanceof SatelliteApiError && err.message.startsWith("No Sentinel-2 imagery");
}

/**
 * Cache-only read — never triggers a live Earth Engine query. Returns `null`
 * (rather than throwing) when no analysis has run yet for this farm, since
 * that's an expected, common state for a brand-new farm.
 */
export async function getLatestSatelliteAnalysis(farmId: string): Promise<SatelliteObservation | null> {
  try {
    return await satelliteFetch<SatelliteObservation>(farmId, "/latest");
  } catch (err) {
    if (err instanceof SatelliteApiError && err.status === 404) return null;
    throw err;
  }
}

/** Runs a real, live Sentinel-2 query via Earth Engine — slower than the
 * cache read above, so only call this on an explicit user action. */
export async function refreshSatelliteAnalysis(farmId: string): Promise<SatelliteObservation> {
  return satelliteFetch<SatelliteObservation>(farmId, "/refresh", { method: "POST" });
}

export interface TileLayerUrls {
  true_color: string;
  ndvi: string;
  ndwi: string;
  evi: string;
  stress: string;
}

export interface StressZone {
  id: string;
  zone_type: "water_stress" | "nutrient_pest_suspected";
  area_ha: number;
  geometry_geojson: GeoJSON.Geometry;
  suggested_action: string;
}

export interface SatelliteLayers {
  farm_id: string;
  image_date: string; // ISO date
  layers: TileLayerUrls;
  generated_at: string;
  expires_at: string;
  stress_zones: StressZone[];
}

/**
 * Visualised, farm-polygon-clipped Sentinel-2 tile URLs (true color, NDVI,
 * NDWI, EVI, stress classification) plus vectorized stress zones for one
 * scene. Backend-cached for ~12h; can be a real Earth Engine round trip
 * (several seconds), not just a cache read, so callers should show a
 * loading state. Throws on any failure (including 503) -- callers only ask
 * for a known pass date, so a failure is a real error to show, never an
 * "empty" result that would read as "no stress zones on this field".
 */
export function getSatelliteLayers(farmId: string, date?: string): Promise<SatelliteLayers> {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return satelliteFetch<SatelliteLayers>(farmId, `/layers${query}`);
}

export interface TimeseriesPoint {
  id: string;
  farm_id: string;
  image_date: string; // ISO date -- one clear Sentinel-2 pass
  satellite: string;
  cloud_pct: number;
  ndvi_mean: number;
  ndwi_mean: number;
  evi_mean: number;
  benchmark_ndvi: number;
  created_at: string;
}

/** Cache-only read of every accumulated clear pass, oldest first. Populated
 * by the backend's nightly job -- an empty list is a normal state. */
export function getSatelliteTimeseries(farmId: string): Promise<TimeseriesPoint[]> {
  return satelliteFetch<TimeseriesPoint[]>(farmId, "/timeseries");
}

export interface EnvironmentProvenance {
  source: string;
  resolution: string; // e.g. "~9-11 km regional (SMAP L4)"
  as_of: string | null;
}

export interface EnvironmentReport {
  farm_id: string;
  rainfall: {
    mm_7d: number;
    mm_30d: number;
    mm_90d: number;
    mm_since_sowing: number | null;
    provenance: EnvironmentProvenance;
  };
  temperature: {
    mean_lst_c: number | null;
    hot_periods_60d: number;
    provenance: EnvironmentProvenance;
  };
  soil_moisture: {
    surface_moisture: number | null; // m³/m³
    provenance: EnvironmentProvenance;
  };
  soil: {
    ph: number | null;
    organic_carbon_g_per_kg: number | null;
    texture_class: string | null;
    // Only set when is_lab_report is true -- OpenLandMap has no NPK or
    // organic-matter-% readings, only a farmer's lab report does.
    nitrogen: "Low" | "Medium" | "High" | null;
    phosphorus: "Low" | "Medium" | "High" | null;
    potassium: "Low" | "Medium" | "High" | null;
    organic_matter_pct: number | null;
    is_lab_report: boolean;
    provenance: EnvironmentProvenance;
  };
  generated_at: string;
}

/** Cache-only read; `null` until the nightly job (or refreshEnvironmentReport)
 * has produced a report. */
export async function getEnvironmentReport(farmId: string): Promise<EnvironmentReport | null> {
  try {
    return await apiFetch<EnvironmentReport>(`/farms/${farmId}/environment`);
  } catch (err) {
    if (err instanceof SatelliteApiError && err.status === 404) return null;
    throw err;
  }
}

/** Runs a live rainfall/temperature/soil-moisture refresh right now instead
 * of waiting for the nightly job -- see getLatestSatelliteAnalysis's
 * refreshSatelliteAnalysis for the same pattern. */
export function refreshEnvironmentReport(farmId: string): Promise<EnvironmentReport> {
  return apiFetch<EnvironmentReport>(`/farms/${farmId}/environment/refresh`, { method: "POST" });
}

export interface FarmAlert {
  id: string;
  farm_id: string;
  alert_type: "ndvi_drop" | "below_benchmark" | "water_stress" | string;
  severity: "warning" | "critical" | string;
  message: string;
  detected_at: string; // ISO date
  is_read: boolean;
  created_at: string;
}

export function getFarmAlerts(farmId: string): Promise<FarmAlert[]> {
  return apiFetch<FarmAlert[]>(`/farms/${farmId}/alerts`);
}

export function markAlertRead(alertId: string): Promise<FarmAlert> {
  return apiFetch<FarmAlert>(`/alerts/${alertId}/read`, { method: "PATCH" });
}
