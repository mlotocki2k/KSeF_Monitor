"""
Podpis XAdES-BES dokumentu AuthTokenRequest dla logowania certyfikatem do KSeF (v0.6).

Logowanie certyfikatem (alternatywa dla tokenu KSeF) polega na:
  1. pobraniu challenge (`POST /auth/challenge`),
  2. zbudowaniu dokumentu `AuthTokenRequest` (schemat auth v2-1),
  3. podpisaniu go podpisem XAdES-BES (enveloped, RSA-SHA256, digest SHA-256),
  4. wysłaniu podpisanego XML do `POST /auth/xades-signature`.

Akceptowane przez KSeF (auth/podpis-xades.md):
  - format: XAdES-BES, otaczany (enveloped)
  - podpis: http://www.w3.org/2001/04/xmldsig-more#rsa-sha256 (klucz min. 2048-bit)
  - digest: http://www.w3.org/2001/04/xmlenc#sha256

Moduł nie loguje hasła ani materiału klucza.
"""
from typing import Tuple

from lxml import etree

# Namespace dokumentu AuthTokenRequest (schemat auth v2-1)
AUTH_NS = "http://ksef.mf.gov.pl/auth/token/2.1"

# Dozwolone wartości SubjectIdentifierType (schemat auth v2-1)
SUBJECT_IDENTIFIER_TYPES = ("certificateSubject", "certificateFingerprint")

_SIGNATURE_ALGORITHM = "rsa-sha256"
_DIGEST_ALGORITHM = "sha256"
_C14N_ALGORITHM = "http://www.w3.org/2001/10/xml-exc-c14n#"


def build_auth_token_request(
    challenge: str,
    nip: str,
    subject_identifier_type: str = "certificateSubject",
) -> etree._Element:
    """
    Zbuduj dokument `AuthTokenRequest` (przed podpisem).

    Args:
        challenge: wartość z `POST /auth/challenge`
        nip: NIP kontekstu (10 cyfr)
        subject_identifier_type: "certificateSubject" lub "certificateFingerprint"

    Returns:
        Element lxml gotowy do podpisu.

    Raises:
        ValueError: nieprawidłowy `subject_identifier_type` lub puste wymagane pola.
    """
    if subject_identifier_type not in SUBJECT_IDENTIFIER_TYPES:
        raise ValueError(
            f"Nieprawidłowy subject_identifier_type '{subject_identifier_type}' "
            f"(dozwolone: {', '.join(SUBJECT_IDENTIFIER_TYPES)})"
        )
    if not challenge:
        raise ValueError("Brak challenge do zbudowania AuthTokenRequest")
    if not nip:
        raise ValueError("Brak NIP do zbudowania AuthTokenRequest")

    root = etree.Element(f"{{{AUTH_NS}}}AuthTokenRequest", nsmap={None: AUTH_NS})
    etree.SubElement(root, f"{{{AUTH_NS}}}Challenge").text = challenge
    context = etree.SubElement(root, f"{{{AUTH_NS}}}ContextIdentifier")
    etree.SubElement(context, f"{{{AUTH_NS}}}Nip").text = nip
    etree.SubElement(root, f"{{{AUTH_NS}}}SubjectIdentifierType").text = subject_identifier_type
    return root


def load_pkcs12(p12_bytes: bytes, password: str) -> Tuple[bytes, bytes]:
    """
    Wczytaj certyfikat PKCS#12 (.p12/.pfx) → (klucz prywatny PEM, certyfikat PEM).

    Args:
        p12_bytes: zawartość pliku .p12/.pfx
        password: hasło do PKCS#12 (może być pusty/None dla braku hasła)

    Returns:
        Krotka (private_key_pem, certificate_pem) w formacie PEM (bytes).

    Raises:
        ValueError: błędne hasło, uszkodzony plik lub brak klucza/certyfikatu.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    pwd = password.encode("utf-8") if password else None
    try:
        key, cert, _additional = pkcs12.load_key_and_certificates(p12_bytes, pwd)
    except Exception as exc:  # ValueError z backendu OpenSSL przy złym haśle/formacie
        raise ValueError(
            "Nie udało się wczytać certyfikatu PKCS#12 — błędne hasło lub nieprawidłowy format pliku"
        ) from exc

    if key is None or cert is None:
        raise ValueError("Plik PKCS#12 musi zawierać klucz prywatny i certyfikat")

    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return key_pem, cert_pem


def sign_auth_token_request(
    root: etree._Element,
    key_pem: bytes,
    cert_pem: bytes,
) -> bytes:
    """
    Podpisz `AuthTokenRequest` podpisem XAdES-BES (enveloped, RSA-SHA256).

    Args:
        root: element AuthTokenRequest (z `build_auth_token_request`)
        key_pem: klucz prywatny w PEM
        cert_pem: certyfikat w PEM

    Returns:
        Podpisany dokument XML (bytes, z deklaracją XML, UTF-8).
    """
    # Import leniwy — signxml jest potrzebny tylko przy logowaniu certyfikatem.
    from signxml.xades import XAdESSigner

    signer = XAdESSigner(
        signature_algorithm=_SIGNATURE_ALGORITHM,
        digest_algorithm=_DIGEST_ALGORITHM,
        c14n_algorithm=_C14N_ALGORITHM,
    )
    signed_root = signer.sign(root, key=key_pem, cert=cert_pem)
    return etree.tostring(signed_root, xml_declaration=True, encoding="UTF-8")


def build_signed_auth_request(
    challenge: str,
    nip: str,
    p12_bytes: bytes,
    password: str,
    subject_identifier_type: str = "certificateSubject",
) -> bytes:
    """
    Zbuduj i podpisz `AuthTokenRequest` — pełny krok podpisu dla logowania certyfikatem.

    Returns:
        Podpisany XML (bytes) gotowy do `POST /auth/xades-signature`.

    Raises:
        ValueError: problem z certyfikatem PKCS#12 lub danymi wejściowymi.
    """
    key_pem, cert_pem = load_pkcs12(p12_bytes, password)
    root = build_auth_token_request(challenge, nip, subject_identifier_type)
    return sign_auth_token_request(root, key_pem, cert_pem)
