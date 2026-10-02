"use client";


import { useState } from "react";
import Link from "next/link";
import AppLayout from "@/components/AppLayout";
import FarmsLoadError from "@/components/FarmsLoadError";
import MapView from "@/components/map/MapView";
import { useFarmStore, Farm, FarmDraft } from "@/lib/stores/farmStore";
import {
  MapPin, ChevronRight, Plus, Leaf, X, CheckCircle2,
  Edit3, Calendar, Search, Navigation,
  Satellite, AlertCircle, Trash2
} from "lucide-react";

const CROPS = ["Rice", "Wheat", "Onion", "Sugarcane", "Potato"];

const STEPS = ["Farm Details", "Crop & Soil", "Draw on Map", "Done"];

type SoilLevel = Farm["soil"]["nitrogen"];

function polygonCentroid(
  polygon: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon>
): [number, number] | null {
  const ring =
    polygon.geometry.type === "Polygon" ? polygon.geometry.coordinates[0] : polygon.geometry.coordinates[0]?.[0];
  if (!ring || ring.length === 0) return null;
  const [sumLng, sumLat] = ring.reduce(([a, b], [lng, lat]) => [a + lng, b + lat], [0, 0]);
  return [sumLng / ring.length, sumLat / ring.length];
}

/** State and district of a point, via Mapbox reverse geocoding. Either can
 * come back null (no token, network error, or Mapbox has no match) -- the
 * farm is then saved without it rather than with a made-up default. */
async function reverseGeocodeRegion([lng, lat]: [number, number]): Promise<{ state: string | null; district: string | null }> {
  const token = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
  try {
    const res = await fetch(
      `https://api.mapbox.com/geocoding/v5/mapbox.places/${lng},${lat}.json?access_token=${token}&types=region,district`
    );
    const data = await res.json();
    const features: { place_type: string[]; text: string }[] = data.features ?? [];
    return {
      state: features.find((f) => f.place_type.includes("region"))?.text ?? null,
      district: features.find((f) => f.place_type.includes("district"))?.text ?? null,
    };
  } catch {
    return { state: null, district: null };
  }
}

const blankForm = {
  name: "", address: "", crop: "", plantingDate: "", area: "",
  hasSoilReport: false,
  soil: { ph: "", nitrogen: "Medium", phosphorus: "Medium", potassium: "Medium", organicMatter: "" },
};

// ── Registration Modal ────────────────────────────────────────────────────────

