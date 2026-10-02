
import { authorizedFetch, getAccessToken } from "@/lib/auth/auth-client";

const API_ROOT = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(
  /\/api\/v1\/?$/,
  ""
);

export class WeatherApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export interface WeatherFlags {
  heavy_rain: boolean;
  heat_stress: boolean;
  good_spray_window: boolean;
}

export interface DailyWeather {
  date: string; // ISO date
  temp_max_c: number;
  temp_min_c: number;
  precipitation_sum_mm: number;
  precipitation_probability_pct: number | null;
  wind_speed_max_kmh: number;
  relative_humidity_pct: number | null;
  uv_index_max: number | null;
  et0_fao_evapotranspiration_mm: number | null;
  flags: WeatherFlags;
}

export interface WeatherProvenance {
  source: string; // "Open-Meteo"
  is_live: boolean;
  fetched_at: string; // ISO datetime -- when this forecast was actually fetched (cached up to 3h)
}

export interface FarmWeather {
  farm_id: string;
  daily: DailyWeather[];
  provenance: WeatherProvenance;
}

function extractErrorMessage(payload: unknown, status: number): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  return `Request failed (${status})`;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (!getAccessToken()) throw new WeatherApiError("Not signed in.", 401);

  const res = await authorizedFetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers as Record<string, string> | undefined),
    },
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new WeatherApiError(extractErrorMessage(payload, res.status), res.status);
  }
  return res.json() as Promise<T>;
}

/**
 * 10-day Open-Meteo forecast for this farm's centroid, cached backend-side
 * for up to 3h (see WEATHER_CACHE_HOURS). Never 404s for a real farm --
 * Open-Meteo needs no prior refresh step, unlike satellite analysis.
 */
export function getFarmWeather(farmId: string): Promise<FarmWeather> {
  return apiFetch<FarmWeather>(`/farms/${farmId}/weather`);
}
