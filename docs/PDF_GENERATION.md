# Generowanie PDF Faktur z KSeF

Moduł generowania PDF faktur z KSeF. Włączany w konfiguracji sekcją `storage`.

## Włączenie

Aby automatycznie generować PDF dla nowych faktur, ustaw w `config.json`:

```json
{
  "storage": {
    "save_pdf": true,
    "save_xml": true,
    "output_dir": "/data/invoices",
    "folder_structure": "{year}/{month}",
    "file_exists_strategy": "skip"
  }
}
```

Pliki będą zapisywane automatycznie w katalogu `output_dir` (tworzony automatycznie).
Klucz `folder_structure` pozwala organizować pliki w podfoldery wg daty/typu (patrz niżej).

---

## Przegląd

Moduł `invoice_pdf_generator` umożliwia:
1. Pobieranie XML faktury po numerze KSeF (endpoint `GET /v2/invoices/ksef/{ksefNumber}`)
2. Parsowanie XML faktury w formacie FA_VAT
3. Generowanie profesjonalnego PDF według wzoru KSeF

## Architektura

### Komponenty

```
┌─────────────────────┐
│  KSeFClient         │
│  get_invoice_xml()  │──┐
└─────────────────────┘  │
                         │ XML + metadata
                         ▼
┌─────────────────────────────────────────┐
│  InvoiceXMLParser                       │
│  - Parsuje wszystkie sekcje FA(3)       │
│  - Ekstrahuje dane sprzedawcy/nabywcy   │
│  - Przetwarza pozycje faktury           │
│  - Sumuje kwoty                         │
└─────────────────────────────────────────┘
                         │ Strukturyzowane dane
                         ▼
┌─────────────────────────────────────────┐
│  generate_invoice_pdf()                 │
│  (publiczna funkcja dispatching)        │
├─────────────────────────────────────────┤
│                                         │
│  PRIMARY: InvoicePDFTemplateRenderer    │
│  - Jinja2 HTML/CSS → xhtml2pdf          │
│  - Konfigurowalny szablon               │
│  - Podmiana szablonu przez użytkownika   │
│                                         │
│  FALLBACK: InvoicePDFGenerator          │
│  - ReportLab (programatyczny)           │
│  - Używany gdy xhtml2pdf niedostępny    │
│  - Lub gdy rendering szablonu się nie uda│
└─────────────────────────────────────────┘
                         │ PDF
                         ▼
         output_dir / folder_structure / faktura.pdf
```

### Klasy i metody

#### KSeFClient.get_invoice_xml()

```python
def get_invoice_xml(self, ksef_number: str) -> Optional[Dict]:
    """
    Pobiera XML faktury z KSeF API

    Args:
        ksef_number: Numer KSeF faktury

    Returns:
        {
            'xml_content': '<XML faktury>',
            'sha256_hash': 'hash z headera x-ms-meta-hash',
            'ksef_number': 'numer KSeF'
        }
    """
```

**Endpoint:** `GET /v2/invoices/ksef/{ksefNumber}`
**Autoryzacja:** Bearer token (access_token)
**Content-Type:** application/xml
**Header:** `x-ms-meta-hash` - SHA-256 hash faktury w base64

#### InvoiceXMLParser

```python
class InvoiceXMLParser:
    """Parser XML faktury FA_VAT"""

    def parse(self) -> Dict:
        """
        Parsuje XML i zwraca strukturyzowane dane

        Returns:
            {
                'ksef_metadata': {...},
                'invoice_header': {...},
                'seller': {...},
                'buyer': {...},
                'items': [...],
                'summary': {...},
                'payment': {...},
                'annotations': [...]
            }
        """
```

**Parsowane sekcje XML:**
- `Naglowek` - nagłówek faktury (numer, daty)
- `Podmiot1/Sprzedawca` lub `Podmiot2/Sprzedawca` - dane sprzedawcy
- `Podmiot1/Nabywca` lub `Podmiot2/Nabywca` - dane nabywcy
- `Fa/FaWiersz` - pozycje faktury (items)
- `Fa` - podsumowanie kwot
- `Platnosc` - informacje o płatności
- `Adnotacje` - uwagi dodatkowe

