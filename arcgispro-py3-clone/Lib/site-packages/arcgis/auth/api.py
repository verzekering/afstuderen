from __future__ import annotations
from contextlib import contextmanager
import os
import sys
import logging
from typing import Dict, Any, Tuple
import requests

from requests.sessions import Session
from urllib3 import Retry
from ._auth import (
    EsriPKIAuth,
    EsriWindowsAuth,
    EsriKerberosAuth,
)
from ._auth._winauth import HAS_KERBEROS
from ._auth._negotiate import HAS_GSSAPI
from ._version import __version__
from .tools import EsriTrustStoreAdapter
from .tools._lazy import LazyLoader

__USERAGENT__ = f"Geosaurus/{__version__}"
__log__ = logging.getLogger()


def _is_cert_files(certs: tuple) -> bool:
    """checks if the tuple is all files"""
    checks: list[bool] = []
    for fp in certs:
        try:
            checks.append(os.path.isfile(fp))
        except:
            checks.append(False)
    return all(checks)


###########################################################################
class EsriSession:
    """
    The `EsriSession` class is designed to simplify access to the Esri WebGIS
    environments without the additional components of the `arcgis` or `arcpy`
    modules.  It is designed to allow users to connect and manage all HTTP calls
    themselves with no hand holding.

    Security is handled through the `requests` authentication model. Leveraging
    authentication handlers and primarily connecting to 10.8.1+ enterprise components.

    The supported Authentication Schemes are:

        1. Username/Password
        2. Oauth 2
        3. IWA/NTLM
        4. Basic
        5. Digest
        6. PKI
        7. API Keys
        8. User Provided Tokens
        9. Kerberos

    Anyone can extend the authentication handlers by creating a class and inheriting
    from `requests.auth.AuthBase`.

    The `EsriSession` authentication supports authentication chaining.  Meaning
    users can stack authentication methods.

        `auth1 + auth2 + auth3`

    It is recommended that you do not stack unneeded authenticators because they
    can caused unintended failures.

    ==================     ====================================================================
    **Parameter**           **Description**
    ------------------     --------------------------------------------------------------------
    auth                   Optional AuthBase. This is a security handler that performs some sort
                           of security check.
    ------------------     --------------------------------------------------------------------
    cert                   Optional Tuple. The client side certificate as a tuple or string. It
                           should be noted that `EsriSession` does not support encrypted private
                           keys.
    ------------------     --------------------------------------------------------------------
    verify_cert            Optional Bool. When `False` all SSL certificate errors are ignored.
                           The default is `True`.
    ------------------     --------------------------------------------------------------------
    allow_redirects        Optional Bool. When `False` if the URL redirects a user, an error
                           will be raised.  The default is `True`
    ------------------     --------------------------------------------------------------------
    headers                Optional Dict. An additional set of key/value(s) to append to any
                           request's header.
    ------------------     --------------------------------------------------------------------
    referer                Optional Str. The `referer` header value.  The default is `http`. This
                           is mainly used with `token` security.
    ==================     ====================================================================


    **Optional Arguments**

    ==================     ====================================================================
    **Parameter**           **Description**
    ------------------     --------------------------------------------------------------------
    trust_env              Optional Bool. The default is `True`. If `False` proxies will cause
                           an error to be raised if set by **.netrc** files.
    ------------------     --------------------------------------------------------------------
    stream                 Optional Bool.  To enable handling streaming responses, set stream to
                           True and iterate over the response with `iter_lines`. The default is
                           `False`.
    ------------------     --------------------------------------------------------------------
    check_hostname         Optional Bool. When connecting to a side via IP Address with an SSL
                           certificate, the hostname will not match.  This allows a user to
                           specify the hostname in the headers parameters and ignore hostname
                           errors.
    ------------------     --------------------------------------------------------------------
    retries                Optional Int. The max number of tries to retry a service for 50x errors.
    ------------------     --------------------------------------------------------------------
    backoff_factor         Optional float. The amount of time in seconds to wait between retries.
    ------------------     --------------------------------------------------------------------
    status_to_retry        Optional Tuple. The status codes to run retries on.  The default is
                           (413, 429, 503, 500, 502, 504).
    ------------------     --------------------------------------------------------------------
    method_whitelist       Optional List.  When `retries` is specified, the user can specify what methods are retried.
                           The default is `'POST', 'DELETE', 'GET', 'HEAD', 'OPTIONS', 'PUT', 'TRACE'`
    ------------------     --------------------------------------------------------------------
    proxies                Optional Dict. A key/value mapping where the keys are the transfer protocol and the value is the <url>:<port>.

                           **example**

                           ```python
                           proxies = {"http" : 127.0.0.1:8080, "https" : 127.0.0.1:8081}
                           session = EsriSession(proxies=proxies)
                           ```

    ==================     ====================================================================


    """

    _session: Session | None = None
    _verify: bool | None = None
    _baseurl: str | None = None  # if partial url given, try the base url
    _referer: str | None = None
    _cert: tuple[str] | None = None
    _useragent: str | None = None
    _retry: Retry | None = None

    # ----------------------------------------------------------------------
    def __init__(
        self,
        auth: requests.auth.AuthBase | None = None,
        verify_cert: bool = True,
        cert: tuple[str, str] | None = None,
        headers: Dict[str, Any] = None,
        referer: str | None = "http",
        trust_env: bool | None = None,
        assert_hostname: bool = True,
        **kwargs,
    ) -> "EsriSession":
        super()
        verify: bool = verify_cert
        if not verify is None and not isinstance(verify, bool):
            raise ValueError(
                "`verify only accepts a boolean.  If you want to pass a CA bundle, please use ca_bundle`"
            )
        self._session: Session = Session()
        self._session.verify = verify
        if not auth is None:
            self.auth = auth
        if cert is None:
            self._x509_cert, self._x509_pw = None, None
        elif cert and len(cert) == 2 and _is_cert_files(certs=cert):
            self._x509_cert, self._x509_pw = cert, None
        elif cert and len(cert) == 2:
            self._x509_cert, self._x509_pw = cert[0], cert[1]
        else:
            raise ValueError(
                "Parameter `cert` must either be a tuple of size 2 where the "
                "first value is a pfx certificate and the second a password, or None."
            )

        self.assert_hostname = assert_hostname

        if referer is None:
            referer: str = ""
        if referer or referer == "":
            self.update_headers(
                {
                    "referer": referer,
                }
            )
        if self._useragent is None:
            self._useragent: str = __USERAGENT__
            self.update_headers({"User-Agent": self._useragent})

        if isinstance(headers, dict):
            self.update_headers(headers)

        self._session.stream: bool = kwargs.pop("stream", False)
        self.timeout: int | float = kwargs.pop("timeout", 10)
        self.proxies: dict | None = kwargs.get("proxies", None)
        self.allow_redirects: bool = kwargs.get("allow_redirects", True)

        self._ca_bundles: list[str] | str | None = kwargs.pop("ca_bundles", None)
        if isinstance(self._ca_bundles, str):
            self._ca_bundles: list[str] = [self._ca_bundles]

        if not "referer" in self._session.headers:
            self._session.headers["referer"] = self._referer

        self._retry: Retry = Retry(
            total=kwargs.get("retries", 5),
            read=kwargs.get("retries", 5),
            connect=kwargs.get("retries", 5),
            status_forcelist=kwargs.get(
                "status_to_retry", (413, 429, 503, 500, 502, 504)
            ),
            allowed_methods=kwargs.get(
                "method_whitelist",
                frozenset(
                    [
                        "POST",
                        "DELETE",
                        "GET",
                        "HEAD",
                        "OPTIONS",
                        "PUT",
                        "TRACE",
                    ]
                ),
            ),
        )

        self._adapter: EsriTrustStoreAdapter = EsriTrustStoreAdapter(
            max_retries=self._retry,
            assert_hostname=self.assert_hostname,
            verify=verify,
            additional_certs=self._ca_bundles,
            pki_data=self._x509_cert,
            pki_password=self._x509_pw,
        )
        self.verify = verify
        self._session.mount("http://", self._adapter)
        self._session.mount("https://", self._adapter)
        self.auth = auth

        if auth is None:
            if cert and len(cert) > 1:
                self._session.auth = EsriPKIAuth(session=self)
            elif (
                sys.platform == "win32" and HAS_GSSAPI
            ):  # Default Case Load IWA/WinAuth
                self._session.auth = EsriWindowsAuth(
                    referer=referer,
                    session=self,
                )
            elif HAS_KERBEROS:
                self._session.auth = EsriKerberosAuth(
                    referer=self._referer, session=self
                )

    # ----------------------------------------------------------------------
    def close(self):
        """Closes all adapters and as such the session"""
        self._session.close()

    # ----------------------------------------------------------------------
    def __enter__(self) -> "EsriSession":
        return self

    # ----------------------------------------------------------------------
    def __exit__(self, *args):
        self._session.close()

    # ----------------------------------------------------------------------
    @property
    def ca_bundles(self) -> list[str] | str:
        """returns the path to the extra CA bundles"""
        return self._adapter.additional_certs

    # ----------------------------------------------------------------------
    @property
    def trust_env(self) -> bool | None:
        """Trust environment settings for proxy configuration, default authentication and similar."""
        if self._session is None:
            self._session = Session()
        return self._session.trust_env

    # ----------------------------------------------------------------------
    @trust_env.setter
    def trust_env(self, value: bool):
        """Trust environment settings for proxy configuration, default authentication and similar."""
        if self._session is None:
            self._session = Session()
        if self._session.trust_env != value and isinstance(value, bool):
            self._session.trust_env = value
        elif value is None:
            self._session.trust_env = value

    # ----------------------------------------------------------------------
    @property
    def stream(self) -> bool:
        """Gets/Sets the stream property for the current session object"""
        if self._session is None:
            self._session = Session()
        return self._session.stream

    # ----------------------------------------------------------------------
    @stream.setter
    def stream(self, stream: bool):
        """Gets/Sets the stream property for the current session object"""
        if self._session is None:
            self._session = Session()
        if isinstance(stream, bool):
            self._session.stream = stream

    # ----------------------------------------------------------------------
    @property
    def headers(self) -> Dict[str, Any]:
        """Gets/Sets the headers from the current session object"""
        if self._session is None:
            self._session = Session()
        return self._session.headers

    # ----------------------------------------------------------------------
    @headers.setter
    def headers(self, values: Dict[str, Any]):
        """Gets/Sets the headers from the current session object"""
        if self._session is None:
            self._session = Session()
        if isinstance(values, dict):
            from requests.utils import CaseInsensitiveDict

            values = CaseInsensitiveDict(values)
            self._session.headers = values

    # ----------------------------------------------------------------------
    def update_headers(self, values: Dict[str, Any]) -> bool:
        """Performs an update call on the headers"""
        if self._session is None:
            self._session = Session()
        try:
            self._session.headers.update(values)
            return True
        except:
            return False

    # ----------------------------------------------------------------------
    @property
    def referer(self) -> str:
        """Gets/Sets the referer"""
        if self._session is None:
            self._session = Session()
        try:
            return self._session.headers["referer"]
        except:
            return None

    # ----------------------------------------------------------------------
    @referer.setter
    def referer(self, value: str):
        """Gets/Sets the referer"""
        if self._session is None:
            self._session = Session()
        self._session.headers["referer"] = value

    # ----------------------------------------------------------------------
    def __str__(self) -> str:
        return f"<ArcGIS Session {__version__}>"

    # ----------------------------------------------------------------------
    def __repr__(self) -> str:
        return f"<ArcGIS Session {__version__}>"

    # ----------------------------------------------------------------------
    @property
    def verify(self) -> bool | str:
        """
        Get/Set property that allows for the verification of SSL certificates

        :returns: bool
        """
        if self._session is None:
            self._session = Session()
        return self._session.verify

    # ----------------------------------------------------------------------
    @verify.setter
    def verify(self, value: bool):
        if self._session is None:
            self._session = Session()
        if isinstance(value, bool):
            self._session.verify = value
            self._adapter: EsriTrustStoreAdapter = EsriTrustStoreAdapter(
                max_retries=self._retry,
                assert_hostname=self._adapter.assert_hostname,
                verify=value,
                additional_certs=self._adapter.additional_certs,
                pki_data=self._x509_cert,
                pki_password=self._x509_pw,
            )
            self._session.mount("http://", self._adapter)
            self._session.mount("https://", self._adapter)

    # ----------------------------------------------------------------------
    def mount(self, prefix: str, adapter: "HTTPAdapter"):
        """
        Registers a connection adapter to a prefix.

        Adapters are sorted in descending order by prefix length.
        """
        return self._session.mount(prefix, adapter)

    # ----------------------------------------------------------------------
    @property
    def adapters(self) -> Dict[str, str]:
        """
        Returns an dictionary of mounted adapters.

        :return: dict
        """
        return self._session.adapters

    # ----------------------------------------------------------------------
    @property
    def auth(self) -> "AuthBase":
        """Get/Set the Authentication Handler for the Session"""
        return self._session.auth

    # ----------------------------------------------------------------------
    @auth.setter
    def auth(self, value: "AuthBase"):
        """Get/Set the Authentication Handler for the Session"""
        self._session.auth = value

    # ----------------------------------------------------------------------
    @property
    def proxies(self) -> Dict[str, str]:
        """
        Dictionary mapping protocol or protocol and host to the URL of the proxy.
        (e.g. {'http': 'foo.bar:3128', 'http://host.name': 'foo.bar:4012'}) to
        be used on each :class:`Request <Request>`.

        :return: dict
        """
        return self._session.proxies

    # ----------------------------------------------------------------------
    @proxies.setter
    def proxies(self, value: Dict[str, str]) -> None:
        """
        Dictionary mapping protocol or protocol and host to the URL of the proxy.
        (e.g. {'http': 'foo.bar:3128', 'http://host.name': 'foo.bar:4012'}) to
        be used on each :class:`Request <Request>`.

        :return: dict
        """
        if isinstance(value, dict) and self._session.proxies:
            self._session.proxies.update(value)
        elif isinstance(value, dict) and not self._session.proxies:
            self._session.proxies = value
        elif value is None:
            self._session.proxies = {}
        else:
            raise ValueError("Proxy must be of type dictionary.")

    @property
    def cert(self) -> Tuple[str]:
        """
        Get/Set the users certificate as a (private, public) keys.

        :return: Tuple[str]
        """
        return self._cert

    @cert.setter
    def cert(self, cert: tuple[str]):
        """
        Get/Set the users certificate as a (private, public) keys.

        :return: Tuple[str]
        """
        if cert:
            self._cert = cert
            self._x509_cert, self._x509_pw = cert
            self._adapter: EsriTrustStoreAdapter = EsriTrustStoreAdapter(
                max_retries=self._retry,
                assert_hostname=self._adapter.assert_hostname,
                verify=self._adapter.verify,
                additional_certs=self._adapter.additional_certs,
                pki_data=cert[0],
                pki_password=cert[1],
            )

            self.mount("https://", self._adapter)
            self.mount("http://", self._adapter)

    # ----------------------------------------------------------------------
    def get(self, url, **kwargs) -> "requests.Response":
        r"""Sends a GET request. Returns :class:`Response` object.

        :param url: URL for the new :class:`Request` object.
        :param \*\*kwargs: Optional arguments that ``request`` takes.
        :rtype: requests.Response
        """

        kwargs.pop("verify", None)
        if "allow_redirects" in kwargs:
            redirects = kwargs.pop("allow_redirects")
        else:
            redirects = self.allow_redirects
        if "proxies" in kwargs:
            proxies = kwargs.pop("proxies")
        else:
            proxies = self.proxies
        with self._handle_drop_auth(drop_auth=kwargs.pop("drop_auth", False)):
            return self._session.get(
                url, allow_redirects=redirects, proxies=proxies, **kwargs
            )

    # ----------------------------------------------------------------------
    def options(self, url, **kwargs) -> "requests.Response":
        r"""Sends a OPTIONS request. Returns :class:`Response` object.

        :param url: URL for the new :class:`Request` object.
        :param \*\*kwargs: Optional arguments that ``request`` takes.
        :rtype: requests.Response
        """
        kwargs.pop("verify", None)
        if "proxies" in kwargs:
            proxies = kwargs.pop("proxies")
        else:
            proxies = self.proxies
        with self._handle_drop_auth(drop_auth=kwargs.pop("drop_auth", False)):
            return self._session.options(url, proxies=proxies, **kwargs)

    # ----------------------------------------------------------------------
    def head(self, url, **kwargs) -> "requests.Response":
        r"""Sends a HEAD request. Returns :class:`Response` object.

        :param url: URL for the new :class:`Request` object.
        :param \*\*kwargs: Optional arguments that ``request`` takes.
        :rtype: requests.Response
        """
        kwargs.pop("verify", None)
        if "proxies" in kwargs:
            proxies = kwargs.pop("proxies")
        else:
            proxies = self.proxies
        with self._handle_drop_auth(drop_auth=kwargs.pop("drop_auth", False)):
            return self._session.head(url, proxies=proxies, **kwargs)

    # ----------------------------------------------------------------------
    def post(self, url, data=None, json=None, **kwargs) -> "requests.Response":
        r"""Sends a POST request. Returns :class:`Response` object.

        :param url: URL for the new :class:`Request` object.
        :param data: (optional) Dictionary, list of tuples, bytes, or file-like
            object to send in the body of the :class:`Request`.
        :param json: (optional) json to send in the body of the :class:`Request`.
        :param \*\*kwargs: Optional arguments that ``request`` takes.
        :rtype: requests.Response
        """
        kwargs.pop("verify", None)
        if "proxies" in kwargs:
            proxies = kwargs.pop("proxies")
        else:
            proxies = self.proxies
        if "allow_redirects" in kwargs:
            redirects = kwargs.pop("allow_redirects")
        else:
            redirects = self.allow_redirects
        with self._handle_drop_auth(drop_auth=kwargs.pop("drop_auth", False)):
            return self._session.post(
                url,
                data=data,
                json=json,
                allow_redirects=redirects,
                proxies=proxies,
                **kwargs,
            )

    # ----------------------------------------------------------------------
    def put(self, url, data=None, **kwargs) -> "requests.Response":
        r"""Sends a PUT request. Returns :class:`Response` object.

        :param url: URL for the new :class:`Request` object.
        :param data: (optional) Dictionary, list of tuples, bytes, or file-like
            object to send in the body of the :class:`Request`.
        :param \*\*kwargs: Optional arguments that ``request`` takes.
        :rtype: requests.Response
        """
        kwargs.pop("verify", None)
        if "proxies" in kwargs:
            proxies = kwargs.pop("proxies")
        else:
            proxies = self.proxies
        with self._handle_drop_auth(drop_auth=kwargs.pop("drop_auth", False)):
            return self._session.put(url, data=data, proxies=proxies, **kwargs)

    # ----------------------------------------------------------------------
    def patch(self, url, data=None, **kwargs) -> "requests.Response":
        r"""Sends a PATCH request. Returns :class:`Response` object.

        :param url: URL for the new :class:`Request` object.
        :param data: (optional) Dictionary, list of tuples, bytes, or file-like
            object to send in the body of the :class:`Request`.
        :param \*\*kwargs: Optional arguments that ``request`` takes.
        :rtype: requests.Response
        """
        kwargs.pop("verify", None)
        if "proxies" in kwargs:
            proxies = kwargs.pop("proxies")
        else:
            proxies = self.proxies
        with self._handle_drop_auth(drop_auth=kwargs.pop("drop_auth", False)):
            return self._session.patch(url, data=data, proxies=proxies, **kwargs)

    # ----------------------------------------------------------------------
    def delete(self, url, **kwargs) -> "requests.Response":
        r"""Sends a DELETE request. Returns :class:`Response` object.

        :param url: URL for the new :class:`Request` object.
        :param \*\*kwargs: Optional arguments that ``request`` takes.
        :rtype: requests.Response
        """
        kwargs.pop("verify", None)
        if "proxies" in kwargs:
            proxies = kwargs.pop("proxies")
        else:
            proxies = self.proxies
        with self._handle_drop_auth(drop_auth=kwargs.pop("drop_auth", False)):
            return self._session.delete(url, proxies=proxies, **kwargs)

    @contextmanager
    def _handle_drop_auth(self, drop_auth: bool):
        """Context manager to handle dropping the auth for requests that must be made anonymously"""
        try:
            session_auth = self._session.auth
            if drop_auth:
                self._session.auth = None
            yield
        finally:
            if drop_auth:
                self._session.auth = session_auth
