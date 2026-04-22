# Re-Audyt po wdrożeniu poprawek — KSeF Monitor v0.5 (branch `test`)

> **Data re-audytu:** 2026-04-22
> **Zakres:** 22 commity remediation (`f7aa694..39bf5c4`) wykonane w trakcie sesji remediacji
> **Cel:** potwierdzić, że poprawki zamknęły znaleziska z poprzedniego audytu + wykryć nowe wprowadzone przez zmiany
> **Metoda:** empiryczna inspekcja diff + weryfikacja CVE dla nowo pinowanych deps

---

## 1. Podsumowanie

**Stan ogólny: DOBRY.** Wszystkie 4 HIGH z audytu poprzedniego zamknięte. Poprawki kodu nie wprowadziły nowych CRITICAL/HIGH. Wykryto **3 nowe MEDIUM** regresje funkcjonalne i **5 LOW/INFO** quality gaps.

| Kategoria | Count |
|-----------|-------|
| v0.5 audit findings zamknięte | **12 / 12** |
| Nowe CRITICAL regresje | **0** |
| Nowe HIGH regresje | **0** |
| Nowe MEDIUM regresje | **3** (R1 UI auth mismatch, R2 lockfile drift vs constraint, R3 loose lower bounds for fresh CVE fixes) |
| Nowe LOW | **3** (R4 Tailwind config redundancy, R5 `/ksef-status` error leak, R6 `cancel_initial_load` unvalidated input) |
| Nowe INFO | **2** (R7 TOCTOU SSRF guard, R8 IPv6 scope-ID bypass) |

---

## 2. Status poprzednich znalezisk v0.5

| ID | Severity | Finding | Status |
|----|---------|---------|--------|
| V5-01 | HIGH | Auth bypass `path.startswith("/ui")` | ✅ **FIXED** (commit `5788669`) — `_EXEMPT_EXACT` ograniczony do 4 tras, `ui_public=False` default |
| V5-02 | HIGH | `/ui/push` pairing_code leak | ✅ **FIXED** (`4002105`, `8e9c082`) — masking `X…Y`, auth-gated `/push/pairing`, 64-bit code |
| V5-03 | HIGH | Invoice PDF/XML bypass + no ksef validation | ✅ **FIXED** (`5788669`, `06e01e1`) — `KsefNumberPath` Pydantic type, `quote()` filename |
| V5-04 | HIGH | Supply chain (urllib3, starlette, python-multipart, cryptography) | ✅ **FIXED** (`274caf2`, `0ba334b`) z **uwagą R2** (lockfile drift) |
| V5-05 | MED | CSP + security headers | ✅ **FIXED** (`21ed958`, `193f9c4`) — CSP, HSTS, Referrer-Policy, Permissions-Policy |
| V5-06 | MED | Rate limits per-endpoint | ✅ **FIXED** (`dce4376`) |
| V5-07 | MED | SSRF guard for CIRFMF | ✅ **FIXED** (`181a868`, `0de84ad`) — shared `app._ssrf_guard` |
| V5-08 | MED | xhtml2pdf link_callback | ✅ **FIXED** (`624c79a`) |
| V5-09/V5-12 | MED/LOW | Version unify | ✅ **FIXED** (`b899271`, `f0d6972`, `ef7870f`) |
| V5-10 | LOW | Tailwind CDN | ✅ **FIXED** (`21ed958`, `193f9c4`) |
| V5-11 | LOW | Initial load max range | ✅ **FIXED** (`d28a8eb`) |
| v0.4 F-06 | LOW | JSON template autoescape | ✅ **FIXED** (`bc30e5f`) |
| v0.4 F-07 | LOW | `_migrate_schema` ALTER TABLE | ✅ **FIXED** (`93877d6`, `182d074`) |
| v0.4 F-09 | LOW | Rootless entrypoint | ✅ **FIXED** (`7bb6799`) |

---

## 3. Nowe znaleziska wprowadzone przez poprawki

### R1 (MEDIUM) — UI dashboard fetch'e nie korzystają z `apiCall()`, psują się po zacieśnieniu whitelist

