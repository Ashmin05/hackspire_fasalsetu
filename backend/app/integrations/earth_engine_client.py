"""Google Earth Engine client — initialises once at app startup and exposes
a small async-safe wrapper around EE's blocking Python SDK.

EE's Python SDK is synchronous: every call that touches the network (most
importantly `.getInfo()`) blocks the calling thread. Every such call in this
module goes through `_get_info`, which runs it in a worker thread with a
timeout, so a slow or unreachable Earth Engine call can never freeze the
FastAPI event loop for every other request.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import ee
from google.auth import default as google_auth_default

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 20.0
FIELD_ANALYSIS_TIMEOUT_SECONDS = 60.0  # reduceRegion over a whole collection is slower than a count
TIMESERIES_TIMEOUT_SECONDS = 120.0  # up to ~120 days of scenes, two reduceRegions each
MAP_LAYERS_TIMEOUT_SECONDS = 60.0  # 5 getMapId calls + one stress-zone vectorization getInfo

# Per-field Sentinel-2 analysis (see EarthEngineClient.analyze_field).
FIELD_ANALYSIS_WINDOW_DAYS = 45
ACCEPTABLE_CLOUD_PCT = 20.0
REFLECTANCE_SCALE = 0.0001  # Sentinel-2 SR bands are Int16, scaled by 1e-4 to reflectance
REGION_REDUCE_SCALE_M = 10  # native resolution of the visible/NIR S2 bands
NDVI_HEALTHY_THRESHOLD = 0.6
NDVI_STRESSED_THRESHOLD = 0.3
# SCL (Scene Classification Layer) classes to mask out: cloud shadow (3),
# cloud medium probability (8), cloud high probability (9), thin cirrus (10).
SCL_CLOUD_SHADOW_CLASSES = [3, 8, 9, 10]

# Map tile visualization (EarthEngineClient.get_field_map_layers).
TRUE_COLOR_VIS = {"min": 0, "max": 0.3}
NDVI_VIS = {"min": 0, "max": 0.9, "palette": ["red", "yellow", "green"]}
NDWI_VIS = {"min": -0.5, "max": 0.5, "palette": ["8B4513", "white", "0000FF"]}  # brown (dry) -> blue (wet)
EVI_VIS = {"min": 0, "max": 1, "palette": ["red", "yellow", "green"]}
STRESS_CLASS_VIS = {"min": 0, "max": 2, "palette": ["red", "orange", "green"]}  # 0=stressed 1=moderate 2=healthy

# Stress-zone vectorization: a pixel is "stressed" if its NDVI is more than
# this many standard deviations below the field's own mean NDVI (not a fixed
# absolute threshold, since "stressed relative to this field" is what
# matters for anomaly detection).
STRESS_ZONE_STD_DEV_THRESHOLD = 1.0
STRESS_ZONE_MIN_AREA_M2 = 200.0
# Cached tile URLs are treated as stale after this long (see SatelliteService)
# -- not because Earth Engine's own map tokens are known to expire this fast,
# but as a conservative, simple cache-invalidation policy.
MAP_LAYERS_CACHE_HOURS = 12

# Farm environment report (EarthEngineClient.get_environment_dynamics /
# get_soil_properties). Timeout is generous -- this bundles several
# independent Earth Engine round trips (rainfall, temperature, soil
# moisture), each of which can be slow on a cache-cold call.
ENVIRONMENT_TIMEOUT_SECONDS = 45.0

# reduceRegion's `scale` is a *sampling* parameter, not a claim about the
# source data's real resolution -- passing a dataset's true native scale
# (e.g. CHIRPS's ~5.5km or SMAP's ~11km pixel) over a farm polygon smaller
# than that one pixel makes EE's grid-alignment sampling miss the region
# entirely and silently return null instead of the enclosing pixel's value
# (confirmed empirically: scale=5566 on a ~1ha polygon -> None, scale=30 on
# the same polygon -> the real value). A small scale here just means EE
# resamples the coarse raster down before reducing; it does not change
# which pixel's value comes back for a region this small. The dataset's
# real native resolution is what's surfaced to the UI via the separate
# *_RESOLUTION_LABEL constants below -- these two concerns are independent.
SMALL_FIELD_REDUCE_SCALE_M = 30

CHIRPS_COLLECTION_ID = "UCSB-CHG/CHIRPS/DAILY"
CHIRPS_RESOLUTION_LABEL = "~5.5 km field-region (CHIRPS daily)"
# CHIRPS's "final" product lags real time by several weeks -- a naive
# "last 7 days from today" window can come back empty. Windows are anchored
# to the latest date actually present in the collection instead (see
# _get_rainfall_summary), not to today.
RAINFALL_SINCE_SOWING_CAP_DAYS = 365  # bounds the query even for an old/perennial field

MODIS_LST_COLLECTION_ID = "MODIS/061/MOD11A2"
MODIS_LST_RESOLUTION_LABEL = "1 km (MODIS 8-day composite)"
MODIS_LST_SCALE_FACTOR = 0.02  # per the dataset's documented band scale
KELVIN_TO_CELSIUS_OFFSET = 273.15
HOT_PERIOD_THRESHOLD_C = 35.0
LST_LOOKBACK_DAYS = 60

# NASA/SMAP/SPL4SMGP/007 is EE's flagged-deprecated SMAP L4 collection
# (superseded by .../008), but it's what was asked for. Its production
# stopped around mid-2025, so "latest" can be materially stale -- always
# surfaced honestly via the returned `as_of` date rather than assumed fresh.
SMAP_COLLECTION_ID = "NASA/SMAP/SPL4SMGP/007"
SMAP_RESOLUTION_LABEL = "~9-11 km regional (SMAP L4)"

# OpenLandMap/LandGIS static soil layers (~2017 global compilation) -- no
# acquisition date, fetched once per farm and reused (see SatelliteService
# .environment_report). Values are 250 m raster pixels; a farm's polygon is
# usually smaller than one pixel, so `first()` (not `mean()`) is used to
# read them -- `mean()` would silently average the *class numbers* of the
# categorical texture band into a meaningless non-integer.
OPENLANDMAP_PH_ASSET_ID = "OpenLandMap/SOL/SOL_PH-H2O_USDA-4C1A2A_M/v02"
OPENLANDMAP_ORGANIC_CARBON_ASSET_ID = "OpenLandMap/SOL/SOL_ORGANIC-CARBON_USDA-6A1C_M/v02"
OPENLANDMAP_TEXTURE_ASSET_ID = "OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-TT_M/v02"
OPENLANDMAP_RESOLUTION_LABEL = "250 m field-level (OpenLandMap, static ~2017 compilation)"
OPENLANDMAP_PH_SCALE_FACTOR = 0.1  # band stores pH x10 (integer-encoded)
# OpenLandMap doesn't expose its organic-carbon scale factor via getInfo();
# this was determined empirically (raw pixel value x5 lands in the
# plausible g/kg range for real agricultural soil; /5 does not -- see
# get_soil_properties). Flagged here in case an authoritative source
# surfaces a different documented factor later.
OPENLANDMAP_ORGANIC_CARBON_SCALE_FACTOR = 5.0
USDA_TEXTURE_CLASS_NAMES = {
    1: "Clay", 2: "Silty Clay", 3: "Sandy Clay", 4: "Clay Loam",
    5: "Silty Clay Loam", 6: "Sandy Clay Loam", 7: "Loam", 8: "Silt Loam",
    9: "Sandy Loam", 10: "Silt", 11: "Loamy Sand", 12: "Sand",
}

# Roughly central India — used only by the health check to count recent
# Sentinel-2 passes; the location itself has no other significance.
HEALTH_CHECK_LON = 78.9629
HEALTH_CHECK_LAT = 20.5937

# Scopes Earth Engine needs from Application Default Credentials. Only used
# on the ADC path (see _initialize_with_application_default_credentials) --
# the service-account path gets its scope from the key file itself.
ADC_SCOPES = [
    "https://www.googleapis.com/auth/earthengine",
    "https://www.googleapis.com/auth/cloud-platform",
]

ADC_LOGIN_HINT = f"gcloud auth application-default login --scopes={','.join(ADC_SCOPES)}"


class EarthEngineNotConfiguredError(Exception):
    """Raised when an EE call is attempted but no usable Earth Engine
    credentials are configured (neither a service account nor Application
    Default Credentials). Callers should treat this as "feature
    unavailable", not a server error — see GEE_* in .env.example for what
    to set."""


class EarthEngineTimeoutError(Exception):
    """Raised when a call to Earth Engine doesn't finish within the timeout."""


