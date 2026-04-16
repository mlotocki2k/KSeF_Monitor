"""
Invoice Export Manager for KSeF Monitor.

Implements the async export flow:
  POST /invoices/exports → poll GET /invoices/exports/{ref} → download → AES-256-CBC decrypt → parse

Reference: KSeF API v2.4.0, OpenAPI spec /invoices/exports
"""

import base64
import hashlib
import io
import logging
import os
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.x509 import load_der_x509_certificate

logger = logging.getLogger(__name__)


# ── Export status codes ──────────────────────────────────────────────────────

STATUS_PROCESSING = 100
STATUS_SUCCESS = 200
STATUS_EXPIRED = 210
STATUS_DECRYPT_ERROR = 415
STATUS_RANGE_ERROR = 420
STATUS_UNKNOWN_ERROR = 500
STATUS_CANCELLED = 550

_TERMINAL_ERRORS = {STATUS_EXPIRED, STATUS_DECRYPT_ERROR, STATUS_RANGE_ERROR, STATUS_CANCELLED}
_RETRIABLE_ERRORS = {STATUS_UNKNOWN_ERROR}


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class ExportResult:
    """Result of a single export operation."""
    success: bool
    invoices: List[Dict] = field(default_factory=list)
    is_truncated: bool = False
    last_issue_date: Optional[str] = None
    last_invoicing_date: Optional[str] = None
    last_permanent_storage_date: Optional[str] = None
    error: Optional[str] = None
    reference_number: Optional[str] = None


# ── Manager ──────────────────────────────────────────────────────────────────

