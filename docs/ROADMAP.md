# Roadmap

## v0.2 ✅ (zrobione)
**Cel:** podstawowa obserwowalność + dostęp do PDF

- [x] Endpoint pod Prometheusa
- [x] Pobieranie obrazu/PDF wybranej faktury

**DoD:** metryki widoczne w Prometheusie, PDF/obraz faktury do pobrania dla wskazanego dokumentu.

---

## v0.3 (Fundament: templating + DB)
**Cel:** ustandaryzować komunikację i zacząć trwale trzymać dane o fakturach

### 1) Powiadomienia oparte o template
- system template (np. Jinja2) + możliwość wyboru template per kanał
- dokumentacja: zmienne/placeholdery + przykłady

### 2) Template generowania obrazu faktury
- HTML/CSS template → render do PNG/PDF (lub tylko PNG)
- dokumentacja: jak zmienić wygląd, jak podmienić logo/kolory, lista pól

### 3) Przeniesienie informacji o fakturach do bazy
- model danych rozdzielony “per subject, per NIP”
- indeksy pod najczęstsze zapytania (np. subject + nip + timestamp)
- migracja: zapis przy pobraniu/detekcji faktury

**Zależności:** v0.2  
**DoD:** powiadomienia i obraz faktury generują się wyłącznie z template; faktury lądują w DB i da się je filtrować per subject/NIP.

---

## v0.4 (Stabilizacja + API pod UI) — propozycja
**Cel:** przygotować solidne backend API i jakość pod web UI + initial load

- Warstwa API dla UI  
  - endpointy: statystyki / lista / szczegóły / podgląd  
  - paginacja, sortowanie, filtrowanie (subject, nip, role: sprzedawca/kupujący, daty)
- Idempotencja i deduplikacja  
  - klucz unikalny faktury, retry-safe zapisy
- Obsługa błędów i retry  
  - polityka retry dla KSeF, timeouts, backoff
- Metryki + logi “operacyjne”  
  - liczba nowych faktur/okno czasowe, błędy API, czasy odpowiedzi
- Testy i CI  
  - testy jednostkowe logiki DB + templating  
  - testy integracyjne (mock KSeF / sandbox)
- Szkielet uprawnień  
  - podstawowe auth (np. token) dla web UI/admin

**Zależności:** v0.3  
**DoD:** UI może bazować na stabilnym API; system jest odporny na retry i ma podstawową telemetrię operacyjną.

---

## v0.5 (Initial load + Web UI: odczyt)
**Cel:** pierwszy sensowny produkt dla użytkownika: dane + podgląd

### 1) Initial load
- od `2026-02-01` albo data definiowana w config
- tryb: jednorazowy import + zapis do DB + raport (ile pobrano, ile pominięto)

### 2) Interfejs webowy (odczyt)
- pokazywanie ile nowych faktur od ostatniego sprawdzenia: **per subject, per NIP**
- pokazywanie ile ogólnie faktur: **per subject, per NIP** (sprzedawcy i kupującego)
- lista wszystkich faktur (z bazy): filtry/sort/paginacja
- podgląd wybranej faktury: pobranie po API z KSeF konkretnej faktury (z cache, jeśli już jest)

**Zależności:** v0.4  
**DoD:** użytkownik widzi dashboard + listę + podgląd; initial load działa powtarzalnie bez duplikatów.

---

## v1.0 (Web UI: konfiguracja / panel admin)
**Cel:** samodzielna konfiguracja bez grzebania w plikach

**Panel konfiguracji:**
- konfiguracja schedulera (częstotliwość, okna czasowe, tryb “catch-up”)
- konfiguracja notifiera (kanały, template, routing per subject/NIP)
- konfiguracja Prometheusa (enable/disable, port, ścieżka, metryki)
- konfiguracja MQ (połączenie, retry policy, DLQ jeśli używacie)

**Zależności:** v0.5  
**DoD:** wszystko da się skonfigurować z UI, a zmiany wchodzą w życie bez ręcznych edycji configów (lub z kontrolowanym restartem usługi).

---

## v2.0 (Multi-NIP)
**Cel:** obsługa wielu NIP-ów w jednym wdrożeniu

- model tenantów: NIP jako tenant + separacja danych (DB, konfiguracja, uprawnienia)
- UI: przełącznik NIP / lista NIP-ów / role
- scheduler: osobne harmonogramy per NIP (lub wspólny z kolejką)
- notifier: routing per NIP
- monitoring: metryki per NIP

**Zależności:** v1.0  
**DoD:** można dodać drugi NIP i wszystko (import, lista, powiadomienia, metryki) działa niezależnie.

---

## Kluczowe zależności (krótko)
- **DB (v0.3)** jest krytyczne przed sensownym UI (v0.5)
- **API + stabilizacja (v0.4)** minimalizuje “dług” zanim dojdzie UI
- **Initial load (v0.5)** najlepiej robić dopiero gdy masz deduplikację/idempotencję (v0.4)