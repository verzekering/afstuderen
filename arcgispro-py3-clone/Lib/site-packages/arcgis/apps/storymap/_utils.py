from __future__ import annotations
import warnings
import tempfile
from time import sleep
from typing import Optional, Union
import uuid
from arcgis.auth.tools import LazyLoader
import re

arcgis = LazyLoader("arcgis")
Content = LazyLoader("arcgis.apps.storymap.story_content")
collection = LazyLoader("arcgis.apps.storymap.collection")
storymap = LazyLoader("arcgis.apps.storymap.story")
briefing = LazyLoader("arcgis.apps.storymap.briefing")
json = LazyLoader("json")
time = LazyLoader("time")
sharing = LazyLoader("gis._impl._content_manager_sharing.api")
_dt = LazyLoader("datetime")

_TEMPLATES = {
    "storymap_2": {
        "root": "n-4xkUEe",
        "nodes": {
            "n-4xkUEe": {
                "type": "story",
                "data": {"storyTheme": "r-vlc4Kp"},
                "config": {"coverDate": "first-published"},
                "children": ["n-aTn8ak", "n-1AItUD", "n-cOeTah"],
            },
            "n-aTn8ak": {
                "type": "storycover",
                "data": {
                    "type": "minimal",
                    "title": "",
                    "summary": "",
                    "byline": "",
                    "titlePanelPosition": "start",
                },
            },
            "n-1AItUD": {
                "type": "navigation",
                "data": {"links": []},
                "config": {"isHidden": True},
            },
            "n-cOeTah": {"type": "credits"},
        },
        "resources": {
            "r-vlc4Kp": {
                "type": "story-theme",
                "data": {
                    "themeId": "summit",
                    "themeBaseVariableOverrides": {},
                },
            }
        },
    },
    "briefing": {
        "root": "n-k23c2p",
        "nodes": {
            "n-XK0GeP": {"type": "briefing-ui", "children": ["n-11SuEF"]},
            "n-11SuEF": {
                "type": "briefing-slide",
                "data": {"layout": "cover"},
                "children": ["n-3r3mhh"],
            },
            "n-3r3mhh": {
                "type": "storycover",
                "data": {
                    "type": "sidebyside",
                    "title": "",
                    "summary": "",
                    "byline": "",
                    "titlePanelPosition": "start",
                },
                "children": [],
            },
            "n-k23c2p": {
                "type": "briefing",
                "data": {"storyTheme": "r-vlc4Kp"},
                "children": ["n-XK0GeP"],
            },
        },
        "resources": {
            "r-vlc4Kp": {
                "type": "story-theme",
                "data": {
                    "themeId": "summit",
                    "themeBaseVariableOverrides": {},
                },
            }
        },
    },
    "collection": {
        "root": "n-vCW523",
        "nodes": {
            "n-vCW523": {
                "type": "collection",
                "data": {"storyTheme": "r-QvId58"},
                "children": ["n-eERiZz"],
            },
            "n-eERiZz": {
                "type": "collection-ui",
                "data": {"items": []},
                "children": ["n-U3Ou63", "n-JTJJo2"],
            },
            "n-U3Ou63": {
                "type": "collection-cover",
                "data": {
                    "title": "",
                    "summary": "",
                    "byline": "",
                    "type": "tiles",
                },
            },
            "n-JTJJo2": {
                "type": "collection-nav",
                "data": {"type": "compact"},
            },
        },
        "resources": {
            "r-QvId58": {
                "type": "story-theme",
                "data": {
                    "themeId": "summit",
                    "themeBaseVariableOverrides": {},
                },
            }
        },
    },
}


# ----------------------------------------------------------------------
def _get_thumbnail(gis) -> str:
    """
    Private method to get the default thumbnail path dependent on whether the
    user is Online or on Enterprise.
    """
    if gis._is_agol:
        thumbnail = "https://storymaps.arcgis.com/static/images/item-default-thumbnails/item.jpg"
    else:
        thumbnail = (
            gis._url + "/apps/storymaps/static/images/item-default-thumbnails/item.jpg"
        )
    return thumbnail


# ----------------------------------------------------------------------
def show(item, width: Optional[int] = None, height: Optional[int] = None):
    """
    Show a preview. The default is a width of 700 and height of 300.
    """
    try:
        if item:
            width = 700 if width is None else width
            height = 350 if height is None else height
            from IPython.display import IFrame

            return IFrame(
                src=item.url,
                width=width,
                height=height,
                params="title=" + item.title,
            )
    except Exception:
        return item.url


