# Tworzenie tokena KSeF — przewodnik krok po kroku

Token autoryzacyjny KSeF jest wymagany do komunikacji z API Krajowego Systemu e-Faktur.
KSeF Monitor potrzebuje tokena wyłącznie do **przeglądania faktur** (odczyt) — nie wymaga uprawnień do wystawiania, modyfikowania ani usuwania faktur.

---

## Wymagania wstępne

- Aktywne konto w portalu KSeF (jako podatnik lub osoba upoważniona)
- Profil zaufany, e-dowód lub kwalifikowany podpis elektroniczny (do logowania w portalu)
- Dostęp do NIP podmiotu, dla którego tworzysz token

## Środowiska KSeF

| Środowisko | Portal | Przeznaczenie |
|------------|--------|---------------|
| **Test** | [ksef-test.mf.gov.pl](https://ksef-test.mf.gov.pl/web/login) | Testowanie integracji, dane testowe |
| **Demo** | [ksef-demo.mf.gov.pl](https://ksef-demo.mf.gov.pl/web/login) | Testy z danymi zbliżonymi do produkcyjnych |
| **Produkcja** | [ksef.mf.gov.pl](https://ksef.mf.gov.pl/web/login) | Prawdziwe faktury |

> **Zalecenie:** Zacznij od środowiska **test**, aby zweryfikować poprawność konfiguracji. Po potwierdzeniu działania przejdź na produkcję.

---

## Tworzenie tokena — krok po kroku

### Krok 1: Zaloguj się do portalu KSeF

1. Otwórz portal KSeF odpowiedni dla wybranego środowiska (linki powyżej)
2. Kliknij **Zaloguj się**
3. Wybierz metodę uwierzytelnienia:
   - **Profil zaufany** (ePUAP) — najpopularniejsza metoda
   - **e-Dowód** — dowód osobisty z warstwą elektroniczną
   - **Kwalifikowany podpis elektroniczny** — certyfikat kwalifikowany
4. Przejdź proces uwierzytelnienia

### Krok 2: Wybierz kontekst (NIP)

1. Po zalogowaniu wybierz **kontekst podmiotu** (NIP), dla którego chcesz utworzyć token
2. Jeśli masz dostęp do wielu podmiotów, wybierz odpowiedni z listy
3. Upewnij się, że wybrany NIP zgadza się z wartością `nip` w `config.json`

### Krok 3: Przejdź do zarządzania tokenami

1. W menu głównym portalu znajdź sekcję **Tokeny** (lub **Zarządzanie tokenami**)
2. Kliknij aby wejść do panelu zarządzania tokenami

### Krok 4: Wygeneruj nowy token

1. Kliknij **Generuj token** (lub **Utwórz nowy token**)
2. Podaj **nazwę tokena** — np. `KSeF Monitor - odczyt faktur`
   - Nazwa jest tylko opisowa, służy do identyfikacji tokena w portalu

### Krok 5: Ustaw uprawnienia (TYLKO ODCZYT)

**To najważniejszy krok.** KSeF Monitor potrzebuje wyłącznie uprawnień do przeglądania faktur.

Zaznacz **tylko** następujące uprawnienia:

| Uprawnienie | Zaznacz? | Opis |
|-------------|----------|------|
| **Przeglądanie faktur** | **TAK** | Odczyt metadanych i treści faktur |
| **Pobieranie faktur** | **TAK** | Pobieranie XML faktur (potrzebne do generowania PDF) |
| **Pobieranie UPO** | **TAK** | Pobieranie Urzędowego Poświadczenia Odbioru |
| Wystawianie faktur | **NIE** | Monitor nie wystawia faktur |
| Zarządzanie tokenami | **NIE** | Nie jest potrzebne |
| Zarządzanie uprawnieniami | **NIE** | Nie jest potrzebne |

> **Zasada minimalnych uprawnień:** Nadaj tokenowi tylko te uprawnienia, które są niezbędne do działania monitora. Mniejsze uprawnienia = mniejsze ryzyko w przypadku wycieku tokena.

> **Uwaga:** Nazwy uprawnień mogą się różnić w zależności od wersji portalu KSeF. Szukaj uprawnień związanych z **odczytem/przeglądaniem** faktur i **unikaj** uprawnień do **wystawiania/modyfikowania**.

### Krok 6: Potwierdź i skopiuj token

1. Kliknij **Generuj** / **Utwórz** / **Zatwierdź**
2. Portal wyświetli wygenerowany token
3. **Natychmiast skopiuj token** — w zależności od portalu może być wyświetlony tylko raz
4. Token ma postać długiego ciągu znaków alfanumerycznych

> **Skopiuj token od razu!** Niektóre wersje portalu KSeF nie pozwalają na ponowne wyświetlenie tokena. Jeśli go zgubisz, będziesz musiał wygenerować nowy.

### Krok 7: Zapisz token bezpiecznie

Token jest wrażliwą daną — traktuj go jak hasło.

**Metoda 1: Plik .env (rozwój / testowanie)**
```bash
# W pliku .env
KSEF_TOKEN=twoj-skopiowany-token
```
```bash
chmod 600 .env
```

**Metoda 2: Docker Secret (produkcja)**
```bash
echo "twoj-skopiowany-token" | docker secret create ksef_token -
```

**Metoda 3: Config file (NIE ZALECANE)**
```json
{
  "ksef": {
    "token": "twoj-skopiowany-token"
  }
}
```

Więcej o bezpiecznym przechowywaniu: [SECURITY.md](SECURITY.md)

---

## Konfiguracja w KSeF Monitor

Po uzyskaniu tokena, uzupełnij `config.json`:

```json
{
  "ksef": {
    "environment": "test",
    "nip": "1234567890",
    "token": "loaded-from-env"
  }
}
```

| Pole | Opis |
|------|------|
| `environment` | Musi odpowiadać portalowi, z którego pochodzi token: `test`, `demo` lub `prod` |
| `nip` | Dokładnie 10 cyfr, bez myślników i spacji |
| `token` | Token wpisany bezpośrednio lub ładowany z `.env` / Docker secret |

> **Token musi odpowiadać środowisku.** Token wygenerowany w portalu testowym (`ksef-test.mf.gov.pl`) działa tylko z `"environment": "test"`. Token produkcyjny — tylko z `"environment": "prod"`.

---

## Ważność tokena

- Tokeny KSeF mają **ograniczoną ważność** — sprawdź datę wygaśnięcia w portalu
- Zalecenie: ustaw sobie przypomnienie o odnowieniu tokena przed wygaśnięciem
- Po wygaśnięciu tokena monitor przestanie działać — w logach pojawią się błędy autentykacji

**Rotacja tokena:**
1. Wygeneruj nowy token w portalu KSeF (kroki 3-6)
2. Zaktualizuj token w `.env` lub Docker secret
3. Zrestartuj kontener: `docker-compose restart`
4. (Opcjonalnie) Usuń stary token w portalu KSeF

---

## Rozwiązywanie problemów

### Token nie działa — błąd autentykacji

```
ERROR - Authentication failed: 401 Unauthorized
```

**Sprawdź:**
1. Czy token nie wygasł — zaloguj się do portalu i sprawdź datę ważności
2. Czy `environment` w config odpowiada portalowi źródłowemu tokena
3. Czy `nip` jest poprawny (10 cyfr, bez myślników)
4. Czy token został skopiowany kompletnie (bez obcięcia)

### Token ma za mało uprawnień

```
ERROR - Forbidden: 403
```

**Sprawdź:**
- Czy token ma uprawnienie do **przeglądania faktur**
- W razie potrzeby wygeneruj nowy token z poprawnymi uprawnieniami

### Nie mogę zalogować się do portalu KSeF

- Sprawdź czy profil zaufany jest aktywny: [pz.gov.pl](https://pz.gov.pl/)
- Wyczyść cache przeglądarki lub spróbuj w trybie incognito
- Środowisko testowe może mieć odrębne konta — zarejestruj się ponownie jeśli potrzeba

---

## Dobre praktyki

- **Osobne tokeny** dla każdego środowiska (test / produkcja)
- **Osobne tokeny** dla różnych aplikacji korzystających z KSeF
- **Tylko uprawnienia do odczytu** — monitor nie potrzebuje więcej
- **Nazwij token opisowo** — np. `KSeF Monitor v0.2 - odczyt` — ułatwia zarządzanie
- **Rotuj tokeny regularnie** — co 3-6 miesięcy lub zgodnie z polityką bezpieczeństwa
- **Nie udostępniaj tokena** — nie wklejaj w publiczne repozytoria, czaty, emaile
- **Monitoruj logi** — błędy 401/403 mogą oznaczać problem z tokenem

---

## Przydatne linki

- [Portal KSeF — produkcja](https://ksef.mf.gov.pl/web/login)
- [Portal KSeF — test](https://ksef-test.mf.gov.pl/web/login)
- [Portal KSeF — demo](https://ksef-demo.mf.gov.pl/web/login)
- [Dokumentacja KSeF API](https://github.com/CIRFMF/ksef-docs)
- [SECURITY.md](SECURITY.md) — Bezpieczne przechowywanie tokena
- [QUICKSTART.md](QUICKSTART.md) — Szybki start w 5 minut