#### InvoicePDFGenerator

```python
class InvoicePDFGenerator:
    """Generator PDF wg wzoru KSeF"""

    def generate(self, invoice_data: Dict, output_path: str = None) -> BytesIO:
        """
        Generuje PDF z parsowanych danych

        Args:
            invoice_data: Dane z InvoiceXMLParser.parse()
            output_path: Opcjonalna ścieżka zapisu (None = BytesIO)

        Returns:
            BytesIO z zawartością PDF
        """
```

**Layout PDF:**
- Format: A4 (210mm x 297mm)
- Marginesy: 15mm
- Czcionka: DejaVu Sans (Docker/Linux), Arial (macOS), Helvetica (fallback)
- Sekcje:
  - Watermark KSeF (prawy górny róg)
  - Nagłówek faktury (tytuł, numer, daty)
  - Sprzedawca i Nabywca (obok siebie w ramkach)
  - Tabela pozycji (9 kolumn z VAT)
  - Podsumowanie kwot (netto, VAT, brutto)
  - Informacje o płatności
  - Uwagi

---

## Instalacja

Wszystkie wymagane pakiety (`reportlab`, `xhtml2pdf`, `Jinja2`, `defusedxml`) są w `requirements.txt` i instalowane automatycznie podczas budowania obrazu Docker.

### Lokalna instalacja (bez Docker)

```bash
pip install -r requirements.txt
```

### Weryfikacja

```python
python -c "import reportlab; print(f'reportlab {reportlab.Version} installed')"
python -c "from xhtml2pdf import pisa; print('xhtml2pdf OK')"
```

---

## Użycie

### Sposób 1: Skrypt testowy (CLI)

```bash
# Podstawowe użycie
python examples/test_invoice_pdf.py <numer-ksef>

# Przykład
python examples/test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB
# Wygeneruje: invoice_1234567890-20240101-ABCDEF123456-AB.pdf

# Własna nazwa pliku
python examples/test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB --output faktura_12345.pdf

# Tylko XML (bez generowania PDF)
python examples/test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB --xml-only

# Własny config
python examples/test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB --config /path/to/config.json

# Debug mode (pełne logi)
python examples/test_invoice_pdf.py 1234567890-20240101-ABCDEF123456-AB --debug
```

**Opcje CLI:**
- `-o, --output FILE` - Ścieżka wyjściowa PDF (default: invoice_<numer>.pdf)
- `-c, --config FILE` - Ścieżka do config.json (default: ./config.json)
- `--xml-only` - Tylko pobierz XML bez generowania PDF
- `--debug` - Włącz pełne logowanie debug

### Sposób 2: Programatyczne użycie

#### Przykład 1: Podstawowy

```python
from app.config_manager import ConfigManager
from app.ksef_client import KSeFClient
from app.invoice_pdf_generator import generate_invoice_pdf

# Inicjalizacja
config = ConfigManager('config.json')
client = KSeFClient(config)
client.authenticate()

# Pobierz i wygeneruj PDF
ksef_number = "1234567890-20240101-ABCDEF123456-AB"
result = client.get_invoice_xml(ksef_number)

if result:
    pdf_buffer = generate_invoice_pdf(
        xml_content=result['xml_content'],
        ksef_number=result['ksef_number'],
        output_path="faktura.pdf"
    )
    print("✓ PDF wygenerowany: faktura.pdf")
else:
    print("✗ Nie udało się pobrać faktury")
```

#### Przykład 2: Generowanie do BytesIO (bez zapisu)

```python
from app.invoice_pdf_generator import generate_invoice_pdf

# Wygeneruj do pamięci
pdf_buffer = generate_invoice_pdf(
    xml_content=result['xml_content'],
    ksef_number=result['ksef_number'],
    output_path=None  # None = zwraca BytesIO
)

# Możesz teraz wysłać przez email, API, itp.
pdf_bytes = pdf_buffer.getvalue()
print(f"PDF w pamięci: {len(pdf_bytes)} bytes")
```

#### Przykład 3: Batch processing (wiele faktur)

