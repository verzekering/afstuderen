from __future__ import annotations
from arcgis.auth.tools import LazyLoader
from arcgis.auth import EsriSession
from arcgis.gis import GIS

from typing import Any
import requests

json = LazyLoader("json")

__all__ = ["ClassificationManager"]


class ClassificationManager:
    """
    This class provides properties for getting information about the
    classification schema and methods for managing it.  This class is not
    meant to be initialized directly, but is accessed by using the
    :attr:`~arcgis.gis.admin.PortalAdminManager.classification` property on the
    ArcGIS Enterprise admin object.

    .. note::
        ArcGIS Enterprise only.

    .. code-block:: python

        >>> from arcgis.gis import GIS
        >>> gis = GIS(profile="your_enterprise_admin_profile")

        >>> classification_mgr = gis.admin.classification
        >>> classification_mgr

        Classification Manager @ <enterprise_url>/portal/sharing/rest/portals/self/classification

    """

    url: str
    gis: GIS
    session: EsriSession
    _properties: dict | None = None

    # ---------------------------------------------------------------------
    def __init__(self, url: str, gis: GIS) -> None:
        if url.endswith("/classification") == False:
            url += "/classification"
        self.url = url
        self.gis = gis
        self.session = gis.session

    # ---------------------------------------------------------------------
    def __str__(self) -> str:
        return f"< Classification Manager @ {self.url} >"

    # ---------------------------------------------------------------------
    def __repr__(self) -> str:
        return f"< Classification Manager @ {self.url} >"

    # ---------------------------------------------------------------------
    @property
    def properties(self) -> dict[str, Any]:
        """
        Returns a Python dictionary with 2 keys whose values indicate the
        specific version of the classification schema and whether the
        organization has a scheme defined.

        * *grammarVersion*
        * *hasClassificationSchema*

        .. code-block:: python

            # Example Usage:
            >>> from arcgis.gis import GIS
            >>> gis = GIS(profile="your_enterprise_admin_profile")

            >>> classify_mgr = gis.admin.classification
            >>> classify_mgr.properties

            {'grammarVersion': '2.0', 'hasClassificationSchema': True}
        """
        if self._properties is None:
            params = {
                "f": "json",
            }
            self._properties = self.session.get(self.url, params=params).json()
        return self._properties

    # ---------------------------------------------------------------------
    @property
    def schema(self) -> dict | None:
        """
        Property that returns a Python dictionary representation of the defined
        classification schema of the organization.

        :returns:
            Dictionary representation of the classification schema.

        .. note::
            The value of each key returned will vary by organization.
            See the `Esri classification <https://github.com/Esri/classification>`_
            repo for more detailed information regarding the classification
            schema.
        """
        url: str = f"{self.url}/classificationSchema"
        params: dict = {
            "f": "json",
        }
        resp: requests.Response = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    # ---------------------------------------------------------------------
    def delete(self) -> bool:
        """
        Operation to remove the currently defined classification schema of the
        organization.

        :returns:
            Boolean value indicating the success or failure of the operation.

        .. code-block:: python

            # Usage Example
            >>> from arcgis.GIS import GIS
            >>> gis = GIS(profile="your_enterprise_admin_profile")

            >>> classify_mgr = gis.admin.classification
            >>> classify_mgr.delete()

            True
        """
        if self.schema == {
            "classificationSchema": []
        }:  #  no schema set, so nothing to clear out
            return True
        url: str = f"{self.url}/deleteClassificationSchema"
        params: dict = {
            "f": "json",
        }
        resp: requests.Response = self.session.post(url, data=params)
        resp.raise_for_status()
        data: dict = resp.json()
        if (
            "error" in data
            and data["error"].get("message", "")
            != "Resource does not exist or is inaccessible."
        ):
            raise Exception(data)
        else:
            return True  # schema isn't set.
        self._properties = None
        return data.get("success", False)

    # ---------------------------------------------------------------------
    def add(self, schema_file: str) -> bool:
        """
        Adds a schema definition from a file to the current enterprise

        .. note::
            For detailed instructions on creating a classification schema, as
            well as example schemas, visit the ArcGIS/Classification GitHub
            repository.

        =================     ==================================================
        **Parameter**         **Description**
        =================     ==================================================
        schema_file           Required string. Pathway to a text file containing
                              the JSON schema that defines the configuration
                              options of the classification schema for the ArcGIS
                              Enterprise organization.
        =================     ==================================================

        :returns:
            Boolean value indicating success or failure of the operation.

        .. code-block:: python

            # Usage Example
            >>> from arcgis.GIS import GIS
            >>> gis = GIS(profile="your_enterprise_admin_profile")

            >>> classify_mgr = gis.admin.classification
            >>> classify_file_path = r"/path/on/system"

            >>> classify_mgr.add(schema_file=classify_file_path)

            True
        """
        url: str = f"{self.url}/assignClassificationSchema"
        params: dict = {
            "f": "json",
        }

        with open(schema_file, "rb") as f:
            resp: requests.Response = self.session.post(
                url,
                data=params,
                files={"classificationSchemaFile": f},
            )

            resp.raise_for_status()
            data: dict = resp.json()
            if "error" in data:
                raise Exception(data)
            self._properties = None
            return data.get("success", False)
        self._properties = None
        return False

    # ---------------------------------------------------------------------
    def validate_schema_file(self, schema_file: str) -> bool:
        """
        Operation that determines whether the schema defined in a file adheres
        to the classification grammar included in the Portal for ArcGIS
        component of the ArcGIS Enterprise deployment.

        =================     ==================================================
        **Parameter**         **Description**
        =================     ==================================================
        schema_file           Required string. Path to a text file containing
                              the JSON schema to validate.
        =================     ==================================================

        :returns:
           Boolean value indication success or failure of the operation.
        """
        url: str = f"{self.url}/validateClassificationSchema"
        params: dict = {
            "f": "json",
        }
        data: dict = {}
        with open(schema_file, "rb") as f:
            resp: requests.Response = self.session.post(
                url,
                data=params,
                files={"classificationSchemaFile": f},
            )

            resp.raise_for_status()
            data: dict = resp.json()
        if "error" in data:
            raise Exception(data)
        return data.get("success", False)

    # ---------------------------------------------------------------------
    def validate_item_schema(
        self,
        classification: dict[str, Any] | None = None,
        classification_schema: str | None = None,
    ) -> bool:
        """
        Operation that would verify whether the classification that would be
        given to an :class:`~arcgis.gis.Item` is in the correct format.

        =======================    =============================================================
        **Parameter**              **Description**
        -----------------------    -------------------------------------------------------------
        classification             Optional dict. The classification payload for a given item.
        -----------------------    -------------------------------------------------------------
        classification_schema      Optional str. The classification payload represented as a
                                   file on the system.
        =======================    =============================================================


        """
        url: str = f"{self.url}/validateClassification"
        params = {
            "f": "json",
        }
        files: dict = {}
        if classification is None and classification_schema is None:
            raise ValueError(
                "A `classification` string or `classification_schema` file path must be provided."
            )
        if isinstance(classification, dict):
            classification: str = json.dumps(classification)
            files["classificationValue"] = (None, classification)
        elif isinstance(classification, str):
            files["classificationValue"] = (None, classification)
        else:
            files["classificationValue"] = (None, "")

        if classification_schema:
            with open(classification_schema, "rb") as f:
                files["classificationValueFile"] = f
                resp: requests.Response = self.session.post(
                    url, data=params, files=files
                )

        else:
            resp: requests.Response = self.session.post(
                url,
                params=params,
                files=files,
            )
        resp.raise_for_status()
        data: dict = resp.json()
        if "error" in data:
            raise Exception(data)
        return data.get("success", False)
