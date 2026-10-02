
import { authorizedFetch, getAccessToken } from "@/lib/auth/auth-client";

const API_ROOT = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(
  /\/api\/v1\/?$/,
  ""
);

export class IrrigationApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export interface IrrigationPlan {
  farm_id: string;
  crop: string;
  days_since_sowing: number;

  kc: number;
  kc_basis: "ndvi" | "crop_stage";
  root_depth_m: number;

  soil_texture_class: string;
  soil_texture_is_default: boolean;

  taw_mm: number;
  raw_mm: number;
  depletion_fraction: number;
  depletion_mm: number;
  is_deficit: boolean;

  computed_through: string; // ISO date
  next_irrigation_date: string | null; // ISO date
  next_irrigation_depth_mm: number | null;

  basis: "Modelled";
  generated_at: string; // ISO datetime
}

function extractErrorMessage(payload: unknown, status: number): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  return `Request failed (${status})`;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (!getAccessToken()) throw new IrrigationApiError("Not signed in.", 401);

  const res = await authorizedFetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers as Record<string, string> | undefined),
    },
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new IrrigationApiError(extractErrorMessage(payload, res.status), res.status);
  }
  return res.json() as Promise<T>;
}

/**
 * FAO-56 root-zone water balance for this farm's latest sowing/crop -- see
 * IrrigationPlanResponse. Never 404s for a real farm -- the first call
 * computes a plan from scratch, same as getFarmWeather.
 */
export function getFarmIrrigation(farmId: string): Promise<IrrigationPlan> {
  return apiFetch<IrrigationPlan>(`/farms/${farmId}/irrigation`);
}
