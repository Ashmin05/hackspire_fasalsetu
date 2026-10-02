
import { authorizedFetch, getAccessToken } from "@/lib/auth/auth-client";

const API_ROOT = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(
  /\/api\/v1\/?$/,
  ""
);

export class MarketApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export interface MarketProvenance {
  sources: string[];
  as_of: string | null;
  is_stale: boolean;
  last_ingested_at: string | null;
  last_ingestion_status: string | null;
}

export interface CommodityRef {
  id: number;
  name: string;
}

export interface MarketCommodity extends CommodityRef {
  commodity_group: string | null;
  markets: number;
  latest_date: string | null;
}

export interface MarketLocationState {
  id: number;
  name: string;
  districts: { id: number; name: string; markets: number }[];
}

export interface MarketInfo {
  id: number;
  name: string;
  district: string | null;
  state: string | null;
  latitude: number | null;
  longitude: number | null;
  coordinate_source: string | null;
  coordinate_precision: "place" | "district" | null;
  latest_date: string | null;
}

export type Trend = "increasing" | "stable" | "decreasing" | "insufficient_data";

export interface MarketStats {
  market_id: number;
  market: string;
  district: string | null;
  state: string | null;
  as_of: string;
  modal_price: number;
  min_price: number | null;
  max_price: number | null;
  arrival_quantity: number | null;
  avg_7d: number | null;
  avg_14d: number | null;
  avg_30d: number | null;
  change_7d_pct: number | null;
  change_30d_pct: number | null;
  min_7d: number | null;
  max_7d: number | null;
  min_30d: number | null;
  max_30d: number | null;
  volatility_30d_pct: number | null;
  trading_days_30d: number;
  trend: Trend;
  trend_change_pct: number | null;
}

export interface LatestPrices {
  commodity: CommodityRef;
  state: string | null;
  district: string | null;
  unit: string;
  prices: MarketStats[];
  provenance: MarketProvenance;
}

export interface HistoryPoint {
  date: string;
  modal_price: number;
  min_price: number | null;
  max_price: number | null;
  arrival_quantity: number | null;
  report_count: number;
  source: string;
}

export interface PriceHistory {
  market: MarketInfo;
  commodity: CommodityRef;
  from_date: string;
  to_date: string;
  unit: string;
  series: HistoryPoint[];
  provenance: MarketProvenance;
}

export interface NearbyMarket extends MarketStats {
  distance_km: number | null;
  scope: "radius" | "district" | "state";
  coordinate_precision: "place" | "district" | null;
  /** Only on /farms/{id}/market/forecast: a stored estimate exists for this mandi. */
  model_ready?: boolean;
}

export interface NearbyMarkets {
  commodity: CommodityRef;
  radius_km: number;
  markets: NearbyMarket[];
  note: string;
  attribution: string | null;
  provenance: MarketProvenance;
}

export interface ForecastPoint {
  horizon_days: number;
  base_date: string;
  base_price: number;
  forecast_date: string;
  predicted_price: number;
  lower_bound: number | null;
  upper_bound: number | null;
  change_pct: number | null;
  model_name: string;
  model_version: string;
}

export interface ForecastModelInfo {
  horizon_days: number;
  model_name: string;
  model_version: string;
  trained_at: string;
  training_period: { from: string; to: string };
  training_samples: number;
  markets: number;
  validation: { mae: number | null; rmse: number | null; mape: number | null; naive_mae: number | null; scheme: string | null };
  selection_note: string | null;
  interval: { level: number; holdout_coverage: number | null };
}

export interface PriceForecast {
  market: MarketInfo;
  commodity: CommodityRef;
  available: boolean;
  reason: string | null;
  generated_at: string | null;
  forecasts: ForecastPoint[];
  models: ForecastModelInfo[];
  disclaimer: string;
}

export interface MarketAnalytics {
  market: MarketInfo;
  commodity: CommodityRef;
  stats: MarketStats | null;
  outlook: { label: "positive" | "negative" | "stable" | "unclear" | "unavailable"; statements: string[]; basis?: Record<string, unknown> | null };
  provenance: MarketProvenance;
}

export interface FarmMarketPrices {
  farm_id: string;
  crop: string;
  commodities: CommodityRef[];
  state: string | null;
  district: string | null;
  selected_commodity: CommodityRef | null;
  nearby: NearbyMarket[];
  attribution: string | null;
  message: string | null;
}

export interface HorizonOption {
  horizon_days: number;
  forecast_date: string;
  predicted_price: number;
  expected_gain: number;
  expected_gain_pct: number;
  holding_cost: number;
  net_gain: number;
  typical_error: number | null;
  typical_error_basis: "mape" | "mae" | null;
  gain_range: [number, number] | null;
  worth_holding: boolean;
  model_name: string;
}

