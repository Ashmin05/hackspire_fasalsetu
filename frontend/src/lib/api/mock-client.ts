

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
  Provenance,
  StressAlert,
  NdviPoint,
} from "./types";

// ─── Helpers ───────────────────────────────────────────────────────────────
const delay = (ms = 400) => new Promise((r) => setTimeout(r, ms));

const now = () => new Date().toISOString();

const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().split("T")[0];
};

const daysFromNow = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().split("T")[0];
};

const ok = <T>(data: T): ApiResponse<T> => ({ ok: true, data });

// ─── Provenance presets ────────────────────────────────────────────────────
const LIVE_SAT: Provenance = {
  source: "satellite",
  is_live: true,
  fetched_at: now(),
  provider: "Sentinel-2",
  confidence: 0.94,
};
const MODELLED_SAT: Provenance = {
  source: "satellite",
  is_live: false,
  fetched_at: daysAgo(5) + "T00:00:00.000Z",
  provider: "Sentinel-2",
  confidence: 0.87,
};
const LIVE_WEATHER: Provenance = {
  source: "weather_api",
  is_live: true,
  fetched_at: now(),
  provider: "IMD",
  confidence: 0.91,
};
const MODEL_YIELD: Provenance = {
  source: "model",
  is_live: false,
  fetched_at: now(),
  provider: "FasalSetu ML v2.1",
  confidence: 0.78,
};
const LIVE_MARKET: Provenance = {
  source: "market_feed",
  is_live: true,
  fetched_at: now(),
  provider: "AGMARK",
  confidence: 1.0,
};
const SOIL_SENSOR: Provenance = {
  source: "soil_sensor",
  is_live: false,
  fetched_at: daysAgo(2) + "T06:00:00.000Z",
  provider: "IoT Sensor Grid",
  confidence: 0.82,
};
const MANUAL: Provenance = {
  source: "manual",
  is_live: false,
  fetched_at: now(),
  confidence: 1.0,
};

// ─── Static mock data ──────────────────────────────────────────────────────
const FARMS: Farm[] = [
  {
    id: "farm-1",
    name: "Ramesh Patil's Farm",
    location: { district: "Nashik", state: "Maharashtra", lat: 20.0, lng: 73.79 },
    total_acres: 12.5,
    active_fields: 3,
    primary_crop: "Wheat",
    season: "Rabi",
    health_score: 78,
    provenance: MANUAL,
  },
  {
    id: "farm-2",
    name: "Sunita Devi's Farm",
    location: { district: "Ludhiana", state: "Punjab", lat: 30.9, lng: 75.85 },
    total_acres: 8.0,
    active_fields: 2,
    primary_crop: "Rice",
    season: "Kharif",
    health_score: 91,
    provenance: MANUAL,
  },
  {
    id: "farm-3",
    name: "Krishnamurthy's Farm",
    location: { district: "Karimnagar", state: "Telangana", lat: 18.43, lng: 79.12 },
    total_acres: 15.0,
    active_fields: 4,
    primary_crop: "Sugarcane",
    season: "Kharif",
    health_score: 65,
    provenance: MANUAL,
  },
];

