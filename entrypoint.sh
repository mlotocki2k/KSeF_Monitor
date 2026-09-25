#!/bin/sh
set -e

SHIPPED_HASHES=/app/app/templates/shipped_defaults.sha256

# Copy one bundled template into /data. An existing copy is replaced only when
# it is byte-identical to a released default (listed in $SHIPPED_HASHES) — so
# fixes to the defaults reach existing installs, while edited copies are kept.
seed_one() {
    src=$1
    dst=$2
    name=$(basename "$src")
    if [ -L "$dst" ]; then
        echo "entrypoint: $dst is a symlink — not touching it"
        return 0
    fi
    new=$(sha256sum "$src" | cut -d' ' -f1)
    if [ ! -e "$dst" ]; then
        cp "$src" "$dst"
        return 0
    fi
    cur=$(sha256sum "$dst" | cut -d' ' -f1)
    [ "$cur" = "$new" ] && return 0
    if grep -q "^$cur  $name\$" "$SHIPPED_HASHES" 2>/dev/null; then
        cp "$src" "$dst"
        echo "entrypoint: updated $dst to the current default"
    else
        echo "entrypoint: $dst differs from the bundled default (customized) — left unchanged; compare with $src"
    fi
}

seed_templates() {
    mkdir -p /data/templates /data/pdf_templates
    for f in /app/app/templates/*.j2; do
        fname=$(basename "$f")
        if [ "$fname" = "invoice_pdf.html.j2" ]; then
            seed_one "$f" "/data/pdf_templates/$fname" || true
        else
            seed_one "$f" "/data/templates/$fname" || true
        fi
    done
}

# Internal: template seeding re-invoked as the unprivileged user (see below).
if [ "$1" = "--seed-templates" ]; then
    seed_templates
    exit 0
fi

# If we're not running as root, skip the UID/chown dance — we already have
# the host user's identity (rootless Docker, Podman rootless, userns-remap).
CURRENT_UID=$(id -u)
if [ "$CURRENT_UID" != "0" ]; then
    echo "entrypoint: running as non-root (UID=$CURRENT_UID) — rootless mode"

    # Best-effort template seeding (user owns /data, no gosu needed).
    seed_templates 2>/dev/null || true

    umask 077
    exec python -u main.py
fi

# Detect host user's UID/GID from /data mount
DATA_UID=$(stat -c %u /data)
DATA_GID=$(stat -c %g /data)

# Adjust ksef user to match host owner
if [ "$DATA_UID" != "0" ]; then
    usermod -u "$DATA_UID" ksef 2>/dev/null || true
    groupmod -g "$DATA_GID" ksef 2>/dev/null || true
fi

# Fix ownership to match host user (chown -R without -L does not follow symlinks)
chown -R "$DATA_UID:$DATA_GID" /data 2>/dev/null || true
chmod -R u+rwX /data 2>/dev/null || true

# Copy default templates as the unprivileged user — /data content is written
# by the app, so root must not follow links planted there.
gosu ksef /entrypoint.sh --seed-templates || true

# Restrict file creation permissions (owner-only)
umask 077

# Drop privileges to ksef user (now has host user's UID)
exec gosu ksef python -u main.py