# ----------------------------------------------------------------------
def cover(
    story,
    title: Optional[str] = None,
    type: str = None,
    summary: Optional[str] = None,
    by_line: Optional[str] = None,
    media: Optional[Union[Content.Image, Content.Video]] = None,
):
    """
    A cover is the first slide/node.
    This method allows the cover to be edited by updating the title, byline, image, and more.
    Changing one part of the briefing cover will not change the rest of the cover. If just the
    image is passed in then only the image will change.
    """
    if isinstance(story, briefing.Briefing) or isinstance(story, collection.Collection):
        ui = story._properties["nodes"][story._properties["root"]]["children"][0]
        story_cover_slide = story._properties["nodes"][ui]["children"][0]
        if isinstance(story, briefing.Briefing):
            story_cover_node = story._properties["nodes"][story_cover_slide][
                "children"
            ][0]
        else:
            # for collection, the cover is the first node in ui
            story_cover_node = story_cover_slide
    else:
        story_cover_node = story._properties["nodes"][story._properties["root"]][
            "children"
        ][0]

    # get original data of story cover
    orig_data = story._properties["nodes"][story_cover_node]["data"]

    # set the new values, if any
    story._properties["nodes"][story_cover_node] = {
        "type": "storycover",
        "data": {
            "type": orig_data["type"] if type is None else type,
            "title": orig_data["title"] if title is None else title,
            "summary": orig_data["summary"] if summary is None else summary,
            "byline": orig_data["byline"] if by_line is None else by_line,
            "titlePanelPosition": (
                orig_data["titlePanelPosition"]
                if by_line is None and "titlePanelPosition" in orig_data
                else "start"
            ),
        },
    }

    # set the cover media
    if media is not None:
        if isinstance(media, str):
            media = Content.Image(media)
        if not isinstance(media, Content.Image) and not isinstance(
            media, Content.Video
        ):
            raise ValueError(
                "Media must be an image or video object. This was not updated"
            )
        if media.node not in story._properties["nodes"]:
            # must be added to story resources
            media._add_to_story(story=story)
        story._properties["nodes"][story_cover_node]["children"] = [media.node]
    else:
        # get original image
        if "children" in story._properties["nodes"][story_cover_node]:
            media = story._properties["nodes"][story_cover_node]["children"][0]
            story._properties["nodes"][story_cover_node]["children"] = [media]

    return story._properties["nodes"][story_cover_node]


# ----------------------------------------------------------------------
def set_logo(
    story,
    logo: str,
    link: Optional[str] = None,
    alt_text: Optional[str] = None,
):
    """
    Set the logo image, link, and/or alt text for the story or briefing.
    """
    # If empty string is passed in then remove the logo
    # This wipes out everything
    if logo == "":
        root = story._properties["root"]
        if "storyLogoResource" in story._properties["nodes"][root]["data"]:
            del story._properties["nodes"][root]["data"]["storyLogoResource"]
        if "storyLogoLink" in story._properties["nodes"][root]["data"]:
            del story._properties["nodes"][root]["data"]["storyLogoLink"]
        if "storyLogoAltText" in story._properties["nodes"][root]["data"]:
            del story._properties["nodes"][root]["data"]["storyLogoAltText"]
    elif logo:
        # check the logo is a path to an image and not a url
        if "http" in logo:
            raise ValueError("Please provide a path to an image not a url.")
        # create unique resource name
        name = "logo_" + _dt.datetime.now().strftime("%Y%m%d%H%M%S")
        # add the image type to end of name
        if logo.endswith(".png"):
            name = name + ".png"
        elif logo.endswith(".jpg"):
            name = name + ".jpg"
        elif logo.endswith(".jpeg"):
            name = name + ".jpeg"
        else:
            raise ValueError(
                "Please provide a path to an image with a valid extension."
            )
        # add the logo to the story item resources
        _add_resource(story, file=logo, resource_name=name)
        # create resource node id
        resource_node = "r-" + uuid.uuid4().hex[0:6]
        # add the resource node to the story properties
        story._properties["resources"][resource_node] = {
            "type": "image",
            "data": {
                "resourceId": name,
                "provider": "item-resource",
                "height": 2304,
                "width": 1536,
            },
        }
        # set the logo to the story properties
        story._properties["nodes"][story._properties["root"]]["data"][
            "storyLogoResource"
        ] = resource_node

        # if link is empty string then remove
        if link == "":
            if "storyLogoLink" in story._properties["nodes"][root]["data"]:
                del story._properties["nodes"][root]["data"]["storyLogoLink"]
        elif link:
            story._properties["nodes"][root]["data"]["storyLogoLink"] = link

        # if alt text is empty string then remove
        if alt_text == "":
            if "storyLogoAltText" in story._properties["nodes"][root]["data"]:
                del story._properties["nodes"][root]["data"]["storyLogoAltText"]
        elif alt_text:
            story._properties["nodes"][root]["data"]["storyLogoAltText"] = alt_text

        return True


