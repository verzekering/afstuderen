# =========================
# Spatial configuration
# =========================

# QGIS extent (EPSG:3857) — pasted verbatim
QGIS_EXTENT_3857 = "499166.0, 6790961.2 : 500287.0, 6791520.9"




# =========================
# Temporal configuration
# =========================

START_DATE = "2024-11-01"
END_DATE   = "2025-10-31"


# =========================
# Utilities (NO EE OBJECTS)
# =========================

from pyproj import Transformer


def _parse_qgis_extent(extent_str):
    left, right = extent_str.split(":")
    xmin, ymin = map(float, left.split(","))
    xmax, ymax = map(float, right.split(","))
    return xmin, ymin, xmax, ymax


def extent_to_ee(extent_str=QGIS_EXTENT_3857):
    """
    Returns [lon_min, lat_min, lon_max, lat_max] (EPSG:4326)
    """
    xmin, ymin, xmax, ymax = _parse_qgis_extent(extent_str)

    transformer = Transformer.from_crs(
        "EPSG:3857", "EPSG:4326", always_xy=True
    )

    lon_min, lat_min = transformer.transform(xmin, ymin)
    lon_max, lat_max = transformer.transform(xmax, ymax)

    return [lon_min, lat_min, lon_max, lat_max]


def extent_to_rd(extent_str=QGIS_EXTENT_3857):
    """
    Returns (xmin, xmax, ymin, ymax) in EPSG:28992
    """
    xmin, ymin, xmax, ymax = _parse_qgis_extent(extent_str)

    transformer = Transformer.from_crs(
        "EPSG:3857", "EPSG:28992", always_xy=True
    )

    xmin_rd, ymin_rd = transformer.transform(xmin, ymin)
    xmax_rd, ymax_rd = transformer.transform(xmax, ymax)

    return (xmin_rd, xmax_rd, ymin_rd, ymax_rd)