class EarthEngineRequestError(Exception):
    """Raised when Earth Engine itself rejects or fails a request (quota,
    a server-side computation error, a transient backend failure, ...) --
    any `ee.EEException` from a network call. Callers turn it into a clean
    503 instead of letting it escape as an unhandled 500."""


class NoSentinelImageryAvailableError(Exception):
    """Raised when no Sentinel-2 scene at all covers the field in the
    analysis window (regardless of cloud cover) -- distinct from a timeout
    or a missing credential."""


@dataclass
class IndexStats:
    mean: float
    min: float
    max: float


@dataclass
class FieldAnalysisResult:
    """Result of EarthEngineClient.analyze_field -- a real Sentinel-2
    vegetation/moisture analysis over one farm's polygon."""

    image_date: date
    satellite: str  # "S2A" / "S2B"
    cloud_pct: float  # cloud+shadow fraction over the FIELD itself, not the whole scene
    is_fallback: bool  # True if no scene in the window was under ACCEPTABLE_CLOUD_PCT
    ndvi: IndexStats
    ndwi: IndexStats
    evi: IndexStats
    ndmi: IndexStats
    healthy_pct: float  # % of field pixels with NDVI > NDVI_HEALTHY_THRESHOLD
    moderate_pct: float  # % with NDVI_STRESSED_THRESHOLD <= NDVI <= NDVI_HEALTHY_THRESHOLD
    stressed_pct: float  # % with NDVI < NDVI_STRESSED_THRESHOLD


@dataclass
class TimeseriesPoint:
    """One scene's field-mean indices, from EarthEngineClient.build_field_timeseries.
    Unlike FieldAnalysisResult this carries no selection/classification --
    just raw per-scene numbers, for SatelliteService to filter and store."""

    image_date: date
    satellite: str
    cloud_pct: float
    ndvi_mean: float
    ndwi_mean: float
    evi_mean: float


@dataclass
class StressZoneResult:
    """One detected stress zone, vectorized from pixels significantly below
    the field's own mean NDVI. Not yet a DB row -- SatelliteService attaches
    farm_id/image_date and persists it."""

    zone_type: str  # "water_stress" | "nutrient_pest_suspected"
    area_ha: float
    geometry_geojson: dict
    suggested_action: str


@dataclass
class FieldMapLayers:
    """Visualised, farm-polygon-clipped Earth Engine tile URLs for one
    scene, plus the stress zones vectorized from that same scene. From
    EarthEngineClient.get_field_map_layers."""

    image_date: date
    true_color_tile_url: str
    ndvi_tile_url: str
    ndwi_tile_url: str
    evi_tile_url: str
    stress_tile_url: str
    stress_zones: list[StressZoneResult]


@dataclass
class RainfallSummary:
    """CHIRPS-derived accumulated rainfall over a few trailing windows, all
    anchored to the latest date actually present in CHIRPS (see
    _get_rainfall_summary), not literally "today"."""

    mm_7d: float
    mm_30d: float
    mm_90d: float
    mm_since_sowing: float | None  # None only if sowing_date is after the latest CHIRPS date
    as_of: date


@dataclass
class TemperatureSummary:
    """MODIS land-surface-temperature summary over the trailing LST_LOOKBACK_DAYS."""

    mean_lst_c: float | None
    hot_periods_60d: int  # count of 8-day MODIS composites with field-mean LST > HOT_PERIOD_THRESHOLD_C
    as_of: date  # most recent MODIS composite date actually used


