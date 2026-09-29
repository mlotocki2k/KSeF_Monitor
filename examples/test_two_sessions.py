#!/usr/bin/env python3
"""Empiryczny test: czy KSeF dopuszcza dwie równoległe sesje uwierzytelnienia
dla jednego NIP-u i czy zamknięcie jednej (DELETE /auth/sessions/current)
unieważnia drugą.

Kontekst: aplikacja iOS woła close() przy przejściu w tło, co ubijało refresh
token oddany Workerowi SaaS (status 425). Sprawdzamy, czy osobna sesja dla
Workera przeżyje zamykanie sesji UI.

Środowisko: TEST (config_test.json). Tokeny nigdy nie są wypisywane.
"""
import json
import logging
import sys

import requests

sys.path.insert(0, ".")
logging.basicConfig(level=logging.WARNING)  # cisza — klient loguje szczegóły na INFO

from app.ksef_client import KSeFClient  # noqa: E402


class Cfg:
    """Minimalny shim pod interfejs ConfigManager.get(section, key)."""

    def __init__(self, data):
        self.data = data

    def get(self, section, key=None):
        sec = self.data.get(section, {})
        if key is None:
            return sec
        return sec.get(key) if isinstance(sec, dict) else None


def list_sessions(client):
    r = requests.get(
        f"{client.base_url}/v2/auth/sessions",
        headers={"Authorization": f"Bearer {client.access_token}",
                 "X-Error-Format": "problem-details"},
        timeout=30,
    )
    if not r.ok:
        return r.status_code, None
    body = r.json()
    items = body.get("items", body if isinstance(body, list) else [])
    return r.status_code, items


def close_current(client):
    r = requests.delete(
        f"{client.base_url}/v2/auth/sessions/current",
        headers={"Authorization": f"Bearer {client.access_token}"},
        timeout=30,
    )
    return r.status_code


def summarize(items):
    if items is None:
        return "(brak dostępu)"
    out = []
    for it in items:
        out.append(f"{it.get('referenceNumber')} status={it.get('status')} method={it.get('authenticationMethod')}")
    return "\n      ".join(out) if out else "(pusto)"


def main():
    cfg = Cfg(json.load(open("config_test.json", encoding="utf-8")))
    print(f"Środowisko: {cfg.get('ksef', 'environment')}  NIP: {cfg.get('ksef', 'nip')}\n")

    print("[1] Uwierzytelnienie sesji A...")
    a = KSeFClient(cfg)
    if not a.authenticate():
        print("    ✗ nie udało się — przerywam"); return 1
    print(f"    ✓ OK (referenceNumber={a.session_reference})")

    print("[2] Uwierzytelnienie sesji B (niezależna instancja)...")
    b = KSeFClient(cfg)
    if not b.authenticate():
        print("    ✗ nie udało się — przerywam"); close_current(a); return 1
    print(f"    ✓ OK (referenceNumber={b.session_reference})")

    print("\n[3] Lista aktywnych sesji (widziana tokenem A):")
    code, items = list_sessions(a)
    print(f"    HTTP {code}, aktywnych: {len(items) if items is not None else '?'}")
    print(f"      {summarize(items)}")

    both_alive = items is not None and len(items) >= 2
    print(f"\n    => Dwie równoległe sesje: {'TAK' if both_alive else 'NIE'}")

    print("\n[4] Zamykam sesję A (DELETE /auth/sessions/current tokenem A)...")
    print(f"    HTTP {close_current(a)}")

    print("\n[5] Czy sesja B nadal działa? (GET /auth/sessions tokenem B)")
    codeB, itemsB = list_sessions(b)
    b_alive = codeB == 200
    print(f"    HTTP {codeB} → sesja B {'ŻYJE' if b_alive else 'UNIEWAŻNIONA'}")
    if itemsB is not None:
        print(f"      {summarize(itemsB)}")

    print("\n[6] Czy refresh tokenem B nadal działa?")
    rb = requests.post(
        f"{b.base_url}/v2/auth/token/refresh",
        headers={"Authorization": f"Bearer {b.refresh_token}", "X-Error-Format": "problem-details"},
        timeout=30,
    )
    print(f"    HTTP {rb.status_code} → refresh B {'DZIAŁA' if rb.ok else 'ODRZUCONY'}")
    if not rb.ok:
        print(f"      {rb.text[:300]}")

    print("\n=== WYNIK ===")
    print(f"  dwie równoległe sesje ....... {'TAK' if both_alive else 'NIE'}")
    print(f"  B przeżyła zamknięcie A ..... {'TAK' if b_alive else 'NIE'}")
    print(f"  refresh B po zamknięciu A ... {'TAK' if rb.ok else 'NIE'}")

    print("\n[7] Sprzątanie: zamykam sesję B")
    print(f"    HTTP {close_current(b)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
