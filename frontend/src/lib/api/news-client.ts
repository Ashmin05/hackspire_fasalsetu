
import { authorizedFetch, getAccessToken } from "@/lib/auth/auth-client";

const API_ROOT = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(
  /\/api\/v1\/?$/,
  ""
);

export class NewsApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export interface NewsArticle {
  title: string;
  description: string | null;
  url: string;
  source: string;
  image_url: string | null;
  published_at: string; // ISO datetime
}

export interface FarmNews {
  farm_id: string;
  location: string;
  articles: NewsArticle[];
  is_configured: boolean;
}

function extractErrorMessage(payload: unknown, status: number): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  return `Request failed (${status})`;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (!getAccessToken()) throw new NewsApiError("Not signed in.", 401);

  const res = await authorizedFetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers as Record<string, string> | undefined),
    },
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new NewsApiError(extractErrorMessage(payload, res.status), res.status);
  }
  return res.json() as Promise<T>;
}

/**
 * Recent farming/agriculture news for this farm's district/state, cached
 * backend-side for up to NEWS_CACHE_MINUTES. is_configured is false (empty
 * articles, not an error) when the backend has no NEWS_API_KEY set.
 */
export function getFarmNews(farmId: string): Promise<FarmNews> {
  return apiFetch<FarmNews>(`/farms/${farmId}/news`);
}