@dataclass
class SoilMoistureSummary:
    """Latest available SMAP L4 surface soil moisture -- see the SMAP_*
    constants for why `as_of` can be materially stale."""

    surface_moisture: float | None  # m3/m3 volumetric water content
    as_of: date | None


@dataclass
class EnvironmentDynamics:
    """The three non-static parts of a farm's environment report -- see
    EarthEngineClient.get_environment_dynamics."""

    rainfall: RainfallSummary
    temperature: TemperatureSummary
    soil_moisture: SoilMoistureSummary


@dataclass
class SoilProperties:
    """Static OpenLandMap soil properties -- see
    EarthEngineClient.get_soil_properties. Fetched once per farm and
    reused (SatelliteService.environment_report), since these never change."""

    ph: float | None
    organic_carbon_g_per_kg: float | None
    texture_class: str | None  # e.g. "Sandy Loam" -- see USDA_TEXTURE_CLASS_NAMES


def _suggested_action(zone_type: str) -> str:
    if zone_type == "water_stress":
        return "Increase irrigation frequency in this zone and check for drainage or delivery issues."
    return (
        "Inspect this zone for nutrient deficiency or pest/disease pressure -- "
        "consider a soil test or targeted scouting."
    )


def _short_satellite_name(spacecraft_name: str | None) -> str:
    """"Sentinel-2A" -> "S2A", and likewise for any unit (2B, 2C -- in
    operation since 2025 -- 2D, ...). Always fits the String(10) `satellite`
    columns: an unrecognised name is truncated rather than failing the insert."""
    if not spacecraft_name:
        return "S2"
    match = re.search(r"2([A-Z])\b", spacecraft_name.upper())
    if match:
        return f"S2{match.group(1)}"
    return spacecraft_name[:10]


