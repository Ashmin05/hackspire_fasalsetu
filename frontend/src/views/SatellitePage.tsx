"use client";



import { useState, useEffect, useMemo, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import AppLayout from "@/components/AppLayout";
import MapView from "@/components/map/MapView";
import FarmsLoadError from "@/components/FarmsLoadError";
import SourceBadge, { formatPassDate, LiveSource } from "@/components/SourceBadge";
import { useFarmStore, applyLiveSatellite } from "@/lib/stores/farmStore";
import { useFarmSatelliteAnalysis } from "@/lib/hooks/useFarmSatelliteAnalysis";
import { useFarmSatelliteLayers } from "@/lib/hooks/useFarmSatelliteLayers";
import { useFarmSatelliteTimeseries } from "@/lib/hooks/useFarmSatelliteTimeseries";
import { useFarmEnvironment } from "@/lib/hooks/useFarmEnvironment";
import SatelliteAnalyticsPanel, {
  PanelStressZone,
  SatelliteMapLayer,
} from "@/components/satellite/SatelliteAnalyticsPanel";
import SatelliteStatusState from "@/components/satellite/SatelliteStatusState";
import PassDateSlider, { SatellitePass } from "@/components/satellite/PassDateSlider";
import EnvironmentReportCard from "@/components/satellite/EnvironmentReportCard";
import type { SeasonCurvePoint } from "@/components/charts/SeasonCurveChart";
import {
  MapPin, Satellite, Droplets, Camera, AlertTriangle, Leaf,
  ChevronLeft, ChevronDown, Plus, RefreshCw, Loader2, Calendar
} from "lucide-react";

const TILE_KEY_BY_LAYER: Record<SatelliteMapLayer, "true_color" | "ndvi" | "ndwi" | "evi" | "stress"> = {
  rgb: "true_color",
  ndvi: "ndvi",
  ndwi: "ndwi",
  evi: "evi",
  stress: "stress",
};

const LAYERS: { key: SatelliteMapLayer; label: string; icon: typeof Satellite }[] = [
  { key: "ndvi", label: "NDVI (Vegetation)", icon: Satellite },
  { key: "ndwi", label: "NDWI (Water)", icon: Droplets },
  { key: "evi", label: "EVI (Enhanced Veg.)", icon: Leaf },
  { key: "rgb", label: "True Color", icon: Camera },
  { key: "stress", label: "Stress Zones", icon: AlertTriangle },
];

const LAYER_CAPTIONS: Record<SatelliteMapLayer, string> = {
  ndvi: "Green areas indicate healthy vegetation. Red areas may indicate stress or poor crop growth.",
  ndwi: "Blue/dark areas indicate higher canopy moisture. Pale areas may indicate water stress.",
  evi: "Enhanced Vegetation Index — corrects for canopy background and atmospheric noise, useful in denser canopy.",
  rgb: "High-resolution natural optical view of the field, as seen by the satellite sensor.",
  stress: "Automated classification of the field into healthy, moderate, and stressed vegetation zones.",
};

const ZONE_TYPE_LABELS: Record<string, string> = {
  water_stress: "Water Stress",
  nutrient_pest_suspected: "Nutrient / Pest",
};

const HA_TO_ACRES = 2.47105;

// ── Satellite View Inner with Search Params ───────────────────────────────────

function SatelliteContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const farmParam = searchParams.get("farm");
  const { farms, mounted, loadError, retryLoad } = useFarmStore();

  const [selectedId, setSelectedId] = useState<string>(farms[0]?.id || "farm-1");
  const [activeLayer, setActiveLayer] = useState<SatelliteMapLayer>("ndvi");
  // null = follow the latest analysis; otherwise a pass date picked on the slider/chart.
  const [selectedPass, setSelectedPass] = useState<string | null>(null);

  useEffect(() => {
    if (farmParam && farms.some((f) => f.id === farmParam)) {
      setSelectedId(farmParam);
    }
  }, [farmParam, farms]);

  useEffect(() => {
    setSelectedPass(null);
  }, [selectedId]);

  const selectedFarm = farms.find((f) => f.id === selectedId) || farms[0];

  const {
    isRealFarm,
    status,
    observation,
    error: analysisError,
    retry: retryAnalysis,
    isRefreshing,
    refreshError,
    refresh: refreshSatellite,
  } = useFarmSatelliteAnalysis(selectedFarm?.id);

  const timeseries = useFarmSatelliteTimeseries(selectedFarm?.id);
  const environment = useFarmEnvironment(selectedFarm?.id);

  // Every known clear pass (nightly timeseries + the latest analysis, which
  // may be newer than tonight's job has recorded), oldest first.
  const passes = useMemo<SatellitePass[]>(() => {
    const byDate = new Map<string, SatellitePass>();
    for (const p of timeseries.points) byDate.set(p.image_date, { date: p.image_date, cloudPct: p.cloud_pct });
    if (observation) byDate.set(observation.image_date, { date: observation.image_date, cloudPct: observation.cloud_pct });
    return Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date));
  }, [timeseries.points, observation]);

  const mapDate = selectedPass ?? observation?.image_date;
  const mapPass = passes.find((p) => p.date === mapDate);

  const {
    layers,
    isLoading: layersLoading,
    error: layersError,
    retry: retryLayers,
  } = useFarmSatelliteLayers(selectedFarm?.id, mapDate);

  // Until the real (per-account) farm list has loaded client-side, `farms`
  // is still the SSR-safe placeholder — render nothing rather than flash it.
  if (!mounted) {
    return null;
  }

  if (loadError) {
    return <FarmsLoadError message={loadError} onRetry={() => retryLoad()} />;
  }

  if (!selectedFarm) {
    return (
      <div className="max-w-5xl mx-auto text-center py-16">
        <Satellite className="w-10 h-10 text-farm-muted mx-auto mb-3" />
        <p className="text-farm-dark font-semibold mb-1">No farms yet</p>
        <p className="text-farm-muted text-sm mb-5">Add your first farm to see satellite analysis.</p>
        <Link
          href="/farms"
          className="inline-flex items-center gap-2 bg-farm-green text-white px-4 py-2 rounded-xl text-sm font-semibold hover:bg-farm-green-dark transition-colors"
        >
          <Plus className="w-4 h-4" /> Add a Farm
        </Link>
      </div>
    );
  }

  const isReady = isRealFarm && !!observation;
  const displaySatellite = observation
    ? applyLiveSatellite(selectedFarm.satellite, observation)
    : selectedFarm.satellite;

  const activeLayerMeta = LAYERS.find((l) => l.key === activeLayer)!;

  // Provenance of whatever pass the map is showing (the map's corner badge).
  const mapSource: LiveSource | null = mapPass
    ? { source: "Sentinel-2", asOf: mapPass.date, cloudPct: mapPass.cloudPct }
    : null;

  // Mean shown in the caption follows the pass on the map when it's a
  // recorded timeseries pass; otherwise the latest analysis (or demo values).
  const mapPoint = timeseries.points.find((p) => p.image_date === mapDate);
  const activeLayerMean = isRealFarm
    ? mapPoint && mapDate !== observation?.image_date
      ? activeLayer === "ndwi"
        ? mapPoint.ndwi_mean
        : activeLayer === "evi"
        ? mapPoint.evi_mean
        : mapPoint.ndvi_mean
      : observation
      ? activeLayer === "ndwi"
        ? observation.ndwi.mean
        : activeLayer === "evi"
        ? observation.evi.mean
        : observation.ndvi.mean
      : null
    : activeLayer === "ndwi"
    ? displaySatellite.ndwi
    : activeLayer === "evi"
    ? null
    : displaySatellite.meanNdvi;

  // ── Panel inputs: live for real farms, demo for guests ──
  const seasonPoints: SeasonCurvePoint[] = isRealFarm
    ? timeseries.points.map((p) => ({
        key: p.image_date,
        label: formatPassDate(p.image_date),
        ndvi: p.ndvi_mean,
        benchmark: p.benchmark_ndvi,
        cloudPct: p.cloud_pct,
      }))
    : displaySatellite.history.map((p) => ({
        key: p.date,
        label: p.date,
        ndvi: p.ndvi,
        benchmark: p.benchmark,
        stage: p.stage,
      }));

  const stressZoneItems: PanelStressZone[] = isRealFarm
    ? (layers?.stress_zones ?? []).map((zone, idx) => ({
        id: zone.id,
        name: `Zone ${idx + 1}`,
        typeLabel: ZONE_TYPE_LABELS[zone.zone_type] ?? zone.zone_type,
        areaAcres: Math.round(zone.area_ha * HA_TO_ACRES * 100) / 100,
        action: zone.suggested_action,
      }))
    : displaySatellite.stressZones.map((zone) => ({
        id: zone.id,
        name: zone.name,
        typeLabel: zone.type,
        areaAcres: zone.areaAcres,
        description: zone.description,
        action: zone.actionRequired,
      }));

  return (
    <div className="max-w-5xl mx-auto space-y-5 pb-16">
      {/* ── Page Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.back()}
            aria-label="Go back"
            className="w-9 h-9 rounded-xl border border-farm-border-color bg-white flex items-center justify-center hover:border-farm-green text-farm-muted hover:text-farm-green transition-all flex-shrink-0"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <div>
            <h1 className="text-xl sm:text-2xl font-extrabold text-farm-dark flex items-center gap-2">
              <Satellite className="w-6 h-6 text-farm-green" />
              Satellite Analysis
            </h1>
            <p className="text-farm-muted text-xs sm:text-sm mt-0.5">
              Analyze crop health using multi-spectral satellite data (Sentinel-2)
            </p>
          </div>
        </div>

        {/* Farm Selector */}
        <div className="relative self-start sm:self-auto flex-shrink-0">
          <select
            aria-label="Select farm"
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            className="appearance-none bg-white border-2 border-farm-green/70 hover:border-farm-green text-farm-dark font-bold text-xs sm:text-sm pl-4 pr-10 py-2.5 rounded-2xl shadow-xs cursor-pointer focus:outline-none focus:ring-2 focus:ring-farm-green/20 transition-all"
          >
            {farms.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name} · {f.crop} · {f.district}
              </option>
            ))}
          </select>
          <ChevronDown className="w-4 h-4 text-farm-green absolute right-3.5 top-3 pointer-events-none" />
        </div>
      </div>

      {/* ── Layer Tabs ── */}
      <div className="flex flex-wrap gap-2">
        {LAYERS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setActiveLayer(key)}
            className={`px-3.5 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-1.5 border ${
              activeLayer === key
                ? "bg-farm-green text-white border-farm-green shadow-xs"
                : "bg-white text-farm-muted border-farm-border-color hover:border-farm-green hover:text-farm-green"
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>

      {/* ── Map Card with Overlay Badges ── */}
      <div className="relative rounded-3xl overflow-hidden border border-farm-border-color shadow-card bg-white">
        <MapView
          height="440px"
          flyToCenter={selectedFarm.polygonGeoJson ? undefined : selectedFarm.center}
          fitToPolygonGeoJson={selectedFarm.polygonGeoJson}
          showDrawControls={false}
          rasterTileUrl={layers?.layers[TILE_KEY_BY_LAYER[activeLayer]] ?? null}
          stressZones={
            activeLayer === "stress"
              ? layers?.stress_zones.map((zone) => ({
                  id: zone.id,
                  type: zone.zone_type,
                  areaHa: zone.area_ha,
                  geometry: zone.geometry_geojson,
                  action: zone.suggested_action,
                }))
              : undefined
          }
        />

        {/* Live raster layer loading indicator */}
        {layersLoading && (
          <div className="absolute top-16 left-1/2 -translate-x-1/2 z-10 bg-slate-900/85 backdrop-blur-sm text-white px-3 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-2 shadow-lg">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Loading satellite imagery…
          </div>
        )}
        {layersError && !layersLoading && (
          <div
            role="alert"
            className="absolute top-16 left-1/2 -translate-x-1/2 z-10 bg-red-600/90 backdrop-blur-sm text-white px-3 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-2 shadow-lg max-w-[90%]"
          >
            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
            <span className="truncate">Couldn&apos;t load imagery for this pass</span>
            <button onClick={() => retryLayers()} className="underline flex-shrink-0">
              Retry
            </button>
          </div>
        )}

        {/* Location badge (top-left) */}
        <div className="absolute top-4 left-4 z-10 bg-white/95 backdrop-blur-sm rounded-xl px-3.5 py-2 shadow-md flex items-center gap-2 max-w-[60%]">
          <MapPin className="w-4 h-4 text-farm-green flex-shrink-0" />
          <div className="min-w-0">
            <p className="text-xs font-bold text-farm-dark truncate">{selectedFarm.name}</p>
            <p className="text-[10px] text-farm-muted truncate">
              {selectedFarm.areaAcres} acres · {selectedFarm.district}, {selectedFarm.state}
            </p>
          </div>
        </div>

        {/* Pass / source badge (top-right) */}
        <div className="absolute top-4 right-4 z-10 bg-white/95 backdrop-blur-sm rounded-xl px-2 py-1.5 shadow-md">
          {isRealFarm ? (
            mapSource ? (
              <SourceBadge live={mapSource} />
            ) : (
              <span className="text-xs font-semibold text-farm-muted px-1">No imagery yet</span>
            )
          ) : (
            <span className="flex items-center gap-1.5 text-xs font-semibold text-farm-dark px-1">
              <Calendar className="w-3.5 h-3.5 text-farm-green flex-shrink-0" />
              Sentinel-2 · {displaySatellite.metadata.acquisitionDate}
              <SourceBadge demo />
            </span>
          )}
        </div>

        {/* Legend (bottom-right) */}
        {activeLayer !== "rgb" && (
          <div className="absolute bottom-4 right-4 z-10 bg-white/95 backdrop-blur-sm rounded-xl px-3 py-2.5 shadow-md space-y-1.5 text-[11px] font-semibold text-farm-dark">
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 flex-shrink-0" /> Healthy
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-400 flex-shrink-0" /> Moderate
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-red-500 flex-shrink-0" /> Stressed
            </div>
            {activeLayer === "stress" && layers && layers.stress_zones.length > 0 && (
              <>
                <div className="border-t border-farm-border-color my-1 pt-1.5 text-[10px] text-farm-muted font-bold uppercase tracking-wide">
                  Zone outlines
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-sky-500 flex-shrink-0" /> Water Stress
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-orange-500 flex-shrink-0" /> Nutrient/Pest
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* ── Pass-date slider (swaps the map layers) ── */}
      {isReady && mapDate && (
        <PassDateSlider
          passes={passes}
          value={mapDate}
          onChange={(date) => setSelectedPass(date === observation?.image_date ? null : date)}
          isLoading={layersLoading}
        />
      )}

      {/* Real stress-zone count + click hint (only when there's something to click) */}
      {activeLayer === "stress" && layers && layers.stress_zones.length > 0 && (
        <p className="text-xs text-farm-muted px-1 -mt-2">
          {layers.stress_zones.length} stress {layers.stress_zones.length === 1 ? "zone" : "zones"} detected
          on this pass — click an outlined area on the map for details.
        </p>
      )}

      {/* ── Caption line ── */}
      <div className="flex items-start gap-2 px-1">
        <span className="w-2 h-2 rounded-full bg-farm-green mt-1.5 flex-shrink-0" />
        <p className="text-xs text-farm-muted leading-relaxed">
          <strong className="text-farm-dark">
            {activeLayerMeta.label} Index
            {activeLayerMean !== null && ` (Mean: ${activeLayerMean.toFixed(2)})`}
          </strong>{" "}
          {LAYER_CAPTIONS[activeLayer]}
        </p>
      </div>

      {isRealFarm && !isReady ? (
        /* ── First analysis running / no clear image / error ── */
        <SatelliteStatusState status={status} error={analysisError} onRetry={retryAnalysis} />
      ) : (
        <>
          {/* ── Live Sentinel-2 status banner (real farms only) ── */}
          {isRealFarm && observation && (
            <div className="rounded-2xl border p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-emerald-50 border-emerald-200">
              <div className="flex flex-wrap items-center gap-2 text-xs text-emerald-900">
                <strong>Latest analysis</strong>
                <span>
                  Health score <strong>{observation.health_score.toFixed(0)}/100</strong>
                </span>
                {observation.is_fallback && (
                  <span className="text-amber-800">(best available — no clear scene this window)</span>
                )}
              </div>
              <button
                onClick={refreshSatellite}
                disabled={isRefreshing}
                className="self-start sm:self-auto px-3 py-1.5 bg-white border border-farm-border-color hover:border-farm-green text-xs font-semibold rounded-lg text-farm-dark hover:text-farm-green transition-all flex items-center gap-1.5 disabled:opacity-60 disabled:cursor-not-allowed flex-shrink-0"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin" : ""}`} />
                {isRefreshing ? "Analysing… ~30 s" : "Refresh from Sentinel-2"}
              </button>
            </div>
          )}
          {refreshError && <p className="text-xs text-red-600">{refreshError}</p>}

          {/* ── Comprehensive Satellite Analytics Panel ── */}
          <SatelliteAnalyticsPanel
            areaAcres={selectedFarm.areaAcres}
            satellite={displaySatellite}
            seasonCurve={{
              points: seasonPoints,
              emptyMessage: timeseries.isLoading
                ? "Loading season curve…"
                : "Your season curve builds up as the nightly job records each clear pass — the first points appear after tonight's run.",
              error: timeseries.isError ? "Couldn't load your season curve." : null,
              onRetry: () => timeseries.retry(),
              selectedKey: isRealFarm ? mapDate : undefined,
              onSelectPoint: isRealFarm
                ? (point) => setSelectedPass(point.key === observation?.image_date ? null : point.key)
                : undefined,
            }}
            stressZones={{
              items: stressZoneItems,
              isLoading: isRealFarm && layersLoading,
              error: layersError,
              onRetry: () => retryLayers(),
            }}
          />

          {/* ── Field environment (real farms only — guests have no demo equivalent) ── */}
          {isRealFarm && (
            <EnvironmentReportCard
              report={environment.report}
              isLoading={environment.isLoading}
              isError={environment.isError}
              onRetry={() => environment.retry()}
            />
          )}
        </>
      )}
    </div>
  );
}

export default function SatellitePage() {
  return (
    <AppLayout>
      <Suspense fallback={<div className="p-8 text-center text-farm-muted">Loading satellite analysis...</div>}>
        <SatelliteContent />
      </Suspense>
    </AppLayout>
  );
}
