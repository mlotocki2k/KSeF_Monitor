"""
Test KSeF — autoryzacja + weryfikacja pobrania UPO.

Użycie:
    python examples/test_upo_download.py \\
        --nip 9730842472 \\
        --token "20260205-EC-..." \\
        --env test \\
        --ksef-number 5265877635-20250626-010080DD2B5E-26

Można też przez ENV: KSEF_NIP, KSEF_TOKEN, KSEF_ENV.

Tryby:
- bez --ksef-number → listuje ostatnie sesje + ich faktury (do wskazania celu)
- z --ksef-number    → znajduje sesję z tą fakturą i pobiera UPO faktury
- z --session-ref    → pobiera UPO sesji (zbiorcze) + listuje faktury tej sesji

Token wymaga uprawnień: Introspection (przeglądanie sesji + UPO) lub InvoiceWrite.
"""

import argparse
import base64
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List

import requests
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives import hashes
from cryptography.x509 import load_der_x509_certificate

API_VERSION = "v2"
ENV_URLS = {
    "prod": "https://api.ksef.mf.gov.pl",
    "demo": "https://api-demo.ksef.mf.gov.pl",
    "test": "https://api-test.ksef.mf.gov.pl",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("upo-test")


class KSeFTestClient:
    def __init__(self, nip: str, token: str, environment: str):
        if environment not in ENV_URLS:
            raise ValueError(f"Invalid env: {environment}. Pick: {list(ENV_URLS)}")
        self.nip = nip
        self.token = token
        self.environment = environment
        self.base_url = ENV_URLS[environment]
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self._public_key = None
        self.session = requests.Session()
        self.session.verify = True
        log.info("Init: env=%s url=%s nip=%s", environment, self.base_url, nip)

    # ---- auth flow (mirror app/ksef_client.py) ----

    def authenticate(self) -> bool:
        log.info("Auth step 1/5: get challenge")
        ch = self._get_challenge()
        if not ch:
            return False
        challenge = ch["challenge"]
        ts_ms = ch["timestampMs"]

        log.info("Auth step 2/5: fetch KSeF public key")
        self._fetch_public_key()

        log.info("Auth step 3/5: encrypt token + POST /auth/ksef-token")
        auth = self._auth_with_token(challenge, ts_ms)
        if not auth:
            return False
        ref = auth["referenceNumber"]
        tmp_token = auth["authenticationToken"]["token"]

        log.info("Auth step 4/5: poll status (ref=%s)", ref)
        if not self._wait_status(ref, tmp_token):
            return False

        log.info("Auth step 5/5: redeem accessToken")
        return self._redeem(tmp_token)

    def _get_challenge(self) -> Optional[Dict]:
        url = f"{self.base_url}/{API_VERSION}/auth/challenge"
        payload = {"contextIdentifier": {"type": "nip", "value": self.nip}}
        r = self.session.post(url, json=payload, timeout=30)
        if not r.ok:
            log.error("Challenge failed: %s %s", r.status_code, r.text[:300])
            return None
        return r.json()

    def _fetch_public_key(self):
        url = f"{self.base_url}/{API_VERSION}/security/public-key-certificates"
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        for cert in r.json():
            if "KsefTokenEncryption" in cert.get("usage", []):
                der = base64.b64decode(cert["certificate"])
                self._public_key = load_der_x509_certificate(der).public_key()
                return
        raise RuntimeError("No KsefTokenEncryption cert found")

    def _auth_with_token(self, challenge: str, ts_ms: int) -> Optional[Dict]:
        url = f"{self.base_url}/{API_VERSION}/auth/ksef-token"
        plaintext = f"{self.token}|{ts_ms}".encode()
        encrypted = self._public_key.encrypt(
            plaintext,
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        payload = {
            "challenge": challenge,
            "contextIdentifier": {"type": "nip", "value": self.nip},
            "encryptedToken": base64.b64encode(encrypted).decode(),
        }
        r = self.session.post(url, json=payload, timeout=30)
        if not r.ok:
            log.error("ksef-token failed: %s %s", r.status_code, r.text[:500])
            return None
        return r.json()

    def _wait_status(self, ref: str, tmp_token: str, max_attempts: int = 15) -> bool:
        url = f"{self.base_url}/{API_VERSION}/auth/{ref}"
        headers = {"Authorization": f"Bearer {tmp_token}"}
        for attempt in range(max_attempts):
            r = self.session.get(url, headers=headers, timeout=30)
            if not r.ok:
                log.error("Status check failed: %s %s", r.status_code, r.text[:300])
                return False
            code = r.json().get("status", {}).get("code")
            if code == 200:
                return True
            if code == 100:
                time.sleep(min(2 ** attempt, 10))
                continue
            log.error("Unexpected processing code: %s", code)
            return False
        log.error("Auth status timeout")
        return False

    def _redeem(self, tmp_token: str) -> bool:
        url = f"{self.base_url}/{API_VERSION}/auth/token/redeem"
        headers = {"Authorization": f"Bearer {tmp_token}"}
        r = self.session.post(url, headers=headers, timeout=30)
        if not r.ok:
            log.error("Redeem failed: %s %s", r.status_code, r.text[:300])
            return False
        d = r.json()
        self.access_token = d.get("accessToken", {}).get("token")
        self.refresh_token = d.get("refreshToken", {}).get("token")
        valid = d.get("accessToken", {}).get("validUntil")
        log.info("OK auth. accessToken validUntil=%s", valid)
        return bool(self.access_token)

    def revoke(self):
        if not self.access_token:
            return
        url = f"{self.base_url}/{API_VERSION}/auth/sessions/current"
        try:
            self.session.delete(url, headers=self._auth_headers(), timeout=10)
            log.info("Session revoked")
        except Exception as e:
            log.warning("Revoke failed: %s", e)

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    # ---- sessions / UPO ----

    def list_sessions(self, session_type: str = "Online", page_size: int = 50) -> List[Dict]:
        url = f"{self.base_url}/{API_VERSION}/sessions"
        params = {"sessionType": session_type, "pageSize": page_size}
        r = self.session.get(url, headers=self._auth_headers(), params=params, timeout=30)
        if r.status_code != 200:
            log.error("List sessions failed: %s %s", r.status_code, r.text[:500])
            return []
        return r.json().get("sessions", [])

    def get_session_status(self, ref: str) -> Optional[Dict]:
        url = f"{self.base_url}/{API_VERSION}/sessions/{ref}"
        r = self.session.get(url, headers=self._auth_headers(), timeout=30)
        if r.status_code != 200:
            log.error("Session status failed: %s %s", r.status_code, r.text[:500])
            return None
        return r.json()

    def get_session_invoices(self, ref: str, page_size: int = 100) -> List[Dict]:
        url = f"{self.base_url}/{API_VERSION}/sessions/{ref}/invoices"
        params = {"pageSize": page_size}
        r = self.session.get(url, headers=self._auth_headers(), params=params, timeout=30)
        if r.status_code != 200:
            log.error("Session invoices failed: %s %s", r.status_code, r.text[:500])
            return []
        return r.json().get("invoices", [])

    def download_invoice_upo(self, session_ref: str, ksef_number: str) -> Optional[Dict]:
        """GET /sessions/{ref}/invoices/ksef/{ksefNumber}/upo → application/xml + x-ms-meta-hash."""
        url = f"{self.base_url}/{API_VERSION}/sessions/{session_ref}/invoices/ksef/{ksef_number}/upo"
        r = self.session.get(url, headers=self._auth_headers(), timeout=60)
        if r.status_code != 200:
            log.error("UPO download failed: %s %s", r.status_code, r.text[:800])
            return None
        return {
            "xml": r.content,
            "sha256_b64_header": r.headers.get("x-ms-meta-hash", ""),
            "content_type": r.headers.get("Content-Type", ""),
        }

    def download_session_upo(self, session_ref: str, upo_ref: str) -> Optional[Dict]:
        """GET /sessions/{ref}/upo/{upoReferenceNumber} → application/xml."""
        url = f"{self.base_url}/{API_VERSION}/sessions/{session_ref}/upo/{upo_ref}"
        r = self.session.get(url, headers=self._auth_headers(), timeout=60)
        if r.status_code != 200:
            log.error("Session UPO failed: %s %s", r.status_code, r.text[:800])
            return None
        return {
            "xml": r.content,
            "sha256_b64_header": r.headers.get("x-ms-meta-hash", ""),
        }


# ---- helpers ----

def verify_sha256(data: bytes, header_b64: str) -> bool:
    if not header_b64:
        log.warning("No x-ms-meta-hash header — skip verify")
        return True
    actual_b64 = base64.b64encode(hashlib.sha256(data).digest()).decode()
    ok = actual_b64 == header_b64
    log.info("SHA256 verify: %s (header=%s, computed=%s)",
             "OK" if ok else "MISMATCH", header_b64, actual_b64)
    return ok


def save_xml(out_dir: Path, name: str, data: bytes) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_bytes(data)
    log.info("Saved %d bytes → %s", len(data), path)
    return path


def find_session_for_ksef_number(client: KSeFTestClient, ksef_number: str,
                                  max_sessions: int = 50) -> Optional[Dict]:
    """Listuje sesje, znajduje tę z fakturą o danym numerze KSeF."""
    log.info("Searching sessions for ksefNumber=%s (max %d sessions)", ksef_number, max_sessions)
    sessions = client.list_sessions(page_size=max_sessions)
    log.info("Got %d sessions", len(sessions))
    for s in sessions:
        ref = s["referenceNumber"]
        invoices = client.get_session_invoices(ref)
        for inv in invoices:
            if inv.get("ksefNumber") == ksef_number:
                log.info("Match: session=%s invoiceRef=%s", ref, inv.get("referenceNumber"))
                return {"session": s, "invoice": inv}
    return None


def cmd_explore(client: KSeFTestClient, limit: int):
    """Tryb bez --ksef-number — pokaż ostatnie sesje + ich faktury."""
    sessions = client.list_sessions(page_size=limit)
    print(f"\n=== Last {len(sessions)} Online sessions ===")
    for s in sessions:
        ref = s["referenceNumber"]
        st = s.get("status", {})
        print(f"\n[{ref}] status={st.get('code')} {st.get('description', '')}")
        print(f"  created={s.get('dateCreated')} invoices={s.get('totalInvoiceCount')} "
              f"ok={s.get('successfulInvoiceCount')} fail={s.get('failedInvoiceCount')}")
        invs = client.get_session_invoices(ref, page_size=20)
        for inv in invs:
            ksefn = inv.get("ksefNumber") or "(brak — odrzucona)"
            inv_st = inv.get("status", {})
            has_upo = bool(inv.get("upoDownloadUrl"))
            print(f"    - ksef={ksefn} ref={inv.get('referenceNumber')} "
                  f"status={inv_st.get('code')} upo_url={'YES' if has_upo else 'no'}")


def cmd_download_invoice_upo(client: KSeFTestClient, ksef_number: str,
                              session_ref: Optional[str], out_dir: Path):
    if not session_ref:
        match = find_session_for_ksef_number(client, ksef_number)
        if not match:
            log.error("No session contains invoice ksefNumber=%s", ksef_number)
            sys.exit(2)
        session_ref = match["session"]["referenceNumber"]

    log.info("Downloading invoice UPO: session=%s ksefNumber=%s", session_ref, ksef_number)
    res = client.download_invoice_upo(session_ref, ksef_number)
    if not res:
        sys.exit(3)

    log.info("Got UPO: %d bytes, content-type=%s", len(res["xml"]), res["content_type"])
    verify_sha256(res["xml"], res["sha256_b64_header"])
    fname = f"upo_{ksef_number}.xml"
    save_xml(out_dir, fname, res["xml"])

    # Print first ~400 bytes preview
    preview = res["xml"][:400].decode("utf-8", errors="replace")
    print("\n=== UPO XML preview ===")
    print(preview)
    print("...\n")


def cmd_download_session_upo(client: KSeFTestClient, session_ref: str, out_dir: Path):
    status = client.get_session_status(session_ref)
    if not status:
        sys.exit(2)
    print(f"\n=== Session {session_ref} ===")
    print(json.dumps(status, indent=2, ensure_ascii=False)[:2000])

    upo_pages = status.get("upo", {}).get("pages", [])
    if not upo_pages:
        log.warning("No UPO pages on this session yet")
        return
    for page in upo_pages:
        upo_ref = page["referenceNumber"]
        log.info("Downloading session UPO: ref=%s", upo_ref)
        res = client.download_session_upo(session_ref, upo_ref)
        if not res:
            continue
        verify_sha256(res["xml"], res["sha256_b64_header"])
        save_xml(out_dir, f"session_upo_{upo_ref}.xml", res["xml"])


def parse_args():
    p = argparse.ArgumentParser(description="Test KSeF UPO download")
    p.add_argument("--nip", default=os.getenv("KSEF_NIP"), help="NIP (env KSEF_NIP)")
    p.add_argument("--token", default=os.getenv("KSEF_TOKEN"), help="KSeF token (env KSEF_TOKEN)")
    p.add_argument("--env", default=os.getenv("KSEF_ENV", "test"),
                   choices=["test", "demo", "prod"], help="Environment (default: test)")
    p.add_argument("--ksef-number", help="Numer KSeF faktury — pobierz UPO tej faktury")
    p.add_argument("--session-ref", help="Numer ref sesji — pomija wyszukiwanie / pobiera UPO sesji")
    p.add_argument("--list-only", action="store_true",
                   help="Tylko listuj ostatnie sesje + faktury (eksploracja)")
    p.add_argument("--limit", type=int, default=10, help="Max sesji do listowania (default: 10)")
    p.add_argument("--out-dir", default="./data/upo_test",
                   help="Katalog na pobrane UPO (default: ./data/upo_test)")
    return p.parse_args()


def main():
    args = parse_args()
    if not args.nip or not args.token:
        log.error("Brak --nip/--token (lub ENV KSEF_NIP/KSEF_TOKEN)")
        sys.exit(1)

    client = KSeFTestClient(args.nip, args.token, args.env)

    if not client.authenticate():
        log.error("Auth failed — sprawdź NIP/token/env i uprawnienia")
        sys.exit(1)

    out_dir = Path(args.out_dir)

    try:
        if args.list_only or (not args.ksef_number and not args.session_ref):
            cmd_explore(client, args.limit)
            return

        if args.ksef_number:
            cmd_download_invoice_upo(client, args.ksef_number, args.session_ref, out_dir)
        elif args.session_ref:
            cmd_download_session_upo(client, args.session_ref, out_dir)
    finally:
        client.revoke()


if __name__ == "__main__":
    main()
