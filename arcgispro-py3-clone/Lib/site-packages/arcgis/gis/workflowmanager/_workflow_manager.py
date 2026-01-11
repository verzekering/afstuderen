from __future__ import annotations

import datetime
import functools
import json
import logging
import sys
import threading
import urllib.parse
from enum import Enum
from typing import Optional, Callable

logger = logging.getLogger(__name__)

import arcgis.gis
from arcgis.auth.tools import parse_url
from arcgis.geoprocessing._tool import _camelCase_to_underscore
from arcgis.gis._impl._con._websocket_connection import WebsocketConnection

logger = logging.getLogger(__name__)


def _underscore_to_camelcase(name):
    def camelcase():
        yield str.lower
        while True:
            yield str.capitalize

    c = camelcase()
    return "".join(next(c)(x) if x else "_" for x in name.split("_"))


def _check_license(gis):
    is_portal = gis.properties.get("isPortal", False)
    portal_version = float(gis.properties.get("currentVersion", "0"))
    if is_portal and portal_version < 10.3:  # < ArcGIS Enterprise 11.1
        user_url = f"{gis._portal.resturl}community/self"
        raw_user = gis._con.get(user_url, {"returnUserLicenseTypeExtensions": True})
        if "userLicenseTypeExtensions" in raw_user:
            licenses = raw_user["userLicenseTypeExtensions"]
            has_license = "workflow" in licenses
        else:
            has_license = False

        if has_license is False:
            raise ValueError(
                "No Workflow Manager license is available for the current user"
            )


def _initialize(instance, gis, is_admin=False):
    instance._gis = gis
    if not instance._gis.users.me:
        raise ValueError("An authenticated `GIS` is required.")

    info_result = instance._gis.properties
    instance.is_enterprise = info_result["isPortal"]

    if instance.is_enterprise:
        instance.org_id = "workflow"
        for s in instance._gis.servers.get("servers", []):
            server_functions = [
                x.strip() for x in s.get("serverFunction", "").lower().split(",")
            ]
            if "workflowmanager" not in server_functions:
                continue
            public_url = s.get("url")
            private_url = s.get("adminUrl")
            instance._server_url = _get_server_url(public_url, private_url, gis)

            if not instance._server_url:
                raise RuntimeError("Cannot find a WorkflowManager Server")

            instance._url = f"{instance._server_url}/{instance.org_id}"
            if not is_admin:
                instance._url = f"{instance._url}/{instance._item.id}"
            break

        if not instance._url:
            raise RuntimeError(
                "Unable to locate Workflow Manager Server. Please contact your ArcGIS Enterprise "
                "Administrator to ensure Workflow Manager Server is properly configured."
            )
    # is Arcgis Online
    else:
        instance.org_id = info_result["id"]
        helper_services = info_result.get("helperServices", {})
        instance._server_url = instance._url = helper_services.get(
            "workflowManager", {}
        ).get("url")
        if not instance._url:
            raise RuntimeError(f"Cannot get Workflow Manager url for {gis}")

        instance._url = f"{instance._url}/{instance.org_id}"
        if not is_admin:
            instance._url = f"{instance._url}/{instance._item.id}"

    if not instance._url:
        raise ValueError(f"WorkflowManager Not Registered on {gis}")
    logger.debug(f"Initializing Workflow Manager. Url = {instance._url}")


@functools.lru_cache(maxsize=255)
def _get_server_url(public_url: str, private_url: str, gis: arcgis.gis.GIS) -> str:
    if not gis._use_private_url_only and not gis._validate_item_url:
        return public_url

    if not private_url:
        return public_url

    parsed_private = parse_url(private_url)
    if parsed_private.port == 6443:
        private_url = (
            parsed_private
            # Port isn't part of the named tuple so can't be replaced directly
            ._replace(netloc=parsed_private.netloc.replace("6443", "13443"))
            ._replace(path="")
            .geturl()
        )

    if gis._use_private_url_only:
        return private_url

    for _url in [public_url, private_url]:
        try:
            if _url:
                logger.debug(f"Testing workflow connection to {_url}")
                gis._con.get(f"{_url}/workflow/checkStatus")
                return _url
        except:
            continue  # if status check fails, try the next url

    return public_url


