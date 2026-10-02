"use client";



import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CalendarRange, Info, LineChart as LineChartIcon, Loader2, MapPin, RefreshCw, Scale, Store, Tractor } from "lucide-react";
import AppLayout from "@/components/AppLayout";
import PriceForecastChart, { PriceForecastLegend } from "@/components/charts/PriceForecastChart";
import PriceTrendChart from "@/components/market/PriceTrendChart";
import NearbyMandisTable from "@/components/market/NearbyMandisTable";
import RecommendationCard from "@/components/market/RecommendationCard";
import ModelInfoTooltip from "@/components/market/ModelInfoTooltip";
import { EstimateBadge, LiveBadge } from "@/components/market/Badges";
import { changeClass, isoDaysAgo, longDate, MODEL_LABELS, pct, rupees, shortDate, TREND_META } from "@/components/market/format";
import { useFarmStore } from "@/lib/stores/farmStore";
import { isRealFarmId } from "@/lib/hooks/useFarmSatelliteAnalysis";
import type { ForecastModelInfo, ForecastPoint, HistoryPoint, NearbyMarket, Trend } from "@/lib/api/market-client";
import {
  useFarmMarketForecast,
  useLatestPrices,
  useMarketAnalytics,
  useMarketCommodities,
  useMarketLocations,
  useNearbyMarkets,
  usePriceForecast,
  usePriceHistory,
} from "@/lib/hooks/useMarketPrices";

const PERIODS = [
  { days: 180, label: "6 months" },
  { days: 365, label: "1 year" },
  { days: 1095, label: "3 years" },
];
const STALE_AFTER_DAYS = 7;
const BASELINE_MODELS = new Set(["naive", "moving_average", "seasonal_naive"]);
// The Crop selector only offers these -- the other Agmarknet commodities
// with stored prices (Soyabean, Cotton, Maize, chillies, ...) stay out of
// the picker, in this order.
const ALLOWED_CROPS = ["Rice", "Wheat", "Onion", "Sugarcane", "Potato"];

