# Moduł sprawdzania OpenAPI + schemat FA — analiza podejść

## Problem

KSeF API jest aktywnie rozwijane przez Ministerstwo Finansów. Zmiany mogą dotyczyć:
- **OpenAPI spec** — nowe/zmienione endpointy, parametry, formaty odpowiedzi → łamie `ksef_client.py`
- **Schemat FA (XSD)** — nowa struktura faktur → łamie parsowanie XML w `invoice_pdf_generator.py` i szablony

Aktualna wersja w repo: API `2.1.1` (build `2.1.1-pr-20260213.1`), schemat `FA(3)_v1-0E`.

## Trzy możliwe podejścia

### Opcja A: GitHub Actions (CI/CD) — scheduled workflow

```
Cron → pobierz spec z źródła → porównaj z /spec/ → raportuj diff → opcjonalnie issue/PR
```

**Zalety:**
- Zero wpływu na runtime aplikacji
- Nie wymaga uruchomionego kontenera
- Naturalnie pasuje do CI/CD (diff, issue, PR)
- Łatwo dodać analizę wpływu (grep endpointów z openapi vs ksef_client.py)

**Wady:**
- Wymaga dostępu do źródła spec (GitHub CIRFMF/ksef-docs lub API KSeF)
- Brak natychmiastowego powiadomienia w kanałach aplikacji (Pushover/Discord/etc.)

### Opcja B: Moduł w aplikacji (runtime check)

```
Scheduler → pobierz spec → porównaj hash/wersję → wyślij notyfikację kanałami
```

**Zalety:**
- Korzysta z istniejącej infrastruktury notyfikacji (5 kanałów)
- Monitoruje w tym samym cyklu co faktury
- Może od razu zareagować (np. warning w logach, metryka Prometheus)

**Wady:**
- Dokłada logikę niezwiązaną z core business (monitoring faktur)
- Wymaga pobierania dużych plików (openapi.json ~500KB) w runtime
- Komplikuje kontener Docker

### Opcja C: Hybrid — GitHub Action + notyfikacja

```
GA cron → pobierz spec → diff → jeśli zmiana: utwórz issue + webhook do aplikacji
```

**Zalety:**
- Analiza i diff po stronie CI (czyste)
- Notyfikacja dociera do użytkownika przez istniejący webhook
- Najlepsze z obu światów

## Rekomendacja: Opcja C — Hybrid (GitHub Actions + Pushover)

### Dlaczego

1. **Separacja odpowiedzialności** — aplikacja monitoruje faktury, CI monitoruje zmiany API. To dwa różne cykle życia.

2. **Źródło spec jest na GitHubie** — KSeF publikuje spec na `github.com/CIRFMF/ksef-docs`. GitHub Action ma natywny dostęp, nie trzeba proxy.

3. **Analiza wpływu jest statyczna** — porównanie endpointów z openapi.json z kodem w `ksef_client.py` to analiza kodu, nie runtime. Idealnie pasuje do CI.

4. **Schemat FA** — nowe wersje XSD publikowane są na `crd.gov.pl`. Workflow może pobrać i porównać hash.

5. **Pushover z GA** — Pushover API to prosty HTTP POST, wystarczy `curl` z workflow:
   ```yaml
   - name: Send Pushover notification
     if: steps.check.outputs.changed == 'true'
     run: |
       curl -sf -F "token=${{ secrets.PUSHOVER_API_TOKEN }}" \
            -F "user=${{ secrets.PUSHOVER_USER_KEY }}" \
            -F "title=KSeF Spec Change" \
            -F "message=${SUMMARY}" \
            -F "priority=1" \
            https://api.pushover.net/1/messages.json
   ```

6. **GitHub Issue** — oprócz push notification, workflow tworzy issue z pełnym diffem i analizą wpływu.

### Bezpieczeństwo GitHub Secrets

Secrets (`PUSHOVER_API_TOKEN`, `PUSHOVER_USER_KEY`) przechowywane jako **Repository Secrets**:

- **Szyfrowane at-rest** — libsodium sealed box
- **Write-only** — nawet owner po zapisaniu nie może odczytać wartości, tylko nadpisać
- **Maskowane w logach** — GitHub automatycznie zastępuje wartości `***`
- **Niedostępne w forkach** — forki nie mają dostępu do secrets repo nadrzędnego
- **Niedostępne w PR z forków** — workflow `pull_request` od zewnętrznych contributorów nie widzi secrets

Konfiguracja: `Settings → Secrets and variables → Actions → New repository secret`

#### Zasady bezpieczeństwa w workflow

1. **Trigger tylko cron + workflow_dispatch** — nigdy `pull_request` (fork mógłby odczytać secrets)
2. **Minimalne permissions** — `contents: read`, `issues: write`
3. **Nigdy nie echo-wać secrets** — bez `echo`, bez `curl -v`
4. **Pinować actions do SHA** — `actions/checkout@<sha>` zamiast `@v4` (ochrona przed supply-chain attack)

## Proponowana architektura

### Pliki

```
.github/workflows/spec-check.yml     ← Cron raz dziennie
scripts/check_openapi_changes.py      ← Logika porównania + analiza wpływu
scripts/check_schema_changes.py       ← Logika dla XSD
spec/openapi.json                     ← Referencyjna kopia (już jest)
spec/schemat_FA(3)_v1-0E.xsd         ← Referencyjna kopia (już jest)
```

### Workflow

1. Cron `0 6 * * *` (raz dziennie rano)
2. Pobierz aktualny `openapi.json` z CIRFMF/ksef-docs
3. Porównaj z `spec/openapi.json` w repo:
   - Hash SHA-256 → szybka detekcja zmiany
   - Jeśli zmiana → szczegółowy diff (nowe endpointy, usunięte, zmienione parametry)
4. Sprawdź wpływ na `ksef_client.py` — które z używanych endpointów zostały zmienione
5. Pobierz aktualny schemat FA z crd.gov.pl
6. Porównaj z `spec/schemat_FA(3)_v1-0E.xsd`
7. Jeśli zmiany → utwórz Issue + opcjonalnie PR z aktualizacją spec

### Analiza wpływu OpenAPI

Skrypt `check_openapi_changes.py` porównuje:

| Co sprawdza | Jak |
|-------------|-----|
| Nowe endpointy | Diff paths z nowego vs starego openapi.json |
| Usunięte endpointy | Endpointy obecne w starym, brak w nowym |
| Zmienione parametry | Deep diff per endpoint (parameters, requestBody, responses) |
| Wpływ na kod | Grep używanych endpointów w `ksef_client.py` vs zmienione ścieżki |
| Wersja API | Porównanie `info.version` i `info.description` (build number) |

### Analiza wpływu schematu FA

Skrypt `check_schema_changes.py` porównuje:

| Co sprawdza | Jak |
|-------------|-----|
| Nowa wersja schematu | Namespace URI w XSD (`http://crd.gov.pl/wzor/...`) |
| Nowe/usunięte elementy | Diff `xs:element` definicji |
| Zmienione typy | Diff `xs:complexType` / `xs:simpleType` |
| Wpływ na parser | Pola używane w `invoice_pdf_generator.py` vs zmienione elementy |
