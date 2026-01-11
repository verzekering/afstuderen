from arcgis.auth.api import LazyLoader

hub = LazyLoader("arcgis.apps.hub")
workforce = LazyLoader("arcgis.apps.workforce")
storymap = LazyLoader("arcgis.apps.storymap")
survey123 = LazyLoader("arcgis.apps.survey123")
tracker = LazyLoader("arcgis.apps.tracker")
dashboard = LazyLoader("arcgis.apps.dashboard")
expbuilder = LazyLoader("arcgis.apps.expbuilder")
itemgraph = LazyLoader("arcgis.apps.itemgraph")


from ._url_schemes import build_collector_url
from ._url_schemes import build_field_maps_url
from ._url_schemes import build_explorer_url
from ._url_schemes import build_navigator_url
from ._url_schemes import build_survey123_url
from ._url_schemes import build_tracker_url
from ._url_schemes import build_workforce_url
