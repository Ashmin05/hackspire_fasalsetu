import uuid
from datetime import date

import pytest

from app.repositories.user_repository import UserRepository
from app.schemas.farm import SoilReportIn
from app.services.farm_service import FarmError, FarmNotFoundError, FarmService

# Roughly a 100m x 100m square near Nashik, Maharashtra — about 1 hectare.
VALID_POLYGON = {
    "type": "Polygon",
    "coordinates": [[
        [73.789522, 19.989548],
        [73.790478, 19.989548],
        [73.790478, 19.990452],
        [73.789522, 19.990452],
        [73.789522, 19.989548],
    ]],
}

# A ~1m x 1m square — far below the 0.05 ha minimum.
TOO_SMALL_POLYGON = {
    "type": "Polygon",
    "coordinates": [[
        [73.789500, 19.989500],
        [73.789509, 19.989500],
        [73.789509, 19.989509],
        [73.789500, 19.989509],
        [73.789500, 19.989500],
    ]],
}

# A self-intersecting "bowtie" — invalid geometry.
SELF_INTERSECTING_POLYGON = {
    "type": "Polygon",
    "coordinates": [[
        [73.789, 19.989],
        [73.791, 19.991],
        [73.791, 19.989],
        [73.789, 19.991],
        [73.789, 19.989],
    ]],
}


async def _user_with_profile(user_repository: UserRepository, *, phone: str | None = "9876543210",
                              state: str | None = "Maharashtra"):
    user = await user_repository.create(email="farmer@example.com", hashed_password="x")
    return await user_repository.update_profile(user, phone=phone, state=state)


async def _create_farm(farm_service: FarmService, user, *, polygon=None):
    return await farm_service.create_farm(
        user,
        name="North Onion Field",
        crop="Onion",
        variety="Bhima Super",
        sowing_date=date(2026, 6, 10),
        irrigation_method="Drip",
        polygon_geojson=polygon or VALID_POLYGON,
        state="Maharashtra",
        district="Nashik",
        address="Dindori Road, Nashik",
    )


class TestCreateFarm:
    async def test_creates_farm_with_computed_area_and_centroid(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)

        farm = await _create_farm(farm_service, user)

        assert farm.user_id == user.id
        assert farm.name == "North Onion Field"
        # ~100m x 100m should compute to roughly 1 hectare.
        assert 0.8 < farm.area_ha < 1.2
        # Centroid should land inside the polygon's bounding box.
        assert 19.989 < farm.centroid_lat < 19.991
        assert 73.789 < farm.centroid_lng < 73.791

    async def test_rejects_farm_when_profile_incomplete(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository, phone=None, state=None)

        with pytest.raises(FarmError):
            await _create_farm(farm_service, user)

    async def test_rejects_polygon_below_minimum_area(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)

        with pytest.raises(FarmError):
            await _create_farm(farm_service, user, polygon=TOO_SMALL_POLYGON)

    async def test_rejects_self_intersecting_polygon(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)

        with pytest.raises(FarmError):
            await _create_farm(farm_service, user, polygon=SELF_INTERSECTING_POLYGON)


class TestOwnership:
    async def test_get_farm_returns_owner_farm(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)
        created = await _create_farm(farm_service, user)

        fetched = await farm_service.get_farm(user, created.id)

        assert fetched.id == created.id

    async def test_get_farm_raises_not_found_for_missing_id(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)

        with pytest.raises(FarmNotFoundError):
            await farm_service.get_farm(user, uuid.uuid4())

    async def test_get_farm_raises_not_found_for_someone_elses_farm(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        owner = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, owner)

        other = await user_repository.create(email="other@example.com", hashed_password="x")
        other = await user_repository.update_profile(other, phone="9123456780", state="Punjab")

        # Same exception as "doesn't exist" — never a 403 — so farm ids
        # can't be enumerated by comparing error responses.
        with pytest.raises(FarmNotFoundError):
            await farm_service.get_farm(other, farm.id)

    async def test_list_farms_only_returns_own_farms(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        owner = await _user_with_profile(user_repository)
        await _create_farm(farm_service, owner)

        other = await user_repository.create(email="other2@example.com", hashed_password="x")
        other = await user_repository.update_profile(other, phone="9123456781", state="Punjab")

        assert await farm_service.list_farms(other) == []
        assert len(await farm_service.list_farms(owner)) == 1

    async def test_update_farm_rejects_someone_elses_farm(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        owner = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, owner)

        other = await user_repository.create(email="other3@example.com", hashed_password="x")
        other = await user_repository.update_profile(other, phone="9123456782", state="Punjab")

        with pytest.raises(FarmNotFoundError):
            await farm_service.update_farm(other, farm.id, name="Renamed")

    async def test_delete_farm_rejects_someone_elses_farm(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        owner = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, owner)

        other = await user_repository.create(email="other4@example.com", hashed_password="x")
        other = await user_repository.update_profile(other, phone="9123456783", state="Punjab")

        with pytest.raises(FarmNotFoundError):
            await farm_service.delete_farm(other, farm.id)


class TestSoilReport:
    async def test_no_soil_report_leaves_has_soil_report_false(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)

        farm = await _create_farm(farm_service, user)

        assert farm.has_soil_report is False
        assert farm.soil_report_ph is None

    async def test_soil_report_is_saved_and_authoritative(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)

        farm = await farm_service.create_farm(
            user,
            name="Lab Tested Field",
            crop="Wheat",
            variety=None,
            sowing_date=date(2026, 6, 10),
            irrigation_method=None,
            polygon_geojson=VALID_POLYGON,
            state="Maharashtra",
            district="Nashik",
            address="Dindori Road, Nashik",
            soil_report=SoilReportIn(ph=6.6, nitrogen="High", phosphorus="Low", potassium="Medium", organic_matter_pct=1.8),
        )

        assert farm.has_soil_report is True
        assert farm.soil_report_ph == 6.6
        assert farm.soil_report_nitrogen == "High"
        assert farm.soil_report_phosphorus == "Low"
        assert farm.soil_report_potassium == "Medium"
        assert farm.soil_report_organic_matter_pct == 1.8
        assert farm.soil_report_recorded_at is not None

    async def test_update_farm_can_add_a_soil_report_later(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        assert farm.has_soil_report is False

        updated = await farm_service.update_farm(
            user, farm.id, soil_report=SoilReportIn(ph=7.1, nitrogen="Medium")
        )

        assert updated.has_soil_report is True
        assert updated.soil_report_ph == 7.1
        assert updated.soil_report_nitrogen == "Medium"


class TestUpdateFarm:
    async def test_updates_simple_fields(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)

        updated = await farm_service.update_farm(user, farm.id, name="Renamed Field")

        assert updated.name == "Renamed Field"
        assert updated.crop == "Onion"  # untouched fields survive

    async def test_updating_polygon_recomputes_area(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        original_area = farm.area_ha

        updated = await farm_service.update_farm(user, farm.id, polygon_geojson=VALID_POLYGON)

        # Same polygon re-submitted should recompute to (about) the same area.
        assert abs(updated.area_ha - original_area) < 0.01

    async def test_update_with_invalid_polygon_raises(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)

        with pytest.raises(FarmError):
            await farm_service.update_farm(user, farm.id, polygon_geojson=TOO_SMALL_POLYGON)


class TestDeleteFarm:
    async def test_deletes_farm(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)

        await farm_service.delete_farm(user, farm.id)

        with pytest.raises(FarmNotFoundError):
            await farm_service.get_farm(user, farm.id)
