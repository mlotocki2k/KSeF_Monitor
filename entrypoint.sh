#!/bin/sh
# Ensure /data is writable by ksef user when bind-mounted from host
# Runs as root, then drops privileges via exec gosu/su-exec or USER

# Fix ownership only if /data is owned by root (bind mount override)
if [ "$(stat -c '%u' /data 2>/dev/null)" = "0" ]; then
    chown -R ksef:ksef /data
fi

# Drop to ksef user and exec the main process
exec su -s /bin/sh ksef -c "python -u main.py"
