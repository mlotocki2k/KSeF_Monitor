"""
Push Manager for KSeF Monitor

Manages iOS push notification lifecycle:
- Credential generation (instance_id, instance_key, pairing_code)
- Registration with Central Push Service (Cloudflare Worker)
- QR code generation for device pairing
- Push notification sending via Worker relay to APNs

Storage: SQLite database (push_instances table) with automatic migration
from legacy push_config.json files.

Architecture: Docker (ksef_monitor) → Worker (push.monitorksef.com) → APNs → iOS
The .p8 APNs key never leaves the Worker. Docker only knows its instance credentials.
"""

import base64
import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

import requests

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

logger = logging.getLogger(__name__)

# QR code prefix for pairing codes (validated by iOS app)
QR_PREFIX = "MKSEF:"


class PushManager:
    """Manages push notification lifecycle: credentials, registration, QR, sending.

    Responsible for:
    - Generating instance_id (UUID), instance_key (32B random), pairing_code (8 hex)
    - Registering instance with Central Push Service (POST /instances/register)
    - Generating QR code with content 'MKSEF:{pairing_code}' for iOS app scanning
    - Sending push notifications via Worker (POST /push/send)
    - Regenerating pairing codes

    Storage: credentials in SQLite push_instances table (with auto-migration
    from legacy push_config.json).

    NOT responsible for:
    - Storing device tokens (Worker handles this via KV)
    - Communicating with APNs (Worker handles this)
    - Generating APNs JWT (Worker handles this)
    """

    def __init__(self, config: Dict[str, Any], data_dir: str = "/data",
                 db=None):
        """
        Initialize PushManager.

        Args:
            config: Notification config dict (from config["notifications"]["ios_push"])
            data_dir: Directory for legacy push_config.json (default: /data)
            db: Database instance for credential storage (optional, falls back to JSON)
        """
        self.central_push_url = config.get("worker_url", "https://push.monitorksef.com")
        self.timeout = config.get("timeout", 15)
        self.push_config_path = Path(data_dir) / "push_config.json"
        self.db = db

        self.instance_id: Optional[str] = None
        self.instance_key: Optional[str] = None
        self.pairing_code: Optional[str] = None
        self.registered_at: Optional[str] = None

        self.session = requests.Session()
        self.session.verify = True

        self._load_or_generate()

    def _load_or_generate(self):
        """Load credentials from DB/JSON or generate new ones on first run."""
        # Try DB first
        if self._load_from_db():
            return

        # Try legacy JSON file (and migrate to DB if found)
        if self.push_config_path.exists():
            self._load_from_json()
            if self.instance_id and self.instance_key:
                self._save_to_db()
                self._rename_legacy_json()
                return

        # First run: generate new credentials
        self._generate_credentials()
        if self._register_instance():
            self._save_to_db()
            self._log_pairing_info()
        else:
            logger.error("Failed to register with Central Push Service")

    # ── DB Storage ───────────────────────────────────────────────────────

    def _load_from_db(self) -> bool:
        """Load credentials from push_instances table."""
        if not self.db:
            return False
        try:
            session = self.db.get_session()
            try:
                instance = self.db.get_push_instance(session)
                if not instance:
                    return False
                self.instance_id = instance.instance_id
                self.instance_key = instance.instance_key
                self.pairing_code = instance.pairing_code
                self.registered_at = instance.registered_at
                logger.info("Push config loaded from DB (instance: %s)", self.instance_id)
                return True
            finally:
                session.close()
        except Exception as e:
            logger.warning("Failed to load push config from DB: %s", e)
            return False

    def _save_to_db(self):
        """Save credentials to push_instances table."""
        if not self.db:
            # Fallback to JSON if no DB
            self._save_to_json()
            return
        try:
            session = self.db.get_session()
            try:
                self.db.save_push_instance(
                    session,
                    instance_id=self.instance_id,
                    instance_key=self.instance_key,
                    pairing_code=self.pairing_code,
                    central_push_url=self.central_push_url,
                    registered_at=self.registered_at,
                )
                session.commit()
                logger.info("Push config saved to DB (instance: %s)", self.instance_id)
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        except Exception as e:
            logger.error("Failed to save push config to DB: %s", e)
            # Fallback to JSON
            self._save_to_json()

    # ── Legacy JSON Storage ──────────────────────────────────────────────

    def _load_from_json(self):
        """Load credentials from legacy push_config.json file."""
        try:
            with open(self.push_config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.instance_id = data.get("instance_id")
            self.instance_key = data.get("instance_key")
            self.pairing_code = data.get("pairing_code")
            self.registered_at = data.get("registered_at")

            if not self.instance_id or not self.instance_key:
                logger.warning("Push config JSON incomplete, regenerating credentials")
                self._generate_credentials()
                if self._register_instance():
                    return  # caller will save to DB
                return

            logger.info("Push config loaded from JSON (instance: %s)", self.instance_id)

        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load push config JSON: %s", e)
            self._generate_credentials()
            self._register_instance()

    def _save_to_json(self):
        """Save credentials to push_config.json (fallback when DB unavailable)."""
        import os
        try:
            self.push_config_path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "instance_id": self.instance_id,
                "instance_key": self.instance_key,
                "pairing_code": self.pairing_code,
                "central_push_url": self.central_push_url,
                "registered_at": self.registered_at,
            }

            fd = os.open(
                str(self.push_config_path),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            except Exception:
                raise

            logger.info("Push config saved to %s (DB fallback)", self.push_config_path)

        except OSError as e:
            logger.error("Failed to save push config to JSON: %s", e)

    def _rename_legacy_json(self):
        """Rename push_config.json to .migrated after DB migration."""
        try:
            migrated_path = self.push_config_path.with_suffix(".json.migrated")
            self.push_config_path.rename(migrated_path)
            logger.info(
                "Migrated push_config.json → DB. Old file renamed to %s",
                migrated_path.name,
            )
        except OSError as e:
            logger.warning("Could not rename legacy push_config.json: %s", e)

    # ── Credential Generation ────────────────────────────────────────────

    def _generate_credentials(self):
        """Generate new instance credentials.

        - instance_id: UUID4
        - instance_key: 32 bytes random hex (64 chars)
        - pairing_code: 4 bytes random hex uppercase (8 chars)
        """
        self.instance_id = str(uuid.uuid4())
        self.instance_key = secrets.token_hex(32)
        self.pairing_code = secrets.token_hex(4).upper()
        logger.info("Generated new push credentials (instance: %s)", self.instance_id)

    # ── Worker Registration ──────────────────────────────────────────────

    def _register_instance(self) -> bool:
        """Register instance with Central Push Service.

        Sends hashes of instance_key and pairing_code (never plaintext).

        Returns:
            True if registration succeeded, False otherwise
        """
        if not self.instance_id or not self.instance_key or not self.pairing_code:
            logger.error("Cannot register: credentials not generated")
            return False

        try:
            payload = {
                "instance_id": self.instance_id,
                "instance_key_hash": self._sha256_hex(self.instance_key),
                "pairing_code_hash": self._sha256_hex(self.pairing_code),
            }

            response = self.session.post(
                f"{self.central_push_url}/instances/register",
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
            )

            if response.status_code == 200:
                self.registered_at = datetime.now(timezone.utc).isoformat()
                logger.info("Instance registered with Central Push Service")
                return True
            elif response.status_code == 409:
                logger.warning("Instance already registered")
                self.registered_at = datetime.now(timezone.utc).isoformat()
                return True
            else:
                logger.error(
                    "Failed to register instance: HTTP %d", response.status_code
                )
                return False

        except requests.exceptions.RequestException as e:
            logger.error("Failed to register with Central Push Service: %s", e)
            return False
        except Exception as e:
            logger.error("Unexpected error during registration: %s", e)
            return False

    # ── Logging / QR ─────────────────────────────────────────────────────

    def _log_pairing_info(self):
        """Log pairing code and QR on first run so user can pair from Docker logs."""
        qr_ascii = self._generate_qr_ascii()
        lines = [
            "",
            "╔══════════════════════════════════════════════════════╗",
            "║           iOS Push — pairing code                   ║",
            "║                                                      ║",
            "║   Code:  %-8s                                   ║" % self.pairing_code,
            "║                                                      ║",
            "║   Scan QR with Monitor KSeF app:                    ║",
        ]
        if qr_ascii:
            for qr_line in qr_ascii.splitlines():
                lines.append("║   %-50s ║" % qr_line)
        lines += [
            "║                                                      ║",
            "║   Or enter code manually in app:                    ║",
            "║   Settings → Add instance → Enter code              ║",
            "╚══════════════════════════════════════════════════════╝",
        ]
        logger.info("\n".join(lines))

    def _generate_qr_ascii(self) -> str:
        """Generate QR code as ASCII art for terminal/log output."""
        if not QRCODE_AVAILABLE or not self.pairing_code:
            return ""
        try:
            import io
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=1,
                border=1,
            )
            qr.add_data(f"{QR_PREFIX}{self.pairing_code}")
            qr.make(fit=True)
            buf = io.StringIO()
            qr.print_ascii(out=buf)
            return buf.getvalue().rstrip()
        except Exception as e:
            logger.debug("Could not generate ASCII QR: %s", e)
            return ""

    def generate_qr_data_uri(self) -> str:
        """Generate QR code as base64 data URI for Web UI display.

        Content: 'MKSEF:{pairing_code}' (prefix validated by iOS app).
        Error correction: M (15%), box_size=6 for minimum 200x200px.

        Returns:
            Base64 data URI string (data:image/png;base64,...) or empty string on failure
        """
        if not QRCODE_AVAILABLE:
            logger.warning("qrcode library not available, cannot generate QR")
            return ""

        if not self.pairing_code:
            logger.warning("No pairing code available for QR generation")
            return ""

        try:
            qr_content = f"{QR_PREFIX}{self.pairing_code}"

            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=6,
                border=2,
            )
            qr.add_data(qr_content)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color='black', back_color='white')

            img_buffer = BytesIO()
            qr_img.save(img_buffer, format='PNG')
            b64 = base64.b64encode(img_buffer.getvalue()).decode('ascii')
            return f"data:image/png;base64,{b64}"

        except Exception as e:
            logger.error("Failed to generate QR code: %s", e)
            return ""

    # ── Pairing Code Regeneration ────────────────────────────────────────

    def regenerate_pairing_code(self) -> bool:
        """Generate new pairing code and update Central Push Service.

        Returns:
            True if regeneration succeeded, False otherwise
        """
        if not self.instance_id or not self.instance_key:
            logger.error("Cannot regenerate: instance not configured")
            return False

        new_code = secrets.token_hex(4).upper()

        try:
            response = self.session.post(
                f"{self.central_push_url}/instances/regenerate-pairing",
                json={"pairing_code_hash": self._sha256_hex(new_code)},
                headers={
                    "X-Instance-Id": self.instance_id,
                    "X-Instance-Key": self.instance_key,
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
                allow_redirects=False,
            )

            if response.status_code == 200:
                self.pairing_code = new_code
                self._save_to_db()
                logger.info("Pairing code regenerated")
                return True
            else:
                logger.error(
                    "Failed to regenerate pairing code: HTTP %d",
                    response.status_code,
                )
                return False

        except requests.exceptions.RequestException as e:
            logger.error("Failed to regenerate pairing code: %s", e)
            return False
        except Exception as e:
            logger.error("Unexpected error during pairing regeneration: %s", e)
            return False

    # ── Push Sending ─────────────────────────────────────────────────────

    def send_push(self, title: str, body: str,
                  data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send push notification via Central Push Service.

        Worker relays to APNs for all paired devices.

        Args:
            title: Notification title
            body: Notification body text
            data: Optional additional data (e.g., invoice metadata)

        Returns:
            Response dict {ok, sent, failed} or {ok: False, error: ...}
        """
        if not self.instance_id or not self.instance_key:
            logger.error("Cannot send push: instance not configured")
            return {"ok": False, "error": "not_configured"}

        try:
            payload: Dict[str, Any] = {
                "title": title,
                "body": body[:256],  # APNs alert body practical limit
            }
            if data:
                payload["data"] = data

            headers = {
                "X-Instance-Id": self.instance_id,
                "X-Instance-Key": self.instance_key,
                "Content-Type": "application/json",
            }

            response = self.session.post(
                f"{self.central_push_url}/push/send",
                json=payload,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
            )

            if response.status_code == 200:
                result = response.json()
                sent = result.get("sent", 0)
                failed = result.get("failed", 0)
                logger.info("Push sent: %d delivered, %d failed", sent, failed)
                return result

            elif response.status_code == 401:
                logger.error("Push auth failed: invalid instance_key")
                return {"ok": False, "error": "unauthorized"}

            elif response.status_code == 429:
                logger.warning("Push rate limited by Central Push Service")
                return {"ok": False, "error": "rate_limited"}

            else:
                logger.error("Push send failed: HTTP %d", response.status_code)
                return {"ok": False, "error": f"http_{response.status_code}"}

        except requests.exceptions.RequestException as e:
            logger.error("Failed to send push notification: %s", e)
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error("Unexpected error sending push: %s", e)
            return {"ok": False, "error": str(e)}

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def is_registered(self) -> bool:
        """Check if instance is registered with Central Push Service."""
        return bool(self.instance_id and self.instance_key and self.registered_at)

    @property
    def pairing_info(self) -> Dict[str, Any]:
        """Return pairing status info for Web UI.

        Returns:
            Dict with instance_id, pairing_code, registered_at, is_registered, qr_data_uri
        """
        return {
            "instance_id": self.instance_id,
            "pairing_code": self.pairing_code,
            "registered_at": self.registered_at,
            "is_registered": self.is_registered,
            "qr_data_uri": self.generate_qr_data_uri(),
        }

    @staticmethod
    def _sha256_hex(value: str) -> str:
        """Compute SHA-256 hash of a string, return as hex."""
        return hashlib.sha256(value.encode('utf-8')).hexdigest()