# ----------------------------------------------------------------------
def theme(story, theme: Union[storymap.Themes, str] = storymap.Themes.SUMMIT):
    """
    Each story/briefing has a theme node in its resources. This method can be used to change the theme.
    To add a custom theme to your story, pass in the item_id for the item of type Story Map Theme.
    """
    # find the node corresponding to the story theme in resources
    # the properties only holds the resource node id. If this doesn't change then don't need to update
    for node, node_info in story._properties["resources"].items():
        for key, val in node_info.items():
            if key == "type" and val == "story-theme":
                if isinstance(theme, storymap.Themes):
                    # theme comes from Themes class
                    story._properties["resources"][node]["data"][
                        "themeId"
                    ] = theme.value
                if isinstance(theme, str):
                    # theme is an item of type Story Theme
                    story._properties["resources"][node]["data"]["themeItemId"] = theme


# ----------------------------------------------------------------------
def get_theme(story):
    """
    Get the theme of the story, briefing, or collection.
    """
    # see if there is a resource that is the story-theme
    for node, node_info in story._properties["resources"].items():
        for key, val in node_info.items():
            if key == "type" and val == "story-theme":
                return story._properties["resources"][node]["data"]["themeId"]


# ----------------------------------------------------------------------
def get_version(story) -> str:
    """
    Get the story, briefing, or collection version. All same version.
    This version is used when saving by adding it to the type keywords.
    """
    try:
        sm_version = story._gis._con.get("https://storymaps.arcgis.com/version")[
            "version"
        ]
    except:
        # When behind firewall or using enterprise, the version is not available
        sm_mapping = {
            "[10, 3]": "22.49",  # Enterprise 11.1
            "[2023, 2]": "23.32",  # Enterprise 11.2
            "[2024, 1]": "24.12",  # Enterprise 11.3
            "[2024, 2]": "24.36",  # Enterprise 11.4
            "default": "24.12",
        }
        gis_version = str(story._gis.version[:2])
        sm_version = sm_mapping.get(gis_version, sm_mapping["default"])
    return sm_version


def _publish(story, access, item_properties):
    """
    Enterprise does not have a publish endpoint. We need to manually update the item properties and resources.
    """
    # Remove old publish item
    for resource in story._resources:
        if (
            "publish_data" in resource["resource"]
            or "published_data" in resource["resource"]
            or "publish" in resource["resource"]
        ):
            _remove_resource(story, file=resource["resource"])
    # Add new publish
    _add_resource(
        story,
        resource_name="published_data.json",
        text=json.dumps(story._properties),
    )

    # add to item properties
    item_properties["text"] = json.dumps(story._properties)
    item_properties["url"] = story._url
    sharing = access or story._item.access
    item_properties["access"] = sharing

    # Update the item and invoke share to have correct access
    story._item.update(item_properties=item_properties)

    if sharing == "private":
        story._item.sharing.sharing_level = "PRIVATE"
    elif sharing == "org":
        story._item.sharing.sharing_level = "ORGANIZATION"
    elif sharing == "public":
        story._item.sharing.sharing_level = "EVERYONE"

    if story._gis._session.auth and story._gis._session.auth.token is not None:
        # Make a call to the StoryMaps publish endpoint
        story._gis._session.post(
            url=story._url + "/publish",
            data={
                "f": "json",
                "token": story._gis._session.auth.token,
            },
        )