| Pole | Wartość |
|------|---------|
| Kategoria | Functional regression / usability |
| Severity | MEDIUM (UI łamie się, nie ma wpływu na dane) |
| CWE | CWE-440 Expected Behavior Violation |
| Status | OPEN |
| Lokalizacja | [app/ui/templates/dashboard.html:197](../app/ui/templates/dashboard.html), [app/ui/templates/push.html:143](../app/ui/templates/push.html) |

**Opis:** Zadanie 4 usunęło `/api/v1/monitor/ksef-status` i `/api/v1/push/devices` z whitelist auth middleware (poprawnie — te endpointy teraz wymagają tokena). Ale Web UI w dwóch miejscach używa `fetch(...)` bezpośrednio, bez nagłówka `Authorization`:

```javascript
// dashboard.html:197 — brak tokena
const r = await fetch('/api/v1/monitor/ksef-status');

// push.html:143 — brak tokena
const r = await fetch('/api/v1/push/devices');
```

**Skutek:**
- Dashboard wyświetla "Błąd" w polu "Status KSeF API" zamiast aktualnego stanu.
- Strona `/ui/push` nie ładuje listy sparowanych urządzeń — `devices-list` pokazuje "Błąd ładowania: ...".

**Nie jest to vuln** — endpointy są prawidłowo chronione — ale **po stronie UX jest to regresja funkcjonalna** wprowadzona moimi poprawkami.

**Naprawa (P1, cosmetic w security sense):**
```javascript
// Zastąpić oba wywołania użyciem helpera `apiCall` z base.html (który dorzuca token):
const d = await apiCall('GET', '/api/v1/monitor/ksef-status');
const d = await apiCall('GET', '/api/v1/push/devices');
```

Alternatywnie przywrócić oba endpointy do `_EXEMPT_EXACT` **z wyraźnym komentarzem**, że są read-only i nie zwracają PII (`ksef-status` = status + latency; `push/devices` = hash device tokenów). Trade-off: lżejsza konfiguracja vs. `V5-01` rygor.

---

### R2 (MEDIUM) — `requirements.lock` vs `requirements.txt` rozjazd pinów

| Pole | Wartość |
|------|---------|
| Kategoria | Supply chain / Dependency management |
| Severity | MEDIUM |
| CWE | CWE-1104 Use of Unmaintained/Uncontrolled Third-Party Components (soft match) |
| Status | OPEN |
| Lokalizacja | [requirements.lock](../requirements.lock) (starlette==1.0.0) vs [requirements.txt:17](../requirements.txt) (`starlette>=0.49.1,<1.0.0`) |

**Opis:** Podczas Task 2 zacieśniliśmy `starlette` w `requirements.txt` do `<1.0.0` (kompatybilność z Python 3.9). Ale `requirements.lock` nie został **ponownie wygenerowany** po tej zmianie — wciąż ma `starlette==1.0.0`, który:
1. **Narusza** ograniczenie z `requirements.txt`.
2. Wymaga Python ≥3.10, a `pyproject.toml:requires-python = ">=3.9"`.
3. Jednak Dockerfile używa `python:3.11-slim`, więc instalacja NIE zawiedzie w kontenerze produkcyjnym.
4. `pip install --require-hashes -r requirements.lock` weryfikuje hashe, NIE weryfikuje constraint `<1.0.0` z `requirements.txt`.

**Evidence:**
```
requirements.txt:17:    starlette>=0.49.1,<1.0.0
requirements.lock:   starlette==1.0.0 \
                          --hash=sha256:...
```

