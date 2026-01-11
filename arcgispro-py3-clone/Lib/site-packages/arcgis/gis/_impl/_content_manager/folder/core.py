from __future__ import annotations
import io
import os
import json
import time
import logging
import requests
import concurrent.futures
from functools import lru_cache
from types import NoneType
from typing import Any, Iterator
from ._exceptions import FolderException
from ._util import (
    _get_folder_id,
    _get_folder_name,
    calculate_upload_size,
    close_upload_files,
    chunk_by_file_size,
    create_upload_tuple,
    status,
    _process_parameters,
)
from arcgis.auth.tools import LazyLoader
from ..._dataclasses import ItemProperties, ItemTypeEnum
from ...._impl._util import is_valid_item_id
from arcgis.auth import EsriSession

_arcgis_gis = LazyLoader("arcgis.gis")
logger = logging.getLogger(__name__)

__all__ = ["Folder", "Folders"]

_JSON_ITEMS: list[str] = [
    "360 VR Experience",
    "Map Area",
    "Web Map",
    "Web Scene",
    "Feature Collection",
    "Feature Collection Template",
    "Feature Service",
    "Group Layer",
    "Image Service",
    "Map Service",
    "Oriented Imagery Catalog",
    "Relational Database Connection",
    "3DTilesService",
    "Scene Service",
    "Vector Tile Service",
    "WFS",
    "WMTS",
    "Dashboard",
    "Data Pipeline",
    "Deep Learning Studio Project",
    "Esri Classification Schema",
    "Excalibur Imagery Project",
    "GeoBIM Application",
    "GeoBIM Project",
    "Hub Event",
    "Hub Initiative",
    "Hub Initiative Template",
    "Hub Page",
    "Hub Project",
    "Hub Site Application",
    "Insights Workbook",
    "Insights Model",
    "Insights Page",
    "Insights Theme",
    "Investigation",
    "Knowledge Studio Project",
    "Mission",
    "Mobile Application",
    "Ortho Mapping Project",
    "Ortho Mapping Template",
    "Solution",
    "StoryMap",
    "Web AppBuilder Widget",
    "Web Experience",
    "Web Experience Template",
    "Web Mapping Application",
    "Workforce Project",
    "Color Set",
    "Content Category Set",
    "StoryMap Theme",
    "Style",
    "Symbol Set",
]


class Job:
    _item: _arcgis_gis.Item | None = None

    def __init__(
        self,
        futures: Dict[concurrent.futures.Future, str],
        commit_url: str,
        commit_params: Dict[str, Any],
        session: requests.Session,
        itemid: str,
        params: Dict[str, Any],
        folder: Folder,
    ):
        self.futures = futures
        self.commit_url = commit_url
        self.commit_params = commit_params
        self.session = session
        self.itemid = itemid
        self.params = params
        self.folder = folder
        self.messages = []

    def __str__(self) -> str:
        return f"< Job for Item: {self.itemid} >"

    def __repr__(self) -> str:
        return self.__str__()

    def result(self) -> _arcgis_gis.Item:
        if self._item:
            return self._item
        results = []
        self.messages = []
        for future in concurrent.futures.as_completed(self.futures):
            r = future.result()
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            if "success" in data:
                results.append(data["success"])
            elif "status" in data and data["status"] == "success":
                results.append(True)
            else:
                results.append(False)
            logger.info(r.text)
            self.messages.append(r.text)

        if all(results):
            self.commit_params.update(self.params)
            resp: requests.Response = self.session.post(
                url=self.commit_url, data=self.commit_params
            )
            resp.raise_for_status()
            res: dict[str, Any] = resp.json()
            if "success" in res and res["success"]:
                item: _arcgis_gis.Item = self.folder._process_item_status(
                    itemid=self.itemid
                )
                if "classification" in self.params:
                    item.update({"classification": self.params["classification"]})
                self._item = item
                return self._item
        raise FolderException("Failed to upload all parts")