function Section({
  title,
  icon: Icon,
  right,
  className = "",
  children,
}: {
  title: string;
  icon?: typeof Store;
  right?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`bg-white rounded-2xl border border-farm-border-color p-4 sm:p-5 shadow-xs min-w-0 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h2 className="text-sm font-bold text-farm-dark flex items-center gap-2">
          {Icon && <Icon className="w-4 h-4 text-farm-green" />}
          {title}
        </h2>
        {right && <div className="flex items-center gap-2">{right}</div>}
      </div>
      {children}
    </section>
  );
}

function Notice({ tone = "info", children, action }: { tone?: "info" | "warn" | "error"; children: React.ReactNode; action?: React.ReactNode }) {
  const styles = {
    info: "bg-farm-gray/70 border-farm-border-color text-farm-dark",
    warn: "bg-amber-50 border-amber-200 text-amber-800",
    error: "bg-rose-50 border-rose-200 text-rose-800",
  }[tone];
  const Icon = tone === "info" ? Info : AlertTriangle;
  return (
    <div className={`flex items-start gap-2.5 rounded-xl border px-3.5 py-3 text-sm ${styles}`} role={tone === "error" ? "alert" : undefined}>
      <Icon className="w-4 h-4 mt-0.5 flex-shrink-0" />
      <div className="flex-1">{children}</div>
      {action}
    </div>
  );
}

function Loading({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-farm-muted py-8 justify-center">
      <Loader2 className="w-4 h-4 animate-spin" /> {label}
    </div>
  );
}

function RetryButton({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} className="inline-flex items-center gap-1 text-xs font-semibold underline underline-offset-2">
      <RefreshCw className="w-3 h-3" /> Retry
    </button>
  );
}

function Select({ label, value, onChange, children, disabled }: { label: string; value: string; onChange: (v: string) => void; children: React.ReactNode; disabled?: boolean }) {
  return (
    <label className="flex flex-col gap-1 min-w-0">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-farm-muted">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-white border border-farm-border-color rounded-lg px-2.5 py-2 text-sm text-farm-dark focus:outline-none focus:border-farm-green disabled:opacity-60"
      >
        {children}
      </select>
    </label>
  );
}

function Stat({ label, value, sub, valueClass = "text-farm-dark" }: { label: string; value: string; sub?: string; valueClass?: string }) {
  return (
    <div className="rounded-xl border border-farm-border-color p-3">
      <p className="text-[11px] uppercase tracking-wide text-farm-muted font-semibold">{label}</p>
      <p className={`text-lg font-extrabold mt-0.5 ${valueClass}`}>{value}</p>
      {sub && <p className="text-[11px] text-farm-muted">{sub}</p>}
    </div>
  );
}

function TrendPill({ trend, change }: { trend: Trend; change: number | null }) {
  const meta = TREND_META[trend];
  return (
    <span className={`inline-flex items-center gap-1.5 border rounded-full px-2.5 py-1 text-xs font-semibold ${meta.className}`}>
      <meta.Icon className="w-3.5 h-3.5" />
      {meta.label}
      {change !== null && <span className="font-normal opacity-80">({pct(change)} week on week)</span>}
    </span>
  );
}

function distanceLabel(km: number | null | undefined, precision?: string | null): string {
  if (km === null || km === undefined) return "";
  return `${precision === "district" ? "~" : ""}${km < 10 ? km.toFixed(1) : Math.round(km)} km`;
}

/** Highest modal price among mandis that reported within the freshness window. */
function bestToday(markets: NearbyMarket[], today: string): number | undefined {
  const fresh = markets.filter((m) => (Date.parse(today) - Date.parse(m.as_of)) / 86_400_000 <= STALE_AFTER_DAYS);
  return fresh.sort((a, b) => b.modal_price - a.modal_price)[0]?.market_id;
}

function ForecastBody({
  available,
  reason,
  forecasts,
  models,
  disclaimer,
  history,
  today,
  highlightHorizon,
  historyLoading,
}: {
  available: boolean;
  reason: string | null;
  forecasts: ForecastPoint[];
  models: ForecastModelInfo[];
  disclaimer: string;
  history: HistoryPoint[];
  today: string;
  highlightHorizon?: number | null;
  historyLoading?: boolean;
}) {
  const baseline = models.length > 0 && models.every((m) => BASELINE_MODELS.has(m.model_name)) ? models[0].model_name : null;
  return (
    <div className="space-y-3">
      {!available && (
        <Notice>
          <span className="font-semibold">No estimate for this mandi.</span> {reason ?? "Forecast unavailable because insufficient historical data exists."}
        </Notice>
      )}
      {available && forecasts.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {forecasts.map((f) => (
            <div
              key={f.horizon_days}
              className={`rounded-xl border border-dashed p-3 ${f.horizon_days === highlightHorizon ? "border-sky-400 bg-sky-50/60" : "border-sky-200"}`}
            >
              <p className="text-[11px] uppercase tracking-wide text-farm-muted font-semibold">
                {f.horizon_days} days · {shortDate(f.forecast_date)}
              </p>
              <p className="text-lg font-extrabold text-farm-dark mt-0.5">
                {rupees(f.predicted_price)} <span className={`text-xs font-semibold ${changeClass(f.change_pct)}`}>{pct(f.change_pct)}</span>
              </p>
              <p className="text-[11px] text-farm-muted">
                {f.lower_bound !== null && f.upper_bound !== null ? `range ${rupees(f.lower_bound)} – ${rupees(f.upper_bound)}` : "range not available"}
              </p>
            </div>
          ))}
        </div>
      )}
      {historyLoading ? (
        <Loading label="Loading prices…" />
      ) : history.length === 0 && forecasts.length === 0 ? (
        <Notice>No prices from this mandi in the last 90 days.</Notice>
      ) : (
        <>
          <PriceForecastChart history={history} forecasts={available ? forecasts : []} today={today} highlightHorizon={highlightHorizon} />
          <PriceForecastLegend withEstimate={available && forecasts.length > 0} />
        </>
      )}
      {available && (
        <p className="flex items-start gap-2 text-[11px] text-farm-muted">
          <LineChartIcon className="w-3.5 h-3.5 text-farm-green mt-px flex-shrink-0" />
          <span>
            {baseline
              ? `Models trained on past mandi prices, seasons, trends and arrivals were tested against simple baselines; for this crop none beat the ${MODEL_LABELS[baseline]?.toLowerCase() ?? baseline} baseline, so that is what these estimates use. `
              : "Estimated from past mandi prices, seasonal patterns, recent trends and arrival data. "}
            {disclaimer}
          </span>
        </p>
      )}
    </div>
  );
}

function MarketContent() {
  const today = isoDaysAgo(0);
  const { farms, mounted } = useFarmStore();
  const realFarms = useMemo(() => farms.filter((f) => isRealFarmId(f.id)), [farms]);

  const [farmId, setFarmId] = useState<string>("");
  // Explicit choices; undefined = automatic (the backend picks for a farm,
  // the busiest crop/state/mandi otherwise).
  const [pickCommodity, setPickCommodity] = useState<number | undefined>();
  const [pickMarket, setPickMarket] = useState<number | undefined>();
  const [pickState, setPickState] = useState<string>("");
  const [periodDays, setPeriodDays] = useState(180);

  const farm = realFarms.find((f) => f.id === farmId);
  const farmMode = !!farm;

  // Default to the signed-in user's first farm -- once, so choosing "none"
  // afterwards sticks.
  const farmDefaulted = useRef(false);
  useEffect(() => {
    if (!mounted || farmDefaulted.current) return;
    farmDefaulted.current = true;
    if (realFarms.length) setFarmId(realFarms[0].id);
  }, [mounted, realFarms]);

  const commodities = useMarketCommodities(undefined, ALLOWED_CROPS.join(","));
  // The most-traded allowed crop, used as the browse-mode default and as the
  // fallback when a farm's real crop isn't one of the allowed ones.
  const topAllowedCommodity = useMemo(() => {
    const allowed = (commodities.data ?? []).filter((c) => ALLOWED_CROPS.includes(c.name));
    return allowed.length ? [...allowed].sort((a, b) => b.markets - a.markets)[0].id : undefined;
  }, [commodities.data]);

  // ---- farm mode ----
  const farmForecast = useFarmMarketForecast(farm?.id, pickCommodity, pickMarket);
  const rawFd = farmMode ? farmForecast.data : undefined;
  // A farm's actual crop can map to a commodity outside the allowed list
  // (e.g. Soyabean) -- when nothing was explicitly picked, swap to the
  // top allowed crop instead of showing one the selector doesn't offer.
  const cropNeedsCorrection =
    farmMode && pickCommodity === undefined && !!rawFd?.selected_commodity &&
    !ALLOWED_CROPS.includes(rawFd.selected_commodity.name) && topAllowedCommodity !== undefined;
  useEffect(() => {
    if (cropNeedsCorrection && topAllowedCommodity !== undefined) setPickCommodity(topAllowedCommodity);
  }, [cropNeedsCorrection, topAllowedCommodity]);
  const fd = cropNeedsCorrection ? undefined : rawFd;

  // ---- browse mode ----
  const browseCommodity = farmMode ? undefined : pickCommodity ?? topAllowedCommodity;
  const locations = useMarketLocations(browseCommodity);
  const browseState = useMemo(() => {
    const states = locations.data;
    if (!states?.length) return undefined;
    if (states.some((s) => s.name === pickState)) return pickState;
    const size = (s: (typeof states)[number]) => s.districts.reduce((n, d) => n + d.markets, 0);
    return [...states].sort((a, b) => size(b) - size(a))[0].name;
  }, [locations.data, pickState]);
  const latest = useLatestPrices(browseState ? browseCommodity : undefined, browseState);
  const browseMarket = useMemo(() => {
    const prices = latest.data?.prices;
    if (!prices?.length) return undefined;
    if (prices.some((p) => p.market_id === pickMarket)) return pickMarket;
    return [...prices].sort((a, b) => b.as_of.localeCompare(a.as_of) || b.trading_days_30d - a.trading_days_30d)[0].market_id;
  }, [latest.data, pickMarket]);
  const publicForecast = usePriceForecast(farmMode ? undefined : browseMarket, browseCommodity);
  const publicHistory = usePriceHistory(farmMode ? undefined : browseMarket, browseCommodity, isoDaysAgo(90), today);
  const browseStats = latest.data?.prices.find((p) => p.market_id === browseMarket);
  const publicNearby = useNearbyMarkets(farmMode ? undefined : browseCommodity, {
    lat: publicForecast.data?.market.latitude ?? null,
    lon: publicForecast.data?.market.longitude ?? null,
    state: browseState,
    radiusKm: 100,
  });

  // ---- one view over both modes ----
  const commodityId = farmMode ? fd?.selected_commodity?.id ?? pickCommodity : browseCommodity;
  const marketId = farmMode ? fd?.market?.id : browseMarket;
  const stats = farmMode ? fd?.today ?? null : browseStats ?? null;
  const forecast = farmMode ? fd?.forecast : publicForecast.data;
  const history90 = (farmMode ? fd?.history : publicHistory.data?.series) ?? [];
  const nearbyRows = (farmMode ? fd?.nearby : publicNearby.data?.markets) ?? [];
  const nearbyNote = farmMode ? null : publicNearby.data?.note;
  const attribution = farmMode ? fd?.attribution : publicNearby.data?.attribution;
  const rec = fd?.recommendation;
  const commodityName =
    (farmMode ? fd?.selected_commodity?.name : undefined) ?? commodities.data?.find((c) => c.id === commodityId)?.name ?? "";
  const sources = latest.data?.provenance.sources.join(", ") ?? "Agmarknet";

  const longHistory = usePriceHistory(marketId, commodityId, isoDaysAgo(periodDays), today);
  const analytics = useMarketAnalytics(marketId, commodityId);
  const staleDays = stats ? Math.round((Date.parse(today) - Date.parse(stats.as_of)) / 86_400_000) : 0;
  const bestId = rec?.best_nearby?.market_id ?? bestToday(nearbyRows, today);

  // Mandi options: the farm's nearby list (with distance), or the state's markets.
  const mandiOptions = useMemo(() => {
    if (farmMode) {
      const rows = fd?.nearby ?? [];
      const opts = rows.map((r) => ({
        id: r.market_id,
        label: `${r.market}${r.distance_km !== null ? ` — ${distanceLabel(r.distance_km, r.coordinate_precision)}` : ""}${r.model_ready ? " · estimate" : ""}`,
      }));
      if (fd?.market && !rows.some((r) => r.market_id === fd.market?.id)) opts.unshift({ id: fd.market.id, label: fd.market.name });
      return opts;
    }
    return (latest.data?.prices ?? []).map((p) => ({ id: p.market_id, label: p.market })).sort((a, b) => a.label.localeCompare(b.label));
  }, [farmMode, fd, latest.data]);

  const cropOptions = useMemo(
    () =>
      (commodities.data ?? [])
        .filter((c) => ALLOWED_CROPS.includes(c.name))
        .map((c) => ({ id: c.id, name: c.name }))
        .sort((a, b) => ALLOWED_CROPS.indexOf(a.name) - ALLOWED_CROPS.indexOf(b.name)),
    [commodities.data]
  );

  const chooseFarm = (id: string) => {
    // Leaving farm mode keeps the crop on screen.
    setPickCommodity(id ? undefined : commodityId);
    setPickMarket(undefined);
    setFarmId(id);
  };
  const chooseCrop = (id: number) => {
    setPickCommodity(id);
    setPickMarket(undefined);
  };

  // ---- whole-page states ----
  if (commodities.isLoading) return <Loading label="Loading mandi prices…" />;
  if (commodities.isError) {
    return (
      <Notice tone="error" action={<RetryButton onClick={() => commodities.refetch()} />}>
        Mandi prices can&apos;t be loaded right now. {(commodities.error as Error)?.message}
      </Notice>
    );
  }
  if (!commodities.data?.length) {
    return <Notice>No mandi price data has been imported yet. Prices appear here after the nightly import from Agmarknet.</Notice>;
  }

  const loadingMain = farmMode ? farmForecast.isLoading || cropNeedsCorrection : latest.isLoading;
  const mandiLocation = stats ? `${stats.district ? `${stats.district}, ` : ""}${stats.state ?? ""}` : "";

  return (
    <div className="space-y-4">
      {/* Filters */}
      <section className="bg-white rounded-2xl border border-farm-border-color p-4 shadow-xs">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {realFarms.length > 0 && (
            <Select label="My farm" value={farmId} onChange={chooseFarm}>
              <option value="">— none (browse) —</option>
              {realFarms.map((f) => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </Select>
          )}
          <Select label="Crop" value={commodityId?.toString() ?? ""} onChange={(v) => chooseCrop(Number(v))}>
            {commodityId === undefined && <option value="">—</option>}
            {cropOptions.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </Select>
          {!farmMode && (
            <Select
              label="State"
              value={browseState ?? ""}
              onChange={(v) => { setPickState(v); setPickMarket(undefined); }}
              disabled={!locations.data?.length}
            >
              {(locations.data ?? []).map((s) => (
                <option key={s.id} value={s.name}>{s.name}</option>
              ))}
            </Select>
          )}
          <Select label="Mandi" value={marketId?.toString() ?? ""} onChange={(v) => setPickMarket(Number(v))} disabled={!mandiOptions.length}>
            {marketId === undefined && <option value="">—</option>}
            {mandiOptions.map((m) => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
          </Select>
        </div>
        {farmMode && fd && (
          <p className="text-[11px] text-farm-muted mt-3">
            {farm.name}: {fd.crop}
            {fd.district || fd.state ? ` · ${[fd.district, fd.state].filter(Boolean).join(", ")}` : ""}. Mandis are listed nearest first; those marked
            &nbsp;&ldquo;estimate&rdquo; have a price forecast.
          </p>
        )}
        {farmMode && fd?.message && <p className="text-xs text-amber-700 mt-2">{fd.message}</p>}
      </section>

      {loadingMain && <Loading label="Loading prices…" />}
      {farmMode && farmForecast.isError && (
        <Notice tone="error" action={<RetryButton onClick={() => farmForecast.refetch()} />}>
          Prices for this farm can&apos;t be loaded right now. {(farmForecast.error as Error)?.message}
        </Notice>
      )}
      {!farmMode && latest.isError && (
        <Notice tone="error" action={<RetryButton onClick={() => latest.refetch()} />}>Latest prices can&apos;t be loaded right now.</Notice>
      )}
      {!farmMode && latest.data && latest.data.prices.length === 0 && (
        <Notice>No recent mandi price is available for {commodityName || "this crop"} in {browseState}.</Notice>
      )}
      {!farmMode && !loadingMain && commodityId !== undefined && browseState === undefined && !locations.isLoading && (
        <Notice>
          No mandi price data is available for {commodityName || "this crop"} yet. Agmarknet mandis haven&apos;t
          reported any trades for it.
        </Notice>
      )}

      {stats && staleDays > STALE_AFTER_DAYS && (
        <Notice tone="warn">
          The latest price from {stats.market} is from {longDate(stats.as_of)} ({staleDays} days ago). This mandi hasn&apos;t reported {commodityName} recently.
        </Notice>
      )}

      {(stats || (farmMode && fd)) && (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* Today's price */}
          <Section
            title={stats ? `${commodityName} at ${stats.market}` : "Today's price"}
            icon={Store}
            className="lg:col-span-2"
            right={stats ? <LiveBadge asOf={shortDate(stats.as_of)} /> : undefined}
          >
            {stats ? (
              <div className="space-y-3">
                <div>
                  <p className="text-3xl font-extrabold text-farm-dark">
                    {rupees(stats.modal_price)}
                    <span className="text-sm font-medium text-farm-muted">/quintal</span>
                  </p>
                  <p className="text-xs text-farm-muted mt-0.5">Modal price (most common trade) on {longDate(stats.as_of)}</p>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Min" value={rupees(stats.min_price)} />
                  <Stat label="Max" value={rupees(stats.max_price)} />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <TrendPill trend={stats.trend} change={stats.trend_change_pct} />
                  <span className={`text-xs font-semibold ${changeClass(stats.change_7d_pct)}`}>{pct(stats.change_7d_pct)} in 7 days</span>
                </div>
                <p className="text-[11px] text-farm-muted flex items-start gap-1">
                  <MapPin className="w-3 h-3 mt-px flex-shrink-0" />
                  <span>
                    {mandiLocation}
                    {fd?.market?.distance_km !== null && fd?.market?.distance_km !== undefined && ` · ${distanceLabel(fd.market.distance_km, fd.market.coordinate_precision)} from ${farm?.name}`}
                    {stats.arrival_quantity !== null && ` · arrivals ${stats.arrival_quantity.toLocaleString("en-IN")} t`}
                    {` · Source: ${sources}`}
                  </span>
                </p>
              </div>
            ) : (
              <Notice>No recent price for {commodityName || "this crop"} at this mandi.</Notice>
            )}
          </Section>

          {/* Sell or hold? */}
          <Section title="Sell or hold?" icon={Scale} className="lg:col-span-3" right={<EstimateBadge />}>
            {farmMode && rec && <RecommendationCard rec={rec} onSelectMarket={(id) => setPickMarket(id)} />}
            {farmMode && !rec && farmForecast.isLoading && <Loading label="Working out the suggestion…" />}
            {!farmMode && realFarms.length > 0 && (
              <Notice>Choose one of your farms above to get a sell-now or hold suggestion for its crop.</Notice>
            )}
            {!farmMode && realFarms.length === 0 && (
              <Notice>
                <Link href="/farms" className="font-semibold text-farm-green underline underline-offset-2">Sign in and add a farm</Link> to get a
                sell-now or hold suggestion for your crop at the mandis near your field.
              </Notice>
            )}
          </Section>
        </div>
      )}

      {/* Forecast */}
      {marketId !== undefined && (
        <Section
          title="Last 90 days and next 30 days"
          icon={CalendarRange}
          right={
            <>
              <LiveBadge />
              <EstimateBadge />
              {forecast?.models && <ModelInfoTooltip models={forecast.models} />}
            </>
          }
        >
          {!forecast && (farmMode ? farmForecast.isLoading : publicForecast.isLoading) && <Loading label="Loading forecast…" />}
          {!farmMode && publicForecast.isError && (
            <Notice tone="error" action={<RetryButton onClick={() => publicForecast.refetch()} />}>The forecast can&apos;t be loaded right now.</Notice>
          )}
          {forecast && (
            <ForecastBody
              available={forecast.available}
              reason={forecast.reason}
              forecasts={forecast.forecasts}
              models={forecast.models}
              disclaimer={forecast.disclaimer}
              history={history90}
              today={today}
              highlightHorizon={rec?.hold_days ?? rec?.expected_gain?.horizon_days}
              historyLoading={!farmMode && publicHistory.isLoading}
            />
          )}
        </Section>
      )}

      {/* Nearby */}
      {commodityId !== undefined && marketId !== undefined && (
        <Section
          title="Nearby mandis"
          icon={MapPin}
          right={<span className="text-[11px] text-farm-muted">{farm ? `From ${farm.name}` : `Around ${stats?.market ?? "this mandi"}`} · within 100 km, then same district/state</span>}
        >
          {!farmMode && publicNearby.isLoading && <Loading label="Finding nearby mandis…" />}
          {!farmMode && publicNearby.isError && (
            <Notice tone="error" action={<RetryButton onClick={() => publicNearby.refetch()} />}>Nearby mandis can&apos;t be loaded right now.</Notice>
          )}
          {nearbyRows.length === 0 && (farmMode ? !!fd : !!publicNearby.data) && (
            <Notice>No other mandi near here has reported {commodityName} recently.</Notice>
          )}
          {nearbyRows.length > 0 && (
            <>
              <NearbyMandisTable markets={nearbyRows} selectedMarketId={marketId} bestMarketId={bestId} onSelect={setPickMarket} today={today} />
              <p className="text-[11px] text-farm-muted mt-2">
                {nearbyNote ?? "Ranked by distance where market locations are known, then same district, then same state. The highest price is not necessarily the best market once transport and time are considered."}
                {attribution && <> · {attribution}</>}
              </p>
            </>
          )}
        </Section>
      )}

      {/* Longer history + summary + outlook */}
      {stats && (
        <>
          <Section
            title="Price history"
            icon={Tractor}
            right={
              <select
                aria-label="History period"
                value={periodDays}
                onChange={(e) => setPeriodDays(Number(e.target.value))}
                className="bg-white border border-farm-border-color rounded-lg px-2 py-1 text-xs text-farm-dark focus:outline-none focus:border-farm-green"
              >
                {PERIODS.map((p) => (
                  <option key={p.days} value={p.days}>{p.label}</option>
                ))}
              </select>
            }
          >
            {longHistory.isLoading && <Loading label="Loading price history…" />}
            {longHistory.isError && <Notice tone="error" action={<RetryButton onClick={() => longHistory.refetch()} />}>Price history can&apos;t be loaded right now.</Notice>}
            {longHistory.data && longHistory.data.series.length === 0 && <Notice>No historical prices for this mandi in the selected period.</Notice>}
            {longHistory.data && longHistory.data.series.length > 0 && <PriceTrendChart series={longHistory.data.series} />}
            <p className="text-[11px] text-farm-muted mt-2">Live modal price with the day&apos;s min–max range.</p>
          </Section>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Section title="Price summary" className="lg:col-span-2" right={<TrendPill trend={stats.trend} change={stats.trend_change_pct} />}>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <Stat label="7-day average" value={rupees(stats.avg_7d)} />
                <Stat label="14-day average" value={rupees(stats.avg_14d)} />
                <Stat label="30-day average" value={rupees(stats.avg_30d)} />
                <Stat label="7-day change" value={pct(stats.change_7d_pct)} valueClass={changeClass(stats.change_7d_pct)} />
                <Stat label="30-day change" value={pct(stats.change_30d_pct)} valueClass={changeClass(stats.change_30d_pct)} />
                <Stat label="30-day range" value={`${rupees(stats.min_30d)} – ${rupees(stats.max_30d)}`} sub={`${stats.trading_days_30d} trading days`} />
              </div>
              <p className="text-[11px] text-farm-muted mt-3">Trend compares the last 7 days&apos; average with the 7 days before (±2.5% counts as stable).</p>
            </Section>
            <Section title="Price outlook">
              {analytics.isLoading && <Loading label="Working out the outlook…" />}
              {analytics.data && (
                <div className="space-y-2">
                  <p className="text-sm font-bold text-farm-dark">
                    Outlook: <span className="capitalize">{analytics.data.outlook.label}</span>
                  </p>
                  <ul className="space-y-1.5 text-sm text-farm-dark list-disc pl-4">
                    {analytics.data.outlook.statements.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                  <p className="text-[11px] text-farm-muted">Calculated from the prices and estimates shown on this page.</p>
                </div>
              )}
              {analytics.isError && <Notice tone="error">The outlook can&apos;t be loaded right now.</Notice>}
            </Section>
          </div>
        </>
      )}
    </div>
  );
}

export default function MarketPage() {
  return (
    <AppLayout>
      <div className="max-w-6xl mx-auto space-y-4 pb-16">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl sm:text-2xl font-extrabold text-farm-dark">Market</h1>
            <p className="text-sm text-farm-muted mt-1">
              Mandi prices reported on Agmarknet, price estimates for the next 30 days, and whether to sell now or hold.
            </p>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-farm-muted">
            <LiveBadge /> actual prices
            <EstimateBadge /> model estimates
          </div>
        </div>
        <MarketContent />
      </div>
    </AppLayout>
  );
}
