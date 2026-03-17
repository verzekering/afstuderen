# =========================
# Spatial configuration
# =========================


# # Groundwater data extent (EPSG:3857)
# GW_EXTENT_3857 = "492113.76, 6780550.11 : 492204.31, 6780597.59"
# GW_EXTENT_LON_LAT = ""

# # NDVI extent (EPSG:3857)
# NDVI_EXTENT_3857 = ""
# NDVI_EXTENT_LON_LAT = ""

#Ommoord:
# Groundwater data extent (EPSG:3857)
GW_EXTENT_3857 = "505687.9, 6792924.9 : 505780.7, 6792987.8"
GW_EXTENT_LON_LAT = ""

# NDVI extent (EPSG:3857)
NDVI_EXTENT_3857 = "501571, 6790874 : 509877, 6795228"
NDVI_EXTENT_LON_LAT = ""

# #Heijplaat:
# # Groundwater data extent (EPSG:3857)
# GW_EXTENT_3857 = "492113.76, 6780550.11 : 492204.31, 6780597.59"
# GW_EXTENT_LON_LAT = " "

# # NDVI extent (EPSG:3857)
# NDVI_EXTENT_3857 = "490616, 6779463 : 494445, 6781538"
# NDVI_EXTENT_LON_LAT = ""


# =========================
# Temporal configuration
# =========================

# Groundwater data date range
START_DATE = "2025-01-01"
END_DATE   = "2025-12-31"

# Models
# NDVI data date range
NDVI_START_DATE = "2021-04-1"
NDVI_END_DATE   = "2025-12-31"


# =========================
# Utilities (NO EE OBJECTS)
# =========================

from pyproj import Transformer


def _parse_qgis_extent(extent_str):
    left, right = extent_str.split(":")
    x1, y1 = map(float, left.strip().split(","))
    x2, y2 = map(float, right.strip().split(","))
    return x1, y1, x2, y2


def _get_active_extent(extent_type="gw"):
    """
    Returns (extent_string, crs)
    extent_type: "gw" for groundwater or "ndvi" for NDVI computation
    Chooses 3857 if provided, otherwise lon/lat (EPSG:4326).
    """
    if extent_type.lower() == "gw":
        extent_3857 = (globals().get("GW_EXTENT_3857") or "").strip()
        extent_4326 = (globals().get("GW_EXTENT_LON_LAT") or "").strip()
    elif extent_type.lower() == "ndvi":
        extent_3857 = (globals().get("NDVI_EXTENT_3857") or "").strip()
        extent_4326 = (globals().get("NDVI_EXTENT_LON_LAT") or "").strip()
    else:
        raise ValueError("extent_type must be 'gw' or 'ndvi'")

    if extent_3857:
        return extent_3857, "EPSG:3857"
    if extent_4326:
        return extent_4326, "EPSG:4326"

    raise ValueError(
        f"No extent provided for {extent_type}. Set {extent_type.upper()}_EXTENT_3857 or {extent_type.upper()}_EXTENT_LON_LAT in tsconfig.py"
    )


def extent_to_ee(extent_type="gw"):
    """
    Returns [lon_min, lat_min, lon_max, lat_max] (EPSG:4326)
    extent_type: "gw" for groundwater or "ndvi" for NDVI computation
    """
    extent_str, crs = _get_active_extent(extent_type)
    x1, y1, x2, y2 = _parse_qgis_extent(extent_str)

    xmin, xmax = sorted([x1, x2])
    ymin, ymax = sorted([y1, y2])

    if crs == "EPSG:4326":
        return [xmin, ymin, xmax, ymax]

    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lon_min, lat_min = transformer.transform(xmin, ymin)
    lon_max, lat_max = transformer.transform(xmax, ymax)
    return [lon_min, lat_min, lon_max, lat_max]


def extent_to_rd(extent_type="gw"):
    """
    Returns (xmin, xmax, ymin, ymax) in EPSG:28992
    extent_type: "gw" for groundwater or "ndvi" for NDVI computation
    """
    extent_str, crs = _get_active_extent(extent_type)
    x1, y1, x2, y2 = _parse_qgis_extent(extent_str)

    xmin, xmax = sorted([x1, x2])
    ymin, ymax = sorted([y1, y2])

    if crs == "EPSG:28992":
        return xmin, xmax, ymin, ymax

    transformer = Transformer.from_crs(crs, "EPSG:28992", always_xy=True)
    xmin_rd, ymin_rd = transformer.transform(xmin, ymin)
    xmax_rd, ymax_rd = transformer.transform(xmax, ymax)
    return (xmin_rd, xmax_rd, ymin_rd, ymax_rd)


def get_start_date(date_type="gw"):
    """
    Returns start date for specified type
    date_type: "gw" for groundwater or "ndvi" for NDVI computation
    """
    if date_type.lower() == "gw":
        return globals().get("START_DATE", "2025-01-01")
    elif date_type.lower() == "ndvi":
        return globals().get("NDVI_START_DATE", "2025-01-01")
    else:
        raise ValueError("date_type must be 'gw' or 'ndvi'")