const FIELDS: Record<string, Field[]> = {
  "farm-1": [
    {
      id: "field-1a",
      farm_id: "farm-1",
      name: "North Field A",
      area_acres: 4.5,
      crop: "Wheat",
      variety: "HD-2967",
      sowing_date: daysAgo(62),
      expected_harvest: daysFromNow(38),
      growth_stage: "Grain filling",
      health_score: 82,
      coordinates: [
        { lat: 20.005, lng: 73.79 },
        { lat: 20.01, lng: 73.795 },
        { lat: 20.01, lng: 73.8 },
        { lat: 20.005, lng: 73.795 },
      ],
      provenance: MANUAL,
    },
    {
      id: "field-1b",
      farm_id: "farm-1",
      name: "South Field B",
      area_acres: 5.0,
      crop: "Wheat",
      variety: "GW-322",
      sowing_date: daysAgo(55),
      expected_harvest: daysFromNow(45),
      growth_stage: "Heading",
      health_score: 74,
      coordinates: [
        { lat: 19.995, lng: 73.79 },
        { lat: 20.0, lng: 73.795 },
        { lat: 20.0, lng: 73.8 },
        { lat: 19.995, lng: 73.795 },
      ],
      provenance: MANUAL,
    },
    {
      id: "field-1c",
      farm_id: "farm-1",
      name: "East Plot C",
      area_acres: 3.0,
      crop: "Onion",
      variety: "Agrifound Dark Red",
      sowing_date: daysAgo(40),
      expected_harvest: daysFromNow(80),
      growth_stage: "Bulb formation",
      health_score: 88,
      coordinates: [],
      provenance: MANUAL,
    },
  ],
  "farm-2": [
    {
      id: "field-2a",
      farm_id: "farm-2",
      name: "Paddy Plot 1",
      area_acres: 4.0,
      crop: "Rice",
      variety: "Pusa-44",
      sowing_date: daysAgo(90),
      expected_harvest: daysFromNow(20),
      growth_stage: "Ripening",
      health_score: 93,
      coordinates: [],
      provenance: MANUAL,
    },
    {
      id: "field-2b",
      farm_id: "farm-2",
      name: "Paddy Plot 2",
      area_acres: 4.0,
      crop: "Rice",
      variety: "Basmati-370",
      sowing_date: daysAgo(85),
      expected_harvest: daysFromNow(25),
      growth_stage: "Dough stage",
      health_score: 89,
      coordinates: [],
      provenance: MANUAL,
    },
  ],
  "farm-3": [
    {
      id: "field-3a",
      farm_id: "farm-3",
      name: "Sugarcane Block 1",
      area_acres: 5.0,
      crop: "Sugarcane",
      variety: "Co-0238",
      sowing_date: daysAgo(100),
      expected_harvest: daysFromNow(60),
      growth_stage: "Grand growth",
      health_score: 61,
      coordinates: [],
      provenance: MANUAL,
    },
    {
      id: "field-3b",
      farm_id: "farm-3",
      name: "Sugarcane Block 2",
      area_acres: 4.5,
      crop: "Sugarcane",
      variety: "Co-86032",
      sowing_date: daysAgo(98),
      expected_harvest: daysFromNow(62),
      growth_stage: "Tillering",
      health_score: 70,
      coordinates: [],
      provenance: MANUAL,
    },
    {
      id: "field-3c",
      farm_id: "farm-3",
      name: "Tomato Plot",
      area_acres: 3.0,
      crop: "Tomato",
      variety: "Pusa Ruby",
      sowing_date: daysAgo(70),
      expected_harvest: daysFromNow(30),
      growth_stage: "Fruit development",
      health_score: 76,
      coordinates: [],
      provenance: MANUAL,
    },
    {
      id: "field-3d",
      farm_id: "farm-3",
      name: "Rice Nursery",
      area_acres: 2.5,
      crop: "Rice",
      variety: "Swarna",
      sowing_date: daysAgo(50),
      expected_harvest: daysFromNow(70),
      growth_stage: "Vegetative",
      health_score: 84,
      coordinates: [],
      provenance: MANUAL,
    },
  ],
};

function buildNdviHistory(): NdviPoint[] {
  const base = [0.28, 0.34, 0.45, 0.58, 0.72, 0.83, 0.87, 0.81, 0.74, 0.63, 0.49, 0.36];
  return base.map((v, i) => ({
    date: daysAgo(330 - i * 28),
    ndvi: +(v + (Math.random() * 0.06 - 0.03)).toFixed(3),
    cloud_cover: Math.round(Math.random() * 25),
  }));
}

