"use client";

import React, { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import mapboxgl from "mapbox-gl";
import MapboxDraw from "@mapbox/mapbox-gl-draw";
import * as turf from "@turf/turf";
import "mapbox-gl/dist/mapbox-gl.css";
import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";
import { Layers, Trash2, Edit3, AlertCircle, X } from "lucide-react";

export interface MapViewStressZone {
  id: string;
  type: string; // "water_stress" | "nutrient_pest_suspected"
  areaHa: number;
  geometry: GeoJSON.Geometry;
  action: string;
}

export interface MapViewProps {
  onFieldDrawn?: (
    geojson: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon> | null,
    areaHectares: number
  ) => void;
  initialPolygon?: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon> | null;
  initialCenter?: [number, number]; // [lng, lat]
  initialZoom?: number;
  flyToCenter?: [number, number];  // fly to without re-mounting map
  /** Fit the view to this polygon's bounding box without re-mounting the map
   * (e.g. switching between farms on a read-only analysis view) -- shows the
   * whole registered field, not the surrounding area. Takes precedence over
   * flyToCenter whenever both are passed. */
  fitToPolygonGeoJson?: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon> | null;
  showDrawControls?: boolean;      // false = view-only map, no draw toolbar
  className?: string;
  height?: string | number;
  /** XYZ tile URL template (e.g. an Earth Engine getMapId() tile_fetcher
   * url_format) drawn as a raster overlay. Pass null/undefined to clear it. */
  rasterTileUrl?: string | null;
  /** Stress zone polygons drawn as a colored fill + outline, each with a
   * click popup showing its type/area/suggested action. */
  stressZones?: MapViewStressZone[];
}

function MapViewInner({
  onFieldDrawn,
  initialPolygon,
  initialCenter = [78.9629, 20.5937],
  initialZoom = 4.5,
  flyToCenter,
  fitToPolygonGeoJson,
  showDrawControls = true,
  className = "",
  height = "500px",
  rasterTileUrl,
  stressZones,
}: MapViewProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const drawRef = useRef<MapboxDraw | null>(null);

  const [areaHectares, setAreaHectares] = useState<number | null>(null);
  const [tokenMissing, setTokenMissing] = useState(false);
  const [activeMode, setActiveMode] = useState<string>("simple_select");
  const [locationError, setLocationError] = useState<string | null>(null);
  const geolocateRef = useRef<mapboxgl.GeolocateControl | null>(null);

  // Keep callbacks and initial values in refs so the map init effect only runs once
  const onFieldDrawnRef = useRef(onFieldDrawn);
  onFieldDrawnRef.current = onFieldDrawn;

  const initialPolygonRef = useRef(initialPolygon);
  const initialCenterRef = useRef(initialCenter);
  const initialZoomRef = useRef(initialZoom);
  const flyToCenterRef = useRef(flyToCenter);
  flyToCenterRef.current = flyToCenter;

  const [mapError, setMapError] = useState<string | null>(null);

  useEffect(() => {
    if (!mapContainerRef.current) return;

    const token = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";
    if (!token) {
      setTokenMissing(true);
      return;
    }
    setTokenMissing(false);
    mapboxgl.accessToken = token;

    let map: mapboxgl.Map;
    try {
      map = new mapboxgl.Map({
        container: mapContainerRef.current,
        style: "mapbox://styles/mapbox/satellite-streets-v12",
        center: flyToCenterRef.current ?? initialCenterRef.current,
        zoom: flyToCenterRef.current ? 14 : initialZoomRef.current,
        attributionControl: true,
      });
    } catch (err) {
      // Most commonly thrown when WebGL is disabled or unsupported
      console.error("Mapbox failed to initialise:", err);
      setMapError("The map could not start. Your browser may have WebGL / hardware acceleration turned off.");
      return;
    }

    mapRef.current = map;

    map.on("error", (e: { error?: { status?: number; message?: string } }) => {
      const status = e.error?.status;
      if (status === 401 || status === 403) {
        setMapError("Mapbox rejected the access token. Check NEXT_PUBLIC_MAPBOX_TOKEN (and its URL restrictions) in .env.local, then restart the dev server.");
      } else {
        console.warn("Mapbox error:", e.error?.message ?? e);
      }
    });

    // Add navigation control (zoom and rotation)
    map.addControl(new mapboxgl.NavigationControl(), "top-right");

    // Live GPS "find me" control -- only during farm registration (drawing a
    // new field boundary), where it helps the user locate themselves on the
    // map. Read-only/analysis views always show the farm's registered
    // location instead, never the device's current position.
    let geolocate: mapboxgl.GeolocateControl | null = null;
    if (showDrawControls) {
      geolocate = new mapboxgl.GeolocateControl({
        positionOptions: {
          enableHighAccuracy: true,
        },
        trackUserLocation: false,
        showUserHeading: false,
      });

      geolocateRef.current = geolocate;
      map.addControl(geolocate, "top-right");

      geolocate.on("error", (error: { code?: number; message?: string }) => {
        if (error && error.code === 1) {
          setLocationError("Location permission denied. Please allow location access in your browser to view your live GPS position.");
        } else if (error && error.code === 2) {
          setLocationError("GPS location is unavailable on this device.");
        } else if (error && error.message) {
          setLocationError(error.message);
        }
      });

      geolocate.on("geolocate", () => {
        setLocationError(null);
      });
    }

    // Initialize MapboxDraw — hide native control buttons since we use our own overlay buttons
    const draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: {}, // no native buttons; our custom "Draw Field Polygon" overlay handles it
      defaultMode: "simple_select",
    });

    drawRef.current = draw;
    map.addControl(draw, "top-right");

    const calculateAndUpdateArea = (feature?: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon>) => {
      let activeFeature = feature;
      if (!activeFeature) {
        const all = draw.getAll();
        if (all.features.length > 0) {
          activeFeature = all.features[all.features.length - 1] as GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon>;
        }
      }

      if (activeFeature && (activeFeature.geometry.type === "Polygon" || activeFeature.geometry.type === "MultiPolygon")) {
        try {
          const areaSqMeters = turf.area(activeFeature);
          const hectares = Number((areaSqMeters / 10000).toFixed(4));
          setAreaHectares(hectares);
          if (onFieldDrawnRef.current) {
            onFieldDrawnRef.current(activeFeature, hectares);
          }
        } catch (err) {
          console.error("Error computing area preview:", err);
        }
      } else {
        setAreaHectares(null);
        if (onFieldDrawnRef.current) {
          onFieldDrawnRef.current(null, 0);
        }
      }
    };

    // Ensure single polygon by removing any previous features when a new one is created
    const onDrawCreate = (e: { features: GeoJSON.Feature[] }) => {
      const all = draw.getAll();
      if (all.features.length > 1 && e.features && e.features[0]) {
        const latestId = e.features[0].id;
        all.features.forEach((feat) => {
          if (feat.id !== latestId) {
            draw.delete(feat.id as string);
          }
        });
      }
      calculateAndUpdateArea(e.features[0] as GeoJSON.Feature<GeoJSON.Polygon>);
    };

    const onDrawUpdate = (e: { features: GeoJSON.Feature[] }) => {
      if (e.features && e.features[0]) {
        calculateAndUpdateArea(e.features[0] as GeoJSON.Feature<GeoJSON.Polygon>);
      } else {
        calculateAndUpdateArea();
      }
    };

    const onDrawDelete = () => {
      setAreaHectares(null);
      if (onFieldDrawnRef.current) {
        onFieldDrawnRef.current(null, 0);
      }
    };

    const onDrawModeChange = (e: { mode: string }) => {
      setActiveMode(e.mode);
    };

    map.on("draw.create", onDrawCreate);
    map.on("draw.update", onDrawUpdate);
    map.on("draw.delete", onDrawDelete);
    map.on("draw.modechange", onDrawModeChange);

    map.on("load", () => {
      map.resize();
      // If initial polygon is provided, render and fit bounds
      if (initialPolygonRef.current) {
        draw.add(initialPolygonRef.current);
        calculateAndUpdateArea(initialPolygonRef.current);

        try {
          const bbox = turf.bbox(initialPolygonRef.current);
          map.fitBounds(
            [
              [bbox[0], bbox[1]],
              [bbox[2], bbox[3]],
            ],
            { padding: 50, maxZoom: 16 }
          );
        } catch {
          // fallback if bbox calculation fails
        }
      } else if (geolocate && !flyToCenterRef.current) {
        // Only auto-locate when the caller gave no polygon or target location —
        // otherwise GPS would pull the map away from the farm/village being shown
        if (typeof window !== "undefined" && "geolocation" in navigator) {
          try {
            geolocate.trigger();
          } catch (err) {
            console.warn("Geolocation trigger failed:", err);
          }
        } else {
          setLocationError("Geolocation is not supported by your browser/device.");
        }
      }
    });

    const resizeObserver = new ResizeObserver(() => {
      map.resize();
    });
    if (mapContainerRef.current) {
      resizeObserver.observe(mapContainerRef.current);
    }

    return () => {
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
      drawRef.current = null;
      geolocateRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // ← Empty deps: map initialises once and never re-mounts

  // Fly to a new location without re-initialising the map
  useEffect(() => {
    if (!flyToCenter || !mapRef.current) return;
    const map = mapRef.current;
    const fly = () => map.flyTo({ center: flyToCenter, zoom: 14, duration: 1800, essential: true });
    if (map.isStyleLoaded()) {
      fly();
    } else {
      map.once("load", fly);
    }
  }, [flyToCenter]);

  // Fit the view to a farm polygon's bounds -- e.g. switching the farm on a
  // read-only satellite analysis view -- without re-initialising the map.
  useEffect(() => {
    if (!fitToPolygonGeoJson || !mapRef.current) return;
    const map = mapRef.current;
    const fit = () => {
      try {
        if (drawRef.current) {
          drawRef.current.deleteAll();
          drawRef.current.add(fitToPolygonGeoJson);
        }
        const bbox = turf.bbox(fitToPolygonGeoJson);
        map.fitBounds(
          [
            [bbox[0], bbox[1]],
            [bbox[2], bbox[3]],
          ],
          { padding: 60, maxZoom: 17, duration: 1200 }
        );
      } catch (err) {
        console.warn("Failed to fit map to polygon bounds:", err);
      }
    };
    if (map.isStyleLoaded()) {
      fit();
    } else {
      map.once("load", fit);
    }
  }, [fitToPolygonGeoJson]);

  // Raster overlay (e.g. an Earth Engine NDVI/NDWI/stress tile layer) —
  // added/replaced without re-mounting the map whenever the tile URL changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const RASTER_SOURCE_ID = "ee-raster-source";
    const RASTER_LAYER_ID = "ee-raster-layer";

    const applyRaster = () => {
      if (map.getLayer(RASTER_LAYER_ID)) map.removeLayer(RASTER_LAYER_ID);
      if (map.getSource(RASTER_SOURCE_ID)) map.removeSource(RASTER_SOURCE_ID);
      if (!rasterTileUrl) return;

      map.addSource(RASTER_SOURCE_ID, {
        type: "raster",
        tiles: [rasterTileUrl],
        tileSize: 256,
      });
      map.addLayer({
        id: RASTER_LAYER_ID,
        type: "raster",
        source: RASTER_SOURCE_ID,
        paint: { "raster-opacity": 0.85 },
      });
    };

    if (map.isStyleLoaded()) {
      applyRaster();
    } else {
      map.once("load", applyRaster);
    }
  }, [rasterTileUrl]);

  // Stress zone polygons — colored by type, with a click popup. The click
  // handler is stable across re-renders (it only reads data off the clicked
  // feature itself, never a captured `stressZones` value), so it's safe to
  // attach once per layer without leaking duplicate listeners.
  const zoneClickHandlerRef = useRef<((e: mapboxgl.MapLayerMouseEvent) => void) | null>(null);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const ZONES_SOURCE_ID = "stress-zones-source";
    const ZONES_FILL_LAYER_ID = "stress-zones-fill";
    const ZONES_LINE_LAYER_ID = "stress-zones-outline";

    const applyZones = () => {
      if (zoneClickHandlerRef.current) {
        map.off("click", ZONES_FILL_LAYER_ID, zoneClickHandlerRef.current);
        zoneClickHandlerRef.current = null;
      }
      if (map.getLayer(ZONES_FILL_LAYER_ID)) map.removeLayer(ZONES_FILL_LAYER_ID);
      if (map.getLayer(ZONES_LINE_LAYER_ID)) map.removeLayer(ZONES_LINE_LAYER_ID);
      if (map.getSource(ZONES_SOURCE_ID)) map.removeSource(ZONES_SOURCE_ID);

      if (!stressZones || stressZones.length === 0) return;

      const featureCollection: GeoJSON.FeatureCollection = {
        type: "FeatureCollection",
        features: stressZones.map((zone) => ({
          type: "Feature",
          geometry: zone.geometry,
          properties: { id: zone.id, type: zone.type, areaHa: zone.areaHa, action: zone.action },
        })),
      };

      map.addSource(ZONES_SOURCE_ID, { type: "geojson", data: featureCollection });
      map.addLayer({
        id: ZONES_FILL_LAYER_ID,
        type: "fill",
        source: ZONES_SOURCE_ID,
        paint: {
          "fill-color": [
            "match", ["get", "type"],
            "water_stress", "#0ea5e9",
            "nutrient_pest_suspected", "#f97316",
            "#ef4444",
          ],
          "fill-opacity": 0.35,
        },
      });
      map.addLayer({
        id: ZONES_LINE_LAYER_ID,
        type: "line",
        source: ZONES_SOURCE_ID,
        paint: {
          "line-color": [
            "match", ["get", "type"],
            "water_stress", "#0284c7",
            "nutrient_pest_suspected", "#ea580c",
            "#dc2626",
          ],
          "line-width": 2,
        },
      });

      const handleClick = (e: mapboxgl.MapLayerMouseEvent) => {
        const feature = e.features?.[0];
        if (!feature) return;
        const props = feature.properties as { type: string; areaHa: number; action: string };
        const label = props.type === "water_stress" ? "Water Stress" : "Nutrient/Pest Suspected";
        new mapboxgl.Popup({ closeButton: true, maxWidth: "240px" })
          .setLngLat(e.lngLat)
          .setHTML(
            `<div style="font-size:12px;line-height:1.5">
              <strong>${label}</strong><br/>
              Area: ${Number(props.areaHa).toFixed(2)} ha<br/>
              <span style="color:#555">${props.action}</span>
            </div>`
          )
          .addTo(map);
      };
      zoneClickHandlerRef.current = handleClick;
      map.on("click", ZONES_FILL_LAYER_ID, handleClick);
      map.on("mouseenter", ZONES_FILL_LAYER_ID, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", ZONES_FILL_LAYER_ID, () => {
        map.getCanvas().style.cursor = "";
      });
    };

    if (map.isStyleLoaded()) {
      applyZones();
    } else {
      map.once("load", applyZones);
    }
  }, [stressZones]);

  const handleStartDraw = () => {
    if (drawRef.current) {
      // Clear any previous polygon before drawing new one
      drawRef.current.deleteAll();
      setAreaHectares(null);
      drawRef.current.changeMode("draw_polygon");
      setActiveMode("draw_polygon");
    }
  };

  const handleClear = () => {
    if (drawRef.current) {
      drawRef.current.deleteAll();
      setAreaHectares(null);
      if (onFieldDrawn) {
        onFieldDrawn(null, 0);
      }
    }
  };

  return (
    <div
      className={`relative w-full rounded-2xl overflow-hidden border border-farm-border-color shadow-card ${className}`}
      style={{ height }}
    >
      {/* Mapbox Canvas Container */}
      <div ref={mapContainerRef} className="w-full h-full" />

      {/* Missing Token Banner */}
      {tokenMissing && (
        <div className="absolute top-4 left-4 right-4 z-20 bg-amber-500/90 backdrop-blur-sm text-white px-4 py-2.5 rounded-xl text-xs flex items-center gap-2 shadow-lg max-w-lg">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>
            <strong>NEXT_PUBLIC_MAPBOX_TOKEN</strong> is not set. Add your public token in <code>.env.local</code> to render satellite tiles.
          </span>
        </div>
      )}

      {/* Map Load Error Banner */}
      {mapError && (
        <div className="absolute inset-0 z-20 bg-farm-gray flex items-center justify-center p-6">
          <div className="flex items-start gap-2 max-w-md text-sm text-farm-dark">
            <AlertCircle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
            <span>{mapError}</span>
          </div>
        </div>
      )}

      {/* Location Permission / Error Banner */}
      {locationError && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-30 bg-slate-900/90 text-white border border-amber-500/40 backdrop-blur-md px-4 py-2 rounded-xl text-xs flex items-center gap-2.5 shadow-xl max-w-md animate-in fade-in slide-in-from-top-2">
          <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0" />
          <span className="flex-1 leading-snug">{locationError}</span>
          <button
            type="button"
            onClick={() => setLocationError(null)}
            className="p-1 hover:bg-white/10 rounded-md text-white/70 hover:text-white transition-colors"
            title="Dismiss"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Quick Field Drawing Toolbar — only shown during farm registration */}
      {showDrawControls && (
        <div className="absolute top-4 left-4 z-10 flex items-center gap-2">
          <button
            type="button"
            onClick={handleStartDraw}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold shadow-card transition-all ${
              activeMode === "draw_polygon"
                ? "bg-farm-green text-white ring-2 ring-white"
                : "bg-white/95 text-farm-dark hover:bg-farm-green-light hover:text-farm-green"
            }`}
            title="Draw a new field boundary"
          >
            <Edit3 className="w-3.5 h-3.5" />
            {activeMode === "draw_polygon" ? "Click to plot points…" : "Draw Field Polygon"}
          </button>

          {areaHectares !== null && (
            <button
              type="button"
              onClick={handleClear}
              className="flex items-center gap-1.5 px-3 py-2 bg-white/95 text-red-600 hover:bg-red-50 rounded-xl text-xs font-semibold shadow-card transition-all"
              title="Delete current polygon"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Clear
            </button>
          )}
        </div>
      )}

      {/* Live Area Preview Badge — only shown during farm registration */}
      {showDrawControls && (
        areaHectares !== null ? (
          <div className="absolute bottom-5 left-4 z-10 bg-white/95 backdrop-blur-md border border-farm-border-color shadow-hero px-4 py-3 rounded-2xl flex items-center gap-3 animate-in fade-in slide-in-from-bottom-2">
            <div className="w-10 h-10 rounded-xl bg-farm-green-light flex items-center justify-center text-farm-green flex-shrink-0">
              <Layers className="w-5 h-5" />
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wider text-farm-muted font-semibold">
                Live Field Area
              </p>
              <div className="flex items-baseline gap-2">
                <span className="text-base font-bold text-farm-dark">
                  {areaHectares.toFixed(2)} ha
                </span>
                <span className="text-xs font-medium text-farm-muted">
                  ({(areaHectares * 2.47105).toFixed(2)} acres)
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="absolute bottom-5 left-4 z-10 bg-black/60 backdrop-blur-sm text-white px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 shadow-sm">
            <span className="w-2 h-2 rounded-full bg-farm-green animate-pulse" />
            Use polygon tool to trace your field boundary
          </div>
        )
      )}
    </div>
  );
}

// Dynamically load with ssr: false
export const MapView = dynamic(() => Promise.resolve(MapViewInner), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full min-h-[300px] bg-farm-gray rounded-2xl flex items-center justify-center text-farm-muted border border-farm-border-color">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-3 border-farm-green border-t-transparent rounded-full animate-spin" />
        <span className="text-sm font-medium">Loading satellite map...</span>
      </div>
    </div>
  ),
});

export default MapView;
