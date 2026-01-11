from arcgis.gis import GIS, Item
from arcgis.features import FeatureLayer
import itertools
import re
from collections import OrderedDict

# any item that can contain another item or require another to exist
_COMPLEX_ITEMS = frozenset(
    [
        "Web Map",
        "Web Scene",
        "Web Mapping Application",
        "Dashboard",
        "Feature Service",
        "StoryMap",
        "Workforce Project",
        "Form",
        "QuickCapture Project",
        "Notebook",
        "Feature Collection",
        "Web Experience",
        "Hub Site Application",
        "Hub Page",
        "Solution",
        "Geoprocessing Service",
    ]
)

_RELATIONSHIPS = {
    "API Key": {"forward": ["APIKey2Item"], "reverse": []},
    "Application Configuration": {"forward": [], "reverse": ["Map2AppConfig"]},
    "Code Attachment": {"forward": [], "reverse": ["MobileApp2Code", "WMA2Code"]},
    "Compact Tile Package": {"forward": [], "reverse": ["Service2Data"]},
    "CSV": {"forward": [], "reverse": ["Service2Data"]},
    "DesktopStyle": {"forward": [], "reverse": ["WebStyle2DesktopStyle"]},
    "Feature Collection": {
        "forward": [],
        "reverse": ["Service2Data", "Map2FeatureCollection"],
    },
    "Feature Service": {
        "forward": [
            "Service2Data",
            "Service2Layer",
            "Service2Service",
            "TrackView2Map",
        ],
        "reverse": [
            "Map2Service",
            "Service2Data",
            "Service2Layer",
            "Survey2Data",
            "Survey2Service",
        ],
    },
    "File Geodatabase": {"forward": [], "reverse": ["Service2Data"]},
    "Form": {"forward": ["Survey2Data", "Survey2Service"], "reverse": []},
    "GeoJson": {"forward": [], "reverse": ["Service2Data"]},
    "GeoPackage": {"forward": [], "reverse": ["Service2Data"]},
    "Geoprocessing Service": {"forward": [], "reverse": ["Notebook2WebTool"]},
    "Hosted Feature Service": {
        "forward": ["Service2Data", "Service2Route"],
        "reverse": [],
    },
    "Image": {"forward": [], "reverse": ["Item2Attachment", "Item2Report"]},
    "Image Collection": {"forward": [], "reverse": ["Service2Data"]},
    "Image Service": {"forward": [], "reverse": ["Map2Service"]},
    "Indoors Map Configuration": {"forward": [], "reverse": ["Map2IndoorsConfig"]},
    "Map Area": {
        "forward": ["Area2CustomPackage", "Area2Package"],
        "reverse": ["Map2Area"],
    },
    "Map Package": {
        "forward": [],
        "reverse": ["Area2CustomPackage", "Area2Package", "Survey2Data"],
    },
    "Map Service": {
        "forward": ["Service2Data"],
        "reverse": ["Service2Service", "Map2Service"],
    },
    "Microsoft Excel": {
        "forward": [],
        "reverse": ["Item2Attachment", "Item2Report", "Service2Data"],
    },
    "Microsoft PowerPoint": {
        "forward": [],
        "reverse": ["Item2Attachment", "Item2Report"],
    },
    "Microsoft Word": {
        "forward": [],
        "reverse": ["Item2Attachment", "Item2Report", "Survey2Data"],
    },
    "Mission": {"forward": ["Mission2Item"], "reverse": []},
    "Mobile Application": {"forward": ["MobileApp2Code"], "reverse": []},
    "Notebook": {"forward": ["Notebook2WebTool"], "reverse": []},
    "OGCFeatureServer": {"forward": ["Service2Data"], "reverse": []},
    "PDF": {"forward": [], "reverse": ["Item2Attachment", "Item2Report"]},
    "Route Layer": {"forward": [], "reverse": ["Service2Route"]},
    "Scene Package": {"forward": [], "reverse": ["Service2Data"]},
    "Scene Service": {"forward": ["Service2Data"], "reverse": []},
    "Service Definition": {"forward": [], "reverse": ["Service2Data"]},
    "Shapefile": {"forward": [], "reverse": ["Service2Data"]},
    "SQLite Geodatabase": {
        "forward": [],
        "reverse": ["Area2CustomPackage", "Area2Package", "Service2Data"],
    },
    "StoryMap": {"forward": [], "reverse": ["Theme2Story"]},
    "StoryMap Theme": {"forward": ["Theme2Story"], "reverse": []},
    "Style": {
        "forward": ["Service2Style", "Style2Style", "WebStyle2DesktopStyle"],
        "reverse": ["Service2Style", "Style2Style"],
    },
    "Survey123 Add In": {"forward": ["SurveyAddIn2Data"], "reverse": []},
    "Tile Package": {
        "forward": [],
        "reverse": [
            "Area2CustomPackage",
            "Area2Package",
            "Service2Data",
            "Survey2Data",
        ],
    },
    "Vector Tile Package": {
        "forward": [],
        "reverse": [
            "Area2CustomPackage",
            "Area2Package",
            "Service2Data",
            "Survey2Data",
        ],
    },
    "Vector Tile Service": {
        "forward": ["Service2Data", "Service2Style", "Style2Style"],
        "reverse": ["Service2Style", "Style2Style"],
    },
    "Visio Document": {"forward": [], "reverse": ["Item2Attachment", "Item2Report"]},
    "Web Map": {
        "forward": [
            "Map2AppConfig",
            "Map2Area",
            "Map2FeatureCollection",
            "Map2Service",
            "Map2IndoorsConfig",
        ],
        "reverse": ["Survey2Data", "TrackView2Map"],
    },
    "Web Mapping Application": {"forward": ["WMA2Code"], "reverse": []},
    "WFS": {"forward": ["Service2Data"], "reverse": []},
    "WMS": {"forward": ["Service2Data"], "reverse": []},
    "WMTS": {"forward": ["Service2Data"], "reverse": []},
}