```python
from datetime import datetime, timedelta

# Pobierz listę faktur z ostatnich 7 dni
date_to = datetime.now()
date_from = date_to - timedelta(days=7)

invoices = client.get_invoices_metadata(
    date_from=date_from,
    date_to=date_to,
    subject_type="Subject1"
)

# Generuj PDF dla każdej faktury
for invoice in invoices:
    ksef_number = invoice.get('ksefReferenceNumber')
    invoice_number = invoice.get('invoiceNumber')

    print(f"Pobieranie: {invoice_number} ({ksef_number})")

    result = client.get_invoice_xml(ksef_number)
    if result:
        output_file = f"invoices/{invoice_number}.pdf"
        generate_invoice_pdf(
            xml_content=result['xml_content'],
            ksef_number=ksef_number,
            output_path=output_file
        )
        print(f"  ✓ Zapisano: {output_file}")
```

---

## Format numeru KSeF

### Struktura

```
NIP-YYYYMMDD-RANDOM-XX

Przykład: 1234567890-20240115-ABCDEF123456-AB
```

### Walidacja

| Część | Format | Opis | Przykład |
|-------|--------|------|----------|
| NIP | 10 cyfr | NIP podatnika | `1234567890` |
| Data | YYYYMMDD | Data w formacie ISO basic | `20240115` |
| Random | Alfanumeryk | Unikalny identyfikator | `ABCDEF123456` |
| Sufiks | 2 litery | Kod kontrolny (uppercase) | `AB` |

### Przykłady

**✅ Poprawne:**
```
1234567890-20240115-ABCDEF123456-AB
9876543210-20231201-123ABC456DEF-XY
1111111111-20240101-AAAAAA000000-ZZ
```

**❌ Niepoprawne:**
```
123456789020240115ABCDEF123456AB    # Brak myślników
12345-20240115-ABCDEF123456-AB       # NIP za krótki (5 cyfr)
1234567890-2024115-ABCDEF123456-AB   # Data niepoprawna (7 cyfr)
1234567890-20240115-ABCDEF123456-ab  # Sufiks małe litery
1234567890-20240115-ABCDEF123456     # Brak sufiksu
```

---

## Format PDF

### Specyfikacja

- **Format:** A4 (210mm x 297mm)
- **Orientacja:** Portrait (pionowa)
- **Marginesy:** 15mm wszystkie strony
- **Czcionka:** DejaVu Sans / Arial (z polskimi znakami)
- **Biblioteki:** xhtml2pdf (primary) + reportlab (fallback)

### Sekcje dokumentu

#### 1. Watermark KSeF
- Pozycja: Prawy górny róg
- Tekst: "Faktura z systemu KSeF"
- Czcionka: 8pt, szary kolor
- Cel: Identyfikacja źródła faktury

#### 2. Nagłówek faktury
- Tytuł: "FAKTURA VAT" (16pt, bold, wyśrodkowany)
- Informacje:
  - Numer faktury
  - Data wystawienia
  - Data sprzedaży

#### 3. Sprzedawca i Nabywca
- Layout: Dwie kolumny obok siebie (90mm każda)
- Ramki: Box z obramowaniem
- Zawartość każdej kolumny:
  - Tytuł: "SPRZEDAWCA" / "NABYWCA" (bold)
  - Nazwa firmy
  - NIP
  - Adres (ulica, numer budynku/lokalu)
  - Kod pocztowy i miejscowość

#### 4. Tabela pozycji faktury
- Kolumny (9 total):
  1. Lp. (10mm)
  2. Nazwa towaru/usługi (50mm)
  3. Ilość (15mm)
  4. J.m. (10mm)
  5. Cena netto (20mm)
  6. Wartość netto (20mm)
  7. VAT % (15mm)
  8. Kwota VAT (20mm)
  9. Wartość brutto (20mm)
