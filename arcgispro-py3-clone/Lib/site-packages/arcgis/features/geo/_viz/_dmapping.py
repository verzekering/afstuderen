# Dask Mapping
"""
Mapping Holds the Plot function for creating a FeatureCollection JSON plus the render options
"""
import uuid
import json
import dask.dataframe as dd
import arcgis
from arcgis.auth.tools import LazyLoader

_imports = LazyLoader("arcgis._impl.imports")


###########################################################################
##  Helper Lambda
###########################################################################
def _fn_method(a, op, **kwargs):
    return getattr(a, op)(**kwargs)


###########################################################################
def dask_plot(df, map_widget=None, renderer=None):
    """

    Plot draws the data on a web map. The user can describe in simple terms how to
    renderer spatial data using symbol.  To make the process simpler a pallette
    for which colors are drawn from can be used instead of explicit colors.


    ======================  =========================================================
    **Explicit Argument**   **Description**
    ----------------------  ---------------------------------------------------------
    df                      required Dask DataFrame. This is the data to map.
    ----------------------  ---------------------------------------------------------
    map_widget              optional Map object. This is the map to display the
                            data on.
    ----------------------  ---------------------------------------------------------
    renderer                Optional Renderer dataclass.  The renderer definition for the dataset.
    ======================  =========================================================



    """
    renderer = None
    name = None
    map_exists = True
    if not hasattr(df, "spatial"):
        raise ValueError("DataFrame must be spatially enabled.")

    if df.spatial.renderer:
        renderer = json.loads(df.spatial.renderer.json)
    if name is None:
        name = uuid.uuid4().hex[:7]
    if not map_widget:
        arcgismapping = _imports.get_arcgis_map_mod(True)
        map_exists = False
        map_widget = arcgismapping.Map()
    assert isinstance(df, dd.DataFrame)

    feature_collections = df.map_partitions(
        lambda part: _fn_method(part.spatial, "to_feature_collection", **{"name": name})
    ).compute()
    if len(feature_collections) == 1:
        if map_exists:
            drawing_info = {"renderer": renderer} if renderer else {}
            map_widget.content.add(
                feature_collections[0],
                drawing_info=drawing_info,
                options={"title": name},
            )
        else:
            drawing_info = {"renderer": renderer} if renderer else {}
            map_widget.content.add(
                feature_collections[0],
                drawing_info=drawing_info,
                options={"title": name},
            )
    else:
        main_fc = feature_collections[0]
        main_fc.layer["layerDefinition"]["drawingInfo"]["renderer"] = renderer.dict()
        for fc in feature_collections[1:]:
            main_fc.properties["featureSet"]["features"].extend(
                fc.properties["featureSet"]["features"]
            )
            # fc.layer['layerDefinition']['drawingInfo']['renderer'] = renderer
        if map_exists:
            map_widget.content.add(main_fc, options={"title": name})
        else:
            map_widget.content.add(main_fc, options={"title": name})
    if map_exists is False:
        return map_widget
    return True
