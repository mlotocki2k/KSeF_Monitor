# Szablony powiadomień (Jinja2)

KSeF Monitor wykorzystuje [Jinja2](https://jinja.palletsprojects.com/) do renderowania powiadomień. Każdy kanał (Email, Slack, Discord, Pushover, Webhook) ma własny szablon, który można dowolnie modyfikować bez zmiany kodu Python.

---

## Szybki start

Domyślne szablony są wbudowane w aplikację i działają od razu — nie musisz nic konfigurować. Jeśli chcesz dostosować format powiadomień:

1. Skopiuj domyślne szablony:
   ```bash
   # Skopiuj domyślne szablony do katalogu roboczego
   cp -r app/templates/ ./my_templates/
   ```

2. Edytuj wybrane szablony w `./my_templates/`

3. Dodaj ścieżkę do `config.json`:
   ```json
   "notifications": {
     "templates_dir": "./my_templates",
     ...
   }
   ```

4. W Docker — zamontuj volume:
   ```yaml
   volumes:
     - ./my_templates:/data/templates:ro
   ```
   i ustaw `"templates_dir": "/data/templates"` w configu.

**Wystarczy skopiować i edytować tylko te szablony, które chcesz zmienić.** Brakujące pliki automatycznie użyją wbudowanych domyślnych wersji.

---

## Pliki szablonów

| Plik | Kanał | Format | Opis |
|------|-------|--------|------|
| `pushover.txt.j2` | Pushover | plain text | Tekst do 1024 znaków |
| `email.html.j2` | Email | HTML | Pełny email z CSS |
| `slack.json.j2` | Slack | JSON (Block Kit) | Bloki Slack API |
| `discord.json.j2` | Discord | JSON (Embed) | Discord rich embed |
| `webhook.json.j2` | Webhook | JSON | Pełny payload HTTP |

---

## Zmienne dostępne w szablonach

Każdy szablon otrzymuje identyczny zestaw zmiennych:

### Dane faktury

| Zmienna | Typ | Opis | Przykład |
|---------|-----|------|---------|
| `ksef_number` | string | Numer KSeF faktury | `"1234567890-20260220-ABCDEF-AB"` |
| `invoice_number` | string | Numer faktury nadany przez wystawcę | `"FV/2026/001"` |
| `issue_date` | string | Data wystawienia (ISO 8601) | `"2026-02-20T10:30:00"` |
| `gross_amount` | float | Kwota brutto | `12345.67` |
| `net_amount` | float/None | Kwota netto (może być `None`) | `10028.19` |
| `vat_amount` | float/None | Kwota VAT (może być `None`) | `2317.48` |
| `currency` | string | Kod waluty (3 litery) | `"PLN"` |

### Strony transakcji

| Zmienna | Typ | Opis | Przykład |
|---------|-----|------|---------|
| `seller_name` | string | Nazwa sprzedawcy | `"Firma ABC Sp. z o.o."` |
| `seller_nip` | string | NIP sprzedawcy | `"1234567890"` |
| `buyer_name` | string | Nazwa nabywcy | `"Klient XYZ S.A."` |
| `buyer_nip` | string | NIP nabywcy | `"0987654321"` |
| `subject_type` | string | Typ podmiotu | `"Subject1"` lub `"Subject2"` |

> `Subject1` = faktura sprzedażowa (Ty jesteś sprzedawcą)
> `Subject2` = faktura zakupowa (Ty jesteś nabywcą)

### Metadane powiadomienia

| Zmienna | Typ | Opis | Przykład |
|---------|-----|------|---------|
| `title` | string | Tytuł powiadomienia (PL) | `"Nowa faktura sprzedażowa w KSeF"` |
| `priority` | int | Poziom priorytetu (-2 do 2) | `0` |
| `priority_emoji` | string | Emoji dla priorytetu | `"📋"` |
| `priority_name` | string | Nazwa priorytetu (EN) | `"normal"` |
| `priority_color` | string | Kolor CSS hex | `"#36a64f"` |
| `priority_color_int` | int | Kolor jako integer (Discord) | `3447003` |
| `timestamp` | string | Timestamp ISO | `"2026-02-20T10:30:00"` |
| `url` | string/None | Link do KSeF (opcjonalny) | `None` |

---

## Filtry Jinja2

Oprócz [wbudowanych filtrów Jinja2](https://jinja.palletsprojects.com/en/3.1.x/templates/#builtin-filters) dostępne są filtry dedykowane:

### `money` — kwota z walutą (format polski)

Formatuje liczbę zgodnie z polskimi normami: przecinek jako separator dziesiętny, spacja jako separator tysięcy, z kodem waluty.

```jinja2
{{ gross_amount | money }}           → 12 345,67 PLN
{{ gross_amount | money("EUR") }}    → 12 345,67 EUR
{{ 1000000.5 | money }}              → 1 000 000,50 PLN
{{ 0.99 | money }}                   → 0,99 PLN
```

### `money_raw` — kwota bez waluty

Jak `money`, ale bez kodu waluty na końcu. Przydatne gdy chcesz dodać walutę osobno.

```jinja2
{{ gross_amount | money_raw }}       → 12 345,67
{{ gross_amount | money_raw }} {{ currency }}  → 12 345,67 PLN
```

### `date` — formatowanie daty

Parsuje datę ISO 8601 i formatuje ją wg podanego wzorca ([strftime](https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior)).

```jinja2
{{ issue_date | date }}                     → 2026-02-20 10:30:00
{{ issue_date | date("%d.%m.%Y") }}         → 20.02.2026
{{ issue_date | date("%d %B %Y") }}         → 20 February 2026
{{ issue_date | date("%H:%M") }}            → 10:30
```

### `json_escape` — escapowanie JSON

Escapuje znaki specjalne (cudzysłowy, backslashe, znaki kontrolne) do bezpiecznego użycia wewnątrz stringów JSON. **Wymagany w szablonach JSON** (Slack, Discord, Webhook) dla pól tekstowych.

```jinja2
{{ seller_name | json_escape }}
{# Firma "Specjalna" Sp. z o.o.  →  Firma \"Specjalna\" Sp. z o.o. #}
```

---

## Składnia Jinja2 — mini-przewodnik

Pełna dokumentacja: [jinja.palletsprojects.com/templates](https://jinja.palletsprojects.com/en/3.1.x/templates/)

### Wyświetlanie zmiennych

```jinja2
{{ invoice_number }}              {# zwykłe wyświetlenie #}
{{ gross_amount | money_raw }}    {# z filtrem #}
{{ net_amount | default(0, true) }}  {# wartość domyślna jeśli None #}
```

### Warunki

```jinja2
{% if subject_type == "Subject1" %}
Do: {{ buyer_name }}
{% elif subject_type == "Subject2" %}
Od: {{ seller_name }}
{% else %}
Od: {{ seller_name }}
Do: {{ buyer_name }}
{% endif %}
```

### Opcjonalne pola

```jinja2
{% if net_amount %}
Netto: {{ net_amount | money_raw }} {{ currency }}
{% endif %}

{% if url %}
<a href="{{ url }}">Zobacz w KSeF</a>
{% endif %}
```

### Komentarze

```jinja2
{# To jest komentarz — nie pojawi się w wyniku #}
```

### Filtry łańcuchowe

```jinja2
{{ seller_name | upper }}         {# FIRMA ABC SP. Z O.O. #}
{{ seller_name | truncate(20) }}  {# Firma ABC Sp. z... #}
{{ ksef_number | length }}        {# 35 #}
```

> Kompletna lista wbudowanych filtrów: [Jinja2 Builtin Filters](https://jinja.palletsprojects.com/en/3.1.x/templates/#builtin-filters)

---

## Przykłady modyfikacji

### 1. Dodanie kwoty netto i VAT do Pushover

Domyślny `pushover.txt.j2` pokazuje tylko kwotę brutto. Aby dodać netto i VAT:

```jinja2
{% if subject_type == "Subject1" -%}
Do: {{ buyer_name }} - NIP {{ buyer_nip }}
{% elif subject_type == "Subject2" -%}
Od: {{ seller_name }} - NIP {{ seller_nip }}
{% else -%}
Od: {{ seller_name }} - NIP {{ seller_nip }}
Do: {{ buyer_name }} - NIP {{ buyer_nip }}
{% endif -%}
Nr Faktury: {{ invoice_number }}
Data: {{ issue_date | date("%d.%m.%Y %H:%M") }}
Brutto: {{ gross_amount | money }}
{% if net_amount -%}
Netto: {{ net_amount | money }}
{% endif -%}
{% if vat_amount -%}
VAT: {{ vat_amount | money }}
{% endif -%}
KSeF: {{ ksef_number }}
```

### 2. Email z polskim formatowaniem daty

W `email.html.j2` zmień linię z datą:

```html
<!-- Przed -->
<p><span class="field-label">Data:</span> {{ issue_date | date }}</p>

<!-- Po -->
<p><span class="field-label">Data wystawienia:</span> {{ issue_date | date("%d.%m.%Y godz. %H:%M") }}</p>
```

### 3. Webhook z dodatkowymi polami

W `webhook.json.j2` dodaj własne pola do obiektu `invoice`:

```json
"invoice": {
    "ksef_number": "{{ ksef_number | json_escape }}",
    "invoice_number": "{{ invoice_number | json_escape }}",
    "issue_date": "{{ issue_date }}",
    "issue_date_formatted": "{{ issue_date | date('%d.%m.%Y') }}",
    "gross_amount": {{ gross_amount | default(0, true) }},
    "gross_amount_formatted": "{{ gross_amount | money }}",
    "net_amount": {{ net_amount | default(0, true) }},
    "vat_amount": {{ vat_amount | default(0, true) }},
    "currency": "{{ currency }}",
    "seller": {
        "name": "{{ seller_name | json_escape }}",
        "nip": "{{ seller_nip }}"
    },
    "buyer": {
        "name": "{{ buyer_name | json_escape }}",
        "nip": "{{ buyer_nip }}"
    },
    "subject_type": "{{ subject_type }}",
    "is_purchase": {{ "true" if subject_type == "Subject2" else "false" }}
}
```

### 4. Discord z polami embed zamiast opisu

Zamień opis tekstowy na [pola embed](https://discord.com/developers/docs/resources/message#embed-object-embed-field-structure):

```json
{
    "title": "{{ title | json_escape }}",
    "color": {{ priority_color_int }},
    "fields": [
        {
            "name": "Kontrahent",
            "value": "{% if subject_type == 'Subject1' %}{{ buyer_name | json_escape }}{% else %}{{ seller_name | json_escape }}{% endif %}",
            "inline": true
        },
        {
            "name": "NIP",
            "value": "{% if subject_type == 'Subject1' %}{{ buyer_nip }}{% else %}{{ seller_nip }}{% endif %}",
            "inline": true
        },
        {
            "name": "Kwota brutto",
            "value": "{{ gross_amount | money_raw }} {{ currency }}",
            "inline": true
        },
        {
            "name": "Nr faktury",
            "value": "{{ invoice_number | json_escape }}",
            "inline": true
        },
        {
            "name": "Data",
            "value": "{{ issue_date | date('%d.%m.%Y') }}",
            "inline": true
        },
        {
            "name": "KSeF",
            "value": "{{ ksef_number | json_escape }}",
            "inline": false
        }
    ],
    "timestamp": "{{ timestamp }}",
    "footer": {
        "text": "KSeF Invoice Monitor"
    }
    {% if url %}
    ,"url": "{{ url | json_escape }}"
    {% endif %}
}
```

### 5. Slack z sekcjami i dividerami

```json
{
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "{{ priority_emoji }} {{ title | json_escape }}"
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": "*{% if subject_type == 'Subject1' %}Nabywca{% else %}Sprzedawca{% endif %}:*\n{% if subject_type == 'Subject1' %}{{ buyer_name | json_escape }}{% else %}{{ seller_name | json_escape }}{% endif %}"
                },
                {
                    "type": "mrkdwn",
                    "text": "*NIP:*\n{% if subject_type == 'Subject1' %}{{ buyer_nip }}{% else %}{{ seller_nip }}{% endif %}"
                }
            ]
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": "*Brutto:*\n{{ gross_amount | money_raw }} {{ currency }}"
                },
                {
                    "type": "mrkdwn",
                    "text": "*Data:*\n{{ issue_date | date('%d.%m.%Y') }}"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Nr faktury: {{ invoice_number | json_escape }} | KSeF: {{ ksef_number | json_escape }}"
                }
            ]
        }
        {% if url %}
        ,{
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": { "type": "plain_text", "text": "Zobacz w KSeF" },
                    "url": "{{ url | json_escape }}"
                }
            ]
        }
        {% endif %}
    ],
    "attachments": [
        {
            "color": "{{ priority_color }}",
            "fallback": "{{ title | json_escape }}"
        }
    ]
}
```

---

## Uwagi techniczne

### Autoescape HTML

Szablon `email.html.j2` ma włączony automatyczny [autoescape](https://jinja.palletsprojects.com/en/3.1.x/api/#autoescaping). Znaki `<`, `>`, `&`, `"` w zmiennych są automatycznie zamieniane na encje HTML. Szablony `.json.j2` i `.txt.j2` **nie mają** autoescapingu.

### Szablony JSON — ważne

W szablonach JSON (`slack.json.j2`, `discord.json.j2`, `webhook.json.j2`):

- **Zawsze** używaj `| json_escape` dla pól tekstowych (nazwy firm mogą zawierać `"`)
- Dla wartości `None` użyj `| default(0, true)` — sam `| default(0)` **nie** zadziała, bo Jinja2 `default` domyślnie obsługuje tylko zmienne niezdefiniowane, nie `None`
- Wynik szablonu musi być poprawnym JSON — błąd parsowania spowoduje fallback na plain text

### Whitespace control

Użycie `-%}` zamiast `%}` usuwa białe znaki po tagu. Jest to istotne w szablonach plain text (Pushover), żeby nie mieć pustych linii:

```jinja2
{% if condition -%}     {# usuwa newline po tagu #}
Tekst
{% endif -%}
```

Dokumentacja: [Jinja2 Whitespace Control](https://jinja.palletsprojects.com/en/3.1.x/templates/#whitespace-control)

### Fallback przy błędach

Jeśli renderowanie szablonu się nie powiedzie (błąd składni, brakujący plik), system automatycznie wyśle powiadomienie w formacie plain text (identycznym z domyślnym Pushover). Błąd zostanie zalogowany.

### Które powiadomienia używają szablonów?

| Typ powiadomienia | Szablon? | Opis |
|---|---|---|
| Nowa faktura | Tak | Pełne dane faktury przez Jinja2 |
| Błąd | Nie | Prosty tekst: `"Error occurred: ..."` |
| Test połączenia | Nie | Stały tekst: `"Test notification - ... configured correctly!"` |
| Start/Stop monitora | Nie | Stałe komunikaty (hardcoded) |

---

## Testowanie szablonów

### Szybki test w terminalu

```bash
python3 -c "
from app.template_renderer import TemplateRenderer
import json

r = TemplateRenderer()  # lub TemplateRenderer('./my_templates')

context = {
    'ksef_number': 'TEST-20260220-ABCDEF-AB',
    'invoice_number': 'FV/2026/001',
    'issue_date': '2026-02-20T10:30:00',
    'gross_amount': 12345.67,
    'net_amount': 10028.19,
    'vat_amount': 2317.48,
    'currency': 'PLN',
    'seller_name': 'Firma ABC Sp. z o.o.',
    'seller_nip': '1234567890',
    'buyer_name': 'Klient XYZ S.A.',
    'buyer_nip': '0987654321',
    'subject_type': 'Subject1',
    'title': 'Nowa faktura sprzedażowa w KSeF',
    'priority': 0,
    'priority_emoji': '📋',
    'priority_name': 'normal',
    'priority_color': '#36a64f',
    'priority_color_int': 3447003,
    'timestamp': '2026-02-20T10:30:00',
    'url': None,
}

# Renderuj wybrany kanał
for channel in ['pushover', 'email', 'slack', 'discord', 'webhook']:
    result = r.render(channel, context)
    if channel in ('slack', 'discord', 'webhook'):
        json.loads(result)  # walidacja JSON
    print(f'{channel}: OK ({len(result)} chars)')
"
```

### Walidacja JSON szablonów

```bash
python3 -c "
from app.template_renderer import TemplateRenderer
import json

r = TemplateRenderer('./my_templates')  # Twój katalog

context = {
    'ksef_number': 'X', 'invoice_number': 'Y',
    'issue_date': '2026-01-01', 'gross_amount': 100.0,
    'net_amount': None, 'vat_amount': None, 'currency': 'PLN',
    'seller_name': 'Firma \"Test\"',  # celowo cudzysłowy
    'seller_nip': '111', 'buyer_name': 'Buyer', 'buyer_nip': '222',
    'subject_type': 'Subject2', 'title': 'Test', 'priority': 0,
    'priority_emoji': '📋', 'priority_name': 'normal',
    'priority_color': '#36a64f', 'priority_color_int': 3447003,
    'timestamp': '2026-01-01T00:00:00', 'url': 'https://example.com',
}

for ch in ['slack', 'discord', 'webhook']:
    result = r.render(ch, context)
    try:
        json.loads(result)
        print(f'{ch}: valid JSON')
    except json.JSONDecodeError as e:
        print(f'{ch}: INVALID JSON - {e}')
        print(result)
"
```

---

## Odnośniki

- [Jinja2 — dokumentacja](https://jinja.palletsprojects.com/en/3.1.x/)
- [Jinja2 — składnia szablonów](https://jinja.palletsprojects.com/en/3.1.x/templates/)
- [Jinja2 — wbudowane filtry](https://jinja.palletsprojects.com/en/3.1.x/templates/#builtin-filters)
- [Jinja2 — whitespace control](https://jinja.palletsprojects.com/en/3.1.x/templates/#whitespace-control)
- [Jinja2 — autoescape](https://jinja.palletsprojects.com/en/3.1.x/api/#autoescaping)
- [Python strftime](https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior) — kody formatowania daty
- [Slack Block Kit Builder](https://app.slack.com/block-kit-builder) — wizualny edytor bloków Slack
- [Discord Embed Visualizer](https://autocode.com/tools/discord/embed-builder/) — podgląd embeds Discord
