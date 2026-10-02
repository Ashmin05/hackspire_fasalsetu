/**
 * Auth client for the real FastAPI backend (backend/app/routers/auth.py).
 * Always calls the live backend — unlike src/lib/api, it is not gated by
 * NEXT_PUBLIC_USE_MOCKS, since auth has no mock counterpart.
 */

// The backend's auth routes live at the API root, not under /api/v1 like the
// (not-yet-implemented) data endpoints NEXT_PUBLIC_API_URL points at.
const API_ROOT = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(
  /\/api\/v1\/?$/,
  ""
);

const ACCESS_TOKEN_KEY = "fasalsetu_access_token";
const REFRESH_TOKEN_KEY = "fasalsetu_refresh_token";

export interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
  phone: string | null;
  state: string | null;
  location: string | null;
  is_active: boolean;
  created_at: string;
  profile_complete: boolean;
}

export interface ProfileUpdate {
  full_name?: string;
  phone?: string;
  state?: string;
  location?: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export class AuthError extends Error {}

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

async function authFetch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_ROOT}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new AuthError(extractErrorMessage(payload, res.status));
  }

  return res.json() as Promise<T>;
}

export function storeTokens(tokens: AuthTokens): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token);
  localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
}

export function clearTokens(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getAccessToken() !== null;
}

/**
 * Reads the "sub" claim (the user's id) out of the stored access token
 * without a network call. Used to namespace per-user local data (e.g.
 * farmStore) so different accounts on the same browser never see each
 * other's data. Returns null if signed out or the token is malformed.
 */
export function getUserId(): string | null {
  const token = getAccessToken();
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const claims = JSON.parse(json) as { sub?: string };
    return claims.sub ?? null;
  } catch {
    return null;
  }
}

export async function register(
  email: string,
  password: string,
  fullName?: string,
  profile?: { phone?: string; state?: string; location?: string }
): Promise<AuthUser> {
  return authFetch<AuthUser>("/auth/register", {
    email,
    password,
    full_name: fullName ?? null,
    phone: profile?.phone ?? null,
    state: profile?.state ?? null,
    location: profile?.location ?? null,
  });
}

export async function login(email: string, password: string): Promise<AuthTokens> {
  const tokens = await authFetch<AuthTokens>("/auth/login", { email, password });
  storeTokens(tokens);
  return tokens;
}

export async function loginWithGoogle(idToken: string): Promise<AuthTokens> {
  const tokens = await authFetch<AuthTokens>("/auth/google", { id_token: idToken });
  storeTokens(tokens);
  return tokens;
}

type RefreshOutcome = AuthTokens | "expired" | "unreachable";

// Only an actual rejection from /auth/refresh ends the session; a network
// failure (backend briefly down) must not sign the user out.
async function tryRefresh(): Promise<RefreshOutcome> {
  if (typeof window === "undefined") return "unreachable";
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refreshToken) return "expired";

  try {
    const tokens = await authFetch<AuthTokens>("/auth/refresh", {
      refresh_token: refreshToken,
    });
    storeTokens(tokens);
    return tokens;
  } catch (err) {
    if (err instanceof AuthError) {
      clearTokens();
      return "expired";
    }
    return "unreachable";
  }
}

// Several queries usually 401 at the same moment when the access token
// expires -- they all share one refresh call instead of racing each other.
let refreshInFlight: Promise<RefreshOutcome> | null = null;

function refreshOnce(): Promise<RefreshOutcome> {
  if (!refreshInFlight) {
    refreshInFlight = tryRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

export async function refreshAccessToken(): Promise<AuthTokens | null> {
  const outcome = await refreshOnce();
  return typeof outcome === "string" ? null : outcome;
}

export class SessionExpiredError extends Error {}

function endExpiredSession(): void {
  clearTokens();
  if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.assign("/login?expired=1");
  }
}

/**
 * `fetch` with the stored access token for every authenticated backend
 * call. Access tokens live 30 minutes: on a 401 this refreshes once via the
 * refresh token and retries. If the refresh token is rejected too, the
 * session is over -- tokens are cleared and the user is sent to
 * /login?expired=1 (a SessionExpiredError is thrown meanwhile).
 */
export async function authorizedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const send = async (token: string) => {
    try {
      return await fetch(url, {
        ...init,
        headers: { ...(init.headers as Record<string, string> | undefined), Authorization: `Bearer ${token}` },
      });
    } catch {
      // fetch only rejects when no response arrived at all; the browser's own
      // wording ("Failed to fetch") means nothing to a farmer.
      throw new Error("Can't reach the FasalSetu server. Check your connection and try again.");
    }
  };

  const accessToken = getAccessToken();
  if (!accessToken) throw new SessionExpiredError("Not signed in.");

  const res = await send(accessToken);
  if (res.status !== 401) return res;

  const outcome = await refreshOnce();
  if (outcome === "expired") {
    endExpiredSession();
    throw new SessionExpiredError("Your session has expired. Please sign in again.");
  }
  if (outcome === "unreachable") return res; // let the caller surface the original 401
  return send(outcome.access_token);
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  if (!getAccessToken()) return null;

  try {
    const res = await authorizedFetch(`${API_ROOT}/auth/me`);
    if (!res.ok) return null;
    return (await res.json()) as AuthUser;
  } catch {
    // Network error (backend unreachable, CORS, etc.) — treat as "couldn't
    // load", not "signed out", so callers don't get stuck forever.
    return null;
  }
}

export function logout(): void {
  clearTokens();
}

export async function updateProfile(update: ProfileUpdate): Promise<AuthUser> {
  if (!getAccessToken()) throw new AuthError("Not signed in.");

  const res = await authorizedFetch(`${API_ROOT}/auth/profile`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new AuthError(extractErrorMessage(payload, res.status));
  }
  return res.json() as Promise<AuthUser>;
}

