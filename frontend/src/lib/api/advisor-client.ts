
import { authorizedFetch, getAccessToken } from "@/lib/auth/auth-client";

const API_ROOT = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(
  /\/api\/v1\/?$/,
  ""
);

export class AdvisorApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export interface AdvisorSource {
  module: string;
  label: string;
  as_of: string | null; // ISO date
}

export interface AdvisorAskResponse {
  answer: string;
  action_points: string[];
  warnings: string[];
  sources_used: AdvisorSource[];
  language: string;
  is_scripted_fallback: boolean;
  generated_at: string; // ISO datetime
}

function extractErrorMessage(payload: unknown, status: number): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  return `Request failed (${status})`;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (!getAccessToken()) throw new AdvisorApiError("Not signed in.", 401);

  const res = await authorizedFetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers as Record<string, string> | undefined),
    },
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new AdvisorApiError(extractErrorMessage(payload, res.status), res.status);
  }
  return res.json() as Promise<T>;
}

/**
 * Asks KrishiBot a question about this farm. The backend answers only from
 * that farm's already-stored data (satellite, environment, weather,
 * irrigation, mandi price) -- see AdvisorService. Can 429 (rate limit) or
 * 503 (every configured Gemini key failed) -- see AdvisorApiError.status.
 */
export function askAdvisor(farmId: string, question: string, language: string): Promise<AdvisorAskResponse> {
  return apiFetch<AdvisorAskResponse>(`/farms/${farmId}/ask`, {
    method: "POST",
    body: JSON.stringify({ question, language }),
  });
}
