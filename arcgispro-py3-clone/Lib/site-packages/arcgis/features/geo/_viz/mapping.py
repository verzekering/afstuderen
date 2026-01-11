"""
Mapping Holds the Plot function for creating a FeatureCollection JSON plus the render options
"""

from typing import Optional, Union
import pandas as pd

import arcgis
from arcgis.auth.tools import LazyLoader

_imports = LazyLoader("arcgis._impl.imports")
renderers = LazyLoader("arcgis.map.renderers")
rm = LazyLoader("arcgis.map.definitions._renderer_metaclass")


def plot(
    df,
    map: Optional["arcgis.map.Map"] = None,
    name: Optional[str] = None,
    renderer: Optional[
        Union[
            renderers.HeatmapRenderer,
            renderers.SimpleRenderer,
            renderers.UniqueValueRenderer,
            renderers.ClassBreaksRenderer,
            renderers.DotDensityRenderer,
        ]
    ] = None,
    **kwargs,
):
    """

    Plot draws the data on a web map. The user can describe in simple terms how to
    renderer spatial data using symbol.  To make the process simpler a palette
    for which colors are drawn from can be used instead of explicit colors.


    ======================  =========================================================
    **Explicit Argument**   **Description**
    ----------------------  ---------------------------------------------------------
    df                      Required Spatially Enabled DataFrame or GeoSeries. This is the data
                            to map.
    ----------------------  ---------------------------------------------------------
    map                     Optional Map object. This is the map to display the
                            data on.
    ----------------------  ---------------------------------------------------------
    name                    Optional string. The name to assign as a title of the map widget.
    ----------------------  ---------------------------------------------------------
    renderer                Optional Renderer object. The renderer to use to draw the data.
                            To create a renderer dataclass use the renderers module in the
                            arcgis.map module.
    ======================  =========================================================

    """

    if not hasattr(df, "spatial") and not hasattr(df, "geom"):
        raise ValueError("DataFrame or Series must be spatially enabled.")

    if isinstance(df, pd.Series) and df.dtype.name == "geometry":
        fid = df.index.tolist()
        sdf = pd.DataFrame(data=fid, columns=["OID"])
        sdf["SHAPE"] = df
        return plot(
            df=sdf,
            map_widget=map,
            name=name,
            renderer=renderer,
            **kwargs,
        )

    if name is None:
        import uuid

        name = uuid.uuid4().hex[:7]
    if map is None:
        arcgismapping = _imports.get_arcgis_map_mod(True)
        map = arcgismapping.Map()
    import string

    trantab = str.maketrans(string.punctuation, "_" * len(string.punctuation))
    col_new = [col.translate(trantab) for col in df.columns]
    col_old = df.columns.tolist()
    df.columns = col_new
    drawing_info = {}
    if renderer is not None:
        drawing_info["renderer"] = renderer
    elif hasattr(df.spatial, "renderer") and df.spatial.renderer is not None:
        # Create the correct renderer
        drawing_info["renderer"] = rm.FactoryWorker(
            renderer_type=df.spatial.renderer["type"],
            renderer=df.spatial.renderer,
        )
    map.content.add(df, drawing_info=drawing_info)
    df.columns = col_old

    return True
