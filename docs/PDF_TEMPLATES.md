# Custom Invoice PDF Templates

Customize the visual appearance of generated invoice PDFs using HTML/CSS templates.

**New in v0.3** - Invoice PDFs are now rendered from a Jinja2 HTML/CSS template via xhtml2pdf,
with automatic fallback to the direct ReportLab generator.

## How It Works

```
Invoice XML (KSeF) -> InvoiceXMLParser -> invoice_data dict
                                              |
                              Jinja2: invoice_pdf.html.j2 + context -> HTML
                                              |
                              xhtml2pdf: HTML -> PDF

                     (fallback if xhtml2pdf unavailable: ReportLab generator)
```

## Quick Start

### 1. Copy the default template

```bash
# Create local directory for custom templates
mkdir -p pdf_templates

# Copy built-in template
cp app/templates/invoice_pdf.html.j2 pdf_templates/
```

### 2. Edit the template

```bash
nano pdf_templates/invoice_pdf.html.j2
```

### 3. Configure

In `config.json`:
```json
{
  "storage": {
    "save_pdf": true,
    "pdf_templates_dir": "/data/pdf_templates"
  }
}
```

### 4. Mount in Docker

In `docker-compose.yml`:
```yaml
volumes:
  - ./pdf_templates:/data/pdf_templates:ro
```

### 5. Restart

```bash
docker-compose restart
```

## Template Variables

The template receives the full parsed invoice data from `InvoiceXMLParser`:

### `header` (dict)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `rodzaj` | str | Invoice type code | `"VAT"`, `"KOR"`, `"ZAL"` |
| `kod_waluty` | str | Currency code | `"PLN"` |
| `p2` | str | Invoice number | `"FV/2026/02/001"` |
| `p1` | str | Issue date | `"2026-02-18"` |
| `p1m` | str | Place of issue | `"Warszawa"` |
| `p6` | str | Delivery/service date | `"2026-02-15"` |
| `p6_od` | str | Invoice period from | `"2026-02-01"` |
| `p6_do` | str | Invoice period to | `"2026-02-28"` |
| `p15` | str | Total amount due | `"30135.00"` |
| `kod_formularza` | str | Form code | `"FA"` |
| `wariant` | str | Form variant | `"3"` |
| `data_wytworzenia` | str | Creation timestamp | `"2026-02-18T10:30:00"` |
| `kurs_waluty_z` | str | Exchange rate | `"4.5678"` |

### `seller` / `buyer` (dict)

| Field | Type | Description |
|-------|------|-------------|
| `nip` | str | Tax ID (NIP) |
| `nazwa` | str | Company name |
| `kod_kraju` | str | Country code |
| `adres_l1` | str | Address line 1 |
| `adres_l2` | str | Address line 2 |
| `email` | str | Email address |
| `telefon` | str | Phone number |
| `kod_ue` | str | EU country code |
| `nr_vat_ue` | str | EU VAT number |

### `items` (list of dict)

Each item in the list:

| Field | Type | Description |
|-------|------|-------------|
| `nr` | str | Line number |
| `p7` | str | Product/service name |
| `p8a` | str | Unit of measure |
| `p8b` | str | Quantity |
| `p9a` | str | Unit price (net) |
| `p9b` | str | Unit price (gross) |
| `p10` | str | Discount amount |
| `p11` | str | Net value |
| `p11a` | str | Gross value |
| `p11vat` | str | VAT amount |
| `p12` | str | VAT rate code |
| `indeks` | str | Product index |
| `pkwiu` | str | PKWiU code |
| `gtu` | str | GTU code |

### `vat_rows` (list of dict)

Pre-filtered VAT summary rows (only rows with data):

| Field | Type | Description |
|-------|------|-------------|
| `label` | str | VAT rate label (e.g., `"22% lub 23%"`) |
| `net` | str | Net amount |
| `vat` | str | VAT amount |

### `payment` (dict)

| Field | Type | Description |
|-------|------|-------------|
| `forma` | str | Payment method code |
| `zaplacono` | str | Paid flag (`"1"` = yes) |
| `data_zaplaty` | str | Payment date |
| `terminy` | list | Payment terms |
| `rachunki` | list | Bank accounts |
| `rachunki_faktora` | list | Factor bank accounts |
| `zaplaty_czesciowe` | list | Partial payments |
| `skonto_warunki` | str | Discount conditions |
| `skonto_wysokosc` | str | Discount amount |

### `annotations` (dict)

| Field | Value | Description |
|-------|-------|-------------|
| `p16` | `"1"`/`"2"` | Cash method |
| `p17` | `"1"`/`"2"` | Self-billing |
| `p18` | `"1"`/`"2"` | Reverse charge |
| `p18a` | `"1"`/`"2"` | Split payment |
| `p19` | `"1"`/`"2"` | Tax exemption |
| `p19a` | str | Exemption: law reference |
| `p19b` | str | Exemption: EU directive |
| `p19c` | str | Exemption: other basis |