# regular expression to find GUID
_REGEX_GUID = r"[0-9a-f]{8}[0-9a-f]{4}[1-5][0-9a-f]{3}[89ab][0-9a-f]{3}[0-9a-f]{12}"


def _get_item_dependencies(itemid, gis, include_related=True, include_reverse=False):
    if isinstance(itemid, Item):
        item = itemid
    else:
        item = gis.content.get(itemid)

    if not item:
        return []

    dependencies = []
    item_type = item["type"]

    if item_type in ["Web Map", "Web Scene"]:
        dependencies = _parse_webmap(item)
    elif item_type == "Dashboard":
        dependencies = _parse_dashboard(item)
    elif item_type == "Web Experience":
        dependencies = _parse_exb(item)
    elif item_type == "Web Mapping Application":
        dependencies = _parse_wma(item)
    elif item_type == "StoryMap":
        dependencies = _parse_storymap(item)
    elif item_type in ["Hub Site Application", "Hub Page"]:
        dependencies = _parse_hub(item)
    elif item_type == "Geoprocessing Service":
        dependencies = _parse_gp_service(item)
    elif item_type == "QuickCapture Project":
        dependencies = _parse_qc(item)
    else:
        dependencies = []

    if include_related:
        # if reverse deps, include them in _get_related_items
        forward_deps, reverse_deps = _get_related_items(
            item,
            forward=True,
            reverse=include_reverse,
        )
        dependencies.extend(
            f.itemid for f in forward_deps if f.itemid not in dependencies
        )
        # if reverse deps, return a tuple, second containing reverse deps
        if include_reverse:
            rd = [r.itemid for r in reverse_deps]
            return dependencies, rd

    return dependencies


