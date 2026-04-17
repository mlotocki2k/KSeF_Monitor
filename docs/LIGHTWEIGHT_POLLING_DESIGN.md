# Lightweight Polling — detekcja nowych faktur bez pobierania XML

Dokument opisuje architekturę lekkiego pollingu KSeF API na potrzeby:
- **iOS push notifications** — szybkie informowanie o nowych fakturach
- **Przyszłego SaaS/Worker** — multi-user polling bez własnego serwera

---

## Problem

Obecny monitor pobiera metadane + XML w jednym cyklu. To kosztowne i nieoptymalne gdy celem jest tylko wykrycie _czy_ pojawiły się nowe faktury.

---

## Kluczowy endpoint

```
POST /invoices/query/metadata
```

**Limity (z OpenAPI spec `x-rate-limits`):**

| /sec | /min | /hour |
|---|---|---|
| 8 | 16 | **20** |

To **jedyny** endpoint umożliwiający wykrycie nowych faktur. Brak:
- endpointu "count only"
- WebSocket / server-sent events
- webhooków po stronie KSeF

---

## Matematyka limitów

| Scenariusz | Calls/hour | Limit | Status |
|---|---|---|---|
| Poll co 60s, 1 subject | 60 | 20 | ❌ 3× przekroczony |
| Poll co 60s, 2 subjects | 120 | 20 | ❌ 6× przekroczony |
| Poll co 3 min, 1 subject | 20 | 20 | ⚠️ na granicy |
| Poll co 4 min, 1 subject | 15 | 20 | ✅ bezpieczny |
| Poll co 4 min, 2 subjects | 30 | 20 | ❌ przekroczony |
| Poll co 7 min, 2 subjects | ~17 | 20 | ✅ bezpieczny |

**Minimum bezpieczne: 4 min (1 subject) / 7 min (oba subjects)**

---

## Request — minimum danych

```http
POST /invoices/query/metadata?pageSize=10&pageOffset=0&sortOrder=Desc
Authorization: Bearer <token>
Content-Type: application/json

{
  "dateRange": {
    "dateType": "Invoicing",
    "from": "<lastSeenTimestamp>",
    "to": "<now>"
  },
  "subjectType": "subject2"
}
```

- `pageSize=10` — minimum wg spec, wystarczy do detekcji
- `sortOrder=Desc` — najnowsze pierwsze
- `dateFrom = lastSeen` — tylko faktury po ostatnio widzianej

**Wykrycie:** `len(response.invoices) > 0`

> ⚠️ Response **nie ma `totalCount`**. Schema `QueryInvoicesMetadataResponse`: tylko `invoices[]`, `hasMore`, `isTruncated`.

---

## Dane dostępne w metadanych (bez XML)

```
ksefNumber        — unikalny ID faktury w KSeF
invoiceNumber     — numer wystawcy
invoicingDate     — data przyjęcia w KSeF
issueDate         — data wystawienia
seller.name/nip   — dane sprzedawcy
buyer.name/nip    — dane nabywcy
netAmount         — kwota netto
grossAmount       — kwota brutto
vatAmount         — VAT w PLN
currency          — kod waluty
invoiceType       — Vat / Kor / Zal / VatRr...
```

**Metadata wystarczy na pełną treść push notification.** XML (`GET /invoices/ksef/{ksefNumber}`) pobieramy lazy — dopiero gdy user otwiera fakturę w app.

---

## Architektura dwufazowa

### Faza 1 — Detekcja (częsta, tania)

```
scheduler co 4/7 min
    └─ POST /invoices/query/metadata (pageSize=10, dateFrom=lastSeen)
           ├─ invoices[] empty → skip, update lastCheckTime
           └─ invoices[] non-empty →
                  ├─ zapis do DB: ksef_number + metadata (artifacts_downloaded=False)
                  ├─ send push notification (dane z metadata)
                  └─ update lastSeen = max(invoicingDate z listy)
```

Koszt per cykl: **1–2 API calls** (Subject1 + Subject2 osobno).

### Faza 2 — Artefakty (lazy, rate-limited)

```
background job lub na żądanie:
    └─ SELECT FROM invoices WHERE artifacts_downloaded=False
           └─ GET /invoices/ksef/{ksefNumber}  (hour limit: 64)
                  ├─ zapis XML do storage
                  ├─ generacja PDF
                  └─ UPDATE artifacts_downloaded=True
```

---

## Token vs certyfikat

KSeF v2.4 obsługuje wyłącznie **Bearer token**. Certyfikatowa autentykacja istniała w v1 (wycofane). W v2 **nie ma rozróżnienia** limitów — identyczne `x-rate-limits` niezależnie od metody autentykacji.

---

## Zmiany w Docker monitorze

W `invoice_monitor.py` oddzielić detekcję od pobierania artefaktów:

```python
def check_for_new_invoices(self):
    # Faza 1: detekcja (1-2 API calls)
    for subject_type in self.subject_types:
        invoices = self.ksef.get_invoices_metadata(
            date_from=self.last_seen,
            date_to=now,
            subject_type=subject_type,
            page_size=10,   # minimum — wystarczy do detekcji
        )
        for inv in invoices:
            if not self._is_seen(inv['ksefNumber']):
                db.save_invoice(inv, artifacts_downloaded=False)
                self._send_notification(inv)  # dane z metadata, bez XML
        if invoices:
            self.last_seen = max(inv['invoicingDate'] for inv in invoices)

    # Faza 2: artefakty (osobny cykl / background)
    # → patrz InvoiceArtifact download queue w DATABASE_DESIGN.md
```

---

## Przyszłość: CF Worker SaaS

```
Cron Worker co 5 min
    └─ foreach user in KV store
          ├─ KV: {nip}:{token_hash} → {lastSeen, deviceToken, settings}
          ├─ POST /invoices/query/metadata (token usera, pageSize=10)
          └─ APNs push → iOS jeśli invoices[] non-empty

Limity per NIP+token → każdy user ma własny budżet 20/hour
N userów = N × 20 calls/hour — brak współdzielenia limitów między userami
```

---

## Powiązane dokumenty

- [KSEF_API_LIMITATIONS.md](KSEF_API_LIMITATIONS.md) — pełna tabela limitów per endpoint
- [RATE_LIMITING_DESIGN.md](RATE_LIMITING_DESIGN.md) — globalny rate limiter (sliding window)
- [DATABASE_DESIGN.md](DATABASE_DESIGN.md) — InvoiceArtifact download queue

---

**Ostatnia aktualizacja:** 2026-04-17
**Wersja API:** v2.4.0
