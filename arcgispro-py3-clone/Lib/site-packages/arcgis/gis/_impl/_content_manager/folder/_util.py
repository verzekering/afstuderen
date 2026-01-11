from __future__ import annotations
import io
import os
import json
import logging
import requests
import mimetypes
from functools import lru_cache
from types import NoneType
from typing import Optional, Any, Iterator, Tuple, Union
from arcgis.auth import EsriSession
from arcgis.auth.tools import LazyLoader

_arcgis_gis = LazyLoader("arcgis.gis")

__log__ = logging.getLogger()

__all__ = [
    "guess_mimetype",
    "create_upload_tuple",
    "close_upload_files",
    "_get_folder_id",
    "_get_folder_name",
    "close_upload_files",
    "calculate_upload_size",
    "chunk_by_file_size",
    "status",
]


# ----------------------------------------------------------------------
def status(
    resturl: str,
    session: EsriSession,
    owner: str,
    itemid: str,
    job_id: Optional[str] = None,
    job_type: Optional[str] = None,
):
    """
    The ``status`` method provides the status of an :class:`~arcgis.gis.Item` in the following situations:
        1. Publishing an :class:`~arcgis.gis.Item`
        2. Adding an :class:`~arcgis.gis.Item` in async mode
        3. Adding with a multipart upload. `Partial` is available for ``Add Item Multipart`` when only a part is
        uploaded and the :class:`~arcgis.gis.Item` object is not committed.


    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    job_id              Optional string. The job ID returned during publish, generateFeatures,
                        export, and createService calls.
    ---------------     --------------------------------------------------------------------
    job_type            Optional string. The type of asynchronous job for which the status
                        has to be checked. Default is none, which checks the item's status.
                        This parameter is optional unless used with the operations listed
                        below. Values: `publish`, `generateFeatures`, `export`, and `createService`
    ===============     ====================================================================

    :return:
       The status of a publishing :class:`~arcgis.gis.Item` object.

    .. code-block:: python

        # Usage Example

        >>> item.status(job_type="generateFeatures")
    """
    params = {"f": "json"}
    data_path = f"{resturl}content/users/{owner}/items/{itemid}/status"
    if job_type is not None:
        params["jobType"] = job_type
    if job_id is not None:
        params["jobId"] = job_id
    resp: requests.Response = session.get(url=data_path, params=params)
    resp.raise_for_status()
    return resp.json()


def chunk_by_file_size(
    file_path: Union[str, io.BytesIO, io.StringIO],
    size: int | None = None,
    parameter_name: str = "file",
    upload_format: bool = False,
) -> Iterator[Union[Tuple[str, Union[bytes, str], str], bytes, str]]:
    """Lazy function (generator) to read a file piece by piece using os module.
    Default chunk size: 1k."""
    if size is None:
        size = calculate_upload_size(file_path)
        __log__.debug(f"Calculated chunk size: {size / (1024 * 1024)} MB")
    if isinstance(file_path, str) and not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    if not isinstance(size, int) or size <= 0:
        raise ValueError("size must be a positive integer")
    i: int = 1
    if isinstance(file_path, (io.BytesIO, io.StringIO, io.BufferedReader)):
        file_path.seek(0)
        while True:
            chunk = file_path.read(size)
            if not chunk:
                break
            if upload_format:
                fpath: str = f"split{i}.split"
                yield parameter_name, chunk, fpath
            else:
                yield chunk
            i += 1
    else:
        fd = os.open(file_path, os.O_RDONLY)
        try:
            while True:
                chunk = os.read(fd, size)
                if not chunk:
                    break
                if upload_format:
                    fpath: str = f"split{i}.split"
                    yield parameter_name, chunk, fpath
                else:
                    yield chunk
                i += 1
        finally:
            os.close(fd)


# -------------------------------------------------------------------------
@lru_cache(maxsize=255)
def guess_mimetype(extension: str) -> str:
    """guesses the mimetype for an extension"""
    if extension in ["", None]:
        return None
    return mimetypes.guess_type(f"t{extension}")[0]


# -------------------------------------------------------------------------
def create_upload_tuple(file: str | io.StringIO | io.BytesIO, **kwargs) -> tuple:
    """
    Creates the tuple used for uploading a file

    Returns a tuple of the file name, no-param lambda returning a file stream, and mimetype.
    """
    if isinstance(file, (io.StringIO, io.BytesIO)):
        if not "file_name" in kwargs:
            raise ValueError(
                "The `file_name` is required when using io.BytesIO or io.StringIO."
            )
        file_name = kwargs.pop("file_name")
        _, ext = os.path.splitext(file_name)
        return (
            file_name,
            file,
            guess_mimetype(ext),
        )
    if isinstance(file, str) and os.path.exists(file):
        _, ext = os.path.splitext(file)
        return (
            os.path.basename(file),
            # TODO @jtroe @achapkowski, consider using a lambda here
            # to open the file when needed, instead of opening it here.
            open(file, "rb"),
            guess_mimetype(ext),
        )
    raise ValueError(
        "Could not parse the file, ensure it exists and is of type string."
    )