def _get_related_items(item, forward=True, reverse=True):
    if not forward and not reverse:
        raise ValueError("At least one direction must be specified.")

    forward_deps = []
    reverse_deps = []
    # leaving out Listed2ImplicitlyListed for now due to issues
    f_rel_types = [
        "Item2Attachment",
        "Item2Report",
        "Listed2Provisioned",
        # "Listed2ImplicitlyListed",
        "Solution2Item",
    ]
    r_rel_types = [
        "Listed2Provisioned",
        # "Listed2ImplicitlyListed",
        "SurveyAddIn2Data",
        "Solution2Item",
        "APIKey2Item",
        "Mission2Item",
    ]
    if item.type in _RELATIONSHIPS:
        f_rel_types.extend(_RELATIONSHIPS[item.type]["forward"])
        r_rel_types.extend(_RELATIONSHIPS[item.type]["reverse"])
        if item.type == "Feature Service" and "View Service" not in item.typeKeywords:
            f_rel_types.remove("Service2Service")

    if forward:
        for rel_type in f_rel_types:
            rel_items = item.related_items(rel_type, direction="forward")
            forward_deps.extend(f for f in rel_items if f not in forward_deps)

    if reverse:
        for rel_type in r_rel_types:
            rel_items = item.related_items(rel_type, direction="reverse")
            reverse_deps.extend(r for r in rel_items if r not in reverse_deps)

    return forward_deps, reverse_deps


def _get_related_item_dict(item, forward=True, reverse=True):
    if not forward and not reverse:
        raise ValueError("At least one direction must be specified.")

    rel_item_dict = {}
    # leaving out Listed2ImplicitlyListed for now due to issues
    f_rel_types = [
        "Item2Attachment",
        "Item2Report",
        "Listed2Provisioned",
        # "Listed2ImplicitlyListed",
        "Solution2Item",
    ]
    r_rel_types = [
        "Listed2Provisioned",
        # "Listed2ImplicitlyListed",
        "SurveyAddIn2Data",
        "Solution2Item",
        "APIKey2Item",
        "Mission2Item",
    ]
    if item.type in _RELATIONSHIPS:
        f_rel_types.extend(_RELATIONSHIPS[item.type]["forward"])
        r_rel_types.extend(_RELATIONSHIPS[item.type]["reverse"])
        if item.type == "Feature Service" and "View Service" not in item.typeKeywords:
            f_rel_types.remove("Service2Service")

    if forward:
        f_rel_dict = {}
        for rel_type in f_rel_types:
            rel_items = item.related_items(rel_type, direction="forward")
            if rel_items:
                f_rel_dict[rel_type] = [rel_item.id for rel_item in rel_items]
        rel_item_dict["forward"] = f_rel_dict

    if reverse:
        r_rel_dict = {}
        for rel_type in r_rel_types:
            rel_items = item.related_items(rel_type, direction="reverse")
            if rel_items:
                r_rel_dict[rel_type] = [rel_item.id for rel_item in rel_items]
        rel_item_dict["reverse"] = r_rel_dict

    return rel_item_dict


def _parse_webmap(item):
    items = []
    services = []
    webmap_json = item.get_data()

    def process_op_layer(layer):
        if layer.get("layerType") == "GroupLayer":
            for sublayer in layer.get("layers"):
                process_op_layer(sublayer)

        else:
            if "itemId" in layer:
                if layer["itemId"] not in items:
                    items.append(layer["itemId"])
            elif "url" in layer:
                try:
                    sid = FeatureLayer(layer["url"]).properties["serviceItemId"]
                    if sid not in items:
                        items.append(sid)
                except:
                    if layer["url"] not in services:
                        services.append(layer["url"])

    for op_layer in webmap_json.get("operationalLayers"):
        process_op_layer(op_layer)

    items.extend(services)
    return items


def _parse_dashboard(item):
    # shoutout Dan Yaw for first iteration of this function
    deps = []
    structure = item.get_data()
    widgets1 = structure.get("widgets", [])
    widgets2 = structure.get("desktopView", {}).get("widgets", [])
    widgets = widgets1 + widgets2

    for widget in widgets:
        if widget.get("type") == "mapWidget":
            deps.append(widget.get("itemId"))
            continue
        try:
            for dataset in widget.get("datasets", []):
                if dataset.get("type") == "serviceDataset":
                    data_source = dataset.get("dataSource", {})
                    if data_source.get("type") == "itemDataSource":
                        deps.append(data_source.get("itemId"))
                    elif data_source.get("type") == "arcadeDataSource":
                        script = data_source.get("script")
                        deps.extend(_find_regex(script, _REGEX_GUID, []))
        except:
            pass

    return deps


