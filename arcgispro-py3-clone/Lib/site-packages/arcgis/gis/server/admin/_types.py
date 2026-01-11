from __future__ import annotations
import requests
from typing import Any, Iterable
from arcgis.auth import EsriSession
from ._uploads import Uploads

__all__ = [
    "RegisteredExtension",
    "ExtensionManager",
    "TypesManager",
    "ProvidersManager",
]


###########################################################################
class RegisteredExtension:
    """
    Represents a single SOE or SOI deployment.
    """

    url: str | None = None
    extension_name: str | None = None
    session: EsriSession | None = None
    _uploads: Uploads = None
    _properties: dict[str, Any] | None = None

    def __init__(
        self,
        url: str,
        session: EsriSession,
        extension_name: str,
        properties: dict[str, Any],
        upload: Uploads,
    ) -> None:
        self.url = url
        self.session = session
        self._properties = properties
        self.extension_name = extension_name
        self._uploads: Uploads = upload

    def __str__(self) -> str:
        return f"< {self.__class__.__name__}:{self.extension_name} >"

    def __repr__(self) -> str:
        return f"< {self.__class__.__name__}:{self.extension_name} >"

    @property
    def name(self) -> str:
        """returns the SOI/SOE name"""
        return self.extension_name

    def update(self, file_path: str) -> bool:
        """updates the extension"""
        url: str = f"{self.url}/update"

        status, upload = self._uploads.upload(path=file_path)

        item_id: str = upload["item"]["itemID"]
        params: dict[str, Any] = {
            "f": "json",
            "id": item_id,
        }
        resp: requests.Response = self.session.post(url=url, data=params)
        resp.raise_for_status()
        data: dict = resp.json()
        return data.get("status", "failed") == "success"

    def delete(self) -> bool:
        """Removes the extension from the server"""
        url: str = f"{self.url}/unregister"
        params: dict[str, Any] = {
            "f": "json",
            "extensionFilename": self.extension_name,
        }
        resp: requests.Response = self.session.post(url=url, data=params)
        resp.raise_for_status()
        data: dict = resp.json()
        return data.get("status", "failed") == "success"

    @property
    def properties(self) -> dict[str, Any]:
        """returns the properties of the extension"""
        return self._properties


###########################################################################
class ExtensionManager:
    """Manages the Service Extension Objects"""

    _um: Uploads
    url: str
    session: EsriSession
    _properties: dict[str, Any] | None = None

    def __init__(self, url: str, session: EsriSession, um: Uploads) -> None:
        self.url = url
        self.session = session
        self._um = um

    def __str__(self) -> str:
        return f"< {self.__class__.__name__} >"

    def __repr__(self) -> str:
        return f"< {self.__class__.__name__} >"

    @property
    def properties(self) -> dict[str, Any]:
        """returns the properties of the extension"""
        if self._properties is None:
            resp: requests.Response = self.session.get(
                url=self.url,
                params={
                    "f": "json",
                },
            )
            resp.raise_for_status()
            self._properties = resp.json()
        return self._properties

    def register(self, file_path: str) -> bool:
        """
        Registers a new extension

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        file_path           Required str. The path to the SOI/SOE zipped file.
        ===============     ====================================================================

        :return: dict
        """
        self._properties = None
        url: str = f"{self.url}/register"
        status, upload = self._um.upload(file_path)
        item_id: str = upload["item"]["itemID"]
        params: dict[str, Any] = {
            "f": "json",
            "id": item_id,
        }
        resp: requests.Response = self.session.post(url=url, data=params)
        data: dict = resp.json()
        return data.get("status", "failed") == "success"

    @property
    def extensions(self) -> Iterable[RegisteredExtension]:
        """returns all the registered extensions"""
        data = self.properties
        for key in data.keys():

            yield RegisteredExtension(
                url=self.url,
                session=self.session,
                properties=data[key],
                extension_name=key,
                upload=self._um,
            )