**Dobra wiadomość:** starlette 1.0.0 jest non-vulnerable — oba CVE (CVE-2025-62727, CVE-2025-54121) są zaadresowane. ([starlette 1.0.0 on Snyk](https://security.snyk.io/package/pip/starlette))

**Zła wiadomość:** kontrakt plików `pyproject.toml` ⟷ `requirements.txt` ⟷ `requirements.lock` jest zerwany. Ponadto lockfile został wygenerowany pod Python 3.12, co jest znanym P1 follow-upem (Docker Desktop był wyłączony gdy próbowaliśmy regen).

**Naprawa (P1):**
```bash
# Po uruchomieniu Docker Desktop:
docker run --rm -v "$(pwd)":/w -w /w python:3.11-slim bash -lc \
  "apt-get update -qq && apt-get install -y -qq gcc libcairo2-dev pkg-config >/dev/null && \
   pip install -q --upgrade pip pip-tools && \
   pip-compile --generate-hashes --output-file=requirements.lock requirements.txt"
# Sprawdzić czy starlette resolve'uje się teraz do 0.x (powinien — constraint <1.0.0)
```

Rozważyć dodanie **CI guard**: `pip-compile --check --quiet` w workflow — failuje gdy lockfile nie match-uje requirements.txt.

---

### R3 (MEDIUM) — Dolne granice wersji za luźne — akceptują wersje podatne na właśnie-naprawione CVE

| Pole | Wartość |
|------|---------|
| Kategoria | Supply chain / Constraint hygiene |
| Severity | MEDIUM |
| CWE | CWE-1035 OWASP Top Ten 2017 — A9 Using Components with Known Vulnerabilities |
| Status | OPEN |
| Lokalizacja | [requirements.txt](../requirements.txt), [pyproject.toml](../pyproject.toml) |

**Opis:** `requirements.txt` deklaruje **dolne granice** które dopuszczają wersje nadal podatne na właśnie-naprawione CVE:

| Pakiet | Wpis w `requirements.txt` | Podatna dolna granica | Naprawiona wersja |
|--------|---------------------------|------------------------|-------------------|
| `urllib3` | `>=2.6.0,<3.0.0` | 2.6.0, 2.6.1, 2.6.2 | **CVE-2026-21441** (decompression bomb via redirects) naprawiona w **2.6.3** ([GHSA-38jv-5279-wg99](https://github.com/advisories/GHSA-38jv-5279-wg99)) |
| `python-multipart` | `>=0.0.22,<1.0.0` | 0.0.22-0.0.25 | **CVE-2026-40347** (preamble DoS) naprawiona w **0.0.26** ([GitLab advisory](https://advisories.gitlab.com/pypi/python-multipart/CVE-2026-40347/)) |

Lockfile resolwuje się do zdrowych wersji (`urllib3==2.6.3`, `python-multipart==0.0.26`), więc **obraz produkcyjny jest safe** — ale dev install bez lockfile (`pip install -r requirements.txt`) może złapać podatną wersję.

**Naprawa (P2):** Dociąć dolne granice:
```diff
- urllib3>=2.6.0,<3.0.0
+ urllib3>=2.6.3,<3.0.0            # CVE-2026-21441 fix

- python-multipart>=0.0.22,<1.0.0
+ python-multipart>=0.0.26,<1.0.0  # CVE-2026-40347 fix
```

Zrobić to też w `pyproject.toml`.

---

### R4 (LOW) — Tailwind config scan glob odnosi się do `./templates/**` ale build został uruchomiony z `--content` innym

| Pole | Wartość |
|------|---------|
| Kategoria | Build reproducibility |
| Severity | LOW |
| Status | OPEN |
| Lokalizacja | [app/ui/tailwind.config.js:5](../app/ui/tailwind.config.js), [app/ui/static/tailwind.min.css](../app/ui/static/tailwind.min.css) |

**Opis:** `tailwind.config.js` ma `content: ["./templates/**/*.html"]` — scan relatywny od working dir (`app/ui/`). Następny regen z `cd app/ui && npx tailwindcss` zrobi dokładnie to samo. Ale jeśli ktoś uruchomi z innego katalogu z `-c app/ui/tailwind.config.js`, path expansion zachowa się nieintuicyjnie i skończyć się może pustym output.

**Naprawa (P3):** użyć absolutnego path lub jawnego glob dopasowania — tj. w `tailwind.config.js` użyć `path.join(__dirname, "templates/**/*.html")`.

---

### R5 (LOW) — `/api/v1/monitor/ksef-status` ujawnia `str(e)` w odpowiedzi

| Pole | Wartość |
|------|---------|
| Kategoria | Information disclosure |
| Severity | LOW |
| CWE | CWE-209 Information Exposure Through an Error Message |
| Status | OPEN |
| Lokalizacja | [app/api/routers/monitor.py:77-80](../app/api/routers/monitor.py) |

**Opis:** Handler KSeF status w przypadku wyjątku zwraca `str(e)` klientowi:
```python
except Exception as e:
    logger.error("KSeF status probe failed: %s", e)
    return JSONResponse(
        status_code=500,
        content={"available": False, "error": str(e), "environment": "unknown"},
    )
```

Globalny `generic_error_handler` (`app/api/__init__.py:204`) zwraca tylko "Internal server error" — ten lokalny handler jest niekonsekwentny. `str(e)` może zawierać ścieżki, fragmenty stack trace, dane wrażliwe ze struktury błędu.

**Istniało przed remediation** (nie wprowadzone moimi poprawkami), ale że zmieniliśmy wokół — warto przypomnieć. Ponadto docstring line 61 mówi "public endpoint, no KSeF auth required" — **stale** po Task 4 (endpoint teraz wymaga API auth).

**Naprawa (P3):**
```python
    except Exception as e:
        logger.error("KSeF status probe failed: %s", e)
        return JSONResponse(
            status_code=500,
            content={"available": False, "error": "probe failed", "environment": "unknown"},
        )
```
Plus aktualizacja docstring: "Auth required; probes /security/... as connectivity check."

---

### R6 (LOW) — `cancel_initial_load(job_id: str)` bez walidacji formatu

| Pole | Wartość |
|------|---------|
| Kategoria | Input validation |
| Severity | LOW |
| CWE | CWE-20 |
| Status | OPEN |
| Lokalizacja | [app/api/routers/initial_load.py:143](../app/api/routers/initial_load.py) |

**Opis:** `cancel_initial_load(request: Request, job_id: str)` przyjmuje dowolny string. Brak walidacji formatu UUID. Tak samo `get_initial_load_status(job_id: Optional[str])`. Brak direct SQL injection (SQLAlchemy ORM), ale log injection możliwy (manager może logować `job_id` bez sanityzacji).

**Naprawa (P3):** dodać regex validator jak `KsefNumberPath`:
```python
from pydantic import StringConstraints
from typing import Annotated
JobIdPath = Annotated[str, StringConstraints(pattern=r"^[0-9a-f-]{36}$")]
```

Plus zastosować na obu endpointach.

---

### R7 (INFO) — TOCTOU w `is_safe_public_url` — DNS rebinding

| Pole | Wartość |
|------|---------|
| Kategoria | SSRF / DNS rebinding |
| Severity | INFO (już częściowo mitygowane w webhook przez `_revalidate_url`) |
| CWE | CWE-350 Reliance on Reverse DNS Resolution for a Security-Critical Action, CWE-367 TOCTOU |
| Status | DOCUMENTED |
| Lokalizacja | [app/_ssrf_guard.py:40-56](../app/_ssrf_guard.py) |

**Opis:** `socket.getaddrinfo` wykonywane w `is_safe_public_url` jest rozdzielne od `socket.getaddrinfo` wykonywanego przez `requests.get(url)` na żywo. W czasie między tymi wywołaniami atakujący kontrolujący DNS może zmienić rekord A z publicznego IP na prywatny. Requests pobierze wtedy prywatny zasób.

**Istniejący mitigation:** `WebhookNotifier._revalidate_url()` wywołuje walidację ponownie tuż przed requestem, co skraca okno ale nie eliminuje (DNS może zmienić się między re-validate i rzeczywistym connect).

**Pełna naprawa:** wyciągnąć IP z `getaddrinfo` w guardzie i **pass go jako host header** w requescie, a komunikować się po IP (np. przez mocked resolver w `requests.adapters`). Zaawansowana zmiana, defensive-in-depth. Nie wymagane — ryzyko niskie, bo tylko admin może ustawić URL webhooka.

---

### R8 (INFO) — IPv6 scope ID → ValueError → `continue` → silent pass

| Pole | Wartość |
|------|---------|
| Kategoria | SSRF guard edge case |
| Severity | INFO (trudne do eksploatacji) |
| CWE | CWE-754 Improper Check for Unusual or Exceptional Conditions |
| Status | OPEN |
| Lokalizacja | [app/_ssrf_guard.py:46-52](../app/_ssrf_guard.py) |

**Opis:** Pętla nad `addr_info`:
```python
for _family, _type, _proto, _canon, sockaddr in addr_info:
    ip_str = sockaddr[0]
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        continue      # ← SKIPS this IP entirely
    if (ip.is_private or ip.is_loopback or ...):
        return False
```

IPv6 link-local z zone ID ma format `fe80::1%eth0`. `ipaddress.ip_address("fe80::1%eth0")` → `ValueError`. Kod **pomija** ten IP i może skończyć z return True, gdy jedynie ten zone-scoped IP był w wynikach DNS.

**Prawdopodobieństwo eksploatacji:** NISKIE — rzadko publiczny DNS zwraca scope-ID IPs. Ale `ipaddress.ip_address` przyjmuje `%` tylko w Python 3.9+ (w niektórych wariantach).

**Naprawa (P3):** Stripować zone ID przed parse lub zmienić semantykę `except ValueError` na `return False`:
```python
except ValueError:
    logger.warning("URL rejected: unparseable IP %s", ip_str[:64])
    return False
```

Stricter policy: nieznany IP = odrzuć.

---

## 4. Zweryfikowane CVE dla nowo pinowanych deps (2026-04-22)

| Pakiet | Wersja w lockfile | Podatność? | Źródło |
|--------|--------------------|------------|--------|
| cryptography | 46.0.7 | ✅ CZYSTE (fix CVE-2026-39892, CVE-2026-34073) | [Cryptography 46.0.7 changelog](https://cryptography.io/en/stable/changelog/) |
| urllib3 | 2.6.3 | ✅ CZYSTE (fix CVE-2025-66418/66471/**CVE-2026-21441**) | [GHSA-38jv-5279-wg99](https://github.com/advisories/GHSA-38jv-5279-wg99) |
| starlette | 1.0.0 | ✅ CZYSTE (fix CVE-2025-62727, CVE-2025-54121) | [Snyk starlette](https://security.snyk.io/package/pip/starlette) |
| python-multipart | 0.0.26 | ✅ CZYSTE (fix CVE-2024-53981, CVE-2026-40347, CVE-2026-24486) | [GitLab advisory](https://advisories.gitlab.com/pypi/python-multipart/CVE-2026-40347/) |
| fastapi | 0.136.0 | ✅ CZYSTE | [PyPI fastapi](https://pypi.org/project/fastapi/) |
| jinja2 | 3.1.6 | ✅ CZYSTE (fix CVE-2025-27516) | [GHSA-cpwx-vrp4-4pq7](https://github.com/advisories/GHSA-cpwx-vrp4-4pq7) |

**Nowe CVE wykryte w re-audycie:** CVE-2026-21441 (urllib3 decompression bomb via redirects) — **już zaadresowany** w lockfile przez upgrade do 2.6.3.

---

## 5. Priorytety napraw

### P1 — BLOCKER przed merge `test → main`

1. **R1** — naprawić UI fetche aby używały `apiCall()` (albo re-add `/ksef-status` + `/push/devices` do whitelist z komentarzem)
2. **R2** — regen `requirements.lock` pod Python 3.11, po uruchomieniu Docker Desktop (blocker z Task 2)

### P2 — w trakcie v0.5 RC

3. **R3** — dociąć dolne granice deps do wersji z fix'ami CVE (`urllib3>=2.6.3`, `python-multipart>=0.0.26`)
4. **R5** — ukryć `str(e)` z `/monitor/ksef-status`; dodać CI step `pip-compile --check`

### P3 — backlog

5. **R4** — `tailwind.config.js` z absolutnym path (`__dirname`)
6. **R6** — walidacja `job_id` jako `Annotated[str, StringConstraints(UUID)]`
7. **R7** — TOCTOU DNS rebinding — resolve once + pass IP to connection
8. **R8** — unparseable IP → odrzuć (zamiast pomiń)

---

## 6. Pozytywne obserwacje

| # | Praktyka | Dowód |
|---|----------|-------|
| I1 | Wszystkie CVE z poprzedniego audytu zaadresowane w lockfile | urllib3 2.6.3, starlette 1.0.0, cryptography 46.0.7, python-multipart 0.0.26 |
| I2 | Shared `_ssrf_guard.is_safe_public_url` — single source of truth dla URL validation | [app/_ssrf_guard.py](../app/_ssrf_guard.py), wykorzystany w webhook + CIRFMF |
| I3 | `KsefNumberPath` — Pydantic-level walidacja = 422 automatycznie, usuwa ręczne guardy | [app/api/path_params.py](../app/api/path_params.py) |
| I4 | `_EXEMPT_EXACT = {docs, redoc, openapi, health}` — minimalistyczny whitelist | [app/api/__init__.py:83-86](../app/api/__init__.py) |
| I5 | Per-endpoint rate limits skonfigurowalne z configu | [app/api/_limiter.py](../app/api/_limiter.py), `configure_limiter()` |
| I6 | Security headers: CSP + HSTS + Referrer-Policy + Permissions-Policy | [app/api/__init__.py:116-144](../app/api/__init__.py) |
| I7 | Tailwind zbundlowany lokalnie (14 KB), brak CDN dependency | [app/ui/static/tailwind.min.css](../app/ui/static/tailwind.min.css) |
| I8 | xhtml2pdf `link_callback` blokuje zewnętrzne zasoby | [app/invoice_pdf_template.py:193-199](../app/invoice_pdf_template.py) |
| I9 | Pairing code 64-bit, masked in UI, auth-gated reveal | [app/push_manager.py:244,549-577](../app/push_manager.py) |
| I10 | Alembic dla migracji zamiast ALTER TABLE | [app/database.py:415-486](../app/database.py) |
| I11 | Rootless entrypoint support | [entrypoint.sh:6-25](../entrypoint.sh) |
| I12 | CI: pip-audit + Trivy image scan z exit-code 1 | [.github/workflows/docker-publish.yml](../.github/workflows/docker-publish.yml) |
| I13 | `Content-Disposition` filename wyłącznie przez `quote()` | [app/api/routers/invoices.py:156,173,213,252](../app/api/routers/invoices.py) |
| I14 | CHANGELOG.md dokumentuje wszystkie zmiany + znane follow-upy | [CHANGELOG.md](../CHANGELOG.md) |
| I15 | JSON templates wrapped w `{% autoescape false %}` — kompatybilne z extension-driven autoescape | [app/templates/*.json.j2](../app/templates/) |

---

## 7. Źródła CVE (zweryfikowane WebSearch 2026-04-22)

- [CVE-2026-21441 — urllib3 decompression via redirects (GHSA-38jv-5279-wg99)](https://github.com/advisories/GHSA-38jv-5279-wg99) — **NOWE**, przed re-audytem nieznane
- [CVE-2026-40347 — python-multipart preamble DoS (GitLab)](https://advisories.gitlab.com/pypi/python-multipart/CVE-2026-40347/)
- [CVE-2026-39892 — cryptography OOB read (GHSA-p423-j2cm-9vmq)](https://github.com/advisories/GHSA-p423-j2cm-9vmq)
- [CVE-2026-34073 — cryptography DNS constraint](https://advisories.gitlab.com/pkg/pypi/cryptography/CVE-2026-34073/)
- [CVE-2025-66418/66471 — urllib3 decompression](https://github.com/advisories/GHSA-gm62-xv2j-4w53)
- [CVE-2025-62727 — starlette FileResponse Range DoS](https://github.com/advisories/GHSA-7f5h-v6xp-fcq8)
- [CVE-2025-54121 — starlette multipart file DoS](https://github.com/advisories/GHSA-2c2j-9gv5-cj73)

---

## 8. Metadane re-audytu

- **Branch:** `test`, HEAD: `39bf5c4`
- **Diff:** `git diff --stat f7aa694..HEAD` → 50 files, 2910 insertions, 163 deletions
- **Narzędzia:** WebSearch (NVD/GHSA), manualna inspekcja diff + struktury kodu, weryfikacja lockfile vs constraints
- **Anti-hallucination ✅:** wszystkie 7 cytowanych CVE zweryfikowane przez WebSearch URL do GHSA/GitLab
- **Ograniczenia:** nie uruchomiono live `pip-audit` ani `trivy image` — blocker Docker Desktop

**Auditor:** Claude Code + security-audit skill
**Timestamp:** 2026-04-22