class WorkflowManagerAdmin:
    """
    Represents a series of CRUD functions for Workflow Manager Items

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    gis                 Optional GIS. The connection to the Enterprise.
    ===============     ====================================================================
    """

    def __init__(self, gis):
        _initialize(self, gis, is_admin=True)
        _check_license(gis)

    def create_item(self, name: str) -> tuple:
        """
        Creates a `Workflow Manager` schema that stores all the configuration
        information and location data in the data store on Portal. This can
        be run by any user assigned to the administrator role in Portal.

        For users that do not belong to the administrator role, the
        following privileges are required to run Create Workflow Item:

        ==================  =========================================================
        **Parameter**        **Description**
        ------------------  ---------------------------------------------------------
        name                Required String. The name of the new schema.
        ==================  =========================================================

        :return:
            string (item_id)
        """

        url = "{base}/admin/createWorkflowItem?name={name}".format(
            base=self._url, name=name
        )
        params = {"name": name}
        return_obj = json.loads(
            self._gis._con.post(
                url, params=params, try_json=False, json_encode=False, post_json=True
            )
        )
        return_obj = return_obj["itemId"]
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj

    def upgrade_item(self, item):  # TODO TypeHint removed in order to avoid import
        """
        Upgrades an outdated Workflow Manager schema. Requires the Workflow Manager
        Advanced Administrator privilege or the Portal Admin Update Content privilege.

        ==================  =========================================================
        **Parameter**        **Description**
        ------------------  ---------------------------------------------------------
        item                Required Item. The Workflow Manager Item to be upgraded
        ==================  =========================================================

        :return:
            success object

        """

        url = "{base}/admin/{id}/upgrade".format(base=self._url, id=item.id)
        return_obj = json.loads(
            self._gis._con.post(url, try_json=False, json_encode=False, post_json=True)
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj

    def delete_item(self, item):  # TODO TypeHint removed in order to avoid import
        """
        Delete a Workflow Manager schema. Does not delete the Workflow Manager Admin group.
        Requires the administrator or publisher role. If the user has the publisher role,
        the user must also be the owner of the item to delete.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        id                  Required Item. The Workflow Manager Item to be deleted
        ===============     ====================================================================

        :return:
            success object

        """

        url = "{base}/admin/{id}?".format(base=self._url, id=item.id)

        return_obj = json.loads(self._gis._con.delete(url, try_json=False))
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    @property
    def server_status(self):
        """
        Gets the current status of the Workflow Manager Server

        :return:
            Boolean

        """

        url = "{base}/checkStatus".format(base=self._url)

        return_obj = self._gis._con.get(url)
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj

    @property
    def health_check(self):
        """
        Checks the health of Workflow Manager Server and if the cluster is active (if applicable).

        :return:
            Boolean

        """

        url = "{base}/healthCheck".format(base=self._url)

        return_obj = self._gis._con.get(url)
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj

    def export_item(
        self,
        item,  # TODO TypeHint removed in order to avoid import
        job_template_ids: Optional[str] = None,
        diagram_ids: Optional[str] = None,
        include_other_configs: bool = True,
        passphrase: Optional[str] = None,
    ):
        """
        Exports a new Workflow Manager configuration (.wmc) file based on the indicated item. This configuration file
        includes the version, job templates, diagrams, roles, role-group associations, lookup tables, charts and
        queries, templates, and user settings of the indicated item. This file can be used with the import endpoint
        to update other item configurations. Configurations from Workflow items with a server that is on a more
        recent version will not import due to incompatibility.

        =====================  =========================================================
        **Argument**           **Description**
        ---------------------  ---------------------------------------------------------
        item                   Required Item. The Workflow Manager Item to be exported
        ---------------------  ---------------------------------------------------------
        job_template_ids       Optional. The job template(s) to be exported. If job template is exported,
                               the associated diagram must be included to be exported.
        ---------------------  ---------------------------------------------------------
        diagram_ids            Optional. The diagram(s) to be exported. If not defined, all diagrams are exported.
                               If defined as empty, no diagram is exported
        ---------------------  ---------------------------------------------------------
        include_other_configs  Optional. If false other configurations are not exported including templates,
                               User defined settings, shared searches, shared queries, email settings etc.
        ---------------------  ---------------------------------------------------------
        passphrase             Optional. If exporting encrypted user defined settings, define a passphrase.
                               If no passphrase is specified, the keys for encrypted user defined settings will be
                               exported without their values.
        =====================  =========================================================

        :return:
            success object

        """
        params = {"includeOtherConfiguration": include_other_configs}
        if job_template_ids is not None:
            params["jobTemplateIds"] = job_template_ids
        if diagram_ids is not None:
            params["diagramIds"] = diagram_ids
        if passphrase is not None:
            params["passphrase"] = passphrase

        url = "{base}/admin/{id}/export".format(base=self._url, id=item.id)
        return_obj = self._gis._con.post(
            url, params=params, try_json=False, json_encode=False, post_json=True
        )

        if "error" in return_obj:
            return_obj = json.loads(return_obj)
            self._gis._con._handle_json_error(return_obj["error"], 0)
        return return_obj

    def import_item(
        self, item, config_file, passphrase: Optional[str] = None
    ):  # TODO TypeHint removed in order to avoid import
        """
        Imports a new Workflow Manager configuration from the selected .wmc file. Configurations from Workflow
        items with a server that is on a more recent version will not import due to incompatibility. This will
        completely replace the version, job templates, diagrams, roles, role-group associations, lookup tables,
        charts and queries, templates, and user settings of the indicated item, and it is recommended to back
        up configurations before importing. Any encrypted settings included will only have their key imported
        and will need the value updated. Importing will fail if any jobs exist in the destination item.
        Excess scheduled tasks will be dropped based on the portal limit.

        ==================  =========================================================
        **Argument**        **Description**
        ------------------  ---------------------------------------------------------
        item                Required Item. The Workflow Manager Item that to import the configuration to.
        ------------------  ---------------------------------------------------------
        config_file         Required. The file path to the workflow manager configuration file.
        ------------------  ---------------------------------------------------------
        passphrase          Optional. If importing encrypted user defined settings, specify the same passphrase
                            used when exporting the configuration file. If no passphrase is specified, the keys for
                            encrypted user defined settings will be imported without their values.
        ==================  =========================================================

        :return:
            success object

        """

        url = "{base}/admin/{id}/import".format(base=self._url, id=item.id)
        data = {}
        if passphrase is not None:
            data["passphrase"] = passphrase

        return_obj = self._gis._con.post(
            url,
            files={"file": config_file},
            params=data,
            try_json=False,
            json_encode=False,
            post_json=False,
        )
        return_obj = json.loads(return_obj)

        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj


class JobManager:
    """
    Represents a helper class for workflow manager jobs. Accessible as the
    :attr:`~arcgis.gis.workflowmanager.WorkflowManager.jobs` property of the
    :class:`~arcgis.gis.workflowmanager.WorkflowManager`.

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    item                The Workflow Manager Item
    ---------------     --------------------------------------------------------------------
    workflow_manager    The :class:`~arcgis.gis.workflowmanager.WorkflowManager` object
    ===============     ====================================================================

    """

    def __init__(self, item, workflow_manager):
        """initializer"""
        if item is None:
            raise ValueError("Item cannot be None")
        self._workflow_manager = workflow_manager
        self._item = item
        self._gis = self._item._gis
        _initialize(self, self._item._gis)

    def _handle_error(self, info):
        """Basic error handler - separated into a function to allow for expansion in future releases"""
        error_class = info[0]
        error_text = info[1]
        raise Exception(error_text)

    def close(self, job_ids: list):
        """
        Closes a single or multiple jobs with specific Job IDs

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        job_ids             Required list of job ID strings
        ===============     ====================================================================

        :return:
            success object

        """
        try:
            url = "{base}/jobs/manage".format(base=self._url)
            return Job.manage_jobs(self, self._gis, url, job_ids, "Close")
        except:
            self._handle_error(sys.exc_info())

    def reopen(self, job_ids):
        """
        Reopens a single or multiple jobs with specific Job IDs

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        job_ids             Required list of job ID strings
        ===============     ====================================================================

        :return:
            success object

        """
        try:
            url = "{base}/jobs/manage".format(base=self._url)
            return Job.manage_jobs(self, self._gis, url, job_ids, "Reopen")
        except:
            self._handle_error(sys.exc_info())

    def create(
        self,
        template: str,
        count: int = 1,
        name: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        priority: Optional[str] = None,
        description: Optional[str] = None,
        owner: Optional[str] = None,
        group: Optional[str] = None,
        assigned: Optional[str] = None,
        complete: Optional[str] = None,
        notes: Optional[str] = None,
        parent: Optional[str] = None,
        location: Optional = None,  # TODO TypeHint removed in order to avoid import
        extended_properties: Optional[dict] = None,
        related_properties: Optional[dict] = None,
        job_id: Optional[str] = None,
    ):
        """
        Adds a job to the Workflow Manager instance given a user-defined template

        ===================         ====================================================================
        **Parameter**                **Description**
        -------------------         --------------------------------------------------------------------
        template                    Required object. Workflow Manager Job Template ID
        -------------------         --------------------------------------------------------------------
        count                       Optional Integer Number of jobs to create
        -------------------         --------------------------------------------------------------------
        name                        Optional string. Job Name
        -------------------         --------------------------------------------------------------------
        start                       Optional string. Job Start Date
        -------------------         --------------------------------------------------------------------
        end                         Optional string. Job End Date
        -------------------         --------------------------------------------------------------------
        priority                    Optional string. Job Priority Level
        -------------------         --------------------------------------------------------------------
        description                 Optional string. Job Description
        -------------------         --------------------------------------------------------------------
        owner                       Optional string. Job Owner
        -------------------         --------------------------------------------------------------------
        group                       Optional string. Job Assignment Group. The Assignment type of the job to be
                                    created. Type of assignment designated Values: "User" | "Group" | "Unassigned"
        -------------------         --------------------------------------------------------------------
        assigned                    Optional string. Initial Job Assignee
        -------------------         --------------------------------------------------------------------
        complete                    Optional Integer Percentage Complete
        -------------------         --------------------------------------------------------------------
        notes                       Optional string. Job Notes
        -------------------         --------------------------------------------------------------------
        parent                      Optional string Parent Job
        -------------------         --------------------------------------------------------------------
        location                    Optional Geometry or Workflow Manager :class:`~arcgis.gis.workflowmanager.JobLocation`
                                    Define an area of location for your job.
        -------------------         --------------------------------------------------------------------
        extended_properties         Optional Dict. Define additional properties on a job template
                                    specific to your business needs.
        -------------------         --------------------------------------------------------------------
        related_properties          Optional Dict. Define additional 1-M properties on a job template
                                    specific to your business needs.
        -------------------         --------------------------------------------------------------------
        job_id                      Optional string. Define the unique jobId of the job to be created.
                                    Once defined, only one job can be created.
        ===================         ====================================================================

        :return:
            List of newly created job ids

        """
        location_obj = location
        if location is not None and type(location) is not dict:
            location_obj = {"geometryType": location.type}
            if location.type == "Polygon":
                location_obj["geometry"] = json.dumps(
                    {
                        "rings": location.rings,
                        "spatialReference": location.spatial_reference,
                    }
                )
            elif location.type == "Polyline":
                location_obj["geometry"] = json.dumps(
                    {
                        "paths": location.paths,
                        "spatialReference": location.spatial_reference,
                    }
                )
            elif location.type == "Multipoint":
                location_obj["geometry"] = json.dumps(
                    {
                        "points": location.points,
                        "spatialReference": location.spatial_reference,
                    }
                )
        job_object = {
            "numberOfJobs": count,
            "jobName": name,
            "startDate": start,
            "dueDate": end,
            "priority": priority,
            "description": description,
            "ownedBy": owner,
            "assignedType": group,
            "assignedTo": assigned,
            "percentComplete": complete,
            "notes": notes,
            "parentJob": parent,
            "location": location_obj,
            "extendedProperties": extended_properties,
            "relatedProperties": related_properties,
            "jobId": job_id,
        }
        filtered_object = {}
        for key in job_object:
            if job_object[key] is not None:
                filtered_object[key] = job_object[key]
        url = "{base}/jobTemplates/{template}/job".format(
            base=self._url, template=template
        )
        return_obj = json.loads(
            self._gis._con.post(
                url,
                filtered_object,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj["jobIds"]

    def delete_attachment(self, job_id: str, attachment_id: str):
        """
        Deletes a job attachment given a job ID and attachment ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        job_id              Required string. Job ID
        ---------------     --------------------------------------------------------------------
        attachment_id       Required string. Attachment ID
        ===============     ====================================================================

        :return:
            status code

        """
        try:
            res = Job.delete_attachment(
                self,
                self._gis,
                "{base}/jobs/{jobId}/attachments/{attachmentId}".format(
                    base=self._url,
                    jobId=job_id,
                    attachmentId=attachment_id,
                    item=self._item.id,
                ),
            )
            return res
        except:
            self._handle_error(sys.exc_info())

    def diagram(self, id: str):
        """
        Returns the job diagram for the user-defined job

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        id                  Required string. Job ID
        ===============     ====================================================================

        :return:
            Workflow Manager :class:`Job Diagram <arcgis.gis.workflowmanager.JobDiagram>` object

        """
        try:
            return JobDiagram.get(
                self,
                self._gis,
                "{base}/jobs/{job}/diagram".format(base=self._url, job=id),
                {},
            )
        except:
            self._handle_error(sys.exc_info())

    def get(self, id: str, get_ext_props: bool = True, get_holds: bool = True):
        """
        Returns an active job with the given ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        id                  Required string. Job ID
        ---------------     --------------------------------------------------------------------
        get_ext_props       Optional Boolean. If set to false the object will not include the jobs extended properties.
        ---------------     --------------------------------------------------------------------
        get_holds           Optional Boolean. If set to false the object will not include the jobs holds.
        ===============     ====================================================================

        :return:
            Workflow Manager :class:`Job <arcgis.gis.workflowmanager.Job>` Object

        """
        try:
            url = f"{self._url}/jobs/{id}"
            job_dict = self._gis._con.get(
                url, {"extProps": get_ext_props, "holds": get_holds}
            )
            return Job(job_dict, self._gis, self._url, self._workflow_manager)
        except:
            self._handle_error(sys.exc_info())

    def search(
        self,
        query: Optional[str] = None,
        search_string: Optional[str] = None,
        fields: Optional[str] = None,
        display_names: Optional[str] = [],
        sort_by: Optional[str] = [],
        num: int = 10,
        start_num: int = 0,
    ):
        """
        Runs a search against the jobs stored inside the Workflow Manager instance

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        query               Required string. SQL query to search against (e.g. "priority='High'")
        ---------------     --------------------------------------------------------------------
        search_str          Optional string. Search string to search against (e.g. "High")
        ---------------     --------------------------------------------------------------------
        fields              Optional string. Field list to return
        ---------------     --------------------------------------------------------------------
        display_names       Optional string. Display names for the return fields
        ---------------     --------------------------------------------------------------------
        sort_by             Optional string. Field to sort by (e.g. {'field': 'priority', 'sortOrder': 'Asc'})
        ---------------     --------------------------------------------------------------------
        num                 Optional Integer. Number of return results
        ---------------     --------------------------------------------------------------------
        start_num           Optional string. Index of first return value
        ===============     ====================================================================

        :return:
            `List <https://docs.python.org/3/library/stdtypes.html#list>`_ of search results

        """
        try:
            search_object = {
                "q": query,
                "search": search_string,
                "num": num,
                "displayNames": display_names,
                "start": start_num,
                "sortFields": sort_by,
                "fields": fields,
            }
            url = "{base}/jobs/search".format(base=self._url)
            return Job.search(self, self._gis, url, search_object)
        except:
            self._handle_error(sys.exc_info())

    def statistics(
        self,
        query: Optional[str] = None,
        search_str: Optional[str] = None,
        group_by: Optional[str] = None,
        spatial_extent: Optional[str] = None,
        has_location: Optional[bool] = None,
    ):
        """
        Runs a search against the jobs stored inside the Workflow Manager instance

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        query               Optional string. The SQL query for the search you want total number of records for.
                            (e.g. "priority='High'") Must specify either query or search_str as a parameter.
        ---------------     --------------------------------------------------------------------
        search_str          Optional string. The match criteria for a simple search. (e.g. "High")
                            Must specify either search_str or query as a parameter.
        ---------------     --------------------------------------------------------------------
        group_by            Optional string. The search field that is used to separate counts by value.
        ---------------     --------------------------------------------------------------------
        spatial_extent      Optional string. Spatial extent string to filter jobs by their locations
        ---------------     --------------------------------------------------------------------
        has_location        Optional boolean. If set to true jobs with defined location in jobLocation are returned
        ===============     ====================================================================

        :return:
            An object representing Workflow Manager job statistics


        .. code-block:: python

            # USAGE EXAMPLE

            # create a Workflow Manager object from the workflow item
            workflow_manager = WorkflowManager(wf_item)

            user_query = "diagramId='99o2QTePTqq-BHRHK_Aeag' "
            workflow_manager.jobs.statistics(query=user_query, group_by="assignedTo")


            # Example returned Job Statistics Object:

            {
              "total": 2,
              "groupBy": "assignedTo",
              "groupedValues": [ { "value": "assignedTo", count": 2 } ]
            }

        """
        try:
            search_object = {}

            if query is not None:
                search_object["q"] = query
            if search_str is not None:
                search_object["search"] = search_str
            if group_by is not None:
                search_object["groupBy"] = group_by
            if spatial_extent is not None:
                search_object["spatialExtent"] = spatial_extent
            if has_location is not None:
                search_object["hasLocation"] = has_location

            url = "{base}/jobs/statistics".format(base=self._url)
            return Job.search(self, self._gis, url, search_object)
        except:
            self._handle_error(sys.exc_info())

    def update(
        self,
        job_id: str,
        update_object: dict,
        allow_running_step_id: Optional[str] = None,
    ):
        """
        Updates a job object by ID

        =====================       ====================================================================
        **Parameter**               **Description**
        ---------------------       --------------------------------------------------------------------
        job_id                      Required string. ID for the job to update
        ---------------------       --------------------------------------------------------------------
        update_object               Required dictionary. A dictionary containing the fields and new
                                    values to add to the job.
        ---------------------       --------------------------------------------------------------------
        allow_running_step_id       Optional string. Allow updating job properties when the specified
                                    step is running
        =====================       ====================================================================

        :return:
            success object


        .. code-block:: python

            # USAGE EXAMPLE: Updating a Job's properties

            # create a WorkflowManager object from the workflow item
            workflow_manager = WorkflowManager(wf_item)

            updates = { 'priority': 'High' }
            updates['extended_properties']: [
                {
                    "identifier": "table_name.prop1",
                    "value": "updated_123"
                },
                {
                    "identifier": "table_name.prop2",
                    "value": "updated_456"
                },
            ]

            workflow_manager.jobs.update(job_id, updates, 'stepid123')

        """
        try:
            current_job = self.get(job_id).__dict__
            for k in update_object.keys():
                current_job[k] = update_object[k]
            if allow_running_step_id is not None:
                current_job["allowRunningStepId"] = allow_running_step_id
            url = "{base}/jobs/{jobId}/update".format(base=self._url, jobId=job_id)
            new_job = Job(current_job, self._gis, url)
            # remove existing properties if not updating.
            if "extended_properties" not in update_object:
                new_job.extended_properties = None
            if "related_properties" not in update_object:
                new_job.related_properties = None

            # temporary fix for error in privileges
            delattr(new_job, "percent_complete")
            delattr(new_job, "parent_job")
            return new_job.post()
        except:
            self._handle_error(sys.exc_info())

    def upgrade(self, job_ids: list):
        """
        Upgrades a single or multiple jobs with specific JobIDs

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        job_ids             Required list. A list of job ID strings
        ===============     ====================================================================

        :return:
          success object

        """
        try:
            url = "{base}/jobs/manage".format(base=self._url)
            return Job.manage_jobs(self, self._gis, url, job_ids, "Upgrade")
        except:
            self._handle_error(sys.exc_info())

    def set_job_location(self, job_id, geometry):
        """
        Set a location of work for an existing job. jobUpdateLocation privilege is required to set a location on a job.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        job_id              Required string. ID for the job to update
        ---------------     --------------------------------------------------------------------
        geometry            Required ArcGIS.Geometry.Geometry or Workflow Manager :class:`~arcgis.gis.workflowmanager.JobLocation`
                            that describes a Job's Location. Must be a Polygon, Polyline, or Multipoint geometry type
        ===============     ====================================================================

        :return:
            success object

        """
        try:
            url = "{base}/jobs/{jobId}/location".format(
                base=self._url, jobId=job_id, item=self._item
            )
            if type(geometry) is dict:
                location = geometry
            else:
                location = {"geometryType": geometry.type}
                if geometry.type == "Polygon":
                    location["geometry"] = json.dumps(
                        {
                            "rings": geometry.rings,
                            "spatialReference": geometry.spatial_reference,
                        }
                    )
                elif geometry.type == "Polyline":
                    location["geometry"] = json.dumps(
                        {
                            "paths": geometry.paths,
                            "spatialReference": geometry.spatial_reference,
                        }
                    )
                elif geometry.type == "Multipoint":
                    location["geometry"] = json.dumps(
                        {
                            "points": geometry.points,
                            "spatialReference": geometry.spatial_reference,
                        }
                    )

            return_obj = json.loads(
                self._gis._con.put(
                    url,
                    {"location": location},
                    post_json=True,
                    try_json=False,
                    json_encode=False,
                )
            )
            if "error" in return_obj:
                self._gis._con._handle_json_error(return_obj["error"], 0)
            elif "success" in return_obj:
                return return_obj["success"]
            return_obj = {
                _camelCase_to_underscore(k): v
                for k, v in return_obj.items()
                if v is not None and not k.startswith("_")
            }
            return return_obj
        except:
            self._handle_error(sys.exc_info())

    def delete(self, job_ids: list):
        """
        Deletes a single or multiple jobs with specific JobIDs

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        job_ids             Required list. A list of job ID strings
        ===============     ====================================================================

        :return:
            success object

        """
        try:
            url = "{base}/jobs/manage".format(base=self._url)
            return Job.manage_jobs(self, self._gis, url, job_ids, "Delete")
        except:
            self._handle_error(sys.exc_info())


class WorkflowManager:
    """
    Represents a connection to a Workflow Manager instance or item.

    Users create, update, delete workflow diagrams, job templates and jobs
    or the various other properties with a workflow item.

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    item                Required string. The Workflow Manager Item
    ===============     ====================================================================

    .. code-block:: python

        # USAGE EXAMPLE: Creating a WorkflowManager object from a workflow item

        from arcgis.gis.workflowmanager import WorkflowManager
        from arcgis.gis import GIS

        # connect to your GIS and get the web map item
        gis = GIS(url, username, password)
        wf_item = gis.content.get('1234abcd_workflow item id')

        # create a WorkflowManager object from the workflow item
        wm = WorkflowManager(wf_item)
        type(wm)
        >> arcgis.gis.workflowmanager.WorkflowManager

        # explore the users in this workflow using the 'users' property
        wm.users
        >> [{}...{}]  # returns a list of dictionaries representing each user
    """

    _nm: NotificationManager = None

    def __init__(self, item):
        if item is None:
            raise ValueError("Item cannot be None")
        self._item = item
        _initialize(self, item._gis)
        _check_license(item._gis)

        self.job_manager = JobManager(item, self)
        self.saved_searches_manager = SavedSearchesManager(item)

    def _handle_error(self, info):
        """Basic error handler - separated into a function to allow for expansion in future releases"""
        error_class = info[0]
        error_text = info[1]
        raise Exception(error_text)

    @property
    def jobs(self):
        """
        The job manager for a workflow item.

        :return:
            :class:`~arcgis.gis.workflowmanager.JobManager` object

        """

        return self.job_manager

    @property
    def _notification_manager(self):
        if not self._nm:
            self._nm = NotificationManager(self._item, self)

        return self._nm

    def evaluate_arcade(
        self,
        expression: str,
        context: Optional[str] = None,
        context_type: str = "BaseContext",
        mode: str = "Standard",
    ):
        """
        Evaluates an arcade expression

        ======================  ===============================================================
        **Parameter**            **Description**
        ----------------------  ---------------------------------------------------------------
        expression              Required String.
        ----------------------  ---------------------------------------------------------------
        context                 Optional String.
        ----------------------  ---------------------------------------------------------------
        context_type            Optional String.
        ----------------------  ---------------------------------------------------------------
        mode                    Optional String.
        ======================  ===============================================================

        :return: String
        """
        url = f"{self._url}/evaluateArcade"
        params = {
            "expression": expression,
            "contextType": context_type,
            "context": context,
            "parseMode": mode,
        }
        res = self._gis._con.post(url, params=params, json_encode=False, post_json=True)
        return res.get("result", None)

    @property
    def wm_roles(self):
        """
        Returns a list of user :class:`roles <arcgis.gis.workflowmanager.WMRole>` available
        in the local Workflow Manager instance.

        :return: List
        """
        try:
            role_array = self._gis._con.get(
                "{base}/community/roles".format(base=self._url)
            )["roles"]
            return_array = [WMRole(r) for r in role_array]
            return return_array
        except:
            self._handle_error(sys.exc_info())

    @property
    def users(self):
        """
        Returns an list of all user profiles stored in Workflow Manager

        :return: List of :attr:`~arcgis.gis.workflowmanager.WorkflowManager.user` profiles
        """
        try:
            user_array = self._gis._con.get(
                "{base}/community/users".format(base=self._url)
            )["users"]
            return_array = [self.user(u["username"]) for u in user_array]
            return return_array
        except:
            self._handle_error(sys.exc_info())

    @property
    def assignable_users(self):
        """
        Get all assignable users for a user in the workflow system

        :return:
            A `list <https://docs.python.org/3/library/stdtypes.html#list>`_ of the assignable :attr:`~assarcgis.gis.workflowmanager.WorkflowManager.user` objects

        """
        try:
            user_array = self._gis._con.get(
                "{base}/community/users".format(base=self._url)
            )["users"]
            return_array = [
                self.user(u["username"]) for u in user_array if u["isAssignable"]
            ]
            return return_array
        except:
            self._handle_error(sys.exc_info())

    @property
    def assignable_groups(self):
        """
        Get portal groups associated with Workflow Manager roles, to which the current user
        can assign work based on their Workflow Manager assignment privileges.

        :return:
            A `list <https://docs.python.org/3/library/stdtypes.html#list>`_ of
            the assignable :class:`~arcgis.gis.workflowmanager.Group` objects

        """
        try:
            group_array = self._gis._con.get(
                "{base}/community/groups".format(base=self._url)
            )["groups"]
            return_array = [
                self.group(g["id"]) for g in group_array if g["isAssignable"]
            ]
            return return_array
        except:
            self._handle_error(sys.exc_info())

    @property
    def settings(self):
        """
        Returns a list of all settings for the Workflow Manager instance

        :return:
            `List <https://docs.python.org/3/library/stdtypes.html#list>`_

        """
        try:
            return self._gis._con.get("{base}/settings".format(base=self._url))[
                "settings"
            ]
        except:
            self._handle_error(sys.exc_info())

    @property
    def groups(self):
        """
        Returns an list of all user :class:`groups <arcgis.gis.workflowmanager.Group>`
        stored in Workflow Manager

        :return:
            `List <https://docs.python.org/3/library/stdtypes.html#list>`_

        """
        try:
            group_array = self._gis._con.get(
                "{base}/community/groups".format(base=self._url)
            )["groups"]
            return_array = [self.group(g["id"]) for g in group_array]
            return return_array
        except:
            self._handle_error(sys.exc_info())

    def searches(self, search_type: Optional[str] = None):
        """
        Returns a list of all saved searches.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        search_type         Optional string. The search type for returned saved searches.
                            The accepted values are `Standard`, `Chart`, and `All`. If not
                            defined, the Standard searches are returned.
        ===============     ====================================================================

        :return:
            `List <https://docs.python.org/3/library/stdtypes.html#list>`_

        """
        params = {}
        if search_type is not None:
            params["searchType"] = search_type

        try:
            return self._gis._con.get(
                "{base}/searches".format(base=self._url), params=params
            )["searches"]
        except:
            self._handle_error(sys.exc_info())

    @property
    def job_templates(self):
        """
        Gets all the job templates in a workflow item.

        :return:
            List of all current :class:`job templates <arcgis.gis.workflowmanager.JobTemplate>`
            in the Workflow Manager (required information for create_job call).

        """
        try:
            template_array = self._gis._con.get(
                "{base}/jobTemplates".format(base=self._url)
            )["jobTemplates"]
            return_array = [
                JobTemplate(t, self._gis, self._url) for t in template_array
            ]
            return return_array
        except:
            self._handle_error(sys.exc_info())

    @property
    def diagrams(self):
        """
        Gets the workflow diagrams within the workflow item.

        :return:
            `List <https://docs.python.org/3/library/stdtypes.html#list>`_ of all current
            :class:`diagrams <arcgis.gis.workflowmanager.JobDiagram>` in the Workflow Manager

        """
        try:
            diagram_array = self._gis._con.get(
                "{base}/diagrams".format(base=self._url)
            )["diagrams"]
            return_array = [JobDiagram(d, self._gis, self._url) for d in diagram_array]
            return return_array
        except:
            self._handle_error(sys.exc_info())

    def update_settings(self, props: list):
        """
        Returns an active job with the given ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        props               Required list. A list of Props objects to update
                            (Prop object example: {'propName': 'string', 'value': 'string'})
        ===============     ====================================================================

        :return:
            success object

        """
        url = "{base}/settings".format(base=self._url)
        params = {"settings": props}
        return_obj = json.loads(
            self._gis._con.post(
                url,
                params,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj

    def wm_role(self, name: str):
        """
        Returns an active role with the given name

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        name                Required string. Role Name
        ===============     ====================================================================

        :return:
            Workflow Manager :class:`Role <arcgis.gis.workflowmanager.WMRole>` Object

        """
        try:
            return WMRole.get(
                self,
                self._gis,
                "{base}/community/roles/{role}".format(
                    base=self._url, role=urllib.parse.quote(name), item=self._item.id
                ),
                params={},
            )
        except:
            self._handle_error(sys.exc_info())

    def delete_wm_role(self, name: str):
        """
        Returns boolean indicating whether or not the role was deleted.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        name                Required string. Role Name
        ===============     ====================================================================

        :return:
            Boolean

        """
        try:
            url = "{base}/community/roles/{role}".format(
                base=self._url, role=urllib.parse.quote(name), item=self._item.id
            )
            return_obj = json.loads(self._gis._con.delete(url, try_json=False))
            if "error" in return_obj:
                self._gis._con._handle_json_error(return_obj["error"], 0)
            elif "success" in return_obj:
                return return_obj["success"]
            elif "found" in return_obj:
                return return_obj["found"]
            return_obj = {
                _camelCase_to_underscore(k): v
                for k, v in return_obj.items()
                if v is not None and not k.startswith("_")
            }
            return return_obj
        except:
            self._handle_error(sys.exc_info())

    def job_template(self, id: str):
        """
        Returns a job template with the given ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        id                  Required string. Job Template ID
        ===============     ====================================================================

        :return:
            Workflow Manager :class:`JobTemplate <arcgis.gis.workflowmanager.JobTemplate>` Object

        """
        try:
            return JobTemplate.get(
                self,
                self._gis,
                "{base}/jobTemplates/{jobTemplate}".format(
                    base=self._url, jobTemplate=id
                ),
                params={},
            )
        except:
            self._handle_error(sys.exc_info())

    def delete_job_template(self, id: str):
        """
        Deletes a job template with the given ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        id                  Required string. Job Template ID
        ===============     ====================================================================

        :return:
            status code

        """
        try:
            res = JobTemplate.delete(
                self,
                self._gis,
                "{base}/jobTemplates/{jobTemplate}".format(
                    base=self._url, jobTemplate=id, item=self._item.id
                ),
            )
            return res
        except:
            self._handle_error(sys.exc_info())

    def user(self, username: str):
        """
        Returns a user profile with the given username

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        username            Required string. Workflow Manager Username
        ===============     ====================================================================

        :return:
            Workflow Manager user profile

        """
        try:
            return arcgis.gis.User(self._gis, username)
        except:
            self._handle_error(sys.exc_info())

    def group(self, group_id: str):
        """
        Returns group information with the given group ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        group_id            Required string. Workflow Manager Group ID
        ===============     ====================================================================

        :return:
            Workflow Manager :class:`~arcgis.gis.workflowmanager.Group` Object

        """
        try:
            wmx_group = Group.get(
                self,
                self._gis,
                "{base}/community/groups/{groupid}".format(
                    base=self._url, groupid=group_id, item=self._item.id
                ),
                params={},
            )
            arcgis_group = arcgis.gis.Group(self._gis, group_id)
            arcgis_group.roles = wmx_group.roles
            return arcgis_group
        except:
            self._handle_error(sys.exc_info())

    def update_group(self, group_id: str, update_object):
        """
        Update the information to the portal group. The adminAdvanced privilege is required.
        New roles can be added to the portal group. Existing roles can be deleted from the portal group.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        group_id            Required string. :class:`Workflow Manager Group <arcgis.gis.workflowmanager.Group>` ID
        ---------------     --------------------------------------------------------------------
        update_object       Required object. Object containing the updated actions of the information to be taken to the portal group.
        ===============     ====================================================================

        :return:
            Boolean

        """
        url = "{base}/community/groups/{groupid}".format(
            base=self._url, groupid=group_id
        )

        return_obj = json.loads(
            self._gis._con.post(
                url,
                update_object,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )

        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]

        return return_obj

    def diagram(self, id: str):
        """
        Returns the :class:`diagram <arcgis.gis.workflowmanager.JobDiagram>` with the given ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        id                  Required string. Diagram ID
        ===============     ====================================================================

        :return:
             Workflow Manager :class:`~arcgis.gis.workflowmanager.JobDiagram` Object

        """
        try:
            return JobDiagram.get(
                self,
                self._gis,
                "{base}/diagrams/{diagram}".format(base=self._url, diagram=id),
                params={},
            )
        except:
            self._handle_error(sys.exc_info())

    def diagram_version(self, diagram_id: str, version_id: str):
        """
        Returns the :class:`diagram <arcgis.gis.workflowmanager.JobDiagram>` with the given version ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        diagram_id          Required string. Diagram ID
        ---------------     --------------------------------------------------------------------
        version_id          Required string. Diagram Version ID
        ===============     ====================================================================

        :return:
             Specified version of the Workflow Manager :class:`~arcgis.gis.workflowmanager.JobDiagram` object

        """
        try:
            return JobDiagram.get(
                self,
                self._gis,
                "{base}/diagrams/{diagram}/{diagramVersion}".format(
                    base=self._url, diagram=diagram_id, diagramVersion=version_id
                ),
                params={},
            )
        except:
            self._handle_error(sys.exc_info())

    def diagram_upgraded_version(self, diagram_id: str, version_id: str):
        """
        Get an upgraded version of a workflow diagram that uses centralized data references. If the version number does
        not exist, an error saying the specific diagram version does not exist is returned. The adminBasic or
        adminAdvanced privilege is required to get an upgraded diagram.

        Note: You can upgrade a diagram by placing the transformedDiagram dictionary in the diagram
        parameter of update_diagram.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        diagram_id          Required string. Diagram ID
        ---------------     --------------------------------------------------------------------
        version_id          Required string. Diagram Version ID
        ===============     ====================================================================

        :return:
             Success Object

        .. code-block:: python

            # USAGE EXAMPLE: Using the transformedDiagram from the result object to update a diagram.

            # create a WorkflowManager object from the workflow item
            wm = WorkflowManager(wf_item)

            upgrade_obj = wm.diagram_upgraded_version("gb1GBilqT4yk68Hfs5ghxw", diagram_version=1)

            # update diagram draft
            wm.update_diagram( body=upgrade_obj['transformedDiagram'] )

        .. code-block:: python

            # Success Object Example:
            {
                "transformedDiagram": {
                    "diagramId": "gb1GBilqT4yk68Hfs5ghxw",
                    "diagramVersion": 1,
                    "diagramName": "Test New Diagram123 2024_12_13_11_59_54_764959",
                    "description": "Test Description",
                    "initialStepId": "1640baf9-f934-fd12-2b62-af6bfc2d0e87",
                    "initialStepName": "Start/End",
                    "steps": [
                        {
                            "id": "1640baf9-f934-fd12-2b62-af6bfc2d0e87",
                            "name": "Start/End",
                            "description": "Start and end of a workflow",
                            "stepTemplateId": "AVw8d6MdyiKjHtuS9dJ6",
                            "automatic": false,
                            "proceedNext": true,
                            "canSkip": false,
                            "position": "0,0,100,50",
                            "shape": 3,
                            "color": "130, 202, 237",
                            "outlineColor": "130, 202, 237",
                            "labelColor": "black",
                            "action": { "actionType": "Manual" },
                            "paths": [
                                {
                                    "nextStep": "21bff5ee-1586-a635-30ea-86769f01ac93",
                                    "points": [ { "x": 0, "y": 26 }, { "x": 0,  "y": 74 } ],
                                    "ports": [  "BOTTOM", "TOP" ],
                                    "assignedType": "Unassigned",
                                    "notifications": [],
                                    "lineColor": "black"
                                }
                            ],
                            "helpUrl": "Start/End help url",
                            "helpText": "Start/End help text"
                        }
                    ],
                    "centralizedDataReferences": [],
                    "displayGrid": true,
                    "useCentralizedDataReferences": true
                },
                "modifiedStepIds": [],
                "failedStepIds": [],
                "modifiedDataSourceNames": [],
                "failedDataSourceNames": []
            }

        """
        try:
            return self._gis._con.get(
                f"{self._url}/diagrams/{diagram_id}/{version_id}/upgraded"
            )
        except:
            self._handle_error(sys.exc_info())

    def create_wm_role(self, name, description="", privileges=[]):
        """
        Adds a role to the Workflow Manager instance given a user-defined name

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        name                Required string. Role Name (required)
        ---------------     --------------------------------------------------------------------
        description         Required string. Role Description
        ---------------     --------------------------------------------------------------------
        privileges          Required list. List of privileges associated with the role
        ===============     ====================================================================

        :return:
            Workflow Manager :class:`~arcgis.gis.workflowmanager.WMRole` Object

        """
        try:
            url = "{base}/community/roles/{name}".format(base=self._url, name=name)
            post_role = WMRole(
                {"roleName": name, "description": description, "privileges": privileges}
            )
            return post_role.post(self._gis, url)
        except:
            self._handle_error(sys.exc_info())

    def create_job_template(
        self,
        name: str,
        priority: str,
        id: str = None,
        category: str = "",
        job_duration: int = 0,
        assigned_to: str = "",
        default_due_date: Optional[str] = None,
        default_start_date: Optional[str] = None,
        start_date_type: str = "CreationDate",
        diagram_id: str = "",
        diagram_name: str = "",
        assigned_type: str = "Unassigned",
        description: str = "",
        default_description: str = "",
        state: str = "Draft",
        last_updated_by: str = "",
        last_updated_date: Optional[str] = None,
        extended_property_table_definitions: list = [],
    ):
        """
        Adds a job template to the Workflow Manager instance given a user-defined name and default priority level

        ====================================     ====================================================================
        **Parameter**                             **Description**
        ------------------------------------     --------------------------------------------------------------------
        name                                     Required string. Job Template Name
        ------------------------------------     --------------------------------------------------------------------
        priority                                 Required string. Default Job Template Priority Level
        ------------------------------------     --------------------------------------------------------------------
        id                                       Optional string. Job Template ID
        ------------------------------------     --------------------------------------------------------------------
        category                                 Optional string. Job Template Category
        ------------------------------------     --------------------------------------------------------------------
        job_duration                             Optional int. Default Job Template Duration
        ------------------------------------     --------------------------------------------------------------------
        assigned_to                              Optional string. Job Owner
        ------------------------------------     --------------------------------------------------------------------
        default_due_date                         Optional string. Due Date for Job Template
        ------------------------------------     --------------------------------------------------------------------
        default_start_date                       Optional string. Start Date for Job Template
        ------------------------------------     --------------------------------------------------------------------
        start_date_type                          Optional string. Type of Start Date (e.g. creationDate)
        ------------------------------------     --------------------------------------------------------------------
        diagram_id                               Optional string. Job Template Diagram ID
        ------------------------------------     --------------------------------------------------------------------
        diagram_name                             Optional string. Job Template Diagram Name
        ------------------------------------     --------------------------------------------------------------------
        assigned_type                            Optional string. Type of Job Template Assignment
        ------------------------------------     --------------------------------------------------------------------
        description                              Optional string. Job Template Description
        ------------------------------------     --------------------------------------------------------------------
        default_description                      Optional string. Default Job Template Description
        ------------------------------------     --------------------------------------------------------------------
        state                                    Optional string. Default Job Template State
        ------------------------------------     --------------------------------------------------------------------
        last_updated_by                          Optional string. User Who Last Updated Job Template
        ------------------------------------     --------------------------------------------------------------------
        last_updated_date                        Optional string. Date of Last Job Template Update
        ------------------------------------     --------------------------------------------------------------------
        extended_property_table_definitions      Optional list. List of Extended Properties for Job Template
        ====================================     ====================================================================

        :return:
            Workflow Manager :class:`~arcgis.gis.workflowmanager.JobTemplate` ID

        """
        try:
            if default_due_date is None:
                default_due_date = datetime.datetime.now().strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            if default_start_date is None:
                default_start_date = datetime.datetime.now().strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            if last_updated_date is None:
                last_updated_date = datetime.datetime.now().strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            url = "{base}/jobTemplates".format(base=self._url)

            post_job_template = JobTemplate(
                {
                    "jobTemplateId": id,
                    "jobTemplateName": name,
                    "category": category,
                    "defaultJobDuration": job_duration,
                    "defaultAssignedTo": assigned_to,
                    "defaultDueDate": default_due_date,
                    "defaultStartDate": default_start_date,
                    "jobStartDateType": start_date_type,
                    "diagramId": diagram_id,
                    "diagramName": diagram_name,
                    "defaultPriorityName": priority,
                    "defaultAssignedType": assigned_type,
                    "description": description,
                    "defaultDescription": default_description,
                    "state": state,
                    "extendedPropertyTableDefinitions": extended_property_table_definitions,
                    "lastUpdatedBy": last_updated_by,
                    "lastUpdatedDate": last_updated_date,
                }
            )

            return post_job_template.post(self._gis, url)
        except:
            self._handle_error(sys.exc_info())

    def update_job_template(self, template):
        """
        Updates a job template object by ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        template            Required object. :class:`Job Template <arcgis.gis.workflowmanger.JobTemplate>`
                            body. Existing Job Template object that inherits required/optional fields.
        ===============     ====================================================================

        :return:
            success object

        """
        try:
            url = "{base}/jobTemplates/{jobTemplate}".format(
                base=self._url,
                jobTemplate=template["job_template_id"],
                item=self._item.id,
            )
            template_object = JobTemplate(template)
            res = template_object.put(self._gis, url)
            return res
        except:
            self._handle_error(sys.exc_info())

    def create_diagram(
        self,
        name: str,
        steps: list,
        display_grid: bool,
        description: str = "",
        active: bool = False,
        annotations: list = [],
        data_sources: list = [],
        diagram_id: Optional[str] = None,
        centralized_data_references: list = [],
        use_centralized_data_references: bool = False,
    ):
        """
        Adds a diagram to the Workflow Manager instance given a user-defined name and array of steps

        =============================== ====================================================================
        **Parameter**                   **Description**
        ------------------------------- --------------------------------------------------------------------
        name                            Required string. Diagram Name
        ------------------------------- --------------------------------------------------------------------
        steps                           Required list. List of Step objects associated with the Diagram
        ------------------------------- --------------------------------------------------------------------
        display_grid                    Required boolean. Boolean indicating whether the grid will be displayed in the
                                        Diagram
        ------------------------------- --------------------------------------------------------------------
        description                     Optional string. Diagram description
        ------------------------------- --------------------------------------------------------------------
        active                          Optional Boolean. Indicates whether the Diagram is active
        ------------------------------- --------------------------------------------------------------------
        annotations                     Optional list. List of Annotation objects associated with the Diagram
        ------------------------------- --------------------------------------------------------------------
        data_sources                    Optional list. Spatial data that will be used in the steps of the diagram.
                                        Note: It is recommended to use centralizedDataReferences for new diagrams.
                                        Data sources are not supported in ArcGIS Online.
        ------------------------------- --------------------------------------------------------------------
        diagram_id                      Optional string. The unique ID of the diagram to be created.
        ------------------------------- --------------------------------------------------------------------
        centralized_data_references     Optional list. The Centralized references to data and other content that will be
                                        used in the steps of the diagram. See details for CentralizedDataReference below
        ------------------------------- --------------------------------------------------------------------
        use_centralized_data_references Optional boolean. Indicates that the diagram's step configurations make use of
                                        CentralizedDataReferences. Defaults to false. Note: It is recommended that this
                                        is set to True for new diagrams
        =============================== ====================================================================

        :return:
            :class:`Workflow Manager Diagram <arcgis.gis.workflowmanager.JobDiagram>` ID

        CentralizedDataReference Dictionary
        ===============================

        ===============              ====================================================================
        **Parameter**                **Description**
        ---------------              --------------------------------------------------------------------
        id                           Required string. The unique identifier of the data reference to be stored in the diagram.
        ---------------              --------------------------------------------------------------------
        alias                        Required string. The unique name of the data reference to be stored in the diagram.
        ---------------              --------------------------------------------------------------------
        isValidated                  Required boolean. Indicates whether the data reference has been validated.
                                     Note: Pro Items and Pro Commands are not validated.
        ---------------              --------------------------------------------------------------------
        referenceType                Required string. The type of data reference. Accepted values include FeatureService,
                                     Survey, GeoprocessingService, WebMap, ProProject, ProMapItem, ProSceneItem,
                                     ProTaskItem, ProLayoutItem, ProSystemToolboxItem, or ProCommand. Note: Geoprocessing
                                     services must use either standaloneGPUrl or portalItem.
        ---------------              --------------------------------------------------------------------
        capabilities                 Optional list. The capabilities of a branch versioned feature service. Valid values
                                     include SupportsBranchVersioning, SupportsCreateReplica, and SupportsDataQuality.
        ---------------              --------------------------------------------------------------------
        portalItem                   Optional portalItem dict. The item information for the reference. Required for
                                     referencesTypes set to FeatureService, Survey, WebMap, or ProProject. For more
                                     details, see PortalItem below.
        ---------------              --------------------------------------------------------------------
        proItemName                  Optional string. The name of the Pro item. Required when the referenceType is set
                                     to ProMapItem, ProSceneItem, ProTaskItem, ProLayoutItem, or ProSystemToolboxItem
        ---------------              --------------------------------------------------------------------
        command                      Optional string. The Pro command DAML id. Required when the referenceType is ProCommand.
        ---------------              --------------------------------------------------------------------
        standaloneGPUrl              Optional string. The service URL for the Geoprocessing Service. Required when the
                                     referenceType is GeoprocessingService and portalItem is not defined.
        ===============              ====================================================================

        .. code-block:: python

            # CentralizedDataReference Object Example 1:
            {
              "id": "50c6a626-2e45-4cfa-b149-3add455f9d72",
              "alias": "ParcelFabricDataQuality",
              "portalItem": {
                "itemId": "a64fdcf5e7b44a27bd98d098ca02ca57",
                "portalType": "Current",
                "portalUrl": null
              },
              "isValidated": true,
              "referenceType": "FeatureService",
              "capabilities": [
                "SupportsBranchVersioning",
                "SupportsDataQuality"
              ]
            }

        .. code-block:: python

            # CentralizedDataReference Object Example 2:
            {
                "id": "f9f002b0-ea3e-49a3-b40c-5e08687282f0",
                "alias": "GeocodingTools",
                "portalItem": {
                    "itemId": "7eacbbfff9a24bc0a7fc0e9d7b805ccd",
                    "portalType": "Current",
                    "portalUrl": null
                },
                "isValidated": true,
                "referenceType": "GeoprocessingService"
            }

        .. code-block:: python

            # CentralizedDataReference Object Example 3:
            {
              "id": "b09ae444-3400-49ca-9a1b-1f3795332139",
              "alias": "Echo Tool",
              "isValidated": true,
              "referenceType": "GeoprocessingService",
              "standaloneGPUrl": "https://example.esri.com/arcgis/rest/services/ProcessingTool/GPServer/ProcessingTool"
            }

        .. code-block:: python

            # CentralizedDataReference Object Example 4:
            {
              "id": "e8e5c963-a485-4f5f-a298-dcf430f72c28",
              "proItemName": "MyProMap",
              "referenceType": "ProMapItem"
            }


        PortalItem Object
        ========================

        ===============              ====================================================================
        **Parameter**                **Description**
        ---------------              --------------------------------------------------------------------
        itemId                       Required string. The unique item identifier of the Portal item.
        ---------------              --------------------------------------------------------------------
        portalType                   Optional string. The hosting Portal location of the data reference relative to the
                                     workflow item. Accepted values include Current, ArcGIS Online, and Other. This value
                                     is set to Current by default.
        ---------------              --------------------------------------------------------------------
        portalUrl                    Optional string. Required when portalType is set to Other, the full URL including
                                     Web Adaptor for the Portal hosting the item.
        ===============              ====================================================================

        """
        try:
            url = "{base}/diagrams".format(base=self._url)
            diagram_obj = {
                "diagramId": diagram_id,
                "diagramName": name,
                "description": description,
                "active": active,
                "initialStepId": "",
                "initialStepName": "",
                "steps": steps,
                "dataSources": data_sources,
                "annotations": annotations,
                "displayGrid": display_grid,
            }
            if centralized_data_references:
                diagram_obj["centralizedDataReferences"] = centralized_data_references
            if use_centralized_data_references:
                diagram_obj["useCentralizedDataReferences"] = True

            post_diagram = JobDiagram(diagram_obj)
            return post_diagram.post(self._gis, url)["diagram_id"]
        except:
            self._handle_error(sys.exc_info())

    def update_diagram(self, body, delete_draft: bool = True):
        """
        Updates a diagram object by ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        body                Required object. Diagram body - existing Diagram object that inherits required/optional
                            fields.
        ---------------     --------------------------------------------------------------------
        delete_draft        Optional Boolean - option to delete the Diagram draft (optional)
        ===============     ====================================================================

        :return:
            success object

        .. code-block:: python

            # USAGE EXAMPLE: Updating a diagram with centralized data references

            # create a WorkflowManager object from the workflow item
            wm = WorkflowManager(wf_item)

            # The update body contains only those fields we wish to update.
            updated_diagram_body = {
                                    "diagramName": "Updated Diagram Name",
                                    "description": "Updated",
                                    "centralizedDataReferences": [
                                          {
                                            "id": "f9f002b0-ea3e-49a3-b40c-5e08687282f0",
                                            "alias": "GeocodingTools",
                                            "isValidated": true,
                                            "portalItem": {
                                              "itemId": "7eacbbfff9a24bc0a7fc0e9d7b805ccd",
                                              "portalType": "Current"
                                            },
                                            "acceptsToken": true,
                                            "referenceType": "GeoprocessingService"
                                          },
                                          {
                                            "id": "5a3aa2d1-06ed-49fc-9c38-e1576d9cc5d2",
                                            "alias": "Example Feature Service",
                                            "portalItem": {
                                              "itemId": "a64fdcf5e7b44a27bd98d098ca02ca57",
                                              "portalType": "Current",
                                              "portalUrl": null
                                            },
                                            "isValidated": true,
                                            "referenceType": "FeatureService",
                                            "capabilities": [ "SupportsBranchVersioning", "SupportsDataQuality" ]
                                          }
                                        ]
                                    "useCentralizedDataReferences": True
                                    }

            wm.update_diagram(update_diagram_body, delete_draft=True)

        """
        try:
            body = {
                _camelCase_to_underscore(k): v
                for k, v in body.items()
                if v is not None and not k.startswith("_")
            }
            url = "{base}/diagrams/{diagramid}".format(
                base=self._url, diagramid=body["diagram_id"]
            )
            diagram_obj = {
                "diagramId": body["diagram_id"],
                "diagramName": body["diagram_name"],
                "description": (body["description"] if "description" in body else ""),
                "active": (body["active"] if "active" in body else False),
                "initialStepId": (
                    body["initial_step_id"] if "initial_step_id" in body else ""
                ),
                "initialStepName": (
                    body["initial_step_name"] if "initial_step_name" in body else ""
                ),
                "steps": body["steps"],
                "dataSources": (body["data_sources"] if "data_sources" in body else []),
                "annotations": (body["annotations"] if "annotations" in body else ""),
                "displayGrid": body["display_grid"],
                "useCentralizedDataReferences": (
                    body["use_centralized_data_references"]
                    if "use_centralized_data_references" in body
                    else False
                ),
            }
            if body.get("centralized_data_references"):
                diagram_obj["centralizedDataReferences"] = body[
                    "centralized_data_references"
                ]

            post_diagram = JobDiagram(diagram_obj)
            res = post_diagram.update(self._gis, url, delete_draft)

            return res
        except:
            self._handle_error(sys.exc_info())

    def delete_diagram(self, id: str):
        """
        Deletes a diagram object by ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        id                  Required string. Diagram id
        ===============     ====================================================================

        :return:
            :class:`Workflow Manager Diagram <arcgis.gis.workflowmanager.JobDiagram>` ID

        """
        try:
            url = "{base}/diagrams/{diagramid}".format(base=self._url, diagramid=id)
            return JobDiagram.delete(self, self._gis, url)
        except:
            self._handle_error(sys.exc_info())

    def delete_diagram_version(self, diagram_id, version_id):
        """
        Deletes a diagram version by ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        diagram_id          Required string. Diagram ID
        ---------------     --------------------------------------------------------------------
        version_id          Required string. Diagram Version ID
        ===============     ====================================================================

        :return:
            Boolean

        """
        try:
            url = "{base}/diagrams/{diagramid}/{diagramVersion}".format(
                base=self._url, diagramid=diagram_id, diagramVersion=version_id
            )
            return JobDiagram.delete(self, self._gis, url)
        except:
            self._handle_error(sys.exc_info())

    @property
    def saved_searches(self):
        """
        The Saved Searches manager for a workflow item.

        :return:
            :class:`~arcgis.gis.workflowmanager.SavedSearchesManager`

        """

        return self.saved_searches_manager

    @property
    def table_definitions(self):
        """
        Get the definitions of each extended properties table in a workflow item. The response will consist of a list
        of table definitions. If the extended properties table is a feature service, its definition will include a
        dictionary of feature service properties. Each table definition will also include definitions of the properties
        it contains and list the associated job templates. This requires the adminBasic or adminAdvanced privileges.

        :return:
            `List <https://docs.python.org/3/library/stdtypes.html#list>`_

        """

        url = "{base}/tableDefinitions".format(base=self._url)

        return_obj = self._gis._con.get(url)
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]

        return return_obj["tableDefinitions"]

    def lookups(self, lookup_type):
        """
        Returns LookUp Tables by given type

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        lookup_type         Required string. The type of lookup table stored in the workflow item.
        ===============     ====================================================================

        :return:
           Workflow Manager :class:`LookUpTable <arcgis.gis.workflowmanager.LookUpTable>` Object

        """
        try:
            return LookUpTable.get(
                self,
                self._gis,
                "{base}/lookups/{lookupType}".format(
                    base=self._url, lookupType=lookup_type
                ),
                params={},
            )
        except:
            self._handle_error(sys.exc_info())

    def delete_lookup(self, lookup_type):
        """
        Deletes a job template with the given ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        lookup_type         Required string. The type of lookup table stored in the workflow item.
        ===============     ====================================================================

        :return:
            status code

        """
        try:
            res = LookUpTable.delete(
                self,
                self._gis,
                "{base}/lookups/{lookupType}".format(
                    base=self._url, lookupType=lookup_type, item=self._item.id
                ),
            )
            return res
        except:
            self._handle_error(sys.exc_info())

    def create_lookup(self, lookup_type, lookups):
        """
        Adds a diagram to the Workflow Manager instance given a user-defined name and array of steps

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        lookup_type         Required string. The type of lookup table stored in the workflow item.
        ---------------     --------------------------------------------------------------------
        lookups             Required list. List of lookups to be created / updated
        ===============     ====================================================================

        :return:
            Boolean

        .. code-block:: python

            # USAGE EXAMPLE: Creating a Lookup Table

            # create a WorkflowManager object from the workflow item
            wm = WorkflowManager(wf_item)

            # create the lookups object
            lookups = [{"lookupName": "Low", "value": 0},
                       {"lookupName": "Medium", "value": 5},
                       {"lookupName": "High", "value": 10},
                       {"lookupName": "EXTRA", "value": 15},
                       {"lookupName": "TEST", "value": 110}]

            wm.create_lookup("priority", lookups)
            >> True  # returns true if created successfully
        """
        try:
            url = "{base}/lookups/{lookupType}".format(
                base=self._url, lookupType=lookup_type
            )

            post_lookup = LookUpTable({"lookups": lookups})

            return post_lookup.put(self._gis, url)
        except:
            self._handle_error(sys.exc_info())

    def templates(self, template_type):
        """
        Returns Templates by given type

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        template_type       Required string. The type of template stored in the workflow item.
                            Get the email templates by entering 'email', the Web Request Templates by entering
                            'webRequest', or, enter your own value to get the custom templates.
        ===============     ====================================================================

        :return:
           Workflow Manager :class:`Template <arcgis.gis.workflowmanager.Template>` List

        """
        try:
            template_list = self._gis._con.get(
                f"{self._url}/templates/{template_type}"
            )["templates"]

            return [
                self.get_template(template_type, template_dict["templateId"])
                for template_dict in template_list
            ]
        except:
            self._handle_error(sys.exc_info())

    def get_template(self, template_type: str, template_id: str):
        """
        Returns a Template by the given type and id

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        template_type       Required string. The type of template stored in the workflow item.
                            Get an email template by entering 'email', a Web Request Template by entering
                            'webRequest', or enter your own value to get a custom template.
        ---------------     --------------------------------------------------------------------
        template_id         Required string. The id of the template to be retrieved
        ===============     ====================================================================

        :return:
           Workflow Manager :class:`Template <arcgis.gis.workflowmanager.Template>` Object

        .. code-block:: python

            # USAGE EXAMPLE: Get a Template

            # create a WorkflowManager object from the workflow item
            wm = WorkflowManager(wf_item)

            # get a template
            wm.get_template(template_type="email", template_id="Ef42tu_QQMS-IgZc7pOPnQ")

            >> { "template_name": "Email Template",
                 "template_id": "Ef42tu_QQMS-IgZc7pOPnQ",
                 "template_details": {"to":["user@esri.com"],
                                      "cc":["boss@esri.com"],
                                      "bcc":["supervisor@esri.com"],
                                      "subject":"Workflow Manager Templates",
                                      "body":"Look how easy it is to make an email template!",
                                      "attachmentSelection":"None",
                                      "attachmentFolder":null }
               }
        """
        try:
            url = f"{self._url}/templates/{template_type}/{template_id}"
            template_dict = self._gis._con.get(url, {})
            return Template(
                template_dict["templateName"],
                template_dict["templateId"],
                template_dict["templateDetails"],
                self._gis,
                url,
            )
        except:
            self._handle_error(sys.exc_info())

    def delete_template(self, template_type: str, template_id: str):
        """
        Returns a boolean indicating whether or not the template has been deleted.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        template_type       Required string. The type of template stored in the workflow item.
                            Delete an email template by entering 'email', a Web Request Template by entering
                            'webRequest', or enter your own value to delete a custom template.
        ---------------     --------------------------------------------------------------------
        template_id         Required string. The id of the template to be deleted
        ===============     ====================================================================

        :return:
           Boolean

        """
        try:
            url = f"{self._url}/templates/{template_type}/{template_id}"
            return_obj = json.loads(self._gis._con.delete(url, try_json=False))
            if "error" in return_obj:
                raise Exception(return_obj["error"].get("message"))
            elif "success" in return_obj:
                return return_obj["success"]
            return_obj = {
                _camelCase_to_underscore(k): v
                for k, v in return_obj.items()
                if v is not None and not k.startswith("_")
            }
            return return_obj
        except:
            self._handle_error(sys.exc_info())

    def update_template(
        self,
        template_type: str,
        template_id: str,
        template_name: str,
        template_details: str,
    ):
        """
        Returns a boolean indicating whether or not the template was updated.

        =================     ====================================================================
        **Parameter**          **Description**
        -----------------     --------------------------------------------------------------------
        template_type         Required string. The type of template stored in the workflow item.
                              Update an email template by entering 'email', a Web Request Template by entering
                              'webRequest', or enter your own value to update a custom template.
        -----------------     --------------------------------------------------------------------
        template_id           Required string. The id of the template to be updated
        -----------------     --------------------------------------------------------------------
        template_name         Required string. The new name to be given to the template
        -----------------     --------------------------------------------------------------------
        template_details      Required dict. The new information to be stored in the template
        =================     ====================================================================

        :return:
           Boolean

        .. code-block:: python

            # USAGE EXAMPLE: Update a Template

            # update a WorkflowManager object from the workflow item
            wm = WorkflowManager(wf_item)

            # update the template object
            details = { "to":["user@esri.com"],
                         "cc":["boss@esri.com"],
                         "bcc":["supervisor@esri.com"],
                         "subject": "Workflow Manager Templates",
                         "body": "Look how easy it is to make an email template!",
                         "attachmentSelection":"None" }

            wm.update_template(template_type="email",
                               template_id='Ef42tu_QQMS-IgZc7pOPnQ'
                               template_name="Email Template",
                               template_details=details)
            >> True  # returns True if updated successfully
        """
        try:
            details = self.get_template(template_type, template_id).template_details
            details = {**details, **template_details}
            details_str = json.dumps(details)
            obj = {
                "templateId": template_id,
                "templateName": template_name,
                "templateDetails": details_str,
            }
            url = f"{self._url}/templates/{template_type}/{template_id}"
            return_obj = json.loads(
                self._gis._con.put(
                    url,
                    obj,
                    post_json=True,
                    try_json=False,
                    json_encode=False,
                )
            )
            if "error" in return_obj:
                raise Exception(return_obj["error"].get("message"))
            elif "success" in return_obj:
                return return_obj["success"]
            return_obj = {
                _camelCase_to_underscore(k): v
                for k, v in return_obj.items()
                if v is not None and not k.startswith("_")
            }
            return return_obj
        except:
            self._handle_error(sys.exc_info())

    def create_template(
        self,
        template_type: str,
        template_name: str,
        template_details: dict,
        template_id: Optional[str] = None,
    ):
        """
        Returns the newly created template id.

        =================     ====================================================================
        **Parameter**         **Description**
        -----------------     --------------------------------------------------------------------
        template_type         Required string. The type of template stored in the workflow item.
                              Create an email template by entering 'email', a Web Request Template by entering
                              'webRequest', or enter your own value to define a custom template.
        -----------------     --------------------------------------------------------------------
        template_name         Required string. The new name to be given to the template
        -----------------     --------------------------------------------------------------------
        template_details      Required dict. The new information to be stored in the template
        -----------------     --------------------------------------------------------------------
        template_id           Optional string. The id of the template to be created
        =================     ====================================================================

        :return:
           Workflow Manager :class:`Template <arcgis.gis.workflowmanager.Template>` ID

        .. code-block:: python

            # USAGE EXAMPLE: Creating a Template

            # create a WorkflowManager object from the workflow item
            wm = WorkflowManager(wf_item)

            # create the template object
            details = { "to":["user@esri.com"],
                         "cc":["boss@esri.com"],
                         "bcc":["supervisor@esri.com"],
                         "subject":"Workflow Manager Templates",
                         "body":"Look how easy it is to make an email template!",
                         "attachmentSelection":"None" }

            wm.create_template(template_type="email", template_name="Email Template", template_details=details)
            >> Ef42tu_QQMS-IgZc7pOPnQ  # returns Template ID if created successfully
        """
        try:
            details_str = json.dumps(template_details)
            obj = {
                "templateName": template_name,
                "templateDetails": details_str,
            }
            if template_id is not None:
                obj["templateId"] = template_id

            url = f"{self._url}/templates/{template_type}"
            return_obj = json.loads(
                self._gis._con.post(
                    url,
                    obj,
                    post_json=True,
                    try_json=False,
                    json_encode=False,
                )
            )
            if "error" in return_obj:
                raise Exception(return_obj["error"].get("message"))
            elif "success" in return_obj:
                return return_obj["success"]
            return return_obj
        except:
            self._handle_error(sys.exc_info())


class LookUpTable(object):
    """
    Represents a Workflow Manager Look Up object with accompanying GET, POST, and DELETE methods.

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    init_data           data object containing the relevant properties for a LookUpTable to complete REST calls
    ===============     ====================================================================
    """

    _camelCase_to_underscore = _camelCase_to_underscore
    _underscore_to_camelcase = _underscore_to_camelcase

    def __init__(self, init_data, gis=None, url=None):
        for key in init_data:
            setattr(self, _camelCase_to_underscore(key), init_data[key])
        self._gis = gis
        self._url = url

    def __getattr__(self, item):
        gis = object.__getattribute__(self, "_gis")
        url = object.__getattribute__(self, "_url")
        id = object.__getattribute__(self, "job_template_id")
        full_object = gis._con.get(url, {})
        try:
            setattr(self, _camelCase_to_underscore(item), full_object[item])
            return full_object[item]
        except KeyError:
            raise KeyError(f'The attribute "{item}" is invalid for LookUpTables')

    def get(self, gis, url, params):
        lookup_dict = gis._con.get(url, params)
        return LookUpTable(lookup_dict, gis, url)

    def put(self, gis, url):
        put_dict = {
            _underscore_to_camelcase(k): v
            for k, v in self.__dict__.items()
            if v is not None
        }
        return_obj = json.loads(
            gis._con.put(
                url,
                put_dict,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def delete(self, gis, url):
        return_obj = json.loads(gis._con.delete(url, try_json=False))
        if "error" in return_obj:
            gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj


class Template(object):
    """
    Represents a Workflow Manager Template object with accompanying GET, POST, and DELETE methods.

    =================     ====================================================================
    **Parameter**          **Description**
    -----------------     --------------------------------------------------------------------
    template_name         The template name
    -----------------     --------------------------------------------------------------------
    template_details      The details of the template
    -----------------     --------------------------------------------------------------------
    template_id           The template ID
    =================     ====================================================================
    """

    _camelCase_to_underscore = _camelCase_to_underscore
    _underscore_to_camelcase = _underscore_to_camelcase

    def __init__(
        self, template_name, template_id, template_details, gis=None, url=None
    ):
        self.template_name = template_name
        self.template_id = template_id
        self.template_details = json.loads(template_details)
        self._gis = gis
        self._url = url

    def __getattr__(self, item):
        gis = object.__getattribute__(self, "_gis")
        url = object.__getattribute__(self, "_url")
        full_object = gis._con.get(url, {})
        try:
            setattr(self, _camelCase_to_underscore(item), full_object[item])
            return full_object[item]
        except KeyError:
            raise KeyError(f'The attribute "{item}" is invalid for Templates')


class SavedSearchesManager:
    """
    Represents a helper class for workflow manager saved searches. Accessible as the
    :attr:`~arcgis.gis.workflowmanager.WorkflowManager.saved_searches` property.

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    item                The Workflow Manager Item
    ===============     ====================================================================

    """

    def __init__(self, item):
        """initializer"""
        if item is None:
            raise ValueError("Item cannot be None")
        self._item = item
        _initialize(self, item._gis)

    def _handle_error(self, info):
        """Basic error handler - separated into a function to allow for expansion in future releases"""
        error_class = info[0]
        error_text = info[1]
        raise Exception(error_text)

    def create(
        self,
        name: str,
        search_type: str,
        folder: Optional[str] = None,
        definition: Optional[str] = None,
        color_ramp: Optional[str] = None,
        sort_index: Optional[str] = None,
        search_id: Optional[str] = None,
    ):
        """
        Create a saved search or chart by specifying the search parameters in the json body.
        All search properties except for optional properties must be passed in the body to save the search or chart.
        The adminAdvanced or adminBasic privilege is required.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        name                Required string. The display name for the saved search or chart.
        ---------------     --------------------------------------------------------------------
        search_type         Required string. The type for the saved search or chart. The accepted values are Standard, Chart and All.
        ---------------     --------------------------------------------------------------------
        folder              Optional string. The folder the saved search or chart will be categorized under.
        ---------------     --------------------------------------------------------------------
        definition          Required string. if the searchType is Standard. The search definition to be saved.
        ---------------     --------------------------------------------------------------------
        color_ramp          Required string. if the searchType is Chart. The color ramp for the saved chart.
        ---------------     --------------------------------------------------------------------
        sort_index          Optional string. The sorting order for the saved search or chart.
        ---------------     --------------------------------------------------------------------
        search_id           Optional string. The unique ID of the search or chart to be created.
        ===============     ====================================================================

        :return:
            Saved Search ID

        """
        try:
            url = "{base}/searches".format(base=self._url, id=search_id)
            post_dict = {
                "name": name,
                "folder": folder,
                "definition": definition,
                "searchType": search_type,
                "colorRamp": color_ramp,
                "sortIndex": sort_index,
                "searchId": search_id,
            }
            post_dict = {k: v for k, v in post_dict.items() if v is not None}
            return_obj = json.loads(
                self._gis._con.post(
                    url,
                    post_dict,
                    post_json=True,
                    try_json=False,
                    json_encode=False,
                )
            )

            if "error" in return_obj:
                self._gis._con._handle_json_error(return_obj["error"], 0)
            elif "success" in return_obj:
                return return_obj["success"]

            return return_obj["searchId"]
        except:
            self._handle_error(sys.exc_info())

    def delete(self, id: str):
        """
        Deletes a saved search by ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        id                  Required string. Saved Search id
        ===============     ====================================================================

        :return:
            Boolean
        """
        try:
            url = "{base}/searches/{searchid}".format(base=self._url, searchid=id)

            return_obj = json.loads(self._gis._con.delete(url, try_json=False))

            if "error" in return_obj:
                self._gis._con._handle_json_error(return_obj["error"], 0)
            elif "success" in return_obj:
                return return_obj["success"]
        except:
            self._handle_error(sys.exc_info())

    def update(self, search):
        """
        Update a saved search or chart by specifying the update values in the json body.
        All the properties except for optional properties must be passed in the body
        to update the search or chart. The searchId cannot be updated once it is created.
        The adminAdvanced or adminBasic privilege is required.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        search              Required object. An object defining the properties of the search to be updated.
        ===============     ====================================================================

        :return: success object

        .. code-block:: python

            # USAGE EXAMPLE: Updating a search's properties

            # create a WorkflowManager object from the workflow item
            workflow_manager = WorkflowManager(wf_item)

            workflow_manager.create_saved_search(name="name",
                                                 definition={
                                                     "start": 0,
                                                     "fields": ["job_status"],
                                                     "displayNames": ["Status"  ],
                                                     "sortFields": [{"field": "job_status",
                                                                     "sortOrder": "Asc:}]
                                                             },
                                                 search_type='Chart',
                                                 color_ramp='Flower Field Inverse',
                                                 sort_index=2000)

            search_lst = workflow_manager.searches("All")
            search = [x for x in search_lst if x["searchId"] == searchid][0]

            search["colorRamp"] = "Default"
            search["name"] = "Updated search"

            actual = workflow_manager.update_saved_search(search)

        """
        try:
            url = "{base}/searches/{searchId}".format(
                base=self._url, searchId=search["searchId"]
            )
            return_obj = json.loads(
                self._gis._con.put(
                    url,
                    search,
                    post_json=True,
                    try_json=False,
                    json_encode=False,
                )
            )

            if "error" in return_obj:
                self._gis._con._handle_json_error(return_obj["error"], 0)
            elif "success" in return_obj:
                return return_obj["success"]
            return return_obj
        except:
            self._handle_error(sys.exc_info())

    def share(self, search_id, group_ids):
        """
        Shares a saved search with the list of groups

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        search_id           Required string. Saved Search id
        ---------------     --------------------------------------------------------------------
        group_ids           Required list. List of Workflow Group Ids
        ===============     ====================================================================

        :return:
            Boolean
        """
        try:
            url = "{base}/searches/{searchId}/shareWith".format(
                base=self._url, searchId=search_id
            )
            post_dict = {"groupIds": group_ids}

            return_obj = json.loads(
                self._gis._con.post(
                    url,
                    post_dict,
                    post_json=True,
                    try_json=False,
                    json_encode=False,
                )
            )

            if "error" in return_obj:
                self._gis._con._handle_json_error(return_obj["error"], 0)
            elif "success" in return_obj:
                return return_obj["success"]
        except:
            self._handle_error(sys.exc_info())

    def share_details(self, search_id):
        """
        Returns the list of groups that the saved search is shared with by searchId.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        search_id           Search ID
        ===============     ====================================================================

        :return:
            List of :class:`~arcgis.gis.workflowmanager.Group` ID

        """

        url = "{base}/searches/{searchId}/shareWith".format(
            base=self._url, searchId=search_id
        )

        return_obj = self._gis._con.get(url)

        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj["groupIds"]


class Job(object):
    """
    Helper class for managing Workflow Manager jobs in a workflow item. This class is
    not created by users directly. An instance of this class, can be created by calling
    the :meth:`get <arcgis.gis.workflowmanager.JobManager.get>` method of the
    :class:`~arcgis.gis.workflowmanager.JobManager` with the appropriate job ID. The
    :class:`~arcgis.gis.workflowmanager.JobManager` is accessible as the
    :attr:`~arcgis.gis.workflowmanager.WorkflowManager.jobs` property of the
    :class:`~arcgis.gis.workflowmanager.WorkflowManager`.

    """

    _camelCase_to_underscore = _camelCase_to_underscore
    _underscore_to_camelcase = _underscore_to_camelcase

    def __init__(self, init_data, gis=None, url=None, workflow_manager=None):
        self.job_status = None
        self.notes = None
        self.diagram_id = None
        self.end_date = None
        self.due_date = None
        self.description = None
        self.started_date = None
        self.current_steps = None
        self.job_template_name = None
        self.job_template_id = None
        self.extended_properties = None
        self.holds = None
        self.diagram_name = None
        self.parent_job = None
        self.job_name = None
        self.diagram_version = None
        self.active_versions = None
        self.percent_complete = None
        self.priority = None
        self.job_id = None
        self.created_date = None
        self.created_by = None
        self.closed = None
        self.owned_by = None
        self.start_date = None
        self._location = None
        self.related_properties = None
        for key in init_data:
            setattr(self, _camelCase_to_underscore(key), init_data[key])
        self._gis = gis
        self._url = url
        self._workflow_manager = workflow_manager

    def post(self):
        post_dict = {
            _underscore_to_camelcase(k): v
            for k, v in self.__dict__.items()
            if v is not None and not k.startswith("_")
        }
        return_obj = json.loads(
            self._gis._con.post(
                self._url,
                post_dict,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj

    def search(self, gis, url, search_object):
        return_obj = json.loads(
            gis._con.post(
                url,
                search_object,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def get_attachment(self, attachment_id: str):
        """
        Returns an embedded job attachment given an attachment ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        attachment_id       Attachment ID
        ===============     ====================================================================

        :return:
            Job Attachment

        """

        url = "{base}/jobs/{jobId}/attachments/{attachmentId}".format(
            base=self._url, jobId=self.job_id, attachmentId=attachment_id
        )
        return_obj = self._gis._con.get(url, {}, try_json=False)
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj

    def add_attachment(
        self, attachment: str, alias: Optional[str] = None, folder: Optional[str] = None
    ):
        """
        Adds an attachment to the job

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        attachment          Filepath to attachment
        ---------------     --------------------------------------------------------------------
        alias               Optional string. Alias for the attachment
        ---------------     --------------------------------------------------------------------
        folder              Optional string. Folder for the attachment
        ===============     ====================================================================

        :return:
            Job Attachment

        """
        url = "{base}/jobs/{jobId}/attachments".format(
            base=self._url, jobId=self.job_id
        )
        return_obj = json.loads(
            self._gis._con.post(
                url,
                params={"alias": alias, "folder": folder},
                files={"attachment": attachment},
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        return {"id": return_obj["url"].split("/")[-1], "alias": return_obj["alias"]}

    def add_linked_attachment(self, attachments: list):
        """
        Add linked attachments to a job to provide additional or support information related to the job.
        Linked attachments can be links to a file on a local or shared file system or a URL.
        jobUpdateAttachments privilege is required to add an attachment to a job.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        attachments         List of linked attachments to associate with the job.
                            Each attachment should define the url, alias and folder
        ===============     ====================================================================

        :return:
            `List <https://docs.python.org/3/library/stdtypes.html#list>`_ list of job attachments

        """
        url = "{base}/jobs/{jobId}/attachmentslinked".format(
            base=self._url, jobId=self.job_id
        )

        post_object = {"attachments": attachments}
        return_obj = json.loads(
            self._gis._con.post(
                url,
                params=post_object,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        return return_obj["attachments"]

    def update_attachment(self, attachment_id: str, alias: str):
        """
        Updates an attachment alias given a Job ID and attachment ID

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        attachment_id       Attachment ID
        ---------------     --------------------------------------------------------------------
        alias               Alias
        ===============     ====================================================================

        :return:
            success

        """
        url = "{base}/jobs/{jobId}/attachments/{attachmentid}".format(
            base=self._url, jobId=self.job_id, attachmentid=attachment_id
        )
        post_object = {"alias": alias}
        return_obj = json.loads(
            self._gis._con.post(
                url, params=post_object, try_json=False, json_encode=False
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def delete_attachment(self, gis, url):
        return_obj = json.loads(gis._con.delete(url, try_json=False))
        if "error" in return_obj:
            gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def update_step(self, step_id: str, assigned_type: str, assigned_to: str):
        """
        Update the assignment of the current step in a job based on the current user's Workflow Manager assignment privileges

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        step_id             Required String. Active Step ID
        ---------------     --------------------------------------------------------------------
        assigned_type       Required String. Type of assignment designated
                            Values: "User" | "Group" | "Unassigned"
        ---------------     --------------------------------------------------------------------
        assigned_to         Required String. User id to which the active step is assigned
        ===============     ====================================================================

        :return:
            success object

        .. code-block:: python

            # USAGE EXAMPLE: Updating a step assignment

            # create a WorkflowManager object from the workflow item
            wm = WorkflowManager(wf_item)

            job = wm.jobs.get('job_id')
            job.update_step(step_id='123456', assigned_type='User', assigned_to='my_user')

        """

        if step_id is None:
            step_id = self.currentSteps[0]["step_id"]
        url = "{base}/jobs/{jobId}/{stepId}".format(
            base=self._url,
            jobId=self.job_id,
            stepId=step_id,
        )
        post_object = {"assignedType": assigned_type, "assignedTo": assigned_to}
        return_obj = json.loads(
            self._gis._con.post(
                url,
                params=post_object,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def set_current_step(self, step_id: str):
        """
        Sets a single step to be the active step on the job. The ability to set a step as current is controlled by the **workflowSetStepCurrent** privilege.

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        step_id             Active Step ID
        ===============     ====================================================================

        :return:
            success object

        """

        url = "{base}/jobs/{jobId}/action".format(base=self._url, jobId=self.job_id)
        post_object = {"type": "SetCurrentStep", "stepIds": [step_id]}
        return_obj = json.loads(
            self._gis._con.post(
                url,
                params=post_object,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def add_hold(
        self,
        step_ids: Optional[list],
        dependent_job_id: Optional[str] = None,
        dependent_step_id: Optional[str] = None,
        hold_scheduled_release: Optional[str] = None,
    ):
        """
        Applies a hold or a dependency to a step. The Run and Finish actions cannot be performed
        on the step until the dependent step is resolved, the ReleaseHold action is run or the holdScheduledReleased has
        expired. If there is not a holdScheduledReleased timestamp, the ReleaseHold action is required to remove the
        hold or dependency. If there are multiple holds or dependencies, they must all be released or expired for the
        Run and Finish actions to be performed. Cannot be applied if the step is already running or job is closed.

        ======================      ====================================================================
        **Parameter**               **Description**
        ----------------------      --------------------------------------------------------------------
        step_ids                    Optional. The array of steps put on hold when adding a dependency hold.
                                    If not specified, the dependency hold is applied to all the active steps in the job.
        ----------------------      --------------------------------------------------------------------
        dependent_job_id            Optional. A job that the current job is dependent on from being performed step actions
                                    including Run and Finish
        ----------------------      --------------------------------------------------------------------
        dependent_step_id           Optional. The step in the job that the current job is dependent on from being performed
                                    step actions including Run and Finish.
        ----------------------      --------------------------------------------------------------------
        hold_scheduled_release      Optional. The release timestamp for a scheduled hold. Once the current date and time
                                    has passed the scheduled release timestamp, the hold will automatically release without
                                    requiring the ReleaseHold action.
        ======================      ====================================================================

        :return:
            success object

        """

        url = "{base}/jobs/{jobId}/action".format(base=self._url, jobId=self.job_id)

        post_object = {"type": "Hold"}

        if step_ids is not None:
            post_object["stepIds"] = step_ids
        if dependent_job_id is not None:
            post_object["dependentJobId"] = dependent_job_id
        if dependent_step_id is not None:
            post_object["dependentStepId"] = dependent_step_id
        if hold_scheduled_release is not None:
            post_object["holdScheduledRelease"] = hold_scheduled_release

        return_obj = json.loads(
            self._gis._con.post(
                url,
                params=post_object,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def release_hold(
        self,
        step_ids: Optional[list],
        dependent_job_id: Optional[str] = None,
        dependent_step_id: Optional[str] = None,
    ):
        """
        Releases a hold from a step, allowing the Run and Finish actions to be once again performed on the step.

        =================       ====================================================================
        **Parameter**           **Description**
        -----------------       --------------------------------------------------------------------
        step_ids                Optional. The array of steps on hold to be released. If not specified the release
                                is applied to all the steps on hold.
        -----------------       --------------------------------------------------------------------
        dependent_job_id        Optional. A job that the current job is dependent on from being performed step actions
                                including Run and Finish.
        -----------------       --------------------------------------------------------------------
        dependent_step_id       Optional. The step in the job that the current job is dependent on from being performed
                                step actions including Run and Finish.
        =================       ====================================================================

        :return:
            success object

        """

        url = "{base}/jobs/{jobId}/action".format(base=self._url, jobId=self.job_id)

        post_object = {"type": "ReleaseHold"}

        if step_ids is not None:
            post_object["stepIds"] = step_ids
        if dependent_job_id is not None:
            post_object["dependentJobId"] = dependent_job_id
        if dependent_step_id is not None:
            post_object["dependentStepId"] = dependent_step_id

        return_obj = json.loads(
            self._gis._con.post(
                url,
                params=post_object,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    @property
    def attachments(self):
        """
        Gets the attachments of a job given job ID

        :return:
            `List <https://docs.python.org/3/library/stdtypes.html#list>`_ of attachments

        """

        url = "{base}/jobs/{jobId}/attachments".format(
            base=self._url, jobId=self.job_id
        )
        return_obj = self._gis._con.get(url)
        return return_obj["attachments"]

    @property
    def history(self):
        """
        Gets the history of a job given job ID

        :return:
            success object

        """

        url = "{base}/jobs/{jobId}/history".format(base=self._url, jobId=self.job_id)
        return_obj = self._gis._con.get(url)
        if "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    @property
    def location(self):
        """
        Get/Set the job location for the user-defined job

        :return:
            Workflow Manager :class:`~arcgis.gis.workflowmanager.JobLocation` object
        """

        if self._location is None:
            self._location = JobLocation.get(
                self,
                self._gis,
                "{base}/jobs/{job}/location".format(base=self._url, job=self.job_id),
                {},
            )
        return self._location

    @location.setter
    def location(self, value):
        self._location = value

    def manage_jobs(self, gis, url, ids, action):
        post_object = {"jobIds": ids, "type": action}
        return_obj = json.loads(
            gis._con.post(
                url,
                params=post_object,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def add_comment(self, comment: str):
        """
        Adds a comment to the job

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        comment             Required string. Comment to add to job
        ===============     ====================================================================

        :return:
            Workflow Manager Comment Id

        """
        url = "{base}/jobs/{jobId}/comments".format(base=self._url, jobId=self.job_id)
        post_obj = {"comment": comment}

        return_obj = json.loads(
            self._gis._con.post(
                url,
                post_obj,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        return return_obj["commentId"]

    @property
    def comments(self):
        """
        Gets the comments of a job given job ID

        :return:
            `List <https://docs.python.org/3/library/stdtypes.html#list>`_ of comments

        """

        url = "{base}/jobs/{jobId}/comments".format(base=self._url, jobId=self.job_id)
        return_obj = self._gis._con.get(url)
        return return_obj["jobComments"]

    def set_job_version(
        self,
        data_source_name=None,
        version_guid=None,
        version_name=None,
        administered=False,
        data_reference_id=None,
    ):
        """
        Sets the version of the job.

        =================    ===================================================================
        **Argument**         **Description**
        -----------------    -------------------------------------------------------------------
        data_source_name     The name of the data source for the job version to be set. Required if the job diagram is using the data sources format.
        -----------------    -------------------------------------------------------------------
        version_guid         Optional. The guid of the version to be set. If the value is null or not defined,
                             the versionName must be defined. versionGuid is preferred to be defined for better
                             performance.
        -----------------    -------------------------------------------------------------------
        version_name         Optional. The name of the version to be set. If the value is null or not defined,
                             the versionGuid must be defined.
        -----------------    -------------------------------------------------------------------
        administered         Optional. If true, the version can be claimed. If not defined, the default value is false.
        -----------------    -------------------------------------------------------------------
        data_reference_id    The id of the data reference for the job version to be set. Required if the job diagram is using the data references format.
        =================    ===================================================================

        :return:
            success object

        """

        url = "{base}/jobs/{jobId}/update".format(base=self._url, jobId=self.job_id)

        params = {
            "workflowAdministered": administered,
        }
        if data_source_name:
            params["dataSourceName"] = data_source_name
        if data_reference_id:
            params["dataReferenceId"] = data_reference_id
        if version_guid is not None:
            params["versionGuid"] = version_guid
        if version_name is not None:
            params["versionName"] = version_name

        post_object = {"versions": [params]}

        return_obj = json.loads(
            self._gis._con.post(
                url,
                params=post_object,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def _execute_step(self, step_ids: Optional[list], execution_type: ExecutionType):
        # Create a JobExecution object
        je = JobExecution(self, execution_type)
        # Subscribe to this job
        self._workflow_manager._notification_manager.subscribe(
            [self.job_id], je._callback
        )

        # Call the action endpoint
        url = f"{self._url}/jobs/{self.job_id}/action"
        post_obj = {}
        if execution_type is ExecutionType.RUN:
            post_obj["type"] = "Run"
        elif execution_type is ExecutionType.FINISH:
            post_obj["type"] = "Finish"
        elif execution_type is ExecutionType.STOP:
            post_obj["type"] = "Stop"

        if step_ids is not None:
            post_obj["stepIds"] = step_ids

        try:
            return_obj = json.loads(
                self._gis._con.post(
                    url,
                    post_obj,
                    post_json=True,
                    try_json=False,
                    json_encode=False,
                )
            )
            # If it fails, unsubscribe then throw
            if "error" in return_obj:
                self._gis._con._handle_json_error(return_obj["error"], 0)
            elif "success" in return_obj and return_obj["success"] is False:
                raise Exception(return_obj["stepResponses"])
        except:
            self._workflow_manager._notification_manager.unsubscribe([self.job_id])
            raise

        # If it succeeds, return the JobExecution
        je._started()
        return je

    def run(self, step_ids: Optional[list] = None):
        """
        Starts running the current step(s). Running a step marks it as finished, if the step is set to proceed to next.

        The step will not be started under the following conditions:

        - Not assigned to the current user
        - No active step is defined
        - The job is closed
        - A step that cannot be skipped and has not been started or has been cancelled, will not be finished
        - A step cannot be set current if the job is running.
        - A step that has one or more holds will not run nor finish.

        ================    ===================================================================
        **Argument**        **Description**
        ----------------    -------------------------------------------------------------------
        step_ids            Optional list. The job's active step ID or active parallel step IDs.
                            If a step ID isn't provided, the action is performed on the job's current, active step(s).
        ================    ===================================================================

        :return:
            :class:`~arcgis.gis.workflowmanager.JobExecution`

        .. code-block:: python

            # USAGE EXAMPLE: Run the current active steps

            # create a WorkflowManager object from the workflow item
            wm = WorkflowManager(wf_item)

            job = wm.jobs.get('job_id')

            # Will run the current active steps, if no param is given, i.e job.run()
            run_execution = job.run(step_ids=['stepid'])

            print(f'Result = { run_execution.result() }')
            print(f'Status = { run_execution.status }')
            print(f'Elapsed Time = { run_execution.elapse_time }')
            print(f'Messages:')
            for m in run_execution.messages:
                print(m.message)

        """
        return self._execute_step(step_ids, execution_type=ExecutionType.RUN)

    def stop(self, step_ids: Optional[list] = None):
        """
        Stops the current running step(s). The step(s) can be Run again or Finish can be used to complete it. In case of
        GP step and question step, the processing of the step is cancelled. In case of manual and open app step,
        the step is paused. The step can be forced to stop by a user not assigned to the step with the
        jobForceStop privilege.

        The step will not be stopped under the following conditions:

        - Not assigned to the current user
        - No active step is defined
        - The job is closed
        - A step that cannot be skipped and has not been started or has been cancelled, will not be finished
        - A step cannot be set current if the job is running.
        - A step that has one or more holds will not run nor finish.

        ================    ===================================================================
        **Argument**        **Description**
        ----------------    -------------------------------------------------------------------
        step_ids            Optional list. The job's active step ID or active parallel step IDs.
                            If a step ID isn't provided, the action is performed on the job's current, active step(s).
        ================    ===================================================================

        :return:
            :class:`~arcgis.gis.workflowmanager.JobExecution`

        .. code-block:: python

            # USAGE EXAMPLE: Stop the current active steps

            # create a WorkflowManager object from the workflow item
            wm = WorkflowManager(wf_item)

            job = wm.jobs.get('job_id')

            # Will stop the current active steps, if no param is given
            stop_execution = job.stop()

            print(f'Result = { stop_execution.result() }')
            print(f'Status = { stop_execution.status }')
            print(f'Elapsed Time = { stop_execution.elapse_time }')
            print(f'Messages: ')
            for m in stop_execution.messages:
                print(m.message)

        """
        return self._execute_step(step_ids, execution_type=ExecutionType.STOP)

    def finish(self, step_ids: Optional[list] = None):
        """
        Finishes the current step(s).

        The step will not be finished under the following conditions:

        - Not assigned to the current user
        - No active step is defined
        - The job is closed
        - A step that cannot be skipped and has not been started or has been cancelled, will not be finished
        - A step cannot be set current if the job is running.
        - A step that has one or more holds will not run nor finish.

        ================    ===================================================================
        **Argument**        **Description**
        ----------------    -------------------------------------------------------------------
        step_ids            Optional list. The job's active step ID or active parallel step IDs.
                            If a step ID isn't provided, the action is performed on the job's current, active step(s).
        ================    ===================================================================

        :return:
            :class:`~arcgis.gis.workflowmanager.JobExecution`

        .. code-block:: python

            # USAGE EXAMPLE: Finish the current active steps

            # create a WorkflowManager object from the workflow item
            wm = WorkflowManager(wf_item)

            job = wm.jobs.get('job_id')

            # Will finish the current active steps, if no param is given
            finish_execution = job.finish()

            print(f'Result = { finish_execution.result() }')
            print(f'Status = { finish_execution.status }')
            print(f'Elapsed Time = { finish_execution.elapse_time }')
            print(f'Messages: ')
            for m in finish_execution.messages:
                print(m.message)

        """
        return self._execute_step(step_ids, execution_type=ExecutionType.FINISH)


class JobExecution:
    """
    Represents a single step executing in a workflow manager job.  The `JobExecution` class allows for the asynchronous
    operation of an executing step. The status of the step execution can then be queried by the class properties,
    status, result, elapse_time and messages. This class is not intended for users to call directly.

    See :attr:`~arcgis.gis.workflowmanager.Job.run`, :attr:`~arcgis.gis.workflowmanager.Job.stop` or
    :attr:`~arcgis.gis.workflowmanager.Job.finish` for examples.

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    job                 Required :class:`~arcgis.gis.workflowmanager.Job` The job to execute
    ---------------     --------------------------------------------------------------------
    execution_type      Required :class:`~arcgis.gis.workflowmanager.ExecutionType`. The execution type
    ===============     ====================================================================

    """

    _start_time = None
    _end_time = None
    _execution_type = None

    def __init__(self, job: Job, execution_type: ExecutionType):
        self._job = job
        self._messages = []
        self._event = threading.Event()
        self._execution_type = execution_type

    def _callback(self, msg: Notification, nm: NotificationManager):
        if (
            "jobId" in msg.message
            and msg.message["jobId"] == self._job.job_id
            and msg.msg_type not in [MessageType.JOB_STATE, MessageType.CREATED]
        ):
            logger.debug(f"Received {msg}")
            self._messages.append(msg)
            if self._execution_type is ExecutionType.RUN:
                if msg.msg_type in [
                    MessageType.STEP_FINISHED,
                    MessageType.STEP_STOPPED,
                    MessageType.STEP_ERROR,
                    MessageType.STEP_INFO_REQUIRED,
                ]:
                    self._end_time = datetime.datetime.now()
                    self._event.set()
                    nm._disconnect_check(self._job.job_id)
            elif self._execution_type is ExecutionType.STOP:
                if msg.msg_type in [
                    MessageType.STEP_PAUSED,
                    MessageType.STEP_STOPPED,
                    MessageType.STEP_ERROR,
                    MessageType.STEP_CANCELLED,
                ]:
                    self._end_time = datetime.datetime.now()
                    self._event.set()
                    nm._disconnect_check(self._job.job_id)
            elif self._execution_type is ExecutionType.FINISH:
                if msg.msg_type in [
                    MessageType.STEP_STARTED,
                    MessageType.STEP_ERROR,
                    MessageType.STEP_FINISHED,
                ]:
                    self._end_time = datetime.datetime.now()
                    self._event.set()
                    nm._disconnect_check(self._job.job_id)

    def _started(self):
        self._start_time = datetime.datetime.now()

    @property
    def messages(self):
        """
        Gets the messages collected during execution

        :return:
            List of :class:`~arcgis.gis.workflowmanager.Notification`

        """
        return self._messages

    @property
    def status(self):
        """
        Returns the execution status

        :return:
            string

        """
        return (
            ExecutionStatus.COMPLETE
            if self._event.is_set()
            else ExecutionStatus.RUNNING
        )

    def result(self, timeout: Optional[int] = 300):
        """
        Returns the last :class:`~arcgis.gis.workflowmanager.Notification` message received at the end of the execution

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        timeout             Optional integer. The timeout argument specifies a timeout for the operation in seconds.
        ===============     ====================================================================

        :return:
            string

        """
        if self._event.wait(timeout):
            return self._messages[-1]

        raise TimeoutError("Timeout waiting for result")

    @property
    def elapse_time(self):
        """
        Get the amount of time that passed while the
        :class:`~arcgis.gis.workflowmanager.JobExecution` ran.
        """
        if self._end_time:
            return self._end_time - self._start_time

        return datetime.datetime.now() - self._start_time

    def running(self):
        """
        Returns a boolean indicating whether the execution is running.

        :return:
            boolean

        """
        return self._start_time and not self._event.is_set()

    def done(self):
        """
        Returns a boolean indicating whether the execution is done.

        :return:
            boolean

        """
        return not self.running()

    def __repr__(self):
        return f'JobExecution({{"job": {self._job.job_id},  "status": {ExecutionStatus.RUNNING if self.running() else ExecutionStatus.COMPLETE}}}'


class WMRole(object):
    """
    Represents a Workflow Manager Role object with accompanying GET, POST, and DELETE methods

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    init_data           data object representing relevant parameters for GET or POST calls
    ===============     ====================================================================
    """

    _camelCase_to_underscore = _camelCase_to_underscore
    _underscore_to_camelcase = _underscore_to_camelcase

    def __init__(self, init_data):
        self.privileges = self.roleName = self.description = None
        for key in init_data:
            setattr(self, _camelCase_to_underscore(key), init_data[key])

    def get(self, gis, url, params):
        role_dict = gis._con.get(url, params)
        return WMRole(role_dict)

    def post(self, gis, url):
        post_dict = {
            _underscore_to_camelcase(k): v
            for k, v in self.__dict__.items()
            if v is not None
        }
        return_obj = json.loads(
            gis._con.post(
                url,
                post_dict,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj


class JobTemplate(object):
    """
    Represents a Workflow Manager Job Template object with accompanying GET, POST, and DELETE methods

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    init_data           data object representing relevant parameters for GET or POST calls
    ===============     ====================================================================
    """

    _camelCase_to_underscore = _camelCase_to_underscore
    _underscore_to_camelcase = _underscore_to_camelcase

    def __init__(self, init_data, gis=None, url=None):
        for key in init_data:
            setattr(self, _camelCase_to_underscore(key), init_data[key])
        self._gis = gis
        self._url = url

    def __getattr__(self, item):
        possible_fields = [
            "default_assigned_to",
            "last_updated_by",
            "diagram_id",
            "extended_property_table_definitions",
            "description",
            "job_template_name",
            "job_template_id",
            "default_start_date",
            "default_priority_name",
            "last_updated_date",
            "job_start_date_type",
            "diagram_name",
            "default_job_duration",
            "default_due_date",
            "state",
            "category",
            "default_assigned_type",
            "default_description",
        ]
        gis = object.__getattribute__(self, "_gis")
        url = object.__getattribute__(self, "_url")
        id = object.__getattribute__(self, "job_template_id")
        full_object = gis._con.get(url, {})
        try:
            setattr(self, _camelCase_to_underscore(item), full_object[item])
            return full_object[item]
        except KeyError:
            if item in possible_fields:
                setattr(self, _camelCase_to_underscore(item), None)
                return None
            else:
                raise KeyError(f'The attribute "{item}" is invalid for Job Templates')

    def get(self, gis, url, params):
        job_template_dict = gis._con.get(url, params)
        return JobTemplate(job_template_dict, gis, url)

    def put(self, gis, url):
        put_dict = {
            _underscore_to_camelcase(k): v
            for k, v in self.__dict__.items()
            if v is not None
        }
        return_obj = json.loads(
            gis._con.put(
                url,
                put_dict,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def post(self, gis, url):
        post_dict = {
            _underscore_to_camelcase(k): v
            for k, v in self.__dict__.items()
            if v is not None
        }
        return_obj = json.loads(
            gis._con.post(
                url,
                post_dict,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj["jobTemplateId"]

    def delete(self, gis, url):
        return_obj = json.loads(gis._con.delete(url, try_json=False))
        if "error" in return_obj:
            gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def share(self, group_ids):
        """
        Shares a job template with the list of groups

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        group_ids           Required list. List of Workflow Group Ids
        ===============     ====================================================================

        :return:
            boolean
        """
        try:
            url = "{base}/shareWith".format(
                base=self._url,
                templateId=self.job_template_id,
            )
            post_dict = {"groupIds": group_ids}

            return_obj = json.loads(
                self._gis._con.post(
                    url,
                    post_dict,
                    post_json=True,
                    try_json=False,
                    json_encode=False,
                )
            )

            if "error" in return_obj:
                self._gis._con._handle_json_error(return_obj["error"], 0)
            elif "success" in return_obj:
                return return_obj["success"]
        except:
            self._handle_error(sys.exc_info())

    @property
    def share_details(self):
        """
        Returns the list of groups that the job_template is shared with by template_id.

        :return:
            list of :class:`~arcgis.gis.workflowmanager.Group` ID

        """

        url = "{base}/shareWith".format(base=self._url, templateId=self.job_template_id)
        return_obj = self._gis._con.get(url)

        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj["groupIds"]

    @property
    def automated_creations(self):
        """
        Retrieve the list of created automations for a job template, including scheduled job creation and webhook.

        :return:
            list of automatedCreations associated with the JobTemplate

        """
        try:
            return_obj = self._gis._con.get(
                "{base}/automatedCreation".format(
                    base=self._url, jobTemplateId=self.job_template_id
                ),
                params={},
            )
            return return_obj["automations"]
        except:
            self._handle_error(sys.exc_info())

    def automated_creation(self, automation_id):
        """
        Returns the specified automated creation

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        automation_id       Required string. Automation Creation Id
        ===============     ====================================================================

        :return:
            automated creation object.

        """
        try:
            return_obj = self._gis._con.get(
                "{base}/automatedCreation/{automationId}".format(
                    base=self._url,
                    jobTemplateId=self.job_template_id,
                    automationId=automation_id,
                ),
                params={},
            )
            return return_obj
        except:
            self._handle_error(sys.exc_info())

    def update_automated_creation(self, adds=None, updates=None, deletes=None):
        """
        Creates an automated creation

        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        adds                Optional List. The list of automated creations to create.
        ---------------     --------------------------------------------------------------------
        updates             Optional List. The list of automated creations to update
        ---------------     --------------------------------------------------------------------
        deletes             Optional List. The list of automated creation ids to delete
        ===============     ====================================================================

        :return:
            success object

        .. code-block:: python

            # USAGE EXAMPLE: Creating an automated creation for a job template

            # create a WorkflowManager object from the workflow item
            wm = WorkflowManager(wf_item)

            # create the props object with the required automation properties
            adds = [{
                        "automationName": "auto_mation",
                        "automationType": "Scheduled",
                        "enabled": True,
                        "details": "{\"timeType\":\"NumberOfDays\",\"dayOfMonth\":1,\"hour\":8,\"minutes\":0}"
                    }]
            updates = [
                    {
                      "automationId": "abc123",
                      "automationName": "automation_updated"
                    }
                  ]
            deletes =  ["def456"]

            wm.update_automated_creation(adds, updates, deletes)
            >> True  # returns true if created successfully

        """
        if adds is None:
            adds = []
        if deletes is None:
            deletes = []
        if updates is None:
            updates = []

        props = {"adds": adds, "updates": updates, "deletes": deletes}
        url = "{base}/automatedCreation".format(
            base=self._url, jobTemplateId=self.job_template_id
        )

        return_obj = json.loads(
            self._gis._con.post(
                url,
                props,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            self._gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return return_obj


class Group(object):
    """
    Represents a Workflow Manager Group object with accompanying GET, POST, and DELETE methods

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    init_data           data object representing relevant parameters for GET or POST calls
    ===============     ====================================================================
    """

    _camelCase_to_underscore = _camelCase_to_underscore

    def __init__(self, init_data):
        self.roles = None
        for key in init_data:
            setattr(self, _camelCase_to_underscore(key), init_data[key])

    def get(self, gis, url, params):
        group_dict = gis._con.get(url, params)
        return Group(group_dict)


class JobDiagram(object):
    """
    Helper class for managing Workflow Manager :class:`job diagrams <arcgis.gis.workflowmanager.JobDiagram>`
    in a workflow :class:`item <arcgis.gis.Item>`. This class is not created directly. An instance
    can be created by calling the :attr:`~arcgis.gis.workflowmanager.WorkflowManager.diagrams` property
    of the :class:`~arcgis.gis.workflowmanager.WorkflowManager` to retrieve a list of diagrams. Then
    the :meth:`~arcgis.gis.workflowmanager.WorkflowManager.diagram` method can be used with the appropriate
    ID of the diagram to retrieve the :class:`job diagram <arcgis.gis.workflowmanager.JobDiagram>`.

    """

    _camelCase_to_underscore = _camelCase_to_underscore
    _underscore_to_camelcase = _underscore_to_camelcase

    def __init__(self, init_data, gis=None, url=None):
        for key in init_data:
            setattr(self, _camelCase_to_underscore(key), init_data[key])
        self._gis = gis
        self._url = url

    def __getattr__(self, item):
        possible_fields = [
            "display_grid",
            "diagram_version",
            "diagram_name",
            "diagram_id",
            "description",
            "annotations",
            "initial_step_id",
            "data_sources",
            "steps",
            "initial_step_name",
        ]
        gis = object.__getattribute__(self, "_gis")
        url = object.__getattribute__(self, "_url")
        id = object.__getattribute__(self, "diagram_id")
        full_object = gis._con.get(url, {})
        try:
            setattr(self, _camelCase_to_underscore(item), full_object[item])
            return full_object[item]
        except KeyError:
            if item in possible_fields:
                setattr(self, _camelCase_to_underscore(item), None)
                return None
            else:
                raise KeyError(f'The attribute "{item}" is invalid for Diagrams')

    def get(self, gis, url, params):
        job_diagram_dict = gis._con.get(url, params)
        return JobDiagram(job_diagram_dict, gis, url)

    def post(self, gis, url):
        post_dict = {
            _underscore_to_camelcase(k): v
            for k, v in self.__dict__.items()
            if v is not None
        }
        return_obj = json.loads(
            gis._con.post(
                url,
                post_dict,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def update(self, gis, url, delete_draft):
        clean_dict = {
            _underscore_to_camelcase(k): v
            for k, v in self.__dict__.items()
            if v is not None
        }
        post_object = {"deleteDraft": delete_draft, "diagram": clean_dict}
        return_obj = json.loads(
            gis._con.post(
                url,
                post_object,
                post_json=True,
                try_json=False,
                json_encode=False,
            )
        )
        if "error" in return_obj:
            gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj

    def delete(self, gis, url):
        return_obj = json.loads(gis._con.delete(url, try_json=False))
        if "error" in return_obj:
            gis._con._handle_json_error(return_obj["error"], 0)
        elif "success" in return_obj:
            return return_obj["success"]
        return_obj = {
            _camelCase_to_underscore(k): v
            for k, v in return_obj.items()
            if v is not None and not k.startswith("_")
        }
        return return_obj


class JobLocation(object):
    """
    Represents a Workflow Manager Job Location object with accompanying GET, POST, and DELETE methods

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    init_data           Required object. Represents. relevant parameters for GET or POST calls
    ===============     ====================================================================
    """

    _camelCase_to_underscore = _camelCase_to_underscore

    def __init__(self, init_data):
        self.geometry = self.geometry_type = None
        for key in init_data:
            setattr(self, _camelCase_to_underscore(key), init_data[key])

    def get(self, gis, url, params):
        job_location_dict = gis._con.get(url, params)
        return JobLocation(job_location_dict)


class NotificationManager:
    """
    Represents a helper class for workflow manager websocket notifications. Accessible as the
    :attr:`~arcgis.gis.workflowmanager.WorkflowManager.notifications` property of the
    :class:`~arcgis.gis.workflowmanager.WorkflowManager`.

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    item                The Workflow Manager Item
    ===============     ====================================================================

    """

    def __init__(self, item: arcgis.gis.Item, workflow_manager: WorkflowManager):
        self._item = item
        _initialize(self, item._gis)
        self.workflow_item_id = item.id
        self.websocket_connection = None
        self.subscribed_jobs = {}
        self._workflow_manager = workflow_manager
        self._connected = False
        self._manually_connected = False
        self._server_url = self._workflow_manager._server_url
        self._received_connected_msg = None
        self._timeout = 30
        self._subscription_lock = threading.RLock()

        # need baseAddress/ server address, orgid, and workflow item id
        base = self._server_url.replace("http://", "ws://").replace(
            "https://", "wss://"
        )
        item_url = f"{self.org_id}/{self.workflow_item_id}"
        self.websocket_url = f"{base}/{item_url}/notificationWs"
        self.token_request_url = f"{self._server_url}/{item_url}"

    def _disconnect_check(self, job_id):
        with self._subscription_lock:
            if job_id in self.subscribed_jobs:
                self.unsubscribe([job_id])
                # If this list is empty, all job executions have terminated, can disconnect.
                logger.debug(
                    f"Jobs: {self.subscribed_jobs}. Manually connected: {self._manually_connected}"
                )
                if not self.subscribed_jobs and not self._manually_connected:
                    self.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _subscriber(self, message):
        try:
            message_dict = json.loads(message)

            # ensure we are connected via setting an event before subscribing
            if message_dict.get("connected"):
                self._received_connected_msg.set()

            if "msgType" in message_dict:
                msg = Notification(message_dict)

                if "jobId" in msg.message:
                    job_id = msg.message["jobId"]
                    if job_id in self.subscribed_jobs.keys():
                        callback = self.subscribed_jobs[job_id]
                        callback(msg, self)
        except:
            logger.exception(f"Error with messages and callbacks")

    def _connect(self) -> WebsocketConnection:
        ws = WebsocketConnection(self._subscriber, self._gis, self._timeout)
        self._received_connected_msg = threading.Event()
        ws.connect(
            self.websocket_url,
            self.token_request_url,
        )
        self._received_connected_msg.wait(self._timeout)
        self._connected = True
        return ws

    def connect(self):
        """
        Establishes a websocket connection to the workflow manager server.

        .. code-block:: python
            # USAGE EXAMPLE: Manage websocket connection manually

            # create a WorkflowManager object from the workflow item
            wf_item = gis.content.get('d6e25f2db0514520b32d6e65e7ad49a0')
            wm = WorkflowManager(wf_item)

            nm = NotificationManager(wf_item, wm)

            with nm.connect() as connection:
                # subscribe, unsubscribe, manage jobs etc
                nm.subscribe([job_id])

        """
        if not self.websocket_connection:
            logger.debug(f"Creating websocket connection to {self.websocket_url}")
            self.websocket_connection = self._connect()
            self._manually_connected = True

    def disconnect(self):
        """
        Removes and disconnects the websocket connection to the workflow manager server.
        """
        if self.websocket_connection:
            self.websocket_connection.disconnect()
            self.websocket_connection = None
            self._connected = False
            self._manually_connected = False

    def subscribe(self, job_ids: list, callback: Callable[[Notification], None]):
        """
        Subscribes to the notifications provided job ids. Register a callback for the specified jobId when subscribing to a job.
        Whenever messages containing the specified jobId are received, the callback will be invoked with the contents
        of the job notification message.

        Refer to the WebSocket Message API for the list of subscribed job messages. (https://developers.arcgis.com/workflow-manager/api-reference/web-sockets/)
        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        job_ids             Required list. The list of job ids to subscribe to.
        ---------------     --------------------------------------------------------------------
        callback            Required Callable. A Callable function that takes one parameter of type
                            :class:`~arcgis.gis.workflowmanager.Notification`
        ===============     ====================================================================

        :return:
            Workflow Manager :class:`Role <arcgis.gis.workflowmanager.WMRole>` Object

        """
        try:
            with self._subscription_lock:
                ids = job_ids
                if self.websocket_connection is None:
                    logger.debug(
                        f"Creating temporary websocket connection to {self.websocket_url}"
                    )
                    self.websocket_connection = self._connect()
                    subscribe_obj = {
                        "msgType": "subscribe",
                        "jobIds": ids,
                        "token": self.websocket_connection.get_token(
                            self.token_request_url
                        ),
                    }

                    self.websocket_connection.send_and_wait(json.dumps(subscribe_obj))
                else:
                    ids = [i for i in job_ids if i not in self.subscribed_jobs.keys()]
                    subscribe_obj = {
                        "msgType": "subscribe",
                        "jobIds": ids,
                        "token": self.websocket_connection.get_token(
                            self.token_request_url
                        ),
                    }
                    if len(ids) > 0:
                        self.websocket_connection.send_and_wait(
                            json.dumps(subscribe_obj)
                        )
                    else:
                        # check if the new ids are already subscribed to, so we set the callback correctly.
                        ids = [i for i in job_ids if i in self.subscribed_jobs.keys()]

                for jid in ids:
                    self.subscribed_jobs[jid] = callback
        except:
            logger.exception(f"Error when trying to subscribe")

    def unsubscribe(self, job_ids: list):
        """
        Unsubscribes to the notifications for provided job ids. Removes the callback for the corresponding callbackId.
        If no callbacks remain for a particular jobId, an unsubscribe message will be sent to Workflow Manager
        Server for that particular jobId.

        Refer to the WebSocket Message API for the list of subscribed job messages. (https://developers.arcgis.com/workflow-manager/api-reference/web-sockets/)
        ===============     ====================================================================
        **Parameter**        **Description**
        ---------------     --------------------------------------------------------------------
        job_ids             Required list. The list of job ids to subscribe to
        ===============     ====================================================================

        :return:
            Workflow Manager :class:`Role <arcgis.gis.workflowmanager.WMRole>` Object

        """
        try:
            with self._subscription_lock:
                if self.websocket_connection is not None:
                    unsubscribe_obj = {
                        "msgType": "unsubscribe",
                        "jobIds": job_ids,
                        "token": self.websocket_connection.get_token(
                            self.token_request_url
                        ),
                    }
                    self.websocket_connection.send(json.dumps(unsubscribe_obj))

                    for jid in job_ids:
                        self.subscribed_jobs.pop(jid)
        except:
            logger.exception(f"Error when trying to unsubscribe")


class Notification:
    """
    Represents a Workflow Manager Notification object. The Notification contains the
    :class:`~arcgis.gis.workflowmanager.MessageType`, the message object and the timestamp the notification was received

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    init_data           data object representing relevant properties of a notification
    ===============     ====================================================================

    .. code-block:: python

        # USAGE EXAMPLE: Print Notification Properties

        # create a WorkflowManager object from the workflow item
        wm = WorkflowManager(wf_item)

        job = wm.jobs.get('job_id')
        run_execution = job.run(step_ids=['stepid'])

        print(f'Result = { run_execution.result() }')
        print(f'Messages:')
        for m in run_execution.messages:
            print(m.msg_type)
            print(m.message)
            print(m.timestamp)
    """

    def __init__(self, init_data):
        self.message = init_data["message"]
        self.timestamp = init_data["timestamp"]
        self.msg_type = MessageType(init_data["msgType"].upper())

    def __repr__(self):
        return f'Notification({{"timestamp": "{self.timestamp}", "msgType": "{self.msg_type}", "message": "{self.message}"}})'


class MessageType(Enum):
    """
    The Workflow Manager Message Types

    This enum class represents the list of all possible message types when sending or receiving messages.
    """

    CREATED = "CREATED"
    ERROR = "ERROR"
    JOB_STATE = "JOBSTATE"
    JOB_UPDATED = "JOBUPDATED"
    JOB_COMMENT_UPDATED = "JOBCOMMENTUPDATED"
    JOB_ATTACHMENT_UPDATED = "JOBATTACHMENTUPDATED"
    JOB_LOCATION_UPDATED = "JOBLOCATIONUPDATED"
    STEP_STARTED = "STEPSTARTED"
    STEP_PROGRESS = "STEPPROGRESS"
    STEP_CANCELLED = "STEPCANCELLED"
    STEP_PAUSED = "STEPPAUSED"
    STEP_STOPPING = "STEPSTOPPING"
    STEP_STOPPED = "STEPSTOPPED"
    STEP_WARNING_STOPPED = "STEPWARNINGSTOPPED"
    STEP_FINISHED = "STEPFINISHED"
    STEP_REASSIGNED = "STEPREASSIGNED"
    STEP_HELD = "STEPHELD"
    STEP_HOLD_RELEASED = "STEPHOLDRELEASED"
    STEP_ERROR = "STEPERROR"
    STEP_INFO_REQUIRED = "STEPINFOREQUIRED"
    STEP_INFORMATION = "STEPINFORMATION"


class ExecutionType(Enum):
    """
    The Workflow Manager Execution Types

    This enum class represents the possible step execution types to be run with websocket messaging.
    """

    RUN = "RUN"
    STOP = "STOP"
    FINISH = "FINISH"


class ExecutionStatus(Enum):
    """
    The Workflow Manager Execution Statuses

    This enum class represents the possible step execution statuses.
    """

    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
