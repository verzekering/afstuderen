from __future__ import annotations
import os
import json
import time
import uuid
import logging
import tempfile
import concurrent.futures
from arcgis.auth.tools import LazyLoader
from arcgis.auth import EsriSession
from typing import Any

from dataclasses import asdict
from typing import Any
import requests
from ._editdc import Attachments, VersionInfo

_arcgis_features = LazyLoader("arcgis.features")

_log = logging.getLogger()


def _status(
    session: EsriSession, result: dict[str, Any], job_url: str
) -> dict[str, Any]:
    """Checks the status of the apply edits call"""
    # handles case where job is put into pending status mode (this is rare)
    i: int = 1
    resp: requests.Response = session.get(
        url=job_url,
        params={
            "f": "json",
        },
    )
    resp.raise_for_status()
    result: dict[str, Any] = resp.json()
    while not result.get("status", "none").lower() in [
        "completed",
        "failed",
    ]:
        if result.get("status", "none").lower() == "none":
            return result  # null case, something went wrong.
        time.sleep(i)
        resp: requests.Response = session.get(
            url=job_url,
            params={
                "f": "json",
            },
        )
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        if i < 5:
            i += 1
    if "resultUrl" in result:
        # return the payload
        return session.get(
            url=result["resultUrl"],
            params={
                "f": "json",
            },
        ).json()
    return result


def apply_edits(
    fl: _arcgis_features.FeatureLayer,
    adds: list[dict[str, Any]] | None = None,
    updates: list[dict[str, Any]] | None = None,
    deletes: list[str] | list[int] | str | None = None,
    attachments: Attachments | None = None,
    use_global_ids: bool = False,
    version_info: VersionInfo | None = None,
    return_edit_moment: bool = False,
    rollback: bool = True,
    true_curve_client: bool = False,
    datum_transformation: dict[str, Any] | None = None,
    time_reference: bool = False,
    return_edit_results: bool = False,
) -> concurrent.futures.Future | dict[str, Any] | None:
    """
    Adds, updates, and deletes features to the
    associated :class:`~arcgis.features.FeatureLayer` or :class:`~arcgis.features.Table` in a single call.

    """
    session = fl._con._session
    if adds is None and deletes is None and updates is None and attachments is None:
        _log.warning(
            "You must supply at least one value for adds, deletes, updates or attachments."
        )
        return None
    if use_global_ids == False and attachments:
        _log.warning("Ignoring attachments because `user_global_ids` is False")

    edit_url: str = f"{fl._url}/applyEdits"
    params: dict[str, Any] = {
        "f": "json",
        "async": True,
        "useGlobalIds": use_global_ids,
        "returnEditMoment": return_edit_moment,
        "trueCurveClient": true_curve_client,
        "editsUploadFormat": "json",
    }
    if return_edit_results:
        params["returnEditResults"] = return_edit_results
    if time_reference:
        params["timeReferenceUnknownClient"] = time_reference
    if datum_transformation:
        params["datumTransformation"] = datum_transformation
    if (
        "supportsRollbackOnFailureParameter" in fl.properties
        and fl.properties["supportsRollbackOnFailureParameter"]
        and isinstance(rollback, bool)
    ):
        params["rollbackOnFailure"] = rollback
    else:
        _log.warn("Not applying the rollback on failure parameter.")
    if version_info:
        # version_info: dict[str, Any] = asdict(version_info)
        version: str = version_info.version
        session_id: str = version_info.session_id
        use_previous_edit_moment: bool = version_info.use_previous_edit_moment

        if (
            "isDataVersioned" in fl.properties
            and fl.properties["isDataVersioned"]
            and version
        ):
            params["gdbVersion"] = version
            if session_id:
                params["sessionID"] = session_id
            if use_previous_edit_moment in [True, False]:
                params["usePreviousEditMoment"] = use_previous_edit_moment
        elif not "isDataVersioned" in fl.properties or (
            (
                "isDataVersioned" in fl.properties
                and fl.properties["isDataVersioned"] == False
            )
            and version
        ):
            _log.warn("Layer is not versioned, ignoring the version_info parameter")
    if (
        "advancedEditingCapabilities" in fl.properties
        and fl.properties["advancedEditingCapabilities"]
        and "supportsApplyEditsbyUploadID"
        in fl.properties["advancedEditingCapabilities"]
        and fl.properties["advancedEditingCapabilities"]["supportsApplyEditsbyUploadID"]
    ):
        if isinstance(deletes, str):
            deletes = [
                int(d) if (isinstance(d, str) and d.isdigit()) else d
                for d in deletes.split(",")
            ]
        elif deletes is None:
            deletes = []

        data = {
            "adds": adds,
            "updates": updates,
            "deletes": deletes,
            "attachments": {
                "adds": [],
                "updates": [],
                "deletes": [],
            },
        }

        if use_global_ids and attachments:
            attachments: dict[str, Any] = asdict(attachments)
            data["attachments"] = attachments
        elif use_global_ids == False and attachments:
            _log.warning("Cannot add attachments without `user_global_ids` being True.")
        if attachments is None:
            data.pop("attachments", None)
        with tempfile.TemporaryDirectory() as folder:
            fp = os.path.join(folder, f"{uuid.uuid4().hex}.json")
            with open(fp, "w") as writer:
                writer.write(json.dumps(data))
            mgr = fl._upload_manager
            upload = mgr.upload(path=fp)
            itemid = upload.properties["itemID"]
            params["editsUploadId"] = itemid
            resp: requests.Response = session.post(url=edit_url, data=params)
            resp.raise_for_status()
    else:
        if adds:
            params["adds"] = adds
        if updates:
            params["updates"] = updates
        if deletes:
            params["deletes"] = deletes
        resp: requests.Response = session.post(url=edit_url, data=params)
        resp.raise_for_status()
    if resp is None:
        _log.error("Could not complete the call.")

    result: dict[str, Any] = resp.json()
    if "statusUrl" in result:
        status_url = result.get("statusUrl", None)
        if status_url is None:
            return result
        else:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                _status,
                **{
                    "session": session,
                    "result": result,
                    "job_url": status_url,
                },
            )
            executor.shutdown(wait=True)
            return future
    else:
        return result
    return resp.json()