- Nagłówek: Tło szare (#e0e0e0), bold, wyśrodkowane
- Dane: 8pt, wyrównanie według typu (tekst=left, liczby=right)
- Obramowanie: Grid 0.5pt, kolor szary

#### 5. Podsumowanie
- Pozycja: Po tabeli pozycji
- Wyrównanie: Do prawej strony
- Zawartość:
  - Wartość netto
  - VAT
  - **RAZEM DO ZAPŁATY** (bold, większa czcionka)
- Format kwot: polskie normy (`,` separator dziesiętny, spacja tysięcy) + waluta

#### 6. Płatność
- Tytuł: "PŁATNOŚĆ" (uppercase, bold)
- Informacje:
  - Termin płatności
  - Forma płatności
  - Numer konta bankowego

#### 7. Uwagi (opcjonalne)
- Tytuł: "UWAGI"
- Zawartość: Lista adnotacji z XML
- Widoczne tylko jeśli faktury zawiera uwagi

### Przykład renderowania

```
┌────────────────────────────────────────────────────┐
│                           Faktura z systemu KSeF   │
│                                                    │
│                  FAKTURA VAT                       │
│                                                    │
│  Numer faktury:      FV/2024/01/123                │
│  Data wystawienia:   2024-01-15                    │
│  Data sprzedaży:     2024-01-15                    │
│                                                    │
├────────────────────┬───────────────────────────────┤
│ SPRZEDAWCA         │ NABYWCA                       │
│ Firma XYZ Sp. z o.o│ Klient ABC SA                 │
│ NIP: 1234567890    │ NIP: 9876543210               │
│ ul. Przykładowa 1  │ ul. Testowa 99/5              │
│ 00-001 Warszawa    │ 30-001 Kraków                 │
├────────────────────┴───────────────────────────────┤
│                                                    │
│ ┌──┬──────┬────┬────┬──────┬──────┬───┬────┬────┐ │
│ │Lp│Nazwa │Ilść│J.m.│Cena  │Netto │VAT│VAT │Brt │ │
│ ├──┼──────┼────┼────┼──────┼──────┼───┼────┼────┤ │
│ │1 │Usługa│  1 │szt │100.00│100.00│23%│23.00│...│ │
│ │2 │Towar │  5 │szt │ 50.00│250.00│23%│57.50│...│ │
│ └──┴──────┴────┴────┴──────┴──────┴───┴────┴────┘ │
│                                                    │
│                     Wartość netto:     350.00 PLN  │
│                     VAT:                80.50 PLN  │
│                     RAZEM DO ZAPŁATY:  430.50 PLN  │
│                                                    │
│ PŁATNOŚĆ                                           │
│ Termin płatności:    2024-01-29                    │
│ Forma płatności:     przelew                       │
│ Numer konta:         12 3456 7890 1234 5678 9012  │
└────────────────────────────────────────────────────┘
```

---

## Troubleshooting

### ImportError: No module named 'reportlab'

**Problem:** Biblioteka reportlab nie jest zainstalowana.

**Rozwiązanie:**
```bash
pip install reportlab==4.4.10
```

### Authentication failed

**Problem:** Nie można uwierzytelnić z KSeF API.

**Możliwe przyczyny:**
1. Token KSeF wygasł lub jest niepoprawny
2. NIP w konfiguracji jest błędny
3. Brak połączenia z API KSeF

**Rozwiązanie:**
```bash
# Sprawdź config.json
cat config.json | grep -A 5 '"ksef"'

# Sprawdź token
python -c "
from app.config_manager import ConfigManager
config = ConfigManager('config.json')
print(f'Environment: {config.get(\"ksef\", \"environment\")}')
print(f'NIP: {config.get(\"ksef\", \"nip\")}')
print(f'Token: {config.get(\"ksef\", \"token\")[:10]}...')
"

# Wygeneruj nowy token w portalu KSeF
```

### Failed to fetch invoice XML

**Problem:** Nie można pobrać faktury.

**Możliwe przyczyny:**
1. Faktura nie istnieje (błędny numer KSeF)
2. Brak uprawnień do faktury
3. Faktura została usunięta
4. Rate limiting API

**Rozwiązanie:**
```bash
# Włącz debug mode
python examples/test_invoice_pdf.py <numer-ksef> --debug

# Sprawdź format numeru KSeF
python -c "
import re
num = '1234567890-20240101-ABCDEF123456-AB'
pattern = r'^\\d{10}-\\d{8}-[A-Z0-9]+-[A-Z]{2}$'
print('Valid' if re.match(pattern, num) else 'Invalid')
"

# Sprawdź czy faktura istnieje przez portal KSeF
```

### Invalid KSeF number format

**Problem:** Numer KSeF ma niepoprawny format.

**Rozwiązanie:**
```bash
# Poprawny format: NIP-YYYYMMDD-RANDOM-XX
# Przykład: 1234567890-20240101-ABCDEF123456-AB

# Niepoprawne:
# - Brak myślników
# - NIP nie ma 10 cyfr
# - Data nie ma 8 cyfr (YYYYMMDD)
# - Sufiks nie ma 2 wielkich liter
```

### XML parsing error

**Problem:** Błąd podczas parsowania XML faktury.

**Możliwe przyczyny:**
1. XML jest uszkodzony
2. Nieoczekiwany format XML (inna wersja FA)
3. Brakujące elementy w XML

**Rozwiązanie:**
```bash
# Zapisz XML i sprawdź ręcznie
python examples/test_invoice_pdf.py <numer-ksef> --xml-only

# Sprawdź poprawność XML
xmllint --noout invoice_<numer>.xml

# Jeśli problem persystuje, zgłoś issue z przykładowym XML
```

### PDF rendering issues

**Problem:** PDF wygenerowany, ale źle renderowany.

**Możliwe problemy:**
- Brakujące dane w XML (puste pola)
- Za długi tekst (przekracza szerokość kolumny)
- Specjalne znaki UTF-8

**Rozwiązanie:**
```bash
# Sprawdź wygenerowany PDF
# Jeśli problem z polskimi znakami, zgłoś issue
# Jeśli tekst wychodzi poza margines, skróć nazwę towaru w fakturze
```

---

## Ograniczenia

### Obecne ograniczenia

1. **Tylko format FA(3)**
   - Obsługiwane faktury zgodne ze schematem FA(3) v1-0E
   - Brak wsparcia dla starszych wersji schematu

2. **Brak batch processing**
   - Trzeba pobierać faktury pojedynczo
   - Brak CLI do przeglądania listy

3. **Brak cache'owania**
   - Każde wywołanie pobiera XML na nowo
   - Brak lokalnej bazy PDF-ów

### Znane problemy

1. **Długie nazwy towarów**
   - Mogą przekroczyć szerokość kolumny w ReportLab renderer
   - W szablonie HTML/CSS tekst łamie się automatycznie

2. **Polskie znaki w ReportLab (fallback)**
   - ReportLab wymaga fontu z polskimi znakami (DejaVu Sans / Arial)
   - Font jest automatycznie wykrywany na Linux, macOS, Docker

---

## Struktura folderów

Klucz `folder_structure` w sekcji `storage` pozwala organizować pliki w podfoldery:

```json
{
  "storage": {
    "folder_structure": "{year}/{month}"
  }
}
```

**Dostępne placeholdery:**

| Placeholder | Wartość | Przykład |
|---|---|---|
| `{year}` | Rok z daty wystawienia | `2026` |
| `{month}` | Miesiąc (2-cyfrowy) | `02` |
| `{day}` | Dzień (2-cyfrowy) | `27` |
| `{type}` | Typ faktury | `sprzedaz` / `zakup` |

**Przykłady:**

| Wzorzec | Wynik |
|---|---|
| `""` (domyślnie) | `/data/invoices/sprz_20260227_FV-123_2026.pdf` |
| `"{year}/{month}"` | `/data/invoices/2026/02/sprz_20260227_FV-123_2026.pdf` |
| `"{type}/{year}/{month}/{day}"` | `/data/invoices/sprzedaz/2026/02/27/sprz_20260227_FV-123_2026.pdf` |

Podfoldery tworzone automatycznie. Pusty string = płaski katalog (zachowanie domyślne).

## Nazwy plików (file_name_pattern)

Klucz `file_name_pattern` w sekcji `storage` kontroluje nazwy zapisywanych plików:

```json
{
  "storage": {
    "file_name_pattern": "{type}_{date}_{invoice_number}"
  }
}
```

**Dostępne placeholdery:**

| Placeholder | Wartość | Przykład |
|---|---|---|
| `{type}` | Typ: `sprz` / `zak` | `sprz` |
| `{date}` | Data wystawienia YYYYMMDD | `20260227` |
| `{invoice_number}` | Numer faktury (sanitized) | `FV-123_2026` |
| `{ksef}` | Pełny numer KSeF (sanitized) | `1234567890-20260227-ABC123DEF456-78` |
| `{ksef_short}` | Ostatnie 6 znaków numeru KSeF | `456-78` |
| `{seller_nip}` | NIP sprzedawcy | `9730842472` |
| `{buyer_nip}` | NIP kupującego | `1234567890` |

**Przykłady:**

| Wzorzec | Wynik (XML) |
|---|---|
| `"{type}_{date}_{invoice_number}"` (domyślnie) | `sprz_20260227_FV-123_2026.xml` |
| `"{type}_{seller_nip}_{date}_{invoice_number}"` | `sprz_9730842472_20260227_FV-123_2026.xml` |
| `"{date}_{type}_{ksef_short}"` | `20260227_sprz_456-78.xml` |

Znaki niedozwolone w systemie plików (`/\:*?"<>|`) są automatycznie zamieniane na `_`.

## Strategia zapisu plików (file_exists_strategy)

Klucz `file_exists_strategy` w sekcji `storage` kontroluje zachowanie gdy plik (XML/PDF) już istnieje:

| Strategia | Zachowanie |
|---|---|
| `"skip"` (domyślnie) | Pomija zapis, loguje INFO |
| `"rename"` | Dodaje sufiks `_1`, `_2`, ... do nazwy pliku |
| `"overwrite"` | Nadpisuje istniejący plik, loguje WARNING |

```json
{
  "storage": {
    "file_exists_strategy": "skip"
  }
}
```

---

## Realizacja i roadmap

### Zrealizowane (v0.3)

- [x] Integracja z `invoice_monitor.py` (auto-download)
- [x] Konfiguracja w `config.json` (włącz/wyłącz auto-PDF)
- [x] QR Code Type I na PDF
- [x] Katalog archiwum z konfigurowalną strukturą folderów
- [x] Konfigurowalny szablon PDF (HTML/CSS, Jinja2, xhtml2pdf)
- [x] Pełna zgodność parsera z FA(3) v1-0E
- [x] Multi-page support (ReportLab automatycznie łamie strony)

### Planowane

- [ ] Załączanie PDF do powiadomień email
- [ ] Batch download (wiele faktur naraz)
- [ ] Logo firmy w nagłówku (konfigurowalny szablon)

---

## FAQ

**Q: Czy PDF jest legalny?**
A: PDF jest generowany z oryginalnego XML z KSeF, więc zawiera te same dane co w systemie. Jest to reprezentacja wizualna, nie podpis elektroniczny. W razie kontroli oryginalny XML z KSeF ma pierwszeństwo.

**Q: Czy mogę używać PDF do księgowości?**
A: Zalecane jest używanie oryginalnego XML z KSeF. PDF może służyć do celów poglądowych lub archiwizacyjnych.

**Q: Czy PDF zawiera QR kod KSeF?**
A: Tak. QR Code Type I jest generowany automatycznie z danych faktury (NIP sprzedawcy, data, hash XML).

**Q: Czy mogę dostosować wygląd PDF?**
A: Tak. Skopiuj `app/templates/invoice_pdf.html.j2` do własnego katalogu, zmodyfikuj HTML/CSS, i wskaż ścieżkę w `storage.pdf_templates_dir`. Szczegóły: [PDF_TEMPLATES.md](PDF_TEMPLATES.md).

**Q: Czy będzie wsparcie dla innych języków?**
A: Obecnie tylko polski. W przyszłości może być możliwość wyboru języka (EN, PL).

---

## Wsparcie

**Pytania i problemy:**
- Otwórz issue na GitHub
- Dołącz logi debug (`--debug`)
- Nie załączaj faktury/XML z danymi osobowymi!

**Feature requests:**
- Zaproponuj w GitHub Issues z tagiem `enhancement`

**Dokumentacja:**
- Ten dokument: `docs/PDF_GENERATION.md`
- README główny: [README.md](../README.md)
- API KSeF: https://github.com/CIRFMF/ksef-docs

---

**Ostatnia aktualizacja:** 2026-02-27
**Wersja:** v0.3