# -------------------------------------------------------------------------
def close_upload_files(upload_tuple: list[tuple]) -> None:
    """Closes the files once the upload is completed."""
    for ut in upload_tuple:
        ut[1].close()
        del ut


# -------------------------------------------------------------------------
@lru_cache(maxsize=100)
def calculate_upload_size(fp: str | io.BytesIO | io.StringIO) -> int:
    """calculates the file MAX upload limit."""
    if isinstance(fp, (io.BytesIO, io.StringIO, io.BufferedReader)):
        fp.seek(0, os.SEEK_END)
        size: int = fp.tell()
        fp.seek(0)  # Reset the pointer to the beginning
    else:
        fd = os.open(fp, os.O_RDONLY)
        size: int = os.fstat(fd).st_size
        os.close(fd)

    if size <= 5 * (1024 * 1024):
        return int(5 * (1024 * 1024))
    elif size > 5 * (1024 * 1024) and size <= 10 * (1024 * 1024):
        return int(7 * (1024 * 1024))
    elif size > 10 * (1024 * 1024) and size <= 15 * (1024 * 1024):
        return int(13 * (1024 * 1024))
    elif size > 15 * (1024 * 1024) and size <= 25 * (1024 * 1024):
        return int(25 * (1024 * 1024))
    elif size > 25 * (1024 * 1024) and size <= 35 * (1024 * 1024):
        return int(30 * (1024 * 1024))
    elif size > 35 * (1024 * 1024) and size <= 100 * (1024 * 1024):
        return int(50 * (1024 * 1024))
    elif size > 100 * (1024 * 1024) and size <= 200 * (1024 * 1024):
        return int(100 / 2 * (1024 * 1024))
    elif size > 200 * (1024 * 1024) and size <= 300 * (1024 * 1024):
        return int(200 / 2 * (1024 * 1024))
    elif size > 300 * (1024 * 1024) and size <= 600 * (1024 * 1024):
        return int(300 / 2 * (1024 * 1024))
    elif size > 700 * (1024 * 1024) and size <= 1000 * (1024 * 1024):
        return int(700 / 2 * (1024 * 1024))
    else:
        return int(size / 2000)  # null case split by 2K parts.


# -------------------------------------------------------------------------
@lru_cache(maxsize=255)
def _get_folder_id(
    gis: _arcgis_gis.GIS, owner: str, folder_name: str
) -> dict[str, Any]:
    """Finds the folder for a particular owner and returns its id.

    ================  ========================================================
    **Parameter**      **Description**
    ----------------  --------------------------------------------------------
    owner             required string, the name of the user
    ----------------  --------------------------------------------------------
    folder_name       required string, the name of the folder to search for
    ================  ========================================================

    :return:
        a boolean if succeeded.
    """
    if folder_name in [None, "/", "Root Folder"]:
        return None
    session: EsriSession = gis._con._session
    resp = session.post(
        url=f"{gis._portal.resturl}content/users/{owner}",
        data={
            "f": "json",
        },
    ).json()
    result = [
        f["id"]
        for f in resp.get("folders", [])
        if folder_name.lower() in [f["id"].lower(), f["title"].lower()]
    ]
    if len(result) > 0:
        return result[0]
    return None


# -------------------------------------------------------------------------
def _get_folder_name(
    gis: _arcgis_gis.GIS, owner: str, folder_id: str
) -> dict[str, Any]:
    """Finds the folder for a particular owner and returns its id.

    ================  ========================================================
    **Parameter**      **Description**
    ----------------  --------------------------------------------------------
    owner             required string, the name of the user
    ----------------  --------------------------------------------------------
    folder_name       required string, the name of the folder to search for
    ================  ========================================================

    :return:
        a boolean if succeeded.
    """
    if folder_id is None:
        return "Root Folder"
    session: EsriSession = gis._con._session
    resp = session.post(
        url=f"{gis._portal.resturl}content/users/{owner}",
        data={
            "f": "json",
        },
    )
    data: dict[str, Any] = resp.json()
    result = [
        f["title"]
        for f in data.get("folders", [])
        if folder_id.lower() in [f["id"].lower(), f["title"].lower()]
    ]
    if len(result) > 0:
        return result[0]
    return None


def _process_parameters(params: dict[str, Any]) -> dict:
    """handles the requests parameters"""
    for k, v in dict(params).items():
        if isinstance(v, (dict, list, bool, NoneType)):
            params[k] = json.dumps(v)
        else:
            params[k] = v
    return params
