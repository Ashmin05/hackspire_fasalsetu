"""Soil-texture -> available water capacity lookup, used by
IrrigationService to turn a farm's root depth into total available water
(TAW = available water capacity x root depth).

**Typical, indicative figures** (commonly cited midpoints for each USDA
texture class' plant-available water), not a lab measurement for any
specific farm -- real available water capacity varies with structure,
compaction, and organic matter even within one texture class. Keyed on the
exact class names EarthEngineClient.get_soil_properties returns (see
USDA_TEXTURE_CLASS_NAMES in app/integrations/earth_engine_client.py), so a
farm with an OpenLandMap-derived EnvironmentSnapshot.soil_texture_class
maps straight through.
"""

# mm of plant-available water per metre of root depth, by USDA texture
# class -- typical midpoints (finer textures hold more total water, but
# tighter pore structure means not all of it is easily extractable, which
# is why clay isn't simply the highest value here).
SOIL_AWC_MM_PER_M: dict[str, float] = {
    "Sand": 90.0,
    "Loamy Sand": 100.0,
    "Sandy Loam": 130.0,
    "Sandy Clay Loam": 150.0,
    "Sandy Clay": 155.0,
    "Loam": 175.0,
    "Silt": 180.0,
    "Silt Loam": 190.0,
    "Clay Loam": 190.0,
    "Silty Clay Loam": 200.0,
    "Silty Clay": 205.0,
    "Clay": 195.0,
}

# A farm with no soil-texture reading yet (no EnvironmentSnapshot, or one
# whose OpenLandMap fetch hasn't run -- see app/models/environment_snapshot.py)
# falls back to this mid-range texture rather than blocking the irrigation
# plan. Always surfaced to the caller via IrrigationPlanResponse's
# soil_texture_is_default flag, never silently assumed.
DEFAULT_SOIL_TEXTURE = "Loam"


def available_water_capacity_mm_per_m(texture_class: str | None) -> float:
    return SOIL_AWC_MM_PER_M.get(texture_class or "", SOIL_AWC_MM_PER_M[DEFAULT_SOIL_TEXTURE])


def total_available_water_mm(texture_class: str | None, root_depth_m: float) -> float:
    """TAW = available water capacity (mm/m) x root depth (m)."""
    return available_water_capacity_mm_per_m(texture_class) * root_depth_m
