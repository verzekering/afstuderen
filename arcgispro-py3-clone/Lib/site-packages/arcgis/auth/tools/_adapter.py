from __future__ import annotations
from requests.adapters import HTTPAdapter
import os
import ssl
import certifi
import tempfile
import truststore
import cryptography
from requests.utils import get_environ_proxies
from cryptography import x509
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    pkcs12,
    Encoding,
    PrivateFormat,
    NoEncryption,
)

_crypto_version = [
    int(i) if i.isdigit() else i for i in cryptography.__version__.split(".")
]


# ----------------------------------------------------------------------
def pfx_to_pem(pfx_path, pfx_password, folder=None, use_openssl=False):
    """Decrypts the .pfx file to be used with requests.

    ===============     ====================================================================
    **Parameter**        **Description**
    ---------------     --------------------------------------------------------------------
    pfx_path            Required string.  File pathname to .pfx file to parse.
    ---------------     --------------------------------------------------------------------
    pfx_password        Required string.  Password to open .pfx file to extract key/cert.
    ---------------     --------------------------------------------------------------------
    folder              Optional String.  The save location of the certificate files.  The
                        default is the tempfile.gettempdir() directory.
    ---------------     --------------------------------------------------------------------
    user_openssl        Optional Boolean. If True, OpenPySSL is used to convert the pfx to pem instead of cryptography.
    ===============     ====================================================================

    :return: Tuple
       File path to key_file located in a tempfile location
       File path to cert_file located in a tempfile location
    """
    if (
        pfx_path.lower().endswith(".pfx") == False
        and pfx_path.lower().endswith(".p12") == False
    ):
        raise ValueError("`pfx_to_pem` only supports `pfx` and `p12` certificates.")
    if folder is None:
        folder = tempfile.gettempdir()
    elif folder and not os.path.isdir(folder):
        raise Exception("Folder location does not exist.")
    key_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False, dir=folder)
    cert_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False, dir=folder)
    if use_openssl:
        try:
            import OpenSSL.crypto

            k = open(key_file.name, "wb")
            c = open(cert_file.name, "wb")
            try:
                pfx = open(pfx_path, "rb").read()
                p12 = OpenSSL.crypto.load_pkcs12(pfx, pfx_password)
            except OpenSSL.crypto.Error:
                raise RuntimeError("Invalid PFX password.  Unable to parse file.")
            k.write(
                OpenSSL.crypto.dump_privatekey(
                    OpenSSL.crypto.FILETYPE_PEM, p12.get_privatekey()
                )
            )
            c.write(
                OpenSSL.crypto.dump_certificate(
                    OpenSSL.crypto.FILETYPE_PEM, p12.get_certificate()
                )
            )
            k.close()
            c.close()
        except ImportError as e:
            raise e
        except Exception as ex:
            raise ex
    else:
        _default_backend = None
        if _crypto_version < [3, 0]:
            from cryptography.hazmat.backends import default_backend

            _default_backend = default_backend()
        if isinstance(pfx_password, str):
            pfx_password = str.encode(pfx_password)
        with open(pfx_path, "rb") as f:
            (
                private_key,
                certificate,
                additional_certificates,
            ) = pkcs12.load_key_and_certificates(
                f.read(), pfx_password, backend=_default_backend
            )
        cert_bytes = certificate.public_bytes(Encoding.PEM)
        pk_bytes = private_key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )
        k = open(key_file.name, "wb")
        c = open(cert_file.name, "wb")

        k.write(pk_bytes)
        c.write(cert_bytes)
        k.close()
        c.close()
        del k
        del c
    key_file.close()
    cert_file.close()
    return cert_file.name, key_file.name  # certificate/key


# ----------------------------------------------------------------------
def _handle_cert_context(
    cert: tuple | str,
    password: str,
    ssl_context: truststore.SSLContext | ssl.SSLContext,
) -> None | str:
    """handles the certificate logic"""
    if cert is None:
        return None
    elif (
        cert
        and isinstance(cert, str)
        and (cert.lower().endswith(".p12") or cert.lower().endswith(".pfx"))
        and password
    ):
        #  case 2 - p12/pfx with password
        return _handle_cert_context(
            cert=pfx_to_pem(cert, password),
            password=password,
            ssl_context=ssl_context,
        )
    elif (
        cert
        and isinstance(cert, str)
        and (cert.lower().endswith(".p12") or cert.lower().endswith(".pfx"))
        and password is None
    ):
        # case 2 p12/pfx with no password - not allowed, raise error
        raise ValueError("`password` is required.")
    elif isinstance(cert, (tuple, list)):
        # case 3 tuple[str] or list[str]
        with tempfile.NamedTemporaryFile(delete=False) as c:
            with open(cert[0], "rb") as reader:
                public_cert = x509.load_pem_x509_certificate(reader.read())
            with open(cert[1], "rb") as reader:
                private_bytes = reader.read()
            cert_bytes = public_cert.public_bytes(Encoding.PEM)

            private_key = load_pem_private_key(
                data=private_bytes, password=None, backend=None
            )
            pk_buf = private_key.private_bytes(
                Encoding.PEM,
                PrivateFormat.TraditionalOpenSSL,
                NoEncryption(),
            )
            c.write(pk_buf)

            c.write(cert_bytes)
            c.flush()
            c.close()

            ssl_context.load_cert_chain(c.name)
        return ssl_context
    else:
        raise ValueError("Invalid `cert` parameter")