def _parse_exb(item):
    pub_data = item.get_data()
    draft_data = item.resources.get("config/config.json")

    itemids = []

    for data in [pub_data, draft_data]:
        data_sources = data.get("dataSources", {})
        for ds in data_sources.values():
            if "itemId" in ds and ds["itemId"] not in itemids:
                itemids.append(ds["itemId"])

        widgets = data.get("widgets", [])
        try:
            for widg_dict in widgets.values():
                config = widg_dict.get("config", {})
                if "surveyItemId" in config and config["surveyItemId"] not in itemids:
                    itemids.append(config["surveyItemId"])
        except:
            pass

    return itemids


def _parse_wma(item):
    data = item.get_data()
    itemids = set()

    if "map" in data:
        try:
            itemids.add(data["map"]["itemId"])
        except:
            pass

    if "dataSource" in data:
        data_sources = data["dataSource"].get("dataSources")

        for ds in data_sources.values():
            try:
                itemids.add(ds["itemId"])
            except:
                pass

    try:
        itemids.add(data["values"]["webmap"])
    except:
        pass

    return list(itemids)


def _parse_storymap(item):
    itemids = []
    data_list = [item.get_data()]
    draft_name = None
    for res in item.resources.list():
        if "draft" in res["resource"] and "express" not in res["resource"]:
            draft_name = res["resource"]

    if draft_name:
        draft_data = item.resources.get(draft_name)
        data_list.append(draft_data)

    for draft in data_list:
        if "resources" not in draft:
            continue
        web_maps = set(
            [
                v["data"]["itemId"]
                for k, v in draft["resources"].items()
                if v["type"].lower().find("webmap") > -1
            ]
        )

        themes = set(
            [
                v["data"]["themeItemId"]
                for k, v in draft["resources"].items()
                if v["type"].lower().find("story-theme") > -1
                and "themeItemId" in v["data"].keys()
            ]
        )

        for ids in [web_maps, themes]:
            for i in ids:
                if i not in itemids:
                    itemids.append(i)

    return itemids


def _parse_hub(item):
    itemids = set()
    pub_data = item.get_data()
    draft_name = None
    for r in item.resources.list():
        if "draft" in r["resource"]:
            draft_name = r["resource"]
            break
    if draft_name:
        draft_data = item.resources.get(draft_name)["data"]
    else:
        draft_data = None

    def _parse_hub_sections(data):
        dep_ids = set()
        for section in data["values"]["layout"]["sections"]:
            for row in section["rows"]:
                for card in row["cards"]:
                    c = card["component"]
                    if c["name"] == "webmap-card":
                        for w in ["webmap", "webscene"]:
                            if c["settings"].get(w, None):
                                dep_ids.add(c["settings"][w])
                    elif c["name"] in ["app-card", "chart-card"]:
                        dep_ids.add(c["settings"]["itemId"])
                    elif c["name"] == "survey-card":
                        dep_ids.add(c["settings"]["surveyId"])
        return dep_ids

    for data in [pub_data, draft_data]:
        if data:
            itemids.update(_parse_hub_sections(data))

    return list(itemids)


def _parse_gp_service(item):
    try:
        structure = item.resources.get("webtoolDefinition.json")
        return [structure["jsonProperties"]["notebookId"]]
    except:
        return []


def _parse_qc(item):
    try:
        structure = item.resources.get("qc.project.json")
        deps = set()
        deps.add(structure["basemap"]["itemId"])
        for ds in structure["dataSources"]:
            deps.add(ds["featureServiceItemId"])
        return list(deps)
    except:
        return []


def _find_regex(i, regex, res=[]):
    """
    Takes a dict with nested lists and dicts,
    and searches all dicts for a key of the field
    provided.
    """
    if isinstance(i, dict):
        for v in i.values():
            _find_regex(v, regex, res)
    elif isinstance(i, list):
        for v in i:
            _find_regex(v, regex, res)
    elif isinstance(i, str):
        matches = re.findall(regex, i, re.MULTILINE)
        if matches:
            res.append(matches)
    # Flattening list of lists
    results = list(itertools.chain(*res))
    # Removing duplicates
    results = list(OrderedDict.fromkeys(results))
    return results
