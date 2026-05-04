# Audyt Bezpieczeństwa — KSeF Monitor Docker **v0.5.1** — UI Auth (V5-12 / V5-13 / V5-14)

> **Data audytu:** 2026-05-04
> **Audytor:** Claude Opus 4.7 (1M context)
> **Commit HEAD:** `7206d43` (branch `test`, tracking `origin/test`)
> **Zakres:** delta v0.5.0 → v0.5.1 wprowadzająca uwierzytelnianie użytkowników UI (cookie sesyjny, baza userów, bcrypt, split middleware) — nieaudytowana w cyklu v0.5.0
> **Typ:** focused audit nowej attack surface (auth UI)

---

## 1. Podsumowanie wykonawcze

**Stan ogólny: ŚREDNI** — projekt sesji solidny w fundamentach (256-bit `secrets.token_hex`, HttpOnly, SameSite=strict, bcrypt 12 rounds, split middleware, sesje opaque w DB, password change → revoke wszystkich sesji), ale brakuje kilku warstw obrony przy realnych deployment scenariuszach (reverse-proxy bez `X-Forwarded-Proto` honoring, brute-force per-username, anti-hijack binding).

| Kategoria | Liczba |
|-----------|-------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | **6** (U-01..U-06) |
| LOW | **6** (U-07..U-12) |
| INFO | **5** (U-13..U-17) |
| Carryover (świadome cap'y) | **1** (U-18) |

### Top do działania (P1 przed merge `test → main`)

| ID | Problem | Severity |
|----|---------|----------|
| **U-01** | Cookie `Secure` flag bazuje na `request.url.scheme`. Reverse-proxy terminujący TLS przekazuje `http://` do uvicorn → cookie wysyłane bez `Secure` mimo realnie HTTPS w stronę klienta | MEDIUM |
| **U-02** | Bcrypt 4.x silently truncuje passwords >72B; brak SHA256+b64 pre-hash. Bump do bcrypt 5.0 (już zaplanowany w ROADMAP) zamieni truncation w `ValueError` → DoS na obecnych userach z długimi hasłami | MEDIUM |
| **U-03** | Brute-force protection per-IP only (5/min). Botnet rozproszony omija. Per-username counter brak | MEDIUM |
| **U-04** | Sesje wiązane wyłącznie z `id` cookie — brak IP/UA fingerprint/anti-hijack. Skradziony cookie używalny zewsząd przez 7 dni (sliding) | MEDIUM |

### Mocne strony

- ✅ 256-bit entropy session ID (`secrets.token_hex(32)`)
- ✅ HttpOnly + SameSite=strict cookie (skutecznie chroni przed CSRF/XSS exfiltration)
- ✅ Sesje opaque DB-backed — nie JWT, brak ryzyka algorithm confusion / klucza w klocie
- ✅ Bcrypt 12 rounds, `hmac.compare_digest` dla Bearer
- ✅ Password change → DELETE wszystkich sesji usera (cleanest invalidation)
- ✅ Single-user delete protection (`count_users() == 1` block)
- ✅ Setup wizard idempotent (po stworzeniu admina zawsze 303 do login)
- ✅ Logout via POST (immune na CSRF logout-via-img)
- ✅ Sliding TTL z absolute expiry per-row (`expires_at` w DB, nie polegać na cookie)
- ✅ Setup auto-login bez password re-prompt (UX-friendly bez kompromisu)

---

## 2. Stack auth-related — delta v0.5.0 → v0.5.1

| Warstwa | v0.5.0 | v0.5.1 (delta) |
|---------|--------|----------------|
| UI auth model | Bearer token z localStorage (V5-01 + V5-12 hybrid) | **Cookie session, opaque sid w DB (V5-13)**; localStorage Bearer **usunięty** |
| User accounts | brak (single Bearer token) | **`UiUser`** + **`UiSession`** tabele, **`bcrypt 12r`** hash, password change → revoke all |
| Setup flow | konfiguracja CLI / env | **`/ui/setup`** wizard pierwszego uruchomienia (race-safe transakcja) |
| Middleware | `verify_auth` (Bearer + UI bypass) | **split:** `resolve_ui_session` (zawsze, populuje `request.state.ui_user_id`) **+** `verify_auth` (gate jeśli `auth_token`) |
| Whitelist auth | `{/docs,/redoc,/openapi.json,/health}` | **+ `/ui/login`, `/ui/logout`, `/ui/setup`** |
| Account management | brak | **`/ui/account`** (change password, GET) + **`/ui/account/password`** (POST, re-auth via `current_password`) |
| CLI tooling | brak | **`python -m app.user_admin {list,add,reset-password,delete,cleanup-sessions}`** |
| DB migration | phase4 initial_load_jobs | **phase5_ui_users** (`e0f1g2h34567`) |

---

## 3. MEDIUM FINDINGS

### U-01 (MEDIUM) — Cookie `Secure` flag ignoruje `X-Forwarded-Proto`

| Pole | Wartość |
|------|---------|
| Kategoria | Cookie security / TLS confidentiality |
| Severity | MEDIUM |
| CWE | CWE-614 Sensitive Cookie in HTTPS Session Without 'Secure' Attribute, CWE-319 Cleartext Transmission |
| Status | OPEN |
| Lokalizacja | [app/api/routers/ui.py:380-389](../app/api/routers/ui.py#L380-L389) |

**Opis:** Helper `_set_session_cookie` ustala flagę `Secure` na podstawie `request.url.scheme`:

```python
def _set_session_cookie(resp, sid: str, scheme: str) -> None:
    resp.set_cookie(
        key=_SESSION_COOKIE,
        value=sid,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=scheme == "https",   # ← polega na .url.scheme
        samesite="strict",
        path="/",
    )
```

W typowym deployment (per `docs/TODO.md` scenario "reverse-proxy ui_public" + scenario "prod direct"): nginx/caddy/traefik terminują TLS i forwardują na `http://uvicorn:8080`. `request.url.scheme` w uvicorn = `http`. Cookie ustawiane bez `Secure` mimo że klient pobiera je przez HTTPS.

**Skutek:** atakujący w segmencie sieci (cloud LAN, zalokalizowany w VPC, BGP hijack) który podsunie HTTP request do `http://monitor.example/ui/foo` może odczytać cookie sessyjny. SameSite=strict pomaga (cookie wysyłane tylko gdy pierwszy poziom navigation), ale nie chroni przed atakiem typu "user clicks http:// link".

**Naprawa (P1):**
1. Skonfigurować uvicorn z `--proxy-headers --forwarded-allow-ips '*'` (lub konkretne IP proxy) — wtedy `request.url.scheme` honoruje `X-Forwarded-Proto`.
2. ALBO: dodać explicite parameter `secure_cookie: bool` z config (dwa stany: `force_https=true` / `auto`). Default `force_https=true` w prod.
3. ALBO: ustawiać `Secure=True` zawsze gdy `auth_token` jest skonfigurowany (heurystyka: prod-mode).

**Test:**
```bash
curl -s -i -k 'https://monitor.example/ui/login' -d 'username=admin&password=…' | grep -i 'set-cookie'
# Oczekiwane: Set-Cookie: mksef_session=...; Secure; HttpOnly; SameSite=Strict
```

---

### U-02 (MEDIUM) — Bcrypt silently truncuje passwords >72B; przyszły bump do 5.0 → DoS

| Pole | Wartość |
|------|---------|
| Kategoria | Cryptographic weakness / availability regression |
| Severity | MEDIUM |
| CWE | CWE-916 Use of Password Hash With Insufficient Computational Effort, CWE-1391 Use of Weak Credentials |
| Status | OPEN |
| Lokalizacja | [app/ui_auth.py:36-40](../app/ui_auth.py#L36-L40) |

**Opis:** `hash_password` przekazuje raw bytes hasła do `bcrypt.hashpw` bez ograniczenia długości:

```python
def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(
        plaintext.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    ).decode("utf-8")
```

Bcrypt z definicji obsługuje **tylko 72 bajty**. Wszystko ponad jest **silently truncowane** w bcrypt 4.x (zachowanie OpenBSD compat). Skutek dwojaki:

1. **Collision risk:** dwa różne hasła z identycznymi pierwszymi 72 bajtami mają ten sam hash. UX: user wie, że "password123_(jakaś_długa_fraza)" działa, ale tak naprawdę server akceptuje też skróconą wersję. Slight ale realny.
2. **Future DoS (V5-04 carryover):** ROADMAP zakłada w przyszłości bump bcrypt → 5.0 (po dodaniu obejścia). bcrypt 5.0 **zamienia truncation w `ValueError`**. Każdy user, który **już ustawił** hasło >72B, nie zaloguje się po upgrade kontenera — `verify_password` zwróci False z `except ValueError`. Operator nie ma diagnostyki.

**Naprawa (P1, koniecznie przed bcrypt 5.0):**

```python
import base64
import hashlib

def _bcrypt_safe(password: str) -> bytes:
    """Pre-hash long passwords with SHA256+base64 to bypass 72B limit safely."""
    pw = password.encode("utf-8")
    if len(pw) > 72:
        pw = base64.b64encode(hashlib.sha256(pw).digest())  # 44 bytes ASCII
    return pw

def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(_bcrypt_safe(plaintext), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")

def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_safe(plaintext), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
```

**UWAGA migracji:** zmiana łamie istniejące hashe userów z hasłami >72B (wymuszą reset). Userzy z hasłami ≤72B nie odczują różnicy (`_bcrypt_safe` no-op poniżej 72B).

**Test:**
```python
def test_long_password_hashed_safely():
    long_pw = "x" * 100
    h = hash_password(long_pw)
    assert verify_password(long_pw, h)
    # Critical: ensure two different long passwords don't collide
    h2 = hash_password("y" * 100)
    assert not verify_password(long_pw, h2)
```

---

### U-03 (MEDIUM) — Brute-force protection per-IP only; per-username counter brak

| Pole | Wartość |
|------|---------|
| Kategoria | Authentication / brute-force |
| Severity | MEDIUM |
| CWE | CWE-307 Improper Restriction of Excessive Authentication Attempts |
| Status | OPEN |
| Lokalizacja | [app/api/routers/ui.py:482-483](../app/api/routers/ui.py#L482-L483) (login limit 5/min/IP) |

**Opis:** `POST /ui/login` ma rate limit `5/minute` ale slowapi defaultowo keyuje po IP. Atakujący z botnetu (residential proxies, np. 100k IP) może próbować **500k haseł/min globalnie** mimo limitu 5/min/IP. Przy `password_min_len = 8` i bez sprawdzania słownikowego (zob. U-11), słabe hasło ("admin1234") znalezione w setki ms.

**Brak account lockout per username.** W połączeniu z brakiem audit logu na succesful login (zob. U-12), atak jest niewykrywalny do momentu gdy atakujący zaloguje się i wykona widoczną akcję.

**Naprawa (P1):**

1. **Dodać per-username licznik** w nowej tabeli `ui_login_attempts`:
   ```sql
   CREATE TABLE ui_login_attempts (
     username TEXT PRIMARY KEY,
     failed_count INTEGER NOT NULL DEFAULT 0,
     locked_until DATETIME,
     last_attempt_at DATETIME NOT NULL
   );
   ```
2. **Lockout policy:** po 5 nieudanych próbach w 15 min — 15 min lock; po 10 nieudanych w godzinie — 1h lock. Reset licznika po udanym loginie.
3. **Audit log:** na każdą failed/succeeded login + lockout, struktured log do `ApiRequestLog` lub osobnej tabeli.
4. (Opcjonalnie) **CAPTCHA** po N failed dla danego usera.

**Pragma:** w aplikacji single-user-admin (typowy use case) ryzyko niskie, ale jeśli dojdzie multi-user (V0.6+), problem rośnie.

---

### U-04 (MEDIUM) — Sesja bez IP/UA fingerprint anti-hijack

| Pole | Wartość |
|------|---------|
| Kategoria | Session hijacking |
| Severity | MEDIUM |
| CWE | CWE-613 Insufficient Session Expiration, CWE-384 Session Fixation (partial coverage) |
| Status | OPEN |
| Lokalizacja | [app/ui_auth.py:128-158](../app/ui_auth.py#L128-L158) (`validate_session`) |

**Opis:** `validate_session` weryfikuje wyłącznie `id == cookie` + `expires_at > now`. Brak walidacji IP/UA. W połączeniu z 7-dniowym TTL i sliding refresh:

- Skradziony cookie (XSS na innym serwisie z tego samego hosta — gdyby był subdomain → mitygowane przez SameSite=strict; ale: lokalny malware, browser extension, shared computer) **żyje 7 dni i się odnawia z każdym requestem**.
- Brak detekcji "ten sid widziany z 5 różnych krajów" → brak alertu / auto-revoke.

**Skutek:** jeden ukradziony sid → trwały dostęp dopóki user nie zmieni hasła (revoke all).

**Naprawa (defense-in-depth, P2):**

1. **Bind UA hash** przy `create_session` (sha256 user-agent). W `validate_session` jeśli UA hash ≠ → revoke + log.
2. **Bind IP/24** (lub /48 IPv6). Tolerancja na zmianę ostatniego oktetu (DHCP). Mismatch → revoke.
3. **Absolute lifetime cap:** dodać `created_at + 30d` jako hard limit. Sliding nie odnawia tego.

**Trade-off:** UA/IP binding łamie UX dla mobile/DHCP/VPN użytkowników. Lepiej: **opt-in setting** w `/ui/account` ("strict session binding").

---

### U-05 (MEDIUM) — CSP `script-src 'self' 'unsafe-inline'` neguje XSS protection

| Pole | Wartość |
|------|---------|
| Kategoria | Web hardening — Content Security Policy |
| Severity | MEDIUM (carryover z V5-05; explicitly oznaczony jako "tighten in follow-up") |
| CWE | CWE-1021 Improper Restriction of Rendered UI Layers, CWE-79 (XSS amplifier) |
| Status | KNOWN — komentarz w kodzie planuje fix |
| Lokalizacja | [app/api/__init__.py:182-191](../app/api/__init__.py#L182-L191) |

**Opis:** CSP middleware w `add_security_headers`:

```python
response.headers["Content-Security-Policy"] = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "    # ← amplifier
    ...
)
```

`'unsafe-inline'` w `script-src` wyłącza praktycznie ochronę CSP przed XSS — dowolny inline `<script>` lub atrybut `onclick="…"` wykona się. W kontekście login form: jeśli kiedyś pojawi się stored XSS (np. invoice number z payloadem renderowany w `/ui/invoices`), CSP nie zatrzyma kradzieży session cookie (HttpOnly chroni cookie, ale nie chroni przed innymi XSS skutkami: keylogger, action-on-behalf).

**Pozytyw:** HttpOnly cookie chroni przed `document.cookie` exfiltration. SameSite=strict chroni przed cross-site action-on-behalf. CSP `frame-ancestors 'none'` chroni przed clickjackingiem. Sumarycznie XSS payload ma ograniczoną zdolność.

**Naprawa (P2, post-merge):**

1. Wynieść inline `<script>` z `push.html` do `/ui/static/push.js`.
2. Wynieść inline event handlers (`onclick`) do `addEventListener` w bundlowanym JS.
3. Wymienić `'unsafe-inline'` na **per-request nonce**:
   ```python
   nonce = secrets.token_urlsafe(16)
   request.state.csp_nonce = nonce
   response.headers["Content-Security-Policy"] = f"script-src 'self' 'nonce-{nonce}'; ..."
   ```
   W templates: `<script nonce="{{ request.state.csp_nonce }}">`.

---

### U-06 (MEDIUM) — Setup wizard race — brak atomic check-and-insert

| Pole | Wartość |
|------|---------|
| Kategoria | Race condition / privilege escalation |
| Severity | MEDIUM (low likelihood but high impact) |
| CWE | CWE-362 Concurrent Execution using Shared Resource with Improper Synchronization, CWE-367 TOCTOU |
| Status | OPEN |
| Lokalizacja | [app/api/routers/ui.py:445-449](../app/api/routers/ui.py#L445-L449) |

**Opis:** Handler `POST /ui/setup`:

```python
with db.get_session() as s:
    if count_users(s) > 0:
        return RedirectResponse(url="/ui/login", status_code=303)
    user = create_user(s, username, password)
    sid = create_session(s, user)
```

`count_users` to `SELECT`, `create_user` to `INSERT + commit`. Mimo że oba w jednej `with db.get_session()` — SQLAlchemy używa autocommit-off + `session.commit()` w `create_user` na środku → dwa concurrent requesty mogą oba przejść `count_users() == 0` przed którymkolwiek `commit`. SQLite w trybie WAL serializuje writers, więc drugi insert poczeka — ale jeśli oba inserty mają **różne username**, drugi przechodzi UNIQUE check i mamy **dwóch first-launch adminów** zamiast jednego.

**Skutek:** atakujący który publicznie (przed pierwszym uruchomieniem) zna URL `/ui/setup` i wyśle POST jednocześnie z legalnym operatorem może utworzyć drugie konto z arbitrary username/password. Operator nie zauważy — widzi tylko swoje konto.

**Prawdopodobieństwo eksploatacji:** NISKIE — atakujący musi (a) znać URL przed pierwszym uruchomieniem, (b) trafić w sub-second window. Ale **impact wysoki** — pełna kontrola UI (= cały /api/v1).

**Naprawa (P1):**

```python
from sqlalchemy.exc import IntegrityError

with db.get_session() as s:
    try:
        # Strategy: rely on UNIQUE constraint via "INSERT … WHERE NOT EXISTS"
        # (SQLite-compatible) or explicit advisory lock.
        existing_count = s.execute(
            text("SELECT COUNT(*) FROM ui_users LIMIT 1")
        ).scalar_one()
        if existing_count > 0:
            return RedirectResponse(url="/ui/login", status_code=303)
        # Fast path: BEGIN IMMEDIATE acquires write lock immediately
        s.execute(text("BEGIN IMMEDIATE"))
        if s.execute(text("SELECT COUNT(*) FROM ui_users")).scalar_one() > 0:
            return RedirectResponse(url="/ui/login", status_code=303)
        user = create_user(s, username, password)
    except IntegrityError:
        return RedirectResponse(url="/ui/login", status_code=303)
```

ALBO: dodać `is_first_admin BOOLEAN DEFAULT FALSE` z partial unique index `WHERE is_first_admin=TRUE` — atomic ograniczenie do jednego "pierwszego admina".

ALBO (najprostsze): wyłączyć `/ui/setup` po pierwszym uruchomieniu via plik flag lub config, zamiast polegać na `count_users() == 0` runtime check.

---

## 4. LOW FINDINGS

### U-07 (LOW) — Username timing oracle: skip bcrypt gdy user nie istnieje

| Pole | Wartość |
|------|---------|
| Kategoria | Side-channel / username enumeration |
| Severity | LOW |
| CWE | CWE-208 Observable Timing Discrepancy, CWE-203 Observable Discrepancy |
| Status | OPEN |
| Lokalizacja | [app/api/routers/ui.py:506-507](../app/api/routers/ui.py#L506-L507) |

**Opis:**
```python
user = get_user_by_username(s, username.strip())
if user is None or not verify_password(password, user.password_hash):
```

Bcrypt 12-rounds zajmuje ~250ms. Jeśli user nie istnieje, bcrypt **nie wykonuje się** → response w ~5ms. Atakujący z timing API może rozróżnić "user istnieje" vs "user nie istnieje" przy progu 200ms+.

**Naprawa:**
```python
user = get_user_by_username(s, username.strip())
DUMMY_HASH = "$2b$12$" + "x" * 53  # valid bcrypt format, never matches
hash_to_check = user.password_hash if user else DUMMY_HASH
if not verify_password(password, hash_to_check) or user is None:
    return RedirectResponse(url=f"/ui/login?error=invalid", status_code=303)
```

Zawsze wykonuje bcrypt, równa się timing.

---

### U-08 (LOW) — Failed login loguje arbitrary `username` z requestu

| Pole | Wartość |
|------|---------|
| Kategoria | Information disclosure / log injection vector |
| Severity | LOW |
| CWE | CWE-117 Improper Output Neutralization for Logs, CWE-532 Insertion of Sensitive Information into Log File |
| Status | OPEN |
| Lokalizacja | [app/api/routers/ui.py:508-512](../app/api/routers/ui.py#L508-L512) |

**Opis:**
```python
logger.warning(
    "Failed UI login for %r from %s",
    username,
    request.client.host if request.client else "unknown",
)
```

Loguje raw `username` z formularza. Skutki:

1. **Username harvesting:** atakujący próbuje 1000 username'ów; loguje się oczywiście tylko jednego, ale **wszystkie próby są w logu** wraz z timestampem. Operator widząc logi nie wie który był real attempt.
2. **Log injection:** username może zawierać znaki sterujące (`\n`, `\r`, ANSI escape). `%r` daje `repr()` → wyświetla escape'owane, więc raczej OK, ale narzędzia do log forwardingu (Loki, Splunk) mogą rozparsować repr i zinterpretować newline.

**Naprawa:**
1. Loguj **długość** lub **hash** username, nie raw value:
   ```python
   logger.warning(
       "Failed UI login (username_len=%d) from %s",
       len(username), request.client.host if request.client else "unknown",
   )
   ```
2. Lub: loguj raw tylko gdy `user is not None` (mamy potwierdzony existing username).

---

### U-09 (LOW) — Sliding session bez absolute lifetime cap

| Pole | Wartość |
|------|---------|
| Kategoria | Session lifecycle |
| Severity | LOW |
| CWE | CWE-613 Insufficient Session Expiration |
| Status | OPEN |
| Lokalizacja | [app/ui_auth.py:155-156](../app/ui_auth.py#L155-L156) |

**Opis:** Każde successful `validate_session` przedłuża `expires_at = now + 7d`. Sesja użytkownika aktywnego (codzienny login) **żyje wiecznie**.

**Skutek:** ukradziony cookie wciąż w użyciu po kilku miesiącach (atakujący odnawia regularnie). Brak detekcji przez TTL.

**Naprawa:**
```python
ABSOLUTE_LIFETIME = timedelta(days=30)

def validate_session(session: Session, sid: Optional[str]) -> ...:
    ...
    if row.created_at + ABSOLUTE_LIFETIME < now:
        session.execute(delete(UiSession).where(UiSession.id == sid))
        session.commit()
        return None
    ...
```

Po 30 dniach od `created_at` user musi się ponownie zalogować.

---

### U-10 (LOW) — `_safe_next` mija check dla ścieżek typu `/ui-attacker.com/`

| Pole | Wartość |
|------|---------|
| Kategoria | Open redirect (limited) |
| Severity | LOW (relative path, browser pozostaje na host) |
| CWE | CWE-601 URL Redirection to Untrusted Site (mitigated, but check imperfect) |
| Status | OPEN |
| Lokalizacja | [app/api/routers/ui.py:373-377](../app/api/routers/ui.py#L373-L377) |

**Opis:**
```python
def _safe_next(value: Optional[str]) -> str:
    if not value or not value.startswith("/ui") or value.startswith("//"):
        return "/ui"
    return value
```

`startswith("/ui")` matchuje:
- `/ui` ✅
- `/ui/foo` ✅
- `/ui-attacker.com/` ✅ ← namespace pollution; nie jest to host (relative path), ale aplikacja zwróci 404 / nieoczekiwany content. Drobny UX bug, ale **przy odpowiednim routing** mogłaby trafić w arbitrary handler.
- `/uiarbitrary` ✅ ← j.w.

**Naprawa:**
```python
def _safe_next(value: Optional[str]) -> str:
    if not value:
        return "/ui"
    if value == "/ui" or value.startswith("/ui/"):
        if value.startswith("//"):  # protocol-relative
            return "/ui"
        return value
    return "/ui"
```

---

### U-11 (LOW) — Brak password strength check (zxcvbn / breach corpus)

| Pole | Wartość |
|------|---------|
| Kategoria | Weak credential acceptance |
| Severity | LOW |
| CWE | CWE-521 Weak Password Requirements |
| Status | OPEN |
| Lokalizacja | [app/ui_auth.py:67-73](../app/ui_auth.py#L67-L73) |

**Opis:** `validate_password` sprawdza tylko `len(password) >= 8`. Akceptuje `12345678`, `password`, `qwerty12`. NIST SP 800-63B 5.1.1.2 zaleca:
- Min 8 chars ✅
- **Block listy najczęstszych haseł** ❌
- **Block sekwencyjnych/repetytywnych** ❌
- **Block dictionary words** ❌

W kontekście V5-13 (single-admin self-hosted) ryzyko zmniejszone (operator sam wybiera). Ale jeśli admin ustawi `admin1234`, U-03 (brute-force) staje się trywialny.

**Naprawa:**
1. Lekka: dodać blocklist najczęstszych 100k haseł (plik 1MB):
   ```python
   COMMON_PASSWORDS = set(open("data/common-passwords.txt").read().split())
   def validate_password(password: str) -> Optional[str]:
       ...
       if password.lower() in COMMON_PASSWORDS:
           return "Hasło zbyt popularne — wybierz mniej oczywiste."
       return None
   ```
2. Solidna: integracja z [zxcvbn-python](https://github.com/dwolfhub/zxcvbn-python) — score ≥ 3 wymagany.
3. Opcjonalna: HIBP API check (privacy-preserving via k-anonymity).

---

### U-12 (LOW) — Brak audit log dla successful login / logout / session.create

| Pole | Wartość |
|------|---------|
| Kategoria | Insufficient logging |
| Severity | LOW |
| CWE | CWE-778 Insufficient Logging |
| Status | OPEN |
| Lokalizacja | [app/api/routers/ui.py:482-535](../app/api/routers/ui.py#L482-L535), [app/ui_auth.py:110-125](../app/ui_auth.py#L110-L125) |

**Opis:** Failed login → `logger.warning` ✅. Successful login → **brak logu**. Logout → brak. Password change → `logger.info` w `set_password` ✅. Session creation → brak.

**Skutek:**
- Atakujący który przejdzie U-03 (brute-force) zaloguje się i nie ma śladu w logach (poza request log z access).
- Brak audytu "kto zalogował się i kiedy" mimo że tabela `ui_users.last_login_at` to zapisuje (ale: brak IP/UA, brak history).

**Naprawa:**
1. Logować successful login:
   ```python
   logger.info("UI login OK: user=%s from %s", username, request.client.host)
   ```
2. Logować logout:
   ```python
   logger.info("UI logout: sid=%s…", sid[:8])
   ```
3. (Solidna) tabela `ui_audit_log` z (timestamp, user_id, event_type, ip, ua, success).

---

## 5. INFO FINDINGS

### U-13 (INFO) — `count_users()` materializuje wszystkie row ID zamiast `func.count()`

| Pole | Wartość |
|------|---------|
| Lokalizacja | [app/ui_auth.py:79-80](../app/ui_auth.py#L79-L80) |

```python
def count_users(session: Session) -> int:
    return session.execute(select(UiUser.id)).scalars().all().__len__()
```

**Naprawa:**
```python
from sqlalchemy import func
def count_users(session: Session) -> int:
    return session.execute(select(func.count(UiUser.id))).scalar_one()
```

W single-user DB różnica nieistotna. Ale skalowalność: `cleanup-sessions` + `count_users` w pętli mogłyby się zsumować.

---

### U-14 (INFO) — `expires_at` bez explicit TZ; workaround zakłada UTC

| Pole | Wartość |
|------|---------|
| Lokalizacja | [app/database.py:416](../app/database.py#L416), [app/ui_auth.py:144-145](../app/ui_auth.py#L144-L145) |

SQLAlchemy `DateTime` na SQLite nie zachowuje `tzinfo`. Workaround:
```python
if expires.tzinfo is None:
    expires = expires.replace(tzinfo=timezone.utc)
```

Załóżmy że DB zawsze pisany w UTC — OK, spójne z resztą kodu (`datetime.now(timezone.utc)`). Ale wg dokumentacji: `DateTime(timezone=True)` lub udokumentować invariant.

---

### U-15 (INFO) — `resolve_ui_session` catch-all `Exception` może maskować schema corruption

| Pole | Wartość |
|------|---------|
| Lokalizacja | [app/api/__init__.py:160-161](../app/api/__init__.py#L160-L161) |

```python
except Exception as exc:  # DB hiccup must not 500 the UI
    logger.warning("Session resolver failed: %s", exc)
```

Catch-all maskuje DB corruption / schema mismatch / OOM. Skutek: user nigdy nie zostaje zalogowany, operator widzi tylko warningi w logu.

**Naprawa:** zacieśnić do `(OperationalError, DBAPIError)`. Inne wyjątki re-raise (powinny dać 500).

---

### U-16 (INFO) — Cookie `path=/` szersze niż konieczne

| Pole | Wartość |
|------|---------|
| Lokalizacja | [app/api/routers/ui.py:388](../app/api/routers/ui.py#L388) |

Cookie wysyłany dla wszystkich requestów (włącznie ze statycznymi `/ui/static/*.css`). Defense-in-depth: `path=/ui` ograniczyłoby surface. Ale kosztem: BeArer-y do API z UI muszą iść też pod /api/* z cookie → trzeba zostawić `/`.

**Pragma:** zostawić `path=/`, jest świadomy choice.

---

### U-17 (INFO) — Username case-sensitive (collision risk)

| Pole | Wartość |
|------|---------|
| Lokalizacja | [app/ui_auth.py:83-86](../app/ui_auth.py#L83-L86) |

```python
def get_user_by_username(session: Session, username: str) -> Optional[UiUser]:
    return session.execute(
        select(UiUser).where(UiUser.username == username)
    ).scalar_one_or_none()
```

`username` porównywany case-sensitive. User może utworzyć "admin" i "Admin" jako dwa konta. UX confusion, drobny phishing vector.

**Naprawa:** wymusić lowercase przy `validate_username` lub porównywać `lower(UiUser.username) == lower(username)`. UNIQUE index na `lower(username)`.

---

## 6. CARRYOVER (znane / świadomie pinowane)

### U-18 — `bcrypt<5.0.0` cap świadomy ale tymczasowy

| Pole | Wartość |
|------|---------|
| Lokalizacja | [requirements.txt:29](../requirements.txt#L29), zob. też GH issue #28 zamknięte jako wontfix |

`bcrypt>=4.2.0,<5.0.0` świadomie pinowane bo bcrypt 5.0 rzuca `ValueError` na >72B (zob. U-02). U-02 fix (SHA256+b64 pre-hash) odblokuje bezpieczny bump.

**Status:** TRACKED w wontfix-snapshot na issue #28.

---

## 7. Zweryfikowane CVE — biblioteki dotykane przez UI auth (2026-05-04)

| Pakiet | Wersja w `requirements.txt` | Podatność? | Źródło |
|--------|----------------------------|------------|--------|
| bcrypt | 4.3.0 (latest 4.x) | ✅ CZYSTE; 4.3.0 fix [GHSA-w8jq-xcqf-f792](https://github.com/advisories/GHSA-w8jq-xcqf-f792) (panic on invalid salt fixed in 4.0.1) | [pyca/bcrypt CHANGELOG](https://github.com/pyca/bcrypt/blob/main/CHANGELOG.rst) |
| Jinja2 | 3.1.6 | ✅ CZYSTE (fix CVE-2025-27516, CVE-2024-56326) | [pallets/jinja](https://github.com/pallets/jinja/security) |
| FastAPI | 0.115.x | ✅ CZYSTE | — |
| starlette | 0.52.1 | ✅ CZYSTE (fix CVE-2025-62727 i wcześniejsze) | [encode/starlette](https://github.com/encode/starlette/security) |
| python-multipart | 0.0.26 | ✅ CZYSTE (fix CVE-2026-40347) | — |
| SQLAlchemy | 2.x | ✅ CZYSTE | — |

Brak nowych CVE w obrębie auth-stack.

---

## 8. Priorytety napraw

### P1 — BLOCKER przed merge `test → main`

1. **U-01** — honor `X-Forwarded-Proto`. Albo `--proxy-headers`, albo explicit config flag `force_https_cookie=true` w prod.
2. **U-02** — SHA256+b64 pre-hash w `hash_password`/`verify_password`. Bez tego bcrypt 5.0 upgrade = DoS.
3. **U-03** — per-username brute-force counter + lockout. Min: tabela + middleware `/ui/login` POST.
4. **U-06** — atomic check-and-insert w setup wizard (`BEGIN IMMEDIATE` lub partial unique index).

### P2 — przed produkcją (post-merge)

5. **U-04** — opt-in IP/UA binding + absolute lifetime cap (30d).
6. **U-05** — CSP nonce zamiast `'unsafe-inline'` (wymaga refactor `push.html`).
7. **U-07** — dummy bcrypt call dla nieistniejącego usera (constant-time).
8. **U-12** — audit log successful/logout events.

### P3 — quality / hardening

9. **U-08** — sanitize username w log lub log tylko hash.
10. **U-09** — absolute lifetime cap (`created_at + 30d`).
11. **U-10** — `_safe_next` strict prefix check.
12. **U-11** — password strength check (blocklist common passwords).
13. **U-13..U-17** — code quality / micro-fixes.

---

## 9. Test plan po remediacji

| Finding | Test |
|---------|------|
| U-01 | curl HTTPS przez nginx proxy → cookie zawiera `Secure` flag |
| U-02 | unit test: `hash_password("x" * 100)` i `verify_password("x" * 100, h)` round-trip |
| U-03 | 6× failed POST /ui/login dla tego samego username → 7. zwraca 429/403 z lockout |
| U-04 | manual: zaloguj się z laptopa, skopiuj cookie do innej przeglądarki/IP → revoked |
| U-06 | concurrency test: 10× POST /ui/setup równolegle z różnymi username — tylko 1 user w DB |
| U-07 | timing test: 100× login z istniejącym vs nieistniejącym username, mediana czasów ±5ms |
| U-09 | unit test: mock `created_at` w przeszłości, validate_session zwraca None |

---

## 10. Podsumowanie

V5-12/V5-13/V5-14 wprowadziły **dobrze zaprojektowany** sesyjny system auth: opaque DB sessions, 256-bit entropy, HttpOnly + SameSite=strict, bcrypt 12r, password-change-revokes-all, split middleware, race-aware setup wizard. **Nie ma CRITICAL ani HIGH findings.**

6 MEDIUM findings to **standardowe niedoróbki defense-in-depth** w pierwszej iteracji auth-stacku. U-01 (cookie Secure flag) i U-02 (bcrypt 72B) muszą być naprawione przed produkcją. Reszta to gradacja "nice-to-have" → "blocker per-deploy".

Auth UI **NIE BLOKUJE** merge `test → main` w sensie funkcjonalnym, ale **wymaga 4 fixów P1** dla bezpiecznego prod-deploymentu.

---

**Powiązane dokumenty:**
- Original v0.5 audit: [audit/20260421_security_audit_docker_v0_5_test_branch.md](20260421_security_audit_docker_v0_5_test_branch.md)
- Post-remediation re-audit: [audit/20260422_security_reaudit_v0_5_post_remediation.md](20260422_security_reaudit_v0_5_post_remediation.md)
- v0.4 baseline: [audit/20260421_security_audit_docker_v0_4_pre_v0_5.md](20260421_security_audit_docker_v0_4_pre_v0_5.md)
- ROADMAP v0.5.1: [docs/ROADMAP.md#v051](../docs/ROADMAP.md)
- CHANGELOG: [CHANGELOG.md#0.5.1](../CHANGELOG.md)
