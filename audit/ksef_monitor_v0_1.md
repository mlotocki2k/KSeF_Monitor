# Audyt Kodu — KSeF Monitor v0.3

> Data audytu: 2026-02-20

---

## 🟢 Co działa dobrze

### Architektura i struktura

Projekt ma czytelną, modularną strukturę. Rozdzielenie odpowiedzialności między `ksef_client.py`, `invoice_monitor.py`, `config_manager.py` i `secrets_manager.py` jest logiczne i dobrze utrzymane. Każdy moduł ma jedną odpowiedzialność.

### Bezpieczeństwo

Zarządzanie sekretami jest przemyślane — hierarchia (env vars → Docker secrets → config file) z dokumentacją dla każdego środowiska. RSA-OAEP do szyfrowania tokenu w przepływie autentykacji KSeF jest poprawne. Oddzielenie `config.secure.json` od sekretów to dobra praktyka.

### System szablonów (v0.3)

Jinja2 z fallbackiem na wbudowane szablony, custom filtry (`money`, `date`, `json_escape`), override przez użytkownika — solidna implementacja. Dokumentacja `TEMPLATES.md` jest kompletna.

### Obsługa błędów

Retry przy wygaśnięciu tokenu (401 → refresh → re-auth → fallback), `exc_info=True` w logach błędów, graceful shutdown z rewokacją sesji — właściwe podejście.

---

## 🟡 Rzeczy do poprawy

### 1. Deduplikacja faktur przez MD5 jest krucha

`last_check.json` z MD5-hashem jest niestabilne — hash jest zależny od kolejności kluczy w JSON-ie z API KSeF. Lepsze podejście: deduplikacja po `ksefReferenceNumber` (unikalny identyfikator po stronie KSeF). To też bloker dla v0.3 (baza danych).

### 2. Brak retry z backoffem w `_wait_for_auth_status`

Polling statusu autentykacji ma stały `time.sleep(2)` bez exponential backoff. Przy przeciążeniu API KSeF może to generować odpowiedzi 429.

### 3. `requests` bez session pooling

Każde wywołanie `requests.get/post` tworzy nowe połączenie TCP. `requests.Session()` z connection poolingiem zmniejszyłoby latencję i liczbę połączeń, szczególnie podczas pollingu.

### 4. ReportLab zakomentowany w `requirements.txt`

PDF generation jest dostępne przez `save_pdf: true` w configu, ale zależność jest zakomentowana. Użytkownik dostanie runtime error, nie instalacyjny. Warto to odkomentować lub dać wyraźny check przy starcie.

### 5. `invoice_pdf.html.j2` — polskie znaki jako encje HTML

Szablon ma `&#322;` (ł), `&#347;` (ś) itd. zamiast bezpośrednio UTF-8. xhtml2pdf obsługuje UTF-8, więc to niepotrzebne i utrudnia edycję szablonu przez użytkownika.

### 6. Brak walidacji wejść w `get_invoice_xml`

Metoda przyjmuje `ksef_number: str` bez walidacji formatu. Walidacja regex jest w skrypcie testowym (`test_invoice_pdf.py`), ale powinna być w `KSeFClient`. Teraz błędny numer powoduje HTTP 404/400 zamiast czytelnego błędu.

### 7. Metrics shutdown — race condition

W `shutdown()`: najpierw `metrics.shutdown()`, potem `revoke_current_session()`. Jeśli rewokacja sesji jest długa (timeout), metryki mogą nie zdążyć się zapisać. Odwrócona kolejność byłaby bezpieczniejsza.

---

## 🔴 Problemy krytyczne

### 1. Brak testów jednostkowych i integracyjnych

Cały kod produkcyjny (autentykacja, monitoring, PDF generation, szablony) nie ma pokrycia testami. ROADMAP wymienia testy dopiero w v0.4, ale dla tak wrażliwego systemu (faktury, token, KSeF API) brak testów to duże ryzyko regresji przy każdej zmianie.

### 2. Token KSeF logowany w debug

W `_get_challenge()` jest `logger.info(f"Challenge response: {data}")`. Jeśli response zawiera wrażliwe pola, trafiają do logów. Warto logować tylko wybrane pola (`challenge`, `timestampMs`), nie cały response.

### 3. Brak limitu przechowywanych hashy w `last_check.json`

Stan deduplikacji rośnie w nieskończoność. Po roku monitorowania plik może mieć tysiące MD5. Brak TTL ani limitu — przy dużej liczbie faktur to problem pamięciowy i I/O.

### 4. Brak obsługi KSeF maintenance windows

KSeF API ma planowane okna serwisowe. Monitor wysyła wtedy powiadomienia o błędach co interwał schedulera. Brak rozróżnienia między błędem sieciowym a planowaną niedostępnością KSeF.

---

## 📋 Priorytety przed v0.4

W kolejności ważności:

1. Zmienić deduplikację z MD5 na `ksefReferenceNumber` — bez tego baza danych (v0.3 punkt 3) nie ma sensu
2. Dodać walidację numeru KSeF w `KSeFClient.get_invoice_xml()`
3. Usunąć logowanie całego response w `_get_challenge()`
4. Dodać TTL/limit do stanu deduplikacji
5. Odkomentować `reportlab` w `requirements.txt` lub dodać check na starcie
6. Napisać testy dla `InvoiceXMLParser` i `TemplateRenderer` zanim pójdą do v0.4

---

## Ogólna ocena

Projekt jest dobrze pomyślany architektonicznie i ma solidną dokumentację. Główne ryzyko to brak testów i krucha deduplikacja — oba problemy będą boleć przy wdrożeniu bazy danych w v0.3. Bezpieczeństwo sekretów i system szablonów to mocne strony, które warto utrzymać w tej formie.
