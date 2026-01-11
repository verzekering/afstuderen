import uuid
from uuid import uuid4
import os
import re
import tempfile
from arcgis.auth.tools import LazyLoader
from arcgis._impl.common._utils import _date_handler
from arcgis._impl.common._mixins import PropertyMap
from arcgis._impl.common._isd import InsensitiveDict
from arcgis.auth.tools import LazyLoader

_arcgis_gis = LazyLoader("arcgis.gis")
_tool_utils = LazyLoader("arcgis.features.geo._tools._utils")
_common_utils = LazyLoader("arcgis._impl.common._utils")
_arcgis_gis = LazyLoader("arcgis.gis")
features = LazyLoader("arcgis.features")
json = LazyLoader("json")
pd = LazyLoader("pandas")

# Check for available engines
from arcgis._impl._geometry_engine import SELECTED_ENGINE, GeometryEngine

USE_ARCPY = USE_GDAL = USE_PYSHP = False

if SELECTED_ENGINE == GeometryEngine.SHAPEFILE:
    import shapefile

    SHPVERSION = [int(i) for i in shapefile.__version__.split(".")]
    USE_PYSHP = True
elif SELECTED_ENGINE == GeometryEngine.GDAL:
    from osgeo import ogr, osr

    USE_GDAL = True
elif SELECTED_ENGINE == GeometryEngine.ARCPY:
    import arcpy

    USE_ARCPY = True


def _json_encode_params(postdata):
    for k, v in postdata.items():
        if isinstance(v, (dict, list, tuple, bool)):
            postdata[k] = json.dumps(v, default=_date_handler)
        elif isinstance(v, PropertyMap):
            postdata[k] = json.dumps(dict(v), default=_date_handler)
        elif isinstance(v, InsensitiveDict):
            postdata[k] = v.json

    return postdata


def _create_file(df, file_type, output_dir=None, **kwargs):
    """
    Create a file from a DataFrame.
    This method is used by the import_as_item method as well as the insert_layer method in the GeoAccessor.
    """
    # File Type Dictionary
    file_types = {
        "File Geodatabase": "gdb",
        "Shapefile": "shp",
        "CSV": "csv",
    }

    # Generate random service name if not provided
    service_name = kwargs.get("service_name") or f"a{uuid4().hex[:5]}"
    sanitize_columns = kwargs.pop("sanitize_columns", True)

    # Use provided output_dir or create a temporary directory
    if not output_dir:
        temp_dir = tempfile.mkdtemp()
    else:
        temp_dir = output_dir
        os.makedirs(temp_dir, exist_ok=True)

    # Construct file paths
    file_extension = file_types[file_type]
    name = f"{service_name}.{file_extension}"
    location = os.path.join(temp_dir, name)

    if file_type in ["File Geodatabase", "Shapefile"]:
        temp_zip = os.path.join(temp_dir, f"{service_name}.zip")

        if file_type == "File Geodatabase" and USE_ARCPY:
            # Create empty File Geodatabase with ArcPy
            fgdb = _tool_utils.run_and_hide(
                fn=arcpy.CreateFileGDB_management,
                **{"out_folder_path": temp_dir, "out_name": name},
            )[0]
            location = os.path.join(fgdb, os.path.basename(temp_dir))
            zip_loc = os.path.join(temp_dir, name)
        elif file_type == "File Geodatabase" and USE_GDAL:
            zip_loc = location
        else:
            zip_loc = temp_dir

        # Write the DataFrame to a feature class
        df.spatial.to_featureclass(
            location=location,
            sanitize_columns=sanitize_columns,
            has_m=kwargs.get("has_m", False),
            has_z=kwargs.get("has_z", False),
        )

        # zip it
        file = _common_utils.zipws(path=zip_loc, outfile=temp_zip, keep=True)
        f = open(file, "r")
        f.close()
    elif file_type == "CSV":
        # Write the DataFrame to a CSV file
        file = os.path.join(temp_dir, f"{service_name}.csv")
        with open(file, "w", newline="") as my_csv:
            df.to_csv(my_csv)

    # Return the file path
    return file


def _find_service_name(
    gis: "GIS", name: str, service_type: str = "featureService"
) -> str:
    i: int = 1
    if name == "data":
        name = "mydata"
    new_name: str = name
    while gis.content.is_service_name_available(new_name, service_type) == False:
        new_name = f"{name}{i}"
        if gis.content.is_service_name_available(new_name, "featureService"):
            break

        i += 1
        if i > 10:
            new_name = f"{name}{uuid.uuid4().hex[:3]}"
    return new_name