def _prepare_story_for_save(
    story, publish, make_copyable, no_seo, title, tags, sm_version
):
    """
    Remove old resource and add new draft resource that is the story._properties.
    """
    for resource in story._resources:
        if re.match("draft_[0-9]{13}.json", resource["resource"]) or re.match(
            "draft.json", resource["resource"]
        ):
            _remove_resource(story, file=resource["resource"])

    # Add new draft with time in milliseconds
    draft = "draft_" + str(int(time.time() * 1000)) + ".json"

    # Add a new empty json draft
    _add_resource(story, resource_name=draft, text="{}", access="private")

    # Create a temporary file to write the story._properties
    with tempfile.NamedTemporaryFile(
        mode="w+", suffix=".json", delete=False, encoding="utf-8"
    ) as temp:
        json.dump(story._properties, temp, ensure_ascii=False)
        temp.seek(0)

        # update the draft with the story._properties
        story._item.resources.update(file=temp.name, file_name=draft)

    item_properties = _prepare_item_properties_for_save(
        story, publish, make_copyable, no_seo, title, tags, sm_version, draft
    )
    return item_properties


def _prepare_item_properties_for_save(
    story, publish, make_copyable, no_seo, title, tags, sm_version, draft
):
    # Find type keywords to use based on whether to publish or not
    if publish:
        keywords = story._item.typeKeywords
        if "smstatusunpublishedchanges" in keywords:
            # changing to publish after
            idx = keywords.index("smstatusunpublishedchanges")
            del keywords[idx]
        if "smstatusdraft" in keywords:
            idx = keywords.index("smstatusdraft")
            del keywords[idx]
        for keyword in keywords:
            # iterate through since only know part of keyword we want to remove
            if (
                "smdraftresourceid"
                or "smpublisheddate"
                or "smstatusdraft"
                or "smpublisherapp"
            ) in keyword:
                keywords.remove(keyword)
        new_keywords = [
            "smstatuspublished",
            "smversiondraft:" + sm_version,
            "smversionpublished:" + sm_version,
            "python-api",
            "smpublisherapp:python-api-" + arcgis.__version__,
            "smdraftresourceid:" + draft,
            "smpublisheddate:" + str(int(time.time() * 1000)),
        ]
        # publish keywords
        if make_copyable is True:
            new_keywords.append("Viewer Copyable")
        if no_seo is False:
            new_keywords.append("smsharingnoseo")
    else:
        # Set the type keywords
        keywords = story._item.typeKeywords
        previously_published = False
        for keyword in keywords:
            if "smpublisheddate" in keyword:
                # Update the date in new keywords
                previously_published = True
                keywords.remove(keyword)
            elif (
                "smstatuspublished" in keyword
                or "smstatusdraft" in keyword
                or "smdraftresourceid" in keyword
                or "smeditorapp" in keyword
                or "Copy Item" in keyword
            ):
                # Remove old keywords and will be replaced in new keywords
                keywords.remove(keyword)
        if previously_published is True:
            # Unpublished changes mode
            new_keywords = [
                "smstatusunpublishedchanges",
                "smversiondraft:" + sm_version,
                "python-api",
                "smeditorapp:python-api-" + arcgis.__version__,
                "smdraftresourceid:" + draft,
                "smversionpublished:" + sm_version,
                "smpublisheddate:" + str(int(time.time() * 1000)),
            ]
        if previously_published is False:
            # Draft mode
            new_keywords = [
                "smstatusdraft",
                "smversiondraft:" + sm_version,
                "python-api",
                "smeditorapp:python-api-" + arcgis.__version__,
                "smdraftresourceid:" + draft,
            ]

    # Add extra keywords
    if isinstance(story, briefing.Briefing):
        new_keywords = new_keywords + ["alphabriefing", "storymapbriefing"]
    elif isinstance(story, collection.Collection):
        new_keywords = new_keywords + ["storymapcollection"]

    new_keywords = list(set(keywords + new_keywords))

    p = {"typeKeywords": new_keywords}
    if title:
        p["title"] = title
    if tags:
        p["tags"] = tags
    return p


