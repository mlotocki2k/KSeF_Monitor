# Przegląd optymalizacji KSeF Monitor v0.3

Data analizy: 2026-02-20

---

## Podsumowanie

| Priorytet | Znalezisk | Szacowany zysk |
|-----------|-----------|----------------|
| KRYTYCZNY | 3 | Poprawność działania |
| WYSOKI | 6 | Redukcja ~130 linii duplikacji, lepsza wydajność |
| ŚREDNI | 5 | Czystość kodu, spójność |
| NISKI | 4 | Kosmetyka, dokumentacja |

---

## KRYTYCZNY

### K1. Nieprawidłowe rate limiting przy pobieraniu artefaktów

**Plik:** `app/invoice_monitor.py:254-256`

**Problem:** `time.sleep(2)` po każdej fakturze to 30 req/min, ale `_save_invoice_artifacts()` wykonuje 1-3 zapytania API (XML + opcjonalnie UPO). Przy 10 fakturach = 20-30 requestów w ~20s = **60-90 req/min**, przekracza limit 30/min.

**Rekomendacja:** Przenieść sleep między poszczególne zapytania API wewnątrz `_save_invoice_artifacts()`, nie między fakturami. Alternatywnie: token bucket / leaky bucket limiter.

---

### K2. Brak paginacji w `get_invoices_metadata()`

**Plik:** `app/ksef_client.py:457-458`

**Problem:** Zapytanie ustawia `pageSize: 100, pageOffset: 0` i pobiera tylko pierwszą stronę. Jeśli jest 150+ faktur w okresie, **50 zostanie pominiętych**.

**Rekomendacja:** Dodać pętlę paginacji — sprawdzać `numberOfElements` vs `pageSize` i pobierać kolejne strony.

---

### K3. Kaskadowa re-autentykacja przy 401 może wygenerować 22+ requestów

**Plik:** `app/ksef_client.py:466-476, 591-601, 657-667`

**Problem:** Przy 401 kolejno: `refresh_access_token()` (1 req) → `authenticate()` (do 20 req) → retry oryginalnego zapytania. Jeden 401 = potencjalnie 22+ requestów API, co łatwo wyczerpuje limit.

**Rekomendacja:** Dodać flagę `_is_reauthenticating` zapobiegającą kaskadzie. Albo: jeden retry z refresh, jeśli nie działa — fail fast.

---

## WYSOKI

### W1. Duplikacja obsługi 401 — 3 identyczne bloki

**Pliki:** `app/ksef_client.py:466-476, 591-601, 657-667`

**Problem:** Identyczny pattern 10-liniowy powtórzony 3x w `get_invoices_metadata()`, `get_invoice_xml()`, `get_invoice_upo()`.

**Rekomendacja:** Wyciągnąć do metody `_request_with_auth(method, url, **kwargs)` która opakowuje `_request_with_retry()` + obsługę 401.

---

### W2. Duplikacja pętli powiadomień w NotificationManager — 4 identyczne pętle

**Plik:** `app/notifiers/notification_manager.py:110-125, 147-155, 181-189, 214-223`

**Problem:** 4 metody (`send_invoice_notification`, `send_notification`, `send_error_notification`, `test_connection`) zawierają identyczną pętlę iteracji po notifierach z try/except i licznikiem sukcesów (~15 linii x4 = 60 linii duplikacji).

**Rekomendacja:** Wyciągnąć do `_broadcast(callback)` — jedna pętla, callback per notifier.

---

### W3. Duplikacja exception handling w notifierach — 8 bloków

**Pliki:** Wszystkie 5 notifierów + manager

**Problem:** Identyczny pattern:
```python
except requests.exceptions.RequestException as e:
    logger.error(f"Failed to send {CHANNEL}: {e}")
    if hasattr(e, 'response') and e.response is not None:
        logger.error(f"Response status: {e.response.status_code}")
    return False
```
Powtórzony 8x = ~40 linii duplikacji.

**Rekomendacja:** Wyciągnąć do `BaseNotifier._handle_request_error(e, context)`.

---

### W4. Duplikacja `test_connection()` i `send_error_notification()` w notifierach

**Pliki:** Wszystkie 5 notifierów

**Problem:** `test_connection()` (~12 linii x5) i `send_error_notification()` (~6 linii x5) są praktycznie identyczne. Łącznie ~90 linii duplikacji.

**Rekomendacja:** Przenieść domyślną implementację do `BaseNotifier`. Notifiery nadpisują tylko jeśli potrzebują innej logiki.

---

### W5. PushoverNotifier — hardcoded timeout, brak konfiguracji

**Plik:** `app/notifiers/pushover_notifier.py:83, 117`

**Problem:** `timeout=10` zahardkodowane. Wszystkie inne notifiery (Slack, Discord, Email, Webhook) czytają timeout z konfiguracji. Pushover ignoruje ustawienie użytkownika.

