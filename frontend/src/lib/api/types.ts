// ─── Provenance ────────────────────────────────────────────────────────────
export type DataSource =
  | "satellite"
  | "weather_api"
  | "soil_sensor"
  | "model"
  | "manual"
  | "market_feed";

export interface Provenance {
  source: DataSource;
  is_live: boolean;
  fetched_at: string; // ISO-8601
  provider?: string;  // e.g. "Sentinel-2", "IMD", "AGMARK"
  confidence?: number; // 0–1
}

// ─── Auth ──────────────────────────────────────────────────────────────────
export interface User {
  id: string;
  name: string;
  phone: string;
  email?: string;
  language: string; // 'hi' | 'en' | 'ta' | etc.
  state: string;
  avatar_initials: string;
}

// ─── Farm ──────────────────────────────────────────────────────────────────
export interface Farm {
  id: string;
  name: string;
  location: { district: string; state: string; lat: number; lng: number };
  total_acres: number;
  active_fields: number;
  primary_crop: string;
  season: "Kharif" | "Rabi" | "Zaid";
  health_score: number; // 0–100
  provenance: Provenance;
}

// ─── Field ─────────────────────────────────────────────────────────────────
export interface Field {
  id: string;
  farm_id: string;
  name: string;
  area_acres: number;
  crop: string;
  variety: string;
  sowing_date: string;
  expected_harvest: string;
  growth_stage: string;
  health_score: number;
  coordinates: Array<{ lat: number; lng: number }>;
  provenance: Provenance;
}

// ─── Satellite ─────────────────────────────────────────────────────────────
export interface NdviPoint {
  date: string;
  ndvi: number;
  cloud_cover: number;
}

export interface HealthZone {
  label: "Excellent" | "Good" | "Moderate" | "Poor" | "Very Poor";
  color: string;
  percentage: number;
}

export interface StressAlert {
  id: string;
  date: string;
  type: "Water Stress" | "Pest Activity" | "Nutrient Deficiency" | "Recovery" | "Disease Risk";
  severity: "low" | "medium" | "critical";
  field_id: string;
  message: string;
  recommended_action: string;
}

export interface SatelliteData {
  field_id: string;
  latest_ndvi: number;
  ndvi_change_30d: number;
  scan_date: string;
  health_zones: HealthZone[];
  ndvi_history: NdviPoint[];
  stress_alerts: StressAlert[];
  provenance: Provenance;
}

// ─── Weather ───────────────────────────────────────────────────────────────
export interface DayForecast {
  date: string;
  day_label: string;
  condition: string;
  icon: "sun" | "cloud" | "rain" | "storm" | "fog";
  temp_hi: number;
  temp_lo: number;
  rain_chance: number;
  rain_mm: number;
  wind_kmh: number;
  humidity: number;
}

export interface WeatherAlert {
  id: string;
  type: string;
  severity: "advisory" | "watch" | "warning";
  valid_from: string;
  valid_to: string;
  message: string;
  crop_impact: string;
}

export interface WeatherData {
  field_id: string;
  current: {
    temp: number;
    condition: string;
    humidity: number;
    wind_kmh: number;
    feels_like: number;
  };
  forecast: DayForecast[];
  alerts: WeatherAlert[];
  irrigation_advice: string;
  provenance: Provenance;
}

// ─── Irrigation / Soil ─────────────────────────────────────────────────────
export interface SoilInfo {
  type: string;
  ph: number;
  nitrogen: "low" | "medium" | "high";
  phosphorus: "low" | "medium" | "high";
  potassium: "low" | "medium" | "high";
  organic_carbon: number; // %
  water_retention: "poor" | "moderate" | "good";
}

export interface IrrigationSchedule {
  next_irrigation: string;
  duration_hours: number;
  method: string;
  water_liters_per_acre: number;
  skip_reason?: string;
}

export interface IrrigationData {
  field_id: string;
  soil_moisture_pct: number;
  moisture_status: "dry" | "optimal" | "wet" | "waterlogged";
  soil_info: SoilInfo;
  schedule: IrrigationSchedule;
  water_saved_pct: number;
  fertiliser_recommendation: string;
  provenance: Provenance;
}

// ─── Yield & Price ─────────────────────────────────────────────────────────
export interface PricePoint {
  date: string;
  price_per_quintal: number;
  mandi: string;
}

export interface MandiPrice {
  mandi: string;
  district: string;
  price_per_quintal: number;
  change_pct: number;
}

export interface YieldData {
  field_id: string;
  estimated_yield_quintal_per_acre: number;
  confidence: number; // 0–1
  yield_range: { low: number; high: number };
  harvest_date: string;
  input_cost_per_acre: number;
  expected_revenue_per_acre: number;
  profit_per_acre: number;
  price_trend_30d: PricePoint[];
  top_mandis: MandiPrice[];
  best_sell_window: string;
  provenance: Provenance;
}

// ─── AI Assistant ──────────────────────────────────────────────────────────
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  language?: string;
}

export interface ChatContext {
  farm_id?: string;
  field_id?: string;
  crop?: string;
}

// ─── API Response wrapper ──────────────────────────────────────────────────
export interface ApiResponse<T> {
  data: T;
  ok: boolean;
  error?: string;
}
