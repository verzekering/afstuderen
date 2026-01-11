from __future__ import annotations
from arcgis.auth.tools import LazyLoader

_arcgis = LazyLoader("arcgis")


def is_valid_item_id(item_id: str) -> bool:
    """Check if the item id is valid"""
    return isinstance(item_id, str) and len(item_id) == 32


def _get_item_url(item: _arcgis.gis.Item) -> str:
    """returns the proper URL based on the user's form of logging in"""
    gis: _arcgis.gis.GIS = item._gis
    if gis._use_private_url_only:
        if hasattr(item, "privateUrl") and getattr(item, "privateUrl", None):
            return getattr(item, "privateUrl")
        elif getattr(item, "url", None) and getattr(item, "privateUrl", None) is None:
            url_check = gis._private_service_url(item.url)
            if "privateServiceUrl" in url_check:
                return url_check.get("privateServiceUrl")

            return url_check.get("serviceUrl")
        elif getattr(item, "url", None):
            return item.url
        else:
            return None
    else:
        if hasattr(item, "url"):
            return item.url
        else:
            return None
    return None