### Metadata variables

| Variable | Type | Description |
|----------|------|-------------|
| `ksef_number` | str | KSeF reference number |
| `qr_code_data_uri` | str | QR Code as `data:image/png;base64,...` |
| `invoice_type_title` | str | Resolved title (e.g., "Faktura VAT") |
| `total_label` | str | Total amount label |
| `generation_stamp` | str | Generation timestamp string |
| `has_col` | dict | Which optional item columns have data |
| `payment_methods` | dict | Payment code -> Polish name mapping |
| `vat_rate_labels` | dict | VAT code -> display label mapping |
| `font_paths` | dict | Font file paths (`regular`, `bold`) |

## Custom Jinja2 Filters

| Filter | Usage | Output |
|--------|-------|--------|
| `fmt_amt` | `{{ "24000.00" \| fmt_amt }}` | `24 000,00` |
| `vat_label` | `{{ "23" \| vat_label }}` | `23%` |
| `payment_method` | `{{ "6" \| payment_method }}` | `Przelew` |

## CSS Customization

### Change colors

```css
/* Header background for tables */
.items-table th { background-color: #3498db; color: white; }
.vat-table th { background-color: #3498db; color: white; }

/* KSeF branding */
.ksef-branding { color: #2c3e50; }
.ksef-e { color: #e74c3c; }
```

### Change fonts

```css
@font-face {
    font-family: "CustomFont";
    src: url("/path/to/your/font.ttf");
}
body { font-family: "CustomFont", sans-serif; }
```

### Add company logo

```html
<!-- Add before the KSeF branding section -->
<img src="/data/pdf_templates/logo.png" style="width: 40mm; float: right;" />
```

### Change page margins

```css
@page {
    size: A4;
    margin: 20mm 15mm 20mm 15mm;  /* top right bottom left */
}
```

## Fallback Behavior

The system uses a graceful fallback chain:

1. **Custom template** (`pdf_templates_dir/invoice_pdf.html.j2`) - if exists
2. **Built-in template** (`app/templates/invoice_pdf.html.j2`) - default
3. **ReportLab generator** (`InvoicePDFGenerator`) - if xhtml2pdf fails or is unavailable

This means:
- Existing installations work without any config changes
- If `xhtml2pdf` is not installed, PDFs are generated with ReportLab (previous behavior)
- If a custom template has errors, the system falls back to ReportLab with a warning log

## Testing

### Generate a test PDF from template

```bash
python examples/test_template_pdf.py
```

This creates `examples/test_output_template.pdf` which you can compare with the ReportLab version:
```bash
python examples/test_dummy_pdf.py     # -> test_output_przelew.pdf (ReportLab)
python examples/test_template_pdf.py  # -> test_output_template.pdf (xhtml2pdf)
```

### Test inside Docker

```bash
docker-compose run --rm ksef-monitor python3 -c "
from app.invoice_pdf_template import InvoicePDFTemplateRenderer, XHTML2PDF_AVAILABLE
print(f'xhtml2pdf available: {XHTML2PDF_AVAILABLE}')
if XHTML2PDF_AVAILABLE:
    renderer = InvoicePDFTemplateRenderer()
    print('Template renderer initialized successfully')
"
```

## xhtml2pdf CSS Support

xhtml2pdf supports CSS 2.1 with some CSS3 extensions. Key supported features:

- `@page` directive (size, margins)
- `@font-face` for custom fonts (TTF)
- `table`, `border`, `padding`, `margin`
- `color`, `background-color`, `font-size`, `font-weight`
- `text-align`, `vertical-align`
- `width`, `height` (px, mm, pt, %)
- `border-collapse`

**Not supported**: flexbox, grid, CSS3 selectors, media queries.

Use `table` layout for all structural elements (already done in the default template).

## File Structure

```
ksef-invoice-monitor/
├── app/
│   ├── invoice_pdf_template.py      # Template renderer class
│   └── templates/
│       └── invoice_pdf.html.j2      # Built-in default template
├── pdf_templates/                    # Your custom templates (optional)
│   └── invoice_pdf.html.j2          # Your modified template
└── config.json
    └── storage.pdf_templates_dir    # Points to /data/pdf_templates
```

## Dependencies

| Package | Purpose | Size |
|---------|---------|------|
| `xhtml2pdf` | HTML/CSS to PDF conversion | ~2MB (pure Python) |
| `reportlab` | PDF engine (used by xhtml2pdf internally) | Already installed |
| `Jinja2` | Template engine | Already installed |
| `qrcode` | QR Code generation | Already installed |