# ----------------------------------------------------------------------
def save(
    story,
    title: Optional[str] = None,
    tags: Optional[list] = None,
    access: str = None,
    publish: bool = False,
    make_copyable: bool = None,
    no_seo: bool = None,
):
    """
    This method will save your StoryMap or Briefing to your active GIS. The story will be saved
    with unpublished changes unless publish parameter is specified to True.

    The title only needs to be specified if a change is wanted, otherwise exisiting title
    is used.
    """
    # Add meta settings and change push meta so title doesn't get overwritten on publish at any point.
    if title:
        root = story._properties["root"]
        if "metaSettings" not in story._properties["nodes"][root]["data"]:
            story._properties["nodes"][root]["data"]["metaSettings"] = {"title": None}
        story._properties["nodes"][root]["data"]["metaSettings"]["title"] = title
        if "config" not in story._properties["nodes"][root]:
            story._properties["nodes"][root]["config"] = {}
        story._properties["nodes"][root]["config"][
            "shouldPushMetaToAGOItemDetails"
        ] = False

    # get the story map version from endpoint
    sm_version = get_version(story)

    # No endpoint, do manually
    item_properties = _prepare_story_for_save(
        story, publish, make_copyable, no_seo, title, tags, sm_version
    )

    if publish:
        _publish(story, access, item_properties)
    else:
        # access does not change when only saving
        item_properties["access"] = story._item.access
        story._item.update(item_properties=item_properties)

    story._item = story._gis.content.get(story._itemid)
    return story._item


# ----------------------------------------------------------------------
def delete_item(story):
    """
    Deletes the item.
    """
    # Check if item id exists
    item = story._gis.content.get(story._itemid)
    return item.delete(permanent=True)


# ----------------------------------------------------------------------
def duplicate(story, title: Optional[str] = None):
    """
    Duplicate the story. All items will be duplicated as they are. This allows you to create
    a briefing template and duplicate it when you want to work with it.
    """
    # get the item to copy
    item = story._gis.content.get(story._itemid)
    # set the title
    title = title if title is not None else item.title + " Copy"
    # copy the story item
    copy = item.copy_item(title=title, include_resources=True, include_private=True)

    # remove the type keywords that are not needed
    keywords = story._item.typeKeywords
    for keyword in keywords:
        if "smeditorapp" in keyword or "Copy Item" in keyword:
            # Remove old keywords and will be replaced in new keywords
            keywords.remove(keyword)

    copy.update({"typeKeywords": keywords})

    # make a resources call
    copy.resources.list()
    return copy


# ----------------------------------------------------------------------
def get(story, node: Optional[str] = None, type: Optional[str] = None):
    """
    Get node(s) by type or by their id. Using this function will help grab a specific node
    from the story if a node id is provided. Set this to a variable and this way edits can be
    made on the node in the story.

    """
    spec_type = []
    node_id = node
    if node_id and node_id not in story._properties["nodes"]:
        raise ValueError(
            "This node value is not in the story. "
            + "Please check that you have entered the correct node id. "
            + "To see all main nodes and their ids use the nodes property."
        )
    if type is None and node_id is None:
        # return all nodes in order
        return story.nodes
    elif node_id is not None:
        # check first if it's an action
        all_actions = story.actions
        for action in all_actions:
            id = list(action.keys())[0]
            if node_id == id:
                return list(action.values())[0]
        # return a specific node
        all_nodes = _create_node_dict(story)
        # find the node in the list and return it
        for node in all_nodes:
            id = list(node.keys())[0]
            if node_id == id:
                return list(node.values())[0]
    else:
        # return all nodes of a certain type
        all_nodes = _create_node_dict(story)
        for node in all_nodes:
            keyword = str(list(node.values())[0]).lower()
            if isinstance(keyword, str):
                # Not a type of story content (i.e. navigation)
                if type.lower() in keyword:
                    spec_type.append(node)
            else:
                # Find all story content instances (i.e. Text)
                # Map types are uppercase and have spaces so handle
                if type.lower() in keyword._type.lower().replace(" ", ""):
                    spec_type.append(node)
        return spec_type


# ----------------------------------------------------------------------
def populate_resource_dict(story, resource, complete_resource_dict, resource_files):
    if isinstance(resource, str):
        # check if value is a resource
        if "r-" in resource:
            # get the resource dict
            resource_dict = story._properties["resources"][resource]
            complete_resource_dict[resource] = resource_dict
            if "resourceId" in resource_dict["data"]:
                # some nodes keep the resource under resourceId key
                name = resource_dict["data"]["resourceId"]
                # get the resource file to add to new story
                resource_file = story._item.resources.get(name)
                resource_files[name] = resource_file
            elif "itemId" in resource_dict["data"]:
                name = resource_dict["data"]["itemId"]
                # express map keeps resource under itemId key
                if name.endswith(".json"):
                    # need to add draft_ in front to be one-to-one with builder
                    name = "draft_" + resource_dict["data"]["itemId"]
                    # get the json file draft
                    resource_file = story._item.resources.get(name)
                    if resource_file and "error" in resource_file:
                        # if resource returns 403, skip and add warning
                        warnings.warn(
                            f"{name}: Resource is not accessible, the content placeholder will be copied but resource will have to be added manually."
                        )
                        return complete_resource_dict, resource_files
                    resource_files[name] = resource_file
    return complete_resource_dict, resource_files


