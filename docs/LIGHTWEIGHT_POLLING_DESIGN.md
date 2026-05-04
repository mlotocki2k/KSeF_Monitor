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

- `pageSize=10` — minimum wg spec (`min=10, max=250, default=10`), wystarczy do detekcji
- `sortOrder=Desc` — najnowsze pierwsze (dla scenariusza przyrostowego spec zaleca `Asc` + `dateType=PermanentStorage`; `Desc` OK dla samej detekcji)
- `dateFrom = lastSeen` — tylko faktury po ostatnio widzianej

**Wykrycie:** `len(response.invoices) > 0`

> ⚠️ Response **nie ma `totalCount`**. Schema `QueryInvoicesMetadataResponse`: tylko `invoices[]`, `hasMore`, `isTruncated`.

### Constrainty endpointu (z OpenAPI v2.4)

- **Brak NIPa w body** — `InvoiceQueryFilters.required = [dateRange, subjectType]`. Kontekst NIPa pochodzi z Bearer tokena (server-side mapping). Pola `sellerNip` / `buyerIdentifier` to opcjonalne filtry, nie identyfikacja usera.
- **`dateRange` max 3 miesiące** — przy resume po długim downtime trzeba paginować po dacie (kolejne 3-miesięczne okna).
- **Wymagane uprawnienie `InvoiceRead`** — token musi je mieć. Sprawdzić przy rejestracji w SaaS Workerze (jednorazowy probe call) i odrzucić tokeny bez uprawnień.
- **`subjectType` ma 4 wartości** — `Subject1` (sprzedawca), `Subject2` (nabywca), `Subject3`, `SubjectAuthorized`. Dla pełnego obrazu trzeba pollować wszystkie 4 → 4 calls/cykl/user. Wpływ na matematykę limitów:

| Subjecty | Min interwał (limit 20/h) |
|---|---|
| 1 | 4 min |
| 2 | 7 min |
| 3 | 10 min |
| 4 | 13 min |

Domyślnie wystarczą `Subject1` + `Subject2` (sprzedawca/nabywca) — pokrywa standardowy use case. `Subject3` / `SubjectAuthorized` opcjonalne (per-user opt-in w app).

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

## Przyszłość: CF Worker SaaS (zero-knowledge)

> Założenie krytyczne: **Worker nie przechowuje NIPa ani tokena KSeF w postaci jawnej.** Compromise KV nie może ujawnić poświadczeń userów ani powiązać ich z firmą.

### Schemat KV (per device)

```
key:    deviceId = HMAC-SHA256(server_pepper, apnsToken_at_register)
value:  {
    encToken:     AES-256-GCM(dataKey, ksefToken),   // ciphertext + IV + tag
    encDataKey:   KMS.encrypt(rootKey, dataKey),     // envelope wrap
    apnsToken:    <do wysyłki push>,
    lastSeenKsef: <ksefNumber, NIE timestamp>,
    expiresAt:    now + 30d
}
```

- **Brak NIPa** — token KSeF jest server-side związany z NIPem, Worker nie potrzebuje go znać.
- **Brak metadanych faktur** — push budowany inline z response KSeF, KV nie widzi kwot, kontrahentów ani numerów faktur.
- **Kursor jako `ksefNumber`** zamiast timestampu — nie ujawnia wzorców aktywności.
- **`deviceId` opaque** — compromise KV daje atakującemu listę APNs tokenów + zaszyfrowane blob, ale nie wie czyje są.
- **Root key w Cloudflare Secrets / external KMS**, nie w KV. Plaintext token istnieje tylko w RAM scope iteracji crona.

### Cykl crona

