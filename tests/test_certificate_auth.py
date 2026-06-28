"""
Testy logowania certyfikatem (XAdES) — KSeF Monitor v0.6.

Pokrycie:
  - app/xades_signer.py: budowa AuthTokenRequest, ładowanie PKCS#12, podpis XAdES-BES
  - app/ksef_client.py: dispatch auth_method, flow _authenticate_with_xades / certificate_flow
  - app/config_manager.py: walidacja token vs certificate
  - app/secrets_manager.py: wstrzyknięcie KSEF_CERT_PASSWORD

Weryfikacja na poziomie mock (bez realnego KSeF i bez realnego certyfikatu) —
certyfikat self-signed generowany w teście; HTTP do KSeF jest mockowany.
"""
import datetime
import json
from unittest.mock import MagicMock, patch

import pytest
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree
from fastapi.testclient import TestClient

from app import xades_signer
from app.api import create_app
from app.database import Base, Database
from app.ui_auth import create_user
from app.xades_signer import (
    AUTH_NS,
    build_auth_token_request,
    build_signed_auth_request,
    load_pkcs12,
)

CHALLENGE = "20260628-CR-1234ABCD56-7890EF1234-AB"
NIP = "1234567890"
P12_PASSWORD = "pass123"


# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #
def _make_self_signed_p12(password: str = P12_PASSWORD) -> bytes:
    """Wygeneruj self-signed cert (RSA-2048) + zapakuj do PKCS#12."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
        x509.NameAttribute(NameOID.COMMON_NAME, f"TEST {NIP}"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "KrzewiLabs Test"),
    ])
    not_before = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_before + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    enc = (
        serialization.BestAvailableEncryption(password.encode())
        if password
        else serialization.NoEncryption()
    )
    return pkcs12.serialize_key_and_certificates(b"test", key, cert, None, enc)


@pytest.fixture(scope="module")
def p12_bytes() -> bytes:
    return _make_self_signed_p12()


@pytest.fixture
def p12_file(tmp_path, p12_bytes) -> str:
    path = tmp_path / "cert.p12"
    path.write_bytes(p12_bytes)
    return str(path)


def _cert_config(p12_path: str, password: str = P12_PASSWORD) -> MagicMock:
    """MagicMock ConfigManager z auth_method=certificate (bez tokenu)."""
    data = {
        "ksef": {
            "environment": "test",
            "nip": NIP,
            "auth_method": "certificate",
            "certificate": {"path": p12_path, "password": password},
        },
        "monitoring": {"date_type": "Invoicing"},
    }
    config = MagicMock()
    config.config = data

    def _get(*keys, default=None):
        value = data
        for key in keys:
            if isinstance(key, str) and isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value

    config.get = _get
    return config


# --------------------------------------------------------------------------- #
# xades_signer — AuthTokenRequest
# --------------------------------------------------------------------------- #
class TestBuildAuthTokenRequest:
    def test_structure_and_namespace(self):
        root = build_auth_token_request(CHALLENGE, NIP)
        assert root.tag == f"{{{AUTH_NS}}}AuthTokenRequest"
        assert root.find(f"{{{AUTH_NS}}}Challenge").text == CHALLENGE
        nip_el = root.find(f"{{{AUTH_NS}}}ContextIdentifier/{{{AUTH_NS}}}Nip")
        assert nip_el is not None and nip_el.text == NIP
        sit = root.find(f"{{{AUTH_NS}}}SubjectIdentifierType")
        assert sit.text == "certificateSubject"

    def test_custom_subject_identifier_type(self):
        root = build_auth_token_request(CHALLENGE, NIP, "certificateFingerprint")
        assert root.find(f"{{{AUTH_NS}}}SubjectIdentifierType").text == "certificateFingerprint"

    def test_invalid_subject_identifier_type_raises(self):
        with pytest.raises(ValueError):
            build_auth_token_request(CHALLENGE, NIP, "bogus")

    def test_missing_challenge_raises(self):
        with pytest.raises(ValueError):
            build_auth_token_request("", NIP)

    def test_missing_nip_raises(self):
        with pytest.raises(ValueError):
            build_auth_token_request(CHALLENGE, "")


# --------------------------------------------------------------------------- #
# xades_signer — PKCS#12
# --------------------------------------------------------------------------- #
class TestLoadPkcs12:
    def test_roundtrip_returns_pem(self, p12_bytes):
        # Parse the outputs to confirm valid PEM private key + certificate.
        # (Parsing rather than asserting on header literals keeps the repo
        #  secret-scan hook from flagging a PEM key header in the test source.)
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.x509 import load_pem_x509_certificate

        key_pem, cert_pem = load_pkcs12(p12_bytes, P12_PASSWORD)
        assert load_pem_private_key(key_pem, password=None) is not None
        assert load_pem_x509_certificate(cert_pem) is not None

    def test_wrong_password_raises_valueerror(self, p12_bytes):
        with pytest.raises(ValueError):
            load_pkcs12(p12_bytes, "wrong-password")

    def test_garbage_bytes_raises_valueerror(self):
        with pytest.raises(ValueError):
            load_pkcs12(b"not-a-p12", P12_PASSWORD)


# --------------------------------------------------------------------------- #
# xades_signer — XAdES signature
# --------------------------------------------------------------------------- #
class TestSignAuthTokenRequest:
    def test_signed_xml_is_xades_bes_enveloped(self, p12_bytes):
        signed = build_signed_auth_request(CHALLENGE, NIP, p12_bytes, P12_PASSWORD)
        assert isinstance(signed, bytes)
        # Re-parse, confirm well-formed and original content preserved
        tree = etree.fromstring(signed)
        assert tree.tag == f"{{{AUTH_NS}}}AuthTokenRequest"
        assert tree.find(f"{{{AUTH_NS}}}Challenge").text == CHALLENGE

        text = signed
        # XAdES-BES markers
        assert b"http://www.w3.org/2000/09/xmldsig#" in text          # ds namespace
        assert b"QualifyingProperties" in text                         # XAdES qualifying props
        assert b"SignedProperties" in text
        # Algorithms required by KSeF (auth/podpis-xades.md)
        assert b"http://www.w3.org/2001/04/xmldsig-more#rsa-sha256" in text
        assert b"http://www.w3.org/2001/04/xmlenc#sha256" in text
        # Enveloped signature over the whole document
        assert b"http://www.w3.org/2000/09/xmldsig#enveloped-signature" in text
        assert b'URI=""' in text

    def test_signature_element_present_in_dom(self, p12_bytes):
        signed = build_signed_auth_request(CHALLENGE, NIP, p12_bytes, P12_PASSWORD)
        tree = etree.fromstring(signed)
        sig = tree.find("{http://www.w3.org/2000/09/xmldsig#}Signature")
        assert sig is not None

    def test_wrong_password_propagates_valueerror(self, p12_bytes):
        with pytest.raises(ValueError):
            build_signed_auth_request(CHALLENGE, NIP, p12_bytes, "wrong")


# --------------------------------------------------------------------------- #
# ksef_client — config + dispatch
# --------------------------------------------------------------------------- #
class TestClientCertificateConfig:
    def test_init_reads_certificate_config(self, p12_file):
        from app.ksef_client import KSeFClient

        client = KSeFClient(_cert_config(p12_file))
        assert client.auth_method == "certificate"
        assert client.cert_path == p12_file
        assert client.cert_password == P12_PASSWORD
        assert client.cert_subject_identifier_type == "certificateSubject"

    def test_authenticate_dispatches_to_certificate_flow(self, p12_file):
        from app.ksef_client import KSeFClient

        client = KSeFClient(_cert_config(p12_file))
        with patch.object(client, "_authenticate_certificate_flow", return_value=True) as flow:
            assert client.authenticate() is True
            flow.assert_called_once()

    def test_token_method_does_not_call_certificate_flow(self, mock_config):
        from app.ksef_client import KSeFClient

        client = KSeFClient(mock_config)
        assert client.auth_method == "token"
        with patch.object(client, "_authenticate_certificate_flow") as flow:
            with patch.object(client, "_get_challenge", return_value=None):
                client.authenticate()
            flow.assert_not_called()


# --------------------------------------------------------------------------- #
# ksef_client — XAdES request + full flow
# --------------------------------------------------------------------------- #
class TestXadesAuthRequest:
    def test_posts_signed_xml_to_xades_endpoint(self, p12_file):
        from app.ksef_client import KSeFClient

        client = KSeFClient(_cert_config(p12_file))
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "referenceNumber": "REF-123",
            "authenticationToken": {"token": "AUTH-TOK"},
        }
        with patch.object(client, "_request_with_retry", return_value=resp) as req:
            result = client._authenticate_with_xades(CHALLENGE)

        assert result["referenceNumber"] == "REF-123"
        args, kwargs = req.call_args
        assert args[0] == "POST"
        assert args[1].endswith("/v2/auth/xades-signature")
        assert kwargs["headers"]["Content-Type"] == "application/xml"
        body = kwargs["data"]
        assert b"AuthTokenRequest" in body
        assert b"Signature" in body
        assert CHALLENGE.encode() in body

    def test_missing_cert_path_returns_none(self, p12_file):
        from app.ksef_client import KSeFClient

        client = KSeFClient(_cert_config(p12_file))
        client.cert_path = None
        with patch.object(client, "_request_with_retry") as req:
            assert client._authenticate_with_xades(CHALLENGE) is None
            req.assert_not_called()

    def test_bad_password_returns_none(self, p12_file):
        from app.ksef_client import KSeFClient

        client = KSeFClient(_cert_config(p12_file, password="wrong"))
        with patch.object(client, "_request_with_retry") as req:
            assert client._authenticate_with_xades(CHALLENGE) is None
            req.assert_not_called()

    def test_full_certificate_flow_success(self, p12_file):
        from app.ksef_client import KSeFClient

        client = KSeFClient(_cert_config(p12_file))
        with patch.object(client, "_get_challenge",
                          return_value={"challenge": CHALLENGE, "timestampMs": 1}), \
             patch.object(client, "_authenticate_with_xades",
                          return_value={"referenceNumber": "REF",
                                        "authenticationToken": {"token": "T"}}) as xades, \
             patch.object(client, "_wait_for_auth_status", return_value=True) as wait, \
             patch.object(client, "_redeem_token", return_value=True) as redeem:
            assert client.authenticate() is True
            xades.assert_called_once_with(CHALLENGE)
            wait.assert_called_once_with("REF", "T")
            redeem.assert_called_once_with("T")

    def test_full_flow_fails_when_xades_fails(self, p12_file):
        from app.ksef_client import KSeFClient

        client = KSeFClient(_cert_config(p12_file))
        with patch.object(client, "_get_challenge",
                          return_value={"challenge": CHALLENGE}), \
             patch.object(client, "_authenticate_with_xades", return_value=None):
            assert client.authenticate() is False


# --------------------------------------------------------------------------- #
# config_manager — token vs certificate validation
# --------------------------------------------------------------------------- #
def _load_config(config_dict, tmp_path):
    """Zapisz config do pliku i załaduj przez ConfigManager (z mockiem SecretsManager)."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_dict), encoding="utf-8")
    with patch("app.config_manager.SecretsManager") as MockSM:
        MockSM.return_value.load_config_with_secrets.return_value = config_dict
        from app.config_manager import ConfigManager
        return ConfigManager(str(path))