export interface PriceRecommendation {
  action: "hold" | "sell_now" | "unavailable";
  headline: string;
  hold_days: number | null;
  reason: string;
  commodity: string | null;
  market: string | null;
  base_price: number | null;
  base_date: string | null;
  expected_gain: { per_quintal: number; pct: number; horizon_days: number; by_date: string; predicted_price: number } | null;
  error_range: { typical_error: number | null; basis: string | null; low: number | null; high: number | null; level: number } | null;
  holding_cost: { pct_per_30_days: number; assumed: boolean; configured: boolean; per_quintal: number | null; horizon_days: number | null } | null;
  horizons: HorizonOption[];
  perishable: boolean;
  warning: string | null;
  best_nearby: {
    market_id: number;
    market: string;
    district: string | null;
    distance_km: number | null;
    coordinate_precision: "place" | "district" | null;
    modal_price: number;
    as_of: string;
    is_selected: boolean;
    difference_vs_selected: number | null;
    note: string;
  } | null;
  disclaimer: string;
}

export interface FarmMarketForecast {
  farm_id: string;
  crop: string;
  commodities: CommodityRef[];
  selected_commodity: CommodityRef | null;
  state: string | null;
  district: string | null;
  market: (MarketInfo & { distance_km: number | null; model_ready: boolean }) | null;
  today: MarketStats | null;
  unit: string;
  history: HistoryPoint[];
  forecast: Omit<PriceForecast, "market" | "commodity">;
  recommendation: PriceRecommendation;
  nearby: NearbyMarket[];
  attribution: string | null;
  message: string | null;
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    const detail = (payload as { detail?: unknown } | null)?.detail;
    throw new MarketApiError(typeof detail === "string" ? detail : `Request failed (${res.status})`, res.status);
  }
  return res.json() as Promise<T>;
}

async function publicGet<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_ROOT}${path}`);
  } catch {
    throw new MarketApiError("The FasalSetu server can't be reached right now.", 0);
  }
  return parse<T>(res);
}

export const marketApi = {
  commodities: (state?: string, include?: string) =>
    publicGet<MarketCommodity[]>(`/market-prices/commodities${query({ state, include })}`),
  locations: (commodityId?: number) =>
    publicGet<MarketLocationState[]>(`/market-prices/locations${query({ commodity_id: commodityId })}`),
  markets: (p: { commodityId: number; state?: string; district?: string }) =>
    publicGet<MarketInfo[]>(
      `/market-prices/markets${query({ commodity_id: p.commodityId, state: p.state, district: p.district })}`
    ),
  latest: (p: { commodityId: number; state?: string; district?: string }) =>
    publicGet<LatestPrices>(
      `/market-prices/latest${query({ commodity_id: p.commodityId, state: p.state, district: p.district })}`
    ),
  history: (p: { marketId: number; commodityId: number; from?: string; to?: string }) =>
    publicGet<PriceHistory>(
      `/market-prices/history${query({ market_id: p.marketId, commodity_id: p.commodityId, from: p.from, to: p.to })}`
    ),
  nearby: (p: { commodityId: number; lat?: number | null; lon?: number | null; state?: string; district?: string; radiusKm?: number }) =>
    publicGet<NearbyMarkets>(
      `/market-prices/nearby${query({
        commodity_id: p.commodityId,
        lat: p.lat,
        lon: p.lon,
        state: p.state,
        district: p.district,
        radius_km: p.radiusKm,
      })}`
    ),
  analytics: (p: { marketId: number; commodityId: number }) =>
    publicGet<MarketAnalytics>(`/market-prices/analytics${query({ market_id: p.marketId, commodity_id: p.commodityId })}`),
  forecast: (p: { marketId: number; commodityId: number }) =>
    publicGet<PriceForecast>(`/market-prices/forecast${query({ market_id: p.marketId, commodity_id: p.commodityId })}`),
  async farm(farmId: string, commodityId?: number): Promise<FarmMarketPrices> {
    if (!getAccessToken()) throw new MarketApiError("Not signed in.", 401);
    const res = await authorizedFetch(`${API_ROOT}/farms/${farmId}/market-prices${query({ commodity_id: commodityId })}`);
    return parse<FarmMarketPrices>(res);
  },
  /** Live price, 90-day history, estimates and the sell/hold suggestion for a farm. */
  async farmForecast(farmId: string, p: { commodityId?: number; marketId?: number } = {}): Promise<FarmMarketForecast> {
    if (!getAccessToken()) throw new MarketApiError("Not signed in.", 401);
    const res = await authorizedFetch(
      `${API_ROOT}/farms/${farmId}/market/forecast${query({ commodity_id: p.commodityId, market_id: p.marketId })}`
    );
    return parse<FarmMarketForecast>(res);
  },
};