**Rekomendacja:** Dodać `self.timeout = pushover_config.get("timeout", 10)` w `__init__` i użyć w `send_notification()` oraz `_send_rendered()`.

---

### W6. Importy wewnątrz metod zamiast na poziomie modułu

**Plik:** `app/ksef_client.py:107, 110`

**Problem:** `from email.utils import parsedate_to_datetime` i `from datetime import datetime, timezone` importowane wewnątrz `_request_with_retry()` — przy każdym wywołaniu (choć Python cachuje moduły, to dodatkowy overhead lookup).

**Rekomendacja:** Przenieść na górę pliku.

---

## ŚREDNI

### S1. Stan odczytywany z dysku przy każdym cyklu sprawdzania

**Plik:** `app/invoice_monitor.py:208`

**Problem:** `load_state()` czyta `/data/last_check.json` (do 1000 wpisów) z dysku przy każdym cyklu monitoringu. Przy cyklu co 5 minut to 288 odczytów/dzień.

**Rekomendacja:** Cache stanu w pamięci, odczyt z dysku tylko przy starcie. Zapis na dysk po każdej zmianie (jak teraz).

---

### S2. Duplikacja konfiguracji w `__init__` notifierów

**Pliki:** Wszystkie 5 notifierów

**Problem:** Każdy notifier powtarza pattern:
```python
notifications_config = config.get("notifications") or {}
channel_config = notifications_config.get("channel") or {}
```

**Rekomendacja:** Przenieść do `BaseNotifier.__init__(config, channel_name)`.

---

### S3. Podwójne logowanie powiadomień

**Pliki:** `app/invoice_monitor.py:249-251` + `app/notifiers/notification_manager.py`

**Problem:** InvoiceMonitor loguje sukces/porażkę powiadomienia, a NotificationManager robi to samo. Duplikacja logów.

**Rekomendacja:** Usunąć logowanie z `invoice_monitor.py` — manager jest odpowiedzialny za raportowanie statusu.

---

### S4. Priority mappings tworzone przy każdej fakturze

**Plik:** `app/invoice_monitor.py:299-302`

**Problem:** Słowniki `priority_emojis`, `priority_names`, `priority_colors`, `priority_colors_int` tworzone od nowa przy każdym wywołaniu `build_template_context()`.

**Rekomendacja:** Przenieść do stałych klasowych.

---

### S5. Niespójne typy zwracane przy błędach w ksef_client

**Plik:** `app/ksef_client.py`

**Problem:**
- `_get_challenge()` → `None`
- `get_invoices_metadata()` → `[]`
- `get_invoice_xml()` → `None`
- `get_current_sessions()` → `[]`

Brak spójności: jedne metody zwracają `None`, inne `[]`.

**Rekomendacja:** Ujednolicić — listowe metody zwracają `[]`, obiektowe `None`. Dodać type hints.

---

## NISKI

### N1. Brak walidacji szablonów przy inicjalizacji

**Plik:** `app/template_renderer.py`

**Problem:** `TemplateRenderer.__init__()` nie sprawdza czy pliki szablonów istnieją. Błąd odkrywany dopiero przy pierwszym powiadomieniu.

**Rekomendacja:** Dodać `has_template()` check na starcie z logiem warning.

---

### N2. Brak `__del__` / context manager w KSeFClient

**Plik:** `app/ksef_client.py`

**Problem:** `requests.Session()` zamykana tylko w `revoke_current_session()`. Jeśli wyjątek przerwie pracę przed revoke, sesja HTTP nie jest zamykana.

**Rekomendacja:** Dodać `__del__` z `self.session.close()` lub zaimplementować `__enter__`/`__exit__`.

---

### N3. Brak dokumentacji algorytmu HMAC w WebhookNotifier

**Plik:** `app/notifiers/webhook_notifier.py:92-101`

**Problem:** HMAC-SHA256 signing zaimplementowany, ale brak docstringa opisującego format podpisu i jak odbiorca powinien go weryfikować.

**Rekomendacja:** Dodać docstring z opisem: header name, format, algorytm, przykład weryfikacji.

---

### N4. Redundantne sprawdzanie `is_configured` w notifierach

**Pliki:** Wszystkie 5 notifierów

**Problem:** `is_configured` sprawdzane zarówno w `send_notification()` jak i `_send_rendered()`. Jedno sprawdzenie na wejściu wystarczy.

**Rekomendacja:** Sprawdzać raz w `NotificationManager` przed wywołaniem notifiera.

---

## Statystyki kodu

| Komponent | Linie | Duplikacja |
|-----------|-------|------------|
| ksef_client.py | 690 | ~30 linii (401 handling) |
| invoice_monitor.py | 488 | ~15 linii (logowanie) |
| notifiers/ (7 plików) | 1,502 | ~130 linii |
| config_manager.py | 443 | — |
| invoice_pdf_generator.py | 1,106 | — |
| Reszta (scheduler, secrets, etc.) | 954 | — |
| **RAZEM** | **~6,183** | **~175 linii** |
