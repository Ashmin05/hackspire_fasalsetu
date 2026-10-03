"""Tests for EarthEngineClient. The real `ee` module is always mocked here —
these tests never need real Earth Engine credentials or network access."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations import earth_engine_client as eec
from app.integrations.earth_engine_client import (
    EarthEngineClient,
    EarthEngineNotConfiguredError,
    NoSentinelImageryAvailableError,
    _short_satellite_name,
)


class TestShortSatelliteName:
    @pytest.mark.parametrize(
        ("spacecraft", "expected"),
        [("Sentinel-2A", "S2A"), ("Sentinel-2B", "S2B"), ("Sentinel-2C", "S2C"), (None, "S2")],
    )
    def test_maps_every_sentinel_2_unit(self, spacecraft, expected) -> None:
        assert _short_satellite_name(spacecraft) == expected

    def test_unrecognised_name_fits_the_string_10_column(self) -> None:
        assert len(_short_satellite_name("Some-Future-Satellite")) <= 10


def _unconfigured_client() -> EarthEngineClient:
    return EarthEngineClient(project_id=None, service_account_email=None, key_path=None)


def _configured_client() -> EarthEngineClient:
    client = EarthEngineClient(
        project_id="fasalsetu-509718",
        service_account_email="ee-service@fasalsetu-509718.iam.gserviceaccount.com",
        key_path="secrets/ee-service-account.json",
    )
    client.configured = True
    return client


class TestInitialize:
    def test_stays_unconfigured_when_project_id_is_missing(self) -> None:
        client = _unconfigured_client()

        client.initialize()

        assert client.configured is False
        assert client.auth_mode is None
        assert "GEE_PROJECT_ID" in client.init_error

    def test_does_not_raise_when_settings_missing(self) -> None:
        # The whole point: a missing/blank EE key must never crash startup.
        _unconfigured_client().initialize()

    def test_uses_service_account_when_email_and_key_path_are_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = EarthEngineClient(
            project_id="fasalsetu-509718",
            service_account_email="ee-service@fasalsetu-509718.iam.gserviceaccount.com",
            key_path="secrets/ee-service-account.json",
        )

        client.initialize()

        assert client.configured is True
        assert client.auth_mode == "service_account"
        assert client.init_error is None
        fake_ee.ServiceAccountCredentials.assert_called_once_with(
            "ee-service@fasalsetu-509718.iam.gserviceaccount.com",
            "secrets/ee-service-account.json",
        )
        fake_ee.Initialize.assert_called_once()

    def test_stays_unconfigured_when_ee_rejects_service_account_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ee = MagicMock()
        fake_ee.Initialize.side_effect = Exception("invalid_grant: bad key")
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = EarthEngineClient(
            project_id="fasalsetu-509718",
            service_account_email="ee-service@fasalsetu-509718.iam.gserviceaccount.com",
            key_path="secrets/ee-service-account.json",
        )

        client.initialize()  # must not raise

        assert client.configured is False
        assert client.auth_mode is None
        assert "invalid_grant" in client.init_error

    def test_uses_application_default_credentials_when_no_service_account_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # This is the path used for local dev when an org policy blocks
        # service-account key creation (iam.disableServiceAccountKeyCreation).
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        fake_credentials = MagicMock()
        fake_default = MagicMock(return_value=(fake_credentials, "fasalsetu-509718"))
        monkeypatch.setattr(eec, "google_auth_default", fake_default)

        client = EarthEngineClient(project_id="fasalsetu-509718")

        client.initialize()

        assert client.configured is True
        assert client.auth_mode == "application_default"
        assert client.init_error is None
        fake_default.assert_called_once_with(scopes=eec.ADC_SCOPES)
        fake_ee.Initialize.assert_called_once_with(fake_credentials, project="fasalsetu-509718")
        fake_ee.ServiceAccountCredentials.assert_not_called()

    def test_stays_unconfigured_when_adc_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        fake_default = MagicMock(side_effect=Exception("Could not automatically determine credentials"))
        monkeypatch.setattr(eec, "google_auth_default", fake_default)

        client = EarthEngineClient(project_id="fasalsetu-509718")

        client.initialize()  # must not raise

        assert client.configured is False
        assert client.auth_mode is None
        assert "gcloud auth application-default login" in client.init_error


class TestCountRecentSentinel2Images:
    async def test_raises_not_configured_without_touching_ee(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _unconfigured_client()

        with pytest.raises(EarthEngineNotConfiguredError):
            await client.count_recent_sentinel2_images()

        fake_ee.ImageCollection.assert_not_called()

    async def test_returns_image_count_from_ee(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_collection = MagicMock()
        fake_collection.filterBounds.return_value = fake_collection
        fake_collection.filterDate.return_value = fake_collection
        fake_size = MagicMock()
        fake_size.getInfo.return_value = 7
        fake_collection.size.return_value = fake_size

        fake_ee = MagicMock()
        fake_ee.ImageCollection.return_value = fake_collection
        monkeypatch.setattr(eec, "ee", fake_ee)

        client = _configured_client()
        count = await client.count_recent_sentinel2_images(lon=78.96, lat=20.59, days=30)

        assert count == 7
        fake_ee.ImageCollection.assert_called_once_with("COPERNICUS/S2_SR_HARMONIZED")
        fake_ee.Geometry.Point.assert_called_once_with([78.96, 20.59])

    async def test_wraps_a_timeout_as_earth_engine_timeout_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        async def _never_finishes(coro, *args, **kwargs):
            coro.close()  # avoid a "coroutine was never awaited" warning
            raise asyncio.TimeoutError()

        monkeypatch.setattr(eec.asyncio, "wait_for", _never_finishes)

        fake_collection = MagicMock()
        fake_collection.filterBounds.return_value = fake_collection
        fake_collection.filterDate.return_value = fake_collection
        fake_ee = MagicMock()
        fake_ee.ImageCollection.return_value = fake_collection
        monkeypatch.setattr(eec, "ee", fake_ee)

        client = _configured_client()

        with pytest.raises(eec.EarthEngineTimeoutError):
            await client.count_recent_sentinel2_images()

    async def test_wraps_an_ee_exception_as_earth_engine_request_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ee as real_ee

        fake_size = MagicMock()
        fake_size.getInfo.side_effect = real_ee.EEException("User memory limit exceeded.")
        fake_collection = MagicMock()
        fake_collection.filterBounds.return_value = fake_collection
        fake_collection.filterDate.return_value = fake_collection
        fake_collection.size.return_value = fake_size
        fake_ee = MagicMock()
        fake_ee.ImageCollection.return_value = fake_collection
        fake_ee.EEException = real_ee.EEException
        monkeypatch.setattr(eec, "ee", fake_ee)

        client = _configured_client()

        with pytest.raises(eec.EarthEngineRequestError, match="User memory limit exceeded"):
            await client.count_recent_sentinel2_images()


class TestSelectBestImage:
    """Pure Python selection logic -- no Earth Engine involved, so these run
    against plain dicts shaped like the feature list EE's getInfo() would
    return for an ImageCollection."""

    @staticmethod
    def _feature(image_id: str, time_start_ms: int, cloud_pct: float) -> dict:
        return {
            "id": image_id,
            "properties": {"system:time_start": time_start_ms, "FIELD_CLOUD_PCT": cloud_pct},
        }

    def test_picks_most_recent_scene_under_threshold(self) -> None:
        features = [
            self._feature("old-clear", 1000, 5.0),
            self._feature("new-clear", 3000, 10.0),
            self._feature("newest-cloudy", 4000, 80.0),  # excluded: over threshold
        ]

        selected = EarthEngineClient._select_best_image(features)

        assert selected["id"] == "new-clear"
        assert selected["is_fallback"] is False

    def test_falls_back_to_least_cloudy_when_none_under_threshold(self) -> None:
        features = [
            self._feature("cloudy-a", 1000, 90.0),
            self._feature("cloudy-b", 2000, 45.0),  # least cloudy of the three
            self._feature("cloudy-c", 3000, 99.0),
        ]

        selected = EarthEngineClient._select_best_image(features)

        assert selected["id"] == "cloudy-b"
        assert selected["is_fallback"] is True

    def test_single_scene_under_threshold_is_selected(self) -> None:
        features = [self._feature("only-one", 5000, 12.5)]

        selected = EarthEngineClient._select_best_image(features)

        assert selected["id"] == "only-one"
        assert selected["is_fallback"] is False
        assert selected["cloud_pct"] == 12.5

    def test_boundary_cloud_pct_equal_to_threshold_is_excluded(self) -> None:
        # ACCEPTABLE_CLOUD_PCT is 20.0 -- exactly 20.0 must NOT qualify (strict <).
        features = [self._feature("borderline", 1000, eec.ACCEPTABLE_CLOUD_PCT)]

        selected = EarthEngineClient._select_best_image(features)

        assert selected["is_fallback"] is True


def _configured_client_for_analysis() -> EarthEngineClient:
    client = EarthEngineClient(project_id="fasal-setu-509721")
    client.configured = True
    return client


class TestAnalyzeField:
    """`_get_info` is EarthEngineClient's one boundary between EE-object
    space and plain Python values, so these tests mock it directly (two
    calls: the candidate-scene metadata list, then the final combined
    stats dict) rather than trying to fully replicate EE's chained
    Image/Reducer API on a MagicMock."""

    async def test_raises_not_configured_without_touching_ee(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = EarthEngineClient(project_id=None)

        with pytest.raises(EarthEngineNotConfiguredError):
            await client.analyze_field({"type": "Polygon", "coordinates": [[[0, 0]]]})

        fake_ee.ImageCollection.assert_not_called()

    async def test_raises_when_no_imagery_in_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()
        monkeypatch.setattr(client, "_get_info", AsyncMock(return_value={"features": []}))

        with pytest.raises(NoSentinelImageryAvailableError):
            await client.analyze_field({"type": "Polygon", "coordinates": [[[0, 0]]]})

    async def test_returns_parsed_result_from_selected_scene(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()

        candidates = {
            "features": [
                {
                    "id": "COPERNICUS/S2_SR_HARMONIZED/old",
                    "properties": {"system:time_start": 1000, "FIELD_CLOUD_PCT": 5.0},
                },
                {
                    "id": "COPERNICUS/S2_SR_HARMONIZED/best",
                    "properties": {"system:time_start": 2000, "FIELD_CLOUD_PCT": 8.3},
                },
            ]
        }
        combined_stats = {
            "image_date": "2026-09-20",
            "satellite": "Sentinel-2A",
            "NDVI_mean": 0.65, "NDVI_min": 0.10, "NDVI_max": 0.90,
            "NDWI_mean": -0.20, "NDWI_min": -0.50, "NDWI_max": 0.10,
            "EVI_mean": 0.55, "EVI_min": 0.05, "EVI_max": 0.80,
            "NDMI_mean": 0.30, "NDMI_min": -0.10, "NDMI_max": 0.60,
            "healthy": 0.72, "moderate": 0.20, "stressed": 0.08,
        }
        monkeypatch.setattr(client, "_get_info", AsyncMock(side_effect=[candidates, combined_stats]))

        result = await client.analyze_field({"type": "Polygon", "coordinates": [[[0, 0]]]})

        assert result.image_date == date(2026, 9, 20)
        assert result.satellite == "S2A"
        assert result.cloud_pct == 8.3
        assert result.is_fallback is False
        assert result.ndvi == eec.IndexStats(mean=0.65, min=0.10, max=0.90)
        assert result.ndwi == eec.IndexStats(mean=-0.20, min=-0.50, max=0.10)
        assert result.evi == eec.IndexStats(mean=0.55, min=0.05, max=0.80)
        assert result.ndmi == eec.IndexStats(mean=0.30, min=-0.10, max=0.60)
        assert result.healthy_pct == 72.0
        assert result.moderate_pct == 20.0
        assert result.stressed_pct == 8.0
        fake_ee.Image.assert_called_once_with("COPERNICUS/S2_SR_HARMONIZED/best")

    async def test_marks_fallback_when_only_cloudy_scenes_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()

        candidates = {
            "features": [
                {
                    "id": "COPERNICUS/S2_SR_HARMONIZED/cloudy",
                    "properties": {"system:time_start": 1000, "FIELD_CLOUD_PCT": 55.0},
                },
            ]
        }
        combined_stats = {
            "image_date": "2026-09-01",
            "satellite": "Sentinel-2B",
            "NDVI_mean": 0.4, "NDVI_min": 0.0, "NDVI_max": 0.7,
            "NDWI_mean": -0.1, "NDWI_min": -0.4, "NDWI_max": 0.2,
            "EVI_mean": 0.3, "EVI_min": 0.0, "EVI_max": 0.5,
            "NDMI_mean": 0.1, "NDMI_min": -0.2, "NDMI_max": 0.3,
            "healthy": 0.3, "moderate": 0.4, "stressed": 0.3,
        }
        monkeypatch.setattr(client, "_get_info", AsyncMock(side_effect=[candidates, combined_stats]))

        result = await client.analyze_field({"type": "Polygon", "coordinates": [[[0, 0]]]})

        assert result.is_fallback is True
        assert result.satellite == "S2B"
        assert result.cloud_pct == 55.0


class TestBuildFieldTimeseries:
    """Like TestAnalyzeField, mocks only the _get_info boundary -- one call
    here, since build_field_timeseries computes stats for every candidate
    scene in a single map()+getInfo() rather than a selection round trip
    followed by a stats round trip."""

    async def test_raises_not_configured_without_touching_ee(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = EarthEngineClient(project_id=None)

        with pytest.raises(EarthEngineNotConfiguredError):
            await client.build_field_timeseries(
                {"type": "Polygon", "coordinates": [[[0, 0]]]},
                start=date(2026, 6, 1),
                end=date(2026, 9, 1),
            )

        fake_ee.ImageCollection.assert_not_called()

    async def test_returns_empty_list_when_no_scenes_in_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()
        monkeypatch.setattr(client, "_get_info", AsyncMock(return_value={"features": []}))

        points = await client.build_field_timeseries(
            {"type": "Polygon", "coordinates": [[[0, 0]]]}, start=date(2026, 6, 1), end=date(2026, 9, 1)
        )

        assert points == []

    async def test_parses_and_sorts_points_by_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()

        raw = {
            "features": [
                {
                    "properties": {
                        "TS_IMAGE_DATE": "2026-08-15",
                        "TS_SATELLITE": "Sentinel-2A",
                        "TS_CLOUD_PCT": 12.3,
                        "NDVI": 0.55,
                        "NDWI": -0.05,
                        "EVI": 0.40,
                    }
                },
                {
                    "properties": {
                        "TS_IMAGE_DATE": "2026-06-10",
                        "TS_SATELLITE": "Sentinel-2B",
                        "TS_CLOUD_PCT": 4.0,
                        "NDVI": 0.20,
                        "NDWI": -0.15,
                        "EVI": 0.15,
                    }
                },
            ]
        }
        monkeypatch.setattr(client, "_get_info", AsyncMock(return_value=raw))

        points = await client.build_field_timeseries(
            {"type": "Polygon", "coordinates": [[[0, 0]]]}, start=date(2026, 6, 1), end=date(2026, 9, 1)
        )

        assert [p.image_date for p in points] == [date(2026, 6, 10), date(2026, 8, 15)]
        assert points[0].satellite == "S2B"
        assert points[0].cloud_pct == 4.0
        assert points[0].ndvi_mean == 0.20
        assert points[1].satellite == "S2A"
        assert points[1].ndvi_mean == 0.55
        assert points[1].evi_mean == 0.40

    async def test_skips_features_missing_required_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()

        raw = {
            "features": [
                # Missing NDVI entirely (e.g. zero valid pixels for this scene) -- skipped, not crashed.
                {
                    "properties": {
                        "TS_IMAGE_DATE": "2026-07-01",
                        "TS_SATELLITE": "Sentinel-2A",
                        "TS_CLOUD_PCT": 10.0,
                        "NDVI": None,
                        "NDWI": None,
                        "EVI": None,
                    }
                },
                {
                    "properties": {
                        "TS_IMAGE_DATE": "2026-07-15",
                        "TS_SATELLITE": "Sentinel-2B",
                        "TS_CLOUD_PCT": 8.0,
                        "NDVI": 0.45,
                        "NDWI": None,
                        "EVI": None,
                    }
                },
            ]
        }
        monkeypatch.setattr(client, "_get_info", AsyncMock(return_value=raw))

        points = await client.build_field_timeseries(
            {"type": "Polygon", "coordinates": [[[0, 0]]]}, start=date(2026, 6, 1), end=date(2026, 9, 1)
        )

        assert len(points) == 1
        assert points[0].image_date == date(2026, 7, 15)
        assert points[0].ndvi_mean == 0.45
        # NDWI/EVI were null for this scene -- defaulted to 0.0 rather than crashing.
        assert points[0].ndwi_mean == 0.0
        assert points[0].evi_mean == 0.0


class TestSuggestedAction:
    def test_water_stress_gets_irrigation_advice(self) -> None:
        assert "irrigation" in eec._suggested_action("water_stress").lower()

    def test_nutrient_pest_gets_scouting_advice(self) -> None:
        action = eec._suggested_action("nutrient_pest_suspected").lower()
        assert "soil test" in action or "scouting" in action


class TestGetFieldMapLayers:
    """Mocks only the _get_info and _get_map_id boundaries -- same
    principle as TestAnalyzeField/TestBuildFieldTimeseries."""

    async def test_raises_not_configured_without_touching_ee(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = EarthEngineClient(project_id=None)

        with pytest.raises(EarthEngineNotConfiguredError):
            await client.get_field_map_layers({"type": "Polygon", "coordinates": [[[0, 0]]]}, date(2026, 9, 15))

        fake_ee.ImageCollection.assert_not_called()

    async def test_raises_when_no_imagery_for_that_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()
        monkeypatch.setattr(client, "_get_info", AsyncMock(return_value=0))

        with pytest.raises(NoSentinelImageryAvailableError):
            await client.get_field_map_layers({"type": "Polygon", "coordinates": [[[0, 0]]]}, date(2026, 9, 15))

    async def test_returns_tile_urls_and_classified_stress_zones(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()

        zones_raw = {
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
                    "properties": {"area_m2": 500.0, "ndwi_mean": -0.1},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [[[2, 2], [2, 3], [3, 3], [2, 2]]]},
                    "properties": {"area_m2": 300.0, "ndwi_mean": 0.2},
                },
            ]
        }
        # First _get_info call is the scene-existence count, second is the
        # stress-zone vectorization result.
        monkeypatch.setattr(client, "_get_info", AsyncMock(side_effect=[1, zones_raw]))
        monkeypatch.setattr(
            client,
            "_get_map_id",
            AsyncMock(
                side_effect=[
                    "https://tile/true_color/{z}/{x}/{y}",
                    "https://tile/ndvi/{z}/{x}/{y}",
                    "https://tile/ndwi/{z}/{x}/{y}",
                    "https://tile/evi/{z}/{x}/{y}",
                    "https://tile/stress/{z}/{x}/{y}",
                ]
            ),
        )

        result = await client.get_field_map_layers(
            {"type": "Polygon", "coordinates": [[[0, 0]]]}, date(2026, 9, 15)
        )

        assert result.image_date == date(2026, 9, 15)
        assert result.true_color_tile_url == "https://tile/true_color/{z}/{x}/{y}"
        assert result.ndvi_tile_url == "https://tile/ndvi/{z}/{x}/{y}"
        assert result.ndwi_tile_url == "https://tile/ndwi/{z}/{x}/{y}"
        assert result.evi_tile_url == "https://tile/evi/{z}/{x}/{y}"
        assert result.stress_tile_url == "https://tile/stress/{z}/{x}/{y}"

        assert len(result.stress_zones) == 2
        assert result.stress_zones[0].zone_type == "water_stress"  # ndwi_mean -0.1 < 0
        assert result.stress_zones[0].area_ha == 0.05  # 500 m2 / 10000
        assert result.stress_zones[1].zone_type == "nutrient_pest_suspected"  # ndwi_mean 0.2 >= 0
        assert result.stress_zones[1].area_ha == 0.03  # 300 m2 / 10000

    async def test_drops_zones_missing_geometry_or_area(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()

        zones_raw = {
            "features": [
                {"type": "Feature", "geometry": None, "properties": {"area_m2": 500.0, "ndwi_mean": -0.1}},
                {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}, "properties": {"ndwi_mean": -0.1}},
            ]
        }
        monkeypatch.setattr(client, "_get_info", AsyncMock(side_effect=[1, zones_raw]))
        monkeypatch.setattr(client, "_get_map_id", AsyncMock(side_effect=["a", "b", "c", "d", "e"]))

        result = await client.get_field_map_layers(
            {"type": "Polygon", "coordinates": [[[0, 0]]]}, date(2026, 9, 15)
        )

        assert result.stress_zones == []


class TestGetEnvironmentDynamics:
    """Mocks only the _get_info boundary -- same principle as the other
    EarthEngineClient tests. Call order inside get_environment_dynamics is
    fixed: rainfall (latest-date lookup, then windowed stats), then
    temperature (one FeatureCollection getInfo), then soil moisture (one
    Feature getInfo)."""

    async def test_raises_not_configured_without_touching_ee(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = EarthEngineClient(project_id=None)

        with pytest.raises(EarthEngineNotConfiguredError):
            await client.get_environment_dynamics(
                {"type": "Polygon", "coordinates": [[[0, 0]]]}, date(2026, 8, 1)
            )

        fake_ee.ImageCollection.assert_not_called()

    async def test_computes_rainfall_temperature_and_soil_moisture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()

        temperature_features = {
            "features": [
                {"type": "Feature", "properties": {"date": "2026-08-01", "temp_c": 30.0}},
                {"type": "Feature", "properties": {"date": "2026-08-09", "temp_c": 36.5}},
                {"type": "Feature", "properties": {"date": "2026-08-17", "temp_c": 33.0}},
            ]
        }
        soil_moisture_feature = {"type": "Feature", "properties": {"date": "2026-08-15", "value": 0.23456}}

        monkeypatch.setattr(
            client,
            "_get_info",
            AsyncMock(
                side_effect=[
                    "2026-09-15",  # latest CHIRPS date
                    {"mm_7d": 12.34, "mm_30d": 45.6, "mm_90d": 120.0, "mm_since_sowing": 200.05},
                    temperature_features,
                    soil_moisture_feature,
                ]
            ),
        )

        result = await client.get_environment_dynamics(
            {"type": "Polygon", "coordinates": [[[0, 0]]]}, date(2026, 8, 1)
        )

        assert result.rainfall.mm_7d == 12.3
        assert result.rainfall.mm_30d == 45.6
        assert result.rainfall.mm_90d == 120.0
        assert result.rainfall.mm_since_sowing == 200.1
        assert result.rainfall.as_of == date(2026, 9, 15)

        assert result.temperature.hot_periods_60d == 1  # only 36.5 > 35.0
        assert result.temperature.mean_lst_c == round((30.0 + 36.5 + 33.0) / 3, 1)
        assert result.temperature.as_of == date(2026, 8, 17)

        assert result.soil_moisture.surface_moisture == 0.235
        assert result.soil_moisture.as_of == date(2026, 8, 15)

    async def test_since_sowing_omitted_when_sowing_date_after_latest_chirps_date(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()

        monkeypatch.setattr(
            client,
            "_get_info",
            AsyncMock(
                side_effect=[
                    "2026-09-15",
                    {"mm_7d": 1.0, "mm_30d": 2.0, "mm_90d": 3.0},  # no mm_since_sowing key at all
                    {"features": []},
                    {"type": "Feature", "properties": {}},
                ]
            ),
        )

        result = await client.get_environment_dynamics(
            {"type": "Polygon", "coordinates": [[[0, 0]]]}, date(2026, 10, 1)
        )

        assert result.rainfall.mm_since_sowing is None

    async def test_temperature_returns_none_mean_when_no_periods_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()

        monkeypatch.setattr(
            client,
            "_get_info",
            AsyncMock(
                side_effect=[
                    "2026-09-15",
                    {"mm_7d": 0.0, "mm_30d": 0.0, "mm_90d": 0.0, "mm_since_sowing": 0.0},
                    {"features": []},
                    {"type": "Feature", "properties": {}},
                ]
            ),
        )

        result = await client.get_environment_dynamics(
            {"type": "Polygon", "coordinates": [[[0, 0]]]}, date(2026, 8, 1)
        )

        assert result.temperature.mean_lst_c is None
        assert result.temperature.hot_periods_60d == 0
        assert result.soil_moisture.surface_moisture is None
        assert result.soil_moisture.as_of is None


class TestGetSoilProperties:
    async def test_raises_not_configured_without_touching_ee(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = EarthEngineClient(project_id=None)

        with pytest.raises(EarthEngineNotConfiguredError):
            await client.get_soil_properties({"type": "Polygon", "coordinates": [[[0, 0]]]})

        fake_ee.Image.assert_not_called()

    async def test_returns_scaled_ph_organic_carbon_and_texture_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()

        # raw pH x10, raw organic carbon (x5 -> g/kg), raw USDA texture class number
        monkeypatch.setattr(
            client, "_get_info", AsyncMock(return_value={"ph": 74, "organic_carbon": 2, "texture_class": 9})
        )

        result = await client.get_soil_properties({"type": "Polygon", "coordinates": [[[0, 0]]]})

        assert result.ph == 7.4
        assert result.organic_carbon_g_per_kg == 10.0
        assert result.texture_class == "Sandy Loam"

    async def test_returns_none_fields_when_values_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_ee = MagicMock()
        monkeypatch.setattr(eec, "ee", fake_ee)
        client = _configured_client_for_analysis()

        monkeypatch.setattr(client, "_get_info", AsyncMock(return_value={}))

        result = await client.get_soil_properties({"type": "Polygon", "coordinates": [[[0, 0]]]})

        assert result.ph is None
        assert result.organic_carbon_g_per_kg is None
        assert result.texture_class is None
