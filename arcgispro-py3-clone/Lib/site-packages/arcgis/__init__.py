__version__ = "2.4.1"

from arcgis.auth.tools import LazyLoader

from arcgis import env

os = LazyLoader("os")
features = LazyLoader("arcgis.features")
geocoding = LazyLoader("arcgis.geocoding")
geometry = LazyLoader("arcgis.geometry")
geoprocessing = LazyLoader("arcgis.geoprocessing")
network = LazyLoader("arcgis.network")
raster = LazyLoader("arcgis.raster")
realtime = LazyLoader("arcgis.realtime")
schematics = LazyLoader("arcgis.schematics")
mapping_layers = LazyLoader("arcgis.layers")
apps = LazyLoader("arcgis.apps")

if not os.environ.get("DISABLE_ARCGIS_LEARN", None) == "1":
    learn = LazyLoader("arcgis.learn")

from arcgis.gis import GIS
from arcgis.features.analysis import (
    calculate_density,
    find_hot_spots,
    find_outliers,
    find_point_clusters,
    interpolate_points,
    summarize_center_and_dispersion,
    connect_origins_to_destinations,
    create_buffers,
    create_drive_time_areas,
    find_nearest,
    plan_routes,
    enrich_layer,
    choose_best_facilities,
    create_viewshed,
    create_watersheds,
    derive_new_locations,
    find_centroids,
    find_existing_locations,
    find_similar_locations,
    trace_downstream,
    create_route_layers,
    dissolve_boundaries,
    extract_data,
    generate_tessellation,
    merge_layers,
    overlay_layers,
    aggregate_points,
    calculate_composite_index,
    join_features,
    summarize_center_and_dispersion,
    summarize_nearby,
    summarize_within,
)
from .geocoding import geocode


try:
    import pandas as pd
    from arcgis.features.geo import GeoAccessor
    from arcgis.features.geo import GeoSeriesAccessor


except ImportError as e:
    pass

try:
    # register with dask
    from .features.geo import _dask  # noqa
except Exception as e:
    pass


__all__ = [
    "GIS",
    "aggregate_points",
    "apps",
    "calculate_composite_index",
    "calculate_density",
    "choose_best_facilities",
    "connect_origins_to_destinations",
    "create_buffers",
    "create_drive_time_areas",
    "create_route_layers",
    "create_viewshed",
    "create_watersheds",
    "derive_new_locations",
    "dissolve_boundaries",
    "enrich_layer",
    "env",
    "extract_data",
    "features",
    "find_centroids",
    "find_existing_locations",
    "find_hot_spots",
    "find_nearest",
    "find_outliers",
    "find_point_clusters",
    "find_similar_locations",
    "generate_tessellation",
    "geocode",
    "geocoding",
    "geometry",
    "geoprocessing",
    "interpolate_points",
    "join_features",
    "learn",
    "mapping",
    "merge_layers",
    "network",
    "notebook",
    "overlay_layers",
    "plan_routes",
    "raster",
    "realtime",
    "schematics",
    "summarize_center_and_dispersion",
    "summarize_nearby",
    "summarize_within",
    "trace_downstream",
]