###########################################################################
class Folder:
    """
    Lists a user's content in a folder
    """

    _folder: str | None = None
    _gis: _arcgis_gis.GIS
    _name: str = None
    _fid: str = None
    _properties: dict[str, Any] | None = None

    # ---------------------------------------------------------------------
    def __init__(
        self,
        gis: _arcgis_gis.GIS,
        *,
        folder: str | None = None,
        owner: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> None:
        self._folder = folder
        self._gis = gis
        self._owner = owner or gis.users.me.username
        self._session = gis._con._session
        self._properties = properties
        if self._properties:
            self._name = self._properties.get("title", None)
            self._fid = self._properties.get("id", None)

    # ---------------------------------------------------------------------
    def __str__(self) -> str:
        return f"< Folder: {self.name} Owner: {self._owner}>"

    # ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return self.__str__()

    # ---------------------------------------------------------------------
    @property
    def properties(self) -> dict[str, Any]:
        """Returns a Python dictionary of the
        :class:`~arcgis.gis._impl._content_manager.Folder` properties.

        .. code-block:: python

            # Usage example:
            >>> from arcgis.gis import GIS
            >>> gis = GIS(profile="your_org_admin_profile")

            >>> water_folder = gis.content.folders.get(folder="water_resources",
                                                       owner="field_editor3")
            >>> water_folder.properties
            {'username': 'field_editor3',
             'id': 'fc82e2ebd2091ca752ac29332aa5cfaa',
             'title': 'water_resources',
             'created': 1567502017000}
        """
        return self._properties

    # ---------------------------------------------------------------------
    @property
    def name(self) -> str:
        """returns the current folder's name"""
        if self._name is None:
            self._name = _get_folder_name(
                gis=self._gis, owner=self._owner, folder_id=self._folder
            )
        return self._name

    # ---------------------------------------------------------------------
    @property
    def _folder_id(self) -> str:
        """returns the folder's ID"""
        if self._fid is None:
            self._fid = _get_folder_id(
                gis=self._gis, owner=self._owner, folder_name=self._folder
            )
            if self._fid == "Root Folder":
                self._fid = ""
        return self._fid

    # ---------------------------------------------------------------------
    def list(
        self,
        item_type: str | None = None,
        order: str | None = "asc",
        sort_on: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Returns a Python generator object that can be iterated over to return
        the content in the *folder*.

        ================  ==========================================================================
        **Parameter**      **Description**
        ----------------  --------------------------------------------------------------------------
        item_type         Required string. The specific :class:`~arcgis.gis.Item` type to create
                          a generator for. Authoritative values can be entered by using the *value*
                          attribute of any :class:`~arcgis.gis._impl._dataclasses.ItemTypeEnum` member.

                          .. code-block:: python

                              # Usage example
                              >>> from arcgis.gis import ItemTypeEnum
                              >>> user_folder = gis.content.folders.get(folder="data_folder")

                              >>> fs_generator = user_folder.list(item_type=ItemTypeEnum.FEATURE_SERVICE.value)
        ----------------  --------------------------------------------------------------------------
        order             Optional string. Order of the folders in the returned generator.
                          Options:

                          * *asc*
                          * *desc*
        ----------------  --------------------------------------------------------------------------
        sort_on           Optional string.
                          Options:

                          * *username*
                          * *id*
                          * *title*
        ================  ==========================================================================

        :return:
            A Python generator object which can iterate over the
            :class:`items <arcgis.gis.Item>` that meet the defined arguments.

        .. code-block:: python

            # Usage example #1
            >>> from arcgis.gis import GIS, ItemTypeEnum

            >>> gis = GIS(profile="your_organization_profile")

            >>> wetlands_fldr = gis.content.folders.get(folder="Wetlands data")
            >>> wm_generator = wetlands_fldr.list(item_type=ItemTypeEnum.WEB_MAP.value)

            >>> for wm_item in wm_generator:
            >>>    print(f"{wm_item.title:30}{wm_item.type}")

            swamp_preserves_in_2016       Web Map
            wetland_protected_areas       Web Map

            # Usage example #2
            >>> highway_folder = gis.content.folders.get(folder="highway project")

            >>> sd_genr = highway_folder.list(item_type=ItemTypeEnum.SERVICE_DEFINITION.value,
                                              order="desc", sort_on="title)

            >>> next(sd_genr)
            <Item title:"I-40 sd" type:Service Definition owner:gis_user>

            >>> next(sd_genr)
            <Item title:"I-64-dev sd" type:Service Definition owner:gis_user>
        """
        url: str = f"{self._gis._portal.resturl}content/users/{self._owner}"
        if self._folder:
            url: str = (
                f"{self._gis._portal.resturl}content/users/{self._owner}/{self._folder_id}"
            )
        params: dict[str, Any] = {
            "f": "json",
            "types": item_type,
            "sortField": sort_on,
            "sortOrder": order,
            "num": 99,
            "start": 1,
        }
        resp: requests.Response = self._session.get(url=url, params=params)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        while True:
            for item in data["items"]:
                yield _arcgis_gis.Item(gis=self._gis, itemid=item.get("id", None))
            if data.get("nextStart", -1) == -1:
                break
            else:
                params["start"] = data.get("nextStart")
            resp: requests.Response = self._session.get(url=url, params=params)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

    def rename(self, name: str, owner: str | "User" = None) -> bool:
        """
        The ``rename`` method replaces an existing folder's title with the
        new value in the *name* argument.

        .. note::
            If owner is not specified, owner is set as the logged in user.


        ================  ==========================================================================
        **Parameter**      **Description**
        ----------------  --------------------------------------------------------------------------
        name              Required string. The new name of the folder.
        ----------------  --------------------------------------------------------------------------
        owner             Optional :class:`~arcgis.gis.User` object or *username* string.
        ================  ==========================================================================

        :return:
            A boolean indicating success (True), or failure (False)

        .. code-block:: python

            # Usage Example
            >>> from arcgis.gis import GIS
            >>> gis = GIS(profile="your_organization_admin_profile")

            >>> orig_folder = gis.content.folders.get("2020 Hurricane Data", "mobile_worker6")
            >>> orig_folder.rename("2021_Hurricane_Data", "mobile_worker6")
            True
        """
        params: dict[str, Any] = {"f": "json", "newTitle": name}
        owner_name: str = None
        if self._folder == "/":
            logger.warning("Cannot rename the root folder")
            return False
        else:
            if owner is None:
                owner_name = self._gis.users.me.username
            elif hasattr(owner, "username"):
                owner_name = getattr(owner, "username")
            else:
                owner_name = owner
            folderid: str = _get_folder_id(
                gis=self._gis, owner=owner_name, folder_name=self.name
            )

            if folderid is None:
                raise FolderException("Folder: %s does not exist." % self.name)
            url: str = "{base}content/users/{user}/{folderid}/updateFolder".format(
                base=self._gis._portal.resturl,
                user=owner_name,
                folderid=self._folder_id,
            )
            resp: requests.Response = self._session.post(url=url, params=params)
            resp.raise_for_status()
            res: dict[str, Any] = resp.json()
            if "success" in res:
                self._name = None
                self._folder = self._folder_id
                return res["success"]
        return False

    # ---------------------------------------------------------------------
    def delete(self, permanent: bool = False) -> bool:
        """Deletes the user folder and all its :class`items <arcgis.gis.Item>`.

        .. note::
            Only available on non-Root Folder
            :class:`folders <arcgis.gis._impl._content_manger.Folder>`.

        .. return::
            A boolean indicating success (True), or failure (False)
        """
        url: str = (
            f"{self._gis._portal.resturl}content/users/{self._owner}/{self._folder_id}/delete"
        )
        params = {
            "f": "json",
        }
        if permanent:
            # applicable to online if recycle bin is enabled
            rsupport = self._gis.properties.get("recycleBinSupported", False)
            renabled = (
                self._gis.properties.recycleBinEnabled
                if rsupport and hasattr(self._gis.properties, "recycleBinEnabled")
                else False
            )
            if (
                (self._gis._is_agol or self._gis.version > [2023, 2])
                and rsupport
                and renabled
            ):
                params["permanentDelete"] = True
            else:
                logger.warning(
                    "Recycle bin not enabled on this organization. Permanent delete parameter ignored."
                )
        resp: requests.Response = self._session.post(url, data=params)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if data and data.get("success", False):
            return True
        else:
            logger.warning(
                f"Could not erase the folder: {self.name}. Received the error: {data}."
            )
            return False

    # ---------------------------------------------------------------------
    def _chunk_file(self, io: io.BytesIO | io.StringIO, size: int) -> Iterator[tuple]:
        """chunks the file"""
        for chunk in chunk_by_file_size(
            fp=io, size=size, parameter_name="file", upload_format=True
        ):
            yield chunk
        yield

    # ---------------------------------------------------------------------
    def _add_async_streaming(
        self,
        url: str,
        params: dict,
        upload_size: int,
        file_list: dict | list | None,
    ) -> _arcgis_gis.Item | dict[str, Any]:
        """performs the add by parts upload for files over 5 MBs."""

        parts_url: str = url.replace("/addItem", "/addPart")
        ftuple: tuple = file_list.pop("file")
        params.pop("async", None)
        params_updated: dict = {k: (None, v) for k, v in params.items()}
        file_list.update(params_updated)
        resp: requests.Response = self._session.post(
            url=url, files=file_list
        )  # Gets the initial Item
        data: dict[str, Any] = resp.json()
        itemid = data.get("id", None) or data.get("itemId", None)
        if itemid is None:
            raise FolderException(f"The item could not be added: {str(data)}")
        parts_url: str = url.replace("/addItem", f"/items/{itemid}/addPart")
        commit_url: str = url.replace("/addItem", f"/items/{itemid}/commit")
        # Add By Each Part
        results = []
        futures = {}
        tp: concurrent.futures.ThreadPoolExecutor = (
            concurrent.futures.ThreadPoolExecutor(max_workers=6)
        )

        for idx, chunk in enumerate(
            chunk_by_file_size(ftuple[1], size=upload_size, upload_format=False)
        ):
            logger.info(f"loading part: {idx} part into the upload queue.")
            part_name: str = ftuple[0]
            part_params: dict[str, Any] = {
                "f": "json",
                "partNum": f"{idx + 1}",
                "streamdata": True,
                "size": len(chunk),
            }
            future = tp.submit(
                self._session.post,
                **{
                    "url": parts_url,
                    "params": part_params,
                    "files": {"file": (part_name, chunk, None)},
                },
            )
            futures[future] = part_name
        tp.shutdown(cancel_futures=False)
        return Job(
            futures=futures,
            commit_url=commit_url,
            commit_params={
                "f": "json",
                "id": itemid,
                "type": params["type"],
                "async": True,
            },
            session=self._session,
            itemid=itemid,
            params=params,
            folder=self,
        )

    # ---------------------------------------------------------------------
    def _add_async_large_files(
        self,
        url: str,
        params: dict,
        upload_size: int,
        file_list: dict | list | None,
    ) -> _arcgis_gis.Item | dict[str, Any]:
        """performs the add by parts upload for files over 5 MBs."""

        parts_url: str = url.replace("/addItem", "/addPart")
        ftuple: tuple = file_list.pop("file")
        params.pop("async", None)
        resp: requests.Response = self._session.post(
            url=url, data=params, files=file_list
        )  # Gets the initial Item
        data: dict[str, Any] = resp.json()
        itemid = data.get("id", None) or data.get("itemId", None)
        parts_url: str = url.replace("/addItem", f"/items/{itemid}/addPart")
        commit_url: str = url.replace("/addItem", f"/items/{itemid}/commit")
        # Add By Each Part
        import concurrent.futures

        results = []
        futures = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as tp:
            for idx, chunk in enumerate(
                chunk_by_file_size(ftuple[1], size=upload_size, upload_format=False)
            ):
                part_name: str = f"split{idx}.split"
                part_params: dict[str, Any] = {
                    "f": "json",
                    "partNum": f"{idx + 1}",
                }
                future = tp.submit(
                    self._session.post,
                    **{
                        "url": parts_url,
                        "params": part_params,
                        "files": {"file": (part_name, chunk, None)},
                    },
                )
                futures[future] = part_name
            messages = []
            for future in concurrent.futures.as_completed(futures):
                r = future.result()
                r.raise_for_status()
                data: dict[str, Any] = r.json()
                if "success" in data:
                    results.append(data["success"])
                elif "status" in data and data["status"] == "success":
                    results.append(True)
                else:
                    results.append(False)
                logger.info(r.text)
                messages.append(r.text)
        if all(results):
            commit_params = {
                "f": "json",
                "id": itemid,
                "type": params["type"],
                "async": True,
            }
            commit_params.update(params)
            resp: requests.Response = self._session.post(
                url=commit_url, data=commit_params
            )
            resp.raise_for_status()
            res: dict[str, Any] = resp.json()
            if "success" in res and res["success"]:
                return self._process_item_status(itemid=itemid)
        raise FolderException(str(r.text))

    # ---------------------------------------------------------------------
    def _process_item_status(self, itemid: str) -> _arcgis_gis.Item | dict[str, Any]:
        """Common function that handles the status of a newly added item"""
        i: int = 1
        status_messages: list[str] = [
            "partial",
            "processing",
            "failed",
            "completed",
            "null",
        ]
        status_msg: dict[str, Any] = status(
            resturl=self._gis._portal.resturl,
            session=self._session,
            owner=self._owner,
            itemid=itemid,
        )
        status_code: str | None = status_msg.get("status")
        while status_code in ["processing", "partial"]:
            time.sleep(i)
            if i >= 10:
                i = 10
            else:
                i += 1
            status_msg: dict[str, Any] = status(
                resturl=self._gis._portal.resturl,
                session=self._session,
                owner=self._owner,
                itemid=itemid,
            )
            status_code: str | None = status_msg.get("status")
            if not status_code in status_messages:
                break
        if "id" in status_msg:
            return _arcgis_gis.Item(gis=self._gis, itemid=status_msg["id"])
        elif "itemId" in status_msg:
            count = 5
            while True:
                time.sleep(1)
                try:
                    item = _arcgis_gis.Item(gis=self._gis, itemid=status_msg["itemId"])
                    return item
                except:
                    count -= 1
                    if count <= 0:
                        raise FolderException(f"Could not locate the Item: {itemid}")
        return status_msg

    # ---------------------------------------------------------------------
    def _add_async_text(
        self,
        url: str,
        params: dict,
        file_list: dict | list,
        check_status: bool = False,
    ) -> _arcgis_gis.Item | dict:
        """performs the add workflow"""

        resp: requests.Response = self._session.post(
            url=url, data=params, files=file_list
        )
        data: dict[str, Any] = resp.json()
        itemid = data.get("id", None) or data.get("itemId", None)
        if params.get("async", False):
            return self._process_item_status(itemid=itemid)
        else:
            if itemid:
                return _arcgis_gis.Item(gis=self._gis, itemid=itemid)
        return data

    # ---------------------------------------------------------------------
    def add(
        self,
        item_properties: ItemProperties,
        file: str | None = None,
        text: str | None = None,
        url: str | None = None,
        data_url: str | None = None,
        item_id: str | None = None,
        stream: bool = True,
        upload_file_size: int | None = None,
    ) -> concurrent.futures.Future | Job:
        """
        Adds an :class:`~arcgis.gis.Item` to the current folder.

        .. note::
            This method returns a :class:`concurrent.futures.Future` object. To
            obtain *item*, use :meth:`concurrent.future.Future.result` method.

        =================     ====================================================================
        **Parameter**          **Description**
        -----------------     --------------------------------------------------------------------
        item_properties       Required *ItemProperties* object. The properties for the item to add.
                              When initializing the object, the *title* and *item_type* are
                              required.

                              .. code-block:: python

                                  >>> from arcgis.gis import ItemProperties, ItemTypeEnum

                                  >>> item_props = ItemProperties(title="<item_title>",
                                                                  item_type=ItemTypeEnum.SHAPEFILE.value)
        -----------------     --------------------------------------------------------------------
        file                  Optional string, io.StringIO, or io.BytesIO. Provide the data to the
                              item.
        -----------------     --------------------------------------------------------------------
        text                  Optional String. The JSON content for the item to be submitted.
        -----------------     --------------------------------------------------------------------
        url                   Optional string. The URL of the item to be submitted. The URL can be
                              a URL to a service, a web mapping application, or any other content
                              available at that URL.
        -----------------     --------------------------------------------------------------------
        data_url              Optional string. The URL where the item can be downloaded. The
                              resource will be downloaded and stored as a file type. Similar to
                              uploading a file to be added, but instead of transferring the
                              contents of the file, the URL of the data file is referenced and
                              creates a file item. The referenced URL must be an unsecured URL
                              where the data can be downloaded. This parameter requires the
                              operation to be performed asynchronously. Once the job status
                              returns as complete, the item can be downloaded and the item is
                              added successfully.
        -----------------     --------------------------------------------------------------------
        item_id               Optional string. Available in ArcGIS Enterprise 10.8.1+. Not available in ArcGIS Online.
                              This parameter allows the desired item id to be specified during creation which
                              can be useful for cloning and automated content creation scenarios.
                              The specified id must be a 32 character GUID string without any special characters.

                              If the `item_id` is already being used, an error will be raised
                              during the `add` operation.

                              Example: item_id=9311d21a9a2047d19c0faaebd6f2cca6
        -----------------     --------------------------------------------------------------------
        stream                Optional bool. This parameter is used to override the default streaming
                              upload methods for the ArcGIS API for Python. This should only be used
                              in very rare cases where the enterprise disallows streaming uploads.
                              The default is `True`.
        -----------------     --------------------------------------------------------------------
        upload_file_size      Optional int. This is used when uploading very large files
                              (50GB+ in size).
                              This is the part size to split the file into when performing a
                              streaming upload.  Each piece will be the size of this value.
        =================     ====================================================================

        :returns:
            :class:`concurrent.futures.Future` object

        .. code-block:: python

            # Usage Example:
            >>> from arcgis.gis import GIS, ItemProperties, ItemTypeEnum

            >>> gis = GIS(profile="your_organization_profile")

            >>> data_path = r"<path_to_zipped_shapefile>"
            >>> item_props = ItemProperties(title="new_shapefile_item",
                                            item_type=ItemTypeEnum.SHAPEFILE.value,
                                            tags="new_shp_item,from_api",
                                            snippet="Demo item added from Python API")

            >>> folders_obj = gis.content.folders
            >>> item_folder = folders_obj.get(folder="water_data")

            >>> add_job = item_folder.add(item_properties=item_props,
                                          file=data_path)
            >>> if not add_job.done():
            >>>     print("...job precessing...")
            >>> else:
            >>>     new_shp_item = add_job.result()

            >>> new_flyr_item = new_shp_item.publish()
        """
        item_properties: dict = dict(item_properties)
        # remove None values
        item_properties = {
            key: value for key, value in item_properties.items() if not value is None
        }
        if item_properties.get("overwrite", False):
            logger.warning(
                "The property `overwrite` is deprecated and support will be removed two releases after 2.4.0."
            )
        text: str = text or item_properties.pop("text", None)

        if (
            file
            and isinstance(file, (io.StringIO, io.BytesIO))
            and not item_properties.get("fileName")
        ):
            raise ValueError(
                "When providing a `StringIO` or `BytesIO` object, `file_name` must be given in the `ItemProperties` class."
            )

        upload_size: float | int | None = None
        thumbnail: str | None = item_properties.pop("thumbnail", None)
        metadata: str | None = item_properties.pop("metadata", None)
        file_list: dict[str, Any] = {}
        owner: str | None = None
        params: dict[str, Any] = {
            "f": "json",
            "async": True,
        }
        if is_valid_item_id(item_id):
            params["itemIdToCreate"] = item_id

        if thumbnail and isinstance(thumbnail, tuple):
            fn, thumbnail = thumbnail
            file_list["thumbnail"] = create_upload_tuple(thumbnail, file_name=fn)
        elif thumbnail and os.path.isfile(thumbnail):
            file_list["thumbnail"] = create_upload_tuple(thumbnail)

        if metadata:
            file_list["metadata"] = create_upload_tuple(metadata)

        for k in list(item_properties.keys()):
            try:
                if isinstance(item_properties[k], str) and os.path.isfile(
                    item_properties[k]
                ):
                    file_list[k] = create_upload_tuple(item_properties.pop(k))
            except:
                ...
        params.update(item_properties)

        if self._owner:
            owner = self._owner
        elif owner and hasattr(owner, "username"):
            owner = getattr(owner, "username")
        elif owner is None:
            owner = self._gis.users.me.username
        elif isinstance(owner, str) == False:
            raise ValueError("Owner must be a string or User object.")

        folder: str = self._folder_id
        is_root_folder: bool = folder == "Root Folder"
        curl: str = (
            f"{self._gis._portal.resturl}content/users/{owner if is_root_folder else f'{owner}/{folder}'}/addItem"
        )

        max_workers: int = 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as tp:
            if stream == True and file:
                # upload by streaming data
                logger.info("Adding Item by parts using streaming.")
                upload_size = upload_file_size
                params["multipart"] = True
                params["fileName"] = params.get("fileName") or os.path.basename(file)
                params["async"] = True
                params = _process_parameters(params)
                file_list["file"] = create_upload_tuple(
                    file, file_name=item_properties.pop("fileName", None)
                )
                job = self._add_async_streaming(
                    **{
                        "url": curl,
                        "params": params,
                        "file_list": file_list,
                        "upload_size": upload_size,
                    }
                )

                return job
            if (text and file is None and url is None and data_url is None) or (
                text is None
                and file is None
                and url is None
                and item_properties["type"] in _JSON_ITEMS
            ):
                #  text workflow
                params["async"] = False
                if text and not isinstance(text, str):
                    text: str = json.dumps(text)
                if text:
                    params["text"] = text
                params = _process_parameters(params)
                future = tp.submit(
                    self._add_async_text,
                    **{
                        "url": curl,
                        "params": params,
                        "file_list": file_list,
                        "check_status": params["async"],
                    },
                )
                tp.shutdown(wait=True)
                return future
            if file and text is None and url is None and data_url is None:
                #  file workflow
                params["async"] = True
                file_list["file"] = create_upload_tuple(
                    file, file_name=item_properties.get("file_name", None)
                )
                upload_size = calculate_upload_size(file)
                if upload_size <= 5242880:  # 5mb
                    logger.info(
                        "Adding Item via synchronous operation because it's under 5 MBs."
                    )
                    #  perform basic upload.
                    params["multipart"] = False
                    params = _process_parameters(params)
                    future = tp.submit(
                        self._add_async_text,
                        **{
                            "url": curl,
                            "params": params,
                            "file_list": file_list,
                            "check_status": params["async"],
                        },
                    )
                    tp.shutdown(wait=True)
                    return future

                else:
                    logger.info("Adding Item by parts because it's over 5 MBs.")
                    params["multipart"] = True
                    params["fileName"] = params.get(
                        "fileName", None
                    ) or os.path.basename(file)
                    params = _process_parameters(params)
                    future = tp.submit(
                        self._add_async_large_files,
                        **{
                            "url": curl,
                            "params": params,
                            "file_list": file_list,
                            "upload_size": upload_size,
                        },
                    )
                    tp.shutdown(wait=True)
                    return future
            if (file is None and text is None and url and data_url is None) or (
                file is None and text is None and url is None and data_url is None
            ):
                params["async"] = False
                if not url and "url" in params:
                    url = params.get("url")
                if url:
                    params["url"] = url
                else:
                    logger.warning("Creating an empty item.")
                params = _process_parameters(params)
                future = tp.submit(
                    self._add_async_text,
                    **{
                        "url": curl,
                        "params": params,
                        "file_list": file_list,
                        "check_status": params["async"],
                    },
                )
                tp.shutdown(wait=True)
                return future
            if file is None and text is None and url is None and data_url:
                params["async"] = True
                params["dataUrl"] = data_url
                params = _process_parameters(params)
                future = tp.submit(
                    self._add_async_text,
                    **{
                        "url": curl,
                        "params": params,
                        "file_list": file_list,
                        "check_status": params["async"],
                    },
                )
                tp.shutdown(wait=True)
                return future


###########################################################################
class Folders:
    """This class is a helper class for accessing and managing
    :class:`folders <arcgis.gis._impl._content_manager.Folder>`. A *Folders*
    object is not meant to be initialized directly, but rather returned by
    the :attr:`~arcgis.gis.ContentManager.folders` property of the
    :class:`~arcgis.gis.ContentManager` class.

    .. code-block:: python

        >>> from arcgis.gis import GIS
        >>> gis = GIS(profile="your_online_or_enterprise_profile")

        >>> cm = gis.content
        >>> folders_obj = cm.folders
        >>> folders_obj
        <arcgis.gis._impl._content_manager.folder.core.Folders at <memory_addr>>
    """

    def __init__(self, gis: _arcgis_gis.GIS) -> "Folders":
        self._gis = gis
        self._session: EsriSession = gis._con._session

    # ---------------------------------------------------------------------
    def __str__(self) -> str:
        return f"< Folders >"

    # ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return self.__str__()

    @property
    @lru_cache(maxsize=255)
    def _me(self) -> dict[str, Any]:
        """Gets the logged in user."""
        url: str = f"{self._gis._portal.resturl}community/self"
        params = {
            "f": "json",
        }
        resp: requests.Response = self._session.get(url=url, params=params)
        resp.raise_for_status()
        return resp.json()

    # ---------------------------------------------------------------------
    def _get_or_create(self, folder: str, owner: str | None = None) -> Folder:
        """gets or creates a folder"""
        fldr: Folder = self.get(folder=folder, owner=owner)
        if fldr is None:
            fldr = self.create(folder=folder, owner=owner)
        return fldr

    # ----------------------------------------------------------------------
    def get(
        self,
        folder: str | None = None,
        owner: str | "User" | None = None,
    ) -> Folder | None:
        """
        Gets a single :class:`~arcgis.gis._impl._content_manager.Folder` owned
        by the :class:`~arcgis.gis.User` entered as the *owner* argument.

        ================  ========================================================
        **Parameter**      **Description**
        ----------------  --------------------------------------------------------
        folder            Optional string. The name of the
                          :class:`~arcgis.gis._impl._content_manager.Folder` object
                          to get from the *owner* argument's folders.
        ----------------  --------------------------------------------------------
        owner             Optional string. The :attr:`~arcgis.gis.User.username`
                          value or a :class:`~arcgis.gis.User` object indicating
                          the the owner of the folder to get.

                          .. note::
                              Must have appropriate permissions to get another
                              user's *folders*.
        ================  ========================================================

        .. note::
            If no *folder* or no *owner* argument provided, the
            root folder of the logged-in *user* is returned.

        :returns:
            :class:`~arcgis.gis._impl._content_manager.Folder` object.

        .. code-block:: python

            # Usage Example #1: Get Root Folder of another user
            >>> from arcgis.gis import GIS
            >>> gis = GIS(profile="your_online_or_enterprise_admin_profile")

            >>> user_folder = gis.content.folders.get(owner="gis_editor3")
            >>> user_folder
                < Folder: Root Folder Owner: gis_editor3>

            # Usage Example #2: Get particular folder from a specific user
            >>> h2o_folder = gis.content.folders.get(folder="Water_Resources",
                                                     owner="h2o_project_user")
            >>> h2o_folder
                < Folder: Water_Resources Owner: h2o_project_user>
        """
        if folder is None:
            folder = "Root Folder"
        elif folder.lower() in ["/", "root", "Root Folder", "root folder"]:
            folder = "Root Folder"
        for fld in self.list(owner=owner):
            if (
                fld.name.lower() == folder.lower()
                or fld.properties["id"] == folder.lower()
            ):
                return fld
        return None

    # ---------------------------------------------------------------------
    def create(
        self,
        folder: str,
        owner: str | "User" = None,
        exist_ok: bool = False,
    ) -> Folder:
        """
        The ``create`` method creates a folder named with the value of the
        *folder* argument owned by the :class:`user <arcgis.gis.User>` entered
        in the *owner* argument.

        .. note::
            The ``create`` method raises a `FolderException` if the folder already exists.
            Additionally, if owner is not specified, owner is set as the logged in user.


        ================  ==========================================================================
        **Parameter**      **Description**
        ----------------  --------------------------------------------------------------------------
        folder            Required string. The name of the folder to create for the owner.
        ----------------  --------------------------------------------------------------------------
        owner             Optional string of the :attr:`~arcgis.gis.User.username` attribute
                          or :class:`~arcgis.gis.User` object who will own the *folder*.

                          .. note::
                              Must have administrator privileges to create content for another *user*.
        ----------------  --------------------------------------------------------------------------
        exist_ok          Optional Bool. If exist_ok is False (the default), a FolderException is raised
                          if the target directory already exists.
        ================  ==========================================================================

        :return:
            A :class:`~arcgis.gis._impl._content_manager.Folder` object.

        .. code-block:: python

            # Usage Example
            >>> from arcgis.gis import GIS
            >>> gis = GIS(profile="your_online_or_enterprise_admin_profile")
            >>> new_folder = gis.content.folders.create("Hurricane_Data", owner= "User1234")
            >>> new_folder.name
                'Hurricane_Data'
        """
        if exist_ok:
            return self._get_or_create(folder=folder, owner=owner)
        if folder in ["/", None, ""]:  # we don't create root folder
            logger.warning("Cannot create the root folder, just returning the root.")
            return Folder(gis=self._gis)
        params: dict[str, Any] = {
            "f": "json",
            "title": folder,
        }
        if owner is None:
            owner = self._gis.users.me.username
        elif hasattr(owner, "username"):
            owner = getattr(owner, "username")
        elif isinstance(owner, str) == False:
            raise ValueError("The owner must be a string or User.")

        resp: requests.Response = self._session.post(
            url=f"{self._gis._portal.resturl}content/users/{owner}/createFolder",
            data=params,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        if data and data.get("success"):
            return Folder(
                gis=self._gis,
                folder=data["folder"]["id"],
                properties=data.get("folder", None),
                owner=owner,
            )
        elif data.get("success", False) == False:
            raise FolderException(f"Cannot generate folder: {data}")

    # ---------------------------------------------------------------------
    def list(self, owner: str | "User" | None = None) -> Iterator[Folder]:
        """
        Returns a Python generator over the
        :class:`~arcgis.gis._impl._content_manager.Folder` objects owned by the
        *username* entered in the *owner* argument.

        .. note::
            Must have appropriate privileges to list another user's *folder's*.

        ================  ========================================================
        **Parameter**      **Description**
        ----------------  --------------------------------------------------------
        owner             Optional string. An :attr:`~arcgis.gis.User.username`
                          value or :class:`~arcgis.gis.User` object to indicate
                          the *user* whose folders to examine.

                          .. note::
                              If no argument is provided, a generator over the
                              list of the currently logged in *user's*
                              *folders* is returned.
        ================  ========================================================

        :return:
            Iterator[:class:`~arcgis.gis._impl._content_manager.Folder`]

            A Python `generator <https://realpython.com/introduction-to-python-generators/#understanding-generators>`_
            for iterating over the *owner* argument's folders.

        .. code-block:: python

            # Usage example #1:

            >>> gis = GIS(profile="your_online_admin_profile")

            >>> folders_mgr = gis.content.folders
            >>> user1_folder_gen = folders_mgr.list(owner="web_gis_user_1")
            >>> for user_folder in user1_folder_gen:
                    print(f"{user_folder.name}")
            Root Folder
            Water_Resources_data
            Electric Utility Data
            project_testing_data
            Maps_for_population

            # Usage example #2:

            >>> folders_mgr = gis.content.folders
            >>> user2_folder_gen = folders_mgr.list(owner="web_gis_user_2")
            >>> next(user2_folder_gen)
            < Folder: Root Folder Owner: web_gis_user_2>
            >>> next(user2_folder_gen)
            < Folder: City_project_data Owner: web_gis_user_2>
        """
        if owner and hasattr(owner, "username"):
            owner: str = getattr(owner, "username")
        elif owner:
            owner: str = owner
        else:
            owner: str = self._me.get("username", None)

        if owner is None:
            logger.warning("User is anonymous, exiting")
            return None

        url: str = f"{self._gis._portal.resturl}content/users/{owner}"
        params: dict[str, Any] = {
            "f": "json",
        }
        session: EsriSession = self._session
        resp: requests.Response = session.get(url=url, params=params)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        folder = {
            "id": "Root Folder",
            "name": "Root Folder",
        }
        yield Folder(gis=self._gis, owner=owner, properties=folder)  #  root
        for folder in data.get("folders", []):
            yield Folder(
                gis=self._gis,
                folder=folder["id"],
                owner=owner,
                properties=folder,
            )