# ----------------------------------------------------------------------
def populate_dicts(
    story,
    content: str,
    complete_node_dict: dict,
    complete_resource_dict: dict,
    resource_files: dict,
):
    content_dict = story._properties["nodes"][content]
    complete_node_dict[content] = content_dict
    # find the resource node to add associated with node. Text nodes have data but no resources
    if "data" in content_dict and content_dict["type"] != "text":
        for _, value in content_dict["data"].items():
            if not isinstance(value, list):
                value = [value]
            for val in value:
                # express maps keep their images in a list
                complete_resource_dict, resource_files = populate_resource_dict(
                    story, val, complete_resource_dict, resource_files
                )
    return complete_node_dict, complete_resource_dict, resource_files


# ----------------------------------------------------------------------
def copy_content(
    story,
    target_story: Union[briefing.Briefing, storymap.StoryMap],
    contents: list,
):
    """
    Copy content from one story to another. This will copy the nodes and resources
    from the source story to the target story. The content can be a list of node ids
    or a list of content objects. The content must be part of the source story.

    Copy slides from one briefing to another.
    """
    if isinstance(contents, list) and not isinstance(contents[0], str):
        # get the node ids of the content
        contents = [item.node for item in contents]

    # Step 1: Do Checks
    # Check that nodes exist in original story (children of source story contain all of content)
    if isinstance(target_story, briefing.Briefing):
        # children are in the children of the the root node. In the ui node
        ui = story._properties["nodes"][story._properties["root"]]["children"][0]
        story_children = story._properties["nodes"][ui]["children"]
    else:
        story_children = story._properties["nodes"][story._properties["root"]][
            "children"
        ]
    check = all(node in story_children for node in contents)
    # Return an error if not all nodes are in the source story.
    if check is False:
        raise ValueError(
            "The content needs to be part of the story. Please check that the correct contents are provided."
        )

    # Step 2: Create dictionaries for copying

    # Create node dict of all nodes to add, resource dict, and complete node list
    # Depending on node type, need to take different route to find all children
    original_nodes = contents
    complete_node_list = []
    complete_node_dict = {}
    complete_resource_dict = {}
    resource_files = {}
    has_children = True

    # Begin populating dicts and list, assume there are children to begin with.
    while has_children is True:
        # new list of nodes to check at next iteration
        new_nodes = []
        for node in contents:
            complete_node_dict, complete_resource_dict, resource_files = populate_dicts(
                story, node, complete_node_dict, complete_resource_dict, resource_files
            )
            # check type of node to see if need to find children
            node_children = _has_children(story, node)
            # populate new list with next nodes to add
            if node_children:
                for child in node_children:
                    new_nodes.append(child)
        # if list is not empty, keep going
        if new_nodes:
            has_children = True
            contents = new_nodes
        # once list is empty, all children have been accounted for
        else:
            has_children = False

    # Step 3: Make any changes before copying over
    # existing target story node ids
    target_story_nodes = list(target_story._properties["nodes"].keys())

    if any(node in target_story_nodes for node in complete_node_list):
        # find the node and change it everywhere
        for node in complete_node_list:
            if node in target_story_nodes:
                new_node = "n-" + uuid.uuid4().hex[0:6]
                # replace node with new node in all places
                # in the list passed in, if present
                original_nodes = [s.replace(node, new_node) for s in original_nodes]
                # in the dictionary of all nodes to copy
                # make a copy since we will edit the dict as we iterate through
                iterate_dict = complete_node_dict.copy()
                for key, value in iterate_dict.items():
                    if key == node:
                        # replace old node id with new node id in keys
                        complete_node_dict[new_node] = complete_node_dict.pop(key)
                    if "children" in value:
                        # replace old node id with new node id if child of another node
                        if node in value["children"]:
                            complete_node_dict[key]["children"] = [
                                s.replace(node, new_node) for s in value["children"]
                            ]

    # Step 4: Copy nodes to target story
    for key, value in complete_node_dict.items():
        target_story._properties["nodes"][key] = value
    for key, value in complete_resource_dict.items():
        target_story._properties["resources"][key] = value
    for key, value in resource_files.items():
        try:
            _add_resource(target_story, file=value, resource_name=key)
        except Exception:
            # express map, image editor, other created files will be here
            text = json.dumps(value)
            _add_resource(target_story, resource_name=key, text=text)

    # Step 5: Add the node list to the story children
    for main_node in original_nodes:
        _add_child(target_story, main_node)

    # Step 6: Save
    target_story.save()
    return True