```
Cron Worker co 5 min
    └─ foreach record in KV (TTL filter)
          ├─ dataKey  = KMS.decrypt(encDataKey)
          ├─ ksefToken = AES-256-GCM.decrypt(dataKey, encToken)   // RAM only
          ├─ POST /invoices/query/metadata
          │      Authorization: Bearer ksefToken
          │      body: { dateRange: {...}, subjectType: ... }
          │      params: pageSize=10, sortOrder=Desc
          ├─ if invoices[] non-empty:
          │      ├─ APNs push (treść z metadata, inline)
          │      └─ KV.update(lastSeenKsef = invoices[0].ksefNumber)
          └─ wipe ksefToken / dataKey z RAM
```

### Lifecycle tokena

- **TTL 30 dni** — po wygaśnięciu rekord usunięty, user re-auth w iOS.
- **APNs feedback (unregistered)** → natychmiastowy DELETE rekordu.
- **Logout w iOS** → best-effort DELETE call do Workera + flag w app blokuje re-register bez re-auth.
- **Rotacja root key** kwartalnie, re-encrypt batch.

### Limity

```
Limit per token (KSeF server-side): 20 calls/hour
N userów = N × 20 calls/hour — brak współdzielenia
Worker dodatkowo rate-limit per deviceId by zapobiec abuse
```

---

## Model bezpieczeństwa

### Threat model

| Scenariusz | Skutek bez mitigacji | Mitigacja |
|---|---|---|
| Compromise KV (read-only) | Lista APNs + ciphertext tokenów. **Nie wystarczy do ataku** — potrzebny też root key z KMS. | Envelope encryption, root key poza KV. |
| Compromise Worker secret (KMS root key) | Możliwość deszyfracji wszystkich tokenów. | Krótkie TTL (30d), rotacja kwartalna, kill-switch invalidujący wszystkie rekordy. |
| Compromise Worker runtime (RCE) | Atakujący widzi plaintext tokeny w trakcie cron iteracji. | Minimalny attack surface, brak third-party deps w hot path, audit logging dostępu do KMS. |
| Lost device / kradzież iPhone | Token KSeF na urządzeniu (Keychain) + rekord w KV. | User wykonuje remote logout → DELETE rekordu. Token KSeF i tak w Keychain (Secure Enclave). |
| User logout w iOS | Rekord pozostaje w KV jeśli DELETE nie dojdzie. | TTL 30d gwarantuje wygaśnięcie. APNs feedback przyspiesza purge. |
| Rejestracja cudzego NIPa | Atakujący zna czyjś token KSeF i rejestruje na swoim iPhone. | Out of scope — token KSeF z założenia jest secret. Mitigacja po stronie KSeF (rotacja tokenów przez usera). |
| Złośliwy operator infra (Cloudflare insider) | Dostęp do KV + KMS. | External KMS (nie CF) podnosi koszt ataku. Akceptowalne ryzyko residualne. |

### Zasady operacyjne

- **No-log plaintext** — sanitizer w Workerze blokuje logowanie tokenów, NIPów, treści faktur.
- **Region pinning** KV w EU (RODO).
- **Audit log** każdego KMS.decrypt — kto, kiedy, jaki deviceId. Anomalie → alert.
- **Emergency kill-switch** — globalny flag przerywający cron + invalidujący wszystkie rekordy w KV.
- **Brak persystencji treści faktur** w infra Workera — wszystko leci od razu w APNs payload, nigdzie się nie zapisuje.

### Czego Worker celowo NIE wie

- NIPa usera.
- Numerów faktur poza ostatnim `ksefNumber` jako kursorem.
- Kwot, kontrahentów, dat wystawienia.
- Tożsamości właściciela urządzenia.
- Historii pollingu poza `lastSeenKsef`.

---

## Powiązane dokumenty

- [KSEF_API_LIMITATIONS.md](KSEF_API_LIMITATIONS.md) — pełna tabela limitów per endpoint
- [RATE_LIMITING_DESIGN.md](RATE_LIMITING_DESIGN.md) — globalny rate limiter (sliding window)
- [DATABASE_DESIGN.md](DATABASE_DESIGN.md) — InvoiceArtifact download queue

---

**Ostatnia aktualizacja:** 2026-05-04
**Wersja API:** v2.4.0