class InvoiceExportManager:
    """
    Manages the full KSeF async export flow.

    Encryption model (CLIENT-SIDE):
      1. Client generates random 32-byte AES-256 key + 16-byte IV
      2. Client RSA-OAEP encrypts the AES key with KSeF public key
         (cert usage="SymmetricKeyEncryption")
      3. Client sends encryptedSymmetricKey + IV in POST /invoices/exports
      4. Server encrypts ZIP with AES-256-CBC using provided key + IV
      5. Client downloads .zip.aes, decrypts with stored AES key + IV
      6. Client extracts _metadata.json from ZIP

    Rate limits (per spec):
      POST /invoices/exports      : 4/s, 8/min, 20/h
      GET  /invoices/exports/{ref}: 10/s, 60/min, 600/h
    """

    POLL_INTERVAL_BASE = 5     # seconds
    POLL_INTERVAL_MAX = 60     # seconds
    POLL_MAX_ATTEMPTS = 180    # 180 * 5s = 15 minutes max
    DOWNLOAD_TIMEOUT = 300     # seconds per part
    MAX_RETRY_ON_500 = 3

    def __init__(self, ksef_client):
        """
        Args:
            ksef_client: KSeFClient instance (for auth + HTTP session)
        """
        self.client = ksef_client
        self._sym_key_cert_public_key = None  # cached RSA key for SymmetricKeyEncryption

    # ── Public API ───────────────────────────────────────────────────────────

    def run_export(
        self,
        subject_type: str,
        date_from: datetime,
        date_to: datetime,
        date_type: str = "Invoicing",
        only_metadata: bool = True,
    ) -> ExportResult:
        """
        Execute the full export flow for one (subject_type, date_window) pair.

        Args:
            subject_type: Subject1 / Subject2 / Subject3 / SubjectAuthorized
            date_from: Window start (UTC-aware)
            date_to: Window end (UTC-aware)
            date_type: Issue | Invoicing | PermanentStorage
            only_metadata: True = no XML files in ZIP (faster, smaller)

        Returns:
            ExportResult with invoices list and truncation metadata
        """
        # Step 1: generate encryption keys
        try:
            aes_key, iv, encrypted_key_b64, iv_b64 = self._generate_export_keys()
        except Exception as exc:
            return ExportResult(success=False, error=f"Key generation failed: {exc}")

        # Step 2: create export job
        ref = self._create_export(
            subject_type=subject_type,
            date_from=date_from,
            date_to=date_to,
            date_type=date_type,
            only_metadata=only_metadata,
            encrypted_key_b64=encrypted_key_b64,
            iv_b64=iv_b64,
        )
        if not ref:
            return ExportResult(success=False, error="Failed to create export job")

        logger.info("Export created: ref=%s [%s %s→%s]", ref, subject_type,
                    date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))

        # Step 3: poll until done
        status_data = self._poll_export_status(ref)
        if status_data is None:
            return ExportResult(success=False, error="Export polling failed", reference_number=ref)

        code = status_data.get("status", {}).get("code")
        if code != STATUS_SUCCESS:
            return ExportResult(
                success=False,
                error=f"Export ended with status {code}: {status_data.get('status', {}).get('description', '')}",
                reference_number=ref,
            )

        package = status_data.get("package", {})

        # Step 4: download + decrypt + parse
        try:
            invoices = self._download_and_decrypt(package, aes_key, iv)
        except Exception as exc:
            return ExportResult(success=False, error=f"Download/decrypt failed: {exc}",
                                reference_number=ref)

        return ExportResult(
            success=True,
            invoices=invoices,
            is_truncated=package.get("isTruncated", False),
            last_issue_date=package.get("lastIssueDate"),
            last_invoicing_date=package.get("lastInvoicingDate"),
            last_permanent_storage_date=package.get("lastPermanentStorageDate"),
            reference_number=ref,
        )

    # ── Step 1: Key generation ────────────────────────────────────────────────

    def _fetch_sym_key_cert(self):
        """
        Fetch and cache RSA public key for SymmetricKeyEncryption usage.
        Raises ValueError if cert not found.
        """
        url = f"{self.client.base_url}/{self.client.API_VERSION}/security/public-key-certificates"
        response = self.client._request_with_retry("GET", url, timeout=30)
        response.raise_for_status()

        certs = response.json()
        now = datetime.now(timezone.utc)

        for cert in certs:
            usages = cert.get("usage", [])
            if "SymmetricKeyEncryption" not in usages:
                continue
            # Validate validity window
            valid_from_str = cert.get("validFrom", "")
            valid_to_str = cert.get("validTo", "")
            try:
                valid_from = datetime.fromisoformat(valid_from_str.replace("Z", "+00:00"))
                valid_to = datetime.fromisoformat(valid_to_str.replace("Z", "+00:00"))
                if not (valid_from <= now <= valid_to):
                    logger.warning("SymmetricKeyEncryption cert outside validity window, skipping")
                    continue
            except (ValueError, AttributeError):
                pass  # ignore date parse errors, use cert anyway

            cert_der = base64.b64decode(cert["certificate"])
            x509 = load_der_x509_certificate(cert_der)
            self._sym_key_cert_public_key = x509.public_key()
            logger.debug("SymmetricKeyEncryption public key loaded")
            return

        raise ValueError("No valid SymmetricKeyEncryption certificate found in /security/public-key-certificates")

    def _generate_export_keys(self) -> Tuple[bytes, bytes, str, str]:
        """
        Generate AES-256 key + IV, encrypt key with KSeF RSA public key.

        Returns:
            (aes_key, iv, encrypted_key_b64, iv_b64)
        """
        if self._sym_key_cert_public_key is None:
            self._fetch_sym_key_cert()

        aes_key = os.urandom(32)  # 256-bit
        iv = os.urandom(16)       # 128-bit IV for AES-CBC

        encrypted_key = self._sym_key_cert_public_key.encrypt(
            aes_key,
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

        return aes_key, iv, base64.b64encode(encrypted_key).decode(), base64.b64encode(iv).decode()

    # ── Step 2: Create export ─────────────────────────────────────────────────

    def _create_export(
        self,
        subject_type: str,
        date_from: datetime,
        date_to: datetime,
        date_type: str,
        only_metadata: bool,
        encrypted_key_b64: str,
        iv_b64: str,
    ) -> Optional[str]:
        """POST /invoices/exports → returns referenceNumber."""
        url = f"{self.client.base_url}/{self.client.API_VERSION}/invoices/exports"

        date_from_str = self._fmt_dt(date_from)
        date_to_str = self._fmt_dt(date_to)

        payload = {
            "encryption": {
                "encryptedSymmetricKey": encrypted_key_b64,
                "initializationVector": iv_b64,
            },
            "onlyMetadata": only_metadata,
            "filters": {
                "subjectType": subject_type,
                "dateRange": {
                    "dateType": date_type,
                    "from": date_from_str,
                    "to": date_to_str,
                },
            },
        }

        response = self.client._make_authenticated_request(
            "POST", url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if response is None:
            logger.error("Create export: authentication failed")
            return None

        if response.status_code == 400:
            logger.error("Create export 400: %s",
                         self.client._extract_api_error_details(response))
            return None
        if response.status_code == 429:
            logger.warning("Create export 429 — rate limited (already retried)")
            return None

        try:
            response.raise_for_status()
        except requests.HTTPError:
            logger.error("Create export HTTP %s: %s",
                         response.status_code,
                         self.client._extract_api_error_details(response))
            return None

        return response.json().get("referenceNumber")

    # ── Step 3: Poll status ───────────────────────────────────────────────────

    def _poll_export_status(self, reference_number: str) -> Optional[Dict]:
        """
        Poll GET /invoices/exports/{ref} until terminal status or timeout.

        Returns:
            Full status response dict, or None on timeout/error.
        """
        url = f"{self.client.base_url}/{self.client.API_VERSION}/invoices/exports/{reference_number}"
        retries_on_500 = 0

        for attempt in range(self.POLL_MAX_ATTEMPTS):
            response = self.client._make_authenticated_request("GET", url, timeout=30)
            if response is None:
                logger.error("Poll export: authentication failed")
                return None

            if response.status_code != 200:
                logger.warning("Poll export HTTP %s (attempt %d)",
                               response.status_code, attempt + 1)
                time.sleep(self.POLL_INTERVAL_BASE)
                continue

            data = response.json()
            code = data.get("status", {}).get("code")
            desc = data.get("status", {}).get("description", "")

            if code == STATUS_PROCESSING:
                interval = min(self.POLL_INTERVAL_BASE * (1 + attempt // 10), self.POLL_INTERVAL_MAX)
                logger.debug("Export processing (attempt %d/%d), next poll in %ds",
                             attempt + 1, self.POLL_MAX_ATTEMPTS, interval)
                time.sleep(interval)
                continue

            if code == STATUS_SUCCESS:
                inv_count = data.get("package", {}).get("invoiceCount", "?")
                logger.info("Export completed: ref=%s, invoices=%s", reference_number, inv_count)
                return data

            if code in _TERMINAL_ERRORS:
                logger.error("Export terminal error %s (%s): ref=%s", code, desc, reference_number)
                return data

            if code in _RETRIABLE_ERRORS:
                retries_on_500 += 1
                if retries_on_500 > self.MAX_RETRY_ON_500:
                    logger.error("Export server error %s exceeded retries: ref=%s", code, reference_number)
                    return data
                wait = min(30 * retries_on_500, 120)
                logger.warning("Export server error %s, retry %d/%d in %ds",
                               code, retries_on_500, self.MAX_RETRY_ON_500, wait)
                time.sleep(wait)
                continue

            logger.error("Unknown export status code %s: ref=%s", code, reference_number)
            return data

        logger.error("Export polling timeout after %d attempts: ref=%s",
                     self.POLL_MAX_ATTEMPTS, reference_number)
        return None

    # ── Step 4: Download + decrypt + parse ───────────────────────────────────

    def _download_and_decrypt(self, package: Dict, aes_key: bytes, iv: bytes) -> List[Dict]:
        """
        Download all parts, decrypt with AES-256-CBC, extract _metadata.json.

        Args:
            package: package dict from export status response
            aes_key: 32-byte AES key (client-generated)
            iv: 16-byte IV (client-generated, same as sent in request)

        Returns:
            List of invoice metadata dicts from _metadata.json
        """
        parts = package.get("parts", [])
        if not parts:
            logger.warning("Export package has no parts")
            return []

        # Download all parts in order
        encrypted_chunks: List[bytes] = []
        for part in sorted(parts, key=lambda p: p.get("ordinalNumber", 0)):
            part_data = self._download_part(part)
            encrypted_chunks.append(part_data)

        encrypted_data = b"".join(encrypted_chunks)
        logger.debug("Downloaded %d bytes (encrypted)", len(encrypted_data))

        # Verify encrypted hash (partHash of combined = last part's encryptedPartHash for single-part)
        # For multi-part, verify each part individually (already done in _download_part)

        # Decrypt AES-256-CBC
        zip_bytes = self._decrypt_aes_cbc(encrypted_data, aes_key, iv)
        logger.debug("Decrypted %d bytes", len(zip_bytes))

        # Verify decrypted hash if single part
        if len(parts) == 1:
            expected_hash = parts[0].get("partHash", "")
            if expected_hash:
                actual_hash = base64.b64encode(
                    hashlib.sha256(zip_bytes).digest()
                ).decode()
                if actual_hash != expected_hash:
                    raise ValueError(
                        f"Decrypted data hash mismatch: expected={expected_hash}, got={actual_hash}"
                    )
                logger.debug("Decrypted hash verified OK")

        # Extract _metadata.json from ZIP
        return self._parse_metadata_zip(zip_bytes)

    def _download_part(self, part: Dict) -> bytes:
        """
        Download one encrypted part from signed SAS URL (no auth required).
        Verifies encryptedPartHash after download.
        """
        url = part["url"]
        part_name = part.get("partName", "?")
        expected_enc_hash = part.get("encryptedPartHash", "")

        logger.debug("Downloading part: %s", part_name)

        response = requests.get(url, timeout=self.DOWNLOAD_TIMEOUT, stream=True)
        response.raise_for_status()

        data = response.content

        # Verify encrypted hash
        if expected_enc_hash:
            actual = base64.b64encode(hashlib.sha256(data).digest()).decode()
            if actual != expected_enc_hash:
                raise ValueError(
                    f"Part {part_name} encrypted hash mismatch: "
                    f"expected={expected_enc_hash}, got={actual}"
                )
            logger.debug("Part %s hash verified OK", part_name)

        return data

    def _decrypt_aes_cbc(self, ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
        """
        Decrypt AES-256-CBC ciphertext with PKCS7 unpadding.

        Args:
            ciphertext: Encrypted bytes (pure ciphertext, no prepended IV)
            key: 32-byte AES key
            iv: 16-byte IV (same as sent in export request)

        Returns:
            Decrypted plaintext bytes
        """
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()

        unpadder = PKCS7(128).unpadder()
        return unpadder.update(padded) + unpadder.finalize()

    def _parse_metadata_zip(self, zip_bytes: bytes) -> List[Dict]:
        """
        Extract and parse _metadata.json from ZIP bytes.

        Returns:
            List of invoice metadata dicts
        """
        import json

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = zf.namelist()
            logger.debug("ZIP contents: %s", names)

            # Find _metadata.json (may be at root or in subdirectory)
            meta_name = next(
                (n for n in names if n.endswith("_metadata.json") or n == "_metadata.json"),
                None,
            )
            if not meta_name:
                logger.warning("_metadata.json not found in ZIP. Files: %s", names)
                return []

            raw = zf.read(meta_name)
            data = json.loads(raw.decode("utf-8"))

        # Response structure: {"invoices": [...]} or directly [...]
        if isinstance(data, list):
            invoices = data
        elif isinstance(data, dict):
            invoices = data.get("invoices", [])
        else:
            logger.error("Unexpected _metadata.json structure: %s", type(data))
            return []

        logger.info("Parsed %d invoices from _metadata.json", len(invoices))
        return invoices

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_dt(dt: datetime) -> str:
        """Format datetime to KSeF ISO-8601 with milliseconds + Z."""
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