def _create_items(gis, file, file_type, **kwargs):
    """
    Create the file item and publish.
    """
    service_name = kwargs.pop("service_name", None)
    title = kwargs.pop("title", os.path.basename(file))
    tags = kwargs.pop("tags", file_type)
    folder = kwargs.pop("folder", None)
    # add item to portal
    if folder:
        # Get specific folder
        folder = gis.content.folders._get_or_create(folder)
    else:
        # Get the root folder
        folder = gis.content.folders.get()
    file_item = folder.add(
        item_properties={
            "title": title,
            "type": file_type,
            "tags": tags,
        },
        file=file,
    ).result()

    if file_type == "CSV":
        # analyze the csv for publish params
        publish_parameters = gis.content.analyze(item=file_item, file_type="csv")[
            "publishParameters"
        ]
        #  For the CSV case, to keep with legacy code, set the
        #  name to the file name.
        if service_name is None:
            service_name = file_item["name"]
        #  ensure unique service name
        service_name = _find_service_name(gis, service_name, "featureService")
        publish_parameters["name"] = service_name
        publish_parameters["locationType"] = None
    else:
        # start creating publish params from new file item
        publish_parameters = {
            "name": "data",
            "maxRecordCount": 2000,
            "hasStaticData": True,
            "layerInfo": {"capabilities": "Query"},
        }
        if service_name is None:
            service_name = re.sub(r"[\s\W]", "_", title.replace(" ", ""))

        #  get a unique service name
        service_name = _find_service_name(gis, service_name, "featureService")
        publish_parameters["name"] = service_name

    new_item = file_item.publish(
        publish_parameters=publish_parameters,
        item_id=kwargs.pop("item_id", None),
    )
    return file_item, new_item


def _perform_overwrite(fl_index, flc_manager, layer_definition):
    # update the name and id to represent correct values
    layer_definition["id"] = fl_index
    layer_definition["name"] = flc_manager.properties.layers[fl_index]["name"]

    # Perform edit on the flc
    # Step 1: Preserve layer ids
    revert = False
    if (
        "preserveLayerIds" not in flc_manager.properties
        or flc_manager.properties["preserveLayerIds"] is not True
    ):
        flc_manager.update_definition({"preserveLayerIds": True})
        revert = True
    # Step 2: Delete layer from definition
    flc_manager.delete_from_definition({"layers": [{"id": fl_index}]})
    # Step 3: Add new layer to definition
    flc_manager.add_to_definition({"layers": [dict(layer_definition)]})
    # Step 4: Cleanup
    if revert:
        flc_manager.update_definition({"preserveLayerIds": False})


def _add_features(file_type, fl_index, file_item, fs_item, new_item, gis=None):
    if file_type.lower() == "csv":
        source_info = gis.content.analyze(item=file_item)["publishParameters"]
        fs_item.tables[fl_index].append(
            item_id=file_item.id,
            upload_format=file_type.lower(),
            source_info=source_info,
        )
    elif file_type.lower() == "shapefile" or (
        len(fs_item.layers) > 0
        and "filegdb" in fs_item.layers[fl_index].properties.supportedAppendFormats
    ):
        # correct file type for append method
        if file_type.lower() == "file geodatabase":
            file_type = "filegdb"
        else:
            file_type = "shapefile"
        fs_item.layers[fl_index].append(item_id=file_item.id, upload_format=file_type)
    else:
        # When filegdb not supported through append, use featureCollection
        source_info = gis.content.analyze(
            item=file_item, file_type=file_type.lower().replace(" ", "")
        )["publishParameters"]
        new_features = new_item.layers[0].query().features
        fs_item.layers[fl_index].edit_features(adds=new_features)


