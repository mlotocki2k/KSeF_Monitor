"""
KSeF API Client
Handles authentication and communication with KSeF API v2.0
Based on official KSeF API documentation from github.com/CIRFMF/ksef-docs
"""

import logging
import time
import base64
from datetime import datetime
from typing import Optional, Dict, List
import requests
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives import hashes
from cryptography.x509 import load_der_x509_certificate

logger = logging.getLogger(__name__)


class KSeFClient:
    """Client for KSeF API v2.0 interactions"""
    
    # API version
    API_VERSION = "v2"
    VALID_DATE_TYPES = {"Issue", "Invoicing", "PermanentStorage"}
    
    def __init__(self, config):
        """
        Initialize KSeF client
        
        Args:
            config: ConfigManager instance
        """
        self.config = config
        self.environment = config.get("ksef", "environment")
        self.nip = config.get("ksef", "nip")
        self.token = config.get("ksef", "token")
        
        # Set base URL based on environment
        if self.environment == "prod":
            self.base_url = "https://api.ksef.mf.gov.pl"
        elif self.environment == "demo":
            self.base_url = "https://api-demo.ksef.mf.gov.pl"
        else:  # test
            self.base_url = "https://api-test.ksef.mf.gov.pl"

        self.access_token = None
        self.refresh_token = None
        self._ksef_public_key = None

        date_type = config.get("monitoring", "date_type")
        if date_type not in self.VALID_DATE_TYPES:
            logger.warning(f"Invalid date_type '{date_type}', falling back to 'Invoicing'")
            date_type = "Invoicing"
        self.date_type = date_type

        logger.info(f"KSeF client initialized for {self.environment} environment")
        logger.info(f"Base URL: {self.base_url}, date_type: {self.date_type}")
    
    def authenticate(self) -> bool:
        """
        Authenticate with KSeF API using authorization token
        Full flow: Challenge -> KSeF Token -> Poll Status -> Redeem

        Returns:
            True if authentication successful, False otherwise
        """
        try:
            # Step 1: Get authentication challenge (returns challenge + timestampMs)
            challenge_data = self._get_challenge()
            if not challenge_data:
                logger.error("Failed to get authentication challenge")
                return False

            challenge = challenge_data.get("challenge")
            timestamp_ms = challenge_data.get("timestampMs")
            logger.info(f"Got authentication challenge: {challenge[:10]}...")

            # Step 2: Fetch KSeF public key if not cached
            if not self._ksef_public_key:
                self._fetch_public_key()

            # Step 3: Encrypt token and authenticate
            auth_result = self._authenticate_with_token(challenge, timestamp_ms)
            if not auth_result:
                logger.error("Failed to authenticate with token")
                return False

            reference_number = auth_result.get("referenceNumber")
            authentication_token = auth_result.get("authenticationToken", {}).get("token")

            # Step 4: Poll status using the temporary authenticationToken
            if not self._wait_for_auth_status(reference_number, authentication_token):
                logger.error("Authentication status check failed")
                return False

            # Step 5: Redeem for accessToken + refreshToken
            if not self._redeem_token(authentication_token):
                logger.error("Failed to redeem access token")
                return False

            logger.info("Authentication successful")
            return True

        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False
    
    def _get_challenge(self) -> Optional[Dict]:
        """
        Get authentication challenge from KSeF
        Endpoint: POST /v2/auth/challenge

        Returns:
            Dict with 'challenge' and 'timestampMs', or None if failed
        """
        try:
            url = f"{self.base_url}/{self.API_VERSION}/auth/challenge"

            payload = {
                "contextIdentifier": {
                    "type": "nip",
                    "value": self.nip
                }
            }

            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()

            data = response.json()
            logger.info(f"Challenge response: {data}")
            return data

        except Exception as e:
            logger.error(f"Failed to get challenge: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return None
    
    def _fetch_public_key(self):
        """
        Fetch KSeF public key for token encryption
        Endpoint: GET /v2/security/public-key-certificates (no auth required)

        Filters for certificate with usage KsefTokenEncryption and caches the public key.
        """
        try:
            url = f"{self.base_url}/{self.API_VERSION}/security/public-key-certificates"

            response = requests.get(url, timeout=30)
            response.raise_for_status()

            certificates = response.json()
            for cert in certificates:
                if "KsefTokenEncryption" in cert.get("usage", []):
                    cert_der = base64.b64decode(cert["certificate"])
                    x509_cert = load_der_x509_certificate(cert_der)
                    self._ksef_public_key = x509_cert.public_key()
                    logger.info("KSeF public key fetched successfully")
                    return

            raise ValueError("No certificate with KsefTokenEncryption usage found")

        except Exception as e:
            logger.error(f"Failed to fetch public key: {e}")
            raise

    def _authenticate_with_token(self, challenge: str, timestamp_ms: int) -> Optional[Dict]:
        """
        Authenticate using KSeF token
        Endpoint: POST /v2/auth/ksef-token

        Plaintext: {token}|{timestampMs}
        Encrypted with RSA-OAEP (SHA-256 / MGF1-SHA-256) using KSeF public key, then base64-encoded.

        Args:
            challenge: Challenge string from /auth/challenge response
            timestamp_ms: timestampMs from /auth/challenge response

        Returns:
            Auth result dict with referenceNumber and authenticationToken, or None
        """
        try:
            url = f"{self.base_url}/{self.API_VERSION}/auth/ksef-token"

            headers = {
                "Content-Type": "application/json"
            }

            # Encrypt: token|timestampMs with RSA-OAEP using KSeF public key
            plaintext = f"{self.token}|{timestamp_ms}".encode("utf-8")
            encrypted = self._ksef_public_key.encrypt(
                plaintext,
                asym_padding.OAEP(
                    mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            encrypted_token_b64 = base64.b64encode(encrypted).decode()

            payload = {
                "challenge": challenge,
                "contextIdentifier": {
                    "type": "nip",
                    "value": self.nip
                },
                "encryptedToken": encrypted_token_b64
            }

            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            return response.json()

        except Exception as e:
            logger.error(f"Token authentication failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return None
    
    def _wait_for_auth_status(self, reference_number: str, authentication_token: str, max_attempts: int = 10) -> bool:
        """
        Wait for authentication to complete
        Endpoint: GET /v2/auth/{referenceNumber}
        Requires Bearer authenticationToken (temporary token from ksef-token response)

        Args:
            reference_number: Reference number from ksef-token response
            authentication_token: Temporary token from ksef-token response
            max_attempts: Maximum number of status check attempts

        Returns:
            True if authentication completed successfully
        """
        url = f"{self.base_url}/{self.API_VERSION}/auth/{reference_number}"

        headers = {
            "Authorization": f"Bearer {authentication_token}"
        }

        for attempt in range(max_attempts):
            try:
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()

                data = response.json()
                processing_code = data.get("status", {}).get("code")

                if processing_code == 200:
                    logger.info("Authentication completed successfully")
                    return True
                elif processing_code == 100:
                    logger.debug(f"Authentication in progress (attempt {attempt + 1}/{max_attempts})...")
                    time.sleep(2)
                else:
                    logger.error(f"Unexpected processing code: {processing_code}")
                    return False

            except Exception as e:
                logger.error(f"Status check failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(2)
                else:
                    return False

        logger.error("Authentication timeout")
        return False
    
    def _redeem_token(self, authentication_token: str) -> bool:
        """
        Redeem authentication for access and refresh tokens
        Endpoint: POST /v2/auth/token/redeem
        No body — Bearer authenticationToken in header.

        Response shape: { "accessToken": { "token": "...", "validUntil": "..." },
                          "refreshToken": { "token": "...", "validUntil": "..." } }

        Args:
            authentication_token: Temporary token from ksef-token response

        Returns:
            True if tokens obtained successfully
        """
        try:
            url = f"{self.base_url}/{self.API_VERSION}/auth/token/redeem"

            headers = {
                "Authorization": f"Bearer {authentication_token}"
            }

            response = requests.post(url, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            self.access_token = data.get("accessToken", {}).get("token")
            self.refresh_token = data.get("refreshToken", {}).get("token")

            if not self.access_token:
                logger.error("No access token in response")
                return False

            logger.info("Access token obtained successfully")
            return True

        except Exception as e:
            logger.error(f"Token redemption failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return False
    
    def refresh_access_token(self) -> bool:
        """
        Refresh access token using refresh token
        Endpoint: POST /api/v2/auth/token/refresh
        
        Returns:
            True if token refreshed successfully
        """
        if not self.refresh_token:
            logger.error("No refresh token available")
            return False
        
        try:
            url = f"{self.base_url}/{self.API_VERSION}/auth/token/refresh"
            
            headers = {
                "Authorization": f"Bearer {self.refresh_token}"
            }
            
            response = requests.post(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            self.access_token = data.get("accessToken", {}).get("token")

            logger.info("Access token refreshed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return False
    
    def get_invoices_metadata(self, date_from: datetime, date_to: datetime, subject_type: str) -> List[Dict]:
        """
        Get invoice metadata from KSeF
        Endpoint: POST /v2/invoices/query/metadata

        Args:
            date_from: Start date for invoice search
            date_to: End date for invoice search
            subject_type: Single subjectType value (e.g. Subject1, Subject2)

        Returns:
            List of invoice metadata dictionaries
        """
        try:
            # Ensure we're authenticated
            if not self.access_token:
                if not self.authenticate():
                    logger.error("Cannot query invoices: authentication failed")
                    return []

            url = f"{self.base_url}/{self.API_VERSION}/invoices/query/metadata"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.access_token}"
            }

            # Format dates for KSeF API (ISO 8601)
            date_from_str = date_from.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            date_to_str = date_to.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

            payload = {
                "subjectType": subject_type,
                "dateRange": {
                    "dateType": self.date_type,
                    "From": date_from_str,
                    "To": date_to_str
                },
                "pageSize": 100,
                "pageOffset": 0
            }

            logger.info(f"Querying invoices [{subject_type}] from {date_from_str} to {date_to_str}")
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            # Handle token expiration
            if response.status_code == 401:
                logger.warning("Access token expired, refreshing...")
                if self.refresh_access_token():
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    response = requests.post(url, json=payload, headers=headers, timeout=30)
                elif self.authenticate():
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    response = requests.post(url, json=payload, headers=headers, timeout=30)
                else:
                    logger.error("Re-authentication failed")
                    return []
            
            response.raise_for_status()
            
            data = response.json()
            invoices = data.get('invoices', [])
            
            logger.info(f"Found {len(invoices)} invoice(s)")
            return invoices
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get invoices: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error while getting invoices: {e}")
            return []
    
    def get_current_sessions(self) -> List[Dict]:
        """
        Get list of current active sessions
        Endpoint: GET /api/v2/auth/sessions
        
        Returns:
            List of active sessions
        """
        if not self.access_token:
            return []
        
        try:
            url = f"{self.base_url}/{self.API_VERSION}/auth/sessions"
            headers = {
                "Authorization": f"Bearer {self.access_token}"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            return data.get('sessions', [])
            
        except Exception as e:
            logger.warning(f"Failed to get sessions: {e}")
            return []
    
    def revoke_current_session(self):
        """
        Revoke the current authentication session
        Endpoint: DELETE /api/v2/auth/sessions/current
        """
        if not self.access_token:
            return
        
        try:
            url = f"{self.base_url}/{self.API_VERSION}/auth/sessions/current"
            headers = {
                "Authorization": f"Bearer {self.access_token}"
            }
            
            response = requests.delete(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            logger.info("Session revoked successfully")
        except Exception as e:
            logger.warning(f"Failed to revoke session: {e}")
        finally:
            self.access_token = None
            self.refresh_token = None
