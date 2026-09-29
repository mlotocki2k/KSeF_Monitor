#!/usr/bin/env python3
"""Mierzy realne lifetime tokenów KSeF (accessToken vs refreshToken) i sprawdza,
czy wywołanie /auth/token/refresh przesuwa ważność refresh tokena.

Wypisuje wyłącznie wartości pochodne (czasy życia) — nigdy samych tokenów.
Środowisko: TEST. Sesja zamykana na końcu.
"""
import base64
import json
import logging
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, ".")
logging.basicConfig(level=logging.WARNING)

from app.ksef_client import KSeFClient  # noqa: E402


class Cfg:
    def __init__(self, data):
        self.data = data

    def get(self, section, key=None):
        sec = self.data.get(section, {})
        if key is None:
            return sec
        return sec.get(key) if isinstance(sec, dict) else None


def claims(jwt: str) -> dict:
    """Dekoduje payload JWT bez weryfikacji podpisu (tylko do odczytu exp/iat)."""
    p = jwt.split(".")
    if len(p) != 3:
        return {}
    b = p[1] + "=" * (-len(p[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(b))


def describe(name: str, jwt: str):
    c = claims(jwt)
    exp, iat = c.get("exp"), c.get("iat")
    if not (exp and iat):
        print(f"  {name}: brak exp/iat w payloadzie")
        return None
    life = exp - iat
    d, rem = divmod(life, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    print(f"  {name}: lifetime = {life}s  ({d}d {h}h {m}min)")
    print(f"      iat={datetime.fromtimestamp(iat, timezone.utc):%Y-%m-%d %H:%M:%SZ}"
          f"  exp={datetime.fromtimestamp(exp, timezone.utc):%Y-%m-%d %H:%M:%SZ}")
    return exp


def main():
    cfg = Cfg(json.load(open("config_test.json", encoding="utf-8")))
    print(f"Środowisko: {cfg.get('ksef', 'environment')}\n")

    c = KSeFClient(cfg)
    if not c.authenticate():
        print("✗ uwierzytelnienie nieudane")
        return 1

    print("[1] Tokeny zaraz po /auth/token/redeem:")
    describe("accessToken ", c.access_token)
    exp_refresh_before = describe("refreshToken", c.refresh_token)

    print("\n[2] Wywołuję /auth/token/refresh...")
    r = requests.post(
        f"{c.base_url}/v2/auth/token/refresh",
        headers={"Authorization": f"Bearer {c.refresh_token}",
                 "X-Error-Format": "problem-details"},
        timeout=30,
    )
    print(f"    HTTP {r.status_code}")
    if r.ok:
        body = r.json()
        print(f"    pola odpowiedzi: {list(body.keys())}")
        got_new_refresh = "refreshToken" in body
        print(f"    czy zwrócono NOWY refreshToken: {'TAK' if got_new_refresh else 'NIE'}")
        if "accessToken" in body:
            print("    nowy accessToken:")
            describe("accessToken ", body["accessToken"]["token"])

    print("\n[3] Czy ważność refresh tokena się przesunęła?")
    exp_after = claims(c.refresh_token).get("exp")
    if exp_refresh_before and exp_after:
        delta = exp_after - exp_refresh_before
        print(f"    exp przed = {exp_refresh_before}, po = {exp_after}, różnica = {delta}s")
        print(f"    => {'PRZESUNIĘTA (sliding)' if delta > 0 else 'BEZ ZMIAN (okno stałe)'}")

    print("\n[4] Sprzątanie: zamykam sesję")
    rc = requests.delete(
        f"{c.base_url}/v2/auth/sessions/current",
        headers={"Authorization": f"Bearer {c.access_token}"},
        timeout=30,
    )
    print(f"    HTTP {rc.status_code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
