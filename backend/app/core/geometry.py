"""Polygon validation and area/centroid computation for farm boundaries.

Deliberately never does raw lat/lng arithmetic: a degree of longitude covers
a different real-world distance depending on latitude, so area/centroid math
on raw coordinates is wrong everywhere except the equator. Instead every
polygon is reprojected into a local equal-area CRS (an Albers Equal-Area
projection centered on the polygon itself) before measuring anything.
"""

from dataclasses import dataclass

import pyproj
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

MIN_AREA_HA = 0.05
MAX_AREA_HA = 500.0


class InvalidPolygonError(ValueError):
    """Raised when a submitted polygon isn't a usable field boundary."""


@dataclass(frozen=True)
class PolygonMetrics:
    area_ha: float
    centroid_lat: float
    centroid_lng: float


def _local_equal_area_crs(lon: float, lat: float) -> pyproj.CRS:
    # Albers Equal-Area, standard parallels 1 degree either side of the
    # polygon's own latitude — accurate for anything field-sized.
    proj4 = (
        f"+proj=aea +lat_1={lat - 1} +lat_2={lat + 1} +lat_0={lat} +lon_0={lon} "
        "+x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs"
    )
    return pyproj.CRS.from_proj4(proj4)


def _parse_polygon(polygon_geojson: dict) -> BaseGeometry:
    try:
        geom = shape(polygon_geojson)
    except (KeyError, ValueError, AttributeError, TypeError) as exc:
        raise InvalidPolygonError("polygon_geojson is not a valid GeoJSON geometry.") from exc

    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise InvalidPolygonError(f"Expected a Polygon or MultiPolygon, got {geom.geom_type}.")
    if geom.is_empty:
        raise InvalidPolygonError("Polygon is empty.")
    if not geom.is_valid:
        # Covers self-intersecting rings, duplicate points forming bowties, etc.
        raise InvalidPolygonError("Polygon is not valid (it may self-intersect).")

    return geom


def compute_polygon_metrics(polygon_geojson: dict) -> PolygonMetrics:
    """Validates the polygon and returns its area (hectares) and centroid,
    all computed in a local equal-area projection.

    Raises InvalidPolygonError if the polygon is malformed, self-intersecting,
    or outside the allowed area range (0.05-500 ha).
    """
    geom = _parse_polygon(polygon_geojson)

    lon, lat = geom.centroid.x, geom.centroid.y
    local_crs = _local_equal_area_crs(lon, lat)

    to_local = pyproj.Transformer.from_crs("EPSG:4326", local_crs, always_xy=True).transform
    projected = transform(to_local, geom)

    area_ha = projected.area / 10_000
    if area_ha < MIN_AREA_HA or area_ha > MAX_AREA_HA:
        raise InvalidPolygonError(
            f"Field area must be between {MIN_AREA_HA} and {MAX_AREA_HA} hectares "
            f"(this polygon is {area_ha:.4f} ha)."
        )

    projected_centroid = projected.centroid
    to_wgs84 = pyproj.Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True).transform
    centroid_lng, centroid_lat = to_wgs84(projected_centroid.x, projected_centroid.y)

    return PolygonMetrics(area_ha=area_ha, centroid_lat=centroid_lat, centroid_lng=centroid_lng)