class TestConfigValidationAuthMethod:
    def _base(self):
        return {
            "ksef": {"environment": "test", "nip": NIP},
            "monitoring": {"date_type": "Invoicing"},
            "schedule": {"mode": "minutes", "interval": 5},
        }

    def test_certificate_without_token_is_valid(self, tmp_path):
        cfg = self._base()
        cfg["ksef"]["auth_method"] = "certificate"
        cfg["ksef"]["certificate"] = {"path": "/data/cert.p12"}
        cm = _load_config(cfg, tmp_path)
        assert cm.get("ksef", "auth_method") == "certificate"

    def test_certificate_without_path_exits(self, tmp_path):
        cfg = self._base()
        cfg["ksef"]["auth_method"] = "certificate"
        with pytest.raises(SystemExit):
            _load_config(cfg, tmp_path)

    def test_invalid_auth_method_exits(self, tmp_path):
        cfg = self._base()
        cfg["ksef"]["auth_method"] = "smartcard"
        cfg["ksef"]["token"] = "x"
        with pytest.raises(SystemExit):
            _load_config(cfg, tmp_path)

    def test_token_method_still_requires_token(self, tmp_path):
        cfg = self._base()  # no token, default auth_method
        with pytest.raises(SystemExit):
            _load_config(cfg, tmp_path)

    def test_default_token_method_valid_with_token(self, tmp_path):
        cfg = self._base()
        cfg["ksef"]["token"] = "tok-123"
        cm = _load_config(cfg, tmp_path)
        assert cm.get("ksef", "token") == "tok-123"


