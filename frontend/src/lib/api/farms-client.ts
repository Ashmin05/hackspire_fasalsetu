
import { authorizedFetch, getAccessToken } from "@/lib/auth/auth-client";

const API_ROOT = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(
  /\/api\/v1\/?$/,
  ""
);

export class FarmApiError extends Error {}

export type SoilLevel = "Low" | "Medium" | "High";

// A farmer-submitted Soil Health Card / Lab Test Report. When present on a
// farm, this is the authoritative soil reading -- it takes priority over the
// backend's OpenLandMap satellite estimate rather than being blended with it
// (see backend/app/routers/satellite.py's _soil_response).
export interface SoilReport {
  ph: number | null;
  nitrogen: SoilLevel | null;
  phosphorus: SoilLevel | null;
  potassium: SoilLevel | null;
  organic_matter_pct: number | null;
  recorded_at: string | null;
}

export interface SoilReportInput {
  ph?: number | null;
  nitrogen?: SoilLevel | null;
  phosphorus?: SoilLevel | null;
  potassium?: SoilLevel | null;
  organic_matter_pct?: number | null;
}

export interface BackendFarm {
  id: string;
  name: string;
  crop: string;
  variety: string | null;
  sowing_date: string;
  irrigation_method: string | null;
  polygon_geojson: GeoJSON.Polygon;
  area_ha: number;
  centroid_lat: number;
  centroid_lng: number;
  state: string | null;
  district: string | null;
  address: string | null;
  has_soil_report: boolean;
  soil_report: SoilReport | null;
  created_at: string;
  updated_at: string;
}

export interface FarmCreatePayload {
  name: string;
  crop: string;
  variety?: string | null;
  sowing_date: string;
  irrigation_method?: string | null;
  polygon_geojson: GeoJSON.Polygon;
  state?: string | null;
  district?: string | null;
  address?: string | null;
  // Set only when the farmer ticked "I have a Soil Health Card / Lab Test
  // Report" and entered values.
  soil_report?: SoilReportInput | null;
}

// FastAPI returns `detail` as a plain string for our own HTTPExceptions, but
// as an array of {msg, loc, ...} objects for pydantic validation errors (422).
function extractErrorMessage(payload: unknown, status: number): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
      .join(" ");
  }
  return `Request failed (${status})`;
}

async function farmsFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (!getAccessToken()) throw new FarmApiError("Not signed in.");

  const res = await authorizedFetch(`${API_ROOT}/farms${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers as Record<string, string> | undefined),
    },
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new FarmApiError(extractErrorMessage(payload, res.status));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function listFarms(): Promise<BackendFarm[]> {
  return farmsFetch<BackendFarm[]>("");
}

export async function createFarm(payload: FarmCreatePayload): Promise<BackendFarm> {
  return farmsFetch<BackendFarm>("", { method: "POST", body: JSON.stringify(payload) });
}

export async function deleteFarm(farmId: string): Promise<void> {
  await farmsFetch<void>(`/${farmId}`, { method: "DELETE" });
}