###########################################################################
class EsriTrustStoreAdapter(HTTPAdapter):
    """An HTTP Adapter for Esri's ArcGIS API for Python that leverages TrustStore"""

    def __init__(
        self,
        assert_hostname=None,
        verify=True,
        additional_certs=None,
        *args,
        **kwargs,
    ):
        """
        Constructor for EsriTrustStoreAdapter

        :param assert_hostname: Optional. If True, the hostname in the certificate will be verified.
        :param verify: Optional. If False, the certificate will not be verified.
        :param additional_certs: Optional. Additional certificates to trust.
        :param pki_data: Optional. The path to the PKI data.
        :param pki_password: Optional. The password for the PKI data.
        """
        self.assert_hostname = assert_hostname
        self.verify = verify
        self.additional_certs = additional_certs
        self.pki_data = kwargs.pop("pki_data", None)
        self.pki_password = kwargs.pop("pki_password", None)
        self.ssl_context = kwargs.pop(
            "ssl_context", truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        )
        super(EsriTrustStoreAdapter, self).__init__(*args, **kwargs)

    def __str__(self) -> str:
        return f"< EsriTrustStoreAdapter: verify={self.verify}, assert_hostname={self.assert_hostname} >"

    def __repr__(self) -> str:
        return self.__str__()

    def configure_ssl_context(self, context):
        """Configures the SSL context"""
        context.load_verify_locations(cafile=certifi.where())

        if self.additional_certs:
            if isinstance(self.additional_certs, list):
                for cert in self.additional_certs:
                    context.load_verify_locations(cafile=cert)
            else:
                context.load_verify_locations(cafile=self.additional_certs)

        if self.assert_hostname is not None:
            context.check_hostname = self.assert_hostname
        if not self.verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            context.hostname_checks_common_name = False
        else:
            context.verify_mode = ssl.CERT_REQUIRED
            context.verify_flags = ssl.VERIFY_X509_TRUSTED_FIRST
        if self.pki_data:
            self.ssl_context = _handle_cert_context(
                self.pki_data, self.pki_password, self.ssl_context
            )

    def init_poolmanager(self, *args, **kwargs):
        """Initializes the pool manager"""
        context = self.ssl_context
        self.configure_ssl_context(context)
        kwargs["ssl_context"] = context
        super(EsriTrustStoreAdapter, self).init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        """Creates a proxy manager"""
        context = self.ssl_context
        self.configure_ssl_context(context)
        kwargs["ssl_context"] = context
        return super(EsriTrustStoreAdapter, self).proxy_manager_for(*args, **kwargs)

    # ---------------------------------------------------------------------
    def cert_verify(self, conn, url, verify, cert):
        """Verifies the certificate"""
        check_hostname = self.ssl_context.check_hostname
        try:
            if verify is False:
                self.ssl_context.check_hostname = False
            return super(EsriTrustStoreAdapter, self).cert_verify(
                conn, url, verify, cert
            )
        finally:
            self.ssl_context.check_hostname = check_hostname

    # ---------------------------------------------------------------------
    def send(
        self,
        request,
        stream=False,
        timeout=None,
        verify=True,
        cert=None,
        proxies=None,
    ):
        """Sends the request"""
        if proxies is None and self.poolmanager is not None:
            proxies = (
                get_environ_proxies(request.url) if self.poolmanager.trust_env else {}
            )
        check_hostname = self.ssl_context.check_hostname
        verify_mode = self.ssl_context.verify_mode
        hostname_checks = self.ssl_context.hostname_checks_common_name
        try:
            if verify is False:
                self.ssl_context.check_hostname = False
                self.ssl_context.verify_mode = ssl.CERT_NONE
                self.ssl_context.hostname_checks = False
                # self.ssl_context.hostname_checks_common_name = False
            return super(EsriTrustStoreAdapter, self).send(
                request, stream, timeout, verify, cert, proxies
            )
        finally:
            self.ssl_context.check_hostname = check_hostname
            self.ssl_context.verify_mode = verify_mode
            self.ssl_context.hostname_checks = hostname_checks