############################################
def import_as_item(gis, df, **kwargs):
    # House Keeping
    overwrite = kwargs.pop("overwrite", False)

    if isinstance(df, features.FeatureSet):
        df = df.sdf

    # Check whether it will be a layer or a table
    if features.geo._is_geoenabled(df):
        # layer
        if USE_ARCPY == False and USE_PYSHP == False and USE_GDAL == False:
            raise Exception(
                "Spatially enabled DataFrame's must have either pyshp, gdal, or"
                + " arcpy available to use import_data"
            )
        if USE_ARCPY or USE_GDAL:
            file_type = "File Geodatabase"
        else:
            file_type = "Shapefile"
    else:
        # table
        file_type = "CSV"

    # Create the file
    file = _create_file(df, file_type, **kwargs)
    file_item, new_item = _create_items(gis, file, file_type, **kwargs)
    # normal workflow, simply create file item and new item
    # If not overwrite or insert, return the new item
    if not overwrite:
        return new_item
    else:
        try:
            # Get user defined parameters to continue the workflow and either overwrite or insert
            fs_dict = kwargs.pop("service", None)
            if fs_dict is None:
                raise ValueError(
                    "If overwrite is True, then the feature service id needs to be specified in the `service` parameter."
                )

            # Get the fs_id and make sure correct format
            fs_id = fs_dict["featureServiceId"]
            if fs_id is None:
                raise ValueError(
                    "The provided feature service id cannot be found. Please check it is correct and try again."
                )
            elif isinstance(fs_id, _arcgis_gis.Item):
                fs_id = fs_id.itemid

            # Create the feature layer manager for the existing feature service
            fs_item = gis.content.get(fs_id)
            if fs_item is None:
                raise ValueError(
                    "The provided feature service id cannot be found. Please check it is correct and try again."
                )
            flc_manager = features.FeatureLayerCollection.fromitem(fs_item).manager
            # Index passed in for overwrite, None for insert
            index = fs_dict["layer"]
            lyr_def = dict(new_item.layers[0].properties)
            _perform_overwrite(index, flc_manager, lyr_def)

            # This pushes the features and adds new dependencies
            _add_features(file_type, index, file_item, fs_item, new_item, gis)
        except Exception as e:
            # Clean up the items if an error occurs
            gis.content.delete_items([file_item, new_item], permanent=True)
            raise e
        finally:
            # Clean up the new item
            gis.content.delete_items([file_item, new_item], permanent=True)
        return fs_item


def import_as_fc(gis, df, **kwargs):
    # Get kwargs
    address_fields = kwargs.pop("address_fields", None)
    item_id = kwargs.pop("item_id", None)

    # Step 1: Analyze the df as a csv
    if kwargs.get("geocode_url", None):
        geocode_url = kwargs.get("geocode_url")
    else:
        locators = [
            gc["url"]
            for gc in gis.properties.helperServices.geocode
            if gc.get("batch", False)
        ]
        if len(locators) == 0:
            raise Exception("No batch geocoding service found.")
        geocode_url = locators[0]

    path = gis._public_rest_url + "content/features/analyze"

    postdata = {
        "f": "json",
        "text": df.to_csv(index=False),
        "filetype": "csv",
        "analyzeParameters": {
            "enableGlobalGeocoding": "true",
            "sourceLocale": kwargs.pop("source_locale", "us-en"),
            "sourceCountry": kwargs.pop("source_country", ""),
            "sourceCountryHint": kwargs.pop("country_hint", ""),
            "geocodeServiceUrl": geocode_url,
        },
    }
    if address_fields is not None:
        postdata["analyzeParameters"]["locationType"] = "address"

    postdata = _json_encode_params(postdata)
    resp = gis._con._session.post(url=path, data=postdata, timeout=600)
    res = resp.json()

    # Step 2: Prep parameters to generate features
    if address_fields is not None:
        res["publishParameters"].update({"addressFields": address_fields})
    path = gis._public_rest_url + "content/features/generate"
    postdata = {
        "f": "json",
        "text": df.to_csv(index=False),
        "filetype": "csv",
        "publishParameters": json.dumps(res["publishParameters"]),
    }
    if item_id:
        postdata["itemIdToCreate"] = item_id

    if isinstance(df, pd.DataFrame) and "location_type" not in kwargs:
        # Step 2: Generate features
        postdata = _json_encode_params(postdata)
        resp = gis._con._session.post(path, postdata)
        res_generate = resp.json()
    elif (isinstance(df, pd.DataFrame) and "location_type" in kwargs) or (
        isinstance(df, pd.DataFrame) and address_fields
    ):
        # Step 2: Generate features
        if address_fields is not None:
            res["publishParameters"].update({"addressFields": address_fields})

        update_dict = {}
        update_dict["locationType"] = kwargs.pop("location_type", "")
        update_dict["latitudeFieldName"] = kwargs.pop("latitude_field", "")
        update_dict["longitudeFieldName"] = kwargs.pop("longitude_field", "")
        update_dict["coordinateFieldName"] = kwargs.pop("coordinate_field_name", "")
        update_dict["coordinateFieldType"] = kwargs.pop("coordinate_field_type", "")
        rk = []
        for k, v in update_dict.items():
            if v == "":
                rk.append(k)
        for k in rk:
            del update_dict[k]
        res["publishParameters"].update(update_dict)

        postdata = _json_encode_params(postdata)
        resp = gis._con._session.post(
            path, postdata
        )  # , use_ordered_dict=True) - OrderedDict >36< _mixins.PropertyMap

        res_generate = resp.json()

    # Step 3: Return
    if res_generate:
        return features.FeatureCollection(
            res_generate["featureCollection"]["layers"][0]
        )
    else:
        return None