function buildStressAlerts(fieldId: string): StressAlert[] {
  return [
    {
      id: `alert-${fieldId}-1`,
      date: daysAgo(4),
      type: "Water Stress",
      severity: "medium",
      field_id: fieldId,
      message: "NDVI dropped 18% over 10 days. Soil moisture below threshold.",
      recommended_action: "Irrigate 4–5 hours within next 48 hours. Check irrigation channel for blockage.",
    },
    {
      id: `alert-${fieldId}-2`,
      date: daysAgo(11),
      type: "Pest Activity",
      severity: "critical",
      field_id: fieldId,
      message: "Unusual spectral signature detected in south-east quadrant. Possible aphid attack.",
      recommended_action: "Apply Imidacloprid 17.8 SL @ 0.5 ml/litre. Scout field manually within 24 hours.",
    },
    {
      id: `alert-${fieldId}-3`,
      date: daysAgo(18),
      type: "Recovery",
      severity: "low",
      field_id: fieldId,
      message: "Previous water stress event resolved. NDVI recovering to normal range.",
      recommended_action: "Continue current irrigation schedule. No action needed.",
    },
  ];
}

// ─── API methods ───────────────────────────────────────────────────────────
export const mockClient = {
  // Farms
  async listFarms(): Promise<ApiResponse<Farm[]>> {
    await delay(350);
    return ok(FARMS);
  },

  async getFarm(farmId: string): Promise<ApiResponse<Farm>> {
    await delay(200);
    const farm = FARMS.find((f) => f.id === farmId);
    if (!farm) return { ok: false, data: null as unknown as Farm, error: "Farm not found" };
    return ok(farm);
  },

  // Fields
  async listFields(farmId: string): Promise<ApiResponse<Field[]>> {
    await delay(300);
    return ok(FIELDS[farmId] ?? []);
  },

  async getField(farmId: string, fieldId: string): Promise<ApiResponse<Field>> {
    await delay(200);
    const field = FIELDS[farmId]?.find((f) => f.id === fieldId);
    if (!field) return { ok: false, data: null as unknown as Field, error: "Field not found" };
    return ok(field);
  },

  // Satellite
  async getSatelliteData(fieldId: string): Promise<ApiResponse<SatelliteData>> {
    await delay(600);
    return ok({
      field_id: fieldId,
      latest_ndvi: 0.74,
      ndvi_change_30d: -0.09,
      scan_date: daysAgo(3),
      health_zones: [
        { label: "Excellent", color: "#2d7a3a", percentage: 34 },
        { label: "Good", color: "#81c784", percentage: 28 },
        { label: "Moderate", color: "#ffcc02", percentage: 22 },
        { label: "Poor", color: "#ff9800", percentage: 11 },
        { label: "Very Poor", color: "#e53935", percentage: 5 },
      ],
      ndvi_history: buildNdviHistory(),
      stress_alerts: buildStressAlerts(fieldId),
      provenance: fieldId.includes("3a") ? MODELLED_SAT : LIVE_SAT,
    });
  },

  // Weather
  async getWeatherData(fieldId: string): Promise<ApiResponse<WeatherData>> {
    await delay(400);
    const conditions: WeatherData["forecast"] = [
      { date: daysFromNow(0), day_label: "Today", condition: "Sunny", icon: "sun", temp_hi: 32, temp_lo: 21, rain_chance: 5, rain_mm: 0, wind_kmh: 12, humidity: 58 },
      { date: daysFromNow(1), day_label: "Tomorrow", condition: "Partly Cloudy", icon: "cloud", temp_hi: 30, temp_lo: 20, rain_chance: 20, rain_mm: 2, wind_kmh: 15, humidity: 65 },
      { date: daysFromNow(2), day_label: "Wed", condition: "Light Rain", icon: "rain", temp_hi: 27, temp_lo: 18, rain_chance: 65, rain_mm: 12, wind_kmh: 22, humidity: 82 },
      { date: daysFromNow(3), day_label: "Thu", condition: "Heavy Rain", icon: "rain", temp_hi: 25, temp_lo: 17, rain_chance: 85, rain_mm: 35, wind_kmh: 28, humidity: 90 },
      { date: daysFromNow(4), day_label: "Fri", condition: "Thunderstorm", icon: "storm", temp_hi: 24, temp_lo: 16, rain_chance: 92, rain_mm: 55, wind_kmh: 45, humidity: 95 },
      { date: daysFromNow(5), day_label: "Sat", condition: "Light Rain", icon: "rain", temp_hi: 26, temp_lo: 17, rain_chance: 45, rain_mm: 8, wind_kmh: 18, humidity: 78 },
      { date: daysFromNow(6), day_label: "Sun", condition: "Cloudy", icon: "cloud", temp_hi: 28, temp_lo: 18, rain_chance: 20, rain_mm: 1, wind_kmh: 14, humidity: 68 },
      { date: daysFromNow(7), day_label: "Mon", condition: "Sunny", icon: "sun", temp_hi: 31, temp_lo: 20, rain_chance: 8, rain_mm: 0, wind_kmh: 10, humidity: 55 },
      { date: daysFromNow(8), day_label: "Tue", condition: "Sunny", icon: "sun", temp_hi: 33, temp_lo: 22, rain_chance: 5, rain_mm: 0, wind_kmh: 8, humidity: 50 },
      { date: daysFromNow(9), day_label: "Wed", condition: "Cloudy", icon: "cloud", temp_hi: 30, temp_lo: 21, rain_chance: 18, rain_mm: 3, wind_kmh: 16, humidity: 65 },
    ];
    return ok({
      field_id: fieldId,
      current: { temp: 29, condition: "Sunny", humidity: 58, wind_kmh: 12, feels_like: 31 },
      forecast: conditions,
      alerts: [
        {
          id: "wa-1",
          type: "Heavy Rainfall",
          severity: "warning",
          valid_from: daysFromNow(3),
          valid_to: daysFromNow(4),
          message: "IMD warns of heavy to very heavy rainfall (50–70mm) over the next 48 hours.",
          crop_impact: "Postpone pesticide and fertiliser application. Ensure drainage channels are clear.",
        },
        {
          id: "wa-2",
          type: "Thunderstorm",
          severity: "watch",
          valid_from: daysFromNow(4),
          valid_to: daysFromNow(5),
          message: "Thunderstorm with strong winds (40–50 km/h) expected Friday afternoon.",
          crop_impact: "Secure farm equipment. Avoid field operations during peak storm hours.",
        },
      ],
      irrigation_advice:
        "Skip irrigation for the next 4 days — expected 90+ mm rainfall will exceed crop water requirement. Resume irrigation Sunday if soil moisture drops below 40%.",
      provenance: LIVE_WEATHER,
    });
  },

  // Irrigation / Soil
  async getIrrigationData(fieldId: string): Promise<ApiResponse<IrrigationData>> {
    await delay(450);
    return ok({
      field_id: fieldId,
      soil_moisture_pct: 42,
      moisture_status: "optimal",
      soil_info: {
        type: "Sandy Loam",
        ph: 7.2,
        nitrogen: "medium",
        phosphorus: "low",
        potassium: "high",
        organic_carbon: 0.68,
        water_retention: "moderate",
      },
      schedule: {
        next_irrigation: daysFromNow(5),
        duration_hours: 4,
        method: "Drip irrigation",
        water_liters_per_acre: 18000,
        skip_reason: "Upcoming rainfall forecast (90mm) will replenish soil moisture.",
      },
      water_saved_pct: 28,
      fertiliser_recommendation:
        "Apply DAP @ 50 kg/acre as top-dress within 10 days. Phosphorus levels are low — supplement with SSP if DAP unavailable.",
      provenance: SOIL_SENSOR,
    });
  },

  // Yield & Price
  async getYieldData(fieldId: string): Promise<ApiResponse<YieldData>> {
    await delay(500);
    const priceTrend = Array.from({ length: 30 }, (_, i) => ({
      date: daysAgo(29 - i),
      price_per_quintal: 2050 + Math.round(Math.sin(i / 4) * 120 + (Math.random() - 0.5) * 60),
      mandi: "Nashik",
    }));
    return ok({
      field_id: fieldId,
      estimated_yield_quintal_per_acre: 18.4,
      confidence: 0.79,
      yield_range: { low: 16.5, high: 21.0 },
      harvest_date: daysFromNow(38),
      input_cost_per_acre: 12500,
      expected_revenue_per_acre: 34500,
      profit_per_acre: 22000,
      price_trend_30d: priceTrend,
      top_mandis: [
        { mandi: "Nashik", district: "Nashik, MH", price_per_quintal: 2180, change_pct: 2.4 },
        { mandi: "Pune", district: "Pune, MH", price_per_quintal: 2155, change_pct: 1.8 },
        { mandi: "Aurangabad", district: "Aurangabad, MH", price_per_quintal: 2090, change_pct: -0.5 },
        { mandi: "Nagpur", district: "Nagpur, MH", price_per_quintal: 2060, change_pct: -1.2 },
      ],
      best_sell_window: `${daysFromNow(42)} to ${daysFromNow(55)} — prices expected to rise 8–12% post-harvest season.`,
      provenance: MODEL_YIELD,
    });
  },

  // Market prices (live)
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async getMarketPrice(_fieldId: string): Promise<ApiResponse<{ provenance: Provenance; crop: string; state_avg: number }>> {
    await delay(300);
    return ok({ provenance: LIVE_MARKET, crop: "Wheat", state_avg: 2120 });
  },

  // AI Chat
  async sendChatMessage(
    message: string,
    history: ChatMessage[],
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    _context?: ChatContext
  ): Promise<ApiResponse<ChatMessage>> {
    await delay(800 + Math.random() * 600);

    const responses: Record<string, string> = {
      default:
        "Namaste! I'm KrishiBot, your AI farming assistant. I can help with crop diseases, fertilisers, pest control, irrigation, government schemes, and more. What would you like to know?",
      pest: "For aphid control on wheat: Apply Imidacloprid 17.8 SL at 0.5 ml/litre of water. Spray in the evening to protect pollinators. Repeat after 10–15 days if infestation persists. Also check for natural predators like ladybirds.",
      water:
        "Signs of water stress in wheat: leaf rolling, bluish-green colour, reduced growth. If NDVI is below 0.5 and it hasn't rained in 7 days, irrigate 4–5 cm depth. Best irrigation time: early morning or evening to reduce evaporation.",
      price:
        "Current wheat MSP is ₹2,275/quintal. Nashik mandi is trading at ₹2,180. Prices typically rise 10–15% in April–May after Rabi procurement. I recommend holding 30–40% of produce if you have storage.",
      soil: "For sandy loam soil with low phosphorus: Apply SSP (Single Super Phosphate) @ 250 kg/acre before sowing. Alternatively, DAP @ 50 kg/acre works well. Test soil every 2–3 years — you can get free soil testing through PM Kisan Samridhi Kendra.",
      scheme:
        "Key schemes you may be eligible for:\n• PM-KISAN: ₹6,000/year direct benefit\n• Pradhan Mantri Fasal Bima Yojana: Crop insurance at 1.5–2% premium\n• PM Kisan Credit Card: Low-interest loan up to ₹3 lakh\n• eNAM: Online mandi trading platform\n\nCheck your eligibility at pmkisan.gov.in or your nearest CSC centre.",
    };

    const msgLower = message.toLowerCase();
    let content = responses.default;
    if (msgLower.includes("pest") || msgLower.includes("aphid") || msgLower.includes("insect") || msgLower.includes("keet"))
      content = responses.pest;
    else if (msgLower.includes("water") || msgLower.includes("irrigation") || msgLower.includes("sinchhai") || msgLower.includes("stress"))
      content = responses.water;
    else if (msgLower.includes("price") || msgLower.includes("bhav") || msgLower.includes("msp") || msgLower.includes("mandi"))
      content = responses.price;
    else if (msgLower.includes("soil") || msgLower.includes("mitti") || msgLower.includes("fertilizer") || msgLower.includes("khad"))
      content = responses.soil;
    else if (msgLower.includes("scheme") || msgLower.includes("yojana") || msgLower.includes("subsidy") || msgLower.includes("loan"))
      content = responses.scheme;
    else if (history.length === 0) content = responses.default;

    return ok({
      id: `msg-${Date.now()}`,
      role: "assistant",
      content,
      timestamp: now(),
      language: "en",
    });
  },
};

export type MockClient = typeof mockClient;