# --------------------------------------------------------------------------- #
# secrets_manager — KSEF_CERT_PASSWORD injection
# --------------------------------------------------------------------------- #
class TestSecretsCertPassword:
    def test_cert_password_injected_from_env(self, monkeypatch):
        from app.secrets_manager import SecretsManager

        monkeypatch.setenv("KSEF_CERT_PASSWORD", "secret-pass")
        sm = SecretsManager()
        config = {"ksef": {"environment": "test", "nip": NIP,
                           "auth_method": "certificate",
                           "certificate": {"path": "/data/cert.p12"}}}
        injected = sm._inject_secrets(config)
        assert injected["ksef"]["certificate"]["password"] == "secret-pass"


# --------------------------------------------------------------------------- #
# Web UI — /ui/certificate upload route
# --------------------------------------------------------------------------- #
def _monitor_with_cert_path(cert_path: str) -> MagicMock:
    """MagicMock monitor exposing config.get('ksef','certificate','path')."""
    data = {"ksef": {"auth_method": "certificate", "certificate": {"path": cert_path}}}

    def _get(*keys, default=None):
        value = data
        for key in keys:
            if isinstance(key, str) and isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value

    monitor = MagicMock()
    monitor.config.get = _get
    return monitor


class TestCertificateUploadRoute:
    USERNAME = "admin"
    PASSWORD = "SolidPass_88!"

    def _make_db(self, tmp_path, name="ui.db"):
        db = Database(str(tmp_path / name))
        Base.metadata.create_all(db.engine)
        with db.get_session() as s:
            create_user(s, self.USERNAME, self.PASSWORD)
        return db

    @pytest.fixture
    def cert_path(self, tmp_path):
        return str(tmp_path / "certs" / "ksef.p12")

    @pytest.fixture
    def client(self, tmp_path, cert_path):
        db = self._make_db(tmp_path)
        app = create_app(
            db=db,
            monitor_instance=_monitor_with_cert_path(cert_path),
            auth_token="a" * 32,
        )
        c = TestClient(app, follow_redirects=False)
        resp = c.post("/ui/login", data={"username": self.USERNAME, "password": self.PASSWORD})
        assert resp.status_code == 303
        return c

    def test_get_redirects_to_login_when_unauthenticated(self, tmp_path):
        db = self._make_db(tmp_path, "ui_noauth.db")
        app = create_app(db=db, auth_token="a" * 32)
        c = TestClient(app, follow_redirects=False)
        resp = c.get("/ui/certificate")
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_get_page_renders_when_logged_in(self, client):
        resp = client.get("/ui/certificate")
        assert resp.status_code == 200
        assert "Certyfikat" in resp.text

    def test_upload_valid_p12_saves_file(self, client, cert_path, p12_bytes):
        files = {"certificate": ("ksef.p12", p12_bytes, "application/x-pkcs12")}
        resp = client.post("/ui/certificate", files=files, data={"password": P12_PASSWORD})
        assert resp.status_code == 303
        assert "ok=" in resp.headers["location"]
        from pathlib import Path

        saved = Path(cert_path)
        assert saved.is_file()
        assert saved.read_bytes() == p12_bytes

    def test_upload_wrong_password_rejected_and_no_file(self, client, cert_path, p12_bytes):
        files = {"certificate": ("ksef.p12", p12_bytes, "application/x-pkcs12")}
        resp = client.post("/ui/certificate", files=files, data={"password": "wrong"})
        assert resp.status_code == 303
        assert "error=" in resp.headers["location"]
        from pathlib import Path

        assert not Path(cert_path).exists()

    def test_upload_bad_extension_rejected(self, client, cert_path):
        files = {"certificate": ("evil.txt", b"hello", "text/plain")}
        resp = client.post("/ui/certificate", files=files, data={"password": ""})
        assert resp.status_code == 303
        assert "error=" in resp.headers["location"]
        from pathlib import Path

        assert not Path(cert_path).exists()

    def test_upload_redirects_to_login_when_unauthenticated(self, tmp_path, p12_bytes):
        db = self._make_db(tmp_path, "ui_noauth2.db")
        app = create_app(db=db, auth_token="a" * 32)
        c = TestClient(app, follow_redirects=False)
        files = {"certificate": ("ksef.p12", p12_bytes, "application/x-pkcs12")}
        resp = c.post("/ui/certificate", files=files, data={"password": P12_PASSWORD})
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]