# ----------------------------------------------------------------------
def _has_children(story, node) -> list | str | bool | None:
    """
    Check if node has children and return list of children else None.
    """
    node_class = _assign_node_class(story, node)
    if (
        isinstance(node_class, Content.Sidecar)
        or isinstance(node_class, Content.Gallery)
        or isinstance(node_class, Content.Timeline)
    ):
        return story._properties["nodes"][node]["children"]
    elif isinstance(node_class, Content.Swipe):
        return list(story._properties["nodes"][node]["data"]["contents"].values())
    elif isinstance(node_class, Content.BriefingSlide):
        contents = []
        for block in node_class.blocks:
            block_content = (
                block._content if isinstance(block._content, list) else [block._content]
            )
            for node in block_content:
                contents.append(node)
        if node_class._title:
            contents.append(node_class._title.node)
        return contents
    elif isinstance(node_class, Content.MapTour):
        mt = get(story, node)
        return mt._children
    elif isinstance(node_class, Content.ExpressMap):
        if node_class._media_dependents:
            return story._properties["nodes"][node]["dependents"]["media"]
    elif isinstance(node_class, str):
        if (
            "immersive" in node_class.lower()
            or "credits" in node_class.lower()
            or "event" in node_class.lower()
            or "carousel" in node_class.lower()
        ):
            return (
                story._properties["nodes"][node]["children"]
                if "children" in story._properties["nodes"][node]
                else None
            )
    else:
        return None


# ----------------------------------------------------------------------
def _delete(story, node_id):
    # Check if node is in story
    if node_id not in story._properties["nodes"]:
        return False

    # Get list of nodes in the story
    root_id = story._properties["root"]
    children = story._properties["nodes"][root_id]["children"]

    # Remove from children of story
    if node_id in children:
        story._properties["nodes"][root_id]["children"].remove(node_id)
    # Remove from nodes dictionary
    del story._properties["nodes"][node_id]
    # Remove node from any immersive nodes.
    # A node can belong to an immersive narrative panel or an immersive slide
    for node in story._properties["nodes"]:
        if (
            "immersive" in story._properties["nodes"][node]["type"]
            and "children" in story._properties["nodes"][node]
        ):
            for child in story._properties["nodes"][node]["children"]:
                # iterate through children to see if node is part of it
                if child == node_id:
                    story._properties["nodes"][node]["children"].remove(node_id)

    return True


# ----------------------------------------------------------------------
def _add_child(story, node_id, position=None):
    """
    A story node has children. Children is a list of item nodes that are in
    the story. The order of the list determines the order that the nodes
    appear in the story. First and last nodes are reserved for story_cover
    and credits. The second node is always navigation. If visible is not set
    to True is simply won't be seen but stays in position 2.
    """
    # Get list of children in story
    root_id = story._properties["root"]

    if isinstance(story, briefing.Briefing):
        # for briefings, the only child is the ui
        # the ui node has the slides
        principal_id = story._properties["nodes"][root_id]["children"][0]
        last = len(story._properties["nodes"][principal_id]["children"])
    else:
        # for storymap the children are the root
        principal_id = root_id
        # find the last position. If only one node then the last position is 1
        last = len(story._properties["nodes"][principal_id]["children"]) - 1

    if last == 0:
        # briefings only have cover when you start
        last = 1

    if position and position < last and position != 0 and position != 1:
        # If the position adheres to rules then add node
        story._properties["nodes"][principal_id]["children"].insert(position, node_id)
    elif position and (position == 0 or position == 1):
        # First and second node reserved for story cover and navigation
        # Add as third node if user specified position 0 or 1
        story._properties["nodes"][principal_id]["children"].insert(2, node_id)
    else:
        # Last node is reserved for credits so add before this if user wanted last position
        story._properties["nodes"][principal_id]["children"].insert(last, node_id)


