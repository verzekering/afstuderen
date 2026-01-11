from arcgis.auth.tools import parse_url
from arcgis.auth.tools._adapter import EsriTrustStoreAdapter
from arcgis.gis import GIS
import logging
from requests.adapters import HTTPAdapter
from ssl import SSLContext
import threading
from typing import Callable
import websocket


logger = logging.getLogger(__name__)


class WebsocketConnection:
    ws: websocket.WebSocketApp = None
    thread: threading.Thread = None
    msgEvent: tuple[str, threading.Event] = None
    msgs = []

    def __init__(
        self,
        subscribe_callback: Callable,
        gis: GIS,
        timeout: int = 30,
    ):
        self._gis = gis
        self._headers = gis.session.headers
        self.subscribe_callback = subscribe_callback
        self.timeout = timeout

    def _get_session_adapter_ssl_context(self):
        ws_scheme = parse_url(self._url).scheme
        if ws_scheme == "ws":
            scheme = "http"
        else:
            scheme = "https"
        adapter = self._gis.session.adapters.get(f"{scheme}://", None)
        if isinstance(adapter, EsriTrustStoreAdapter):
            return adapter.ssl_context
        if isinstance(adapter, HTTPAdapter) and hasattr(adapter, "ssl_context"):
            ssl_context = getattr(adapter, "ssl_context")
            if isinstance(ssl_context, SSLContext):
                return ssl_context
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def __on_message__(self, app, msg):
        logger.debug(f"Received msg {msg}")
        if self.msgEvent:
            self.msgEvent[1].set()
            self.msgs.append(msg)
        else:
            self.msgs.append(msg)
        try:
            self.subscribe_callback(msg)
        except Exception as e:
            logger.error(f"Error when processing a incoming message: {e}")

    def connect(self, url: str, token_request_url: str):
        self._url = url
        context = self._get_session_adapter_ssl_context()
        self.sslopt = {"context": context} if context else None

        _open_event = threading.Event()
        # TODO Header does not work (bug with web adaptors), so use query parameter until that is fixed.
        # Sending all headers from requests also causes issues
        # self.headers["X-Esri-Authorization"] = f"Bearer {token}"
        token = self.get_token(token_request_url)
        cookie = self._get_cookie(token_request_url)
        headers = {"X-Esri-Authorization": f"Bearer {token}"}
        url_with_token = url + "?token=" + token

        def start_websocket():
            self.ws.run_forever(sslopt=self.sslopt)

        def on_open(ws: websocket.WebSocket):
            _open_event.set()
            logger.debug("Connection open event succeeded within timeout window")

        def on_error(ws, err):
            logger.exception(f"Error in websocket handler: {err}")

        logger.debug(url_with_token)
        logger.debug(self._headers)

        self.ws = websocket.WebSocketApp(
            url_with_token,
            on_open=on_open,
            on_message=self.__on_message__,
            on_error=on_error,
            header=headers,
            cookie=cookie,
        )

        self.thread = threading.Thread(target=start_websocket, daemon=True)
        self.thread.start()
        if not _open_event.wait(self.timeout):
            raise TimeoutError(
                f"Timed out waiting for connection open event ({self.timeout} seconds)"
            )

    def send(self, msg):
        self.ws.send(msg)

    def send_and_wait(self, msg):
        logger.debug(f"Sending {msg}")
        self.msgs = []
        self.msgEvent = (msg, threading.Event())
        self.send(msg)
        self.msgEvent[1].wait(self.timeout)
        logger.debug(f"Sent {msg}")
        return self.msgs

    def disconnect(self):
        if not self.ws:
            return
        self.ws.close()
        if not self.thread is threading.current_thread():
            self.thread.join(self.timeout)
        logger.debug(f"Disconnected from {self._url}")

    def get_token(self, token_request_url: str) -> str:
        if self._gis._con.token:
            return self._gis._con.token

        # TODO this is always going to make the request even when the token is cached, but would need to expose more to avoid
        # TODO Can optimize to not get cookies when they're not going to be used
        logger.debug(f"Making request to {token_request_url} to generate token")
        resp = self._gis._session._session.get(f"{token_request_url}")
        logger.debug(
            f"Response headers: {resp.headers}. Request header: {resp.request.headers}"
        )
        _, token = resp.request.headers["X-Esri-Authorization"].split()
        return token

    def _get_cookie(self, url: str) -> str:
        """
        Returns semicolon-delimited cookies for a specified domain by url

        if no cookies match in the session, returns None
        """
        matched_cookies = []
        parsed_url = parse_url(url)
        cookies = self._gis.session._session.cookies
        for d in cookies.list_domains():
            if not parsed_url.hostname.endswith(d):
                continue
            matched_cookies.extend(cookies.get_dict(domain=d).items())

        result = "; ".join([f"{k}={v}" for k, v in matched_cookies])
        # return None if no matching cookies found
        return result or None
