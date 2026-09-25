"""
Sonda granicy dateRange w POST /invoices/query/metadata (KSeF TEST).

KSeF API 2.7.1 podniosło limit dateRange z „3 miesięcy” do „100 dni w strefie UTC”.
Dla starego limitu empirycznie działał span 89 dni (`MAX_DATE_RANGE_DAYS = 90`),
więc zanim podbijemy stałe (ROADMAP §v0.6 pkt 8, wersja 0.6.5), mierzymy
faktyczną granicę na TEST: ostatni span z HTTP 200 i pierwszy z 400 [21405].

Użycie (token WYŁĄCZNIE ze zmiennej środowiskowej — nigdy w argumencie):
    read -rs KSEF_TOKEN && export KSEF_TOKEN   # wklej token, Enter
    export KSEF_NIP=1234567890
    python examples/probe_date_range.py

Zużycie limitów: 7 wywołań /invoices/query/metadata (limit TEST = PRD: 20/h).
Nie uruchamiaj równolegle z monitorem TEST na tym samym NIP. Na koniec sesja
KSeF jest unieważniana (DELETE /auth/sessions/current).
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ksef_client import KSeFClient  # noqa: E402

# Kolejność rosnąca — granica to przejście 200 → 400
SPANS = [
    timedelta(days=89),
    timedelta(days=90),
    timedelta(days=99),
    timedelta(days=100) - timedelta(seconds=1),
    timedelta(days=100),
    timedelta(days=100, seconds=1),
    timedelta(days=101),
]


class _ProbeConfig:
    """Minimalny config dla KSeFClient — tylko TEST, token z ENV."""

    def __init__(self, nip: str, token: str):
        self._data = {
            "ksef": {"environment": "test", "nip": nip, "token": token,
                     "auth_method": "token", "certificate": {}},
            "monitoring": {"date_type": "Invoicing"},
        }

    def get(self, section, key=None, default=None):
        value = self._data.get(section, {})
        return value if key is None else value.get(key, default)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def main() -> int:
    nip = os.environ.get("KSEF_NIP", "").strip()
    token = os.environ.get("KSEF_TOKEN", "").strip()
    if not nip or not token:
        print("Ustaw KSEF_NIP i KSEF_TOKEN (token przez `read -rs`, nie w argv).", file=sys.stderr)
        return 2

    client = KSeFClient(_ProbeConfig(nip, token))
    if "api-test" not in client.base_url:
        print(f"Odmowa: sonda tylko na TEST, base_url={client.base_url}", file=sys.stderr)
        return 2
    if not client.authenticate():
        print("Uwierzytelnienie nieudane.", file=sys.stderr)
        return 1

    url = f"{client.base_url}/{client.API_VERSION}/invoices/query/metadata"
    to = datetime.now(timezone.utc).replace(microsecond=0)
    last_ok, first_fail = None, None
    try:
        for span in SPANS:
            payload = {
                "subjectType": "Subject1",
                "dateRange": {"dateType": "Invoicing", "from": _fmt(to - span), "to": _fmt(to)},
            }
            r = client._make_authenticated_request(
                "POST", url, params={"pageSize": 10, "pageOffset": 0},
                headers={"Content-Type": "application/json"}, json=payload, timeout=30,
            )
            if r is None:
                print(f"{span}: brak odpowiedzi (auth)")
                return 1
            detail = "" if r.ok else client._extract_api_error_details(r)
            print(f"{span}: HTTP {r.status_code} {detail}")
            if r.ok:
                last_ok = span
            elif first_fail is None:
                first_fail = span
    finally:
        client.revoke_current_session()

    print(f"\nWYNIK (TEST, {_fmt(to)}): max przyjęty span = {last_ok}, pierwszy odrzucony = {first_fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