# ----------------------------------------------------------------------
def _add_resource(story, file=None, resource_name=None, text=None, access="inherit"):
    """
    See :class:`~arcgis.gis.ResourceManager`
    """
    resource_manager = arcgis.gis.ResourceManager(story._item, story._gis)
    is_present = False
    if file:
        for resource in story._resources:
            if resource["resource"] in file:
                is_present = True
                resp = True
    properties = {
        "editInfo": {
            "editor": story._gis._username,
            "modified": str(int(time.time() * 1000)),
            "id": uuid.uuid4().hex[0:21],
            "app": "python-api",
        }
    }

    # access is inherited from item upon add, except for json where always private
    if is_present is False:
        resp = resource_manager.add(
            file=file,
            file_name=resource_name,
            text=text,
            access=access,
            properties=properties,
        )

    story._resources = story._item.resources.list()
    return resp


# ----------------------------------------------------------------------
def _remove_resource(story, file=None):
    """
    See :class:`~arcgis.gis.ResourceManager`
    """
    try:
        resource_manager = arcgis.gis.ResourceManager(story._item, story._gis)
        resp = resource_manager.remove(file=file)
        story._resources = story._item.resources.list()
        return resp
    except Exception:
        # Resource cannot be found. Should not throw error
        return True


# ----------------------------------------------------------------------
def _assign_node_class(story, node_id):
    NODE_TYPE_CLASS_MAP = {
        "separator": Content.Separator,
        "briefing-slide": Content.BriefingSlide,
        "code": Content.Code,
        "image": Content.Image,
        "video": Content.Video,
        "audio": Content.Audio,
        "embed": {
            "video": Content.Video,
            "link": Content.Embed,
        },
        "webmap": Content.Map,
        "text": Content.Text,
        "button": Content.Button,
        "swipe": Content.Swipe,
        "gallery": Content.Gallery,
        "timeline": Content.Timeline,
        "tour": Content.MapTour,
        "table": Content.Table,
        "immersive": {
            "sidecar": Content.Sidecar,
            # Add more subtypes as needed
        },
        "action-button": Content.MediaAction,
        "expressmap": Content.ExpressMap,
        "navigation": Content.Navigation,
        "storycover": Content.Cover,
        "collection-cover": Content.Cover,
        "collection-nav": Content.CollectionNavigation,
    }

    node_properties = story._properties["nodes"][node_id]
    node_type = node_properties["type"]

    if node_type in NODE_TYPE_CLASS_MAP:
        node_class_or_subtype = NODE_TYPE_CLASS_MAP[node_type]

        if isinstance(node_class_or_subtype, dict):
            # Handle subtypes
            if "sidecar" in node_class_or_subtype:
                # Immersive sidecar has subtypes
                subtype_key = node_properties["data"].get("type")
            else:
                subtype_key = node_properties["data"].get(
                    "embedType"
                )  # Adjust based on actual subtype key
            node_class = node_class_or_subtype.get(subtype_key, node_type.capitalize())
        else:
            # No subtypes, use the class directly
            node_class = node_class_or_subtype
    else:
        # Unknown type, return the type name capitalized
        node_class = node_type.capitalize()

    if isinstance(node_class, str):
        return node_class
    else:
        return node_class(story=story, node_id=node_id)


# ----------------------------------------------------------------------
def _create_node_dict(story):
    """
    Method called by the nodes property and the get method. However, the nodes
    property will transform the keys whereas the get method needs they keys
    to be class instances.
    """
    # get rood node id since it is story node id
    root_id = story._properties["root"]
    # get list of children from story node
    if isinstance(story, briefing.Briefing):
        ui = story._properties["nodes"][root_id]["children"]
        children = story._properties["nodes"][ui[0]]["children"]
    else:
        children = story._properties["nodes"][root_id]["children"]
    nodes = story._properties["nodes"]

    node_order = []
    # for each node assign correct class type to be accessed if needed by user
    for child in children:
        # get only the main nodes and not the subnodes to be returned
        if child in nodes:
            node = _assign_node_class(story, child)
            node_order.append({child: node})
    return node_order
