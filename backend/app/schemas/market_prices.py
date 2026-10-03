"""Response models for /market-prices. Money is Rs/quintal as a JSON number
(2 decimals); arrivals are tonnes; percentages are plain numbers (5.2 = 5.2%)."""

from datetime import date, datetime

from pydantic import BaseModel


class ProvenanceOut(BaseModel):
    sources: list[str]
    as_of: date | None
    is_stale: bool
    last_ingested_at: datetime | None
    last_ingestion_status: str | None


class CommodityOut(BaseModel):
    id: int
    name: str
    commodity_group: str | None
    markets: int
    latest_date: date | None


class DistrictOut(BaseModel):
    id: int
    name: str
    markets: int


class StateOut(BaseModel):
    id: int
    name: str
    districts: list[DistrictOut]


class MarketOut(BaseModel):
    id: int
    name: str
    district: str | None
    state: str | None
    latitude: float | None
    longitude: float | None
    coordinate_source: str | None
    coordinate_precision: str | None
    latest_date: date | None


class MarketStatsOut(BaseModel):
    market_id: int
    market: str
    district: str | None
    state: str | None
    as_of: date
    modal_price: float
    min_price: float | None
    max_price: float | None
    arrival_quantity: float | None
    avg_7d: float | None
    avg_14d: float | None
    avg_30d: float | None
    change_7d_pct: float | None
    change_30d_pct: float | None
    min_7d: float | None
    max_7d: float | None
    min_30d: float | None
    max_30d: float | None
    volatility_30d_pct: float | None
    trading_days_30d: int
    trend: str
    trend_change_pct: float | None


class CommodityRef(BaseModel):
    id: int
    name: str


class LatestPricesOut(BaseModel):
    commodity: CommodityRef
    state: str | None
    district: str | None
    unit: str = "Rs/quintal"
    prices: list[MarketStatsOut]
    provenance: ProvenanceOut


class RawPriceOut(BaseModel):
    market_id: int
    market: str
    district: str | None
    variety: str | None
    grade: str | None
    arrival_date: date
    min_price: float | None
    max_price: float | None
    modal_price: float
    arrival_quantity: float | None
    unit: str
    arrival_unit: str | None
    source: str
    quality_flags: list[str]


class RawPricesOut(BaseModel):
    commodity: CommodityRef
    from_date: date
    to_date: date
    page: int
    page_size: int
    total: int
    records: list[RawPriceOut]


class HistoryPointOut(BaseModel):
    date: date
    modal_price: float
    min_price: float | None
    max_price: float | None
    arrival_quantity: float | None
    report_count: int
    source: str


class HistoryOut(BaseModel):
    market: MarketOut
    commodity: CommodityRef
    from_date: date
    to_date: date
    unit: str = "Rs/quintal"
    series: list[HistoryPointOut]
    provenance: ProvenanceOut


class NearbyMarketOut(MarketStatsOut):
    distance_km: float | None
    scope: str
    coordinate_precision: str | None


class NearbyOut(BaseModel):
    commodity: CommodityRef
    origin: dict
    radius_km: float
    markets: list[NearbyMarketOut]
    note: str
    attribution: str | None
    provenance: ProvenanceOut


class TrendsOut(BaseModel):
    commodity: CommodityRef
    state: str | None
    markets_reporting: int
    markets_stale: int
    trend_counts: dict[str, int]
    average_modal_price: float | None
    median_change_7d_pct: float | None
    median_change_30d_pct: float | None
    top_gainers: list[MarketStatsOut]
    top_decliners: list[MarketStatsOut]
    as_of: date | None


class ForecastPointOut(BaseModel):
    horizon_days: int
    base_date: date
    base_price: float
    forecast_date: date
    predicted_price: float
    lower_bound: float | None
    upper_bound: float | None
    change_pct: float | None
    model_name: str
    model_version: str


class ForecastModelOut(BaseModel):
    horizon_days: int
    model_name: str
    model_version: str
    trained_at: datetime
    training_period: dict[str, date]
    training_samples: int
    markets: int
    validation: dict
    selection_note: str | None
    interval: dict


class ForecastOutBase(BaseModel):
    available: bool
    reason: str | None
    generated_at: datetime | None = None
    forecasts: list[ForecastPointOut]
    models: list[ForecastModelOut]
    disclaimer: str


class ForecastOut(ForecastOutBase):
    market: MarketOut
    commodity: CommodityRef


class OutlookOut(BaseModel):
    label: str
    statements: list[str]
    basis: dict | None = None


class AnalyticsOut(BaseModel):
    market: MarketOut
    commodity: CommodityRef
    stats: MarketStatsOut | None
    outlook: OutlookOut
    provenance: ProvenanceOut


class FarmMarketOut(BaseModel):
    farm_id: str
    crop: str
    commodities: list[CommodityRef]
    state: str | None
    district: str | None
    selected_commodity: CommodityRef | None
    nearby: list[NearbyMarketOut]
    attribution: str | None
    message: str | None


class FarmForecastMarketOut(MarketOut):
    distance_km: float | None
    model_ready: bool


class FarmNearbyMarketOut(NearbyMarketOut):
    model_ready: bool


class HorizonOptionOut(BaseModel):
    horizon_days: int
    forecast_date: date
    predicted_price: float
    expected_gain: float
    expected_gain_pct: float
    holding_cost: float
    net_gain: float
    typical_error: float | None
    typical_error_basis: str | None
    gain_range: list[float] | None
    worth_holding: bool
    model_name: str


class ExpectedGainOut(BaseModel):
    per_quintal: float
    pct: float
    horizon_days: int
    by_date: date
    predicted_price: float


class ErrorRangeOut(BaseModel):
    typical_error: float | None
    basis: str | None
    low: float | None
    high: float | None
    level: float


class HoldingCostOut(BaseModel):
    pct_per_30_days: float
    assumed: bool
    configured: bool
    per_quintal: float | None = None
    horizon_days: int | None = None


class BestNearbyOut(BaseModel):
    market_id: int
    market: str
    district: str | None
    distance_km: float | None
    coordinate_precision: str | None
    modal_price: float
    as_of: date
    is_selected: bool
    difference_vs_selected: float | None
    note: str


class RecommendationOut(BaseModel):
    action: str  # "hold" | "sell_now" | "unavailable"
    headline: str
    hold_days: int | None
    reason: str
    commodity: str | None
    market: str | None
    base_price: float | None
    base_date: date | None
    expected_gain: ExpectedGainOut | None
    error_range: ErrorRangeOut | None
    holding_cost: HoldingCostOut | None
    horizons: list[HorizonOptionOut]
    perishable: bool
    warning: str | None
    best_nearby: BestNearbyOut | None
    disclaimer: str


class FarmForecastOut(BaseModel):
    farm_id: str
    crop: str
    commodities: list[CommodityRef]
    selected_commodity: CommodityRef | None
    state: str | None
    district: str | None
    market: FarmForecastMarketOut | None
    today: MarketStatsOut | None
    unit: str = "Rs/quintal"
    history: list[HistoryPointOut]
    forecast: ForecastOutBase
    recommendation: RecommendationOut
    nearby: list[FarmNearbyMarketOut]
    attribution: str | None
    message: str | None
