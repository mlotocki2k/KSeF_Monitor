# Logowanie certyfikatem (XAdES) — KSeF Monitor

Od **v0.6** monitor obsługuje uwierzytelnianie do KSeF certyfikatem (podpis XAdES)
jako alternatywę dla tokenu KSeF.

Logowanie certyfikatem polega na podpisaniu dokumentu `AuthTokenRequest` podpisem
elektronicznym i wysłaniu go do endpointu `POST /auth/xades-signature`. Pozwala to
logować się **kwalifikowanym podpisem/pieczęcią** lub **certyfikatem KSeF** zamiast
tokenu wygenerowanego w portalu KSeF.

## Jak to działa

Flow (zgodny z [uwierzytelnianie.md](https://github.com/CIRFMF/ksef-api/blob/main/uwierzytelnianie.md)):

1. `POST /auth/challenge` → `challenge`
2. Budowa dokumentu `AuthTokenRequest` (schemat auth v2-1, namespace
   `http://ksef.mf.gov.pl/auth/token/2.1`) z `Challenge`, `ContextIdentifier/Nip`
   oraz `SubjectIdentifierType`.
3. Podpis dokumentu w formacie **XAdES-BES, enveloped**:
   - podpis: `rsa-sha256` (klucz min. 2048-bit) lub `ecdsa-sha256` (krzywa min. 256-bit),
     dobierany automatycznie do typu klucza w PKCS#12
   - kanonizacja: **inclusive C14N 1.0** — referencje `SignedProperties` i `KeyInfo` nie mają
     `<ds:Transforms>`, więc KSeF liczy ich skróty algorytmem domyślnym wg XMLDSig;
     exc-c14n kończy się błędem `9105 "Nieprawidłowy podpis"`
   - digest: `sha256`
4. `POST /auth/xades-signature` (`Content-Type: application/xml`) z podpisanym XML
   → `referenceNumber` + `authenticationToken`.
5. Polling `GET /auth/{referenceNumber}` (jak przy logowaniu tokenem;
   `authenticationMethodInfo.category = "XadesSignature"`).
6. `POST /auth/token/redeem` → `accessToken` + `refreshToken`.

Kroki 1, 5 i 6 są współdzielone z logowaniem tokenem. Logika podpisu znajduje się
w [`app/xades_signer.py`](../app/xades_signer.py), a integracja z klientem w
[`app/ksef_client.py`](../app/ksef_client.py) (`_authenticate_certificate_flow`,
`_authenticate_with_xades`).

## Konfiguracja

W sekcji `ksef` pliku `config.json`:

```json
{
  "ksef": {
    "environment": "test",
    "nip": "1234567890",
    "auth_method": "certificate",
    "certificate": {
      "path": "/data/certs/ksef.p12",
      "subject_identifier_type": "certificateSubject"
    }
  }
}
```

| Pole | Wymagane | Opis |
|------|----------|------|
| `ksef.auth_method` | nie (domyślnie `"token"`) | `"token"` lub `"certificate"` |
| `ksef.certificate.path` | tak (gdy `auth_method="certificate"`) | ścieżka do pliku `.p12`/`.pfx` (PKCS#12) |
| `ksef.certificate.password` | nie | hasło do PKCS#12 — **zalecane** przez sekret, nie w configu |
| `ksef.certificate.subject_identifier_type` | nie (domyślnie `"certificateSubject"`) | `"certificateSubject"` lub `"certificateFingerprint"` |

Przy `auth_method="certificate"` pole `ksef.token` **nie jest wymagane**.

## Hasło do certyfikatu (sekrety)

Hasła do PKCS#12 **nie trzymaj w `config.json`**. Podaj je przez zmienną
środowiskową lub Docker secret — analogicznie do `KSEF_TOKEN`:

```bash
# zmienna środowiskowa
KSEF_CERT_PASSWORD=twoje-haslo

# Docker secret (plik /run/secrets/ksef_cert_password)
```

Wartość jest wstrzykiwana do `ksef.certificate.password` przez
[`SecretsManager`](../app/secrets_manager.py). Jeśli hasło jest w `config.json`,
monitor zaloguje ostrzeżenie.

## Certyfikat (plik .p12/.pfx)

- Format: **PKCS#12** (`.p12` lub `.pfx`) zawierający klucz prywatny + certyfikat.
- Klucz: **RSA min. 2048-bit** lub **ECDSA min. 256-bit** (certyfikaty KSeF są EC P-256).
- Zamontuj plik do kontenera (np. wolumen `-v /host/certs:/data/certs:ro`) i wskaż
  `ksef.certificate.path`.

### Upload przez Web UI

Zamiast ręcznie kopiować plik, zalogowany użytkownik może wgrać `.p12`/`.pfx`
na stronie **`/ui/certificate`** (link „Certyfikat" w nawigacji):

- plik jest walidowany hasłem (sprawdzenie, że da się otworzyć) — **hasło nie jest
  zapisywane**, służy tylko do weryfikacji,
- po walidacji plik jest zapisywany atomowo (uprawnienia `0600`) pod
  `ksef.certificate.path`,
- strona pokazuje status (metoda logowania, ścieżka, czy plik jest obecny).

Przełączenie `auth_method` na `"certificate"` i hasło runtime
(`KSEF_CERT_PASSWORD`) konfigurujesz osobno (UI nie modyfikuje `config.json`).

## Ograniczenia / status

- **Test end-to-end wykonany 2026-07-21** na środowisku TEST certyfikatem KSeF (EC P-256):
  logowanie XAdES, pobranie metadanych i XML faktur, parser FA(3), PDF, sesje, UPO,
  eksport `/invoices/exports`, `refresh` i `revoke` — wszystko OK. Testy jednostkowe
  (`tests/test_certificate_auth.py`) pokrywają dobór algorytmu podpisu i skróty referencji
  liczone inclusive C14N.
- Uprawnienia po zalogowaniu certyfikatem: token kontekstowy z `per: ["Owner"]` — pełne
  uprawnienia właściciela (odczyt i wystawianie faktur, zarządzanie uprawnieniami),
  bez możliwości zawężenia. `accessToken` ważny 15 min, `refreshToken` 7 dni.
- Wydawanie/rotacja certyfikatów KSeF (`/certificates/*`) to osobny temat —
  nieobjęty tą funkcją.