class EarthEngineClient:
    """Thin, async-safe wrapper around the `earthengine-api` SDK.

    Construct once (see the `earth_engine_client` singleton below) and call
    `initialize()` once at app startup. Two auth paths, tried in this order:

    1. **Service account** (production) — used when `service_account_email`
       and `key_path` are both set. Needs a downloaded JSON key, which some
       GCP organizations block via the `iam.disableServiceAccountKeyCreation`
       policy — see path 2 when that applies.
    2. **Application Default Credentials** (local development) — used
       whenever a service-account key isn't configured, as long as
       `project_id` is set. Uses whatever's logged in locally via
       `gcloud auth application-default login` — no key file, so it works
       even when service-account key creation is blocked by org policy.

    If neither path is usable, `configured` stays False and every method
    raises EarthEngineNotConfiguredError instead of touching the network —
    the app must still boot and serve every other route normally without a
    working Earth Engine connection.
    """

    def __init__(
        self,
        *,
        project_id: str | None,
        service_account_email: str | None = None,
        key_path: str | None = None,
    ) -> None:
        self.project_id = project_id
        self.service_account_email = service_account_email
        self.key_path = key_path
        self.configured = False
        self.auth_mode: str | None = None  # "service_account" | "application_default" | None
        self.init_error: str | None = None

    def initialize(self) -> None:
        """Call once at startup. Never raises — failures are recorded on
        `init_error` and surfaced via `configured`, since a missing or
        invalid Earth Engine credential must not prevent the rest of the
        API from starting."""
        if not self.project_id:
            self.configured = False
            self.auth_mode = None
            self.init_error = "GEE_PROJECT_ID is not set."
            logger.info("Earth Engine not configured — %s", self.init_error)
            return

        if self.service_account_email and self.key_path:
            self._initialize_with_service_account()
        else:
            self._initialize_with_application_default_credentials()

    def _initialize_with_service_account(self) -> None:
        try:
            credentials = ee.ServiceAccountCredentials(self.service_account_email, self.key_path)
            ee.Initialize(credentials, project=self.project_id)
            self.configured = True
            self.auth_mode = "service_account"
            self.init_error = None
            logger.info("Earth Engine initialised (service account) for project %s", self.project_id)
        except Exception as exc:  # noqa: BLE001 — any EE/auth failure must not crash startup
            self.configured = False
            self.auth_mode = None
            self.init_error = str(exc)
            logger.warning("Earth Engine service-account initialisation failed: %s", exc)

    def _initialize_with_application_default_credentials(self) -> None:
        try:
            credentials, _ = google_auth_default(scopes=ADC_SCOPES)
            ee.Initialize(credentials, project=self.project_id)
            self.configured = True
            self.auth_mode = "application_default"
            self.init_error = None
            logger.info(
                "Earth Engine initialised (application default credentials) for project %s",
                self.project_id,
            )
        except Exception as exc:  # noqa: BLE001 — any EE/auth failure must not crash startup
            self.configured = False
            self.auth_mode = None
            self.init_error = (
                f"No usable Earth Engine credentials found. Run: {ADC_LOGIN_HINT} "
                f"(original error: {exc})"
            )
            logger.warning("Earth Engine ADC initialisation failed: %s", exc)

    async def _get_info(self, ee_object, *, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        """Runs a blocking EE `.getInfo()` call in a worker thread with a
        timeout, so it never blocks the event loop."""
        try:
            return await asyncio.wait_for(asyncio.to_thread(ee_object.getInfo), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise EarthEngineTimeoutError(
                f"Earth Engine call did not complete within {timeout}s."
            ) from exc
        except ee.EEException as exc:
            raise EarthEngineRequestError(f"Earth Engine request failed: {exc}") from exc

    async def _get_map_id(
        self, image, vis_params: dict, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> str:
        """Runs the blocking EE `.getMapId()` call (which itself makes a
        network request to mint a tile token) in a worker thread with a
        timeout -- same principle as `_get_info`. Returns the XYZ tile URL
        template (`tile_fetcher.url_format`)."""

        def _call() -> str:
            map_id = image.getMapId(vis_params)
            return map_id["tile_fetcher"].url_format

        try:
            return await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise EarthEngineTimeoutError(
                f"Earth Engine call did not complete within {timeout}s."
            ) from exc
        except ee.EEException as exc:
            raise EarthEngineRequestError(f"Earth Engine request failed: {exc}") from exc

    async def count_recent_sentinel2_images(
        self,
        lon: float = HEALTH_CHECK_LON,
        lat: float = HEALTH_CHECK_LAT,
        days: int = 30,
    ) -> int:
        """Counts Sentinel-2 L2A scenes covering (lon, lat) in the last
        `days` days — a trivial, cheap computation used to prove the EE
        connection actually works end-to-end (see GET /health/earth-engine).
        """
        if not self.configured:
            raise EarthEngineNotConfiguredError(
                self.init_error or "Earth Engine is not configured."
            )

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        point = ee.Geometry.Point([lon, lat])
        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(point)
            .filterDate(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        )
        return await self._get_info(collection.size())

    async def analyze_field(
        self,
        polygon_geojson: dict,
        *,
        days: int = FIELD_ANALYSIS_WINDOW_DAYS,
    ) -> FieldAnalysisResult:
        """Runs a real Sentinel-2 NDVI/NDWI/EVI/NDMI analysis over a farm's
        polygon.

        Picks the most recent scene in the last `days` days with under
        ACCEPTABLE_CLOUD_PCT cloud+shadow cover *over the field itself* (not
        the whole scene) -- falling back to the single least-cloudy scene in
        the window (flagged via `is_fallback=True`) if none qualify. Raises
        NoSentinelImageryAvailableError if the window has no Sentinel-2
        coverage of the field at all.

        Cloud/shadow masking uses the scene's SCL (Scene Classification
        Layer) band rather than a COPERNICUS/S2_CLOUD_PROBABILITY join --
        SCL ships on S2_SR_HARMONIZED itself, so this needs only one
        collection and one image per candidate scene.
        """
        if not self.configured:
            raise EarthEngineNotConfiguredError(self.init_error or "Earth Engine is not configured.")

        geometry = ee.Geometry(polygon_geojson)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(geometry)
            .filterDate(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        )

        def _tag_field_cloud_pct(image):
            scl = image.select("SCL")
            is_cloudy = scl.remap(SCL_CLOUD_SHADOW_CLASSES, [1] * len(SCL_CLOUD_SHADOW_CLASSES), 0)
            raw_cloud_fraction = (
                is_cloudy.rename("cloud")
                .reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=geometry,
                    scale=REGION_REDUCE_SCALE_M,
                    bestEffort=True,
                )
                .get("cloud")
            )
            # reduceRegion always includes the "cloud" key in its output, but
            # its VALUE is null whenever this particular scene has zero
            # pixels actually intersecting the field at the pixel-grid level
            # (its bounding footprint can still pass filterBounds while the
            # field falls in a gap between swaths, or right at a tile edge).
            # Unlike a genuinely missing key, dict.get(key, default) does
            # NOT rescue a present-but-null value -- and neither does
            # .unmask() on the source band, since there's no pixel grid
            # there at all to unmask. ee.List(...).reduce(firstNonNull()) is
            # EE's standard null-coalescing idiom for exactly this. Treating
            # "no data" as maximally cloudy (1.0) also correctly excludes
            # such a scene from selection unless it's the only candidate.
            cloud_fraction = ee.List([raw_cloud_fraction, 1]).reduce(ee.Reducer.firstNonNull())
            return image.set("FIELD_CLOUD_PCT", ee.Number(cloud_fraction).multiply(100))

        # select([]) drops pixel bands (properties are untouched) so this
        # getInfo() call only pulls image metadata, not pixel data.
        tagged = collection.map(_tag_field_cloud_pct)
        candidates = await self._get_info(
            tagged.select([]), timeout=FIELD_ANALYSIS_TIMEOUT_SECONDS
        )
        features = (candidates or {}).get("features", [])
        if not features:
            raise NoSentinelImageryAvailableError(
                f"No Sentinel-2 imagery found for this field in the last {days} days."
            )

        selected = self._select_best_image(features)
        image = ee.Image(selected["id"])

        scl = image.select("SCL")
        keep_mask = scl.remap(SCL_CLOUD_SHADOW_CLASSES, [0] * len(SCL_CLOUD_SHADOW_CLASSES), 1)
        masked = image.updateMask(keep_mask)
        scaled = masked.select(["B2", "B3", "B4", "B8", "B11"]).multiply(REFLECTANCE_SCALE)

        ndvi = scaled.normalizedDifference(["B8", "B4"]).rename("NDVI")
        ndwi = scaled.normalizedDifference(["B3", "B8"]).rename("NDWI")
        ndmi = scaled.normalizedDifference(["B8", "B11"]).rename("NDMI")
        evi = scaled.expression(
            "2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))",
            {"NIR": scaled.select("B8"), "RED": scaled.select("B4"), "BLUE": scaled.select("B2")},
        ).rename("EVI")
        indices = ndvi.addBands([ndwi, evi, ndmi])

        stats_reducer = (
            ee.Reducer.mean()
            .combine(ee.Reducer.min(), sharedInputs=True)
            .combine(ee.Reducer.max(), sharedInputs=True)
        )
        stats = indices.reduceRegion(
            reducer=stats_reducer, geometry=geometry, scale=REGION_REDUCE_SCALE_M, bestEffort=True
        )

        classified = (
            ndvi.gt(NDVI_HEALTHY_THRESHOLD)
            .rename("healthy")
            .addBands(
                ndvi.gte(NDVI_STRESSED_THRESHOLD).And(ndvi.lte(NDVI_HEALTHY_THRESHOLD)).rename("moderate")
            )
            .addBands(ndvi.lt(NDVI_STRESSED_THRESHOLD).rename("stressed"))
        )
        classification = classified.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=geometry, scale=REGION_REDUCE_SCALE_M, bestEffort=True
        )

        combined = (
            stats.combine(classification)
            .set("image_date", image.date().format("YYYY-MM-dd"))
            .set("satellite", image.get("SPACECRAFT_NAME"))
        )
        result = await self._get_info(combined, timeout=FIELD_ANALYSIS_TIMEOUT_SECONDS)

        # reduceRegion can legitimately return a key with a JSON `null` value
        # (not an absent key) if the *selected* scene still has zero valid
        # (unmasked) pixels for that particular band over the field -- e.g. a
        # fallback scene with heavy but not total cloud cover concentrated
        # over one band's swath. `dict.get(key, 0.0)` alone does NOT rescue a
        # present-but-None value (only a missing key), so this explicitly
        # treats both as "nothing detected" (0.0) rather than crashing.
        def _stat(key: str) -> float:
            value = result.get(key)
            return 0.0 if value is None else value

        return FieldAnalysisResult(
            image_date=datetime.strptime(result["image_date"], "%Y-%m-%d").date(),
            satellite=_short_satellite_name(result.get("satellite")),
            cloud_pct=round(selected["cloud_pct"], 1),
            is_fallback=selected["is_fallback"],
            ndvi=IndexStats(mean=_stat("NDVI_mean"), min=_stat("NDVI_min"), max=_stat("NDVI_max")),
            ndwi=IndexStats(mean=_stat("NDWI_mean"), min=_stat("NDWI_min"), max=_stat("NDWI_max")),
            evi=IndexStats(mean=_stat("EVI_mean"), min=_stat("EVI_min"), max=_stat("EVI_max")),
            ndmi=IndexStats(mean=_stat("NDMI_mean"), min=_stat("NDMI_min"), max=_stat("NDMI_max")),
            healthy_pct=round(_stat("healthy") * 100, 1),
            moderate_pct=round(_stat("moderate") * 100, 1),
            stressed_pct=round(_stat("stressed") * 100, 1),
        )

    @staticmethod
    def _select_best_image(features: list[dict]) -> dict:
        """Picks the most recent scene under ACCEPTABLE_CLOUD_PCT field
        cloud cover, or the single least-cloudy scene in the window if none
        qualify (flagged as a fallback). Pure Python, no EE calls -- makes
        the selection logic trivially unit-testable."""
        parsed = [
            {
                "id": feature["id"],
                "time_start": feature["properties"]["system:time_start"],
                "cloud_pct": feature["properties"]["FIELD_CLOUD_PCT"],
            }
            for feature in features
        ]
        under_threshold = [p for p in parsed if p["cloud_pct"] < ACCEPTABLE_CLOUD_PCT]
        if under_threshold:
            best = max(under_threshold, key=lambda p: p["time_start"])
            return {**best, "is_fallback": False}
        best = min(parsed, key=lambda p: p["cloud_pct"])
        return {**best, "is_fallback": True}

    async def build_field_timeseries(
        self, polygon_geojson: dict, *, start: date, end: date
    ) -> list[TimeseriesPoint]:
        """Returns one TimeseriesPoint per Sentinel-2 scene covering the
        field between `start` and `end` (inclusive), regardless of cloud
        cover -- callers (SatelliteService) filter by cloud_pct themselves.

        Computes NDVI/NDWI/EVI and field cloud % for *every* candidate scene
        in a single `.map()` over the collection, then a single `getInfo()`
        call -- never one Earth Engine round trip per scene. This is the
        same principle as analyze_field's scene-selection step, just
        computing full stats for every scene instead of picking just one.
        """
        if not self.configured:
            raise EarthEngineNotConfiguredError(self.init_error or "Earth Engine is not configured.")

        geometry = ee.Geometry(polygon_geojson)
        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(geometry)
            .filterDate(start.strftime("%Y-%m-%d"), (end + timedelta(days=1)).strftime("%Y-%m-%d"))
        )

        def _tag_indices_and_cloud(image):
            scl = image.select("SCL")
            keep_mask = scl.remap(SCL_CLOUD_SHADOW_CLASSES, [0] * len(SCL_CLOUD_SHADOW_CLASSES), 1)
            is_cloudy = scl.remap(SCL_CLOUD_SHADOW_CLASSES, [1] * len(SCL_CLOUD_SHADOW_CLASSES), 0)

            masked = image.updateMask(keep_mask)
            scaled = masked.select(["B2", "B3", "B4", "B8"]).multiply(REFLECTANCE_SCALE)
            ndvi = scaled.normalizedDifference(["B8", "B4"]).rename("NDVI")
            ndwi = scaled.normalizedDifference(["B3", "B8"]).rename("NDWI")
            evi = scaled.expression(
                "2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))",
                {"NIR": scaled.select("B8"), "RED": scaled.select("B4"), "BLUE": scaled.select("B2")},
            ).rename("EVI")
            index_stats = ndvi.addBands([ndwi, evi]).reduceRegion(
                reducer=ee.Reducer.mean(), geometry=geometry, scale=REGION_REDUCE_SCALE_M, bestEffort=True
            )

            raw_cloud_fraction = (
                is_cloudy.rename("cloud")
                .reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=geometry,
                    scale=REGION_REDUCE_SCALE_M,
                    bestEffort=True,
                )
                .get("cloud")
            )
            # See analyze_field's _tag_field_cloud_pct for why this null-coalesce
            # is needed: reduceRegion always includes the key, just with a null
            # value, when the field has zero valid pixels for this scene.
            cloud_fraction = ee.List([raw_cloud_fraction, 1]).reduce(ee.Reducer.firstNonNull())

            return (
                image.set(index_stats)
                .set("TS_CLOUD_PCT", ee.Number(cloud_fraction).multiply(100))
                .set("TS_IMAGE_DATE", image.date().format("YYYY-MM-dd"))
                .set("TS_SATELLITE", image.get("SPACECRAFT_NAME"))
            )

        tagged = collection.map(_tag_indices_and_cloud)
        raw = await self._get_info(tagged.select([]), timeout=TIMESERIES_TIMEOUT_SECONDS)
        features = (raw or {}).get("features", [])

        points: list[TimeseriesPoint] = []
        for feature in features:
            props = feature.get("properties", {})
            image_date_str = props.get("TS_IMAGE_DATE")
            ndvi_mean = props.get("NDVI")
            cloud_pct = props.get("TS_CLOUD_PCT")
            if image_date_str is None or ndvi_mean is None or cloud_pct is None:
                continue
            points.append(
                TimeseriesPoint(
                    image_date=datetime.strptime(image_date_str, "%Y-%m-%d").date(),
                    satellite=_short_satellite_name(props.get("TS_SATELLITE")),
                    cloud_pct=round(cloud_pct, 1),
                    ndvi_mean=ndvi_mean,
                    ndwi_mean=props.get("NDWI") or 0.0,
                    evi_mean=props.get("EVI") or 0.0,
                )
            )
        points.sort(key=lambda p: p.image_date)
        return points

    async def get_field_map_layers(self, polygon_geojson: dict, image_date: date) -> FieldMapLayers:
        """Builds visualised, farm-polygon-clipped Earth Engine tile layers
        (true color, NDVI, NDWI, EVI, a healthy/moderate/stressed
        classification) for the Sentinel-2 scene on `image_date`, plus
        stress zones vectorized from that same scene.

        Unlike analyze_field/build_field_timeseries, this targets one
        *specific*, already-known date (normally the date of an existing
        SatelliteObservation or IndexTimeseriesPoint) rather than selecting
        a scene itself -- callers pick the date, this just renders it.
        """
        if not self.configured:
            raise EarthEngineNotConfiguredError(self.init_error or "Earth Engine is not configured.")

        geometry = ee.Geometry(polygon_geojson)
        start = image_date.strftime("%Y-%m-%d")
        end = (image_date + timedelta(days=1)).strftime("%Y-%m-%d")

        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(geometry)
            .filterDate(start, end)
        )
        count = await self._get_info(collection.size())
        if not count:
            raise NoSentinelImageryAvailableError(
                f"No Sentinel-2 imagery found for this field on {image_date}."
            )
        image = ee.Image(collection.first())

        scl = image.select("SCL")
        keep_mask = scl.remap(SCL_CLOUD_SHADOW_CLASSES, [0] * len(SCL_CLOUD_SHADOW_CLASSES), 1)
        masked = image.updateMask(keep_mask)
        scaled = masked.select(["B2", "B3", "B4", "B8", "B11"]).multiply(REFLECTANCE_SCALE)

        ndvi = scaled.normalizedDifference(["B8", "B4"]).rename("NDVI")
        ndwi = scaled.normalizedDifference(["B3", "B8"]).rename("NDWI")
        evi = scaled.expression(
            "2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))",
            {"NIR": scaled.select("B8"), "RED": scaled.select("B4"), "BLUE": scaled.select("B2")},
        ).rename("EVI")

        # Field-relative stress threshold: mean NDVI minus one standard
        # deviation, both computed server-side and kept as lazy ee.Number
        # objects -- no getInfo() needed just to build the classified tile,
        # since Earth Engine's own tile server evaluates the whole graph
        # (including this reduceRegion) per tile request.
        ndvi_stats = ndvi.reduceRegion(
            reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
            geometry=geometry,
            scale=REGION_REDUCE_SCALE_M,
            bestEffort=True,
        )
        # Both are null when every field pixel is cloud-masked on this pass
        # (possible for any date the UI's pass slider asks for) -- default to
        # 0 so the tiles still build (fully transparent over the field)
        # instead of Earth Engine raising "Number.multiply: ... null".
        mean_ndvi = ee.Number(ee.Algorithms.If(ndvi_stats.get("NDVI_mean"), ndvi_stats.get("NDVI_mean"), 0))
        std_ndvi = ee.Number(ee.Algorithms.If(ndvi_stats.get("NDVI_stdDev"), ndvi_stats.get("NDVI_stdDev"), 0))
        stress_threshold = mean_ndvi.subtract(std_ndvi.multiply(STRESS_ZONE_STD_DEV_THRESHOLD))

        stressed_mask = ndvi.lt(stress_threshold)
        moderate_mask = ndvi.gte(stress_threshold).And(ndvi.lt(mean_ndvi))
        stress_class = (
            ndvi.multiply(0).add(2).rename("stress_class")  # default: healthy (2)
            .where(moderate_mask, 1)
            .where(stressed_mask, 0)
        )

        true_color_img = masked.select(["B4", "B3", "B2"]).multiply(REFLECTANCE_SCALE).clip(geometry)
        ndvi_img = ndvi.clip(geometry)
        ndwi_img = ndwi.clip(geometry)
        evi_img = evi.clip(geometry)
        stress_img = stress_class.clip(geometry)

        true_color_url, ndvi_url, ndwi_url, evi_url, stress_url = await asyncio.gather(
            self._get_map_id(true_color_img, TRUE_COLOR_VIS, timeout=MAP_LAYERS_TIMEOUT_SECONDS),
            self._get_map_id(ndvi_img, NDVI_VIS, timeout=MAP_LAYERS_TIMEOUT_SECONDS),
            self._get_map_id(ndwi_img, NDWI_VIS, timeout=MAP_LAYERS_TIMEOUT_SECONDS),
            self._get_map_id(evi_img, EVI_VIS, timeout=MAP_LAYERS_TIMEOUT_SECONDS),
            self._get_map_id(stress_img, STRESS_CLASS_VIS, timeout=MAP_LAYERS_TIMEOUT_SECONDS),
        )

        stress_zones = await self._vectorize_stress_zones(
            geometry=geometry, stressed_mask=stressed_mask, ndwi=ndwi
        )

        return FieldMapLayers(
            image_date=image_date,
            true_color_tile_url=true_color_url,
            ndvi_tile_url=ndvi_url,
            ndwi_tile_url=ndwi_url,
            evi_tile_url=evi_url,
            stress_tile_url=stress_url,
            stress_zones=stress_zones,
        )

    async def _vectorize_stress_zones(self, *, geometry, stressed_mask, ndwi) -> list[StressZoneResult]:
        """Converts the stressed-pixel mask into polygons (one per connected
        cluster of stressed pixels), classifies each by its own mean NDWI,
        and drops anything under STRESS_ZONE_MIN_AREA_M2. Everything --
        vectorization, per-zone area, per-zone NDWI -- happens server-side
        in one lazy graph; only the final result crosses the network via a
        single getInfo() call (never one round trip per zone)."""

        def _classify(feature):
            zone_geom = feature.geometry()
            area_m2 = zone_geom.area(1)
            zone_ndwi_mean = ndwi.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=zone_geom,
                scale=REGION_REDUCE_SCALE_M,
                bestEffort=True,
            ).get("NDWI")
            return feature.set({"area_m2": area_m2, "ndwi_mean": zone_ndwi_mean})

        vectors = (
            stressed_mask.selfMask()
            .reduceToVectors(
                geometry=geometry,
                scale=REGION_REDUCE_SCALE_M,
                geometryType="polygon",
                eightConnected=True,
                maxPixels=1e8,
                bestEffort=True,
            )
            .map(_classify)
            .filter(ee.Filter.gte("area_m2", STRESS_ZONE_MIN_AREA_M2))
        )

        raw = await self._get_info(vectors, timeout=MAP_LAYERS_TIMEOUT_SECONDS)
        features = (raw or {}).get("features", [])

        zones: list[StressZoneResult] = []
        for feature in features:
            props = feature.get("properties", {})
            area_m2 = props.get("area_m2")
            zone_geometry = feature.get("geometry")
            if area_m2 is None or zone_geometry is None:
                continue
            ndwi_mean = props.get("ndwi_mean")
            zone_type = "water_stress" if (ndwi_mean is not None and ndwi_mean < 0) else "nutrient_pest_suspected"
            zones.append(
                StressZoneResult(
                    zone_type=zone_type,
                    area_ha=round(area_m2 / 10000, 4),
                    geometry_geojson=zone_geometry,
                    suggested_action=_suggested_action(zone_type),
                )
            )
        return zones

    async def get_environment_dynamics(
        self, polygon_geojson: dict, sowing_date: date
    ) -> EnvironmentDynamics:
        """Rainfall, land-surface temperature, and soil moisture for a
        farm's polygon -- the parts of the environment report that change
        over time (contrast get_soil_properties, which is static and
        fetched once). Three independent Earth Engine round trips, run
        sequentially since each already minimizes its own network calls to
        one (rainfall) or two (temperature/soil moisture -- one to find
        what's available, one for the reduced value)."""
        if not self.configured:
            raise EarthEngineNotConfiguredError(self.init_error or "Earth Engine is not configured.")

        geometry = ee.Geometry(polygon_geojson)
        rainfall = await self._get_rainfall_summary(geometry, sowing_date)
        temperature = await self._get_temperature_summary(geometry)
        soil_moisture = await self._get_soil_moisture_summary(geometry)
        return EnvironmentDynamics(rainfall=rainfall, temperature=temperature, soil_moisture=soil_moisture)

    async def _get_rainfall_summary(self, geometry, sowing_date: date) -> RainfallSummary:
        chirps = ee.ImageCollection(CHIRPS_COLLECTION_ID).select("precipitation")

        latest_date_str = await self._get_info(
            chirps.sort("system:time_start", False).first().date().format("YYYY-MM-dd"),
            timeout=ENVIRONMENT_TIMEOUT_SECONDS,
        )
        # CHIRPS has been continuously updated since 1981; an empty result
        # here would mean the collection itself is unreachable/broken, not
        # a real data gap -- fall back to today rather than fail the whole
        # environment report over it.
        end_date = date.fromisoformat(latest_date_str) if latest_date_str else datetime.now(timezone.utc).date()

        since_sowing_days = max(0, min((end_date - sowing_date).days, RAINFALL_SINCE_SOWING_CAP_DAYS))

        def window_sum(days: int, band_name: str):
            start = end_date - timedelta(days=days)
            return (
                chirps.filterDate(start.strftime("%Y-%m-%d"), (end_date + timedelta(days=1)).strftime("%Y-%m-%d"))
                .sum()
                .rename(band_name)
            )

        combined = window_sum(7, "mm_7d").addBands(window_sum(30, "mm_30d")).addBands(window_sum(90, "mm_90d"))
        if since_sowing_days > 0:
            combined = combined.addBands(window_sum(since_sowing_days, "mm_since_sowing"))

        stats = await self._get_info(
            combined.reduceRegion(reducer=ee.Reducer.mean(), geometry=geometry, scale=SMALL_FIELD_REDUCE_SCALE_M, bestEffort=True),
            timeout=ENVIRONMENT_TIMEOUT_SECONDS,
        )
        stats = stats or {}
        mm_since_sowing = stats.get("mm_since_sowing")
        return RainfallSummary(
            mm_7d=round(stats.get("mm_7d") or 0.0, 1),
            mm_30d=round(stats.get("mm_30d") or 0.0, 1),
            mm_90d=round(stats.get("mm_90d") or 0.0, 1),
            mm_since_sowing=round(mm_since_sowing, 1) if mm_since_sowing is not None else None,
            as_of=end_date,
        )

    async def get_rainfall_daily_series(
        self, polygon_geojson: dict, start_date: date, end_date: date
    ) -> list[tuple[date, float]]:
        """Daily CHIRPS precipitation (mm) over the farm's polygon for
        `start_date`..`end_date` inclusive -- used by IrrigationService
        (app/services/irrigation_service.py) to roll its root-zone
        depletion balance forward day by day. Same one-`.map()`-then-one-
        `getInfo()` principle as _get_temperature_summary; a day CHIRPS
        hasn't backfilled yet (or with no valid pixels) is simply absent
        from the result rather than zero-filled, so callers can tell "no
        rain" from "no data"."""
        if not self.configured:
            raise EarthEngineNotConfiguredError(self.init_error or "Earth Engine is not configured.")
        if start_date > end_date:
            return []

        geometry = ee.Geometry(polygon_geojson)
        collection = (
            ee.ImageCollection(CHIRPS_COLLECTION_ID)
            .filterDate(start_date.strftime("%Y-%m-%d"), (end_date + timedelta(days=1)).strftime("%Y-%m-%d"))
            .select("precipitation")
        )

        def to_feature(image):
            mm = image.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=geometry, scale=SMALL_FIELD_REDUCE_SCALE_M, bestEffort=True
            ).get("precipitation")
            return ee.Feature(None, {"date": image.date().format("YYYY-MM-dd"), "mm": mm})

        raw = await self._get_info(
            ee.FeatureCollection(collection.map(to_feature)), timeout=ENVIRONMENT_TIMEOUT_SECONDS
        )
        features = (raw or {}).get("features", [])

        days: list[tuple[date, float]] = []
        for feature in features:
            props = feature.get("properties", {})
            mm = props.get("mm")
            day_str = props.get("date")
            if mm is None or day_str is None:
                continue
            days.append((date.fromisoformat(day_str), round(mm, 1)))
        return sorted(days)

    async def _get_temperature_summary(self, geometry) -> TemperatureSummary:
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=LST_LOOKBACK_DAYS)
        collection = (
            ee.ImageCollection(MODIS_LST_COLLECTION_ID)
            .filterDate(start.strftime("%Y-%m-%d"), (today + timedelta(days=1)).strftime("%Y-%m-%d"))
            .select("LST_Day_1km")
        )

        def to_feature(image):
            celsius = image.multiply(MODIS_LST_SCALE_FACTOR).subtract(KELVIN_TO_CELSIUS_OFFSET)
            mean_c = celsius.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=geometry, scale=SMALL_FIELD_REDUCE_SCALE_M, bestEffort=True
            ).get("LST_Day_1km")
            return ee.Feature(None, {"date": image.date().format("YYYY-MM-dd"), "temp_c": mean_c})

        raw = await self._get_info(
            ee.FeatureCollection(collection.map(to_feature)), timeout=ENVIRONMENT_TIMEOUT_SECONDS
        )
        features = (raw or {}).get("features", [])

        periods: list[tuple[date, float]] = []
        for feature in features:
            props = feature.get("properties", {})
            temp_c = props.get("temp_c")
            period_date = props.get("date")
            if temp_c is None or period_date is None:
                continue
            periods.append((date.fromisoformat(period_date), temp_c))

        if not periods:
            return TemperatureSummary(mean_lst_c=None, hot_periods_60d=0, as_of=today)

        temps = [t for _, t in periods]
        hot_periods = sum(1 for t in temps if t > HOT_PERIOD_THRESHOLD_C)
        return TemperatureSummary(
            mean_lst_c=round(sum(temps) / len(temps), 1),
            hot_periods_60d=hot_periods,
            as_of=max(d for d, _ in periods),
        )

    async def _get_soil_moisture_summary(self, geometry) -> SoilMoistureSummary:
        latest = ee.Image(
            ee.ImageCollection(SMAP_COLLECTION_ID)
            .select("sm_surface")
            .sort("system:time_start", False)
            .first()
        )
        feature = ee.Feature(
            None,
            {
                "date": latest.date().format("YYYY-MM-dd"),
                "value": latest.reduceRegion(
                    reducer=ee.Reducer.mean(), geometry=geometry, scale=SMALL_FIELD_REDUCE_SCALE_M, bestEffort=True
                ).get("sm_surface"),
            },
        )
        raw = await self._get_info(feature, timeout=ENVIRONMENT_TIMEOUT_SECONDS)
        props = (raw or {}).get("properties", {})
        value = props.get("value")
        period_date = props.get("date")
        return SoilMoistureSummary(
            surface_moisture=round(value, 3) if value is not None else None,
            as_of=date.fromisoformat(period_date) if period_date else None,
        )

    async def get_soil_properties(self, polygon_geojson: dict) -> SoilProperties:
        """Static OpenLandMap pH / organic carbon / USDA texture class at
        the shallowest available depth (0 cm). Meant to be called once per
        farm and cached -- see SatelliteService.environment_report."""
        if not self.configured:
            raise EarthEngineNotConfiguredError(self.init_error or "Earth Engine is not configured.")

        geometry = ee.Geometry(polygon_geojson)
        combined = (
            ee.Image(OPENLANDMAP_PH_ASSET_ID).select("b0").rename("ph")
            .addBands(ee.Image(OPENLANDMAP_ORGANIC_CARBON_ASSET_ID).select("b0").rename("organic_carbon"))
            .addBands(ee.Image(OPENLANDMAP_TEXTURE_ASSET_ID).select("b0").rename("texture_class"))
        )
        stats = await self._get_info(
            combined.reduceRegion(reducer=ee.Reducer.first(), geometry=geometry, scale=SMALL_FIELD_REDUCE_SCALE_M, bestEffort=True),
            timeout=ENVIRONMENT_TIMEOUT_SECONDS,
        )
        stats = stats or {}

        raw_ph = stats.get("ph")
        raw_oc = stats.get("organic_carbon")
        raw_texture = stats.get("texture_class")

        return SoilProperties(
            ph=round(raw_ph * OPENLANDMAP_PH_SCALE_FACTOR, 2) if raw_ph is not None else None,
            organic_carbon_g_per_kg=(
                round(raw_oc * OPENLANDMAP_ORGANIC_CARBON_SCALE_FACTOR, 1) if raw_oc is not None else None
            ),
            texture_class=USDA_TEXTURE_CLASS_NAMES.get(int(raw_texture)) if raw_texture is not None else None,
        )


def _build_client() -> EarthEngineClient:
    # Imported lazily so importing this module never requires app.core.config
    # to already be fully set up (keeps this module easy to unit test too).
    from app.core.config import settings

    return EarthEngineClient(
        project_id=settings.GEE_PROJECT_ID,
        service_account_email=settings.GEE_SERVICE_ACCOUNT_EMAIL,
        key_path=settings.GEE_KEY_PATH,
    )


# Singleton reused across the app's lifetime — constructed here, initialised
# in main.py's lifespan handler via EarthEngineClient.initialize().
earth_engine_client = _build_client()