function RegisterFarmModal({
  onClose,
  onSave,
}: {
  onClose: () => void;
  onSave: (draft: FarmDraft, areaAcres: number) => Promise<void>;
}) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState(blankForm);
  const [drawnAreaHa, setDrawnAreaHa] = useState<number | null>(null);
  const [drawnPolygon, setDrawnPolygon] = useState<GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon> | null>(null);
  const [geocodedCenter, setGeocodedCenter] = useState<[number, number] | undefined>();
  const [searchLocationQuery, setSearchLocationQuery] = useState("");
  const [searchSearching, setSearchSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [searchFeedback, setSearchFeedback] = useState<string | null>(null);

  const today = new Date().toISOString().split("T")[0];

  function set(field: string, value: string | boolean) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function setSoil(field: string, value: string) {
    setForm((prev) => ({ ...prev, soil: { ...prev.soil, [field]: value } }));
  }

  async function searchLocation(query: string) {
    if (!query.trim()) return;
    setSearchSearching(true);
    setSearchFeedback(null);
    const token = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
    try {
      const res = await fetch(
        `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(
          query
        )}.json?access_token=${token}&country=in&limit=1`
      );
      const data = await res.json();
      if (data.features && data.features.length > 0) {
        const [lng, lat] = data.features[0].center;
        const placeName = data.features[0].place_name;
        setGeocodedCenter([lng, lat]);
        setSearchFeedback(`Jumped to: ${placeName}`);
      } else {
        setSearchFeedback("Location not found. Try adding district or state.");
      }
    } catch {
      setSearchFeedback("Search unavailable. Please use GPS button.");
    } finally {
      setSearchSearching(false);
    }
  }

  function useCurrentGpsLocation() {
    if (!navigator.geolocation) {
      setSearchFeedback("Geolocation is not supported by your browser.");
      return;
    }
    setSearchFeedback("Fetching current GPS location...");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lng = pos.coords.longitude;
        const lat = pos.coords.latitude;
        setGeocodedCenter([lng, lat]);
        setSearchFeedback(`GPS located at: ${lat.toFixed(4)}, ${lng.toFixed(4)}`);
      },
      (err) => {
        setSearchFeedback(`GPS error: ${err.message}. Enter village name manually.`);
      },
      { enableHighAccuracy: true, timeout: 8000 }
    );
  }

  function handleFieldDrawn(
    polygon: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon> | null,
    areaHa: number
  ) {
    if (areaHa > 0 && polygon) {
      setDrawnAreaHa(areaHa);
      setDrawnPolygon(polygon);
      setForm((prev) => ({ ...prev, area: (areaHa * 2.47105).toFixed(2) }));
    } else {
      setDrawnAreaHa(null);
      setDrawnPolygon(null);
    }
  }

  async function handleSave() {
    const acres = parseFloat(form.area) || 2.5;

    // State/district come from the farm's actual location on the map, not
    // a hard-coded default -- mandi prices are looked up by them.
    const center = (drawnPolygon && polygonCentroid(drawnPolygon)) || geocodedCenter || [73.8567, 18.5204];
    setSaving(true);
    const region = await reverseGeocodeRegion(center);

    const draft: FarmDraft = {
      name: form.name.trim() || "My New Farm",
      address: form.address.trim(),
      district: region.district ?? "",
      state: region.state ?? "",
      crop: form.crop || "Rice",
      variety: "",
      plantingDate: form.plantingDate || today,
      center,
      polygonGeoJson: drawnPolygon,
      soilOverride: form.hasSoilReport
        ? {
            ph: parseFloat(form.soil.ph) || undefined,
            nitrogen: form.soil.nitrogen as SoilLevel,
            phosphorus: form.soil.phosphorus as SoilLevel,
            potassium: form.soil.potassium as SoilLevel,
            organicMatter: form.soil.organicMatter ? `${form.soil.organicMatter}%` : undefined,
          }
        : undefined,
    };

    setSaving(true);
    setSaveError(null);
    try {
      await onSave(draft, acres);
      return true;
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save this farm. Please try again.");
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function advanceFromStep0() {
    setStep(1);
    if (form.address.trim()) {
      searchLocation(form.address);
    }
  }

  const canNext0 = form.name.trim() && form.address.trim();
  const canNext1 = form.crop.trim() && form.plantingDate.trim();
  const canNext2 = drawnAreaHa !== null;

  // ── Step 2 Fullscreen Boundary Drawing with Village Search ──
  if (step === 2) {
    return (
      <div className="fixed inset-0 z-50 bg-farm-dark flex flex-col">
        {/* Top bar with location search and GPS button */}
        <div className="px-4 py-3 bg-farm-dark border-b border-white/10 flex flex-wrap items-center justify-between gap-3 flex-shrink-0">
          <div className="flex items-center gap-3">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
            <div>
              <p className="text-white font-semibold text-sm">Draw Farm Boundary</p>
              <p className="text-white/60 text-xs">{form.name} · Crop: {form.crop}</p>
            </div>
          </div>

          {/* Search Village & GPS button */}
          <div className="flex items-center gap-2 flex-1 max-w-lg mx-2">
            <div className="relative flex-1">
              <input
                type="text"
                value={searchLocationQuery}
                onChange={(e) => setSearchLocationQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && searchLocation(searchLocationQuery)}
                placeholder="Search village, town or taluka (e.g. Shirwal, Baramati)..."
                className="w-full bg-white/10 text-white placeholder-white/50 text-xs px-3 py-2 rounded-xl border border-white/20 focus:outline-none focus:border-farm-green pr-8"
              />
              <button
                type="button"
                onClick={() => searchLocation(searchLocationQuery)}
                disabled={searchSearching}
                className="absolute right-2 top-2 text-white/60 hover:text-white disabled:opacity-40 disabled:cursor-wait"
                title={searchSearching ? "Searching…" : "Search location"}
              >
                <Search className="w-3.5 h-3.5" />
              </button>
            </div>

            <button
              type="button"
              onClick={useCurrentGpsLocation}
              className="px-3 py-2 bg-white/15 hover:bg-white/25 border border-white/20 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all flex-shrink-0"
              title="Locate via device GPS"
            >
              <Navigation className="w-3.5 h-3.5 text-emerald-400" />
              <span>Current GPS</span>
            </button>
          </div>

          <div className="flex items-center gap-3">
            {drawnAreaHa !== null && (
              <div className="bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-xs font-semibold px-3 py-1.5 rounded-full flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5" />
                {drawnAreaHa.toFixed(2)} ha ({(drawnAreaHa * 2.47105).toFixed(2)} acres)
              </div>
            )}
            <button
              onClick={() => setStep(1)}
              className="px-3 py-1.5 text-xs font-medium text-white/70 hover:text-white border border-white/20 rounded-lg transition-colors"
            >
              ← Back
            </button>
            <button
              onClick={() => setStep(3)}
              disabled={!canNext2}
              className="px-4 py-1.5 text-xs font-semibold bg-farm-green text-white rounded-lg hover:bg-farm-green-dark transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {canNext2 ? "Confirm & Continue →" : "Draw boundary to continue"}
            </button>
          </div>
        </div>

        {/* Search Feedback Banner */}
        {searchFeedback && (
          <div className="bg-emerald-950/80 text-emerald-300 px-4 py-1 text-xs text-center border-b border-white/10 flex items-center justify-center gap-2">
            <span>{searchFeedback}</span>
            <button onClick={() => setSearchFeedback(null)} className="text-white/60 hover:text-white">
              <X className="w-3 h-3" />
            </button>
          </div>
        )}

        {/* Map */}
        <div className="flex-1 relative">
          <MapView height="100%" onFieldDrawn={handleFieldDrawn} flyToCenter={geocodedCenter} />
          {!drawnAreaHa && (
            <div className="absolute bottom-6 left-1/2 -translate-x-1/2 bg-black/75 text-white text-xs font-medium px-4 py-2 rounded-xl flex items-center gap-2 shadow-lg backdrop-blur-sm">
              <Edit3 className="w-3.5 h-3.5 text-emerald-400" />
              <span>Click &quot;Draw Field Polygon&quot; button on the map to outline your field boundary</span>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-white rounded-3xl shadow-hero border border-farm-border-color w-full max-w-xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="bg-gradient-to-r from-farm-green to-farm-green-dark p-6 text-white">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs font-semibold tracking-wider uppercase text-emerald-200">
                Farm Registration
              </span>
            </div>
            <button
              onClick={onClose}
              className="text-white/70 hover:text-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <h2 className="text-xl font-bold">Register a New Farm</h2>
          <p className="text-emerald-100 text-xs mt-1">
            Draw your field polygon and record crop & soil information for satellite tracking.
          </p>

          {/* Stepper */}
          <div className="flex items-center gap-2 mt-5">
            {STEPS.map((s, i) => (
              <div key={s} className="flex items-center gap-2 flex-1">
                <div
                  className={`h-1.5 rounded-full flex-1 transition-all ${
                    i <= step ? "bg-white" : "bg-white/20"
                  }`}
                />
              </div>
            ))}
          </div>
        </div>

        {/* Body */}
        <div className="p-6">
          {/* Step 0: Name & Address */}
          {step === 0 && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-farm-dark mb-1">
                  Farm / Field Name *
                </label>
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={(e) => set("name", e.target.value)}
                  placeholder="e.g. Riverfront Sugar Plot, North Wheat Block"
                  className="w-full px-3.5 py-2.5 border border-farm-border-color rounded-xl text-sm focus:outline-none focus:border-farm-green"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-farm-dark mb-1">
                  Farm Location / Village Address *
                </label>
                <input
                  type="text"
                  required
                  value={form.address}
                  onChange={(e) => set("address", e.target.value)}
                  placeholder="e.g. Shirwal Village, Satara, Maharashtra"
                  className="w-full px-3.5 py-2.5 border border-farm-border-color rounded-xl text-sm focus:outline-none focus:border-farm-green"
                />
                <p className="text-[11px] text-farm-muted mt-1">
                  We will center the satellite map on this location for boundary drawing.
                </p>
              </div>

              <div className="flex justify-end pt-4">
                <button
                  type="button"
                  disabled={!canNext0}
                  onClick={advanceFromStep0}
                  className="px-5 py-2.5 bg-farm-green text-white rounded-xl text-sm font-semibold hover:bg-farm-green-dark transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                >
                  Next: Crop & Soil →
                </button>
              </div>
            </div>
          )}

          {/* Step 1: Crop & Soil */}
          {step === 1 && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-farm-dark mb-1">
                    Planted Crop *
                  </label>
                  <select
                    value={form.crop}
                    onChange={(e) => set("crop", e.target.value)}
                    className="w-full px-3 py-2.5 border border-farm-border-color rounded-xl text-sm focus:outline-none focus:border-farm-green"
                  >
                    <option value="">Select crop</option>
                    {CROPS.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-bold text-farm-dark mb-1">
                    Sowing / Planting Date *
                  </label>
                  <input
                    type="date"
                    max={today}
                    value={form.plantingDate}
                    onChange={(e) => set("plantingDate", e.target.value)}
                    className="w-full px-3 py-2 border border-farm-border-color rounded-xl text-sm focus:outline-none focus:border-farm-green"
                  />
                </div>
              </div>

              {/* Soil Report checkbox */}
              <div className="p-3.5 bg-farm-gray rounded-xl border border-farm-border-color">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.hasSoilReport}
                    onChange={(e) => set("hasSoilReport", e.target.checked)}
                    className="rounded text-farm-green focus:ring-farm-green"
                  />
                  <span className="text-xs font-bold text-farm-dark">
                    I have a Soil Health Card / Lab Test Report
                  </span>
                </label>

                {form.hasSoilReport && (
                  <div className="grid grid-cols-3 gap-2 mt-3 pt-3 border-t border-farm-border-color">
                    <div>
                      <label className="text-[10px] font-semibold text-farm-muted block mb-0.5">
                        pH Level
                      </label>
                      <input
                        type="number"
                        step="0.1"
                        placeholder="e.g. 6.8"
                        value={form.soil.ph}
                        onChange={(e) => setSoil("ph", e.target.value)}
                        className="w-full px-2.5 py-1.5 border border-farm-border-color rounded-lg text-xs bg-white"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] font-semibold text-farm-muted block mb-0.5">
                        Nitrogen (N)
                      </label>
                      <select
                        value={form.soil.nitrogen}
                        onChange={(e) => setSoil("nitrogen", e.target.value)}
                        className="w-full px-2 py-1.5 border border-farm-border-color rounded-lg text-xs bg-white"
                      >
                        <option value="Low">Low</option>
                        <option value="Medium">Medium</option>
                        <option value="High">High</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-[10px] font-semibold text-farm-muted block mb-0.5">
                        Phosphorus (P)
                      </label>
                      <select
                        value={form.soil.phosphorus}
                        onChange={(e) => setSoil("phosphorus", e.target.value)}
                        className="w-full px-2 py-1.5 border border-farm-border-color rounded-lg text-xs bg-white"
                      >
                        <option value="Low">Low</option>
                        <option value="Medium">Medium</option>
                        <option value="High">High</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-[10px] font-semibold text-farm-muted block mb-0.5">
                        Potassium (K)
                      </label>
                      <select
                        value={form.soil.potassium}
                        onChange={(e) => setSoil("potassium", e.target.value)}
                        className="w-full px-2 py-1.5 border border-farm-border-color rounded-lg text-xs bg-white"
                      >
                        <option value="Low">Low</option>
                        <option value="Medium">Medium</option>
                        <option value="High">High</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-[10px] font-semibold text-farm-muted block mb-0.5">
                        Organic Matter (%)
                      </label>
                      <input
                        type="number"
                        step="0.1"
                        placeholder="e.g. 1.8"
                        value={form.soil.organicMatter}
                        onChange={(e) => setSoil("organicMatter", e.target.value)}
                        className="w-full px-2.5 py-1.5 border border-farm-border-color rounded-lg text-xs bg-white"
                      />
                    </div>
                  </div>
                )}
              </div>

              <div className="flex justify-between pt-4">
                <button
                  type="button"
                  onClick={() => setStep(0)}
                  className="px-4 py-2 border border-farm-border-color rounded-xl text-xs font-semibold text-farm-muted hover:text-farm-dark"
                >
                  ← Back
                </button>
                <button
                  type="button"
                  disabled={!canNext1}
                  onClick={() => setStep(2)}
                  className="px-5 py-2.5 bg-farm-green text-white rounded-xl text-sm font-semibold hover:bg-farm-green-dark transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                >
                  Next: Draw on Map →
                </button>
              </div>
            </div>
          )}

          {/* Step 3: Review & Done */}
          {step === 3 && (
            <div className="space-y-4">
              <div className="p-4 bg-emerald-50 rounded-2xl border border-emerald-200 space-y-2">
                <div className="flex items-center gap-2 text-emerald-800 font-bold text-sm">
                  <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                  <span>Ready to Save Farm</span>
                </div>
                <div className="text-xs text-emerald-900 space-y-1">
                  <p><strong>Name:</strong> {form.name}</p>
                  <p><strong>Location:</strong> {form.address}</p>
                  <p><strong>Crop:</strong> {form.crop} (Planted {form.plantingDate})</p>
                  <p><strong>Area:</strong> {form.area} acres (from satellite polygon)</p>
                </div>
              </div>

              {saveError && (
                <div className="flex items-start gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                  <span>{saveError}</span>
                </div>
              )}

              <div className="flex justify-between pt-4">
                <button
                  type="button"
                  onClick={() => setStep(2)}
                  disabled={saving}
                  className="px-4 py-2 border border-farm-border-color rounded-xl text-xs font-semibold text-farm-muted hover:text-farm-dark disabled:opacity-40"
                >
                  ← Edit Boundary
                </button>
                <button
                  type="button"
                  disabled={saving}
                  onClick={async () => {
                    const ok = await handleSave();
                    if (ok) onClose();
                  }}
                  className="px-6 py-2.5 bg-farm-green text-white rounded-xl text-sm font-semibold hover:bg-farm-green-dark shadow-md transition-all flex items-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <Plus className="w-4 h-4" /> {saving ? "Saving..." : "Save & Activate Farm"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Delete Confirmation Modal ─────────────────────────────────────────────────

function ConfirmDeleteModal({
  farm,
  onCancel,
  onConfirm,
}: {
  farm: Farm;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-hero border border-farm-border-color w-full max-w-sm overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div className="p-6 space-y-4">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-full bg-red-50 flex items-center justify-center flex-shrink-0">
              <Trash2 className="w-5 h-5 text-red-600" />
            </div>
            <div>
              <h3 className="font-bold text-farm-dark text-sm">Delete this farm?</h3>
              <p className="text-xs text-farm-muted mt-1">
                <strong>{farm.name}</strong> and all of its satellite, soil, and weather data will be
                permanently removed. This can't be undone.
              </p>
            </div>
          </div>

          {error && (
            <div className="flex items-start gap-2 text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              <AlertCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onCancel}
              disabled={deleting}
              className="px-4 py-2 border border-farm-border-color rounded-xl text-xs font-semibold text-farm-muted hover:text-farm-dark disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={deleting}
              onClick={async () => {
                setDeleting(true);
                setError(null);
                try {
                  await onConfirm();
                } catch (err) {
                  setError(err instanceof Error ? err.message : "Could not delete this farm. Please try again.");
                  setDeleting(false);
                }
              }}
              className="px-4 py-2 bg-red-600 text-white rounded-xl text-xs font-semibold hover:bg-red-700 transition-all flex items-center gap-1.5 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <Trash2 className="w-3.5 h-3.5" /> {deleting ? "Deleting..." : "Delete Farm"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main Farms View ───────────────────────────────────────────────────────────

export default function FarmsPage() {
  const { farms, addFarm, removeFarm, mounted, loadError, retryLoad } = useFarmStore();
  const [showModal, setShowModal] = useState(false);
  const [farmToDelete, setFarmToDelete] = useState<Farm | null>(null);

  // Until the real (per-account) farm list has loaded client-side, `farms`
  // is still the SSR-safe placeholder — render an empty shell rather than
  // flash it (keep the sidebar so the layout doesn't jump).
  if (!mounted) {
    return <AppLayout>{null}</AppLayout>;
  }

  if (loadError) {
    return (
      <AppLayout>
        <FarmsLoadError message={loadError} onRetry={() => retryLoad()} />
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      {showModal && (
        <RegisterFarmModal
          onClose={() => setShowModal(false)}
          onSave={async (draft, areaAcres) => {
            await addFarm(draft, areaAcres);
          }}
        />
      )}

      {farmToDelete && (
        <ConfirmDeleteModal
          farm={farmToDelete}
          onCancel={() => setFarmToDelete(null)}
          onConfirm={async () => {
            await removeFarm(farmToDelete.id);
            setFarmToDelete(null);
          }}
        />
      )}

      <div className="max-w-6xl mx-auto space-y-8 pb-12">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold text-farm-dark">My Farms</h1>
            <p className="text-farm-muted text-sm mt-0.5">
              {farms.length} managed farm{farms.length !== 1 ? "s" : ""} · Each farm has distinct satellite & weather intelligence
            </p>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="self-start sm:self-auto flex items-center gap-2 bg-farm-green text-white px-4 py-2.5 rounded-xl text-sm font-semibold hover:bg-farm-green-dark transition-all shadow-card"
          >
            <Plus className="w-4 h-4" /> Register New Farm
          </button>
        </div>

        {/* Farm Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {farms.map((farm) => (
            <div
              key={farm.id}
              className="bg-white rounded-2xl border border-farm-border-color hover:shadow-card hover:border-farm-green transition-all duration-200 overflow-hidden flex flex-col"
            >
              {/* Card top */}
              <div className="bg-gradient-to-br from-farm-green to-farm-green-dark p-5 text-white">
                <div className="flex items-start justify-between">
                  <div>
                    <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-white/20 text-white inline-block mb-1">
                      {farm.crop}
                    </span>
                    <h2 className="font-bold text-white text-lg leading-tight">{farm.name}</h2>
                    <p className="text-white/70 text-xs flex items-center gap-1 mt-1">
                      <MapPin className="w-3 h-3" /> {farm.address}
                    </p>
                  </div>
                  <span className="text-xs font-bold px-2 py-1 rounded-full bg-white/15 text-white border border-white/20">
                    {farm.areaAcres} ac
                  </span>
                </div>
              </div>

              {/* Card body */}
              <div className="p-5 flex-1 flex flex-col gap-3">
                {/* Crop details */}
                <div className="flex items-center justify-between text-xs text-farm-muted">
                  <span className="flex items-center gap-1 font-semibold text-farm-dark">
                    <Leaf className="w-3.5 h-3.5 text-farm-green" /> {farm.crop}
                    {farm.variety ? ` (${farm.variety})` : ""}
                  </span>
                  <span className="flex items-center gap-1">
                    <Calendar className="w-3.5 h-3.5" /> Planted {farm.plantingDate}
                  </span>
                </div>

                {/* Action CTA */}
                <div className="flex items-center justify-between pt-3 mt-auto border-t border-farm-border-color">
                  <Link
                    href={`/satellite?farm=${farm.id}`}
                    className="text-xs text-farm-green font-bold flex items-center gap-1 hover:gap-2 transition-all"
                  >
                    <Satellite className="w-3.5 h-3.5" /> Inspect Satellite & NDVI <ChevronRight className="w-3 h-3" />
                  </Link>
                  <button
                    type="button"
                    onClick={() => setFarmToDelete(farm)}
                    title="Delete farm"
                    className="text-farm-muted hover:text-red-600 p-1.5 rounded-lg hover:bg-red-50 transition-colors flex-shrink-0"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          ))}

          {/* Add farm card */}
          <button
            onClick={() => setShowModal(true)}
            className="min-h-[260px] rounded-2xl border-2 border-dashed border-farm-border-color hover:border-farm-green hover:bg-farm-green-light/40 transition-all group flex flex-col items-center justify-center gap-3 text-farm-muted hover:text-farm-green p-6"
          >
            <div className="w-12 h-12 rounded-2xl bg-farm-green-light flex items-center justify-center text-farm-green group-hover:scale-110 transition-transform">
              <Plus className="w-6 h-6" />
            </div>
            <div className="text-center">
              <p className="text-sm font-bold text-farm-dark">Register New Farm</p>
              <p className="text-xs text-farm-muted mt-0.5">Plot boundary with village search & GPS</p>
            </div>
          </button>
        </div>
      </div>
    </AppLayout>
  );
}
