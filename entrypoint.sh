#!/bin/sh
set -e

# Fix ownership of /data for bind mounts (runs as root)
chown -R ksef:ksef /data 2>/dev/null || true
chmod -R u+rwX /data 2>/dev/null || true

# Copy default notification templates (skip existing files)
mkdir -p /data/templates
for f in /app/app/templates/*.j2; do
    fname=$(basename "$f")
    # Skip PDF template — goes to separate dir
    [ "$fname" = "invoice_pdf.html.j2" ] && continue
    [ ! -f "/data/templates/$fname" ] && cp "$f" "/data/templates/$fname"
done

# Copy default PDF template
mkdir -p /data/pdf_templates
[ ! -f "/data/pdf_templates/invoice_pdf.html.j2" ] && \
    cp /app/app/templates/invoice_pdf.html.j2 /data/pdf_templates/

# Fix ownership of newly created files
chown -R ksef:ksef /data 2>/dev/null || true
chmod -R u+rwX /data 2>/dev/null || true

# Drop privileges to ksef user and exec the main process
exec gosu ksef python -u main.py
