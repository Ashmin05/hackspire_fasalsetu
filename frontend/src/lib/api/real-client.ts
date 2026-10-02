
import type {
  ApiResponse,
  Farm,
  Field,
  SatelliteData,
  WeatherData,
  IrrigationData,
  YieldData,
  ChatMessage,
  ChatContext,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<ApiResponse<T>> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      const err = await res.text();
      return { ok: false, data: null as unknown as T, error: err };
    }
    const data: T = await res.json();
    return { ok: true, data };
  } catch (e) {
    return { ok: false, data: null as unknown as T, error: String(e) };
  }
}

export const realClient = {
  listFarms: () => apiFetch<Farm[]>("/farms"),
  getFarm: (id: string) => apiFetch<Farm>(`/farms/${id}`),
  listFields: (farmId: string) => apiFetch<Field[]>(`/farms/${farmId}/fields`),
  getField: (farmId: string, fieldId: string) =>
    apiFetch<Field>(`/farms/${farmId}/fields/${fieldId}`),
  getSatelliteData: (fieldId: string) =>
    apiFetch<SatelliteData>(`/fields/${fieldId}/satellite`),
  getWeatherData: (fieldId: string) =>
    apiFetch<WeatherData>(`/fields/${fieldId}/weather`),
  getIrrigationData: (fieldId: string) =>
    apiFetch<IrrigationData>(`/fields/${fieldId}/irrigation`),
  getYieldData: (fieldId: string) =>
    apiFetch<YieldData>(`/fields/${fieldId}/yield`),
  getMarketPrice: (fieldId: string) =>
    apiFetch<{ provenance: { source: string; is_live: boolean; fetched_at: string }; crop: string; state_avg: number }>(
      `/fields/${fieldId}/market`
    ),
  sendChatMessage: (message: string, history: ChatMessage[], context?: ChatContext) =>
    apiFetch<ChatMessage>("/assistant/chat", {
      method: "POST",
      body: JSON.stringify({ message, history, context }),
    }),
};

export type RealClient = typeof realClient;
