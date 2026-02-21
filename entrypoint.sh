#!/bin/sh
set -e

# Detect host user's UID/GID from /data mount
DATA_UID=$(stat -c %u /data)
DATA_GID=$(stat -c %g /data)

# Adjust ksef user to match host owner
if [ "$DATA_UID" != "0" ]; then
    usermod -u "$DATA_UID" ksef 2>/dev/null || true
    groupmod -g "$DATA_GID" ksef 2>/dev/null || true
fi

# Fix ownership to match host user
chown -R "$DATA_UID:$DATA_GID" /data 2>/dev/null || true
chmod -R u+rwX /data 2>/dev/null || true

# Copy default notification templates (skip existing files)
mkdir -p /data/templates
for f in /app/app/templates/*.j2; do
    fname=$(basename "$f")
    [ "$fname" = "invoice_pdf.html.j2" ] && continue
    if [ ! -f "/data/templates/$fname" ]; then
        cp "$f" "/data/templates/$fname"
    fi
done

# Copy default PDF template
mkdir -p /data/pdf_templates
if [ ! -f "/data/pdf_templates/invoice_pdf.html.j2" ]; then
    cp /app/app/templates/invoice_pdf.html.j2 /data/pdf_templates/
fi

# Fix ownership of newly created files
chown -R "$DATA_UID:$DATA_GID" /data 2>/dev/null || true
chmod -R u+rwX /data 2>/dev/null || true

# Drop privileges to ksef user (now has host user's UID)
exec gosu ksef python -u main.py