###########################################################################
class ProvidersManager:
    """
    The providers resource returns the supported provider types for the
    GIS services in your organization. Starting at ArcGIS Enterprise
    10.9.1, this resource includes an enabled providers section that
    specifies which of the supported providers are currently enabled.
    At Enterprise 11.0, only ArcObjects11 is supported as an enabled
    provider.
    """

    url: str
    session: EsriSession
    _properties: dict[str, Any] | None = None

    def __init__(self, url: str, session: EsriSession) -> None:
        """initializer"""
        self.url = url
        self.session = session

    def __str__(self) -> str:
        return f"< {self.__class__.__name__} >"

    def __repr__(self) -> str:
        return f"< {self.__class__.__name__} >"

    @property
    def properties(self) -> dict[str, Any]:
        """returns the properties of the endpoint."""
        resp: requests.Response = self.session.get(
            url=self.url,
            params={
                "f": "json",
            },
        )
        resp.raise_for_status()
        return resp.json()

    def get(self, provider: str) -> dict[str, Any]:
        """
        Returns the supported services for a given provider

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        provider            Required String. The single provider to return supported service
                            information on.  The registered providers can be obtained from the
                            `properties` property.  The provider types will vary based on your
                            version of ArcGIS Server.
        ===============     ====================================================================

        :return: dict
        """
        if provider in self.properties.get("providers", []):
            url: str = f"{self.url}/{provider}"
            resp: requests.Response = self.session.get(
                url=url,
                params={
                    "f": "json",
                },
            )
            resp.raise_for_status()
            return resp.json()
        else:
            val = "".join(self.properties.get("providers", []))
            raise ValueError(f"Provider must be values: {val}")


###########################################################################
class TypesManager:
    """
    The types resource provides metadata about all service types and
    extensions that can be enabled on each service type. The services
    framework uses this information to validate a service and construct the
    various objects in the service. The metadata contains identifiers for
    each object, a default list of capabilities, properties, and other
    resource information (like WSDL and so forth). Type information for a
    specific service type can be accessed by appending the type name to
    this URL.
    """

    url: str | None = None
    session: EsriSession | None = None
    _properties: dict | None = None
    uploads: Uploads
    _extensions: ExtensionManager | None = None
    _pm: ProvidersManager | None = None

    def __init__(self, uploads: Uploads, url: str, session: EsriSession) -> None:
        """initializer"""
        self.url = url
        self.session = session
        self.uploads = uploads

    def __str__(self) -> str:
        return f"< {self.__class__.__name__} >"

    def __repr__(self) -> str:
        return f"< {self.__class__.__name__} >"

    @property
    def properties(self) -> dict[str, Any]:
        """returns the types properties"""
        if self._properties is None:
            resp: requests.Response = self.session.get(
                url=self.url,
                params={
                    "f": "json",
                },
            )
            resp.raise_for_status()
            self._properties = resp.json()
        return self._properties

    @property
    def extension(self) -> ExtensionManager:
        """
        The extensions resource is a collection of all the custom server
        object extensions that have been uploaded and registered with the
        server. You can register new server object extensions using the
        Register Extension operation. When updating an existing extension,
        you need to use the Update Extension operation. If an extension is
        no longer required, you can use the Unregister operation to remove
        the extension from the site.
        """
        if self._extensions is None:
            url: str = f"{self.url}/extensions"
            self._extensions = ExtensionManager(
                url=url, session=self.session, um=self.uploads
            )
        return self._extensions

    @property
    def provider(self) -> ProvidersManager:
        """
        The providers resource returns the supported provider types for the
        GIS services in your organization. Starting at ArcGIS Enterprise
        10.9.1, this resource includes an enabled providers section that
        specifies which of the supported providers are currently enabled.
        At Enterprise 11.0, only ArcObjects11 is supported as an enabled
        provider.
        """
        if self._pm is None:
            url: str = f"{self.url}/providers"
            self._pm = ProvidersManager(url=url, session=self.session)
        return self._pm
