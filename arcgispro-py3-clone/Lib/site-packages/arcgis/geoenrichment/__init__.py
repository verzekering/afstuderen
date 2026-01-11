"""
The ``arcgis.geoenrichment`` module provides access to Business Analyst's 
demographic and jurisdictional areas data through enrichment, standard 
geography queries and reporting. The source for analysis can be either 
local or remote. Using a local source requires ArcGIS Pro with the 
Business Analyst extension and at least one country's data pack to be 
installed. A remote source requires access to a property configured Web 
GIS. A Web GIS can either be ArcGIS Online or an instance of ArcGIS 
Enterprise with Business Analyst.

.. note::
    Organizations should review the
    `data attributions <https://www.esri.com/en-us/legal/terms/data-attributions>`_
    and `Master Agreement <https://www.esri.com/content/dam/esrisites/en-us/media/legal/ma-full/ma-full.pdf>`_
    to make sure they are in compliance when geoenriching data and making it
    available to other systems.
"""

__all__ = [
    "BufferStudyArea",
    "Country",
    "create_report",
    "enrich",
    "get_countries",
    "service_limits",
    "standard_geography_query",
    "interesting_facts",
]

from .enrichment import (
    BufferStudyArea,
    Country,
    create_report,
    enrich,
    get_countries,
    service_limits,
    standard_geography_query,
    interesting_facts,
)
